"""Offline PhishVN baseline reproduction and predeclared bronze/source diagnostics.

One run directory holds the locked protocol, per-fit predictions and a report.
No provider requests, app-model replacement or threshold selection on test.
"""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import platform
import time
import warnings
import zipfile

import numpy as np
import pandas as pd
import scipy
import sklearn
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score, roc_curve
import xgboost as xgb

from evaluation.url.phishvn import SHA256, notebook_constants, prepare_splits

from app.core.settings import ROOT
SCOPES = ("verified_core", "all", "bronze_matched")
FAMILIES = ("LogReg", "RandomForest", "XGBoost_fixed")
FEATURES = ["url_len", "dom_len", "is_ip", "tld_len", "subdom_cnt", "letter_cnt", "digit_cnt",
            "special_cnt", "eq_cnt", "qm_cnt", "amp_cnt", "dot_cnt", "dash_cnt", "under_cnt",
            "letter_ratio", "digit_ratio", "spec_ratio", "slash_cnt", "entropy", "path_len", "query_len"]
CORE = {"gold", "silver"}
SEEDS = list(range(5))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    tmp.replace(path)


def id_hash(ids):
    return hashlib.sha256("\n".join(ids).encode()).hexdigest()


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def align_reference(metadata, reference, formatter):
    metadata = metadata.copy()
    metadata['alignment_key'] = metadata.url.map(lambda url: formatter(url).lower())
    metadata = metadata.set_index('alignment_key', verify_integrity=True)
    keys = reference.url.map(lambda url: formatter(url).lower())
    if not keys.is_unique or set(keys) != set(metadata.index):
        raise ValueError("Feature URLs and official split URLs disagree.")
    aligned = metadata.loc[keys].reset_index()
    for col in ('split','tier'):
        if not np.array_equal(aligned[col].to_numpy(), reference[col].to_numpy()):
            raise ValueError('Feature metadata mismatch: '+col)
    if not np.array_equal(aligned.labels.to_numpy(), reference.label.to_numpy()):
        raise ValueError('Feature labels and official labels disagree.')
    return aligned


def dataset():
    archive = ROOT / "data/raw/PhishVN_v3.1.0_open.zip"
    package = ROOT / "models/inference_XGBoost_d6_s42"
    prep = load_module("audit_preprocessing", package / "url_preprocessing.py")
    frames, audit = prepare_splits(archive, notebook_constants(ROOT / "notebooks/Train_URL_Phishing_GPU.ipynb")["CFG"], prep)
    metadata = pd.concat(frames.values(), ignore_index=True)
    # Published features add schemes and lowercase URL strings; app text preprocessing
    # preserves case. A validated one-to-one key joins the two without changing row order.
    with zipfile.ZipFile(archive) as z:
        raw = z.read("data/vn_compphish.csv")
        manifest = z.read("MANIFEST.txt").decode()
        expected = next(line.split()[0] for line in manifest.splitlines() if "data/vn_compphish.csv" in line)
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("Feature-table MANIFEST mismatch.")
        reference = pd.read_csv(io.BytesIO(raw), low_memory=False)
    # Preserve the author's feature-table row order, including within each split.
    aligned = align_reference(metadata, reference, prep.format_url)
    X = reference[FEATURES].to_numpy(dtype=np.float64)
    if not np.isfinite(X).all():
        raise ValueError("Missing/nonfinite features; no silent imputation.")
    feat = load_module("audit_features", package / "url_features.py")
    sample = np.arange(len(aligned))
    computed = pd.DataFrame([feat.extract_features(reference.iloc[i].url) for i in sample])[FEATURES].to_numpy()
    match = np.isclose(computed, X, rtol=2e-5, atol=2e-5)
    different = {FEATURES[j]:int((~match[:,j]).sum()) for j in range(len(FEATURES)) if not match[:,j].all()}
    # PSL-derived differences are a known reproducibility axis. Keep the author's
    # published values for every scope, and expose drift instead of silently changing them.
    if set(different) - {'dom_len','tld_len','subdom_cnt'}:
        raise ValueError('Unexpected non-PSL feature drift: '+str(different))
    changed = ~match.all(axis=1)
    audit['feature_drift'] = {'different_columns':different,'rows':int(changed.sum()),
        'by_source':aligned.loc[changed].source.value_counts().to_dict(),
        'by_split':aligned.loc[changed].split.value_counts().to_dict(),
        'examples':[{'id':aligned.iloc[i].id,'columns':[FEATURES[j] for j in np.flatnonzero(~match[i])]} for i in np.flatnonzero(changed)[:10]],
        'policy':'published feature values used unchanged for all new fits; app extractor/model not changed'}
    audit["features"] = {"sha256": expected, "count": len(FEATURES), "is_https_excluded": True,
                         "source_label_tier_id_not_features": True, "local_extractor_rows_checked": len(sample),
                         "row_order": "original vn_compphish.csv; numeric float64 like upstream baseline",
                         "metadata_alignment": "one-to-one scheme-stripped lowercase key; all IDs/labels/splits/tiers validated; no feature values rewritten"}
    return aligned, X, audit


def training_masks(frame):
    train = frame.split.eq("train").to_numpy()
    labels = frame.labels.to_numpy()
    core = frame.tier.isin(CORE).to_numpy()
    count = int((train & core & (labels == 1)).sum())
    bronze = np.flatnonzero(train & frame.tier.eq("bronze").to_numpy() & (labels == 1))
    if len(bronze) < count or not count:
        raise ValueError("Cannot construct a size-matched bronze-positive control.")
    ordered = sorted(bronze, key=lambda i: hashlib.sha256(("bronze-match-v1|" + frame.iloc[i].id).encode()).hexdigest())
    matched = train & (labels == 0)
    matched[np.asarray(ordered[:count])] = True
    return {"verified_core": train & core, "all": train, "bronze_matched": matched}


def metrics(y, scores, threshold=.5):
    y, scores = np.asarray(y, dtype=int), np.asarray(scores, dtype=float)
    if len(y) != len(scores) or not np.isfinite(scores).all() or not np.isin(y, [0, 1]).all():
        raise ValueError("Invalid labels or scores.")
    pred = scores >= threshold
    tp, fp = int(((y == 1) & pred).sum()), int(((y == 0) & pred).sum())
    fn, tn = int(((y == 1) & ~pred).sum()), int(((y == 0) & ~pred).sum())
    both = bool(tp + fn and tn + fp)
    div = lambda a, b: a / b if b else None
    result = {"n": len(y), "positive": tp + fn, "negative": fp + tn, "tp": tp, "fp": fp, "tn": tn, "fn": fn,
              "precision": (div(tp, tp + fp) or 0.) if both else None,
              "recall": div(tp, tp + fn), "f1": div(2 * tp, 2 * tp + fp + fn) if both else None,
              "false_positive_rate": div(fp, fp + tn), "accuracy": div(tp + tn, len(y)),
              "roc_auc": float(roc_auc_score(y, scores)) if both else None,
              "average_precision": float(average_precision_score(y, scores)) if both else None,
              "fpr_at_recall90": None}
    if both:
        fpr, tpr, _ = roc_curve(y, scores)
        result["fpr_at_recall90"] = float(fpr[np.flatnonzero(tpr >= .9)[0]])
    return result


def thresholds(y, scores):
    y, scores = np.asarray(y), np.asarray(scores)
    if set(y) != {0, 1}:
        raise ValueError("Validation must contain both classes.")
    precision, recall, cutoffs = precision_recall_curve(y, scores)
    precision, recall = precision[:-1], recall[:-1]
    f2 = 5 * precision * recall / np.maximum(4 * precision + recall, 1e-12)
    feasible = precision >= .8
    pool = np.flatnonzero(feasible) if feasible.any() else np.arange(len(cutoffs))
    best = pool[np.isclose(f2[pool], f2[pool].max(), atol=1e-12, rtol=0)]
    warning = float(cutoffs[min(best, key=lambda j: abs(float(cutoffs[j]) - .5))])
    counts = len(scores) - np.searchsorted(np.sort(scores), cutoffs, side="left")
    candidates = np.flatnonzero((precision >= .95) & (counts >= 30) & (cutoffs >= warning))
    high = None
    if len(candidates):
        i = max(candidates, key=lambda j: (float(recall[j]), float(precision[j]), -float(cutoffs[j])))
        high = float(cutoffs[i])
    return {"warning": warning, "high": high, "warning_precision_met": bool(feasible.any()),
            "validation_positive": int(y.sum()), "validation_negative": int(len(y) - y.sum()),
            "high_count_precision_possible": int(y.sum()) >= 29,
            "rule": "existing notebook F2 + precision>=.80; HIGH precision>=.95, alerts>=30; validation only"}


def make_model(family, seed, positive, negative, rounds, threads):
    if family == "LogReg":
        return LogisticRegression(max_iter=1000, class_weight="balanced")
    if family == "RandomForest":
        return RandomForestClassifier(n_estimators=300, class_weight="balanced", n_jobs=threads, random_state=seed)
    return xgb.XGBClassifier(n_estimators=rounds, max_depth=6, min_child_weight=6,
        learning_rate=.03, tree_method="hist", device="cpu", scale_pos_weight=negative / positive,
        subsample=.9, colsample_bytree=.9, reg_lambda=1., eval_metric="aucpr", n_jobs=threads, random_state=seed)


def prepare(out, threads=4):
    if threads < 1:
        raise ValueError("Use a positive worker/thread count.")
    if (out / "execution.json").exists():
        raise ValueError("Protocol already exists. Run/verify it; choose a new --out to prepare another experiment.")
    upstream = out / "upstream"
    if not (upstream / "train_url_baseline.py").exists():
        raise ValueError("The pinned upstream source snapshot must be collected before preparation.")
    tree = ast.parse((upstream / "train_url_baseline.py").read_text())
    published = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                     and any(isinstance(t, ast.Name) and t.id == "COMPPHISH" for t in n.targets))
    if published != FEATURES:
        raise ValueError("Feature list differs from the pinned author baseline.")
    with zipfile.ZipFile(ROOT/'data/raw/PhishVN_v3.0.0_results_bundle.zip') as z:
        expected = {line.split()[1]:line.split()[0] for line in z.read('p1a_results_bundle/MANIFEST.txt').decode().splitlines() if line.strip()}
        for name in ['per_seed_metrics.csv','environment.json','README.md']:
            payload = z.read('p1a_results_bundle/'+name)
            if hashlib.sha256(payload).hexdigest() != expected[name] or sha(upstream/('reference_'+name)) != expected[name]:
                raise ValueError('Published reference MANIFEST mismatch: '+name)
    frame, _, audit = dataset()
    masks = training_masks(frame)
    existing = xgb.XGBClassifier()
    existing.load_model(ROOT / "models/inference_XGBoost_d6_s42/model.ubj")
    rounds = int(existing.best_iteration) + 1
    input_index = frame[["id", "split", "labels", "source", "tier", "domain_group", "tld"]].copy()
    scopes = {}
    for scope, mask in masks.items():
        input_index["fit_" + scope] = mask.astype(int)
        subset = frame.loc[mask]
        scopes[scope] = {"n": len(subset), "positive": int(subset.labels.sum()),
                         "negative": int(subset.labels.eq(0).sum()), "ids_sha256": id_hash(subset.id),
                         "sources": subset.source.value_counts().to_dict()}
    out.mkdir(parents=True, exist_ok=True)
    input_index.to_csv(out / "data_index.csv.gz", index=False, compression={"method": "gzip", "mtime": 0})
    files = [Path(__file__), ROOT / "evaluation/url/phishvn.py", ROOT / "notebooks/Train_URL_Phishing_GPU.ipynb",
             ROOT / "scripts/evaluation/reproduce_phishvn_baseline.py",
             ROOT / "models/inference_XGBoost_d6_s42/model.ubj", ROOT / "models/inference_XGBoost_d6_s42/config.json",
             ROOT / "models/inference_XGBoost_d6_s42/url_features.py", ROOT / "models/inference_XGBoost_d6_s42/url_preprocessing.py",
             ROOT / "data/raw/PhishVN_v3.1.0_open.zip", ROOT / "data/raw/PhishVN_v3.0.0_results_bundle.zip"]
    files += sorted(p for p in upstream.iterdir() if p.is_file())
    configuration = {"schema": "url-source-audit-1.0", "created_at": datetime.now(timezone.utc).isoformat(),
        "archive_sha256": SHA256, "threads": threads, "feature_names": FEATURES, "scopes": scopes,
        "families": list(FAMILIES), "stochastic_seeds": SEEDS, "fixed_threshold": .5, "xgb_fixed_rounds": rounds,
        "xgb_rounds_origin": "existing app best_iteration+1; selected on historical validation, reused unchanged in every scope; no early stopping here",
        "model_selection": "none; all predeclared fits are reported, no test-based winner selection",
        "label_scope": "source-listed abuse/anti-fraud, not independently verified credential phishing",
        "independent_new_test": False, "API_calls": 0, "matched_bronze_selection": "first N SHA256(bronze-match-v1|id), N=core train positives; identical benign train rows",
        "threshold_transfer": "diagnostic calibration on full validation versus gold/silver validation, never test; no app deployment",
        "bootstrap": {"draws": 1000, "seed": 20261105, "unit": "registrable domain", "seeds": "fixed mean; does not include refit/label uncertainty"},
        "versions": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__,
                     "sklearn": sklearn.__version__, "scipy": scipy.__version__, "xgboost": xgb.__version__},
        "reference_reproduction": {"fits": 6, "numpy": "1.26.4", "pandas": "2.2.2", "sklearn": "1.4.2",
            "platform_difference": "Linux x86_64 versus author macOS ARM; same source, data, feature order, seeds, threshold and major package versions; score differences are reported"},
        "source_hashes": {str(p.resolve()): sha(p) for p in files}, "index_sha256": sha(out / "data_index.csv.gz")}
    configuration["fits"] = [{"family": fam, "scope": scope, "seed": seed, "id": f"{scope}--{fam}--s{seed}"}
                             for scope in SCOPES for fam in FAMILIES for seed in ([0] if fam == "LogReg" else SEEDS)]
    dump(out / "data_audit.json", audit)
    # Protocol is persisted before any model fit or prediction.
    dump(out / "execution.json", configuration)
    print(json.dumps({"prepared": str(out), "fits": len(configuration["fits"]), "scopes": scopes}, ensure_ascii=False), flush=True)


def check_protocol(out):
    cfg = json.loads((out / "execution.json").read_text())
    for path, expected in cfg["source_hashes"].items():
        if sha(path) != expected:
            raise ValueError("Registered source/input changed: " + path)
    if sha(out / "data_index.csv.gz") != cfg["index_sha256"]:
        raise ValueError("Registered input index changed.")
    return cfg


def run(out):
    cfg = check_protocol(out)
    frame, X, _ = dataset()
    index = pd.read_csv(out / "data_index.csv.gz", keep_default_na=False)
    if not np.array_equal(index.id, frame.id):
        raise ValueError("Changed input ordering.")
    masks = training_masks(frame)
    eval_mask = ~frame.split.eq("train").to_numpy()
    evaluation = frame.loc[eval_mask, ["id", "split", "labels"]].copy()
    val = frame.split.eq("val").to_numpy()
    for plan in cfg["fits"]:
        marker = out / "fits" / (plan["id"] + ".json")
        if marker.exists():
            info = json.loads(marker.read_text())
            if sha(out / info["predictions"]) != info["predictions_sha256"]:
                raise ValueError("Changed checkpoint: " + plan["id"])
            continue
        mask = masks[plan["scope"]]
        train = frame.loc[mask]
        if id_hash(train.id) != cfg["scopes"][plan["scope"]]["ids_sha256"]:
            raise ValueError("Changed fit cohort.")
        model = make_model(plan["family"], plan["seed"], int(train.labels.sum()), int(train.labels.eq(0).sum()), cfg["xgb_fixed_rounds"], cfg["threads"])
        start = time.perf_counter()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            model.fit(X[mask], train.labels.to_numpy())
        elapsed = time.perf_counter() - start
        scores = model.predict_proba(X[eval_mask])[:, 1]
        result = evaluation.copy(); result["score"] = scores
        rel = "predictions/" + plan["id"] + ".csv.gz"
        (out / "predictions").mkdir(exist_ok=True); marker.parent.mkdir(exist_ok=True)
        tmp = out / (rel + ".tmp")
        result.to_csv(tmp, index=False, float_format="%.17g", compression={"method": "gzip", "mtime": 0})
        tmp.replace(out / rel)
        calibration = {}
        for label, subset in (("full_val", np.ones(int(val.sum()), dtype=bool)), ("core_val", frame.loc[val].tier.isin(CORE).to_numpy())):
            sv = scores[evaluation.split.eq("val").to_numpy()]
            calibration[label] = thresholds(frame.loc[val].labels.to_numpy()[subset], sv[subset])
        info = {**plan, "train": cfg["scopes"][plan["scope"]], "fit_seconds": elapsed,
                "parameters": model.get_params(), "warnings": [{"category": type(w.message).__name__, "message": str(w.message)} for w in caught],
                "predictions": rel, "predictions_sha256": sha(out / rel), "thresholds": calibration}
        # XGBoost get_params may hold a missing-value NaN, which is a setting, not a result.
        info["parameters"] = {k: (None if isinstance(v, float) and not np.isfinite(v) else v) for k, v in info["parameters"].items()}
        if hasattr(model, "n_iter_"): info["n_iter"] = np.asarray(model.n_iter_).tolist()
        if hasattr(model, "feature_importances_"): info["feature_importances"] = model.feature_importances_.tolist()
        dump(marker, info)
        print(f"[{len(list(marker.parent.glob('*.json')))}/{len(cfg['fits'])}] {plan['id']} fit {elapsed:.2f}s, warnings={len(caught)}", flush=True)
    report(out)


def load_predictions(out, cfg, index):
    result = {}
    expected = index[index.split != "train"]
    for plan in cfg["fits"]:
        marker = out / "fits" / (plan["id"] + ".json")
        info = json.loads(marker.read_text())
        if sha(out / info["predictions"]) != info["predictions_sha256"]:
            raise ValueError("Prediction checksum mismatch.")
        rows = pd.read_csv(out / info["predictions"], float_precision="round_trip")
        if not np.array_equal(rows.id, expected.id) or not np.array_equal(rows.labels, expected.labels) or not np.array_equal(rows.split, expected.split):
            raise ValueError("Checkpoint IDs/labels/splits changed.")
        if len(rows) != len(expected) or not rows.score.between(0, 1).all():
            raise ValueError("Invalid probability scores.")
        result[plan["id"]] = (plan, info, rows)
    return result


def aggregate(records):
    result = {}
    for name in ["precision", "recall", "f1", "false_positive_rate", "accuracy", "roc_auc", "average_precision", "fpr_at_recall90"]:
        values = [r[name] for r in records if r[name] is not None]
        result[name] = {"mean": float(np.mean(values)), "std": float(np.std(values)), "runs": len(values)} if values else None
    return result


def paired_bootstrap(index, predictions, family, a, b, subset, cfg):
    test = index[index.split == "test"].reset_index(drop=True)
    test = test.loc[subset].reset_index(drop=True)
    _, group = np.unique(test.domain_group, return_inverse=True)
    seeds = [0] if family == "LogReg" else cfg["stochastic_seeds"]
    confusion = {}
    for scope in (a, b):
        entries = []
        for seed in seeds:
            rows = predictions[f"{scope}--{family}--s{seed}"][2]
            values = rows[rows.split == "test"].score.to_numpy()[subset] >= .5
            y = test.labels.to_numpy()
            entries.append(np.array([np.bincount(group, weights=mask.astype(int), minlength=group.max()+1)
                                     for mask in [(y == 1) & values, (y == 0) & values, (y == 0) & ~values, (y == 1) & ~values]]))
        confusion[scope] = np.asarray(entries)
    rng = np.random.default_rng(cfg["bootstrap"]["seed"])
    deltas = {"f1": [], "false_positive_rate": []}
    for _ in range(cfg["bootstrap"]["draws"]):
        weights = np.bincount(rng.integers(0, group.max()+1, group.max()+1), minlength=group.max()+1)
        metrics_by_scope = {}
        for scope, entries in confusion.items():
            counts = np.einsum('scg,g->sc', entries, weights)
            tp, fp, tn, fn = counts.T
            if np.any(2*tp+fp+fn == 0) or np.any(fp+tn == 0):
                break
            metrics_by_scope[scope] = (np.mean(2*tp/(2*tp+fp+fn)), np.mean(fp/(fp+tn)))
        if len(metrics_by_scope) != 2:
            continue
        for i, key in enumerate(deltas): deltas[key].append(float(metrics_by_scope[b][i] - metrics_by_scope[a][i]))
    if not deltas['f1']:
        return {"direction": b + " minus " + a, "valid_draws": 0, "f1_delta_95": None, "fpr_delta_95": None}
    return {"direction": b + " minus " + a, "domains": int(group.max()+1), "valid_draws": len(deltas['f1']),
            "f1_delta_95": np.percentile(deltas["f1"], [2.5,97.5]).tolist(),
            "fpr_delta_95": np.percentile(deltas["false_positive_rate"], [2.5,97.5]).tolist()}


def report(out):
    cfg = check_protocol(out)
    index = pd.read_csv(out / "data_index.csv.gz", keep_default_na=False)
    predictions = load_predictions(out, cfg, index)
    test = index[index.split == "test"].reset_index(drop=True)
    cohorts = {"full_test": np.ones(len(test), dtype=bool), "core_test": test.tier.isin(CORE).to_numpy(),
               "bronze_plus_same_benign": (test.tier.eq("bronze") | test.labels.eq(0)).to_numpy()}
    per_run, transfer = [], []
    for runid, (plan, info, rows) in predictions.items():
        scores = rows[rows.split == "test"].score.to_numpy()
        for cohort, mask in cohorts.items():
            per_run.append({**plan, "cohort": cohort, **metrics(test.labels.to_numpy()[mask], scores[mask])})
        for field in ("source", "tier"):
            for value in sorted(test[field].unique()):
                mask = test[field].eq(value).to_numpy()
                per_run.append({**plan, "cohort": field+":"+str(value), **metrics(test.labels.to_numpy()[mask], scores[mask])})
        for calibration, settings in info["thresholds"].items():
            for name in ("warning", "high"):
                threshold = settings[name]
                for cohort in ("full_test", "core_test"):
                    mask = cohorts[cohort]
                    transfer.append({**plan, "calibration": calibration, "level": name, "threshold": threshold,
                                     "cohort": cohort, "constraint": settings,
                                     "metrics": metrics(test.labels.to_numpy()[mask], scores[mask], threshold) if threshold is not None else None})
    grouped = {}
    for family in FAMILIES:
        grouped[family] = {}
        for scope in SCOPES:
            grouped[family][scope] = {cohort: aggregate([r for r in per_run if r["family"] == family and r["scope"] == scope and r["cohort"] == cohort])
                                      for cohort in [*cohorts, *sorted({r['cohort'] for r in per_run if ':' in r['cohort']})]}
    bootstrap = {}
    for family in FAMILIES:
        bootstrap[family] = {f"{a}_vs_{b}/{cohort}": paired_bootstrap(index, predictions, family, a, b, mask, cfg)
                             for a,b in [("verified_core","all"),("verified_core","bronze_matched")]
                             for cohort,mask in cohorts.items() if cohort in {"full_test","core_test"}}
    reference = pd.read_csv(out / "upstream/reference_per_seed_metrics.csv")
    reproduction = json.loads((out / 'reference_reproduction/summary.json').read_text())
    summary = {"configuration": cfg, "metrics": grouped, "per_run": per_run, "threshold_transfer": transfer,
               "paired_bootstrap": bootstrap, "published_reference_columns": list(reference.columns),
               "published_reference": reference.to_dict('records'), "reference_reproduction": reproduction}
    dump(out / "summary.json", summary)
    pd.DataFrame(per_run).to_csv(out / "metrics_by_source_tier.csv", index=False)
    def cell(metric):
        if metric is None:return 'N/A'
        return f"{metric['mean']*100:.2f}" + (f" ± {metric['std']*100:.2f}" if metric['runs']>1 else '')
    lines = ["# PhishVN: baseline reproduction and bronze/source audit", "",
        "Retrospective analysis on the existing official test; not an independent new test. No API calls or app changes. "
        "All scopes use the same published 21 features, train/test split, benign training rows and fixed decision threshold 0.5. "
        "LogReg is deterministic; RF/XGB use seeds 0–4 (population std). XGB reuses the old validation-selected 241 boosting rounds, "
        "fixed across scopes, on CPU; it is an extension, not a published PhishVN baseline or a bitwise reproduction of the GPU app model.", "",
        "## Core test (gold/silver)", "", "| Family | Training scope | Precision % | Recall % | F1 % | FPR % |", "|---|---|---:|---:|---:|---:|"]
    for cohort in ("core_test", "full_test"):
        if cohort == "full_test":lines += ["", "## Full official test", "", lines[6], lines[7]]
        for family in FAMILIES:
            for scope in SCOPES:
                m = grouped[family][scope][cohort]
                lines.append(f"| {family} | {scope} | {cell(m['precision'])} | {cell(m['recall'])} | {cell(m['f1'])} | {cell(m['false_positive_rate'])} |")
    lines += ["", "## Published reference vs isolated-environment reproduction", "",
        "NumPy 1.26.4, pandas 2.2.2, scikit-learn 1.4.2, same gold/silver rows, features, seeds and 0.5 cutoff. "
        "Python patch/OS/BLAS differ from the author's macOS environment; differences are retained, not optimized away.", "",
        "| Family | Published F1 % | Refit F1 % | Decision disagreements (sum over seeds) | Max absolute score difference |",
        "|---|---:|---:|---:|---:|"]
    for family in ['LogReg','RandomForest']:
        records = [r for r in reproduction if r['family']==family]
        published_values = [r['published_metrics_recomputed']['f1'] for r in records]
        refit_values = [r['metrics']['f1'] for r in records]
        fmt = lambda values: cell({'mean':float(np.mean(values)),'std':float(np.std(values)),'runs':len(values)})
        lines.append(f"| {family} | {fmt(published_values)} | {fmt(refit_values)} | {sum(r['decision_disagreements'] for r in records)} | {max(r['max_abs_score_difference'] for r in records):.10g} |")
    lines += ["", "## Source-conditioned rates at 0.5", "",
        "Recall is meaningful on the positive sources; FPR is meaningful on benign sources. "
        "These sources differ in date, label quality and abuse scope as well as provenance.", "",
        "| Family | Training scope | NCSC recall % | ChongLuaDao recall % | Global Tranco FPR % | Tranco VN FPR % |",
        "|---|---|---:|---:|---:|---:|"]
    for family in FAMILIES:
        for scope in SCOPES:
            g = grouped[family][scope]
            lines.append(f"| {family} | {scope} | {cell(g['source:tinnhiemmang']['recall'])} | {cell(g['source:chongluadao']['recall'])} | {cell(g['source:tranco']['false_positive_rate'])} | {cell(g['source:tranco_vn']['false_positive_rate'])} |")
    lines += ["", "## Validation-source threshold transfer (seed 0 only)", "",
        "The fixed-0.5 tables above are the primary protocol. These are additional retrospective diagnostics; "
        "all seeds and both test cohorts are in summary.json.", "",
        "| Family (all-data fit) | Calibration | Validation positives | WARNING cutoff | HIGH cutoff | Core-test Recall at WARNING % | Core-test FPR at WARNING % |",
        "|---|---|---:|---:|---:|---:|---:|"]
    for family in FAMILIES:
        for calibration in ['full_val','core_val']:
            runid=f'all--{family}--s0'
            settings=predictions[runid][1]['thresholds'][calibration]
            m=next(r['metrics'] for r in transfer if r['id']==runid and r['calibration']==calibration and r['level']=='warning' and r['cohort']=='core_test')
            high = 'not feasible' if settings['high'] is None else f"{settings['high']:.6f}"
            lines.append(f"| {family} | {calibration} | {settings['validation_positive']} | {settings['warning']:.6f} | {high} | {m['recall']*100:.2f} | {m['false_positive_rate']*100:.2f} |")
    lines += ["", "## Interpretation boundaries", "",
        "Gold/silver and bronze positives differ in source, time, label definition/noise and sample count. "
        "The matched bronze control equalizes training counts and uses identical benign rows, but does not isolate a causal source effect. "
        "Source groups often contain a single class: report recall on positive-only sources and FPR on negative-only sources; precision/F1 are N/A there. "
        "Domain bootstrap conditions on these source labels and fixed fitted seeds, not label accuracy, a new deployment or refitting uncertainty.", "",
        "Core validation has only 24 positives: precision >=95% with >=30 alerts is mathematically impossible even if all positives are detected. "
        "Threshold-transfer tables are diagnostics, not a new deployment policy; UNKNOWN/abstention is a separate app behavior.", "",
        "See summary.json for every threshold, validation cohort, paired interval, and published per-seed reference. "
        "CSV metrics and per-fit prediction checkpoints are retained for verification. No model was selected using this test."]
    (out / "report.md").write_text('\n'.join(lines)+'\n')
    verify(out)
    print('Completed and verified:',out/'report.md',flush=True)


def verify(out):
    from sklearn.metrics import confusion_matrix, precision_score, recall_score, f1_score
    cfg = check_protocol(out)
    index = pd.read_csv(out / "data_index.csv.gz", keep_default_na=False)
    predictions = load_predictions(out,cfg,index)
    summary = json.loads((out / "summary.json").read_text())
    test = index[index.split == 'test'].reset_index(drop=True)
    for r in summary['per_run']:
        field = r['cohort']
        if field == 'full_test':mask = np.ones(len(test),dtype=bool)
        elif field == 'core_test':mask = test.tier.isin(CORE).to_numpy()
        elif field == 'bronze_plus_same_benign':mask=(test.tier.eq('bronze')|test.labels.eq(0)).to_numpy()
        else:
            column,value=field.split(':',1);mask=test[column].eq(value).to_numpy()
        rows=predictions[r['id']][2];scores=rows[rows.split=='test'].score.to_numpy()[mask]
        y=test.labels.to_numpy()[mask];pred=scores>=.5
        tn,fp,fn,tp=confusion_matrix(y,pred,labels=[0,1]).ravel()
        assert [r[k] for k in ['tn','fp','fn','tp']]==[int(tn),int(fp),int(fn),int(tp)]
        assert metrics(y,scores)=={k:r[k] for k in metrics(y,scores)}
        if set(y)=={0,1}:
            assert np.isclose(r['precision'],precision_score(y,pred,zero_division=0))
            assert np.isclose(r['recall'],recall_score(y,pred,zero_division=0))
            assert np.isclose(r['f1'],f1_score(y,pred,zero_division=0))
    for r in summary['threshold_transfer']:
        if r['threshold'] is None:
            assert r['metrics'] is None
            continue
        mask = np.ones(len(test), dtype=bool) if r['cohort']=='full_test' else test.tier.isin(CORE).to_numpy()
        rows = predictions[r['id']][2]
        scores = rows[rows.split=='test'].score.to_numpy()[mask]
        assert metrics(test.labels.to_numpy()[mask], scores, r['threshold']) == r['metrics']
    for record in summary['reference_reproduction']:
        p = out/'reference_reproduction'/f"{record['family']}_seed{record['seed']}.csv.gz"
        assert sha(p) == record['prediction_sha256']
        rows = pd.read_csv(p,float_precision='round_trip')
        core = test[test.tier.isin(CORE)]
        assert np.array_equal(rows.id,core.id) and np.array_equal(rows.labels,core.labels)
        m = metrics(rows.labels,rows.score)
        for key,value in record['metrics'].items():assert np.isclose(m[key],value)
    from statistics import mean, pstdev
    for family, scopes in summary['metrics'].items():
        for scope, cohorts in scopes.items():
            for cohort, measures in cohorts.items():
                records=[r for r in summary['per_run'] if r['family']==family and r['scope']==scope and r['cohort']==cohort]
                for key, measure in measures.items():
                    values=[r[key] for r in records if r[key] is not None]
                    if measure is None:assert not values
                    else:assert measure['runs']==len(values) and np.isclose(measure['mean'],mean(values)) and np.isclose(measure['std'],pstdev(values))
    dump(out/'verification.json',{'verified':True,'fits':len(predictions),'metric_rows':len(summary['per_run']),
        'API_calls':0,'independent_new_test':False,'checks':'registered input/source hashes; prediction IDs, splits, labels and scores; sklearn confusion/P/R/F1; no app-model writes',
        'files':{p.name:sha(p) for p in [out/'execution.json',out/'data_index.csv.gz',out/'summary.json',out/'metrics_by_source_tier.csv']}})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['prepare','run','report','verify'])
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--threads',type=int,default=4)
    args=parser.parse_args()
    if args.command=='prepare':prepare(args.out,args.threads)
    else:{'run':run,'report':report,'verify':verify}[args.command](args.out)


if __name__=='__main__':main()
