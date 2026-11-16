"""Paired pipeline comparison on the exact 80 dev SMS and frozen AI references."""
import argparse
import asyncio
from collections import Counter
import json
from pathlib import Path

from app.core.settings import Settings
from app.services.llm.client import approved_ml_metadata
from app.services.llm.compact import payload_for as compact_payload
from app.services.llm.core import build_payload
from app.services.llm.telemetry import ObservedTransport, fingerprint
from evaluation.common import registered
from evaluation.common.metrics import measure, prediction, paired_comparison
from evaluation.data.fresh_dev import cases
from evaluation.data.sms import read_jsonl, sha, write_json, write_jsonl
from evaluation.messages.core_pilot import parse_response
from evaluation.messages.fresh_ablation import parse_response as parse_previous
from evaluation.messages.url_context import canonical_sha

ARMS = ("v61_no_URL", "core_no_URL", "core_with_URL")


def requests_for(sms, prepared, model):
    requests, cells = {}, []
    for case in sms:
        urls = prepared[case["id"]]["url_results"]
        approved = approved_ml_metadata(case["text"], urls)
        for arm in ARMS:
            args = dict(text=case["text"], urls=urls, include_ml=arm == "core_with_URL" and bool(approved),
                        model=model, max_tokens=2048)
            if arm == "v61_no_URL":
                payload, _, _ = compact_payload(**args, sources=[])
                payload["thinking"] = {"type": "disabled"}
                profile = "v61"
            else:
                payload, _ = build_payload(**args, thinking="disabled")
                profile = "core"
            key = case["id"] + "::" + fingerprint(payload)[:16]
            requests.setdefault(key, {"key": key, "case_id": case["id"], "profile": profile,
                "thinking": "disabled", "text": case["text"], "payload": payload})
            cells.append({"id": case["id"], "arm": arm, "request_key": key,
                "URL_context_available": bool(approved), "train_domain_overlap": prepared[case["id"]]["url_train_domain_overlap"]})
    ordered = sorted(requests.values(), key=lambda r: canonical_sha([20261112, "quality", r["key"]]))
    return ordered, cells


def prepare(study, probe, out):
    study, probe, out = Path(study), Path(probe), Path(out)
    if not registered.verify(study, parse_previous)["complete"]: raise ValueError("Original study is incomplete.")
    if not registered.verify(probe, parse_response)["complete"]: raise ValueError("Provider probe is incomplete.")
    probe_state = json.loads((probe / "summary.json").read_text())
    if probe_state["valid"] != probe_state["expected"]: raise ValueError("Provider compatibility probe had failures.")
    cfg, _ = registered.load(study)
    meta = cfg["metadata"]
    pack, labels = Path(meta["pack"]), Path(meta["labels"])
    ref_manifest = json.loads((labels / "labels_manifest.json").read_text())
    if sha(labels / "labels.jsonl") != ref_manifest["label_file_sha256"]:
        raise ValueError("References changed after the previous comparison.")
    sms, _ = cases(pack)
    if len(sms) != 80: raise ValueError("Expected the frozen eighty-message dev cohort.")
    previous_inputs = Path(meta["inputs"])
    prepared = json.loads((previous_inputs / "prepared.json").read_text())
    requests, cells = requests_for(sms, prepared, Settings().llm_model)
    inputs = out.with_name(out.name + "_inputs")
    if inputs.exists(): raise ValueError("Preserve the previous input mapping.")
    inputs.mkdir(parents=True)
    write_jsonl(inputs / "cells.jsonl", cells)
    return registered.register(out, requests, stage="core_quality_dev", max_tokens=2048, token_budget=350000,
        metadata={"pack": str(pack.resolve()), "labels": str(labels.resolve()), "inputs": str(inputs.resolve()),
            "arms": list(ARMS), "logical_cells": len(cells), "reference_status": ref_manifest["status"],
            "reference_judge": ref_manifest["reference_judge"], "human_gold": False,
            "same_model_cap_decoding_thinking_timeout": True, "comparison_is_between_pipeline_profiles": True,
            "schema_and_prompt_difference_is_intentional": True, "identical_payloads_share_response": True,
            "RAG_not_in_classification": True, "reserve_inference": False,
            "URL_scores_origin": str(previous_inputs / "prepared.json")},
        locks=[pack / "manifest.json", pack / "sms.jsonl", labels / "labels.jsonl", labels / "labels_manifest.json",
               previous_inputs / "prepared.json", study / "execution.json", study / "result_hashes.json",
               probe / "result_hashes.json", inputs / "cells.jsonl"])


def report(out):
    out = Path(out)
    if not registered.verify(out, parse_response)["complete"]: raise ValueError("Comparison is incomplete.")
    cfg, _ = registered.load(out)
    _, records = registered.checkpoints(out, cfg)
    labels = {r["id"]: r["label"] for r in read_jsonl(Path(cfg["metadata"]["labels"]) / "labels.jsonl")}
    cells = read_jsonl(Path(cfg["metadata"]["inputs"]) / "cells.jsonl")
    rows = []
    for cell in cells:
        record = records[(cfg["stage"], cell["request_key"])]
        parsed = record["parsed"]
        rows.append({**cell, "label": labels[cell["id"]], "status": parsed["status"], "error": parsed.get("code"),
            "level": parsed["verdict"]["risk_level"] if parsed["status"] == "ok" else "UNKNOWN"})
    result = {"reference_status": cfg["metadata"]["reference_status"], "independent_accuracy": None,
        "reference_counts": dict(Counter("UNKNOWN" if v is None else str(v) for v in labels.values())),
        "physical_run": json.loads((out / "summary.json").read_text()), "logical_cells": len(cells),
        "aliased_cells": len(cells) - len(records), "arms": {}, "paired": {}, "URL_subset": {}}
    lookup = {(r["id"], r["arm"]): r for r in rows}
    baseline = [r for r in rows if r["arm"] == ARMS[0] and r["label"] is not None]
    for arm in ARMS:
        selected = [r for r in rows if r["arm"] == arm]
        binary = [r for r in selected if r["label"] is not None]
        result["arms"][arm] = {**measure([r["label"] for r in binary], [r["level"] for r in binary]),
            "technical_errors_all_80": sum(r["status"] != "ok" for r in selected),
            "unknown_reference_predictions": dict(Counter(r["level"] for r in selected if r["label"] is None))}
        url_cases = [r for r in binary if r["URL_context_available"]]
        result["URL_subset"][arm] = {**measure([r["label"] for r in url_cases], [r["level"] for r in url_cases]),
            "positive_cases": sum(r["label"] == 1 for r in url_cases)}
        if arm != ARMS[0]:
            result["paired"][arm] = paired_comparison([r["label"] for r in baseline], [r["level"] for r in baseline],
                                                       [lookup[(r["id"], arm)]["level"] for r in baseline])
    transitions = Counter()
    for left in [r for r in rows if r["arm"] == "core_no_URL" and r["label"] is not None]:
        right = lookup[(left["id"], "core_with_URL")]
        a, b = prediction(left["level"]), prediction(right["level"])
        if left["label"] == 0 and a == 1 and b == 0: transitions["false_alarm_to_correct_low"] += 1
        if left["label"] == 0 and a == 1 and b is None: transitions["false_alarm_to_unknown"] += 1
        if a == left["label"] and b != left["label"]: transitions["correct_decision_lost"] += 1
    result["URL_effect_transitions"] = dict(transitions)
    binary_labels = [v for v in labels.values() if v is not None]
    result["baselines"] = {"always_low": measure(binary_labels, ["LOW"] * len(binary_labels)),
                           "always_high": measure(binary_labels, ["HIGH"] * len(binary_labels))}
    write_json(out / "metrics.json", result)
    write_jsonl(out / "decisions.jsonl", rows)
    lines = ["# Chất lượng dev: v6.1 và verdict lõi, thinking disabled", "",
        "Cùng 80 SMS, reference trợ lý AI 4 dương/54 âm/22 UNKNOWN. Hai profile khác prompt/schema có chủ ý; "
        "đây là so sánh pipeline, không tách riêng tác dụng một thay đổi prompt. Không có nhãn người độc lập.", "",
        "| Arm | Precision | Recall | F1 | Đúng / n nhị phân | Coverage | FP / 54 âm | Lỗi / 80 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|"]
    fmt = lambda v: "N/A" if v is None else f"{v:.2%}"
    for arm, m in result["arms"].items():
        lines.append(f"| {arm} | {fmt(m['precision'])} | {fmt(m['recall'])} | {fmt(m['f1'])} | "
            f"{m['tp']+m['tn']}/{m['n']} | {fmt(m['coverage'])} | {m['fp']}/54 | {m['technical_errors_all_80']}/80 |")
    lines += ["", f"240 ô logic dùng {len(records)} request; {result['aliased_cells']} ô dùng chung response vì payload giống hệt.",
        "UNKNOWN/lỗi tính sai trong Accuracy; dương UNKNOWN giảm Recall/F1. Nhãn UNKNOWN được báo riêng.",
        "Bốn mẫu dương đều không có URL model context; chưa kiểm được tăng Recall nhờ URL. Score URL lấy từ cache đã khóa của lượt trước.",
        "RAG ở sau verdict nên không được công bố như một arm cải thiện F1 phân loại. Chất lượng nguồn/giải thích cần đo riêng.",
        "Mọi lỗi được giữ nguyên; 120 reserve chưa suy luận. Không đổi nhãn hoặc chọn lại input theo kết quả."]
    (out / "report.md").write_text("\n".join(lines) + "\n")
    write_json(out / "telemetry_manifest.json", {"telemetry_sha256": sha(out / "telemetry.jsonl"),
        "raw_seal_sha256": sha(out / "result_hashes.json"), "analysis_source_sha256": sha(__file__)})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "run", "report", "verify"])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--study", type=Path)
    parser.add_argument("--probe", type=Path)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if args.command == "prepare": value = {"requests": prepare(args.study, args.probe, args.out)["max_attempts"], "API_calls": 0}
    elif args.command == "run":
        transport = ObservedTransport(args.out / "telemetry.jsonl") if args.live else None
        value = asyncio.run(registered.run(args.out, parse_response, live=args.live, transport=transport))
    elif args.command == "verify": value = registered.verify(args.out, parse_response)
    else:
        result = report(args.out); value = {"arms": result["arms"], "physical_run": result["physical_run"]}
    print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
