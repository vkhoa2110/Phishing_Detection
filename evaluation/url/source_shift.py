"""Locked source predictability and positive-source exclusion diagnostics.

Only official train/validation members are loaded. Five fits, one configuration,
fixed 0.5 URL threshold, no API, model selection, holdout or deployment writes.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import time
import warnings

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, balanced_accuracy_score, confusion_matrix, f1_score

from app.services.url.character import DEFAULT_DEPLOYMENT, CharURLService, _learned_hashes, _versions
from evaluation.url.calibration import group_metrics, sha, write_json
from evaluation.url.character_baseline import CONFIG, pipeline
from evaluation.url.representation import ARCHIVE, BASELINE, ROOT, ensure_disjoint, load_frames

POSITIVE_SOURCES = ["chongluadao", "openphish", "tinnhiemmang"]
THRESHOLD = .5
FIT_ORDER = ["source_given_benign", "source_given_phishing"] + ["exclude_" + s for s in POSITIVE_SOURCES]
RESULT_NAMES = ["execution.json", "validation_index.csv", "fit_started.json", "fit.json",
                "source_predictions.csv.gz", "url_predictions.csv.gz", "summary.json", "report.md"]


def validate_frames(frames):
    if set(frames) != {"train", "val"}:
        raise ValueError("Only train/validation frames are permitted.")
    ensure_disjoint(frames)
    for split, frame in frames.items():
        if set(frame.split) != {split} or set(frame.labels) != {0, 1}:
            raise ValueError("Official split/two-class references required.")
        if set(frame.loc[frame.labels.eq(1), "source"]) != set(POSITIVE_SOURCES):
            raise ValueError("Unexpected positive source set.")
        if frame.source.eq("").any() or frame.id.duplicated().any():
            raise ValueError("Missing source/duplicate ID.")
    for label in [0, 1]:
        sources = set(frames["train"].loc[frames["train"].labels.eq(label), "source"])
        if len(sources) < 2 or not set(frames["val"].loc[frames["val"].labels.eq(label), "source"]) <= sources:
            raise ValueError("Source prediction needs known multiple training sources.")


def exclusion_training(train, source):
    if source not in POSITIVE_SOURCES or set(train.split) != {"train"}:
        raise ValueError("Exclusion requires registered source and train rows only.")
    selected = train.loc[~(train.labels.eq(1) & train.source.eq(source))].copy()
    if set(selected.loc[selected.labels.eq(0), "id"]) != set(train.loc[train.labels.eq(0), "id"]):
        raise ValueError("Negative training rows changed.")
    if selected.loc[selected.labels.eq(1), "source"].eq(source).any() or set(selected.labels) != {0, 1}:
        raise ValueError("Held-out positive source leaked into training.")
    return selected


def fit_training(frame, target):
    if set(frame.split) != {"train"} or target not in {"labels", "source"} or frame[target].nunique() < 2:
        raise ValueError("Fit needs training-only data and multiple target classes.")
    model = pipeline()
    started = time.perf_counter()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        model.fit(frame.model_input, frame[target])
    counts = frame[target].value_counts().to_dict()
    return model, {"train_n": len(frame), "target": target,
        "train_target_counts": {str(k): int(v) for k, v in counts.items()},
        "balanced_class_weights": {str(k): len(frame) / (len(counts) * v) for k, v in counts.items()},
        "train_source_by_label": {f"{label}:{source}": len(g) for (label, source), g in frame.groupby(["labels", "source"])},
        "classes": model["classifier"].classes_.tolist(),
        "train_seconds": time.perf_counter() - started,
        "vocabulary_size": len(model["tfidf"].vocabulary_),
        "iterations": model["classifier"].n_iter_.tolist(),
        "warnings": [str(w.message) for w in caught],
        **_learned_hashes(model["tfidf"], model["classifier"])}


def source_metrics(reference, predicted, classes):
    y, p = np.asarray(reference), np.asarray(predicted)
    if not len(y) or len(y) != len(p) or not set(y) <= set(classes) or not set(p) <= set(classes):
        raise ValueError("Invalid source predictions/classes.")
    matrix = confusion_matrix(y, p, labels=classes)
    return {"n": len(y), "accuracy": float(accuracy_score(y, p)),
        "balanced_accuracy": float(balanced_accuracy_score(y, p)),
        "macro_f1": float(f1_score(y, p, labels=classes, average="macro", zero_division=0)),
        "classes": list(classes), "confusion_rows_reference_columns_prediction": matrix.tolist(),
        "per_source": {source: {"n": int(matrix[i].sum()), "correct": int(matrix[i, i]),
            "recall": float(matrix[i, i] / matrix[i].sum()) if matrix[i].sum() else None}
            for i, source in enumerate(classes)}}


def majority_source(train):
    counts = train.source.value_counts()
    # Training-only deterministic lexical tie break, never validation prevalence.
    return sorted(counts[counts.eq(counts.max())].index)[0]


def locked_paths():
    return [Path(__file__), ROOT / "evaluation/url/representation.py",
        ROOT / "evaluation/url/character_baseline.py", ROOT / "evaluation/url/calibration.py",
        ROOT / "evaluation/url/phishvn.py", ROOT / "app/services/url/character.py", ARCHIVE,
        ROOT / "models/inference_XGBoost_d6_s42/url_preprocessing.py",
        *[DEFAULT_DEPLOYMENT / name for name in ["export.json", "vocabulary.json", "weights.npz"]]]


def prepare(out):
    if out.exists():
        raise ValueError("Choose a new output directory; preserve previous experiments.")
    frames, audit = load_frames()
    validate_frames(frames)
    out.mkdir(parents=True)
    write_json(out / "execution.json", {"schema": "url-source-shift-v2-1.0",
        "created_at": datetime.now(timezone.utc).isoformat(), "configuration": CONFIG,
        "fit_order": FIT_ORDER, "fit_count": 5, "positive_sources": POSITIVE_SOURCES,
        "URL_threshold": THRESHOLD, "API_calls": 0, "test_evaluated": False,
        "split_members_opened": ["train", "val"],
        "selection": "single frozen config, no search or selection by validation; exactly five fits",
        "source_prediction": "within each reference class; source as target only; train-only vocabulary/IDF/weights; liblinear OvR",
        "baseline": "unchanged character-v1 frozen export, scored on validation only",
        "exclusion": "remove one positive source, retain all negatives and other positive sources; no resampling",
        "confounds": "source/time/scope/label/campaign are entangled; exclusions change sample size and balanced class weights; not causal attribution",
        "validation": "historical development data previously inspected; no independent holdout or human-verified labels",
        "deployment_changes": False, "data_audit": audit,
        "environment": {"python": platform.python_version(), **_versions()},
        "input_hashes": {str(path.resolve()): sha(path) for path in locked_paths()}})
    frames["val"][["id", "labels", "source", "tier", "domain_group"]].to_csv(out / "validation_index.csv", index=False)


def check_lock(out):
    execution = json.loads((out / "execution.json").read_text())
    if (execution["configuration"] != CONFIG or execution["fit_order"] != FIT_ORDER or
            execution["URL_threshold"] != THRESHOLD or execution["positive_sources"] != POSITIVE_SOURCES):
        raise ValueError("Registered configuration changed.")
    for path, expected in execution["input_hashes"].items():
        if sha(path) != expected:
            raise ValueError("Registered source/input changed: " + path)


def summaries(frames, source_rows, url_rows):
    validation = frames["val"].reset_index(drop=True)
    result = {"source_prediction": {}, "URL_validation_fixed_0.5": {}}
    for label, task in enumerate(FIT_ORDER[:2]):
        training = frames["train"].loc[frames["train"].labels.eq(label)]
        rows = source_rows.loc[source_rows.task.eq(task)]
        classes = sorted(training.source.unique())
        majority = majority_source(training)
        result["source_prediction"][task] = {
            "train_n": len(training), "majority_source_chosen_from_train": majority,
            "char_source_classifier": source_metrics(rows.reference, rows.prediction, classes),
            "majority_source_baseline": source_metrics(rows.reference, [majority] * len(rows), classes)}
    for task in ["baseline_all_sources", *FIT_ORDER[2:]]:
        rows = url_rows.loc[url_rows.task.eq(task)].set_index("id", verify_integrity=True)
        if set(rows.index) != set(validation.id):
            raise ValueError("Incomplete URL validation predictions.")
        aligned = rows.loc[validation.id]
        result["URL_validation_fixed_0.5"][task] = group_metrics(validation, aligned.score.to_numpy(float) >= THRESHOLD)
    return result


def report(out, result):
    pct = lambda x: "N/A" if x is None else f"{100*x:.2f}%"
    lines = ["# Source predictability and exclusion: validation-only diagnostics", "",
        "Exactly five locked train-only fits; fixed URL threshold 0.5. No API, official test member, "
        "new holdout or app changes. Historical validation has been inspected before.", "",
        "## Can URL characters predict source within a reference class?", "",
        "| Reference class | Method | Accuracy | Balanced accuracy | Macro F1 |",
        "|---|---|---:|---:|---:|"]
    for task, value in result["source_prediction"].items():
        for method in ["majority_source_baseline", "char_source_classifier"]:
            m = value[method]
            lines.append(f"| {task} | {method} | {pct(m['accuracy'])} | {pct(m['balanced_accuracy'])} | {pct(m['macro_f1'])} |")
    lines += ["", "Source as target only; inputs remain unchanged format_url text. Vocabulary, IDF, "
        "class weights and majority source use training rows only. Confusion matrices and per-source recall are in summary.json.", "",
        "## Remove one positive training source, retain every negative", "",
        "| Training policy | Validation group | TP / positive | FP / negative | Recall | FPR | F1 |",
        "|---|---|---:|---:|---:|---:|---:|"]
    for task, values in result["URL_validation_fixed_0.5"].items():
        for name, m in values.items():
            if name in {"full", "gold_silver"} or name.startswith("source:"):
                lines.append(f"| {task} | {name} | {m['tp']}/{m['positive']} | {m['fp']}/{m['negative']} | {pct(m['recall'])} | {pct(m['false_positive_rate'])} | {pct(m['f1'])} |")
    lines += ["", "A source classifier outperforming the majority baseline shows recoverable source information, "
        "not proof that the phishing classifier uses it or that it is spurious. Source, collection time, language, scope, "
        "label reliability and campaign can differ. Excluding a source changes positive count and balanced class weights; "
        "any recall/FPR change is a whole-training-policy association, not an isolated causal source effect. "
        "No validation result selects an exclusion, threshold or app model. Only 24 gold/silver validation positives exist; "
        "do not treat source-only groups' recall as whole-class precision/F1 or claim population FPR. "
        "New source-balanced, time-separated, independently reviewed data are still needed."]
    (out / "report.md").write_text("\n".join(lines) + "\n")


def run(out):
    check_lock(out)
    if (out / "fit_started.json").exists():
        raise ValueError("Fit already started; do not refit/retry to select results.")
    frames, _ = load_frames()
    validate_frames(frames)
    write_json(out / "fit_started.json", {"started_at": datetime.now(timezone.utc).isoformat(), "fit_order": FIT_ORDER})
    train, validation = frames["train"], frames["val"]
    fits, source_rows, url_rows = {}, [], []
    metadata = ["id", "labels", "source", "tier", "domain_group"]
    for label, task in enumerate(FIT_ORDER[:2]):
        selected = train.loc[train.labels.eq(label)]
        held = validation.loc[validation.labels.eq(label)]
        model, fits[task] = fit_training(selected, "source")
        for row, prediction in zip(held[metadata].to_dict("records"), model.predict(held.model_input)):
            source_rows.append({**row, "task": task, "reference": row["source"], "prediction": prediction})
        write_json(out / "fit.json", fits)
    baseline = CharURLService()
    if not baseline.load()["ready"]:
        raise ValueError(baseline.error)
    for row, score in zip(validation[metadata].to_dict("records"), baseline._scores(validation.url.tolist())):
        url_rows.append({**row, "task": "baseline_all_sources", "score": float(score), "alarm": int(score >= THRESHOLD)})
    for source in POSITIVE_SOURCES:
        task = "exclude_" + source
        selected = exclusion_training(train, source)
        model, fits[task] = fit_training(selected, "labels")
        for row, score in zip(validation[metadata].to_dict("records"), model.predict_proba(validation.model_input)[:, 1]):
            url_rows.append({**row, "task": task, "score": float(score), "alarm": int(score >= THRESHOLD)})
        write_json(out / "fit.json", fits)
    source_rows, url_rows = pd.DataFrame(source_rows), pd.DataFrame(url_rows)
    for name, rows in [("source_predictions", source_rows), ("url_predictions", url_rows)]:
        rows.to_csv(out / (name + ".csv.gz"), index=False, compression={"method": "gzip", "mtime": 0})
    result = summaries(frames, source_rows, url_rows)
    write_json(out / "summary.json", result)
    report(out, result)
    write_json(out / "result_hashes.json", {name: sha(out / name) for name in RESULT_NAMES})
    verify(out)
    print(json.dumps({"completed_fits": len(fits), "out": str(out)}, ensure_ascii=False))


def verify(out):
    check_lock(out)
    hashes = json.loads((out / "result_hashes.json").read_text())
    if set(hashes) != set(RESULT_NAMES):
        raise ValueError("Incomplete result manifest.")
    for name, expected in hashes.items():
        if sha(out / name) != expected:
            raise ValueError("Saved result changed: " + name)
    frames, _ = load_frames()
    validate_frames(frames)
    reference = frames["val"].set_index("id", verify_integrity=True)
    source_rows = pd.read_csv(out / "source_predictions.csv.gz", float_precision="round_trip")
    url_rows = pd.read_csv(out / "url_predictions.csv.gz", float_precision="round_trip")
    for rows, tasks in [(source_rows, FIT_ORDER[:2]), (url_rows, ["baseline_all_sources", *FIT_ORDER[2:]])]:
        if set(rows.task) != set(tasks) or rows.duplicated(["task", "id"]).any():
            raise ValueError("Duplicate/unknown/missing task predictions.")
        for task, group in rows.groupby("task"):
            expected = reference
            if task in FIT_ORDER[:2]:
                expected = reference.loc[reference.labels.eq(FIT_ORDER.index(task))]
            if set(group.id) != set(expected.index):
                raise ValueError("Validation membership differs.")
            aligned = reference.loc[group.id]
            for field in ["labels", "source", "tier", "domain_group"]:
                if aligned[field].tolist() != group[field].tolist():
                    raise ValueError("Reference metadata differs: " + field)
    if source_rows.reference.tolist() != source_rows.source.tolist():
        raise ValueError("Source reference differs.")
    scores = url_rows.score.to_numpy(float)
    if not np.isfinite(scores).all() or not ((scores >= 0) & (scores <= 1)).all() or not np.array_equal(scores >= THRESHOLD, url_rows.alarm):
        raise ValueError("Invalid URL score/alarm.")
    fits = json.loads((out / "fit.json").read_text())
    if set(fits) != set(FIT_ORDER):
        raise ValueError("Five completed fits required.")
    for source in POSITIVE_SOURCES:
        value = fits["exclude_" + source]
        selected = exclusion_training(frames["train"], source)
        expected = {f"{label}:{s}": len(g) for (label, s), g in selected.groupby(["labels", "source"])}
        if value["train_source_by_label"] != expected or value["train_n"] != len(selected):
            raise ValueError("Exclusion fit membership differs.")
    result = summaries(frames, source_rows, url_rows)
    if result != json.loads((out / "summary.json").read_text()):
        raise ValueError("Recomputed metrics differ.")
    write_json(out / "verification.json", {"passed": True, "API_calls": 0, "new_fits": 0,
        "split_members_opened": ["train", "val"], "test_evaluated": False,
        "source_decisions_checked": len(source_rows), "URL_decisions_checked": len(url_rows),
        "result_hashes_verified": len(hashes), "completed_fits": len(fits),
        "source_confusions_and_sklearn_metrics_match": True,
        "class_weight_and_sample_size_confounds_retained": True})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "run", "verify"])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    {"prepare": prepare, "run": run, "verify": verify}[args.action](args.out.resolve())


if __name__ == "__main__":
    main()
