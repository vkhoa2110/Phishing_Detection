"""Check saved retrieval counts and dev-only threshold selection without embedding or API calls."""
import argparse
import hashlib
import json
import math
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def counts(predictions, threshold):
    hits = rejected = correct = returned = positives = negatives = 0
    for p in predictions:
        gold = set(p["relevant_ids"])
        selected = {d["document_id"] for d in p["ranked"] if d["score"] >= threshold}
        positives += bool(gold)
        negatives += not gold
        hits += bool(gold & selected)
        rejected += not gold and not selected
        correct += len(gold & selected)
        returned += len(selected)
    return {"hits": hits, "rejected": rejected, "correct": correct, "returned": returned,
            "positives": positives, "negatives": negatives}


def verify(run, corpus, dev, test, index):
    summary, predictions = read(run / "summary.json"), read(run / "predictions.json")
    for key, path in (("corpus", corpus), ("dev", dev), ("test", test), ("index_manifest", index / "manifest.json")):
        if hashlib.sha256(path.read_bytes()).hexdigest() != summary["configuration"][key + "_sha256"]:
            raise ValueError("Input fingerprint mismatch: " + key)
    known = {d["id"] for d in rows(corpus)}
    result = {}
    for method, calibration in summary["calibration"].items():
        for split, cases in (("dev", rows(dev)), ("test", rows(test))):
            saved = predictions[split][method]
            if [p["id"] for p in saved] != [c["id"] for c in cases]:
                raise ValueError("Prediction IDs/order disagree.")
            for p, c in zip(saved, cases):
                ranked = p["ranked"]
                if p["relevant_ids"] != c["relevant_ids"] or len(ranked) != 3:
                    raise ValueError("Relevance labels or top-3 count changed.")
                if len({d["document_id"] for d in ranked}) != 3 or not {d["document_id"] for d in ranked} <= known:
                    raise ValueError("Invalid returned source IDs.")
                if not all(math.isfinite(d["score"]) for d in ranked) or [d["score"] for d in ranked] != sorted([d["score"] for d in ranked], reverse=True):
                    raise ValueError("Invalid ranking scores.")
            for mode, threshold in (("raw_top3", -math.inf), ("filtered", calibration["min_score"])):
                if threshold is None:
                    if summary["methods"][method][split + "_" + mode] is not None:
                        raise ValueError("Infeasible calibration must remain null.")
                    continue
                n = counts(saved, threshold)
                expected = {"hit_at_3": n["hits"] / n["positives"],
                            "rejected_no_match": n["rejected"], "returned_sources": n["returned"],
                            "precision_returned_sources": n["correct"] / n["returned"] if n["returned"] else None}
                report = summary["methods"][method][split + "_" + mode]
                if any(report[k] != v for k, v in expected.items()):
                    raise ValueError("Reported metrics disagree: " + method + "/" + split + "/" + mode)
                if split == "test" and mode == "filtered":
                    result[method] = n
        candidates = {0., 1., *(d["score"] for p in predictions["dev"][method] for d in p["ranked"])}
        feasible = []
        for threshold in candidates:
            n = counts(predictions["dev"][method], threshold)
            if n["hits"] / n["positives"] >= .9:
                objective = ((n["hits"] / n["positives"] + n["rejected"] / n["negatives"]) / 2,
                             n["correct"] / n["returned"] if n["returned"] else 0, threshold)
                feasible.append((objective, threshold))
        selected = max(feasible)[1] if feasible else None
        if selected != calibration["min_score"]:
            raise ValueError("Threshold does not match dev-only objective: " + method)
    if read(run / "calibration.json") != summary["calibration"]:
        raise ValueError("Pre-test calibration changed.")
    return {"status": "passed", "test_counts": result,
            "scope": "Independent arithmetic, input hashes, source IDs and dev-only objective; not semantic relevance review or an independent embedding recomputation."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    for name in ("corpus", "dev", "test", "index"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.run, args.corpus, args.dev, args.test, args.index)
    path = args.run / "verification.json"
    if path.exists():
        parser.error("Verification output already exists.")
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
