"""Validate exhaustive, blinded retrieval judgments and score frozen top-3 lists.

No LLM judge, source heuristic or substring match is substituted for relevance.
Unfinished reviews cannot produce retrieval-quality metrics.
"""
import argparse
from collections import Counter
import csv
import json
import math
from pathlib import Path

from .benchmark_pack import RELEVANCE_FIELDS, sheet
from .message_data import read_jsonl, sha, spreadsheet_cell, write_json
from .review import ReviewPending


def workspace(path):
    path = Path(path)
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    allowed = {"queries.jsonl", "corpus.jsonl", "pairs.jsonl", "rubric.json"}
    if set(manifest["files"]) != allowed:
        raise ValueError("Unexpected relevance inputs.")
    for name, expected in manifest["files"].items():
        if sha(path / name) != expected:
            raise ValueError("Relevance input changed: " + name)
    pairs = read_jsonl(path / "pairs.jsonl")
    queries, docs = read_jsonl(path / "queries.jsonl"), read_jsonl(path / "corpus.jsonl")
    keys = {(q["id"], d["id"]) for q in queries for d in docs}
    if len(pairs) != len(keys) or {(p["query_id"], p["document_id"]) for p in pairs} != keys:
        raise ValueError("Relevance matrix must cover every query and document.")
    return pairs, queries, docs


def read_ratings(path, pairs):
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not set(RELEVANCE_FIELDS) <= set(reader.fieldnames or []):
            raise ValueError("Missing relevance rating columns.")
        rows = list(reader)
    ratings = {(r["query_id"], r["document_id"]): r for r in rows}
    if len(ratings) != len(rows) or set(ratings) != {(r["query_id"], r["document_id"]) for r in pairs}:
        raise ValueError("Missing, duplicate or unexpected relevance pairs.")
    pending, ids = 0, set()
    for p in pairs:
        row = ratings[(p["query_id"], p["document_id"])]
        for key in RELEVANCE_FIELDS[:9]:
            expected = str(p.get(key, "") or "")
            if row[key] not in {expected, spreadsheet_cell(expected)}:
                raise ValueError("Reviewers must not change relevance input: " + key)
        for key in ("grade", "support_quote", "notes", "rater_id"):
            row[key] = row[key].strip()
        if not row["grade"] or not row["notes"] or not row["rater_id"]:
            pending += 1
            continue
        if row["grade"] not in {"0", "1", "2", "UNKNOWN"}:
            raise ValueError("Invalid relevance grade.")
        if row["grade"] == "2" and not row["support_quote"]:
            raise ValueError("Direct relevance requires a source quote and rationale.")
        if row["support_quote"] and row["support_quote"] not in p["document_text"]:
            raise ValueError("Relevance support quote is not in the source summary.")
        ids.add(row["rater_id"])
    if pending:
        raise ReviewPending(f"{Path(path).name}: {pending} cặp chưa chấm; chưa có relevance gold.")
    if len(ids) != 1:
        raise ValueError("Each relevance sheet needs one declared reviewer ID.")
    return ratings, next(iter(ids))


def reviews(path):
    path = Path(path)
    pairs, queries, docs = workspace(path)
    a, ia = read_ratings(path / "annotator_a.csv", pairs)
    b, ib = read_ratings(path / "annotator_b.csv", pairs)
    if ia == ib:
        raise ValueError("Two different declared reviewers are required.")
    return pairs, queries, docs, a, b, [ia, ib]


def adjudicate(path):
    path = Path(path)
    pairs, _, _, a, b, _ = reviews(path)
    output = path / "adjudication.csv"
    if output.exists():
        raise ValueError("Adjudication already exists; do not overwrite reviews.")
    differences = [p for p in pairs if a[(p["query_id"], p["document_id"])]["grade"] != b[(p["query_id"], p["document_id"])]["grade"]]
    fields = RELEVANCE_FIELDS + ["grade_a", "grade_b", "notes_a", "notes_b"]
    sheet(output, [{**p, "grade_a": a[(p["query_id"], p["document_id"])]["grade"],
                   "grade_b": b[(p["query_id"], p["document_id"])]["grade"],
                   "notes_a": a[(p["query_id"], p["document_id"])]["notes"],
                   "notes_b": b[(p["query_id"], p["document_id"])]["notes"]} for p in differences], fields)
    return {"disagreements": len(differences), "path": str(output)}


def finalize(path, out):
    path, out = Path(path), Path(out)
    if out.exists():
        raise ValueError("Frozen relevance output already exists.")
    pairs, queries, docs, a, b, raters = reviews(path)
    differences = [p for p in pairs if a[(p["query_id"], p["document_id"])]["grade"] != b[(p["query_id"], p["document_id"])]["grade"]]
    resolved, third = {}, None
    if differences:
        if not (path / "adjudication.csv").is_file():
            raise ReviewPending("Relevance disagreements need a third adjudicator.")
        resolved, third = read_ratings(path / "adjudication.csv", differences)
        if third in raters:
            raise ValueError("Relevance adjudicator must differ from both initial reviewers.")
    rows = []
    for p in pairs:
        key = p["query_id"], p["document_id"]
        decision = resolved.get(key, a[key])
        rows.append({"query_id": key[0], "document_id": key[1],
                     "grade": None if decision["grade"] == "UNKNOWN" else int(decision["grade"]),
                     "support_quote": decision["support_quote"], "rationale": decision["notes"]})
    observed = (len(pairs) - len(differences)) / len(pairs)
    ca, cb = Counter(r["grade"] for r in a.values()), Counter(r["grade"] for r in b.values())
    chance = sum(ca[g] * cb[g] for g in {"0", "1", "2", "UNKNOWN"}) / len(pairs)**2
    out.mkdir(parents=True)
    write_json(out / "judgments.json", rows)
    write_json(out / "queries.json", queries)
    write_json(out / "manifest.json", {"version": "retrieval-gold-1.0", "status": "reviewed_frozen",
        "rater_ids": raters, "adjudicator_id": third, "identity_verification": "Declared IDs only; no authentication of human identity or independence.",
        "input_manifest_sha256": sha(path / "manifest.json"), "corpus_sha256": sha(path / "corpus.jsonl"),
        "document_ids": [d["id"] for d in docs], "pairs": len(rows), "queries": len(queries),
        "raw_agreement": observed, "cohen_kappa_unweighted": (observed - chance) / (1 - chance) if chance < 1 else None,
        "review_sha256": {p.name: sha(p) for p in (path / "annotator_a.csv", path / "annotator_b.csv", path / "adjudication.csv") if p.exists()},
        "files": {name: sha(out / name) for name in ("judgments.json", "queries.json")}})
    return {"status": "reviewed_frozen", "pairs": len(rows), "unknown_pairs": sum(r["grade"] is None for r in rows)}


def score(gold, predictions, split):
    gold = Path(gold)
    manifest = json.loads((gold / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "reviewed_frozen" or len(set(manifest.get("rater_ids", []))) < 2:
        raise ValueError("Retrieval scores require frozen independent review, not AI/unfinished labels.")
    if set(manifest["files"]) != {"judgments.json", "queries.json"}:
        raise ValueError("Unexpected frozen relevance files.")
    for name, expected in manifest["files"].items():
        if sha(gold / name) != expected:
            raise ValueError("Frozen relevance judgments changed.")
    rows = json.loads((gold / "judgments.json").read_text(encoding="utf-8"))
    queries = [q for q in json.loads((gold / "queries.json").read_text(encoding="utf-8")) if q["split"] == split]
    expected = {(q["id"], d) for q in queries for d in manifest["document_ids"]}
    chosen = [r for r in rows if r["query_id"] in {q["id"] for q in queries}]
    if len(chosen) != len(expected) or {(r["query_id"], r["document_id"]) for r in chosen} != expected:
        raise ValueError("Incomplete frozen relevance matrix.")
    if set(predictions) != {q["id"] for q in queries}:
        raise ValueError("Predictions must cover exactly the frozen split; no cherry-picking.")
    results, unresolved = [], []
    for q in queries:
        grades = {r["document_id"]: r["grade"] for r in chosen if r["query_id"] == q["id"]}
        returned = predictions[q["id"]]
        if (not isinstance(returned, list) or len(returned) > 3 or any(not isinstance(d, str) for d in returned)
                or len(set(returned)) != len(returned) or not set(returned) <= set(grades)):
            raise ValueError("Invalid or duplicate top-3 document IDs.")
        if any(g is None for g in grades.values()):
            unresolved.append(q["id"])
            continue
        if any(type(g) is not int or g not in (0, 1, 2) for g in grades.values()):
            raise ValueError("Invalid frozen relevance grade.")
        relevant = {d for d, g in grades.items() if g == 2}
        hits = len(set(returned) & relevant)
        gains = [grades[d] for d in returned]
        dcg = sum((2**g - 1) / math.log2(i + 2) for i, g in enumerate(gains))
        ideal = sum((2**g - 1) / math.log2(i + 2) for i, g in enumerate(sorted(grades.values(), reverse=True)[:3]))
        results.append({"id": q["id"], "has_direct_source": bool(relevant), "returned": len(returned), "hits": hits,
            "hit_at_3": int(hits > 0) if relevant else None, "precision_at_3": hits / 3,
            "precision_returned": hits / len(returned) if returned else None,
            "recall_at_3": hits / len(relevant) if relevant else None,
            "mrr_at_3": next((1 / (i + 1) for i, d in enumerate(returned) if d in relevant), 0) if relevant else None,
            "ndcg_at_3": dcg / ideal if ideal else None,
            "no_match_rejection": int(not returned) if not relevant else None})
    metric_names = ("hit_at_3", "precision_at_3", "precision_returned", "recall_at_3", "mrr_at_3", "ndcg_at_3", "no_match_rejection")
    metrics = {}
    for name in metric_names:
        values = [r[name] for r in results if r[name] is not None]
        metrics[name] = {"value": sum(values) / len(values) if values else None, "n": len(values)}
    return {"status": "scored", "split": split, "queries": len(queries), "scored_queries": len(results),
            "unknown_judgment_queries": unresolved, "metrics": metrics, "rows": results,
            "limitations": "Human IDs are declarations. Complete queries with UNKNOWN judgments are excluded and reported; source relevance is not phishing accuracy. NDCG uses graded relevance, strict hit/precision/recall use grade 2."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "adjudicate", "finalize", "score"))
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--predictions", type=Path)
    parser.add_argument("--split", choices=("dev", "test"), default="test")
    args = parser.parse_args()
    try:
        if args.action == "status":
            pairs, _, _, _, _, _ = reviews(args.workspace)
            result = {"status": "reviews_complete", "pairs": len(pairs)}
        elif args.action == "adjudicate":
            result = adjudicate(args.workspace)
        elif args.action == "finalize":
            if args.out is None:
                raise ValueError("--out is required to freeze judgments.")
            result = finalize(args.workspace, args.out)
        else:
            if args.predictions is None:
                raise ValueError("--predictions is required; JSON mapping query IDs to selected top-3 document ID lists.")
            result = score(args.workspace, json.loads(args.predictions.read_text(encoding="utf-8")), args.split)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(2, f"Relevance review stopped: {exc}\n")


if __name__ == "__main__":
    main()
