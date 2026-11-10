"""One predeclared train-only character baseline; no API or deployment writes.

Historical validation domain folds audit FPR-budget thresholds. Historical test
is reported retrospectively, with thresholds frozen from validation, not tuned.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import time
import warnings

import numpy as np
import pandas as pd
import scipy
import sklearn
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix, f1_score, precision_score, recall_score
from sklearn.pipeline import Pipeline

from evaluation.url.phishvn import SHA256, notebook_constants, prepare_splits
from evaluation.url.calibration import alarm, choose_cutoff, fold_for, group_metrics, sha, write_json

from app.core.settings import ROOT
ARCHIVE = ROOT / "data/raw/PhishVN_v3.1.0_open.zip"
MODEL = ROOT / "models/inference_XGBoost_d6_s42"
HISTORICAL = ROOT / "artifacts/evaluations/phishvn_official_v1"
POLICIES = {"fixed_0.5": None, "fpr_5pct": .05, "fpr_1pct": .01}
CONFIG = {"analyzer": "char", "ngram_range": [3, 5], "lowercase": True,
          "min_df": 2, "max_features": 150000, "sublinear_tf": True,
          "norm": "l2", "dtype": "float64", "C": 1., "solver": "liblinear",
          "class_weight": "balanced", "max_iter": 1000, "random_state": 42}


def dataset():
    spec = importlib.util.spec_from_file_location("char_url_preprocessing", MODEL / "url_preprocessing.py")
    preprocessing = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(preprocessing)
    frames, audit = prepare_splits(ARCHIVE, notebook_constants(ROOT / "notebooks/Train_URL_Phishing_GPU.ipynb")["CFG"], preprocessing)
    historical = json.loads((HISTORICAL / "manifest.json").read_text())["configuration"]
    for key, path in [("model_sha256", MODEL / "model.ubj"), ("config_sha256", MODEL / "config.json"), ("archive_sha256", ARCHIVE)]:
        if sha(path) != historical[key]:
            raise ValueError("Production reference changed: " + str(path))
    for split in ["val", "test"]:
        saved = pd.read_csv(HISTORICAL / f"{split}_predictions.csv", float_precision="round_trip")
        frame = frames[split]
        if len(saved) != len(frame) or saved.id.duplicated().any() or set(saved.id) != set(frame.id):
            raise ValueError("Missing/duplicate production predictions.")
        saved = saved.set_index("id").loc[frame.id]
        for field in ["url", "labels", "source", "tier", "domain_group"]:
            if saved[field].tolist() != frame[field].tolist():
                raise ValueError("Production prediction metadata differs: " + field)
        scores = saved.score.to_numpy(dtype=float)
        if not np.isfinite(scores).all() or not ((scores >= 0) & (scores <= 1)).all():
            raise ValueError("Invalid production scores.")
        frame["xgb_score"] = scores
    return frames, audit


def pipeline():
    return Pipeline([
        ("tfidf", TfidfVectorizer(analyzer=CONFIG["analyzer"], ngram_range=tuple(CONFIG["ngram_range"]),
            lowercase=CONFIG["lowercase"], min_df=CONFIG["min_df"], max_features=CONFIG["max_features"],
            sublinear_tf=CONFIG["sublinear_tf"], norm=CONFIG["norm"], dtype=np.float64)),
        ("classifier", LogisticRegression(C=CONFIG["C"], solver=CONFIG["solver"],
            class_weight=CONFIG["class_weight"], max_iter=CONFIG["max_iter"], random_state=CONFIG["random_state"]))])


def fit_training_only(frames):
    """Only the explicit train frame supplies text, vocabulary, IDF and labels."""
    train = frames["train"]
    if set(train.split) != {"train"} or set(train.labels) != {0, 1}:
        raise ValueError("Fit requires the official two-class training frame.")
    for split in ["val", "test"]:
        for field in ["id", "model_input", "domain_group"]:
            if set(train[field]) & set(frames[split][field]):
                raise ValueError("Train/evaluation overlap: " + field)
    model = pipeline()
    started = time.perf_counter()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        model.fit(train.model_input, train.labels)
    vectorizer, classifier = model["tfidf"], model["classifier"]
    metadata = {"train_n": len(train), "train_positive": int(train.labels.sum()),
        "train_negative": int(train.labels.eq(0).sum()), "train_seconds": time.perf_counter() - started,
        "vocabulary_size": len(vectorizer.vocabulary_), "iterations": classifier.n_iter_.tolist(),
        "warnings": [str(item.message) for item in caught],
        "vocabulary_sha256": hashlib.sha256(json.dumps({key: int(value) for key, value in vectorizer.vocabulary_.items()}, sort_keys=True).encode()).hexdigest(),
        "idf_sha256": hashlib.sha256(vectorizer.idf_.tobytes()).hexdigest(),
        "coefficient_sha256": hashlib.sha256(classifier.coef_.tobytes() + classifier.intercept_.tobytes()).hexdigest()}
    return model, metadata


def cutoff(frame, budget):
    return .5 if budget is None else choose_cutoff(frame, budget)


def compare(validation, test):
    """Fit thresholds without test, keeping a whole registrable domain together."""
    result, rows = {}, []
    for family, score in [("XGBoost_production", "xgb_score"), ("Char_TFIDF_LogReg", "char_score")]:
        val, held_test = validation.copy(), test.copy()
        val["score"], held_test["score"] = val[score], held_test[score]
        val["fold"] = val.domain_group.map(fold_for)
        policies = {}
        for name, budget in POLICIES.items():
            oof = np.zeros(len(val), dtype=bool)
            folds = []
            for fold in range(5):
                mask = val.fold.eq(fold).to_numpy()
                fit, held = val.loc[~mask], val.loc[mask]
                if held.empty or set(fit.domain_group) & set(held.domain_group):
                    raise ValueError("Empty/overlapping domain fold.")
                threshold = cutoff(fit, budget)
                predicted = alarm(held.score, threshold)
                oof[mask] = predicted
                folds.append({"fold": fold, "threshold": threshold, "calibration_n": len(fit),
                              "metrics": group_metrics(held, predicted)})
                for item, output in zip(held.to_dict("records"), predicted):
                    rows.append({"model": family, "policy": name, "split": "val_domain_crossfit",
                        "id": item["id"], "threshold": threshold, "alarm": int(output), "fold": fold})
            # Test is accessed after the full-val cutoff is chosen; it never affects it.
            full_threshold = cutoff(val, budget)
            test_pred = alarm(held_test.score, full_threshold)
            policies[name] = {"full_validation_threshold": full_threshold, "folds": folds,
                "validation_domain_crossfit": group_metrics(val, oof),
                "retrospective_test": group_metrics(held_test, test_pred)}
            for item, output in zip(held_test.to_dict("records"), test_pred):
                rows.append({"model": family, "policy": name, "split": "test_retrospective",
                    "id": item["id"], "threshold": full_threshold, "alarm": int(output), "fold": None})
        result[family] = policies
    return result, pd.DataFrame(rows)


def locked_paths():
    return [Path(__file__), ROOT / "evaluation/url/phishvn.py", ROOT / "evaluation/url/calibration.py",
        ARCHIVE, ROOT / "notebooks/Train_URL_Phishing_GPU.ipynb", MODEL / "url_preprocessing.py",
        MODEL / "model.ubj", MODEL / "config.json", HISTORICAL / "manifest.json",
        HISTORICAL / "val_predictions.csv", HISTORICAL / "test_predictions.csv"]


def prepare(out):
    if out.exists():
        raise ValueError("Choose a new output directory; preserve previous runs.")
    frames, audit = dataset()
    if sha(ARCHIVE) != SHA256:
        raise ValueError("Dataset SHA mismatch.")
    out.mkdir(parents=True)
    write_json(out / "execution.json", {"schema": "url-char-baseline-1.0",
        "created_at": datetime.now(timezone.utc).isoformat(), "configuration": CONFIG,
        "fit_count": 1, "fit_scope": "all official train, no validation/test vocabulary or IDF",
        "selection": "no sweep, no refit, no seed/model selection using validation or test",
        "representation": "unchanged production format_url output; scheme omitted; vectorizer lowercases text",
        "policies": POLICIES, "fold_rule": "SHA256(url-calibration-v1|domain) modulo 5",
        "threshold_selection": "negative-only validation FPR budgets; >= cutoff; boundary ties excluded together",
        "test": "historical test already viewed; retrospective only, never a new holdout",
        "confound": "production XGB earlier used validation for early stopping/model/threshold selection; not a pure architecture isolation",
        "app_model_or_threshold_changes": False, "API_calls": 0,
        "environment": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__,
                        "scipy": scipy.__version__, "sklearn": sklearn.__version__},
        "data_audit": audit, "input_hashes": {str(path.resolve()): sha(path) for path in locked_paths()}})
    index = pd.concat([frame[["id", "split", "labels", "source", "tier", "domain_group"]] for frame in frames.values()])
    index.to_csv(out / "data_index.csv.gz", index=False, compression={"method": "gzip", "mtime": 0})


def check_lock(out):
    execution = json.loads((out / "execution.json").read_text())
    for path, expected in execution["input_hashes"].items():
        if sha(path) != expected:
            raise ValueError("Registered input/source changed: " + path)
    if execution["configuration"] != CONFIG or execution["policies"] != POLICIES:
        raise ValueError("Registered configuration differs.")


def report(out, result):
    pct = lambda value: "N/A" if value is None else f"{100 * value:.2f}%"
    lines = ["# One character URL baseline: historical diagnostic", "",
        "One train-only char 3–5 TF-IDF / balanced Logistic Regression, C=1. No sweep or app update. "
        "Validation domain cross-fitting audits FPR-budget thresholds; historical test is retrospective. "
        "Production XGB previously used validation for early stopping and selection, so this is not a pure architecture comparison.", ""]
    for section, title in [("validation_domain_crossfit", "Validation domain cross-fit"), ("retrospective_test", "Historical test, validation cutoffs frozen")]:
        lines += ["## " + title, "", "| Model | Policy | Group | TP / positive | FP / negative | Recall | FPR | F1 |",
                  "|---|---|---|---:|---:|---:|---:|---:|"]
        for model, policies in result.items():
            for policy, values in policies.items():
                for group in ["full", "gold_silver", "tier:bronze"]:
                    metric = values[section][group]
                    lines.append(f"| {model} | {policy} | {group} | {metric['tp']}/{metric['positive']} | {metric['fp']}/{metric['negative']} | {pct(metric['recall'])} | {pct(metric['false_positive_rate'])} | {pct(metric['f1'])} |")
    lines += ["", "## Conditional source rates, validation cross-fit", "",
              "| Model | Policy | Source | Recall | FPR | Positive | Negative |",
              "|---|---|---|---:|---:|---:|---:|"]
    for model, policies in result.items():
        for policy, values in policies.items():
            for group, metric in values["validation_domain_crossfit"].items():
                if group.startswith("source:"):
                    lines.append(f"| {model} | {policy} | {group[7:]} | {pct(metric['recall'])} | {pct(metric['false_positive_rate'])} | {metric['positive']} | {metric['negative']} |")
    lines += ["", "## Limits", "", "24 core-validation positives only; all source labels remain historical references, "
        "not independent human truth. Source/time/label quality and campaign structure remain confounded. "
        "Domain separation does not guarantee campaign separation. No guaranteed population FPR, calibrated-risk probability, "
        "new holdout or causal model-family claim. Single-class sources report Recall/FPR, not perfect precision/F1. "
        "The character model can learn source-specific strings or campaigns and requires independent future data before use."]
    (out / "report.md").write_text("\n".join(lines) + "\n")


def run(out):
    check_lock(out)
    if (out / "fit.json").exists() or (out / "scores.csv.gz").exists():
        raise ValueError("Fit outputs already exist; preserve the completed experiment.")
    frames, _ = dataset()
    model, fit = fit_training_only(frames)
    write_json(out / "fit.json", fit)
    for split in ["val", "test"]:
        frames[split]["char_score"] = model.predict_proba(frames[split].model_input)[:, 1]
    scores = pd.concat([frames[split][["id", "split", "labels", "source", "tier", "domain_group", "xgb_score", "char_score"]] for split in ["val", "test"]])
    scores.to_csv(out / "scores.csv.gz", index=False, compression={"method": "gzip", "mtime": 0})
    result, decisions = compare(frames["val"], frames["test"])
    write_json(out / "summary.json", result)
    decisions.to_csv(out / "decisions.csv.gz", index=False, compression={"method": "gzip", "mtime": 0})
    report(out, result)
    names = ["execution.json", "data_index.csv.gz", "fit.json", "scores.csv.gz", "summary.json", "decisions.csv.gz", "report.md"]
    write_json(out / "result_hashes.json", {name: sha(out / name) for name in names})
    verify(out)
    print(json.dumps({"completed_fits": 1, "fit": fit, "out": str(out)}, ensure_ascii=False), flush=True)


def verify(out):
    check_lock(out)
    for name, expected in json.loads((out / "result_hashes.json").read_text()).items():
        if sha(out / name) != expected:
            raise ValueError("Output hash differs: " + name)
    frames, _ = dataset()
    scores = pd.read_csv(out / "scores.csv.gz", float_precision="round_trip")
    if scores.duplicated("id").any() or not set(scores.split) == {"val", "test"}:
        raise ValueError("Duplicate/invalid score rows.")
    for split in ["val", "test"]:
        saved = scores.loc[scores.split.eq(split)].set_index("id")
        frame = frames[split]
        if set(saved.index) != set(frame.id):
            raise ValueError("Score IDs differ.")
        saved = saved.loc[frame.id]
        for field in ["labels", "source", "tier", "domain_group", "xgb_score"]:
            if saved[field].tolist() != frame[field].tolist():
                raise ValueError("Score metadata differs: " + field)
        values = saved.char_score.to_numpy(dtype=float)
        if not np.isfinite(values).all() or not ((values >= 0) & (values <= 1)).all():
            raise ValueError("Character scores are invalid.")
        frame["char_score"] = values
    result, expected_decisions = compare(frames["val"], frames["test"])
    if result != json.loads((out / "summary.json").read_text()):
        raise ValueError("Recomputed threshold/metrics differ.")
    saved_decisions = pd.read_csv(out / "decisions.csv.gz", float_precision="round_trip")
    pd.testing.assert_frame_equal(saved_decisions, expected_decisions, check_dtype=False)
    checks = 0
    for (family, policy, split), decisions in saved_decisions.groupby(["model", "policy", "split"]):
        frame = frames["val" if split == "val_domain_crossfit" else "test"]
        decisions = decisions.set_index("id").loc[frame.id]
        groups = result[family][policy]["validation_domain_crossfit" if split == "val_domain_crossfit" else "retrospective_test"]
        for group, recorded in groups.items():
            mask = np.ones(len(frame), dtype=bool) if group == "full" else frame.tier.isin(["gold", "silver"]).to_numpy() if group == "gold_silver" else frame[group.split(":")[0]].eq(group.split(":")[1]).to_numpy()
            y, pred = frame.labels.to_numpy()[mask], decisions.alarm.to_numpy()[mask]
            tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
            if [int(tp), int(fp), int(tn), int(fn)] != [recorded[key] for key in ["tp", "fp", "tn", "fn"]]:
                raise ValueError("Independent confusion check failed.")
            if set(y) == {0, 1}:
                for name, func in [("precision", precision_score), ("recall", recall_score), ("f1", f1_score)]:
                    if not np.isclose(recorded[name], func(y, pred, zero_division=0), atol=1e-12):
                        raise ValueError("Independent metric check failed.")
            checks += 1
    write_json(out / "verification.json", {"verified": True, "groups_checked": checks,
        "decisions_checked": len(saved_decisions), "API_calls": 0, "app_changed": False,
        "new_independent_test": False, "input_and_result_hashes_match": True})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "run", "verify"])
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    {"prepare": prepare, "run": run, "verify": verify}[args.command](args.out)


if __name__ == "__main__":
    main()
