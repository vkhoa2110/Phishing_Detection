"""Domain-crossfit score calibration diagnostic; no test, base-model fit or API.

Calibration scope is an experimental variable: all historical validation versus
gold/silver only. Tiny core positives and source/prior shift limit transfer.
No candidate is exported or used to select an application decision policy.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import platform
import warnings

import numpy as np
import pandas as pd
import scipy
import sklearn
from scipy.special import expit
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss

from .url_calibration import fold_for, sha, write_json
from .url_representation_v2 import check_lock as check_baseline_lock

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "artifacts/evaluations/url_representation_v2"
CONFIG = {"C": 1., "solver": "lbfgs", "max_iter": 1000, "tol": 1e-8,
          "class_weight": None, "random_state": 42, "clip_epsilon": 1e-8,
          "calibration_scopes": ["all", "core"], "folds": 5, "bins": 10}
ARMS = ["raw_score", "sigmoid_all", "sigmoid_core", "prior_all", "prior_core"]


def environment():
    return {"python": platform.python_version(), "numpy": np.__version__,
            "pandas": pd.__version__, "scipy": scipy.__version__, "sklearn": sklearn.__version__}


def validate(frame):
    fields = {"id", "split", "labels", "source", "tier", "domain_group", "score"}
    if frame.empty or not fields <= set(frame) or frame[list(fields)].isna().any().any():
        raise ValueError("Missing validation records/fields.")
    if set(frame.split) != {"val"} or frame.id.duplicated().any():
        raise ValueError("Only unique validation IDs are allowed.")
    if not frame.labels.isin([0, 1]).all() or not frame.tier.isin(["gold", "silver", "bronze"]).all():
        raise ValueError("Invalid reference labels/tiers.")
    if any(frame[key].astype(str).str.strip().eq("").any() for key in ("id", "source", "domain_group")):
        raise ValueError("Empty grouping identifiers.")
    values = frame.score.to_numpy(dtype=float)
    if not np.isfinite(values).all() or not ((values >= 0) & (values <= 1)).all():
        raise ValueError("Scores must be finite in [0,1].")


def logits(values):
    p = np.clip(np.asarray(values, dtype=float), CONFIG["clip_epsilon"], 1 - CONFIG["clip_epsilon"])
    return (np.log(p) - np.log1p(-p)).reshape(-1, 1)


def probability_metrics(labels, probabilities):
    y, p = np.asarray(labels, dtype=int), np.asarray(probabilities, dtype=float)
    if not len(y) or len(y) != len(p) or not np.isin(y, [0, 1]).all() or not np.isfinite(p).all() or not ((p >= 0) & (p <= 1)).all():
        raise ValueError("Invalid probability metric inputs.")
    bins = np.minimum((p * CONFIG["bins"]).astype(int), CONFIG["bins"] - 1)
    reliability = []
    for number in range(CONFIG["bins"]):
        selected = bins == number
        reliability.append({"bin": number, "n": int(selected.sum()),
                            "positive": int(y[selected].sum()),
                            "mean_score": float(p[selected].mean()) if selected.any() else None,
                            "observed_positive_rate": float(y[selected].mean()) if selected.any() else None})
    return {"n": len(y), "positive": int(y.sum()), "negative": int((y == 0).sum()),
            "observed_prevalence": float(y.mean()), "mean_score": float(p.mean()),
            "brier": float(brier_score_loss(y, p, pos_label=1)),
            "log_loss": float(log_loss(y, p, labels=[0, 1])), "reliability_bins": reliability}


def metrics(frame, scores):
    masks = {"full": np.ones(len(frame), dtype=bool), "gold_silver": frame.tier.ne("bronze").to_numpy()}
    masks.update({"source:" + name: frame.source.eq(name).to_numpy() for name in sorted(frame.source.unique())})
    masks.update({"tier:" + name: frame.tier.eq(name).to_numpy() for name in sorted(frame.tier.unique())})
    return {name: probability_metrics(frame.labels.to_numpy()[mask], np.asarray(scores)[mask])
            for name, mask in masks.items() if mask.any()}


def crossfit(frame):
    validate(frame)
    frame = frame.reset_index(drop=True).copy()
    frame["fold"] = frame.domain_group.map(fold_for)
    probabilities = {name: np.full(len(frame), np.nan) for name in ARMS}
    probabilities["raw_score"] = frame.score.to_numpy(dtype=float)
    fitted = []
    for fold in range(CONFIG["folds"]):
        held_mask = frame.fold.eq(fold).to_numpy()
        held = frame.loc[held_mask]
        if held.empty:
            raise ValueError("Empty held-out domain fold.")
        for scope in CONFIG["calibration_scopes"]:
            fit = frame.loc[~held_mask]
            if scope == "core":
                fit = fit.loc[fit.tier.ne("bronze")]
            if set(fit.labels) != {0, 1} or set(fit.domain_group) & set(held.domain_group):
                raise ValueError("Calibration requires two classes and disjoint held-out domains.")
            model = LogisticRegression(**{key: CONFIG[key] for key in
                ("C", "solver", "max_iter", "tol", "class_weight", "random_state")})
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                model.fit(logits(fit.score), fit.labels)
            slope, intercept = float(model.coef_[0, 0]), float(model.intercept_[0])
            if not np.isfinite([slope, intercept]).all() or slope <= 0:
                raise ValueError("Non-increasing or invalid calibration; do not reverse the URL ranking.")
            probabilities["sigmoid_" + scope][held_mask] = model.predict_proba(logits(held.score))[:, 1]
            probabilities["prior_" + scope][held_mask] = float(fit.labels.mean())
            fitted.append({"fold": fold, "scope": scope, "fit_n": len(fit),
                           "fit_positive": int(fit.labels.sum()), "fit_negative": int(fit.labels.eq(0).sum()),
                           "fit_prevalence": float(fit.labels.mean()), "fit_domains": int(fit.domain_group.nunique()),
                           "fit_id_sha256": hashlib.sha256("\n".join(fit.id).encode()).hexdigest(),
                           "held_n": len(held), "slope": slope, "intercept": intercept,
                           "iterations": model.n_iter_.tolist(), "warnings": [str(w.message) for w in caught]})
    if any(not np.isfinite(p).all() for p in probabilities.values()):
        raise ValueError("Missing held-out probabilities.")
    rows = frame[["id", "labels", "source", "tier", "domain_group", "fold", "score"]].copy()
    for name, p in probabilities.items():
        rows[name] = p
    return rows, fitted, {name: metrics(frame, p) for name, p in probabilities.items()}


def load_reference():
    check_baseline_lock(REFERENCE)
    expected = json.loads((REFERENCE / "result_hashes.json").read_text())
    for name, digest in expected.items():
        if sha(REFERENCE / name) != digest:
            raise ValueError("Reference checkpoint changed: " + name)
    frame = pd.read_csv(REFERENCE / "scores.csv.gz", float_precision="round_trip")
    return frame.rename(columns={"baseline_score": "score"}).drop(columns="v2_score")


def prepare(out):
    out = Path(out)
    if out.exists():
        raise ValueError("Choose a new output directory; preserve prior runs.")
    frame = load_reference()
    validate(frame)
    paths = [Path(__file__), ROOT / "evaluation/url_calibration.py", ROOT / "evaluation/url_representation_v2.py",
             REFERENCE / "execution.json", REFERENCE / "result_hashes.json", REFERENCE / "scores.csv.gz"]
    out.mkdir(parents=True)
    frame.to_csv(out / "input.csv.gz", index=False, compression={"method": "gzip", "mtime": 0})
    write_json(out / "execution.json", {"version": "url-probability-audit-v2-1.0",
        "registered_at": datetime.now(timezone.utc).isoformat(), "configuration": CONFIG,
        "arms": ARMS, "environment": environment(), "calibrator_fits": 10, "base_model_fits": 0, "API_calls": 0,
        "fold_rule": "SHA256(url-calibration-v1|domain) modulo 5; calibrator never sees held-out domains",
        "scope": "Historical validation already used in development, not independent test or target deployment population",
        "method": "Regularized logistic sigmoid on clipped logit(raw score), C=1, no class balancing; fitted constant priors are controls",
        "limitations": "Core has only 24 positives; sources/priors differ. Brier/log-loss are proper prediction scores, not pure calibration-only measures. No fit on all validation, export, app threshold changes or generalization claim.",
        "input_hashes": {str(p.resolve()): sha(p) for p in paths},
        "input_sha256": sha(out / "input.csv.gz")})


def check_lock(out):
    protocol = json.loads((out / "execution.json").read_text())
    if protocol["configuration"] != CONFIG or protocol["arms"] != ARMS:
        raise ValueError("Registered calibration configuration changed.")
    if protocol.get("environment") != environment():
        raise ValueError("Registered numerical environment changed.")
    for path, digest in protocol["input_hashes"].items():
        if sha(path) != digest:
            raise ValueError("Registered source/input changed: " + path)
    if sha(out / "input.csv.gz") != protocol["input_sha256"]:
        raise ValueError("Registered validation scores changed.")
    return protocol


def report(out, result):
    lines = ["# Validation-only probability audit", "", "No test inference, base model fit, threshold search, API, or app changes. Ten domain-crossfit calibrators, no full-validation deployable calibrator.", "", "| Arm | Core Brier | Core log-loss | Full Brier | Full log-loss |", "|---|---:|---:|---:|---:|"]
    for name, groups in result.items():
        core, full = groups["gold_silver"], groups["full"]
        lines.append(f"| {name} | {core['brier']:.6f} | {core['log_loss']:.6f} | {full['brier']:.6f} | {full['log_loss']:.6f} |")
    lines += ["", "Lower is better on the stated reference population only. Tiny core positive count and previously inspected validation limit inference. A probability mapping does not by itself improve discrimination or guarantee lower false alarms. Different calibration priors can improve one population and harm another. Fixed .5 decisions on different probability scales are not an equal-operating-point comparison.", "", "One-class source/tier groups report Brier/log-loss, not phishing F1. Constant prior controls are estimated on the other four folds, never the held-out fold.", ""]
    (out / "report.md").write_text("\n".join(lines))


def run(out):
    out = Path(out)
    check_lock(out)
    with (out / ".run.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (out / "fit_started.json").exists():
            raise ValueError("Calibrator fits already started; never overwrite or refit a run.")
        write_json(out / "fit_started.json", {"started_at": datetime.now(timezone.utc).isoformat(), "fits_max": 10})
        frame = pd.read_csv(out / "input.csv.gz", float_precision="round_trip")
        rows, fitted, result = crossfit(frame)
        rows.to_csv(out / "probabilities.csv.gz", index=False, compression={"method": "gzip", "mtime": 0})
        write_json(out / "fits.json", fitted)
        write_json(out / "summary.json", result)
        report(out, result)
        names = ["execution.json", "input.csv.gz", "fit_started.json", "fits.json", "probabilities.csv.gz", "summary.json", "report.md"]
        write_json(out / "result_hashes.json", {name: sha(out / name) for name in names})
        return {"completed": True, "calibrator_fits": len(fitted), "validation_n": len(rows), "API_calls": 0}


def verify(out):
    out = Path(out)
    check_lock(out)
    for name, digest in json.loads((out / "result_hashes.json").read_text()).items():
        if sha(out / name) != digest:
            raise ValueError("Completed result hash mismatch: " + name)
    frame = pd.read_csv(out / "input.csv.gz", float_precision="round_trip")
    validate(frame)
    rows = pd.read_csv(out / "probabilities.csv.gz", float_precision="round_trip")
    pd.testing.assert_frame_equal(rows[["id", "labels", "source", "tier", "domain_group", "score"]],
                                  frame[["id", "labels", "source", "tier", "domain_group", "score"]])
    if rows.id.tolist() != frame.id.tolist() or rows.fold.tolist() != frame.domain_group.map(fold_for).tolist():
        raise ValueError("OOF identifiers or domain folds changed.")
    fitted = json.loads((out / "fits.json").read_text())
    if len(fitted) != 10 or {(x["scope"], x["fold"]) for x in fitted} != {
            (scope, fold) for scope in CONFIG["calibration_scopes"] for fold in range(CONFIG["folds"])}:
        raise ValueError("Expected ten distinct calibrator fits.")
    for item in fitted:
        held = rows.fold.eq(item["fold"])
        subset = frame.loc[~held]
        if item["scope"] == "core":
            subset = subset.loc[subset.tier.ne("bronze")]
        if len(subset) != item["fit_n"] or int(subset.labels.sum()) != item["fit_positive"]:
            raise ValueError("Calibration counts differ.")
        if (hashlib.sha256("\n".join(subset.id).encode()).hexdigest() != item["fit_id_sha256"]
                or item["slope"] <= 0 or not np.isfinite([item["slope"], item["intercept"]]).all()):
            raise ValueError("Calibration fit provenance or monotonicity differs.")
        expected = expit(item["slope"] * logits(frame.loc[held].score).ravel() + item["intercept"])
        np.testing.assert_allclose(rows.loc[held, "sigmoid_" + item["scope"]], expected, rtol=1e-14, atol=1e-15)
        np.testing.assert_array_equal(rows.loc[held, "prior_" + item["scope"]], np.full(int(held.sum()), subset.labels.mean()))
    np.testing.assert_array_equal(rows.raw_score, frame.score)
    result = {name: metrics(frame, rows[name]) for name in ARMS}
    if result != json.loads((out / "summary.json").read_text()):
        raise ValueError("Stored metrics differ from probability checkpoints.")
    write_json(out / "verification.json", {"verified": True, "rows": len(rows), "calibrators": 10,
        "recomputed_probabilities": True, "API_calls": 0, "refits": 0, "test_evaluated": False,
        "app_changes": False})
    return {"verified": True, "rows": len(rows), "refits": 0, "API_calls": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "run", "verify"])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    value = globals()[args.command](args.out)
    print(json.dumps(value if value is not None else {"prepared": True, "API_calls": 0}, indent=2))


if __name__ == "__main__":
    main()
