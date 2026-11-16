"""Readiness and data gaps; an inflated positive F1 cannot promote a candidate."""
import argparse
from collections import Counter
import json
from pathlib import Path

from evaluation.common import registered
from evaluation.data.sms import read_jsonl, sha, write_json
from evaluation.messages.ablation_interpretation import transitions
from evaluation.messages.fresh_ablation import ARMS, parse_response


def gate(baseline, candidate, changes, *, human_gold, positives, positive_url_cases):
    checks = {
        "independent_human_reference": human_gold,
        "at_least_20_positive_examples": positives >= 20,
        "at_least_20_positive_URL_examples": positive_url_cases >= 20,
        "full_set_accuracy_not_lower": candidate["accuracy"] is not None and candidate["accuracy"] >= baseline["accuracy"],
        "recall_not_lower": candidate["recall"] is not None and candidate["recall"] >= baseline["recall"],
        "coverage_not_lower": candidate["coverage"] is not None and candidate["coverage"] >= baseline["coverage"],
        "technical_errors_not_higher": candidate["technical_errors"] <= baseline["technical_errors"],
        "false_alarm_reduction_has_real_correction": candidate["fp"] >= baseline["fp"] or changes["alarm_to_low"] > 0,
    }
    return {"eligible_to_claim_improvement": all(checks.values()), "checks": checks,
            "failed": [key for key, value in checks.items() if not value],
            "automatic_deployment": False}


def report(study, out):
    study, out = Path(study), Path(out)
    if out.exists(): raise ValueError("Preserve the previous readiness snapshot.")
    if not registered.verify(study, parse_response)["complete"]: raise ValueError("Study is incomplete.")
    cfg, _ = registered.load(study)
    derived = json.loads((study / "interpretation_manifest.json").read_text())
    if any(sha(study / name) != derived[field] for name, field in
           (("metrics.json", "metrics_sha256"), ("decisions.jsonl", "decisions_sha256"))):
        raise ValueError("Derived results changed.")
    metrics = json.loads((study / "metrics.json").read_text())
    decisions = read_jsonl(study / "decisions.jsonl")
    labels_dir = Path(cfg["metadata"]["labels"])
    reference = json.loads((labels_dir / "labels_manifest.json").read_text())
    labels = read_jsonl(labels_dir / "labels.jsonl")
    inputs = Path(cfg["metadata"]["inputs"])
    prepared = json.loads((inputs / "prepared.json").read_text())
    buckets = Counter()
    for row in labels:
        name = "with_URL" if prepared[row["id"]]["url_context"] else "without_URL"
        label = "UNKNOWN" if row["label"] is None else "positive" if row["label"] == 1 else "negative"
        buckets[name + "_" + label] += 1
    human = reference.get("independent_human_gold") is True and reference.get("human_reviewed") is True
    target = {key: {"AI_draft_available": buckets[key], "human_gold_available": buckets[key] if human else 0,
        "planning_target_per_group": 20, "AI_draft_gap": max(0, 20 - buckets[key])}
        for key in ("with_URL_positive", "with_URL_negative", "without_URL_positive", "without_URL_negative")}
    base = metrics["groups"]["sms"]["llm_only"]
    gates = {arm: gate(base, metrics["groups"]["sms"][arm], transitions(decisions, arm),
        human_gold=reference.get("independent_human_gold") is True,
        positives=sum(r["label"] == 1 for r in labels), positive_url_cases=buckets["with_URL_positive"])
        for arm in ARMS[1:]}
    result = {"scope": "Previous week4 research ablation; does not rate the new focused runtime",
        "data_reference_status": reference["status"], "gates": gates, "data_gaps": target,
        "reference_unknown": sum(r["label"] is None for r in labels),
        "quotas_are_planning_targets_not_population_prevalence": True,
        "provider_calls": 0, "reserve_inference": False, "new_gold_labels_created": 0}
    out.mkdir(parents=True)
    write_json(out / "readiness.json", result)
    write_json(out / "manifest.json", {"study_seal_sha256": sha(study / "result_hashes.json"),
        "labels_sha256": sha(labels_dir / "labels.jsonl"), "analysis_sha256": sha(__file__)})
    lines = ["# Điều kiện diễn giải cải tiến và khoảng trống dữ liệu", "",
        "Áp dụng cho lượt week4 cũ. Chưa có reference người độc lập hoặc đủ dương có URL; "
        "không cấu hình nào đủ căn cứ công bố cải thiện hay tự triển khai.", "",
        "| Nhóm SMS | Nhãn AI nhị phân hiện có | Mục tiêu review/thu bổ sung | Còn thiếu theo nhãn AI |",
        "|---|---:|---:|---:|"]
    for key, value in target.items():
        lines.append(f"| {key} | {value['AI_draft_available']} | 20 | {value['AI_draft_gap']} |")
    lines += ["", "Mục tiêu 20 mỗi nhóm chỉ là kế hoạch đánh giá phân tầng; mọi mẫu vẫn cần review người, "
        f"không dùng nhãn spam nguồn hoặc dự đoán của hệ thống làm gold. Có {result['reference_unknown']} UNKNOWN để review riêng. "
        "120 reserve chưa được suy luận. Việc thu email thực và nhãn người còn cần thực hiện; công cụ này không tự tạo chúng."]
    (out / "report.md").write_text("\n".join(lines) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(report(args.study, args.out), ensure_ascii=False, indent=2))
