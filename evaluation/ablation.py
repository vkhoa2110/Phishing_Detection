"""Paired Vietnamese message evaluation: LLM, URL metadata, RAG, and fusion.

Offline preparation is the default. --live explicitly enables FPT requests.
Completed responses, including failures, are never retried on resume.
"""
import argparse
import asyncio
from collections import Counter
import csv
from dataclasses import replace
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import random
import statistics
import time

import httpx

from app.fusion import POLICY_VERSION, fuse as fuse_context, fuse_legacy as fuse
from app.llm_service import (LLMFailure, LLMService, PROMPT_VERSION, RAG_PROMPT_VERSION,
                             MESSAGE_PROMPT_VERSION, MESSAGE_RAG_PROMPT_VERSION)
from app.ml_service import ModelService
from app.privacy import redact
from app.rag_service import RAGService
from app.schemas import InputData
from app.settings import ROOT, Settings
from app.urls import extract_urls
from .metrics import measure, paired_comparison, prediction
from .run import FATAL_CODES, digest, level, load_checkpoints, pct, prepare_manifest, write_json

DATASET = ROOT / "data/evaluation/vietnamese_messages_rag_v1.jsonl"
ARMS = ("llm_only", "llm_url", "llm_rag", "llm_url_rag")
SYSTEMS = ("url_model_only", *ARMS, *("fusion_" + a for a in ARMS))


def load_cases(path):
    cases = [json.loads(s) for s in Path(path).read_text(encoding="utf-8").splitlines() if s.strip()]
    ids, texts = set(), set()
    for c in cases:
        InputData(mode="text", text=c["text"])
        if (not isinstance(c["id"], str) or not c["id"] or c["id"] in ids or c["text"] in texts
                or type(c["label"]) is not int or c["label"] not in (0, 1)
                or not c["rationale"].strip() or not c["category"].strip()):
            raise ValueError("Invalid/duplicate case or label.")
        if extract_urls(c["text"], "text")[1]:
            raise ValueError("Invalid URL in " + c["id"])
        ids.add(c["id"])
        texts.add(c["text"])
    if not cases:
        raise ValueError("Empty dataset.")
    return cases


async def call_arm(service, case, prepared, arm, prompt_profile="legacy"):
    if arm not in ARMS:
        raise ValueError("Unknown arm.")
    # No ID, label, rationale, category, or annotation is sent to the provider.
    return await service.analyze(
        text=redact(case["text"])[0], mode="text", urls=prepared["urls"],
        include_ml=arm in {"llm_url", "llm_url_rag"}, endpoint="", model="", api_key="",
        prompt_profile=prompt_profile,
        rag_sources=prepared["retrieval"]["sources"] if arm in {"llm_rag", "llm_url_rag"} else None)


def assemble_rows(cases, prepared, cache, fusion_policy="legacy"):
    policy = fuse_context if fusion_policy == "separate" else fuse
    rows = []
    for c in cases:
        p = prepared[c["id"]]
        outputs = {a: cache.get((c["id"], a), {"status": "pending", "code": "NOT_RUN"}) for a in ARMS}
        levels = {a: level(outputs[a]) for a in ARMS}
        levels["url_model_only"] = fuse("url", p["urls"], {"status": "disabled"}, p["invalid_urls"])["risk_level"]
        for a, output in outputs.items():
            levels["fusion_" + a] = ("UNKNOWN" if output["status"] == "pending" else
                policy("text", p["urls"], output, p["invalid_urls"])["risk_level"])
        rows.append({**c, **p, **outputs, "has_url": bool(p["urls"]), "levels": levels})
    return rows


def metrics(rows):
    return {s: measure([r["label"] for r in rows], [r["levels"][s] for r in rows]) for s in SYSTEMS}


def summarize(rows):
    comparisons = {}
    for name, a, b in (("rag_without_url", "llm_only", "llm_rag"),
                       ("rag_with_url", "llm_url", "llm_url_rag"),
                       ("url_without_rag", "llm_only", "llm_url"),
                       ("url_with_rag", "llm_rag", "llm_url_rag"),
                       ("fusion_full", "llm_url_rag", "fusion_llm_url_rag")):
        comparisons[name] = {}
        for group, subset in (("all", rows), ("with_url", [r for r in rows if r["has_url"]]),
                              ("without_url", [r for r in rows if not r["has_url"]]),
                              ("both_successful", [r for r in rows if r[a]["status"] == "ok" and
                                  r[b.removeprefix("fusion_")]["status"] == "ok"])):
            comparisons[name][group] = paired_comparison([r["label"] for r in subset],
                [r["levels"][a] for r in subset], [r["levels"][b] for r in subset])
    timing, citations = {}, {}
    for a in ARMS:
        times = sorted(r[a]["elapsed_ms"] for r in rows if r[a]["status"] == "ok")
        timing[a] = {"n": len(times), "mean_ms": statistics.mean(times) if times else None,
                     "median_ms": statistics.median(times) if times else None,
                     "p95_ms": times[min(len(times) - 1, int(.95 * len(times)))] if times else None}
        citations[a] = {
            "actual_rag_calls": sum(bool(r[a].get("rag")) for r in rows),
            "calls_with_valid_citation": sum(bool(r[a].get("verdict", {}).get("knowledge_support")) for r in rows),
            "valid_citations": sum(len(r[a].get("verdict", {}).get("knowledge_support", [])) for r in rows),
            "invalid_citation_warnings": sum("Đã loại nguồn dẫn" in w for r in rows for w in r[a].get("warnings", []))}
    return {"n": len(rows), "positive": sum(r["label"] for r in rows),
            "complete_cases": sum(all(r[a]["status"] == "ok" for a in ARMS) for r in rows),
            "metrics": metrics(rows),
            "by_url": {k: metrics([r for r in rows if r["has_url"] == flag])
                       for k, flag in (("with_url", True), ("without_url", False))},
            "by_category": {k: metrics([r for r in rows if r["category"] == k]) for k in sorted({r["category"] for r in rows})},
            "by_injection": {k: metrics([r for r in rows if bool(r.get("prompt_injection")) == flag])
                             for k, flag in (("injection", True), ("other", False))},
            "comparisons": comparisons, "timing": timing, "citations": citations,
            "retrieval": {"status_counts": dict(Counter(r["retrieval"]["status"] for r in rows)),
                          "total_sources": sum(len(r["retrieval"]["sources"]) for r in rows),
                          "total_elapsed_ms": sum(r["retrieval"].get("elapsed_ms", 0) for r in rows)},
            "status_counts": {a: dict(Counter(r[a]["status"] for r in rows)) for a in ARMS},
            "error_codes": {a: dict(Counter(r[a].get("code", "UNKNOWN") for r in rows if r[a]["status"] == "error")) for a in ARMS},
            "usage": {a: {k: sum(r[a].get("usage", {}).get(k, 0) for r in rows)
                          for k in ("prompt_tokens", "completion_tokens", "total_tokens")} for a in ARMS}}


def table(lines, values):
    lines += ["| Cấu hình | n | Precision | Recall | F1 | Accuracy | FPR | Coverage | TP/FP/TN/FN | UNKNOWN +/- |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---|---|"]
    for a, m in values.items():
        lines.append(f"| {a} | {m['n']} | {pct(m['precision'])} | {pct(m['recall'])} | {pct(m['f1'])} | {pct(m['accuracy'])} | {pct(m['false_positive_rate'])} | {pct(m['coverage'])} | {m['tp']}/{m['fp']}/{m['tn']}/{m['fn']} | {m['unknown_positive']}/{m['unknown_negative']} |")


def export(out, manifest, rows, state):
    summary = {"run_state": state, **summarize(rows)}
    write_json(out / "summary.json", summary)
    (out / "results.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    with (out / "comparison.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "label", "category", "has_url", *SYSTEMS, *(a + "_status" for a in ARMS)])
        writer.writeheader()
        for r in rows:
            writer.writerow({**{k: r[k] for k in ("id", "label", "category", "has_url")}, **r["levels"],
                             **{a + "_status": r[a]["status"] for a in ARMS}})
    lines = ["# So sánh LLM, model URL và RAG", "", f"Tạo lúc (UTC): {manifest['created_at']}",
             f"Trạng thái: {state}", "", f"{summary['n']} mẫu mô phỏng; {summary['positive']} lừa đảo; "
             f"{summary['n'] - summary['positive']} bình thường; {summary['complete_cases']} mẫu có đủ 4 kết quả thành công.", ""]
    config = manifest["configuration"]
    lines[5] = (f"{summary['n']} mẫu; {summary['positive']} nhãn dương; {summary['n'] - summary['positive']} nhãn âm; "
                f"{summary['complete_cases']} mẫu có đủ bốn phản hồi thành công.")
    lines += [f"Prompt profile: {config.get('prompt_profile', 'legacy')}; fusion: {config.get('fusion_policy', 'legacy')}; "
              f"nhãn đã review: {bool(config.get('reviewed_gold'))}; diagnostic: {config.get('diagnostic', False)}.", ""]
    table(lines, summary["metrics"])
    for group, values in summary["by_url"].items():
        lines += ["", "## " + group, ""]
        table(lines, values)
    lines += ["", "## So sánh theo cặp", "", "| Tác động | Nhóm | Sửa đúng | Làm sai thêm | Chênh accuracy |",
              "|---|---|---:|---:|---:|"]
    for name, groups in summary["comparisons"].items():
        for group, c in groups.items():
            lines.append(f"| {name} | {group} (n={c['n']}) | {c['improved']} | {c['regressed']} | {pct(c['accuracy_delta'])} |")
    lines += ["", "## Chi phí tài nguyên và nguồn dẫn", "", "| Cấu hình | Token vào | Token ra | Tổng token | Latency trung vị (ms) | RAG thực dùng | Lượt có dẫn nguồn hợp lệ |",
              "|---|---:|---:|---:|---:|---:|---:|"]
    for a in ARMS:
        u, t, c = summary["usage"][a], summary["timing"][a], summary["citations"][a]
        lines.append(f"| {a} | {u['prompt_tokens']} | {u['completion_tokens']} | {u['total_tokens']} | {t['median_ms']} | {c['actual_rag_calls']} | {c['calls_with_valid_citation']} |")
    lines += ["", "## Giới hạn và cách đọc", "",
              "- Dữ liệu và tình trạng nhãn phải đọc cùng manifest: reviewed_gold chỉ có khi đã nộp hai phiếu review khác ID và khóa tập; CLI không xác thực danh tính con người. Lượt diagnostic dùng nhãn tự soạn không phải bằng chứng khả năng tổng quát. Có các nhóm nội dung phụ thuộc nhau.",
              "- Với fusion separate, risk_level của tin nhắn chỉ đánh giá hành vi; cảnh báo URL được giữ riêng và không tự biến thành nhãn lừa đảo của toàn bộ thông điệp. Với fusion legacy, mức ML có thể nâng kết quả tổng hợp. Hai chính sách có phạm vi đầu ra khác nhau.",
              "- Nhãn là hành vi trong tin nhắn, không xác thực danh tiếng URL. Các miền ví dụ khiến model URL lệch phân phối; phải xem riêng đánh giá PhishVN khi nhận xét chất lượng model URL.",
              "- Bốn arm là đầu ra LLM trước fusion. fusion_* kết hợp cùng đầu ra đó với model URL theo quy tắc ứng dụng đang dùng; không gọi thêm API. URL-only không xử lý mẫu không URL và trả UNKNOWN.",
              "- HIGH/WARNING là cảnh báo; LOW là âm; UNKNOWN/lỗi là abstain. Recall/F1 toàn bộ tính mẫu dương abstain là bỏ sót; accuracy chia toàn bộ n. Không chuyển UNKNOWN thành an toàn.",
              "- RAG dùng cùng snapshot truy xuất cho hai arm. Ngưỡng ML và RAG, prompt và corpus được giữ nguyên; không học hoặc chọn lại ngưỡng trên bộ này. Truy xuất rỗng dùng prompt baseline nên arm yêu cầu RAG không phải lúc nào cũng thực sự dùng nguồn.",
              "- Không URL thì không có điểm ML được đưa vào; include_ml chỉ thêm mảng rỗng. Chênh lệch hai arm ở nhóm này có thể do prompt/dao động API, không chứng minh model URL giúp ích.",
              "- Dẫn nguồn hợp lệ nghĩa là mã nguồn có trong kết quả truy xuất và đoạn trích khớp nguyên văn; chưa xác nhận quan hệ hỗ trợ giữa nguồn và lập luận. Rubric ngữ nghĩa cần người chấm độc lập.",
              f"- Mỗi arm chạy một lần, temperature=0.1, tối đa {config['llm']['max_tokens']} token; thứ tự được xáo và luân phiên. Lỗi được giữ nguyên, không retry. Thống kê cặp là thăm dò trên mẫu nhỏ, không chứng minh nhân quả hoặc khả năng tổng quát.",
              "- Token API bao gồm phần suy luận do nhà cung cấp tính. Thời gian là lượt API, chưa gồm retrieval; retrieval có lượt đầu nạp model lạnh. Không lưu khóa API.",
              "", "## Các mẫu sai hoặc abstain", ""]
    for r in rows:
        wrong = {a: r["levels"][a] for a in ARMS if prediction(r["levels"][a]) != r["label"]}
        if wrong:
            lines.append(f"- {r['id']} (nhãn {r['label']}, {r['category']}): {wrong}. "
                         f"URL={r['levels']['url_model_only']}; fusion_full={r['levels']['fusion_llm_url_rag']}.")
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


async def evaluate(args):
    profile = getattr(args, "prompt_profile", "legacy")
    fusion_policy = getattr(args, "fusion_policy", "legacy")
    if profile not in {"legacy", "message-v2"} or fusion_policy not in {"legacy", "separate"}:
        raise ValueError("Unknown prompt profile or fusion policy.")
    reviewed_path = getattr(args, "reviewed_manifest", None)
    diagnostic = getattr(args, "diagnostic", False)
    reviewed_gold = None
    if reviewed_path:
        from .review import validate_gold
        reviewed_gold = validate_gold(reviewed_path, args.dataset)
    elif profile == "message-v2" and not diagnostic:
        raise ValueError("Message-v2 benchmark requires --reviewed-manifest; use --diagnostic only for explicitly non-benchmark regression checks.")
    cases = load_cases(args.dataset)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    settings = replace(Settings(), max_tokens=args.max_tokens, timeout_seconds=args.timeout)
    ml, rag = ModelService(settings), RAGService(settings)
    ml_status, rag_status = ml.load(), rag.status()
    if not ml_status["ready"] or not rag_status["ready"]:
        raise ValueError("ML and RAG must both be ready before evaluating.")
    if args.live and not settings.api_key.strip():
        raise ValueError("FPT_API_KEY is missing; no API requests made.")
    sources = sorted((ROOT / "app").glob("*.py")) + [Path(__file__), Path(__file__).with_name("metrics.py"), Path(__file__).with_name("run.py")]
    index_path = settings.root / settings.rag_index_dir
    sources += [Path(__file__).with_name("review.py"), Path(__file__).with_name("message_data.py")]
    config = {"version": 2, "arms": list(ARMS), "dataset_sha256": digest(args.dataset),
              "dataset_name": Path(args.dataset).name, "dataset_cases": len(cases),
              "dataset_path": str(Path(args.dataset).resolve()),
              "prompt_profile": profile, "fusion_policy": fusion_policy,
              "fusion_version": POLICY_VERSION if fusion_policy == "separate" else "max-alarm-1.0",
              "reviewed_gold": reviewed_gold, "diagnostic": diagnostic,
              "ml_status": ml_status, "rag_status": rag_status,
              "model_files_sha256": {p.name: digest(p) for p in sorted(ml.path.iterdir()) if p.is_file()},
              "rag_files_sha256": {p.name: digest(p) for p in sorted(index_path.iterdir()) if p.is_file()},
              "corpus_sha256": digest(settings.root / settings.rag_corpus),
              "embedding_metadata_sha256": digest(settings.root / settings.rag_model_dir / "phishlens_model.json"),
              "source_sha256": {str(p.relative_to(ROOT)): digest(p) for p in sources},
              "llm": {"endpoint": settings.endpoint, "model": settings.llm_model, "max_tokens": settings.max_tokens,
                      "timeout_seconds": settings.timeout_seconds, "temperature": .1, "top_p": 1, "top_k": 40,
                      "prompt_versions": [MESSAGE_PROMPT_VERSION, MESSAGE_RAG_PROMPT_VERSION] if profile == "message-v2" else [PROMPT_VERSION, RAG_PROMPT_VERSION]},
              "seed": args.seed, "workers": args.workers,
              "versions": {p: importlib.metadata.version(p) for p in ("httpx", "xgboost-cpu", "numpy", "pydantic", "torch", "transformers")}}
    manifest = prepare_manifest(out, config)
    cache = load_checkpoints(out / "checkpoints.jsonl")
    if not cache.keys() <= {(c["id"], a) for c in cases for a in ARMS}:
        raise ValueError("Unknown case or arm in checkpoint.")
    prepared_path = out / "prepared_cases.json"
    if prepared_path.exists():
        prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
        recorded_hash = (out / "prepared_cases.sha256").read_text(encoding="utf-8").strip()
        if digest(prepared_path) != recorded_hash or set(prepared) != {c["id"] for c in cases}:
            raise ValueError("Prepared snapshot was modified or is incomplete.")
    else:
        if cache:
            raise ValueError("Cached calls without a prepared input snapshot.")
        prepared = {}
        for i, c in enumerate(cases, 1):
            urls, invalid = extract_urls(c["text"], "text")
            started = time.perf_counter()
            predictions = ml.predict(urls)
            if any(u["status"] != "ok" for u in predictions):
                raise ValueError("ML prediction failed: " + c["id"])
            ml_ms = round(1000 * (time.perf_counter() - started), 2)
            retrieval = rag.search(redact(c["text"])[0])
            if retrieval["status"] == "unavailable":
                raise ValueError("RAG unavailable: " + c["id"])
            prepared[c["id"]] = {"urls": predictions, "invalid_urls": invalid, "ml_ms": ml_ms, "retrieval": retrieval}
            if i % 10 == 0:
                print(f"Prepared {i}/{len(cases)} messages", flush=True)
        write_json(prepared_path, prepared)
        (out / "prepared_cases.sha256").write_text(digest(prepared_path) + "\n", encoding="utf-8")
    state = {"live": args.live, "new_api_calls": 0, "stop_reason": None if args.live else "offline_prepared"}
    export(out, manifest, assemble_rows(cases, prepared, cache, fusion_policy), state)
    print(f"Cases={len(cases)}, cached={len(cache)}, retrieval={dict(Counter(p['retrieval']['status'] for p in prepared.values()))}", flush=True)
    if args.live:
        ordering = list(cases)
        random.Random(args.seed).shuffle(ordering)
        queue = asyncio.Queue()
        for i, c in enumerate(ordering):
            queue.put_nowait((i, c))
        consecutive_errors = 0
        async with httpx.AsyncClient(timeout=settings.timeout_seconds, trust_env=False) as client:
            service = LLMService(settings, client)

            async def worker():
                nonlocal consecutive_errors
                while not queue.empty() and state["stop_reason"] is None:
                    i, c = queue.get_nowait()
                    arms = ARMS[i % 4:] + ARMS[:i % 4]
                    if (i // 4) % 2:
                        arms = tuple(reversed(arms))
                    for a in arms:
                        if (c["id"], a) in cache:
                            continue
                        if state["stop_reason"] is not None:
                            break
                        if state["new_api_calls"] >= args.max_new_calls:
                            state["stop_reason"] = "call_budget_reached"
                            break
                        state["new_api_calls"] += 1
                        started = time.perf_counter()
                        try:
                            result = await call_arm(service, c, prepared[c["id"]], a, profile)
                        except LLMFailure as exc:
                            result = {"status": "error", "code": exc.code, "message": exc.message,
                                      "elapsed_ms": round(1000 * (time.perf_counter() - started), 1)}
                        except Exception as exc:
                            result = {"status": "error", "code": "UNEXPECTED_" + type(exc).__name__,
                                      "elapsed_ms": round(1000 * (time.perf_counter() - started), 1)}
                        cache[(c["id"], a)] = result
                        with (out / "checkpoints.jsonl").open("a", encoding="utf-8") as f:
                            f.write(json.dumps({"case_id": c["id"], "arm": a, "result": result}, ensure_ascii=False) + "\n")
                            f.flush()
                            os.fsync(f.fileno())
                        consecutive_errors = consecutive_errors + 1 if result["status"] == "error" else 0
                        if result.get("code") in FATAL_CODES or consecutive_errors >= 3:
                            state["stop_reason"] = result.get("code", "consecutive_errors")
                        export(out, manifest, assemble_rows(cases, prepared, cache, fusion_policy), state)
                        print(f"[{len(cache)}/{4 * len(cases)}] {c['id']} {a}: {result['status']} {level(result)} {result.get('code', '')}", flush=True)
            await asyncio.gather(*(worker() for _ in range(args.workers)))
    state["stop_reason"] = "all_calls_completed" if len(cache) == 4 * len(cases) else state["stop_reason"]
    state["completed_at"] = datetime.now(timezone.utc).isoformat()
    summary = export(out, manifest, assemble_rows(cases, prepared, cache, fusion_policy), state)
    print(json.dumps({"out": str(out), "complete_cases": summary["complete_cases"], "state": state}, ensure_ascii=False), flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts/evaluations/rag_ablation_v1")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--prompt-profile", choices=("legacy", "message-v2"), default="legacy")
    parser.add_argument("--fusion-policy", choices=("legacy", "separate"), default="legacy")
    parser.add_argument("--reviewed-manifest", type=Path)
    parser.add_argument("--diagnostic", action="store_true", help="Explicitly mark synthetic/unreviewed checks; never report as an independent benchmark.")
    parser.add_argument("--max-new-calls", type=int, default=400)
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--workers", type=int, choices=(1, 2), default=2)
    parser.add_argument("--seed", type=int, default=20261027)
    args = parser.parse_args()
    if args.max_new_calls < 0 or args.max_tokens < 1 or args.timeout <= 0:
        parser.error("Invalid call/token budget or timeout.")
    try:
        summary = asyncio.run(evaluate(args))
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Evaluation stopped: {exc}\n")
    if args.live and summary["run_state"]["stop_reason"] != "all_calls_completed":
        parser.exit(1, "Incomplete run; resume with the same command.\n")


if __name__ == "__main__":
    main()
