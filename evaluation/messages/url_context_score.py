"""Score imported URL/context predictions; never generate or claim API calls.

This validates data joins/counts, not the authenticity of provider responses.
Freeze an execution manifest before producing real predictions.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import statistics

from evaluation.data.sms import read_jsonl, sha, write_json
from evaluation.common.metrics import measure, prediction
from evaluation.data.url_context import ARMS, TARGETS, verify

LEVELS = {"HIGH", "WARNING", "LOW", "UNKNOWN"}


def expected_keys(cases, repetitions):
    if type(repetitions) is not int or not 1 <= repetitions <= 10:
        raise ValueError("Repetitions must be a preregistered integer from 1 to 10.")
    return {(c["id"], arm, rep) for c in cases for arm in ARMS
            for rep in ([0] if arm == "url_model" else range(1, repetitions + 1))}


def validate_records(cases, records, repetitions):
    expected = expected_keys(cases, repetitions)
    seen = {}
    for r in records:
        key = (r["id"], r["arm"], r["repeat"])
        if type(r["repeat"]) is not int or key not in expected or key in seen:
            raise ValueError("Duplicate or unexpected prediction ID/arm/repeat.")
        if r["status"] not in {"ok", "error"}:
            raise ValueError("Only completed attempts may be imported.")
        if r["status"] == "ok":
            if set(r.get("outputs", {})) != set(TARGETS) or any(v not in LEVELS for v in r["outputs"].values()):
                raise ValueError("Invalid output levels/targets.")
            if r["arm"] == "url_model" and any(r["outputs"][k] != "UNKNOWN" for k in ("message_behavior", "action_risk")):
                raise ValueError("URL-only model cannot claim message-context predictions.")
        elif r.get("outputs") or not str(r.get("error_code", "")).strip():
            raise ValueError("Error needs a code and must not include usable predictions.")
        seen[key] = r
    return seen, expected - seen.keys()


def level(record, target):
    return record["outputs"][target] if record["status"] == "ok" else "UNKNOWN"


def target_metrics(cases, lookup, arm, rep, target):
    binary = [c for c in cases if c["targets"][target] is not None]
    ambiguous = [c for c in cases if c["targets"][target] is None]
    metrics = measure([c["targets"][target] for c in binary],
                      [level(lookup[(c["id"], arm, rep)], target) for c in binary])
    metrics.update(reference_unknown_count=len(ambiguous), reference_unknown_predictions=dict(Counter(
        level(lookup[(c["id"], arm, rep)], target) for c in ambiguous)),
        technical_errors=sum(lookup[(c["id"], arm, rep)]["status"] == "error" for c in cases))
    return metrics


def paired(cases, lookup, rep, target, baseline="llm_only"):
    binary = [c for c in cases if c["targets"][target] is not None]
    counts = Counter(improved=0, regressed=0, both_correct=0, both_wrong=0)
    for c in binary:
        a_rep = 0 if baseline == "url_model" else rep
        a = prediction(level(lookup[(c["id"], baseline, a_rep)], target)) == c["targets"][target]
        b = prediction(level(lookup[(c["id"], "llm_url", rep)], target)) == c["targets"][target]
        counts["both_correct" if a and b else "both_wrong" if not a and not b else "improved" if b else "regressed"] += 1
    return {"n": len(binary), "domain_groups": len({c["group_id"] for c in binary}), **counts,
            "accuracy_delta": (counts["improved"] - counts["regressed"]) / len(binary) if binary else None}


def score(cases, urls, records, repetitions):
    lookup, missing = validate_records(cases, records, repetitions)
    result = {"cases": len(cases), "repetitions": repetitions, "completed_predictions": len(lookup),
        "expected_predictions": len(expected_keys(cases, repetitions)), "missing_predictions": len(missing),
        "metrics_ready": not missing, "metrics": None, "provider_requests": 0,
        "provenance": "Imported predictions. No verification of provider execution; not evidence an API experiment occurred.",
        "reference_status": "historical_source_labels_and_authored_context_not_independent_gold"}
    if missing:
        return result
    by_url = {r["id"]: r for r in urls}
    metrics = {}
    for task in ("url_only", "message_context"):
        task_cases = [c for c in cases if c["task"] == task]
        targets = ("url_risk",) if task == "url_only" else TARGETS
        metrics[task] = {}
        for target in targets:
            arms = ARMS if target == "url_risk" else ("llm_only", "llm_url")
            metric = {"by_repeat": {}, "paired": {}, "by_source_tier": {}, "repeat_summary": {}}
            for arm in arms:
                reps = [0] if arm == "url_model" else range(1, repetitions + 1)
                metric["by_repeat"][arm] = {str(rep): target_metrics(task_cases, lookup, arm, rep, target) for rep in reps}
                metric["repeat_summary"][arm] = {}
                for name in ("f1", "false_positive_rate", "coverage", "accuracy"):
                    values = [m[name] for m in metric["by_repeat"][arm].values() if m[name] is not None]
                    metric["repeat_summary"][arm][name] = {"mean": statistics.mean(values) if values else None,
                        "std_across_repeats": statistics.stdev(values) if len(values) > 1 else None, "defined_repeats": len(values)}
            for baseline in ("llm_only", "url_model") if target == "url_risk" else ("llm_only",):
                metric["paired"][baseline + "_to_llm_url"] = {
                    str(rep): paired(task_cases, lookup, rep, target, baseline) for rep in range(1, repetitions + 1)}
            strata = sorted({(by_url[c["url_id"]]["source"], by_url[c["url_id"]]["tier"]) for c in task_cases})
            for source, tier in strata:
                subset = [c for c in task_cases if (by_url[c["url_id"]]["source"], by_url[c["url_id"]]["tier"]) == (source, tier)]
                metric["by_source_tier"][source + "/" + tier] = {
                    arm: {str(rep): target_metrics(subset, lookup, arm, rep, target)
                          for rep in ([0] if arm == "url_model" else range(1, repetitions + 1))} for arm in arms}
            metrics[task][target] = metric
    context = [c for c in cases if c["task"] == "message_context"]
    groups = {
        "neutral_link": [c for c in context if c["variant"] == "neutral_link"],
        "benign_url_secret_request": [c for c in context if c["targets"]["url_risk"] == 0 and c["targets"]["message_behavior"] == 1],
        "risky_url_educational_quote": [c for c in context if c["targets"]["url_risk"] == 1 and c["url_role"] == "quoted"],
        "injection": [c for c in context if c["variant"].endswith("injection")],
    }
    result["context_checks"] = {name: {"n": len(subset), "by_repeat": {
        arm: {str(rep): target_metrics(subset, lookup, arm, rep, "action_risk") for rep in range(1, repetitions + 1)}
        for arm in ("llm_only", "llm_url")}} for name, subset in groups.items()}
    result["metrics"] = metrics
    result["uncertainty_note"] = "Repeat SD describes generation variability only. Contexts share domains/templates; no independent-row significance test is claimed. Reference uncertainty is not quantified."
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--split", choices=("dev", "test"), required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("Choose a new output file; preserve previous scores.")
    try:
        verify(args.pack)
        result = score(read_jsonl(args.pack / f"{args.split}.jsonl"), read_jsonl(args.pack / "urls.jsonl"),
                       read_jsonl(args.predictions), args.repetitions)
        result.update(split=args.split, hashes={"pack_manifest": sha(args.pack / "manifest.json"),
            "predictions": sha(args.predictions), "scorer": sha(__file__)})
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(2, f"Scoring stopped: {exc}\n")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.out, result)
    print(json.dumps({k: result[k] for k in ("cases", "completed_predictions", "missing_predictions", "metrics_ready")}, indent=2))


if __name__ == "__main__":
    main()
