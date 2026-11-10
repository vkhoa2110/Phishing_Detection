"""Validation-only alarm-budget diagnostics for the unchanged production URL model.

Domain cross-fitting audits threshold selection, not model selection or a new test.
No API calls, model fitting, test predictions, or deployment writes.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import zipfile

import numpy as np
import pandas as pd
import sklearn
from sklearn.metrics import confusion_matrix, f1_score, precision_score, recall_score

from app.core.settings import ROOT
HISTORICAL = ROOT / "artifacts/evaluations/phishvn_official_v1"
MODEL = ROOT / "models/inference_XGBoost_d6_s42"
ARCHIVE = ROOT / "data/raw/PhishVN_v3.1.0_open.zip"
POLICIES = {
    "legacy_warning": {"fixed": "warning_threshold"},
    "current_high": {"fixed": "high_threshold"},
    "fixed_0.5": {"threshold": .5},
    "global_fpr_5pct": {"budget": .05, "per_source": False},
    "global_fpr_1pct": {"budget": .01, "per_source": False},
    "worst_source_fpr_5pct": {"budget": .05, "per_source": True},
    "worst_source_fpr_1pct": {"budget": .01, "per_source": True},
}
FOLDS = 5


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def fold_for(domain):
    key = "url-calibration-v1|" + domain
    return int(hashlib.sha256(key.encode()).hexdigest(), 16) % FOLDS


def validate(frame):
    required = {"id", "url", "labels", "source", "tier", "domain_group", "score"}
    if not required <= set(frame) or frame.empty or frame[list(required)].isna().any().any():
        raise ValueError("Missing validation fields/rows.")
    if frame.id.duplicated().any() or frame.url.duplicated().any():
        raise ValueError("Duplicate validation ID/URL.")
    if not frame.labels.isin([0, 1]).all() or not frame.tier.isin(["gold", "silver", "bronze"]).all():
        raise ValueError("Invalid reference labels/tiers.")
    scores = frame.score.to_numpy(dtype=float)
    if not np.isfinite(scores).all() or not ((scores >= 0) & (scores <= 1)).all():
        raise ValueError("Invalid probability scores.")
    if any(frame[c].astype(str).str.strip().eq("").any() for c in ("id", "source", "domain_group")):
        raise ValueError("Empty identifiers/source/domain.")


def inputs():
    config = json.loads((MODEL / "config.json").read_text())
    historical = json.loads((HISTORICAL / "manifest.json").read_text())["configuration"]
    for key, path in (("model_sha256", MODEL / "model.ubj"), ("config_sha256", MODEL / "config.json"),
                      ("archive_sha256", ARCHIVE)):
        if sha(path) != historical[key]:
            raise ValueError("Historical input changed: " + str(path))
    frame = pd.read_csv(HISTORICAL / "val_predictions.csv", float_precision="round_trip")
    validate(frame)
    # Read only the official validation table; never load train/test labels or scores.
    with zipfile.ZipFile(ARCHIVE) as archive:
        raw = archive.read("data/splits/url_val.csv")
        manifest = archive.read("MANIFEST.txt").decode()
    expected = next(line.split()[0] for line in manifest.splitlines() if "data/splits/url_val.csv" in line)
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("Official validation MANIFEST mismatch.")
    meta = pd.read_csv(io.BytesIO(raw), dtype=str).set_index("id", verify_integrity=True)
    if set(frame.id) != set(meta.index) or set(meta.split) != {"val"}:
        raise ValueError("Saved rows differ from official validation IDs.")
    aligned = meta.loc[frame.id]
    for col in ("url", "source", "tier"):
        if aligned[col].tolist() != frame[col].tolist():
            raise ValueError("Saved validation metadata mismatch: " + col)
    if aligned.label.map({"phishing": 1, "benign": 0}).tolist() != frame.labels.tolist():
        raise ValueError("Saved validation labels changed.")
    frame["fold"] = frame.domain_group.map(fold_for)
    return frame, config["thresholds"]


def choose_cutoff(frame, budget, per_source=False):
    """Smallest nonnegative cutoff satisfying empirical benign FPR constraints.

    Uses negative scores only. nextafter excludes the full boundary tie under >=.
    No feasible cutoff in [0,1] returns None (disable alarms, not mark URLs safe).
    """
    if not 0 <= budget < 1:
        raise ValueError("Budget must be in [0, 1).")
    negatives = frame.loc[frame.labels.eq(0)]
    if negatives.empty:
        raise ValueError("Calibration needs benign examples.")
    groups = [g for _, g in negatives.groupby("source")] if per_source else [negatives]
    cutoffs = []
    for group in groups:
        scores = np.sort(group.score.to_numpy(dtype=float))[::-1]
        allowed = math.floor(budget * len(scores) + 1e-12)
        cutoffs.append(float(np.nextafter(scores[allowed], np.inf)))
    value = max(cutoffs)
    return value if value <= 1 else None


def threshold_for(frame, policy, cutoffs):
    if "fixed" in policy:
        return cutoffs[policy["fixed"]]
    if "threshold" in policy:
        return policy["threshold"]
    return choose_cutoff(frame, policy["budget"], policy["per_source"])


def alarm(scores, threshold):
    return np.zeros(len(scores), dtype=bool) if threshold is None else np.asarray(scores) >= threshold


def measure(frame, predicted):
    y, predicted = frame.labels.to_numpy(dtype=int), np.asarray(predicted, dtype=bool)
    if len(y) != len(predicted):
        raise ValueError("Prediction length differs.")
    tp, fp = int(((y == 1) & predicted).sum()), int(((y == 0) & predicted).sum())
    positive, negative = int((y == 1).sum()), int((y == 0).sum())
    both = bool(positive and negative)
    return {"n": len(y), "domains": frame.domain_group.nunique(), "positive": positive, "negative": negative,
            "tp": tp, "fp": fp, "fn": positive - tp, "tn": negative - fp,
            "recall": tp / positive if positive else None,
            "false_positive_rate": fp / negative if negative else None,
            "precision": (tp / (tp + fp) if tp + fp else 0.) if both else None,
            "f1": 2 * tp / (positive + tp + fp) if both else None}


def group_metrics(frame, predicted):
    # Reset indexes so each subgroup selects the correct positions in the OOF array.
    frame = frame.reset_index(drop=True)
    predicted = np.asarray(predicted)
    groups = {"full": np.ones(len(frame), dtype=bool),
              "gold_silver": frame.tier.isin(["gold", "silver"]).to_numpy()}
    groups.update({"source:" + name: frame.source.eq(name).to_numpy() for name in sorted(frame.source.unique())})
    groups.update({"tier:" + name: frame.tier.eq(name).to_numpy() for name in sorted(frame.tier.unique())})
    return {name: measure(frame.loc[mask], predicted[mask]) for name, mask in groups.items()}


def prevalence_scenarios(recall, fpr):
    # Hypothetical class prior; assumes unchanged conditional rates and source mix.
    result = []
    for prior in [.001, .01, .05]:
        tp, fp, fn = 10000 * prior * recall, 10000 * (1 - prior) * fpr, 10000 * prior * (1 - recall)
        result.append({"positive_prior": prior, "per_urls": 10000, "expected_tp": tp,
                       "expected_fp": fp, "expected_fn": fn,
                       "expected_precision": tp / (tp + fp) if tp + fp else None})
    return result


def evaluate(frame, cutoffs):
    policies, prediction_rows = {}, []
    for name, policy in POLICIES.items():
        selected = threshold_for(frame, policy, cutoffs)
        fitted = group_metrics(frame, alarm(frame.score, selected))
        oof, fold_results = np.zeros(len(frame), dtype=bool), []
        for fold in range(FOLDS):
            mask = frame.fold.eq(fold).to_numpy()
            calibration, heldout = frame.loc[~mask], frame.loc[mask]
            if not len(heldout) or set(calibration.domain_group) & set(heldout.domain_group):
                raise ValueError("Empty/overlapping domain fold.")
            threshold = threshold_for(calibration, policy, cutoffs)
            predicted = alarm(heldout.score, threshold)
            oof[mask] = predicted
            fold_results.append({"fold": fold, "threshold": threshold,
                "calibration_n": len(calibration), "calibration_domains": calibration.domain_group.nunique(),
                "calibration_benign_sources": calibration.loc[calibration.labels.eq(0)].source.value_counts().to_dict(),
                "heldout": group_metrics(heldout, predicted)})
            for row, output in zip(heldout.to_dict("records"), predicted):
                prediction_rows.append({k: row[k] for k in ["id", "labels", "domain_group", "source", "tier", "score", "fold"]}
                                       | {"policy": name, "threshold": threshold, "alarm": int(output)})
        scored = group_metrics(frame, oof)
        core = scored["gold_silver"]
        policies[name] = {"policy": policy, "threshold_full_validation": selected,
            "resubstitution": fitted, "domain_crossfit": scored, "folds": fold_results,
            "hypothetical_prior_scenarios": prevalence_scenarios(core["recall"], core["false_positive_rate"])}
    return {"policies": policies}, pd.DataFrame(prediction_rows)


def report(out, summary):
    pct = lambda value: "N/A" if value is None else f"{100 * value:.2f}%"
    lines = ["# URL alarm calibration: historical validation only", "",
        "Production XGBoost scores unchanged. No test rows, retraining, API calls or deployment. "
        "5 deterministic domain folds select cutoffs on four folds and score the fifth. "
        "The model and old cutoffs previously used this validation; this is a dev diagnostic, not an independent estimate. "
        "New policies target empirical FPR, not a guaranteed population rate. Non-alert does not mean safe.", "",
        "| Policy | Full-val cutoff | OOF FP / negatives | OOF FPR | Core TP / positives | Core Recall | Bronze Recall |",
        "|---|---:|---:|---:|---:|---:|---:|"]
    for name, data in summary["policies"].items():
        m, core = data["domain_crossfit"]["full"], data["domain_crossfit"]["gold_silver"]
        value = data["threshold_full_validation"]
        threshold = "disabled" if value is None else f"{value:.9f}"
        lines.append(f"| {name} | {threshold} | {m['fp']}/{m['negative']} | {pct(m['false_positive_rate'])} | "
                     f"{core['tp']}/{core['positive']} | {pct(core['recall'])} | {pct(data['domain_crossfit']['tier:bronze']['recall'])} |")
    lines += ["", "The cutoff column is fitted on all validation and is NOT the five cross-fit cutoffs. "
              "Both resubstitution and fold-level data are saved in summary.json; all policies are retained.", "",
              "## Conditional source rates (out of fold)", "",
              "| Policy | Source | n | TP / positive | FP / negative | Recall | FPR |",
              "|---|---|---:|---|---|---:|---:|"]
    for name, data in summary["policies"].items():
        for group, m in data["domain_crossfit"].items():
            if group.startswith("source:"):
                lines.append(f"| {name} | {group[7:]} | {m['n']} | {m['tp']}/{m['positive']} | {m['fp']}/{m['negative']} | {pct(m['recall'])} | {pct(m['false_positive_rate'])} |")
    lines += ["", "## Hypothetical prevalence = 1%, per 10,000 URLs", "",
              "Assumes gold/silver positive recall and the same benign source mixture transfer unchanged. "
              "Not a measured production prevalence or forecast; only 24 positive references.", "",
              "| Policy | Expected TP | Expected FP | Expected FN | Expected precision |",
              "|---|---:|---:|---:|---:|"]
    for name, data in summary["policies"].items():
        m = data["hypothetical_prior_scenarios"][1]
        lines.append(f"| {name} | {m['expected_tp']:.1f} | {m['expected_fp']:.1f} | {m['expected_fn']:.1f} | {pct(m['expected_precision'])} |")
    lines += ["", "## Limits", "",
        "Source/tier labels are historical references, not independently adjudicated gold. "
        "Source, time and label quality remain confounded. Small benign sources cannot establish a reliable worst-source FPR. "
        "Fold variation is not a confidence interval. No calibrated-probability claim: a raw score of 0.9 does not establish 90% risk. "
        "A representative prospective calibration and separately sealed future test are still required. "
        "Keep the app's LOW/UNKNOWN/HIGH policy separate from this alarm-only diagnostic."]
    (out / "report.md").write_text("\n".join(lines) + "\n")


def verify(out):
    execution = json.loads((out / "execution.json").read_text())
    for path, digest in execution["input_hashes"].items():
        if sha(path) != digest:
            raise ValueError("Registered input/source changed: " + path)
    expected = json.loads((out / "result_hashes.json").read_text())
    for name, digest in expected.items():
        if sha(out / name) != digest:
            raise ValueError("Result changed: " + name)
    frame, cutoffs = inputs()
    summary = json.loads((out / "summary.json").read_text())
    predictions = pd.read_csv(out / "predictions.csv.gz", float_precision="round_trip")
    if len(predictions) != len(frame) * len(POLICIES) or predictions.duplicated(["policy", "id"]).any():
        raise ValueError("Missing/duplicate policy predictions.")
    checked = 0
    for name, policy in POLICIES.items():
        subset = predictions.loc[predictions.policy.eq(name)].set_index("id").loc[frame.id]
        for col in ["labels", "domain_group", "source", "tier", "score", "fold"]:
            if not np.array_equal(subset[col].to_numpy(), frame[col].to_numpy()):
                raise ValueError("Prediction metadata changed: " + col)
        for fold in range(FOLDS):
            mask = frame.fold.eq(fold).to_numpy()
            selected = threshold_for(frame.loc[~mask], policy, cutoffs)
            saved = subset.loc[frame.loc[mask].id, "threshold"]
            if not (saved.isna().all() if selected is None else np.allclose(saved, selected, rtol=0, atol=1e-15)):
                raise ValueError("Cross-fit cutoff mismatch.")
            if not np.array_equal(subset.alarm.to_numpy()[mask], alarm(frame.loc[mask].score, selected)):
                raise ValueError("Cross-fit decisions mismatch.")
        y, p = frame.labels.to_numpy(), subset.alarm.to_numpy()
        groups = group_metrics(frame, p)
        if groups != summary["policies"][name]["domain_crossfit"]:
            raise ValueError("Saved group metrics disagree.")
        for group, recorded in groups.items():
            mask = np.ones(len(frame), dtype=bool) if group == "full" else frame.tier.isin(["gold", "silver"]).to_numpy() if group == "gold_silver" else frame[group.split(":")[0]].eq(group.split(":")[1]).to_numpy()
            a, b = y[mask], p[mask]
            tn, fp, fn, tp = confusion_matrix(a, b, labels=[0, 1]).ravel()
            if [int(tp), int(fp), int(tn), int(fn)] != [recorded[k] for k in ["tp", "fp", "tn", "fn"]]:
                raise ValueError("Independent confusion-matrix check failed.")
            if set(a) == {0, 1}:
                for key, func in [("precision", precision_score), ("recall", recall_score), ("f1", f1_score)]:
                    if not math.isclose(recorded[key], func(a, b, zero_division=0), abs_tol=1e-12):
                        raise ValueError("Independent metric check failed.")
            checked += 1
    write_json(out / "verification.json", {"verified": True, "groups_checked": checked,
        "policy_predictions": len(predictions), "input_hashes_match": True, "result_hashes_match": True,
        "independent_math": "sklearn confusion matrix/precision/recall/F1", "API_calls": 0,
        "new_independent_test": False})
    return checked


def run(out):
    if out.exists():
        raise ValueError("Choose a new output directory; preserve previous runs.")
    frame, cutoffs = inputs()
    paths = [Path(__file__), HISTORICAL / "val_predictions.csv", HISTORICAL / "manifest.json",
             ARCHIVE, MODEL / "config.json", MODEL / "model.ubj"]
    out.mkdir(parents=True)
    write_json(out / "execution.json", {"schema": "url-calibration-1.0", "created_at": datetime.now(timezone.utc).isoformat(),
        "policies": POLICIES, "folds": FOLDS, "fold_rule": "SHA256(url-calibration-v1|domain) modulo 5; no label/score stratification",
        "selection_rule": "minimum cutoff in [0,1] meeting empirical negative-only FPR budget; None disables alarms; >= comparison",
        "historical_validation_already_used_for_model_and_old_thresholds": True, "new_independent_test": False,
        "API_calls": 0, "test_rows_loaded": 0, "app_thresholds_changed": False,
        "versions": {"numpy": np.__version__, "pandas": pd.__version__, "sklearn": sklearn.__version__},
        "input_hashes": {str(p.resolve()): sha(p) for p in paths}})
    summary, predictions = evaluate(frame, cutoffs)
    summary["validation"] = {"n": len(frame), "domains": frame.domain_group.nunique(),
        "by_source": frame.groupby("source").agg(n=("id", "size"), domains=("domain_group", "nunique"), positive=("labels", "sum")).to_dict("index")}
    write_json(out / "summary.json", summary)
    predictions.to_csv(out / "predictions.csv.gz", index=False, compression={"method": "gzip", "mtime": 0})
    report(out, summary)
    write_json(out / "result_hashes.json", {name: sha(out / name) for name in ["summary.json", "predictions.csv.gz", "report.md"]})
    verify(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["run", "verify"])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "run":
        run(args.out)
    else:
        verify(args.out)
    print(json.dumps({"report": str(args.out / "report.md"), "verified": True, "API_calls": 0}))


if __name__ == "__main__":
    main()
