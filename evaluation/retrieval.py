"""Calibrate on dev, then evaluate held-out queries. No LLM/API calls."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import time

import numpy as np

from app.privacy import redact
from app.rag_service import E5Encoder, RetrievalIndex, rank_chunks, read_jsonl, sha_file, write_json
from app.settings import ROOT


def score_cases(cases, index, encoder):
    rows = []
    known = {c["document_id"] for c in index.chunks}
    for case in cases:
        if not set(case["relevant_ids"]) <= known:
            raise ValueError("Unknown relevance ID.")
        start = time.perf_counter()
        text = redact(case["text"])[0]
        windows = encoder.split(text)
        vectors = encoder.encode(windows, "query: ")
        ranked = rank_chunks(index.chunks, index.vectors, vectors, top_k=3)
        rows.append({"id": case["id"], "relevant_ids": case["relevant_ids"],
                     "ranked": [{"document_id": d["document_id"], "score": d["score"]} for d in ranked],
                     "elapsed_ms": round((time.perf_counter() - start) * 1000, 2)})
    return rows


def metrics(rows, threshold):
    positive = [r for r in rows if r["relevant_ids"]]
    negative = [r for r in rows if not r["relevant_ids"]]
    hits = 0
    returned, correct = 0, 0
    accepted_negative = 0
    for r in rows:
        selected = [d["document_id"] for d in r["ranked"] if d["score"] >= threshold]
        hits += bool(set(selected) & set(r["relevant_ids"]))
        returned += len(selected)
        correct += len(set(selected) & set(r["relevant_ids"]))
        accepted_negative += bool(selected) and not r["relevant_ids"]
    hit_rate = hits / len(positive) if positive else 0
    rejection = 1 - accepted_negative / len(negative) if negative else 0
    return {"n": len(rows), "relevant_queries": len(positive), "no_match_queries": len(negative),
            "hit_at_3": hit_rate, "rejected_no_match": len(negative) - accepted_negative,
            "false_retrievals_no_match": accepted_negative, "no_match_rejection_rate": rejection,
            "balanced_query_accuracy": (hit_rate + rejection) / 2,
            "precision_returned_sources": correct / returned if returned else None,
            "returned_sources": returned,
            "mean_ms": float(np.mean([r["elapsed_ms"] for r in rows])),
            "p95_ms": float(np.percentile([r["elapsed_ms"] for r in rows], 95))}


def select_threshold(rows):
    if not any(r["relevant_ids"] for r in rows) or not any(not r["relevant_ids"] for r in rows):
        raise ValueError("Calibration needs relevant and no-match queries.")
    candidates = sorted({0., 1., *(d["score"] for r in rows for d in r["ranked"])})
    scored = [(t, metrics(rows, t)) for t in candidates]
    # Recall constraint is a registered target, not silently relaxed if it fails.
    feasible = [(t, m) for t, m in scored if m["hit_at_3"] >= .90]
    if not feasible:
        raise ValueError("No threshold meets the 90% dev hit@3 constraint; review corpus/retrieval.")
    threshold, result = max(feasible, key=lambda x: (x[1]["balanced_query_accuracy"],
                                                   x[1]["precision_returned_sources"] or 0, x[0]))
    return threshold, result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=ROOT / "artifacts/rag/e5-small-v1")
    parser.add_argument("--model-dir", type=Path, default=ROOT / "models/embeddings/multilingual-e5-small")
    parser.add_argument("--corpus", type=Path, default=ROOT / "data/knowledge/corpus_v1/documents.jsonl")
    parser.add_argument("--dev", type=Path, default=ROOT / "data/evaluation/rag_retrieval_dev_v1.jsonl")
    parser.add_argument("--test", type=Path, default=ROOT / "data/evaluation/rag_retrieval_test_v1.jsonl")
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts/rag-evaluation/e5-small-v1")
    args = parser.parse_args()
    if args.out.exists() or (args.index / "calibration.json").exists():
        parser.error("Choose fresh index/evaluation directories; previous calibration is frozen.")
    dev, test = read_jsonl(args.dev), read_jsonl(args.test)
    if len({r["id"] for r in dev + test}) != len(dev + test) or len({r["text"] for r in dev + test}) != len(dev + test):
        parser.error("Dev/test must have unique IDs and texts.")
    index = RetrievalIndex.load(args.index, args.corpus)
    encoder = E5Encoder(args.model_dir)
    dev_rows = score_cases(dev, index, encoder)
    threshold, dev_metrics = select_threshold(dev_rows)
    config = {"min_score": threshold, "top_k": 3, "selected_on": "dev",
              "method": "maximize balanced query accuracy subject to dev hit@3 >= 0.90; ties precision then higher threshold",
              "dev_sha256": sha_file(args.dev), "index_manifest_sha256": sha_file(args.index / "manifest.json")}
    # Freeze before reading test predictions; test is never used by select_threshold.
    write_json(args.index / "calibration.json", config)
    test_rows = score_cases(test, index, encoder)
    args.out.mkdir(parents=True)
    result = {"created_at": datetime.now(timezone.utc).isoformat(), "calibration": config,
              "dev": dev_metrics, "test": metrics(test_rows, threshold),
              "test_sha256": sha_file(args.test),
              "limitations": "Assistant-authored smoke queries with source IDs, not independent human annotations; held-out wording shares source topics. Retrieval metrics are not phishing classification metrics."}
    write_json(args.out / "summary.json", result)
    write_json(args.out / "predictions.json", {"dev": dev_rows, "test": test_rows})
    print(__import__('json').dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
