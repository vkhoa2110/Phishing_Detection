"""Locked three-fit factorial URL diagnostic on historical train/validation.

This lossy model representation is not a URL identity or trust normalizer.
No official test member is read, no API is called, no model is deployed.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import time
import warnings

import numpy as np
import pandas as pd
from sklearn.metrics import confusion_matrix, f1_score, precision_score, recall_score

from app.services.url.character import DEFAULT_DEPLOYMENT, CharURLService, _learned_hashes, _versions
from evaluation.url.calibration import alarm, choose_cutoff, fold_for, group_metrics, sha, write_json
from evaluation.url.character_baseline import CONFIG, pipeline
from evaluation.url.representation import ARCHIVE, BASELINE, SMOKE_URLS, baseline_scores, load_frames

from app.core.settings import ROOT
POLICIES = {"fixed_0.5": None, "fpr_5pct": .05}
ARMS = {
    "char_v1_baseline": {"field": "baseline_score", "strip_www": False, "source_weighted": False},
    "A_strip_www": {"field": "A_score", "strip_www": True, "source_weighted": False},
    "B_source_weighted": {"field": "B_score", "strip_www": False, "source_weighted": True},
    "C_strip_www_source_weighted": {"field": "C_score", "strip_www": True, "source_weighted": True},
}
FIT_ORDER = list(ARMS)[1:]
GATES = {"policy": "fpr_5pct", "minimum_gold_silver_true_positives": 22,
         "maximum_phishing_source_recall_drop": .05,
         "scope": "research eligibility only; never automatic app promotion or a population guarantee"}
REPRESENTATION = (
    "Keep exact V1 format_url markers and text, removing only one case-insensitive leading "
    "'www.' from the hostname position of authority, after any userinfo. Preserve original "
    "userinfo, port, case, path, query, fragment. Model view only: raw URL/id/domain identity "
    "and every row/label remain unchanged; www and non-www are not assumed equivalent."
)
WEIGHTING = (
    "Train-only sample_weight_i=N/(2*K_y*n_(y,source_i)); K_y is number of distinct sources "
    "within label y. TF-IDF fits all train documents without weights. Weighted LR uses "
    "class_weight=None; unweighted arms retain balanced class_weight. No double balancing."
)


def www_model_view(url, preprocessing):
    """Strip one hostname prefix only; preserve V1 prefix even for IP-like suffixes."""
    parts, host = preprocessing.parse_url_parts(url)
    text = preprocessing.format_url(url)
    if not host.startswith("www."):
        return text
    userinfo, separator, authority = parts.netloc.rpartition("@")
    if not separator:
        authority, userinfo = parts.netloc, ""
    if not authority.lower().startswith("www."):
        raise ValueError("Hostname/authority mismatch.")
    changed = (userinfo + separator if separator else "") + authority[4:]
    prefix, body = text.split(" ", 1)
    if not body.startswith(parts.netloc):
        raise ValueError("Unexpected V1 formatter authority.")
    return prefix + " " + changed + body[len(parts.netloc):]


def source_weights(train):
    """Equal total class mass and equal source mass within each class, from train only."""
    if set(train.split) != {"train"} or set(train.labels) != {0, 1}:
        raise ValueError("Weights require official two-class train.")
    if train.source.isna().any() or train.source.astype(str).str.strip().eq("").any():
        raise ValueError("Empty training source.")
    counts = train.groupby(["labels", "source"], sort=True).size()
    source_counts = train.groupby("labels").source.nunique()
    n = len(train)
    weights = np.asarray([n / (2 * source_counts.loc[label] * counts.loc[(label, source)])
                          for label, source in zip(train.labels, train.source)], dtype=np.float64)
    if not np.isfinite(weights).all() or (weights <= 0).any() or not np.isclose(weights.sum(), n):
        raise ValueError("Invalid source weights.")
    rows = []
    for (label, source), count in counts.items():
        mask = train.labels.eq(label) & train.source.eq(source)
        rows.append({"label": int(label), "source": source, "n": int(count),
                     "sources_in_label": int(source_counts.loc[label]),
                     "per_sample_weight": float(weights[mask.to_numpy()][0]),
                     "total_weight": float(weights[mask.to_numpy()].sum())})
    return weights, {"n": n, "weight_sum": float(weights.sum()), "groups": rows,
                     "weights_sha256": hashlib.sha256(weights.tobytes()).hexdigest(),
                     "class_weight": None, "learned_from": "train labels/sources/counts only"}


def add_views(frames, preprocessing):
    for frame in frames.values():
        frame["v3_input"] = frame.url.map(lambda value: www_model_view(value, preprocessing))
    for field in ["id", "model_input", "v3_input", "domain_group"]:
        if set(frames["train"][field]) & set(frames["val"][field]):
            raise ValueError("Train/validation overlap: " + field)
    audit = {}
    for split, frame in frames.items():
        grouped = frame.groupby("v3_input", sort=False)
        collision = grouped.size().gt(1)
        conflict = grouped.labels.nunique().gt(1)
        audit[split] = {"n": len(frame), "view_changed": int(frame.v3_input.ne(frame.model_input).sum()),
                        "colliding_views": int(collision.sum()),
                        "rows_in_collisions": int(grouped.size()[collision].sum()),
                        "conflicting_label_views": int(conflict.sum()),
                        "rows_in_conflicting_views": int(grouped.size()[conflict].sum()),
                        "rows_removed_or_relabeled": 0,
                        "model_view_sha256": hashlib.sha256("\n".join(frame.v3_input).encode()).hexdigest()}
    return audit


def fit_arm(frames, arm):
    if arm not in FIT_ORDER:
        raise ValueError("Only the three preregistered new arms may fit.")
    train = frames["train"]
    if set(train.split) != {"train"} or set(train.labels) != {0, 1}:
        raise ValueError("Fit requires official two-class train.")
    for field in ["id", "model_input", "v3_input", "domain_group"]:
        if set(train[field]) & set(frames["val"][field]):
            raise ValueError("Train/validation overlap: " + field)
    settings = ARMS[arm]
    field = "v3_input" if settings["strip_www"] else "model_input"
    model = pipeline()
    weights, weight_info = source_weights(train) if settings["source_weighted"] else (None, None)
    if settings["source_weighted"]:
        model["classifier"].set_params(class_weight=None)
    started = time.perf_counter()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        model.fit(train[field], train.labels, **({"classifier__sample_weight": weights} if weights is not None else {}))
    return model, {"arm": arm, "train_n": len(train), "train_positive": int(train.labels.sum()),
                   "train_negative": int(train.labels.eq(0).sum()), "input_field": field,
                   "class_weight": model["classifier"].class_weight,
                   "source_weighting": weight_info,
                   "train_seconds": time.perf_counter() - started,
                   "vocabulary_size": len(model["tfidf"].vocabulary_),
                   "iterations": model["classifier"].n_iter_.tolist(),
                   "warnings": [str(item.message) for item in caught],
                   **_learned_hashes(model["tfidf"], model["classifier"])}


def evaluate(validation):
    results, rows = {}, []
    for family, settings in ARMS.items():
        frame = validation.copy().reset_index(drop=True)
        frame["score"] = frame[settings["field"]]
        frame["fold"] = frame.domain_group.map(fold_for)
        policies = {}
        for policy, budget in POLICIES.items():
            predictions, folds = np.zeros(len(frame), dtype=bool), []
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


def failures(validation, decisions):
    result = {}
    for (family, policy), group in decisions.groupby(["model", "policy"]):
        pred = group.set_index("id").loc[validation.id].alarm.to_numpy(dtype=bool)
        baseline = decisions.loc[decisions.model.eq("char_v1_baseline") & decisions.policy.eq(policy)]
        base = baseline.set_index("id").loc[validation.id].alarm.to_numpy(dtype=bool)
        y = validation.labels.to_numpy()
        result[family + "/" + policy] = {
            "false_positive_ids": validation.id[(y == 0) & pred].tolist(),
            "false_negative_ids": validation.id[(y == 1) & ~pred].tolist(),
            "corrected_vs_baseline_ids": validation.id[(base != y) & (pred == y)].tolist(),
            "regressed_vs_baseline_ids": validation.id[(base == y) & (pred != y)].tolist()}
    return result


def research_gates(results):
    baseline = results["char_v1_baseline"][GATES["policy"]]["validation_domain_crossfit"]
    gates = {}
    for arm in FIT_ORDER:
        groups = results[arm][GATES["policy"]]["validation_domain_crossfit"]
        sources = []
        for name, metric in groups.items():
            if name.startswith("source:") and metric["positive"]:
                delta = metric["recall"] - baseline[name]["recall"]
                sources.append({"source": name[7:], "positive_n": metric["positive"],
                                "baseline_recall": baseline[name]["recall"], "recall": metric["recall"],
                                "delta": delta, "passes": delta >= -GATES["maximum_phishing_source_recall_drop"],
                                "small_positive_group": metric["positive"] < 30})
        core_pass = groups["gold_silver"]["tp"] >= GATES["minimum_gold_silver_true_positives"]
        gates[arm] = {"gold_silver_tp": groups["gold_silver"]["tp"], "core_gate_passes": core_pass,
                      "positive_sources": sources, "passes": core_pass and all(row["passes"] for row in sources),
                      "deployment_authorized": False}
    return {"preregistered_gates": GATES, "arms": gates}


def load_research_model(directory):
    """Reconstruct only numeric arrays, requiring matching configuration/hashes."""
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest["schema"] != "url-source-robust-v3-research-model-1.0" or manifest["arm_settings"] != ARMS[manifest["arm"]]:
        raise ValueError("Invalid research model schema/arm.")
    if manifest["training_configuration"] != CONFIG or manifest["versions"] != _versions():
        raise ValueError("Research model environment/configuration mismatch.")
    if manifest["runner_sha256"] != sha(Path(__file__)) or manifest["preprocessing_sha256"] != sha(ROOT / "models/inference_XGBoost_d6_s42/url_preprocessing.py"):
        raise ValueError("Research model source changed.")
    for name in ["vocabulary.json", "weights.npz"]:
        if manifest["files"][name] != sha(directory / name):
            raise ValueError("Research model file hash changed.")
    vocabulary = json.loads((directory / "vocabulary.json").read_text())
    if not vocabulary or any(type(value) is not int for value in vocabulary.values()) or set(vocabulary.values()) != set(range(len(vocabulary))):
        raise ValueError("Invalid research vocabulary.")
    with np.load(directory / "weights.npz", allow_pickle=False) as saved:
        if set(saved.files) != {"idf", "coef", "intercept", "classes"}:
            raise ValueError("Invalid research weight arrays.")
        arrays = {name: saved[name].copy() for name in saved.files}
    n = len(vocabulary)
    if arrays["idf"].shape != (n,) or arrays["coef"].shape != (1, n) or arrays["intercept"].shape != (1,) or not np.array_equal(arrays["classes"], [0, 1]):
        raise ValueError("Invalid research weight dimensions.")
    if any(array.dtype != np.float64 or not np.isfinite(array).all() for name, array in arrays.items() if name != "classes") or (arrays["idf"] <= 0).any():
        raise ValueError("Invalid research numeric weights.")
    model = pipeline()
    model["tfidf"].set_params(vocabulary=vocabulary)
    model["tfidf"].idf_ = arrays["idf"]
    classifier = model["classifier"]
    classifier.set_params(class_weight=manifest["effective_class_weight"])
    classifier.classes_, classifier.coef_ = arrays["classes"], arrays["coef"]
    classifier.intercept_, classifier.n_features_in_ = arrays["intercept"], n
    model["tfidf"].transform(["[DOMAIN] example.invalid"])
    if _learned_hashes(model["tfidf"], classifier) != manifest["learned_hashes"]:
        raise ValueError("Research model learned hashes differ.")
    return model


def export_research_model(out, arm, model, validation_texts):
    """Preserve this exact fit for independent diagnostics, never pickle or refit."""
    directory = out / "research_models" / arm
    directory.mkdir(parents=True)
    vectorizer, classifier = model["tfidf"], model["classifier"]
    write_json(directory / "vocabulary.json", {key: int(value) for key, value in vectorizer.vocabulary_.items()})
    np.savez_compressed(directory / "weights.npz", idf=vectorizer.idf_, coef=classifier.coef_,
                        intercept=classifier.intercept_, classes=classifier.classes_)
    write_json(directory / "manifest.json", {"schema": "url-source-robust-v3-research-model-1.0",
        "arm": arm, "arm_settings": ARMS[arm], "training_configuration": CONFIG,
        "effective_class_weight": classifier.class_weight,
        "representation": REPRESENTATION, "weighting": WEIGHTING,
        "purpose": "exact original fit preserved for diagnostics, not production deployment",
        "policies": POLICIES, "versions": _versions(),
        "runner_sha256": sha(Path(__file__)),
        "preprocessing_sha256": sha(ROOT / "models/inference_XGBoost_d6_s42/url_preprocessing.py"),
        "execution_sha256": sha(out / "execution.json"),
        "learned_hashes": _learned_hashes(vectorizer, classifier),
        "files": {name: sha(directory / name) for name in ["vocabulary.json", "weights.npz"]}})
    reconstructed = load_research_model(directory)
    if not np.array_equal(model.predict_proba(validation_texts), reconstructed.predict_proba(validation_texts)):
        raise ValueError("Research export scores differ from original fit.")
    return {"validation_rows": len(validation_texts), "all_scores_bitwise_match": True,
            "new_fits_for_export": 0}


def locked_paths():
    return [Path(__file__), ROOT / "evaluation/url/representation.py",
            ROOT / "evaluation/url/character_baseline.py", ROOT / "evaluation/url/calibration.py",
            ROOT / "evaluation/url/phishvn.py", ROOT / "app/services/url/character.py", ARCHIVE,
            ROOT / "models/inference_XGBoost_d6_s42/url_preprocessing.py",
            *[DEFAULT_DEPLOYMENT / name for name in ["export.json", "vocabulary.json", "weights.npz"]],
            BASELINE / "scores.csv.gz"]


def prepare(out):
    if out.exists():
        raise ValueError("Choose new output; completed experiments are preserved.")
    service = CharURLService()
    if not service.load()["ready"]:
        raise ValueError(service.error)
    frames, audit = load_frames(preprocessing=service.preprocessing)
    views = add_views(frames, service.preprocessing)
    _, weights = source_weights(frames["train"])
    out.mkdir(parents=True)
    write_json(out / "execution.json", {"schema": "url-source-robust-v3-1.0",
        "created_at": datetime.now(timezone.utc).isoformat(), "configuration": CONFIG,
        "arms": ARMS, "fit_order": FIT_ORDER, "fit_count": 3, "API_calls": 0,
        "representation": REPRESENTATION, "weighting": WEIGHTING,
        "split_members_opened": ["train", "val"], "test_evaluated": False,
        "baseline": "frozen char-v1 service; validation scores must match saved checkpoint bitwise before fits",
        "validation": "historical development data already inspected; no independent holdout",
        "policies": POLICIES, "fold_rule": "SHA256(url-calibration-v1|domain) modulo5",
        "research_gates": GATES,
        "selection": "fixed factorial interventions, no sweep, no smoke-based selection; retain every result",
        "smoke_urls": SMOKE_URLS, "smoke_scope": "four known unlabelled post-fit examples, descriptive only",
        "identity_scope": "www/non-www may have different owners/content; model view is lossy, not URL equivalence or a trust rule",
        "deployment_changes": False, "data_audit": audit, "view_audit": views,
        "train_source_weight_audit": weights,
        "environment": {"python": platform.python_version(), **_versions()},
        "input_hashes": {str(path.resolve()): sha(path) for path in locked_paths()}})
    frames["val"][["id", "labels", "source", "tier", "domain_group"]].to_csv(out / "validation_index.csv", index=False)


def check_lock(out):
    protocol = json.loads((out / "execution.json").read_text())
    for field, expected in [("configuration", CONFIG), ("arms", ARMS), ("fit_order", FIT_ORDER),
                            ("policies", POLICIES), ("representation", REPRESENTATION), ("weighting", WEIGHTING)]:
        if protocol[field] != expected:
            raise ValueError("Registered configuration changed: " + field)
    if protocol["research_gates"] != GATES:
        raise ValueError("Registered research gates changed.")
    for path, expected in protocol["input_hashes"].items():
        if sha(path) != expected:
            raise ValueError("Registered source/input changed: " + path)


def report(out, results):
    pct = lambda value: "N/A" if value is None else f"{100 * value:.2f}%"
    lines = ["# URL source robustness: locked factorial development diagnostic", "",
        "Three new train-only fits, one frozen V1 baseline. No test split opened or scored, no API calls, no app update. "
        "Historical validation was already inspected; these are development comparisons, not independent effectiveness estimates.", "",
        "A strips exactly one leading www. from the hostname in the model representation only, retaining V1 markers. "
        "B balances source mass within each label using train-only sample weights and class_weight=None. C combines both. "
        "Raw URL identities/labels remain unchanged. This lossy representation does not assert that www and non-www sites are equivalent.", "",
        "| Model | Policy | Group | TP / positive | FP / negative | Recall | FPR | F1 |",
        "|---|---|---|---:|---:|---:|---:|---:|"]
    for family, policies in results.items():
        for policy, values in policies.items():
            for group, metric in values["validation_domain_crossfit"].items():
                lines.append(f"| {family} | {policy} | {group} | {metric['tp']}/{metric['positive']} | "
                             f"{metric['fp']}/{metric['negative']} | {pct(metric['recall'])} | "
                             f"{pct(metric['false_positive_rate'])} | {pct(metric['f1'])} |")
    lines += ["", "FPR5 thresholds use negatives in four domain folds and score the fifth. Full-validation cutoffs are "
        "recorded separately and are not deployed. Positive/negative source counts and tiers remain confounded with collection, "
        "time, label quality and campaign. Only 24 gold/silver validation positives exist; one-class groups have no Precision/F1. "
        "Source balancing uses source labels at training time only, requires no source inference at prediction, and is not a proof "
        "of removing shortcuts. The sparse source/tier positive groups limit source-transfer conclusions. Four smoke URLs are "
        "unlabelled descriptive cases, excluded from metrics/calibration/selection. Keep all arms even when they regress. "
        "Exact fitted weights/vocabularies are retained in research_models without a second fit; these are research exports, not app replacements. "
        "Preregistered eligibility gates require at least 22/24 core positives and no positive-source recall drop exceeding 5 percentage points "
        "under FPR5 cross-fitting; passing is not deployment approval."]
    (out / "report.md").write_text("\n".join(lines) + "\n")


def run(out):
    check_lock(out)
    if (out / "fit_started.json").exists():
        raise ValueError("Fit already started; no repeated fitting/recovery into same protocol.")
    service = CharURLService()
    if not service.load()["ready"]:
        raise ValueError(service.error)
    frames, _ = load_frames(preprocessing=service.preprocessing)
    views = add_views(frames, service.preprocessing)
    protocol = json.loads((out / "execution.json").read_text())
    if views != protocol["view_audit"]:
        raise ValueError("Registered model views changed.")
    val = frames["val"].copy()
    val["baseline_score"] = baseline_scores(val, service)
    baseline_hashes = _learned_hashes(service.vectorizer, service.classifier)
    write_json(out / "fit_started.json", {"started_at": datetime.now(timezone.utc).isoformat(), "max_new_fits": 3,
                                           "baseline_validation_scores_bitwise_match": True})
    fits, smoke = {}, [{"url": url, "reference_label": None, "used_in_metrics": False,
                        "char_v1_baseline": float(service._scores([url])[0])} for url in SMOKE_URLS]
    for arm in FIT_ORDER:
        model, info = fit_arm(frames, arm)
        fits[arm] = info
        if arm == "B_source_weighted" and any(info[key] != baseline_hashes[key] for key in ["vocabulary_sha256", "idf_sha256"]):
            raise ValueError("Source weighting unexpectedly changed V1 TF-IDF vocabulary/IDF.")
        if arm == "C_strip_www_source_weighted" and any(info[key] != fits["A_strip_www"][key] for key in ["vocabulary_sha256", "idf_sha256"]):
            raise ValueError("Source weighting unexpectedly changed stripped TF-IDF vocabulary/IDF.")
        val[ARMS[arm]["field"]] = model.predict_proba(val[info["input_field"]])[:, 1]
        for row in smoke:
            text = www_model_view(row["url"], service.preprocessing) if ARMS[arm]["strip_www"] else service.preprocessing.format_url(row["url"])
            row[arm] = float(model.predict_proba([text])[0, 1])
        info["research_export_equivalence"] = export_research_model(out, arm, model, val[info["input_field"]])
        write_json(out / "fit.json", fits)
    fields = ["id", "split", "labels", "source", "tier", "domain_group", *[settings["field"] for settings in ARMS.values()]]
    val[fields].to_csv(out / "scores.csv.gz", index=False, compression={"method": "gzip", "mtime": 0})
    results, decisions = evaluate(val)
    write_json(out / "summary.json", results)
    decisions.to_csv(out / "decisions.csv.gz", index=False, compression={"method": "gzip", "mtime": 0})
    write_json(out / "failures.json", failures(val, decisions))
    write_json(out / "candidate_gates.json", research_gates(results))
    write_json(out / "smoke.json", {"scope": protocol["smoke_scope"], "examples": smoke})
    report(out, results)
    names = ["execution.json", "validation_index.csv", "fit_started.json", "fit.json", "scores.csv.gz",
             "summary.json", "decisions.csv.gz", "failures.json", "candidate_gates.json", "smoke.json", "report.md",
             *[f"research_models/{arm}/{name}" for arm in FIT_ORDER for name in ["vocabulary.json", "weights.npz", "manifest.json"]]]
    write_json(out / "result_hashes.json", {name: sha(out / name) for name in names})
    verify(out)
    print(json.dumps({"completed_new_fits": 3, "validation_n": len(val), "test_evaluated": False,
                      "API_calls": 0, "out": str(out)}), flush=True)


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
    for settings in ARMS.values():
        field = settings["field"]
        if not np.isfinite(scores[field]).all() or not scores[field].between(0, 1).all():
            raise ValueError("Invalid model scores.")
    service = CharURLService()
    if not service.load()["ready"]:
        raise ValueError(service.error)
    frames, _ = load_frames(preprocessing=service.preprocessing)
    audit = add_views(frames, service.preprocessing)
    protocol = json.loads((out / "execution.json").read_text())
    if audit != protocol["view_audit"] or source_weights(frames["train"])[1] != protocol["train_source_weight_audit"]:
        raise ValueError("Registered train model views or source weights changed.")
    np.testing.assert_array_equal(baseline_scores(frames["val"], service), scores.baseline_score.to_numpy())
    results, expected = evaluate(scores)
    if results != json.loads((out / "summary.json").read_text()):
        raise ValueError("Recomputed thresholds/metrics differ.")
    decisions = pd.read_csv(out / "decisions.csv.gz", float_precision="round_trip")
    pd.testing.assert_frame_equal(decisions, expected, check_dtype=False)
    if failures(scores, decisions) != json.loads((out / "failures.json").read_text()):
        raise ValueError("Failure inventory differs.")
    if research_gates(results) != json.loads((out / "candidate_gates.json").read_text()):
        raise ValueError("Preregistered research gate results differ.")
    fit = json.loads((out / "fit.json").read_text())
    if list(fit) != FIT_ORDER:
        raise ValueError("Incorrect fit count/order.")
    for arm in FIT_ORDER:
        model = load_research_model(out / "research_models" / arm)
        field = "v3_input" if ARMS[arm]["strip_www"] else "model_input"
        np.testing.assert_array_equal(model.predict_proba(frames["val"][field])[:, 1], scores[ARMS[arm]["field"]].to_numpy())
    checks = 0
    for (family, policy), group in decisions.groupby(["model", "policy"]):
        pred = group.set_index("id").loc[scores.id].alarm.to_numpy()
        for name, recorded in results[family][policy]["validation_domain_crossfit"].items():
            mask = np.ones(len(scores), dtype=bool) if name == "full" else scores.tier.isin(["gold", "silver"]).to_numpy() if name == "gold_silver" else scores[name.split(":")[0]].eq(name.split(":")[1]).to_numpy()
            y, output = scores.labels.to_numpy()[mask], pred[mask]
            tn, fp, fn, tp = confusion_matrix(y, output, labels=[0, 1]).ravel()
            if [int(tp), int(fp), int(tn), int(fn)] != [recorded[key] for key in ["tp", "fp", "tn", "fn"]]:
                raise ValueError("Independent confusion check failed.")
            if set(y) == {0, 1}:
                for key, func in [("precision", precision_score), ("recall", recall_score), ("f1", f1_score)]:
                    if not np.isclose(recorded[key], func(y, output, zero_division=0), atol=1e-12):
                        raise ValueError("Independent metrics differ.")
            checks += 1
    write_json(out / "verification.json", {"verified": True, "validation_n": len(scores), "groups_checked": checks,
        "decisions_checked": len(decisions), "new_model_fits": 3, "test_evaluated": False, "API_calls": 0,
        "baseline_validation_scores_bitwise_match": True, "deployment_changes": False})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "run", "verify"])
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    {"prepare": prepare, "run": run, "verify": verify}[args.command](args.out)


if __name__ == "__main__":
    main()
