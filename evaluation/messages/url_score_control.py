"""Registered metadata-only URL score control on the frozen eighty dev SMS.

The permuted arm deliberately supplies another URL's coherent score pack. It is
a diagnostic for reliance on URL metadata, never a deployable configuration.
"""
import argparse
import asyncio
from collections import Counter
from copy import deepcopy
from importlib.metadata import version
import json
import math
from pathlib import Path
import statistics
import sys

from app.core.privacy import redact
from app.core.settings import ROOT, Settings
from app.services.llm.client import approved_ml_metadata
from app.services.llm.core import PROFILE, build_payload
from app.services.llm.telemetry import fingerprint
from app.services.url.character import CharURLService
from app.services.url.intake import VERSION as INTAKE_VERSION, inspect_url_intake
from app.services.url.policy import VERSION as POLICY_VERSION, operating_prediction
from evaluation.common import controlled_run, registered
from evaluation.common.metrics import measure, paired_comparison, prediction
from evaluation.data.sms import read_jsonl, sha, write_json, write_jsonl
from evaluation.messages.core_pilot import parse_response
from evaluation.messages.url_context import canonical_sha

DEFAULT_ROOT = ROOT / "artifacts/evaluations/week4_dev_20261111"
DEFAULT_PACK = DEFAULT_ROOT / "pack_reviewed"
DEFAULT_LABELS = DEFAULT_ROOT / "assistant_reference"
KNOWN_SMS_SHA256 = "e2bd99b902583e4e0d81c2bba15a9670bda4d69fddad22b9cfdc714b049791c4"
KNOWN_LABELS_SHA256 = "258671d65b1342bcbafb190e08f1a7353c9f7dd1f8c31f00536996621c423dfe"
SEED = 20261118
ARMS = ("core_no_URL", "core_real_URL", "core_permuted_URL")
SCORE_FIELDS = ("score", "risk_level", "warning_threshold", "high_threshold")
METADATA_FIELDS = ("id", "url", *SCORE_FIELDS)


def load_scope(pack, labels):
    """Accept only the existing dev/reference bytes, including copied paths."""
    pack, labels = Path(pack), Path(labels)
    manifest = json.loads((pack / "manifest.json").read_text())
    reference = json.loads((labels / "labels_manifest.json").read_text())
    if (manifest.get("status") != "development_only_not_gold"
            or manifest.get("reserve_inference") is not False
            or sha(pack / "sms.jsonl") != KNOWN_SMS_SHA256
            or manifest.get("files", {}).get("sms.jsonl") != KNOWN_SMS_SHA256):
        raise ValueError("Only the frozen eighty reviewed development SMS are allowed; no reserve input.")
    if (sha(labels / "labels.jsonl") != KNOWN_LABELS_SHA256
            or reference.get("label_file_sha256") != KNOWN_LABELS_SHA256
            or reference.get("pack_manifest_sha256") != sha(pack / "manifest.json")
            or reference.get("status") != "ai_preliminary_not_gold"
            or reference.get("independent_human_gold") is not False):
        raise ValueError("Use the existing assistant reference unchanged; no gold or relabeling.")
    sms, refs = read_jsonl(pack / "sms.jsonl"), read_jsonl(labels / "labels.jsonl")
    ids = {r["id"] for r in sms}
    if (len(sms) != 80 or len(ids) != 80 or len(refs) != 80
            or {r["id"] for r in refs} != ids
            or any(r.get("split") != "dev" or r.get("dataset") != "sms" for r in sms)
            or any(r.get("label") is not None and type(r["label"]) is not int for r in refs)
            or Counter(r["label"] for r in refs) != Counter({0: 54, 1: 4, None: 22})):
        raise ValueError("The exact eighty dev/reference inventory (4/54/22) is required.")
    if any(redact(r["text"])[0] != r["text"] for r in sms):
        raise ValueError("Frozen SMS require a new privacy review; do not change this experiment's text.")
    return sms, refs, reference


def score_cases(sms, model):
    """Score the current intake's local URLs before approved-visible filtering."""
    model.load()
    prepared = {}
    for case in sms:
        intake = inspect_url_intake(case["text"], "text")
        raw = model.predict(intake["urls"]) if intake["urls"] else []
        if [r["url"] for r in raw] != intake["urls"]:
            raise ValueError("Local scoring changed the URL inventory.")
        operating = [operating_prediction(row) for row in raw]
        approved = approved_ml_metadata(case["text"], operating)
        prepared[case["id"]] = {"id": case["id"], "text_sha256": canonical_sha(case["text"]),
            "intake": intake, "raw_url_results": raw, "operating_url_results": operating,
            "real_metadata": approved}
    return prepared


def _score_pack(row):
    if (set(row) != set(METADATA_FIELDS) or row["risk_level"] not in {"LOW", "UNKNOWN", "HIGH"}
            or type(row["score"]) not in (float, int) or not math.isfinite(row["score"])
            or not 0 <= row["score"] <= 1):
        raise ValueError("Approved metadata must contain only a valid complete score pack.")
    low, high = row["warning_threshold"], row["high_threshold"]
    if high is None or type(low) not in (int, float) or type(high) not in (int, float) or not 0 <= low <= high <= 1:
        raise ValueError("Approved metadata thresholds are invalid.")
    return {field: row[field] for field in SCORE_FIELDS}


def permute_metadata(prepared, seed=SEED):
    """One deterministic cycle of URL records; each donor URL differs.

    A URL row's score, risk, and thresholds move together. Receiver identities
    and URL spellings stay fixed, and original prepared inputs are untouched.
    """
    if type(seed) is not int:
        raise ValueError("An integer permutation seed is required before inference.")
    result = deepcopy(prepared)
    records = []
    for case_id, case in prepared.items():
        successful = {(r["id"], r["score"]) for r in case["operating_url_results"] if r.get("status") == "ok"}
        for index, row in enumerate(case["real_metadata"]):
            _score_pack(row)
            if (row["id"], row["score"]) not in successful:
                raise ValueError("Every approved donor must originate from a status-ok local score.")
            records.append({"case_id": case_id, "index": index, "row": row})
        result[case_id]["permuted_metadata"] = deepcopy(case["real_metadata"])
    if len(records) < 2:
        raise ValueError("At least two approved URL records are required for a different-URL control.")
    # Seeded hash ordering avoids global RNG state; attempts depend only on URLs,
    # never scores, labels, provider responses, or the apparent treatment effect.
    for attempt in range(1000):
        ordered = sorted(records, key=lambda r: canonical_sha(
            [seed, "URL-record-cycle", attempt, r["case_id"], r["index"], r["row"]["url"]]))
        if all(left["row"]["url"] != right["row"]["url"]
               for left, right in zip(ordered, ordered[1:] + ordered[:1])):
            break
    else:
        raise ValueError("No different-URL cycle is possible under the deterministic design.")
    mapping = []
    for receiver, donor in zip(ordered, ordered[1:] + ordered[:1]):
        own, other = receiver["row"], donor["row"]
        transferred = {"id": own["id"], "url": own["url"], **_score_pack(other)}
        result[receiver["case_id"]]["permuted_metadata"][receiver["index"]] = transferred
        mapping.append({"receiver_case_id": receiver["case_id"], "receiver_index": receiver["index"],
            "receiver_url_id": own["id"], "receiver_url": own["url"],
            "donor_case_id": donor["case_id"], "donor_index": donor["index"],
            "donor_url_id": other["id"], "donor_url": other["url"], "donor_status": "ok",
            "receiver_real_pack": _score_pack(own), "donor_pack": _score_pack(other),
            "score_unchanged": own["score"] == other["score"],
            "risk_unchanged": own["risk_level"] == other["risk_level"],
            "pack_unchanged": _score_pack(own) == _score_pack(other)})
    return result, mapping


def requests_for(sms, prepared, model, seed=SEED):
    requests, cells = {}, []
    for case in sms:
        item = prepared[case["id"]]
        base = None
        for arm in ARMS:
            rows = [] if arm == ARMS[0] else item["real_metadata" if arm == ARMS[1] else "permuted_metadata"]
            payload, included = build_payload(text=case["text"],
                urls=[{**row, "status": "ok"} for row in rows], include_ml=bool(rows),
                model=model, max_tokens=2048, thinking="disabled")
            data = json.loads(payload["messages"][1]["content"])
            actual_metadata = data.pop("url_results", [])
            if actual_metadata != rows or included != bool(rows):
                raise ValueError("The provider-visible metadata differs from the registered arm.")
            if base is None:
                base = data
            if data != base:
                raise ValueError("Only URL metadata may vary between control arms.")
            key = case["id"] + "::" + fingerprint(payload)[:16]
            requests.setdefault(key, {"key": key, "case_id": case["id"], "profile": "core",
                "thinking": "disabled", "text": case["text"], "payload": payload})
            cells.append({"id": case["id"], "arm": arm, "request_key": key,
                "URL_context_available": bool(item["real_metadata"]),
                "local_URL_count": len(item["intake"]["urls"]),
                "approved_URL_count": len(item["real_metadata"])})
    url_ids = sorted((r["id"] for r in sms if prepared[r["id"]]["real_metadata"]),
                     key=lambda case_id: canonical_sha([seed, "fixed-pilot-cases", case_id]))
    if len(url_ids) < 4:
        raise ValueError("The fixed pilot requires four URL cases selected without outputs or scores.")
    pilot_ids = url_ids[:4]
    lookup = {(r["id"], r["arm"]): r["request_key"] for r in cells}
    pilot_keys = list(dict.fromkeys(lookup[(case_id, arm)] for case_id in pilot_ids for arm in ARMS))
    pilot = [requests[key] for key in pilot_keys]
    remainder = sorted((r for key, r in requests.items() if key not in pilot_keys),
                       key=lambda r: canonical_sha([seed, "remaining-requests", r["key"]]))
    return pilot + remainder, cells, pilot_ids, len(pilot)


def prepare(out, pack=DEFAULT_PACK, labels=DEFAULT_LABELS, seed=SEED):
    out, pack, labels = Path(out), Path(pack).resolve(), Path(labels).resolve()
    inputs = out.with_name(out.name + "_inputs")
    if out.exists() or inputs.exists():
        raise ValueError("Choose fresh output and input directories; preserve previous experiments.")
    sms, refs, reference = load_scope(pack, labels)
    model = CharURLService()
    scored = score_cases(sms, model)
    failures = [{"case_id": case_id, "result": row} for case_id, case in scored.items()
                for row in case["raw_url_results"] if row.get("status") != "ok"]
    if not model.status()["ready"] or failures:
        inputs.mkdir(parents=True)
        write_json(inputs / "prepared.json", scored)
        write_json(inputs / "local_preflight.json", {"URL_model": model.status(), "failures": failures,
            "messages": len(sms), "registered": False, "API_calls": 0,
            "reason": "Local scoring failed; preserve diagnostics without redefining treatment availability."})
        raise ValueError("Local URL scoring failed before registration; diagnostics retained in " + str(inputs))
    prepared, mapping = permute_metadata(scored, seed)
    requests, cells, pilot_ids, pilot_count = requests_for(sms, prepared, Settings().llm_model, seed)
    assets = sorted(p for p in model.path.rglob("*") if p.is_file()) + [model.preprocessing_path]
    assets += sorted(p for p in (ROOT / "app/services/url/resources").rglob("*") if p.is_file())
    corpus = (ROOT / Settings().rag_corpus).resolve()
    assets += [corpus, corpus.with_name("manifest.json")]
    versions = {"python": sys.version, "packages": {name: version(name) for name in
        ("numpy", "scipy", "scikit-learn", "idna", "pydantic", "httpx")},
        "intake_version": INTAKE_VERSION, "policy_version": POLICY_VERSION,
        "classification_profile": PROFILE, "URL_model": model.status(),
        "assets_sha256": {str(path.resolve()): sha(path) for path in assets},
        "corpus_role": "reference locked for reproducibility; no retrieval in classification"}
    inputs.mkdir(parents=True)
    write_json(inputs / "prepared.json", prepared)
    write_json(inputs / "versions.json", versions)
    write_jsonl(inputs / "permutation_mapping.jsonl", mapping)
    write_jsonl(inputs / "cells.jsonl", cells)
    ref_by_id = {r["id"]: r["label"] for r in refs}
    metadata = {"pack": str(pack), "labels": str(labels), "inputs": str(inputs.resolve()),
        "arms": list(ARMS), "seed": seed, "logical_cells": len(cells), "messages": len(sms),
        "URL_context_cases": sum(bool(r["real_metadata"]) for r in prepared.values()),
        "URL_context_positive_references": sum(ref_by_id[key] == 1 and bool(r["real_metadata"])
                                               for key, r in prepared.items()),
        "permuted_URL_records": len(mapping), "unchanged_score_records": sum(r["score_unchanged"] for r in mapping),
        "unchanged_risk_records": sum(r["risk_unchanged"] for r in mapping),
        "unchanged_pack_records": sum(r["pack_unchanged"] for r in mapping),
        "permutation_method": "single seeded cycle across approved URL records; different donor URL; score/risk/cutoffs transferred together",
        "pilot_case_ids": pilot_ids, "pilot_logical_cells": 12, "pilot_unique_requests": pilot_count,
        "pacing_seconds": 4, "reference_status": reference["status"],
        "reference_judge": reference["reference_judge"], "reference_counts": {"positive": 4, "negative": 54, "UNKNOWN": 22},
        "purpose": "Metadata-only real versus deliberately wrong coherent URL evidence diagnostic",
        "permuted_arm_for_deployment": False, "human_gold": False, "independent_accuracy": None,
        "reserve_inference": False, "relabeling": False, "selection_by_scores_or_outputs": False,
        "identical_payloads_share_response": True, "same_schema_model_decoding_cap_thinking": True,
        "RAG_not_in_classification": True, "cost": "unknown; provider rates not assumed"}
    locks = [pack / "manifest.json", pack / "sms.jsonl", labels / "labels.jsonl", labels / "labels_manifest.json"]
    locks += assets + list(inputs.iterdir()) + [ROOT / "tests/messages/test_url_score_control.py"]
    config = registered.register(out, requests, stage="core_URL_score_control_dev", metadata=metadata,
                                 locks=locks, max_tokens=2048, token_budget=300000)
    # Registration is still preparation: pin the concrete paced single-worker
    # policy before returning anything that can be executed.
    config.update(workers=1, timeout_seconds=45)
    write_json(out / "execution.json", config)
    (out / "registration.sha256").write_text(sha(out / "execution.json") + "\n")
    return config


async def run(out, *, live=False, transport=None, limit=None):
    """Use the registered paced controller, including the first-segment pilot."""
    return await controlled_run.run(out, parse_response, live=live, limit=limit, inner=transport)


def _operations(records):
    values = list(records)
    return {"requests": len(values), "valid": sum(r["parsed"]["status"] == "ok" for r in values),
        "errors": dict(Counter(r["parsed"].get("code") for r in values if r["parsed"]["status"] != "ok")),
        "usage": {field: sum(r.get("usage", {}).get(field, 0) for r in values)
                  for field in ("prompt_tokens", "completion_tokens", "total_tokens")},
        "usage_missing": sum("total_tokens" not in r.get("usage", {}) for r in values),
        "median_elapsed_ms": statistics.median(r["elapsed_ms"] for r in values) if values else None,
        "total_elapsed_ms": sum(r["elapsed_ms"] for r in values), "cost": None, "cost_status": "unknown"}


def _transitions(labels, left, right):
    result = Counter(false_alarm_to_correct_low=0, false_alarm_to_unknown_or_error=0, correct_decision_lost=0)
    for label, a, b in zip(labels, left, right):
        pa, pb = prediction(a), prediction(b)
        result["false_alarm_to_correct_low"] += label == 0 and pa == 1 and pb == 0
        result["false_alarm_to_unknown_or_error"] += label == 0 and pa == 1 and pb is None
        result["correct_decision_lost"] += pa == label and pb != label
    return dict(result)


def report(out):
    out = Path(out)
    if not registered.verify(out, parse_response)["complete"]:
        raise ValueError("Complete and verify every registered request before reporting quality.")
    cfg, _ = registered.load(out)
    _, records = registered.checkpoints(out, cfg)
    labels = {r["id"]: r["label"] for r in read_jsonl(Path(cfg["metadata"]["labels"]) / "labels.jsonl")}
    cells = read_jsonl(Path(cfg["metadata"]["inputs"]) / "cells.jsonl")
    rows = []
    for cell in cells:
        record = records[(cfg["stage"], cell["request_key"])]
        parsed = record["parsed"]
        rows.append({**cell, "label": labels[cell["id"]], "status": parsed["status"],
            "error": parsed.get("code"), "level": parsed["verdict"]["risk_level"] if parsed["status"] == "ok" else "UNKNOWN",
            "semantic_UNKNOWN": parsed["status"] == "ok" and parsed["verdict"]["risk_level"] == "UNKNOWN",
            "usage": record.get("usage", {}), "elapsed_ms": record["elapsed_ms"]})
    result = {"reference_status": cfg["metadata"]["reference_status"], "reference_judge": cfg["metadata"]["reference_judge"],
        "reference_counts": cfg["metadata"]["reference_counts"], "independent_accuracy": None,
        "physical_run": _operations(records.values()), "logical_cells": len(rows),
        "aliased_cells": len(rows) - len(records), "arms": {}, "URL_subset": {}, "paired": {},
        "policy": "UNKNOWN and technical errors remain misses in full-reference accuracy/recall/F1; UNKNOWN references are separate",
        "control_limitations": {key: cfg["metadata"][key] for key in
            ("permuted_arm_for_deployment", "reserve_inference", "URL_context_cases", "URL_context_positive_references",
             "unchanged_score_records", "unchanged_risk_records", "unchanged_pack_records")}}
    lookup = {(r["id"], r["arm"]): r for r in rows}
    for arm in ARMS:
        selected = [r for r in rows if r["arm"] == arm]
        binary = [r for r in selected if r["label"] is not None]
        result["arms"][arm] = {**measure([r["label"] for r in binary], [r["level"] for r in binary]),
            "technical_errors_all_80": sum(r["status"] != "ok" for r in selected),
            "semantic_UNKNOWN_all_80": sum(r["semantic_UNKNOWN"] for r in selected),
            "unknown_reference_predictions": dict(Counter(r["level"] for r in selected if r["label"] is None)),
            "operations_with_shared_responses": _operations(records[(cfg["stage"], r["request_key"])] for r in selected)}
        url = [r for r in selected if r["URL_context_available"]]
        url_binary = [r for r in url if r["label"] is not None]
        result["URL_subset"][arm] = {**measure([r["label"] for r in url_binary], [r["level"] for r in url_binary]),
            "all_reference_cases": len(url), "positive_cases": sum(r["label"] == 1 for r in url_binary),
            "unknown_reference_cases": sum(r["label"] is None for r in url),
            "technical_errors": sum(r["status"] != "ok" for r in url)}
    for left_arm, right_arm in ((ARMS[0], ARMS[1]), (ARMS[0], ARMS[2]), (ARMS[1], ARMS[2])):
        pair = {}
        for subset in ("all_binary_references", "URL_binary_references"):
            left = [r for r in rows if r["arm"] == left_arm and r["label"] is not None
                    and (subset == "all_binary_references" or r["URL_context_available"])]
            y, a = [r["label"] for r in left], [r["level"] for r in left]
            b = [lookup[(r["id"], right_arm)]["level"] for r in left]
            pair[subset] = {**paired_comparison(y, a, b), "transitions": _transitions(y, a, b),
                "level_transitions": dict(Counter(f"{x}->{z}" for x, z in zip(a, b)))}
        result["paired"][left_arm + "__to__" + right_arm] = pair
    binary_labels = [value for value in labels.values() if value is not None]
    result["baselines"] = {"always_low": measure(binary_labels, ["LOW"] * len(binary_labels)),
                           "always_high": measure(binary_labels, ["HIGH"] * len(binary_labels))}
    write_jsonl(out / "decisions.jsonl", rows)
    write_json(out / "metrics.json", result)
    fmt = lambda value: "N/A" if value is None else f"{value:.2%}"
    lines = ["# URL score control on known development SMS", "",
        "Same 80 SMS and core schema, model, decoding, disabled thinking, 2048-token cap; only approved URL metadata changes.",
        "Existing assistant AI references: 4 positive, 54 negative, 22 UNKNOWN. No independent human accuracy claim.", "",
        "| Arm | Precision | Recall | F1 | Correct / binary n | Coverage | FP | Errors / 80 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for arm, metrics in result["arms"].items():
        lines.append(f"| {arm} | {fmt(metrics['precision'])} | {fmt(metrics['recall'])} | {fmt(metrics['f1'])} | "
            f"{metrics['tp'] + metrics['tn']}/{metrics['n']} | {fmt(metrics['coverage'])} | {metrics['fp']} | "
            f"{metrics['technical_errors_all_80']}/80 |")
    limits = result["control_limitations"]
    lines += ["", f"{len(rows)} logical cells used {len(records)} physical requests; identical payloads share a response.",
        f"URL metadata is available for {limits['URL_context_cases']} SMS, including {limits['URL_context_positive_references']} positive references. "
        "The URL subset cannot establish a recall benefit when it contains no positives.",
        f"Permuted records with unchanged score: {limits['unchanged_score_records']}; unchanged risk: {limits['unchanged_risk_records']}; "
        f"unchanged whole score pack: {limits['unchanged_pack_records']}. Donor mappings were frozen before inference.",
        "UNKNOWN and errors stay in denominators as misses. Paired tables distinguish false alarms becoming LOW from becoming UNKNOWN and correct decisions lost.",
        "The permuted arm deliberately uses wrong evidence for diagnosis only and must not be deployed. No gain is required or assumed.",
        "Tokens and latency are observed; monetary cost is unknown. Shared response totals in arms overlap; physical totals count each request once.",
        "All errors retained without retries or repair; no reserve inference, new gold labels, relabeling, or selection by scores/results."]
    (out / "report.md").write_text("\n".join(lines) + "\n")
    analysis = {"raw_seal_sha256": sha(out / "result_hashes.json"), "analysis_source_sha256": sha(__file__),
                "artifacts_sha256": {name: sha(out / name) for name in ("metrics.json", "decisions.jsonl", "report.md")}}
    if (out / "telemetry.jsonl").exists():
        analysis["telemetry_sha256"] = sha(out / "telemetry.jsonl")
    write_json(out / "analysis_manifest.json", analysis)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "run", "verify", "report"])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pack", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.command == "prepare":
        cfg = prepare(args.out, args.pack, args.labels, args.seed)
        result = {"requests": cfg["max_attempts"], "logical_cells": cfg["metadata"]["logical_cells"], "API_calls": 0}
    elif args.command == "run":
        result = asyncio.run(run(args.out, live=args.live, limit=args.limit))
    elif args.command == "verify":
        result = registered.verify(args.out, parse_response)
    else:
        result = report(args.out)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
