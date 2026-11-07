"""Locked inference on all provisional OpenPhish candidates; no fit or network.

Single-source, positive-only reference labels cannot establish precision, F1,
accuracy, FPR, verified recall or deployment quality. This exposes every candidate
to adaptive diagnostics; never reuse them as an untouched future test.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform

import numpy as np
import xgboost

from app.ml_service import ModelService
from app.settings import Settings
from app.url_char_service import CharURLService, _versions
from .message_data import read_jsonl, sha, write_json, write_jsonl
from .openphish_candidates_v1 import verify as verify_candidates
from .url_diagnostics import wilson95
from .url_source_robust_v3 import ARMS, FIT_ORDER, load_research_model, www_model_view

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / "artifacts/evaluations/openphish_candidates_v1"
RESEARCH = ROOT / "artifacts/evaluations/url_source_robust_v3"
CHAR = ROOT / "artifacts/evaluations/url_char_baseline_v1/deployment"
XGB = ROOT / "models/inference_XGBoost_d6_s42"
CALIBRATION = ROOT / "artifacts/evaluations/url_calibration_v1/summary.json"
MODELS = ["XGBoost_production", "char_v1_baseline", *FIT_ORDER]
RESULTS = ["execution.json", "cases.jsonl", "inference_started.json", "scores.jsonl", "decisions.jsonl",
           "adaptive_exposure.jsonl", "summary.json", "report.md"]


def environment():
    return {"python": platform.python_version(), "xgboost": xgboost.__version__, **_versions()}


def cutoffs():
    research = json.loads((RESEARCH / "summary.json").read_text())
    xgb = json.loads(CALIBRATION.read_text())["policies"]["global_fpr_5pct"]["threshold_full_validation"]
    values = {"XGBoost_production": {"fixed_0.5": .5, "historical_validation_fpr_5pct": xgb}}
    values.update({name: {"fixed_0.5": .5, "historical_validation_fpr_5pct":
        research[name]["fpr_5pct"]["full_validation_threshold"]} for name in MODELS[1:]})
    for policies in values.values():
        for value in policies.values():
            if value is not None and (type(value) not in {int, float} or not np.isfinite(value) or not 0 <= value <= 1):
                raise ValueError("Invalid historical cutoff.")
    return values


def validate_cases(cases):
    if len(cases) != 200 or len({r["id"] for r in cases}) != 200 or len({r["domain"] for r in cases}) != 200:
        raise ValueError("Use exactly all 200 unique-domain locked candidates.")
    for row in cases:
        if (row["label_status"] != "external_source_provisional" or row["source_label"] != 1 or
                row["human_verified"] is not False or row["prospective_eligible"] is not False):
            raise ValueError("Do not promote source labels to verified references.")


def paths():
    return [Path(__file__), ROOT / "app/ml_service.py", ROOT / "app/settings.py", ROOT / "app/url_char_service.py",
        ROOT / "evaluation/url_source_robust_v3.py", ROOT / "evaluation/openphish_candidates_v1.py",
        ROOT / "evaluation/message_data.py", ROOT / "evaluation/url_diagnostics.py",
        CANDIDATES / "candidates.jsonl", CANDIDATES / "protocol.json", CANDIDATES / "result_hashes.json",
        CANDIDATES / "feed.raw.txt", RESEARCH / "summary.json", RESEARCH / "execution.json",
        RESEARCH / "result_hashes.json", CALIBRATION,
        *[XGB / name for name in ["model.ubj", "config.json", "predict_url.py", "url_features.py", "url_preprocessing.py"]],
        *[CHAR / name for name in ["export.json", "vocabulary.json", "weights.npz"]],
        *[RESEARCH / "research_models" / arm / name for arm in FIT_ORDER for name in ["manifest.json", "vocabulary.json", "weights.npz"]]]


def prepare(out):
    out = Path(out)
    if out.exists():
        raise ValueError("Choose new output; never overwrite diagnostics.")
    verify_candidates(CANDIDATES)
    cases = read_jsonl(CANDIDATES / "candidates.jsonl")
    validate_cases(cases)
    policies = cutoffs()
    out.mkdir(parents=True)
    write_jsonl(out / "cases.jsonl", cases)
    write_json(out / "execution.json", {"schema": "openphish-model-diagnostic-v1-1.0",
        "registered_at": datetime.now(timezone.utc).isoformat(), "models": MODELS,
        "case_count": 200, "cases_sha256": sha(out / "cases.jsonl"), "thresholds": policies,
        "selection": "all previously hash-selected 200 candidates; no selection based on scores or response success",
        "fit_count": 0, "HTTP_requests": 0, "API_calls": 0, "app_changes": False,
        "threshold_provenance": "fixed .5; character V3 summary full-validation FPR5; XGB calibration_v1 global_fpr_5pct full-validation cutoff",
        "reference": "one-source positive-only external_source_provisional; not independent human labels, test gold or known first-seen",
        "metrics": "alert count / all 200; errors UNKNOWN kept in denominator; Wilson95 illustrative independence assumption only",
        "forbidden_metrics": ["precision", "F1", "accuracy", "FPR"],
        "exposure": "all 200 are now adaptive diagnostic cases, never an untouched future test; no winner selection/deployment from this run",
        "environment": environment(),
        "input_hashes": {str(path.resolve()): sha(path) for path in paths()}})


def check_lock(out):
    protocol = json.loads((out / "execution.json").read_text())
    if protocol["environment"] != environment():
        raise ValueError("Registered numerical environment changed.")
    if protocol["models"] != MODELS or protocol["thresholds"] != cutoffs() or sha(out / "cases.jsonl") != protocol["cases_sha256"]:
        raise ValueError("Registered cases/models/policies changed.")
    for path, expected in protocol["input_hashes"].items():
        if sha(path) != expected:
            raise ValueError("Registered code/model/source changed: " + path)
    return protocol


def scorers():
    char = CharURLService()
    if not char.load()["ready"]:
        raise ValueError(char.error)
    xgb = ModelService(Settings(model_dir=str(XGB)))
    if not xgb.load()["ready"] or xgb.path != XGB.resolve() or xgb.spec.get("kind") != "xgboost":
        raise ValueError("Production XGB bundle unavailable or wrong model resolved.")
    def xgb_score(url):
        result = xgb.predict([url])[0]
        if result.get("status") != "ok":
            raise ValueError("Production preprocessing/inference failed.")
        return result["score"]
    handlers = {"XGBoost_production": xgb_score,
                "char_v1_baseline": lambda url: float(char._scores([url])[0])}
    for arm in FIT_ORDER:
        model = load_research_model(RESEARCH / "research_models" / arm)
        def research_score(url, model=model, arm=arm):
            text = www_model_view(url, char.preprocessing) if ARMS[arm]["strip_www"] else char.preprocessing.format_url(url)
            return float(model.predict_proba([text])[0, 1])
        handlers[arm] = research_score
    return handlers


def score_cases(cases, handlers):
    if set(handlers) != set(MODELS):
        raise ValueError("All five registered model handlers are required.")
    rows = []
    for model in MODELS:
        for case in cases:
            base = {"id": case["id"], "model": model}
            try:
                value = float(handlers[model](case["url"]))
                if not np.isfinite(value) or not 0 <= value <= 1:
                    raise ValueError("Invalid model score.")
                rows.append({**base, "status": "ok", "score": value, "error_type": None})
            except Exception as exc:
                rows.append({**base, "status": "error", "score": None, "error_type": type(exc).__name__})
    return rows


def analyze(cases, scores, policies):
    ids = {r["id"] for r in cases}
    if len(scores) != len(cases) * len(MODELS) or {(r["model"], r["id"]) for r in scores} != {(m, i) for m in MODELS for i in ids}:
        raise ValueError("Missing/duplicate/unregistered scores; keep every case.")
    result, decisions = {}, []
    for model in MODELS:
        selected = [r for r in scores if r["model"] == model]
        for row in selected:
            if row["status"] not in {"ok", "error"}:
                raise ValueError("Unknown model status.")
            if row["status"] == "ok":
                if type(row["score"]) not in {float, int} or not np.isfinite(row["score"]) or not 0 <= row["score"] <= 1:
                    raise ValueError("Invalid successful score.")
            elif row["score"] is not None:
                raise ValueError("Failed inference cannot contain a score.")
        result[model] = {}
        for policy, threshold in policies[model].items():
            alerts = sum(row["status"] == "ok" and threshold is not None and row["score"] >= threshold for row in selected)
            errors = sum(row["status"] == "error" for row in selected)
            result[model][policy] = {"threshold": threshold, "source_provisional_n": len(cases),
                "alerts": alerts, "non_alerts": len(cases) - alerts - errors, "unknown_errors": errors,
                "alert_rate_all_source_candidates": alerts / len(cases), "coverage": (len(cases) - errors) / len(cases),
                "illustrative_alert_rate_wilson95_independent_URL_assumption": wilson95(alerts, len(cases))}
            for row in selected:
                decisions.append({"id": row["id"], "model": model, "policy": policy, "threshold": threshold,
                    "decision": "UNKNOWN" if row["status"] == "error" else "ALERT" if threshold is not None and row["score"] >= threshold else "NO_ALERT"})
    return result, decisions


def report(out, result):
    lines = ["# OpenPhish provisional-source diagnostic, all 200 candidates", "",
        "No new fitting, threshold selection, HTTP/API or deployment. All 200 cases retained, errors UNKNOWN. "
        "Single-source positive-only labels are provisional, not human-verified gold, an untouched test or first-seen evidence.", "",
        "| Model | Historical policy | Cutoff | Alerts / all 200 | Unknown | Alert proportion | Wilson95 illustrative |",
        "|---|---|---:|---:|---:|---:|---:|"]
    for model, policies in result.items():
        for policy, metric in policies.items():
            interval = metric["illustrative_alert_rate_wilson95_independent_URL_assumption"]
            lines.append(f"| {model} | {policy} | {metric['threshold']} | {metric['alerts']}/{metric['source_provisional_n']} | "
                f"{metric['unknown_errors']} | {100*metric['alert_rate_all_source_candidates']:.2f}% | "
                f"{100*interval['lower']:.2f}–{100*interval['upper']:.2f}% |")
    lines += ["", "No Precision/F1/accuracy/FPR: no benign controls and no verified URL-risk labels. "
        "Alert proportion is agreement with source-positive candidates, not verified recall. Wilson assumes independent URLs; "
        "shared campaigns/hosting may make intervals too narrow, and intervals ignore label error/source shift. "
        "FPR5 cutoffs were frozen from historical validation, not estimated here; they do not imply 5% FPR in this feed. "
        "Different full-validation cutoffs are not a matched prospective operating point. "
        "Do not choose/deploy a winner from this run. Every candidate is now adaptive/exposed: future holdout exclusion must include "
        "adaptive_exposure.jsonl and unresolved campaigns. No source URLs or raw feed are redistributed in this report."]
    (out / "report.md").write_text("\n".join(lines) + "\n")


def run(out):
    out = Path(out)
    protocol = check_lock(out)
    if (out / "inference_started.json").exists():
        raise ValueError("Inference already started; do not rerun or replace failures.")
    cases = read_jsonl(out / "cases.jsonl")
    validate_cases(cases)
    write_json(out / "inference_started.json", {"started_at": datetime.now(timezone.utc).isoformat(), "new_fits": 0})
    rows = score_cases(cases, scorers())
    write_jsonl(out / "scores.jsonl", rows)
    result, decisions = analyze(cases, rows, protocol["thresholds"])
    write_jsonl(out / "decisions.jsonl", decisions)
    write_jsonl(out / "adaptive_exposure.jsonl", [{"url": r["url"], "domain": r["domain"], "campaign": None,
        "exposure": "adaptive", "reason": "openphish-model-diagnostic-v1; five-model comparison, not an untouched future test"} for r in cases])
    write_json(out / "summary.json", result)
    report(out, result)
    write_json(out / "result_hashes.json", {name: sha(out / name) for name in RESULTS})
    verify(out)
    print(json.dumps({"completed": True, "candidates": len(cases), "model_attempts": len(rows),
        "decisions": len(decisions), "new_fits": 0, "HTTP_requests": 0, "raw_urls_printed": False}))


def verify(out):
    out = Path(out)
    protocol = check_lock(out)
    hashes = json.loads((out / "result_hashes.json").read_text())
    if set(hashes) != set(RESULTS):
        raise ValueError("Incomplete result manifest.")
    for name, expected in hashes.items():
        if sha(out / name) != expected:
            raise ValueError("Saved result changed: " + name)
    cases, scores = read_jsonl(out / "cases.jsonl"), read_jsonl(out / "scores.jsonl")
    validate_cases(cases)
    if cases != read_jsonl(CANDIDATES / "candidates.jsonl"):
        raise ValueError("Original frozen candidates differ.")
    result, decisions = analyze(cases, scores, protocol["thresholds"])
    if result != json.loads((out / "summary.json").read_text()) or decisions != read_jsonl(out / "decisions.jsonl"):
        raise ValueError("Recomputed decisions/metrics differ.")
    exposures = read_jsonl(out / "adaptive_exposure.jsonl")
    if (len(exposures) != len(cases) or {r["url"] for r in exposures} != {r["url"] for r in cases}
            or any(r["exposure"] != "adaptive" for r in exposures)):
        raise ValueError("All candidates must become adaptive exclusions.")
    write_json(out / "verification.json", {"passed": True, "model_records": len(scores), "decisions": len(decisions),
        "new_inference": 0, "new_fits": 0, "HTTP_requests": 0, "source_labels_provisional": True,
        "candidate_exposure": "adaptive", "future_holdout_eligible": False})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "run", "verify"])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    {"prepare": prepare, "run": run, "verify": verify}[args.action](args.out)


if __name__ == "__main__":
    main()
