"""One locked marker-free representation experiment: historical validation only.

Train one new model; reuse frozen character-v1 export. No test split is opened,
no API is called, and neither a deployed model nor its cutoffs are changed.
"""
import argparse
import csv
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path
import platform
import re
import time
import warnings
import zipfile

import numpy as np
import pandas as pd
import tldextract
from sklearn.metrics import confusion_matrix, f1_score, precision_score, recall_score

from app.services.url.character import DEFAULT_DEPLOYMENT, CharURLService, _learned_hashes, _versions
from evaluation.url.phishvn import SHA256
from evaluation.url.calibration import alarm, choose_cutoff, fold_for, group_metrics, sha, write_json
from evaluation.url.character_baseline import CONFIG, pipeline

from app.core.settings import ROOT
ARCHIVE = ROOT / "data/raw/PhishVN_v3.1.0_open.zip"
BASELINE = ROOT / "artifacts/evaluations/url_char_baseline_v1"
POLICIES = {"fixed_0.5": None, "fpr_5pct": .05}
REPRESENTATION = "netloc + path + optional '?'query + optional '#'fragment; no scheme or synthetic markers"
SMOKE_URLS = ["https://example.com/", "https://example.org/",
              "https://github.com/vkhoa2110/Phishing_Detection", "https://www.google.com/"]


def marker_free(url, preprocessing):
    """Reassemble URL parts; preserve marker-like literal text in the real URL."""
    parts, _ = preprocessing.parse_url_parts(url)
    return parts.netloc + parts.path + ("?" + parts.query if parts.query else "") + ("#" + parts.fragment if parts.fragment else "")


def load_frames(archive=ARCHIVE, preprocessing=None):
    if sha(archive) != SHA256:
        raise ValueError("Archive hash changed.")
    if preprocessing is None:
        service = CharURLService()
        if not service.load()["ready"]:
            raise ValueError(service.error)
        preprocessing = service.preprocessing
    ext = tldextract.TLDExtract(suffix_list_urls=(), include_psl_private_domains=False)
    frames, checks = {}, {}
    with zipfile.ZipFile(archive) as package:
        manifest = package.read("MANIFEST.txt").decode()
        for split in ["train", "val"]:
            name = f"data/splits/url_{split}.csv"
            raw = package.read(name)
            expected = re.search(r"(?m)^([0-9a-f]{64})\s+" + re.escape(name) + r"\s", manifest)
            if not expected or hashlib.sha256(raw).hexdigest() != expected.group(1):
                raise ValueError("MANIFEST mismatch: " + split)
            records = pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False)
            if set(records.split.str.strip()) != {split}:
                raise ValueError("Official split mismatch.")
            rows, invalid = [], []
            for item in records.to_dict("records"):
                if item["label"] not in {"phishing", "benign"}:
                    raise ValueError("Unknown reference label.")
                try:
                    _, host = preprocessing.parse_url_parts(item["url"])
                    try:
                        host = host.encode("idna").decode("ascii")
                    except UnicodeError:
                        pass
                    item.update(model_input=preprocessing.format_url(item["url"]),
                                v2_input=marker_free(item["url"], preprocessing),
                                domain_group=ext(host).top_domain_under_public_suffix or host,
                                labels=int(item["label"] == "phishing"))
                except (ValueError, UnicodeError):
                    invalid.append(item["id"])
                    continue
                rows.append(item)
            frame = pd.DataFrame(rows).drop_duplicates(["model_input", "labels"]).reset_index(drop=True)
            if frame.groupby("model_input").labels.nunique().gt(1).any() or frame.id.duplicated().any():
                raise ValueError("Conflicting/duplicate URL rows.")
            frames[split] = frame
            checks[split] = {"raw_n": len(records), "n": len(frame), "positive": int(frame.labels.sum()),
                             "negative": int(frame.labels.eq(0).sum()), "invalid_ids": invalid,
                             "member_sha256": expected.group(1)}
    ensure_disjoint(frames)
    return frames, checks


def ensure_disjoint(frames):
    for field in ["id", "model_input", "v2_input", "domain_group"]:
        if set(frames["train"][field]) & set(frames["val"][field]):
            raise ValueError("Train/validation overlap: " + field)


def fit_training_only(frames):
    ensure_disjoint(frames)
    train = frames["train"]
    if set(train.split) != {"train"} or set(train.labels) != {0, 1}:
        raise ValueError("Fit requires official two-class train.")
    model = pipeline()
    started = time.perf_counter()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        model.fit(train.v2_input, train.labels)
    metadata = {"train_n": len(train), "train_positive": int(train.labels.sum()),
                "train_seconds": time.perf_counter() - started,
                "vocabulary_size": len(model["tfidf"].vocabulary_),
                "iterations": model["classifier"].n_iter_.tolist(), "warnings": [str(w.message) for w in caught],
                **_learned_hashes(model["tfidf"], model["classifier"])}
    return model, metadata


def baseline_scores(frame, service, path=BASELINE / "scores.csv.gz"):
    """Select only val records from the old combined gzip, never parse test scores."""
    expected = []
    with gzip.open(path, "rt", newline="") as stream:
        for row in csv.DictReader(stream):
            if row["split"] == "val":
                expected.append({k: row[k] for k in ["id", "labels", "source", "tier", "domain_group", "char_score"]})
    saved = pd.DataFrame(expected).set_index("id", verify_integrity=True)
    if set(saved.index) != set(frame.id):
        raise ValueError("Baseline validation IDs differ.")
    saved = saved.loc[frame.id]
    for key in ["labels", "source", "tier", "domain_group"]:
        if saved[key].tolist() != frame[key].astype(str).tolist():
            raise ValueError("Baseline validation metadata differs: " + key)
    actual = service._scores(frame.url.tolist())
    if not np.array_equal(actual, saved.char_score.astype(float).to_numpy()):
        raise ValueError("Frozen baseline scores differ from validation checkpoint.")
    return actual


def evaluate(validation):
    results, rows = {}, []
    for family, field in [("char_v1_markers", "baseline_score"), ("char_v2_marker_free", "v2_score")]:
        frame = validation.copy().reset_index(drop=True)
        frame["score"], frame["fold"] = frame[field], frame.domain_group.map(fold_for)
        policies = {}
        for policy, budget in POLICIES.items():
            predictions = np.zeros(len(frame), dtype=bool)
            folds = []
            for fold in range(5):
                held_mask = frame.fold.eq(fold).to_numpy()
                fit, held = frame.loc[~held_mask], frame.loc[held_mask]
                if held.empty or set(fit.domain_group) & set(held.domain_group):
                    raise ValueError("Empty/overlapping domain fold.")
                cutoff = .5 if budget is None else choose_cutoff(fit, budget)
                outputs = alarm(held.score, cutoff)
                predictions[held_mask] = outputs
                folds.append({"fold": fold, "threshold": cutoff, "calibration_n": len(fit),
                              "heldout": group_metrics(held, outputs)})
                for item, output in zip(held.to_dict("records"), outputs):
                    rows.append({"model": family, "policy": policy, "id": item["id"], "fold": fold,
                                 "threshold": cutoff, "alarm": int(output)})
            policies[policy] = {"validation_domain_crossfit": group_metrics(frame, predictions), "folds": folds,
                "full_validation_threshold": .5 if budget is None else choose_cutoff(frame, budget)}
        results[family] = policies
    return results, pd.DataFrame(rows)


def locked_paths():
    return [Path(__file__), ROOT / "app/services/url/character.py", ROOT / "evaluation/url/character_baseline.py",
            ROOT / "evaluation/url/calibration.py", ROOT / "evaluation/url/phishvn.py", ARCHIVE,
            ROOT / "models/inference_XGBoost_d6_s42/url_preprocessing.py",
            *[DEFAULT_DEPLOYMENT / n for n in ["export.json", "vocabulary.json", "weights.npz"]],
            BASELINE / "scores.csv.gz"]


def prepare(out):
    if out.exists():
        raise ValueError("Choose new output; completed experiments are preserved.")
    frames, audit = load_frames()
    out.mkdir(parents=True)
    write_json(out / "execution.json", {"schema": "url-representation-v2-1.0",
        "created_at": datetime.now(timezone.utc).isoformat(), "configuration": CONFIG,
        "representation": REPRESENTATION, "fit_count": 1, "API_calls": 0,
        "split_members_opened": ["train", "val"], "test_evaluated": False,
        "baseline": "frozen char-v1 service; bitwise match to old validation scores required",
        "validation": "historical development data already inspected; not independent holdout",
        "policies": POLICIES, "fold_rule": "same SHA256(url-calibration-v1|domain) modulo5",
        "selection": "single representation/config, no sweep or selection by smoke results",
        "smoke_urls": SMOKE_URLS, "smoke_scope": "known post-fit cases, descriptive and unlabelled; no threshold selection",
        "attribution_limit": "linear score decomposition is descriptive, not causal; TF-IDF normalization changes other terms",
        "source_www_hypothesis": "www prevalence is confounded with source; no www stripping/whitelist intervention",
        "deployment_changes": False, "data_audit": audit,
        "environment": {"python": platform.python_version(), **_versions()},
        "input_hashes": {str(p.resolve()): sha(p) for p in locked_paths()}})
    frames["val"][["id", "labels", "source", "tier", "domain_group"]].to_csv(out / "validation_index.csv", index=False)


def check_lock(out):
    protocol = json.loads((out / "execution.json").read_text())
    if protocol["configuration"] != CONFIG or protocol["policies"] != POLICIES or protocol["representation"] != REPRESENTATION:
        raise ValueError("Registered configuration changed.")
    for path, expected in protocol["input_hashes"].items():
        if sha(path) != expected:
            raise ValueError("Registered source/input changed: " + path)


def report(out, results):
    pct = lambda v: "N/A" if v is None else f"{100*v:.2f}%"
    lines = ["# Marker-free URL representation: validation-only diagnostic", "",
        "One locked train-only configuration, no hyperparameter sweep, no test split opened or scored, no API or app changes. "
        "Historical validation has been inspected before; this is development evidence, not a new generalization estimate. "
        "Only synthetic URL-part markers are removed. Scheme omission, original authority/path/query/fragment and TF-IDF/LR configuration remain fixed.", "",
        "| Model | Policy | Group | TP / positive | FP / negative | Recall | FPR | F1 |",
        "|---|---|---|---:|---:|---:|---:|---:|"]
    for family, policies in results.items():
        for policy, values in policies.items():
            for group, m in values["validation_domain_crossfit"].items():
                lines.append(f"| {family} | {policy} | {group} | {m['tp']}/{m['positive']} | {m['fp']}/{m['negative']} | {pct(m['recall'])} | {pct(m['false_positive_rate'])} | {pct(m['f1'])} |")
    lines += ["", "The FPR5 cutoff is selected on four domain folds and evaluated on the fifth. Full-validation thresholds in summary.json are packaging candidates, not deployed cutoffs or the same five fold values. "
        "Only 24 positive gold/silver references exist. One-class groups intentionally have no Precision/F1. "
        "Known URL smoke cases are unlabelled posthoc diagnostics, excluded from metrics and threshold fitting. "
        "Marker coefficient contributions are descriptive; overlapping n-grams, the intercept and L2 normalization prevent a causal interpretation. "
        "A different representation cannot remove source/time/label confounding; source-balanced prospective data are still required."]
    (out / "report.md").write_text("\n".join(lines) + "\n")


def diagnostics(train, service, model):
    rows = []
    for (label, source), group in train.groupby(["labels", "source"]):
        www = group.url.map(lambda u: service.preprocessing.parse_url_parts(u)[1].startswith("www."))
        rows.append({"label": int(label), "source": source, "n": len(group), "www_n": int(www.sum()), "www_fraction": float(www.mean())})
    smoke = []
    marker_only_terms = {term for marker in ["[DOMAIN]", "[PATH]", "[IP]", "[IPv6]"]
                         for term in service.vectorizer.build_analyzer()(marker)}
    for url in SMOKE_URLS:
        text = service.preprocessing.format_url(url)
        x = service.vectorizer.transform([text]).tocoo()
        names = service.vectorizer.get_feature_names_out()
        contributions = x.data * service.classifier.coef_.ravel()[x.col]
        ranked = np.argsort(contributions)[-10:][::-1]
        smoke.append({"url": url, "reference_label": None, "used_in_metrics": False,
            "baseline_score": float(service._scores([url])[0]),
            "v2_score": float(model.predict_proba([marker_free(url, service.preprocessing)])[0, 1]),
            "baseline_intercept": float(service.classifier.intercept_[0]),
            "baseline_pure_marker_contribution_sum": float(sum(value for value, index in zip(contributions, x.col) if names[index] in marker_only_terms)),
            "baseline_top_positive_contributions": [{"ngram": names[x.col[i]], "contribution": float(contributions[i])} for i in ranked],
            "attribution_is_causal": False})
    return {"source_www_prevalence_train": rows, "smoke": smoke, "smoke_not_benchmark": True}


def run(out):
    check_lock(out)
    if (out / "fit_started.json").exists():
        raise ValueError("Fit already started; no repeated fitting/recovery into same protocol.")
    service = CharURLService()
    if not service.load()["ready"]:
        raise ValueError(service.error)
    frames, _ = load_frames(preprocessing=service.preprocessing)
    val = frames["val"].copy()
    val["baseline_score"] = baseline_scores(val, service)
    write_json(out / "fit_started.json", {"started_at": datetime.now(timezone.utc).isoformat(), "max_new_fits": 1})
    model, info = fit_training_only(frames)
    write_json(out / "fit.json", info)
    val["v2_score"] = model.predict_proba(val.v2_input)[:, 1]
    val[["id", "split", "labels", "source", "tier", "domain_group", "baseline_score", "v2_score"]].to_csv(out / "scores.csv.gz", index=False, compression={"method": "gzip", "mtime": 0})
    results, decisions = evaluate(val)
    write_json(out / "summary.json", results)
    decisions.to_csv(out / "decisions.csv.gz", index=False, compression={"method": "gzip", "mtime": 0})
    write_json(out / "diagnostics.json", diagnostics(frames["train"], service, model))
    report(out, results)
    names = ["execution.json", "validation_index.csv", "fit_started.json", "fit.json", "scores.csv.gz", "summary.json", "decisions.csv.gz", "diagnostics.json", "report.md"]
    write_json(out / "result_hashes.json", {n: sha(out / n) for n in names})
    verify(out)
    print(json.dumps({"completed_new_fits": 1, "validation_n": len(val), "test_evaluated": False, "API_calls": 0, "out": str(out)}))


def verify(out):
    check_lock(out)
    for name, expected in json.loads((out / "result_hashes.json").read_text()).items():
        if sha(out / name) != expected:
            raise ValueError("Result hash changed: " + name)
    scores = pd.read_csv(out / "scores.csv.gz", float_precision="round_trip")
    index = pd.read_csv(out / "validation_index.csv")
    if set(scores.split) != {"val"} or scores.id.duplicated().any():
        raise ValueError("Only unique validation scores are allowed.")
    pd.testing.assert_frame_equal(scores[index.columns], index, check_dtype=False)
    for field in ["baseline_score", "v2_score"]:
        if not np.isfinite(scores[field]).all() or not scores[field].between(0, 1).all():
            raise ValueError("Invalid model scores.")
    results, expected = evaluate(scores)
    if results != json.loads((out / "summary.json").read_text()):
        raise ValueError("Recomputed thresholds/metrics differ.")
    decisions = pd.read_csv(out / "decisions.csv.gz", float_precision="round_trip")
    pd.testing.assert_frame_equal(decisions, expected, check_dtype=False)
    checks = 0
    for (family, policy), group in decisions.groupby(["model", "policy"]):
        aligned = group.set_index("id").loc[scores.id]
        pred = aligned.alarm.to_numpy()
        for name, recorded in results[family][policy]["validation_domain_crossfit"].items():
            mask = np.ones(len(scores), dtype=bool) if name == "full" else scores.tier.isin(["gold", "silver"]).to_numpy() if name == "gold_silver" else scores[name.split(":")[0]].eq(name.split(":")[1]).to_numpy()
            y, output = scores.labels.to_numpy()[mask], pred[mask]
            tn, fp, fn, tp = confusion_matrix(y, output, labels=[0, 1]).ravel()
            if [int(tp), int(fp), int(tn), int(fn)] != [recorded[k] for k in ["tp", "fp", "tn", "fn"]]:
                raise ValueError("Independent confusion check failed.")
            if set(y) == {0, 1}:
                for key, func in [("precision", precision_score), ("recall", recall_score), ("f1", f1_score)]:
                    if not np.isclose(recorded[key], func(y, output, zero_division=0), atol=1e-12):
                        raise ValueError("Independent metrics differ.")
            checks += 1
    write_json(out / "verification.json", {"verified": True, "validation_n": len(scores), "groups_checked": checks,
        "decisions_checked": len(decisions), "new_model_fits": 1, "test_evaluated": False, "API_calls": 0,
        "baseline_validation_scores_bitwise_match": True, "deployment_changes": False})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "run", "verify"])
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    {"prepare": prepare, "run": run, "verify": verify}[args.command](args.out)


if __name__ == "__main__":
    main()
