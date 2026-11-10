"""Score every locked official-origin reference without inferring risk labels.

Only alert counts/fractions are described. No fits, requests, test scoring,
threshold selection, source-based whitelisting or app deployment occurs.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np

from app.services.url.character import DEFAULT_DEPLOYMENT, CharURLService
from evaluation.data.sms import read_jsonl, write_jsonl
from evaluation.data.official_urls import verify as verify_collection
from evaluation.data.prospective_urls import normalize_url
from evaluation.url.calibration import sha, write_json
from evaluation.url.source_robustness import ARMS, BASELINE, FIT_ORDER, ROOT, load_research_model, verify as verify_v3, www_model_view

REFERENCES = ROOT / "data/annotation/official_url_reference_v1"
V3 = ROOT / "artifacts/evaluations/url_source_robust_v3"
MODEL_INPUT = "raw URL only; exact V1 formatter for V1/B, V3 www_model_view for A/C; no label/source/evidence features"
SCOPE = ("Assistant-curated official-origin references with label=null, not independently benign gold. "
         "Counts describe model alerts only; neither alarm nor non-alarm establishes current website legitimacy. "
         "Self-served/self-linked documents are weak origin evidence. No automatic lowering of HIGH or whitelist.")


def validate_cases(cases, expected_n=29):
    if len(cases) != expected_n or len({row["id"] for row in cases}) != len(cases):
        raise ValueError("Use every collected reference exactly once, without subset selection.")
    for row in cases:
        if row["label"] is not None or row["label_scope"] != "official_origin_reference" or row["label_status"] != "assistant_curated" or row["reviewer_ids"]:
            raise ValueError("Reference must remain unlabelled and not human gold.")
        if row["exposure"]["prospective_eligible"] is not False:
            raise ValueError("Reference is not an independent prospective test.")
    return cases


def thresholds(summary):
    values = {}
    for arm in ARMS:
        fixed = summary[arm]["fixed_0.5"]["full_validation_threshold"]
        cutoff = summary[arm]["fpr_5pct"]["full_validation_threshold"]
        if fixed != .5 or cutoff is not None and (not np.isfinite(cutoff) or not 0 <= cutoff <= 1):
            raise ValueError("Invalid frozen validation threshold.")
        values[arm] = {"fixed_0.5": .5, "validation_fpr5_cutoff": cutoff}
    return values


def locked_paths(references=REFERENCES, v3=V3):
    paths = [Path(__file__), ROOT / "evaluation/data/official_urls.py",
        ROOT / "evaluation/data/prospective_urls.py", ROOT / "evaluation/data/sms.py",
        ROOT / "evaluation/url/source_robustness.py", ROOT / "evaluation/url/representation.py",
        ROOT / "evaluation/url/character_baseline.py", ROOT / "evaluation/url/calibration.py",
        ROOT / "evaluation/url/phishvn.py", ROOT / "app/services/url/character.py",
        ROOT / "models/inference_XGBoost_d6_s42/url_preprocessing.py",
        *[references / name for name in ["selection.json", "selection.json.sha256", "collection_locks.json",
                                         "records.jsonl", "attempts.jsonl", "collection.json"]],
        *[v3 / name for name in ["execution.json", "result_hashes.json", "summary.json", "verification.json"]],
        *[DEFAULT_DEPLOYMENT / name for name in ["export.json", "vocabulary.json", "weights.npz"]],
        *[v3 / "research_models" / arm / name for arm in FIT_ORDER
          for name in ["manifest.json", "vocabulary.json", "weights.npz"]]]
    plan = json.loads((references / "selection.json").read_text())
    paths.append(Path(plan["registration"]["path"]))
    for row in read_jsonl(references / "records.jsonl"):
        paths.extend([Path(row["evidence"]["snapshot_path"]), Path(row["evidence"]["robots"]["snapshot_path"])])
    return list(dict.fromkeys(path.resolve() for path in paths))


def prepare(out, references=REFERENCES, v3=V3):
    if out.exists():
        raise ValueError("Use a new output directory, preserving prior experiments.")
    verified = verify_collection(references)
    cases = validate_cases(read_jsonl(references / "records.jsonl"))
    cutoffs = thresholds(json.loads((v3 / "summary.json").read_text()))
    out.mkdir(parents=True)
    write_jsonl(out / "cases.jsonl", cases)
    write_json(out / "execution.json", {"schema": "official-url-diagnostic-v1-1.0",
        "created_at": datetime.now(timezone.utc).isoformat(), "scope": SCOPE,
        "references": str(references.resolve()), "v3": str(v3.resolve()),
        "collection_verification": verified, "cases_sha256": sha(out / "cases.jsonl"),
        "records": len(cases), "arms": list(ARMS), "thresholds": cutoffs,
        "threshold_source": "already locked V3 full-validation thresholds; never fitted on these references",
        "model_input": MODEL_INPUT, "selection": "all29 collected references, no risk/source/score selection; seven collection failures remain outside successful-reference scoring",
        "fit_count": 0, "API_calls": 0, "website_requests": 0, "deployment_changes": False,
        "input_hashes": {str(path): sha(path) for path in locked_paths(references, v3)}})


def check_lock(out):
    protocol = json.loads((out / "execution.json").read_text())
    if protocol["schema"] != "official-url-diagnostic-v1-1.0" or protocol["model_input"] != MODEL_INPUT or protocol["scope"] != SCOPE or protocol["arms"] != list(ARMS):
        raise ValueError("Locked configuration changed.")
    for path, digest in protocol["input_hashes"].items():
        if sha(path) != digest:
            raise ValueError("Locked input changed: " + path)
    if sha(out / "cases.jsonl") != protocol["cases_sha256"]:
        raise ValueError("Locked cases changed.")
    cases = validate_cases(read_jsonl(out / "cases.jsonl"), protocol["records"])
    if cases != read_jsonl(Path(protocol["references"]) / "records.jsonl"):
        raise ValueError("Cases differ from the entire collected reference set.")
    if thresholds(json.loads((Path(protocol["v3"]) / "summary.json").read_text())) != protocol["thresholds"]:
        raise ValueError("Frozen thresholds changed.")
    return protocol, cases


def predict_records(cases, baseline, models, preprocessing):
    """Metadata never enters inference; preserve a result or error for every arm/URL."""
    rows = []
    for arm, settings in ARMS.items():
        for case in cases:
            row = {"arm": arm, "id": case["id"], "url": case["url"], "status": "error", "score": None}
            try:
                if arm == "char_v1_baseline":
                    score = float(baseline._scores([case["url"]])[0])
                else:
                    text = www_model_view(case["url"], preprocessing) if settings["strip_www"] else preprocessing.format_url(case["url"])
                    score = float(models[arm].predict_proba([text])[0, 1])
                if not np.isfinite(score) or not 0 <= score <= 1:
                    raise ValueError("Model returned an invalid score.")
                row.update(status="ok", score=score)
            except Exception as exc:
                row["error"] = type(exc).__name__ + ": " + str(exc)[:200]
            rows.append(row)
    return rows


def group_membership(case):
    exposure = case["exposure"]
    separate = normalize_url(case["source_url"])[0] != case["normalized_url"]
    return ["all", "region:" + case["region"], *["tag:" + tag for tag in case["tags"]],
            "exposure_pool:" + exposure["assigned_pool"],
            "url_overlap:" + str(exposure["url_overlap"]).lower(),
            "domain_overlap:" + str(exposure["domain_overlap"]).lower(),
            "separate_source_document:" + str(separate).lower()]


def aggregate(cases, predictions, cutoffs):
    by_case = {row["id"]: row for row in cases}
    expected = {(arm, case_id) for arm in ARMS for case_id in by_case}
    actual = [(row["arm"], row["id"]) for row in predictions]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError("Missing, duplicated or unexpected model results.")
    results, decisions = {}, []
    for arm in ARMS:
        values = [row for row in predictions if row["arm"] == arm]
        policies = {}
        for policy, cutoff in cutoffs[arm].items():
            buckets = {}
            for row in values:
                case = by_case[row["id"]]
                if row["url"] != case["url"] or row["status"] not in {"ok", "error"}:
                    raise ValueError("Score metadata/status mismatch.")
                if row["status"] == "ok" and (row["score"] is None or not np.isfinite(row["score"]) or not 0 <= row["score"] <= 1):
                    raise ValueError("Invalid score in checkpoint.")
                if row["status"] == "error" and row["score"] is not None:
                    raise ValueError("Error cannot contain a usable score.")
                alert = None if row["status"] != "ok" else bool(cutoff is not None and row["score"] >= cutoff)
                decisions.append({"arm": arm, "policy": policy, "id": row["id"], "threshold": cutoff,
                                  "status": row["status"], "alert": alert})
                for name in group_membership(case):
                    bucket = buckets.setdefault(name, {"n": 0, "alert": 0, "non_alert": 0, "error": 0})
                    bucket["n"] += 1
                    bucket["error" if alert is None else "alert" if alert else "non_alert"] += 1
            for bucket in buckets.values():
                valid = bucket["n"] - bucket["error"]
                bucket["alert_fraction_all"] = bucket["alert"] / bucket["n"]
                bucket["alert_fraction_valid_scores"] = bucket["alert"] / valid if valid else None
                bucket["error_fraction"] = bucket["error"] / bucket["n"]
            policies[policy] = {"frozen_threshold": cutoff, "groups": buckets}
        results[arm] = policies
    return {"scope": SCOPE, "records": len(cases), "risk_labels": 0, "results": results}, decisions


def report(out, summary):
    lines = ["# Official-origin URL references: alert diagnostic", "", SCOPE, "",
             "Four frozen model arms; all29 references, zero fit/API/website requests. Historical validation thresholds are frozen before scoring. "
             "Groups can overlap (especially tags), so their counts must not be added. Errors remain in the all-record denominator and are shown separately.", "",
             "| Arm | Policy | Group | Records | Alerts | Non-alerts | Errors | Alert fraction (all) |",
             "|---|---|---|---:|---:|---:|---:|---:|"]
    for arm, policies in summary["results"].items():
        for policy, result in policies.items():
            for group, values in result["groups"].items():
                lines.append(f"| {arm} | {policy} | {group} | {values['n']} | {values['alert']} | {values['non_alert']} | {values['error']} | {100*values['alert_fraction_all']:.2f}% |")
    lines += ["", "These are alert fractions on curated unlabeled references, not false-positive rates or classification scores. "
              "Most source evidence is self-served/self-linked rather than a distinct document. Exposure is reported, not filtered. "
              "Neither successful source collection nor a low model score is a website safety certificate. The seven collection failures "
              "are preserved in the earlier collection log and were not silently replaced. Do not choose a new arm/threshold by minimizing these alerts."]
    (out / "report.md").write_text("\n".join(lines) + "\n")


def run(out):
    protocol, cases = check_lock(out)
    if (out / "run_started.json").exists():
        raise ValueError("Run already started; never rescore/retry to replace failures in place.")
    write_json(out / "run_started.json", {"started_at": datetime.now(timezone.utc).isoformat(), "maximum_reference_scores": len(cases) * len(ARMS)})
    verify_collection(Path(protocol["references"]))
    # Re-verifies original val score equivalence, without fitting or opening official test.
    verify_v3(Path(protocol["v3"]))
    baseline = CharURLService()
    if not baseline.load()["ready"]:
        raise ValueError(baseline.error)
    models = {arm: load_research_model(Path(protocol["v3"]) / "research_models" / arm) for arm in FIT_ORDER}
    predictions = predict_records(cases, baseline, models, baseline.preprocessing)
    write_jsonl(out / "scores.jsonl", predictions)
    summary, decisions = aggregate(cases, predictions, protocol["thresholds"])
    write_json(out / "summary.json", summary)
    write_jsonl(out / "decisions.jsonl", decisions)
    report(out, summary)
    names = ["execution.json", "cases.jsonl", "run_started.json", "scores.jsonl", "summary.json", "decisions.jsonl", "report.md"]
    write_json(out / "result_hashes.json", {name: sha(out / name) for name in names})
    verify(out)
    print(json.dumps({"records": len(cases), "model_reference_scores": len(predictions), "fits": 0,
                      "API_calls": 0, "website_requests": 0, "out": str(out)}), flush=True)


def verify(out):
    protocol, cases = check_lock(out)
    for name, digest in json.loads((out / "result_hashes.json").read_text()).items():
        if sha(out / name) != digest:
            raise ValueError("Diagnostic result changed: " + name)
    summary, decisions = aggregate(cases, read_jsonl(out / "scores.jsonl"), protocol["thresholds"])
    if summary != json.loads((out / "summary.json").read_text()) or decisions != read_jsonl(out / "decisions.jsonl"):
        raise ValueError("Recomputed alert counts or decisions differ.")
    write_json(out / "verification.json", {"verified": True, "records": len(cases),
        "model_reference_scores": len(cases) * len(ARMS), "decisions": len(decisions),
        "reference_risk_labels": 0, "fits": 0, "API_calls": 0, "website_requests": 0,
        "baseline_original_validation_bitwise_match_verified_before_reference_scoring": True,
        "all_collected_references_retained": True, "deployment_changes": False})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "run", "verify"])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    {"prepare": prepare, "run": run, "verify": verify}[args.command](args.out)


if __name__ == "__main__":
    main()
