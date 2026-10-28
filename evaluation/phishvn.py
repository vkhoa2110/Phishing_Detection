"""Evaluate the exported model on its official PhishVN holdout, then a paired LLM subset."""
import argparse
import ast
import asyncio
from collections import Counter
from dataclasses import replace
import hashlib
import io
import itertools
import json
from pathlib import Path
import random
import re
import sys
import time
import zipfile

import httpx
import numpy as np
import pandas as pd
from sklearn.metrics import (accuracy_score, average_precision_score, confusion_matrix,
                             f1_score, precision_score, recall_score, roc_auc_score)
import tldextract

from app.fusion import fuse_legacy as fuse
from app.llm_service import LLMFailure, LLMService
from app.ml_service import ModelService
from app.privacy import redact
from app.settings import Settings
from .run import ARMS, FATAL_CODES, digest, load_checkpoints, prepare_manifest, summarize, write_json

DOI = "https://data.mendeley.com/datasets/b97hxbxtpd/4"
SHA256 = "308351e9d0c0fca13a81f2f63524a7dee08ccba6c775848d125b3da5525d0ab5"


def notebook_constants(path):
    values = {}
    for cell in json.loads(Path(path).read_text(encoding="utf-8"))["cells"]:
        if cell["cell_type"] != "code":
            continue
        for node in ast.parse("".join(cell.get("source", []))).body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in {"CFG", "FEATURE_SOURCE", "PREPROCESSING_SOURCE"}:
                        values[target.id] = ast.literal_eval(node.value)
    return values


def prepare_splits(archive, cfg, preprocessing):
    if digest(archive) != SHA256 or cfg["DATA_SHA256"] != SHA256 or cfg["DATA_SCOPE"] != "all" or cfg["SMOKE_TEST"]:
        raise ValueError("Archive/config differs from the full-data training run.")
    ext = tldextract.TLDExtract(suffix_list_urls=(), include_psl_private_domains=False)
    def domain_group(url):
        _, host = preprocessing.parse_url_parts(url)
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError:
            pass
        return ext(host).top_domain_under_public_suffix or host
    frames, audit = {}, {}
    with zipfile.ZipFile(archive) as package:
        manifest = package.read("MANIFEST.txt").decode("utf-8")
        for split in ("train", "val", "test"):
            name = f"data/splits/url_{split}.csv"
            data = package.read(name)
            expected = re.search(r"(?m)^([0-9a-f]{64})\s+" + re.escape(name) + r"\s", manifest)
            if not expected or hashlib.sha256(data).hexdigest() != expected.group(1):
                raise ValueError(f"MANIFEST mismatch: {split}")
            raw = pd.read_csv(io.BytesIO(data), dtype=str, keep_default_na=False)
            if set(raw["split"].str.strip()) != {split}:
                raise ValueError("Split labels disagree with official files.")
            rows, invalid = [], []
            for item in raw.to_dict("records"):
                label = item["label"].strip().lower()
                if label not in {"benign", "phishing"}:
                    raise ValueError("Unknown original label.")
                try:
                    item.update(model_input=preprocessing.format_url(item["url"]), domain_group=domain_group(item["url"]), labels=int(label == "phishing"))
                except (ValueError, UnicodeError):
                    invalid.append(item["id"])
                    continue
                rows.append(item)
            df = pd.DataFrame(rows)
            duplicates = int(df.duplicated("model_input").sum())
            df = df.drop_duplicates(["model_input", "labels"]).reset_index(drop=True)
            if df.groupby("model_input").labels.nunique().gt(1).any():
                raise ValueError("Conflicting labels for the same normalized URL.")
            frames[split] = df
            audit[split] = {"raw": len(raw), "clean": len(df), "invalid_ids": invalid,
                            "duplicates": duplicates, "benign": int((df.labels == 0).sum()), "phishing": int(df.labels.sum()),
                            "sha256": expected.group(1)}
    for a, b in itertools.combinations(frames, 2):
        for col in ("id", "model_input", "domain_group"):
            if set(frames[a][col]) & set(frames[b][col]):
                raise ValueError(f"Leakage across {a}/{b}: {col}")
    return frames, audit


def recover_fingerprint(cfg, values, frames, spec):
    config = {k: v for k, v in cfg.items() if k not in {
        "WORK_DIR", "DRIVE_DIR", "USE_DRIVE", "HF_CACHE_DIR", "LOCAL_DATA_ZIP", "ALLOW_CPU", "RESUME_TRAINING"}}
    config.update(pipeline_version="urltrain-2.1", package_versions=spec["versions"],
                  feature_sha256=hashlib.sha256(values["FEATURE_SOURCE"].encode()).hexdigest(),
                  preprocessing_sha256=hashlib.sha256(values["PREPROCESSING_SOURCE"].encode()).hexdigest())
    split_digest = hashlib.sha256()
    for name, df in frames.items():
        split_digest.update(name.encode())
        split_digest.update("\n".join(df.id).encode())
    config["used_split_ids_sha256"] = split_digest.hexdigest()
    for bf16 in (False, True):
        candidate = dict(config)
        if cfg["RUN_BERT"]:
            ram = spec["hardware"]["vram_gb"]
            candidate["bert_runtime"] = {"gpu": spec["hardware"]["gpu"], "bf16": bf16,
                                         "auto_batch": 64 if ram >= 32 else 32 if ram >= 20 else 16}
        fingerprint = hashlib.sha256(json.dumps(candidate, sort_keys=True).encode()).hexdigest()[:12]
        if fingerprint == spec["fingerprint"]:
            return fingerprint, candidate
    raise ValueError("Could not reproduce the exported training fingerprint; do not call this an unseen official holdout.")


def binary_metrics(labels, scores, threshold):
    labels, scores = np.asarray(labels), np.asarray(scores)
    predictions = (scores >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(labels, predictions, labels=[0, 1]).ravel()
    return {"n": len(labels), "threshold": threshold, "accuracy": float(accuracy_score(labels, predictions)),
            "precision": float(precision_score(labels, predictions, zero_division=0)),
            "recall": float(recall_score(labels, predictions, zero_division=0)), "f1": float(f1_score(labels, predictions, zero_division=0)),
            "false_positive_rate": float(fp / (fp + tn)) if fp + tn else None,
            "roc_auc": float(roc_auc_score(labels, scores)) if len(set(labels)) == 2 else None,
            "average_precision": float(average_precision_score(labels, scores)) if len(set(labels)) == 2 else None,
            "tp": int(tp), "fp": int(fp), "tn": int(tn), "fn": int(fn)}


def paired_rows(selected, predictions, cache):
    rows = []
    for item in selected.to_dict("records"):
        url = predictions[item["id"]]
        only = cache.get((item["id"], ARMS[0]), {"status": "pending"})
        informed = cache.get((item["id"], ARMS[1]), {"status": "pending"})
        def level(llm):
            return llm.get("verdict", {}).get("risk_level", "UNKNOWN") if llm["status"] == "ok" else "UNKNOWN"
        rows.append({"id": item["id"], "label": item["labels"], "text": item["url"], "mode": "url",
                     "category": item["source"], "source": item["source"], "tier": item["tier"], "urls": [url],
                     "llm_only": only, "llm_with_url_model": informed,
                     "levels": {"url_model_only": url["risk_level"], "llm_only": level(only), "llm_with_url_model": level(informed),
                                "fusion_independent": fuse("url", [url], only, [])["risk_level"] if only["status"] != "pending" else "UNKNOWN",
                                "fusion_with_url_model": fuse("url", [url], informed, [])["risk_level"] if informed["status"] != "pending" else "UNKNOWN"}})
    return rows


async def evaluate(args):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    settings = replace(Settings(), max_tokens=4096, timeout_seconds=90)
    model = ModelService(settings)
    if not model.load()["ready"]:
        raise ValueError(model.error)
    constants = notebook_constants(args.notebook)
    for key, name in (("FEATURE_SOURCE", "url_features.py"), ("PREPROCESSING_SOURCE", "url_preprocessing.py")):
        if constants[key] != (model.path / name).read_text(encoding="utf-8"):
            raise ValueError("Notebook and exported inference source disagree.")
    frames, audit = prepare_splits(args.archive, constants["CFG"], sys.modules["url_preprocessing"])
    fingerprint, recovered = recover_fingerprint(constants["CFG"], constants, frames, model.spec)
    write_json(out / "provenance.json", {"doi": DOI, "archive_sha256": SHA256, "notebook_sha256": digest(args.notebook),
               "recovered_fingerprint": fingerprint, "fingerprint_configuration": recovered, "splits": audit,
               "disjoint_columns_checked": ["id", "model_input", "domain_group"],
               "feature_source_matches_notebook": True, "preprocessing_source_matches_notebook": True})
    print("Verified dataset, splits, feature source and training fingerprint:", fingerprint, flush=True)
    # Select from labels/IDs only, before model scores, independently within both classes.
    selected = pd.concat([frames["test"][frames["test"].labels == label].sample(n=args.llm_sample // 2, random_state=args.seed)
                          for label in (0, 1)]).sample(frac=1, random_state=args.seed).reset_index(drop=True)
    selected[["id", "labels", "source", "tier"]].to_csv(out / "selected_ids.csv", index=False)
    spec = model.spec
    thresholds = {"warning": spec["thresholds"]["warning_threshold"], "high": spec["thresholds"]["high_threshold"], "fixed_0.5": .5}
    full_metrics, test_outputs = {}, None
    for split in ("val", "test"):
        frame = frames[split]
        outputs = model.predictor.predict(frame.url.tolist())
        scores = [o["score"] for o in outputs]
        full_metrics[split] = {name: binary_metrics(frame.labels, scores, threshold) for name, threshold in thresholds.items() if threshold is not None}
        result = frame[["id", "url", "labels", "source", "tier", "domain_group"]].copy()
        result["score"] = scores
        result["risk_level"] = [o["risk_level"] for o in outputs]
        result.to_csv(out / f"{split}_predictions.csv", index=False)
        if split == "test":
            test_outputs = dict(zip(frame.id, outputs))
            full_metrics["test_by_tier"] = {str(t): binary_metrics(g.labels, g.score, thresholds["warning"]) for t, g in result.groupby("tier")}
            full_metrics["test_by_source"] = {str(t): binary_metrics(g.labels, g.score, thresholds["warning"]) for t, g in result.groupby("source")}
            core = result[result.tier.isin(["gold", "silver"])]
            full_metrics["test_verified_core"] = binary_metrics(core.labels, core.score, thresholds["warning"])
        print(split, len(frame), full_metrics[split], flush=True)
    full_metrics["validation_reproduction"] = {name: {k: full_metrics["val"][name][k] - expected[k] for k in ("tp", "fp", "tn", "fn")}
                for name, expected in (("warning", spec["thresholds"]["validation_metrics"]), ("fixed_0.5", spec["validation_at_05"]))}
    write_json(out / "url_model_metrics.json", full_metrics)
    if any(abs(delta) > 1 for changes in full_metrics["validation_reproduction"].values() for delta in changes.values()):
        raise ValueError("Validation metrics differ from the export by more than one boundary-tie row; investigate before LLM evaluation.")
    predictions = {key: {**value, "id": "URL-01", "status": "ok"} for key, value in test_outputs.items()}
    config = {"dataset": DOI, "archive_sha256": SHA256, "notebook_sha256": digest(args.notebook),
              "model_sha256": digest(model.path / "model.ubj"), "config_sha256": digest(model.path / "config.json"),
              "runner_sha256": digest(__file__), "sample_ids": selected.id.tolist(), "seed": args.seed,
              "llm_model": settings.llm_model, "endpoint": settings.endpoint, "max_tokens": settings.max_tokens, "timeout": 90,
              "prompt_sha256": digest(Path(__file__).parents[1] / "app/llm_service.py"), "live": args.live}
    prepare_manifest(out, config)
    cache = load_checkpoints(out / "checkpoints.jsonl")
    def save():
        rows = paired_rows(selected, predictions, cache)
        write_json(out / "summary.json", summarize(rows))
        (out / "results.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        pd.DataFrame([{k: r[k] for k in ("id", "label", "source", "tier")} | r["levels"] for r in rows]).to_csv(out / "comparison.csv", index=False)
    save()
    if args.live:
        queue = asyncio.Queue()
        for index, item in enumerate(selected.to_dict("records")):
            queue.put_nowait((index, item))
        state = {"stop": False, "new_calls": 0}
        async with httpx.AsyncClient(timeout=90, trust_env=False) as client:
            service = LLMService(settings, client)
            async def worker():
                while not queue.empty() and not state["stop"]:
                    index, item = queue.get_nowait()
                    for arm in (ARMS if index % 2 == 0 else tuple(reversed(ARMS))):
                        key = (item["id"], arm)
                        if key in cache:
                            continue
                        if state["stop"]:
                            break
                        state["new_calls"] += 1
                        try:
                            result = await service.analyze(text=redact(item["url"])[0], mode="url", urls=[predictions[item["id"]]],
                                  include_ml=arm == "llm_with_url_model", endpoint="", model="", api_key="")
                        except LLMFailure as exc:
                            result = {"status": "error", "code": exc.code}
                        except Exception as exc:
                            result = {"status": "error", "code": "UNEXPECTED_" + type(exc).__name__}
                        cache[key] = result
                        with (out / "checkpoints.jsonl").open("a", encoding="utf-8") as file:
                            file.write(json.dumps({"case_id": item["id"], "arm": arm, "result": result}, ensure_ascii=False) + "\n")
                            file.flush()
                        if result.get("code") in FATAL_CODES:
                            state["stop"] = True
                        save()
                        print(f"[{len(cache)}/{2 * len(selected)}] {arm}: {result['status']} {result.get('verdict', {}).get('risk_level', '')} {result.get('code', '')}", flush=True)
            await asyncio.gather(worker(), worker())
        write_json(out / "call_state.json", state)
    save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--notebook", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "artifacts/evaluations/phishvn_new")
    parser.add_argument("--llm-sample", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20261026)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if args.llm_sample < 2 or args.llm_sample % 2:
        parser.error("--llm-sample must be positive and even.")
    asyncio.run(evaluate(args))


if __name__ == "__main__":
    main()
