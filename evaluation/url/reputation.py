"""Offline reputation experiment: train-sourced evidence, dev and known replays.

No LLM, live threat feed, target-page fetch or threshold tuning. Known replays
deliberately overlap the knowledge base and are never called an unseen test.
"""
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import time

from sklearn.metrics import f1_score, precision_score, recall_score

from app.services.url.features import ModelService
from app.core.settings import ROOT, Settings
from app.services.url.reputation import Evidence, ReputationStore, VERSION, canonical_url, route_urls, utc
from evaluation.data.sms import read_jsonl, sha, write_json, write_jsonl
from evaluation.common.metrics import measure, paired_comparison, prediction
from evaluation.url.phishvn import DOI, notebook_constants, prepare_splits, recover_fingerprint
from evaluation.data.url_context import verify as verify_url_pack


SEED = 20261104
TTL_DAYS = {"malicious": 7, "trusted": 30}
KNOWN_QUOTAS = (("tinnhiemmang", "gold", 50), ("tinnhiemmang", "silver", 50),
                ("tinnhiem_org", "gold", 50), ("tinnhiem_web", "gold", 50))


def rank(value):
    return hashlib.sha256(f"{SEED}:{value}".encode()).hexdigest()


def source_time(value):
    # A date-only source timestamp means UTC midnight for this simulation.
    if len(value) == 10:
        value += "T00:00:00+00:00"
    return utc(value)


def build_evidence(rows):
    """Only official train registries/threat lists; no dev labels or predictions."""
    entries, audit = [], Counter()
    for row in rows:
        verdict = ("trusted" if row["source"] in {"tinnhiem_org", "tinnhiem_web"}
                   and row["tier"] == "gold" and row["labels"] == 0 else
                   "malicious" if row["source"] == "tinnhiemmang" and row["tier"] in {"gold", "silver"}
                   and row["labels"] == 1 else None)
        if verdict is None:
            audit["excluded_source_tier_or_label"] += 1
            continue
        try:
            observed = source_time(row["scraped_at"])
            item = Evidence(id="REP-" + row["id"], url=row["url"], verdict=verdict,
                source=row["source"], source_id=row["id"], source_url=DOI, source_tier=row["tier"],
                evidence_kind="source_registry" if verdict == "trusted" else "source_threat_list",
                observed_at=observed.isoformat(),
                expires_at=(observed + timedelta(days=TTL_DAYS[verdict])).isoformat())
        except (ValueError, UnicodeError):
            audit["excluded_invalid_url_or_time"] += 1
            continue
        entries.append(item)
        audit[verdict] += 1
    return entries, dict(audit)


def select_known(entries, rows):
    metadata = {r["id"]: r for r in rows}
    selected, domains = [], set()
    for source, tier, count in KNOWN_QUOTAS:
        pool = sorted((e for e in entries if e.source == source and e.source_tier == tier), key=lambda e: rank(e.source_id))
        candidates = []
        for item in pool:
            row = metadata[item.source_id]
            if row["domain_group"] in domains:
                continue
            candidates.append({"id": "KNOWN-" + row["id"], "source_id": row["id"], "url": item.url,
                "label": row["labels"], "source": source, "tier": tier, "domain_group": row["domain_group"],
                "cohort": "known_replay", "reference": "same_source_record_as_evidence_not_independent"})
            domains.add(row["domain_group"])
            if len(candidates) == count:
                break
        if len(candidates) != count:
            raise ValueError(f"Insufficient known replay domains: {source}/{tier}")
        selected.extend(candidates)
    return sorted(selected, key=lambda r: rank(r["id"]))


def prepare(out, archive, model_dir, notebook, url_pack, reevaluate_at):
    if out.exists():
        raise ValueError("Use a new output directory; preserve previous experiments.")
    constants = notebook_constants(notebook)
    for name, filename in (("FEATURE_SOURCE", "url_features.py"), ("PREPROCESSING_SOURCE", "url_preprocessing.py")):
        if constants[name] != (model_dir / filename).read_text():
            raise ValueError("Model/notebook inference code mismatch.")
    module_spec = importlib.util.spec_from_file_location("reputation_source_preprocessing", model_dir / "url_preprocessing.py")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    frames, split_audit = prepare_splits(archive, constants["CFG"], module)
    spec = json.loads((model_dir / "config.json").read_text())
    fingerprint, _ = recover_fingerprint(constants["CFG"], constants, frames, spec)
    # Build knowledge before reading the dev cohort. The official test is not evaluated.
    train = frames["train"].to_dict("records")
    entries, evidence_audit = build_evidence(train)
    if not entries:
        raise ValueError("No usable source evidence.")
    store = ReputationStore(entries)
    historical_at = max(utc(e.observed_at) for e in entries) + timedelta(seconds=1)
    reevaluate_at = utc(reevaluate_at)
    if reevaluate_at <= max(utc(e.expires_at) for e in entries):
        raise ValueError("This experiment requires an after-expiry clock for the second scenario.")
    verify_url_pack(url_pack)
    dev = [r for r in read_jsonl(url_pack / "urls.jsonl") if r["split"] == "dev"]
    official = {r["id"]: r for r in frames["val"].to_dict("records")}
    unknown = []
    for row in dev:
        original = official[row["source_id"]]
        if row["url"] != original["url"] or row["url_label"] != original["labels"]:
            raise ValueError("Dev reference does not match source.")
        unknown.append({"id": "NEW-" + row["source_id"], "source_id": row["source_id"], "url": row["url"],
            "label": row["url_label"], "source": row["source"], "tier": row["tier"],
            "domain_group": row["domain_group"], "cohort": "unknown_dev",
            "reference": "historical_dev_source_label_previously_evaluated"})
    train_domains = {r["domain_group"] for r in train}
    overlap = train_domains & {r["domain_group"] for r in unknown}
    if overlap or any(store.lookup(r["url"], as_of=historical_at)["state"] != "miss" for r in unknown):
        raise ValueError("Unseen-dev cohort overlaps knowledge/training domains.")
    known = select_known(entries, train)
    if any(store.lookup(r["url"], as_of=historical_at)["state"] != "known" for r in known):
        raise ValueError("Known replays need active, unambiguous source evidence.")
    requests = known + unknown
    if len({canonical_url(r["url"]) for r in requests}) != len(requests):
        raise ValueError("Duplicate canonical request URL.")
    out.mkdir(parents=True)
    from dataclasses import asdict
    write_jsonl(out / "knowledge.jsonl", [asdict(e) for e in entries])
    write_jsonl(out / "requests.jsonl", requests)
    source_files = [archive, notebook, url_pack / "manifest.json", url_pack / "urls.jsonl",
        Path(__file__), ROOT / "app/services/url/reputation.py", ROOT / "app/services/url/features.py", ROOT / "evaluation/common/metrics.py"]
    source_files.extend(p for p in sorted(model_dir.iterdir()) if p.is_file())
    execution = {"version": VERSION, "created_at": datetime.now(timezone.utc).isoformat(), "seed": SEED,
        "source": DOI, "knowledge_official_split": "train", "reference_status": "historical_not_live_verified",
        "historical_at": historical_at.isoformat(), "reevaluate_at": reevaluate_at.isoformat(),
        "time_assumption": "scraped_at is snapshot availability, not live independent verification; date-only means UTC midnight; TTLs are fixed simulation assumptions",
        "ttl_days": TTL_DAYS, "knowledge_audit": evidence_audit, "knowledge_entries": store.size,
        "known_quotas": KNOWN_QUOTAS, "cohorts": dict(Counter(r["cohort"] for r in requests)),
        "unknown_domain_overlap_with_train": len(overlap), "training_fingerprint": fingerprint,
        "model_dir": str(model_dir.resolve()), "thresholds": spec["thresholds"],
        "comparisons": ["lookup_only", "url_model", "lookup_then_model"],
        "provider_call_budget": 0, "maximum_url_model_inputs": 3 * len(requests),
        "test_inference": False, "selection_reads_model_predictions": False,
        "known_replay_limit": "Repeated source records intentionally in KB and ML training; 100% lookup is a routing control, not unseen detection quality",
        "mixed_limit": "200 known + 40 unknown is a designed traffic mixture, not estimated user traffic or a new independent test",
        "split_audit": split_audit,
        "source_hashes": {str(p.resolve()): sha(p) for p in source_files},
        "prepared_hashes": {name: sha(out / name) for name in ("knowledge.jsonl", "requests.jsonl")}}
    write_json(out / "execution.json", execution)
    return execution


def verify_inputs(out):
    execution = json.loads((out / "execution.json").read_text())
    for p, expected in execution["source_hashes"].items():
        if sha(p) != expected:
            raise ValueError("Frozen runtime/source changed: " + p)
    for name, expected in execution["prepared_hashes"].items():
        if sha(out / name) != expected:
            raise ValueError("Prepared evidence/cohort changed: " + name)
    return execution


def checked_metrics(cases, levels):
    labels = [r["label"] for r in cases]
    result = measure(labels, levels)
    # For positive-class P/R/F1, UNKNOWN is a missed alarm, not a dropped row.
    binary = [int(prediction(level) == 1) for level in levels]
    if cases:
        independent = {"f1": f1_score(labels, binary, zero_division=0),
                       "precision": precision_score(labels, binary, zero_division=0),
                       "recall": recall_score(labels, binary, zero_division=0)}
        for name, expected in independent.items():
            if result[name] is not None and not math.isclose(result[name], float(expected), abs_tol=1e-12):
                raise ValueError("Independent metric check failed: " + name)
    result["model_inputs"] = None  # assigned separately from the actual routing trace
    return result


def summarize(cases, baseline, routed):
    summary = {}
    for cohort in ("known_replay", "unknown_dev", "designed_mix"):
        indices = [i for i, r in enumerate(cases) if cohort == "designed_mix" or r["cohort"] == cohort]
        subset = [cases[i] for i in indices]
        levels = {"lookup_only": [routed[i]["reputation"]["risk_level"] for i in indices],
                  "url_model": [baseline[i]["risk_level"] if baseline[i]["status"] == "ok" else "UNKNOWN" for i in indices],
                  "lookup_then_model": [routed[i]["risk_level"] for i in indices]}
        arms = {arm: checked_metrics(subset, values) for arm, values in levels.items()}
        for arm, metrics in arms.items():
            metrics["model_inputs"] = 0 if arm == "lookup_only" else len(indices) if arm == "url_model" else sum(routed[i]["model_called"] for i in indices)
            metrics["model_skip_rate"] = 1 - metrics["model_inputs"] / len(indices) if indices else None
        labels = [r["label"] for r in subset]
        summary[cohort] = {"n": len(subset), "positives": sum(labels), "negatives": len(labels) - sum(labels),
            "lookup_states": dict(Counter(routed[i]["reputation"]["state"] for i in indices)), "arms": arms,
            "paired_ml_to_hybrid": paired_comparison(labels, levels["url_model"], levels["lookup_then_model"])}
    return summary


def report(summary):
    execution = summary["execution"]
    fmt = lambda v: "N/A" if v is None else f"{100 * v:.2f}%"
    lines = ["# Thử nghiệm tra cứu uy tín URL trước model", "",
        "**Chẩn đoán offline, không gọi LLM hoặc xác minh website hiện tại.** Kho chỉ dùng PhishVN train; dev tách miền. "
        "Nhóm truy cập lại cố ý trùng kho và dữ liệu ML đã học; không phải kết quả dự đoán trên URL chưa biết.", "",
        f"Kho: {execution['knowledge_entries']} bản ghi; TTL giả định: malicious 7 ngày, trusted 30 ngày. "
        "Chỉ khớp URL chính xác sau chuẩn hóa bảo thủ; không kế thừa uy tín cho miền con, path, query hoặc fragment khác.", "",
        "`scraped_at` chỉ dùng làm thời điểm có snapshot lịch sử, không chứng minh đã xác minh lại website lúc đó. "
        "Không nhập Tranco/popularity, nhãn dev, kết quả model hay nhận định LLM vào kho. Ngưỡng ML giữ nguyên."]
    labels = {"known_replay": "Truy cập lại URL có trong kho (đối chứng chuyển tuyến)",
              "unknown_dev": "40 URL dev chưa có trong kho (nhóm chẩn đoán chính)",
              "designed_mix": "Hỗn hợp thiết kế 200 đã biết + 40 chưa biết (không đại diện lưu lượng thực)"}
    for scenario in ("historical", "after_expiry"):
        group = summary["scenarios"][scenario]
        lines += ["", f"## {'Snapshot lịch sử còn hiệu lực' if scenario == 'historical' else 'Giữ nguyên kho đến khi hết hạn'}: {group['as_of']}", ""]
        for cohort, title in labels.items():
            item = group["metrics"][cohort]
            lines += [f"### {title}", "", f"n={item['n']}; dương={item['positives']}, âm={item['negatives']}; lookup={item['lookup_states']}", "",
                "| Cấu hình | F1 | Recall | FPR | Accuracy | Coverage | URL qua ML | Bỏ qua ML |",
                "|---|---:|---:|---:|---:|---:|---:|---:|"]
            for arm, m in item["arms"].items():
                lines.append(f"| {arm} | {fmt(m['f1'])} | {fmt(m['recall'])} | {fmt(m['false_positive_rate'])} | "
                             f"{fmt(m['accuracy'])} | {fmt(m['coverage'])} | {m['model_inputs']} | {fmt(m['model_skip_rate'])} |")
            paired = item["paired_ml_to_hybrid"]
            lines += ["", f"ML → kết hợp: sửa đúng {paired['improved']}, làm sai thêm {paired['regressed']}. "
                      "UNKNOWN/lỗi không được tính đúng trong accuracy; F1 lớp dương phải đọc cùng coverage.", ""]
    lines += ["## Cách đọc kết quả", "",
        "- Điểm tra cứu trên URL có sẵn dùng chính nhãn nguồn đã nạp: 100% là kỳ vọng của đối chứng, không chứng minh chất lượng ngoài mẫu hoặc nguồn không sai.",
        "- Nhóm chưa biết không được hưởng lợi từ nhãn trong kho. Nếu không có hit, kết hợp phải giữ nguyên dự đoán ML và vẫn gọi ML cho mọi URL.",
        "- Tỷ lệ URL đã biết trong hỗn hợp do thí nghiệm đặt ra. Không dùng F1 tổng của hỗn hợp làm chất lượng ứng dụng ngoài thực tế.",
        "- Khi hết hạn, toàn bộ bằng chứng phải bị bỏ qua; không duy trì kết luận uy tín vĩnh viễn hoặc tự gia hạn bằng dự đoán ML.",
        "- Không đo LLM, RAG, lời giải thích hay phân loại nội dung tin nhắn. Một URL uy tín không xác nhận tin nhắn xin OTP là an toàn.",
        "- Dev và ML đã được xem trước đây; chưa chạy thêm phần test URL/ngữ cảnh. Không chọn lại ngưỡng, seed hoặc mẫu sau kết quả.",
        "- Thời gian chạy cục bộ phụ thuộc cache/model đã nạp; báo tỷ lệ bỏ qua ML, không suy ra mức tăng tốc đầu cuối.", "",
        f"Số URL thực sự đưa vào ML trong thí nghiệm: {summary['actual_model_inputs']}. Gọi API: **0**.",
        "Số học P/R/F1 được đối chiếu scikit-learn; trace kiểm tra model chỉ nhận những URL chưa có kết luận tra cứu."]
    return "\n".join(lines) + "\n"


def run(out):
    execution = verify_inputs(out)
    if any((out / name).exists() for name in ("baseline.jsonl", "historical.jsonl", "after_expiry.jsonl", "calls.jsonl", "summary.json")):
        raise ValueError("Run already started; preserve it and choose a new directory.")
    cases = read_jsonl(out / "requests.jsonl")
    store = ReputationStore(read_jsonl(out / "knowledge.jsonl"))
    model = ModelService(Settings(model_dir=execution["model_dir"]))
    if not model.load()["ready"]:
        raise ValueError(model.error)
    calls = []
    def predict(urls, arm):
        calls.append({"arm": arm, "urls": list(urls), "n": len(urls)})
        write_jsonl(out / "calls.jsonl", calls)
        return model.predict(urls)
    urls = [r["url"] for r in cases]
    started = time.perf_counter()
    baseline = predict(urls, "baseline")
    write_jsonl(out / "baseline.jsonl", baseline)
    scenarios = {}
    for name, clock in (("historical", execution["historical_at"]), ("after_expiry", execution["reevaluate_at"])):
        routed = route_urls(urls, store, lambda inputs: predict(inputs, name), as_of=clock)
        expected = [r["url"] for r in routed if r["model_called"]]
        actual = [u for call in calls if call["arm"] == name for u in call["urls"]]
        if actual != expected:
            raise ValueError("Model routing trace mismatch.")
        for i, row in enumerate(routed):
            if row["model_called"] and (row["risk_level"] != (baseline[i]["risk_level"] if baseline[i]["status"] == "ok" else "UNKNOWN")):
                raise ValueError("Unchanged deterministic model produced inconsistent outputs.")
        write_jsonl(out / (name + ".jsonl"), [{"case_id": c["id"], **r} for c, r in zip(cases, routed)])
        scenarios[name] = {"as_of": clock, "metrics": summarize(cases, baseline, routed)}
    verify_inputs(out)
    summary = {"execution": execution, "scenarios": scenarios, "provider_requests": 0,
        "actual_model_inputs": sum(c["n"] for c in calls), "elapsed_seconds": time.perf_counter() - started,
        "verification": {"metrics": "scikit-learn P/R/F1", "routing_trace": True, "input_hashes": True,
                         "live_reputation_or_label_correctness": False},
        "output_hashes": {name: sha(out / name) for name in ("baseline.jsonl", "historical.jsonl", "after_expiry.jsonl", "calls.jsonl")}}
    write_json(out / "summary.json", summary)
    (out / "report.md").write_text(report(summary), encoding="utf-8")
    return {"status": "completed_offline_diagnostic_not_external_gold", "report": str(out / "report.md"),
            "knowledge_entries": store.size, "actual_model_inputs": summary["actual_model_inputs"], "provider_requests": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--archive", type=Path, default=ROOT / "data/raw/PhishVN_v3.1.0_open.zip")
    parser.add_argument("--model-dir", type=Path, default=ROOT / "models/inference_XGBoost_d6_s42")
    parser.add_argument("--notebook", type=Path, default=ROOT / "notebooks/Train_URL_Phishing_GPU.ipynb")
    parser.add_argument("--url-pack", type=Path, default=ROOT / "data/annotation/url_context_v1")
    parser.add_argument("--reevaluate-at", default="2026-11-04T00:00:00+00:00")
    args = parser.parse_args()
    try:
        result = (prepare(args.out, args.archive, args.model_dir, args.notebook, args.url_pack, args.reevaluate_at)
                  if args.command == "prepare" else run(args.out))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(2, f"Reputation experiment stopped: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
