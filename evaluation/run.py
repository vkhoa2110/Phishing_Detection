"""Run with: python -m evaluation.run --live --out reports/url_model_ablation_v1"""
import argparse
import asyncio
from collections import Counter
import csv
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import random
import time

import httpx

from app.fusion import fuse
from app.llm_service import LLMFailure, LLMService, PROMPT_VERSION
from app.ml_service import ModelService
from app.privacy import redact
from app.schemas import InputData
from app.settings import ROOT, Settings
from app.urls import extract_urls
from .metrics import measure, paired_comparison, prediction

DATASET = Path(__file__).parent / "data/vietnamese_messages_v1.jsonl"
ARMS = ("llm_only", "llm_with_url_model")
SYSTEMS = ("url_model_only", "llm_only", "llm_with_url_model", "fusion_independent", "fusion_with_url_model")
FATAL_CODES = {"API_KEY_MISSING", "API_KEY_INVALID", "ENDPOINT_INVALID", "HTTP_400", "HTTP_401", "HTTP_402", "HTTP_403", "HTTP_404", "HTTP_429"}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_dataset(path):
    cases = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    seen_ids, seen_texts = set(), set()
    for case in cases:
        if not isinstance(case["id"], str) or not case["id"] or case["id"] in seen_ids or case["text"] in seen_texts:
            raise ValueError("Dataset contains duplicate IDs/text or invalid IDs.")
        if type(case["label"]) is not int or case["label"] not in (0, 1):
            raise ValueError("Dataset labels must be 0 or 1.")
        InputData(mode="text", text=case["text"])
        urls, invalid = extract_urls(case["text"], "text")
        if not urls or invalid or not case["rationale"].strip() or not case["category"].strip():
            raise ValueError(f"Case {case['id']} must have valid URLs, category, and label rationale.")
        seen_ids.add(case["id"])
        seen_texts.add(case["text"])
    if not cases:
        raise ValueError("Dataset is empty.")
    return cases


def prepare_manifest(out, config):
    path = out / "manifest.json"
    if path.exists():
        stored = json.loads(path.read_text(encoding="utf-8"))
        if stored["configuration"] != config:
            raise ValueError("Existing output uses a different dataset/model/prompt/configuration. Choose another --out directory.")
        return stored
    if (out / "checkpoints.jsonl").exists():
        raise ValueError("Checkpoints exist without a matching manifest.")
    stored = {"created_at": datetime.now(timezone.utc).isoformat(), "configuration": config}
    write_json(path, stored)
    return stored


def load_checkpoints(path):
    cache = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            key = (item["case_id"], item["arm"])
            if key in cache:
                raise ValueError("Duplicate checkpoint; choose an unmodified output directory.")
            cache[key] = item["result"]
    return cache


async def call_arm(service, case, urls, arm):
    # Labels, rationales and IDs are deliberately excluded from provider input.
    return await service.analyze(text=redact(case["text"])[0], mode="text", urls=urls,
                                 include_ml=arm == "llm_with_url_model", endpoint="", model="", api_key="")


def level(result):
    return result.get("verdict", {}).get("risk_level", "UNKNOWN") if result.get("status") == "ok" else "UNKNOWN"


def assemble_rows(cases, ml_results, cache):
    rows = []
    for case in cases:
        urls, invalid, ml_ms = ml_results[case["id"]]
        pending = {"status": "pending", "code": "NOT_RUN"}
        only = cache.get((case["id"], ARMS[0]), pending)
        informed = cache.get((case["id"], ARMS[1]), pending)
        ml = fuse("url", urls, {"status": "disabled"}, invalid)["risk_level"]
        levels = {"url_model_only": ml, "llm_only": level(only), "llm_with_url_model": level(informed),
                  "fusion_independent": fuse("text", urls, only, invalid)["risk_level"],
                  "fusion_with_url_model": fuse("text", urls, informed, invalid)["risk_level"]}
        # A pending LLM must not be presented as a completed hybrid experiment.
        if only["status"] == "pending":
            levels["fusion_independent"] = "UNKNOWN"
        if informed["status"] == "pending":
            levels["fusion_with_url_model"] = "UNKNOWN"
        rows.append({**case, "urls": urls, "invalid_urls": invalid, "ml_ms": ml_ms,
                     "llm_only": only, "llm_with_url_model": informed, "levels": levels})
    return rows


def summarize(rows):
    labels = [r["label"] for r in rows]
    metrics = {system: measure(labels, [r["levels"][system] for r in rows]) for system in SYSTEMS}
    complete = [r for r in rows if all(r[a]["status"] == "ok" for a in ARMS)]
    comparisons = {}
    for name, a, b in [("metadata_effect", "llm_only", "llm_with_url_model"),
                       ("fusion_effect", "llm_only", "fusion_independent"),
                       ("full_system_effect", "llm_only", "fusion_with_url_model")]:
        comparisons[name] = {"all_cases": paired_comparison(labels, [r["levels"][a] for r in rows], [r["levels"][b] for r in rows]),
                             "both_llms_successful": paired_comparison([r["label"] for r in complete], [r["levels"][a] for r in complete], [r["levels"][b] for r in complete])}
    groups = {group: {s: measure([r["label"] for r in rows if r["category"] == group],
                                [r["levels"][s] for r in rows if r["category"] == group]) for s in SYSTEMS}
              for group in sorted({r["category"] for r in rows})}
    return {"n": len(rows), "positive": sum(labels), "negative": len(rows) - sum(labels),
            "complete_pairs": len(complete), "metrics": metrics, "comparisons": comparisons,
            "by_category": groups,
            "status_counts": {a: dict(Counter(r[a]["status"] for r in rows)) for a in ARMS},
            "error_codes": {a: dict(Counter(r[a].get("code", "UNKNOWN") for r in rows if r[a]["status"] == "error")) for a in ARMS},
            "usage": {a: {key: sum(r[a].get("usage", {}).get(key, 0) for r in rows) for key in ("prompt_tokens", "completion_tokens", "total_tokens")} for a in ARMS},
            "timing": {a: {"successful_calls": sum(r[a]["status"] == "ok" for r in rows),
                            "total_elapsed_ms": sum(r[a].get("elapsed_ms", 0) for r in rows)} for a in ARMS}}


def pct(value):
    return "N/A" if value is None else f"{100 * value:.2f}%"


def export(out, manifest, rows, state):
    summary = {"run_state": state, **summarize(rows)}
    write_json(out / "summary.json", summary)
    (out / "results.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    with (out / "comparison.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "label", "category", "pair_id", *SYSTEMS, "llm_only_status", "llm_with_url_model_status"])
        writer.writeheader()
        for row in rows:
            writer.writerow({"id": row["id"], "label": row["label"], "category": row["category"], "pair_id": row.get("pair_id", ""),
                             **row["levels"], **{a + "_status": row[a]["status"] for a in ARMS}})
    lines = ["# Đánh giá ảnh hưởng của model URL", "", f"Thời điểm tạo lượt chạy (UTC): {manifest['created_at']}", "",
             f"Bộ dữ liệu: {summary['n']} mẫu, {summary['positive']} phishing / {summary['negative']} thông thường. Cặp có cả hai lượt LLM thành công: {summary['complete_pairs']}.", "",
             f"Trạng thái: {state}", "",
             "| Cấu hình | Coverage | Accuracy toàn bộ | Precision | Recall toàn bộ | F1 toàn bộ | FPR | TP/FP/TN/FN | UNKNOWN (+/-) |",
             "|---|---:|---:|---:|---:|---:|---:|---|---|"]
    for name, m in summary["metrics"].items():
        lines.append(f"| {name} | {pct(m['coverage'])} | {pct(m['accuracy'])} | {pct(m['precision'])} | {pct(m['recall'])} | {pct(m['f1'])} | {pct(m['false_positive_rate'])} | {m['tp']}/{m['fp']}/{m['tn']}/{m['fn']} | {m['unknown_positive']}/{m['unknown_negative']} |")
    lines += ["", "## Cách đọc", "",
              "- `llm_only`: LLM chỉ nhận văn bản có URL, không chạy model URL cho quyết định này và không dùng quy tắc kết hợp ML.",
              "- `llm_with_url_model`: cùng LLM/prompt/văn bản, nhận thêm điểm và ngưỡng model URL; đánh giá trước quy tắc tổng hợp.",
              "- `fusion_independent`: kết hợp model URL với chính kết quả `llm_only`, tách tác động của quy tắc tổng hợp.",
              "- `fusion_with_url_model`: kết quả ứng dụng khi model URL tham gia cả prompt và quy tắc tổng hợp.",
              "- `url_model_only`: mức cao nhất của các URL trong thông điệp, không phân tích ngữ cảnh văn bản.",
              "- HIGH/WARNING = dự đoán dương; LOW = âm; UNKNOWN/lỗi/chưa chạy = abstain. Accuracy lấy toàn bộ mẫu làm mẫu số; recall và F1 tính mẫu dương abstain là bỏ sót, không tự đổi abstain thành LOW. Precision/F1 không xác định được ghi N/A khi mẫu số bằng 0.",
              "", "## So sánh theo cặp", "",
              "| Tác động | Phạm vi | Sửa đúng | Làm sai thêm | Chênh accuracy | McNemar exact p |",
              "|---|---|---:|---:|---:|---:|"]
    for name, groups in summary["comparisons"].items():
        for population, c in groups.items():
            lines.append(f"| {name} | {population}, n={c['n']} | {c['improved']} | {c['regressed']} | {pct(c['accuracy_delta'])} | {c['mcnemar_exact_p']:.4f} |")
    lines += ["", "## Những mẫu thay đổi hoặc sai", ""]
    for row in rows:
        a, b = row["levels"]["llm_only"], row["levels"]["fusion_with_url_model"]
        if a != b or prediction(a) != row["label"] or prediction(b) != row["label"]:
            lines.append(f"- {row['id']} ({row['category']}, nhãn {row['label']}): LLM={a}, LLM+metadata={row['levels']['llm_with_url_model']}, tổng hợp={b}; URL ML={row['levels']['url_model_only']}.")
    lines += ["", "## Phạm vi và giới hạn", "",
              "Dữ liệu do người viết công cụ tự soạn trước khi chạy, chưa được người gán nhãn độc lập thẩm định. Đây là kiểm thử chẩn đoán tổng hợp, không phải test set ngoài thực tế hay đánh giá Accuracy/F1 tổng quát của model. Không dùng dữ liệu này để chọn lại ngưỡng hoặc huấn luyện.", "",
              "Mỗi mẫu có ít nhất một URL. Sáu cặp kiểm soát dùng cùng URL với hai ngữ cảnh đối lập; tách theo `pair_id` khi chia dữ liệu sau này. Nhiều URL dùng miền ví dụ, một số dùng chuỗi URL công khai và IP dành cho tài liệu; không truy cập website và không xác nhận nội dung website. Nhãn nói về yêu cầu trong thông điệp, không phải nhãn xác thực của từng website.", "",
              "LLM chạy một lần mỗi cấu hình, temperature=0.1; kết quả có thể dao động. McNemar là so sánh thăm dò trên mẫu nhỏ có các cặp kiểm soát phụ thuộc nhau, không chứng minh khả năng tổng quát. Không tự retry API; checkpoint giữ từng kết quả để chạy tiếp mà không trả phí lặp. Các lỗi API và UNKNOWN được báo riêng.", "",
              "`manifest.json` lưu hash dữ liệu, model, mã nguồn và prompt; `results.jsonl` lưu từng dự đoán, bằng chứng, token và thời gian; `summary.json` có thêm số đo theo nhóm; `comparison.csv` mở được trong bảng tính. Không lưu API key.", ""]
    (out / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return summary


async def evaluate(args):
    cases = load_dataset(args.dataset)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    settings = replace(Settings(), max_tokens=args.max_tokens, timeout_seconds=args.timeout)
    ml = ModelService(settings)
    status = ml.load()
    if not status["ready"]:
        raise ValueError(status["message"])
    if args.live and not settings.api_key.strip():
        raise ValueError("FPT_API_KEY is missing; no API requests were made.")
    source_paths = sorted((ROOT / "app").glob("*.py")) + sorted(Path(__file__).parent.glob("*.py"))
    config = {"version": 1, "dataset_sha256": digest(args.dataset), "dataset_cases": len(cases),
              "dataset_name": Path(args.dataset).name, "model_status": status,
              "model_files_sha256": {p.name: digest(p) for p in sorted(ml.path.iterdir()) if p.is_file()},
              "source_sha256": {str(p.relative_to(ROOT)): digest(p) for p in source_paths},
              "llm": {"endpoint": settings.endpoint, "model": settings.llm_model, "max_tokens": settings.max_tokens,
                      "timeout_seconds": settings.timeout_seconds, "temperature": 0.1, "top_p": 1, "top_k": 40,
                      "prompt_version": PROMPT_VERSION, "live": args.live},
              "seed": args.seed, "workers": args.workers,
              "versions": {p: importlib.metadata.version(p) for p in ("httpx", "xgboost-cpu", "numpy", "pandas", "pydantic")}}
    manifest = prepare_manifest(out, config)
    cache = load_checkpoints(out / "checkpoints.jsonl")
    valid_keys = {(c["id"], a) for c in cases for a in ARMS}
    if not cache.keys() <= valid_keys:
        raise ValueError("Checkpoint contains unknown case IDs or arms.")
    ml_results = {}
    for case in cases:
        urls, invalid = extract_urls(case["text"], "text")
        started = time.perf_counter()
        predictions = ml.predict(urls)
        if any(u["status"] != "ok" for u in predictions):
            raise ValueError(f"URL model failed for {case['id']}; evaluation stopped before LLM calls.")
        ml_results[case["id"]] = predictions, invalid, round((time.perf_counter() - started) * 1000, 2)
    state = {"live": args.live, "new_api_calls": 0, "stop_reason": "offline" if not args.live else None}
    export(out, manifest, assemble_rows(cases, ml_results, cache), state)
    print(f"Dataset: {len(cases)}; positive: {sum(c['label'] for c in cases)}; cached calls: {len(cache)}; model ready.", flush=True)
    if args.live:
        queue = asyncio.Queue()
        ordering = list(cases)
        random.Random(args.seed).shuffle(ordering)
        for index, case in enumerate(ordering):
            queue.put_nowait((index, case))
        consecutive_errors = 0
        async with httpx.AsyncClient(timeout=settings.timeout_seconds, trust_env=False) as client:
            service = LLMService(settings, client)

            async def worker():
                nonlocal consecutive_errors
                while not queue.empty() and state["stop_reason"] is None:
                    index, case = queue.get_nowait()
                    arms = ARMS if index % 2 == 0 else tuple(reversed(ARMS))
                    for arm in arms:
                        if (case["id"], arm) in cache:
                            continue
                        if state["stop_reason"] is not None:
                            break
                        if state["new_api_calls"] >= args.max_new_calls:
                            state["stop_reason"] = "call_budget_reached"
                            break
                        state["new_api_calls"] += 1
                        try:
                            result = await call_arm(service, case, ml_results[case["id"]][0], arm)
                        except LLMFailure as exc:
                            result = {"status": "error", "code": exc.code, "message": exc.message}
                        except Exception as exc:
                            # Exception messages may contain provider/request details; never serialize them.
                            result = {"status": "error", "code": "UNEXPECTED_" + type(exc).__name__}
                        cache[(case["id"], arm)] = result
                        with (out / "checkpoints.jsonl").open("a", encoding="utf-8") as file:
                            file.write(json.dumps({"case_id": case["id"], "arm": arm, "result": result}, ensure_ascii=False) + "\n")
                            file.flush()
                            os.fsync(file.fileno())
                        consecutive_errors = consecutive_errors + 1 if result["status"] == "error" else 0
                        if result.get("code") in FATAL_CODES or consecutive_errors >= 3:
                            state["stop_reason"] = result.get("code", "consecutive_errors")
                        export(out, manifest, assemble_rows(cases, ml_results, cache), state)
                        print(f"[{len(cache)}/{2 * len(cases)}] {case['id']} {arm}: {result['status']} {level(result)} {result.get('code', '')}", flush=True)
            try:
                await asyncio.gather(*(worker() for _ in range(args.workers)))
            except asyncio.CancelledError:
                state["stop_reason"] = "interrupted"
                state["completed_at"] = datetime.now(timezone.utc).isoformat()
                export(out, manifest, assemble_rows(cases, ml_results, cache), state)
                raise
    if args.live and len(cache) == 2 * len(cases):
        state["stop_reason"] = "all_calls_completed"
    state["completed_at"] = datetime.now(timezone.utc).isoformat()
    summary = export(out, manifest, assemble_rows(cases, ml_results, cache), state)
    print(json.dumps({"out": str(out), "complete_pairs": summary["complete_pairs"], "state": state}, ensure_ascii=False), flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--out", type=Path, default=Path("reports/url_model_ablation_v1"))
    parser.add_argument("--live", action="store_true", help="Send synthetic dataset text to FPT; incurs API usage.")
    parser.add_argument("--max-new-calls", type=int, default=120, help="Maximum new API attempts; cached results are never retried.")
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--workers", type=int, choices=(1, 2), default=2)
    parser.add_argument("--seed", type=int, default=20261026)
    args = parser.parse_args()
    if args.max_new_calls < 0 or args.max_tokens < 1 or args.timeout <= 0:
        parser.error("Budgets and timeout must be positive; call budget may be zero.")
    try:
        summary = asyncio.run(evaluate(args))
    except KeyboardInterrupt:
        parser.exit(130, "Evaluation interrupted; completed API responses remain checkpointed.\n")
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Evaluation stopped: {exc}\n")
    if args.live and summary["complete_pairs"] != summary["n"]:
        parser.exit(1, "Live evaluation is incomplete. Inspect summary.json before interpreting metrics.\n")


if __name__ == "__main__":
    main()
