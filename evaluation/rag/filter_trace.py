"""Trace frozen week-4 E5 filtering from saved ranks, without inference.

Only the saved top-3 pool has scores. The complete relevance grid is retained,
but unranked documents never receive invented ranks, scores, or rejection causes.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from urllib.parse import urlsplit

from app.core.settings import ROOT

SCHEMA = "saved-e5-filter-trace-1.0"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def _unique(rows, field, description):
    result = {row[field]: row for row in rows}
    if len(result) != len(rows):
        raise ValueError("Duplicate " + description)
    return result


def _digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _check_hash(path, expected):
    if sha(path) != expected:
        raise ValueError("Frozen input changed: " + str(path))


def _locked_path_hash(config, path, section, *, root):
    """Resolve registration paths without relying on the original host prefix."""
    path = Path(path).resolve()
    matches = []
    for name, expected in config[section].items():
        registered = Path(name)
        resolved = registered if registered.is_absolute() else root / registered
        if resolved.resolve() == path:
            matches.append(expected)
    if len(matches) != 1:
        raise ValueError("Missing/ambiguous registration binding: " + str(path))
    _check_hash(path, matches[0])


def trace_rankings(queries, documents, judgments, rankings, observed, *, min_score, top_k=3):
    """Pure, strict trace over a complete reference grid and saved E5 pool."""
    if type(top_k) is not int or top_k < 1 or type(min_score) not in (int, float) or not math.isfinite(min_score) or not 0 <= min_score <= 1:
        raise ValueError("Invalid frozen threshold/top_k.")
    qmap = _unique(queries, "id", "query")
    dmap = _unique(documents, "id", "document")
    ranks = _unique(rankings, "id", "ranked query")
    actual = _unique(observed, "query_id", "observed query")
    if set(qmap) != set(ranks) or set(qmap) != set(actual):
        raise ValueError("Query inventory differs across ranks, references, or outputs.")
    grades = {}
    for row in judgments:
        pair = row["query_id"], row["document_id"]
        if pair in grades:
            raise ValueError("Duplicate relevance pair.")
        grade = row["grade"]
        if not (type(grade) is int and grade in (0, 1, 2) or grade == "UNKNOWN"):
            raise ValueError("Invalid relevance grade.")
        if grade == 2 and (not isinstance(row.get("source_quote"), str) or not row["source_quote"].strip()
                           or row["document_id"] not in dmap or row["source_quote"] not in dmap[row["document_id"]]["text"]):
            raise ValueError("Direct relevance requires an exact source quote.")
        grades[pair] = grade
    if set(grades) != {(qid, did) for qid in qmap for did in dmap}:
        raise ValueError("Relevance must cover the complete query × document grid.")
    candidate_rows, query_rows, grid = [], [], []
    counts = Counter(queries=len(qmap), relevant_queries=0, unresolved_queries=0,
                     no_direct_match_queries=0, raw_hit_queries=0, filtered_hit_queries=0,
                     raw_returned=0, filtered_returned=0, raw_returned_direct=0,
                     filtered_returned_direct=0, raw_returned_unknown=0,
                     filtered_returned_unknown=0, raw_no_match_rejected=0,
                     filtered_no_match_rejected=0)
    for qid, query in qmap.items():
        direct = {did for did in dmap if grades[qid, did] == 2}
        unknown = {did for did in dmap if grades[qid, did] == "UNKNOWN"}
        ranked = ranks[qid]["ranked"]
        if set(ranks[qid]["relevant_ids"]) != direct or len(ranks[qid]["relevant_ids"]) != len(direct):
            raise ValueError("Saved raw relevant IDs disagree with full-grid reference.")
        if len(ranked) != min(top_k, len(dmap)):
            raise ValueError("Saved raw top-k candidate pool is incomplete.")
        ids = [row["document_id"] for row in ranked]
        if len(ids) != len(set(ids)) or not set(ids) <= set(dmap):
            raise ValueError("Duplicate/unknown ranked document.")
        previous = math.inf
        selected = []
        by_doc = {}
        for position, item in enumerate(ranked, 1):
            score = item["score"]
            if type(score) not in (int, float) or not math.isfinite(score) or not -1 <= score <= 1 or score > previous:
                raise ValueError("Saved cosine scores must be finite and descending.")
            previous = score
            did = item["document_id"]
            passed = round(score, 6) >= min_score
            if passed:
                selected.append(did)
            entry = {"query_id": qid, "document_id": did, "raw_rank": position,
                     "saved_score": score, "score_used_for_filter": round(score, 6),
                     "min_score": min_score, "threshold_passed": passed,
                     "source_policy": "member_of_hash_verified_frozen_corpus",
                     "semantic_source_filter_applied": False,
                     "decision": "retained" if passed else "rejected_below_frozen_threshold",
                     "filtered_rank": len(selected) if passed else None,
                     "relevance_grade": grades[qid, did],
                     "source_url": dmap[did]["source_url"],
                     "source_summary_sha256": _digest(dmap[did]["text"])}
            candidate_rows.append(entry)
            by_doc[did] = entry
        saved = actual[qid]
        if saved["retrieved_ids"] != selected or set(saved["direct_ids"]) != direct or len(saved["direct_ids"]) != len(direct):
            raise ValueError("Frozen filtering cannot reproduce the saved output: " + qid)
        raw_hit, filtered_hit = bool(direct & set(ids)), bool(direct & set(selected))
        # A query with UNKNOWN grades but no known direct source is unresolved,
        # never silently treated as a known no-match query.
        status = "known_direct_source" if direct else "unresolved_relevance" if unknown else "no_known_direct_source"
        if saved["hit"] is not filtered_hit:
            raise ValueError("Saved hit disagrees with retrieved IDs/reference.")
        if not unknown and saved["no_match_rejected"] is not (not direct and not selected):
            raise ValueError("Saved no-match rejection disagrees with reference.")
        counts["relevant_queries"] += bool(direct)
        counts["unresolved_queries"] += bool(unknown and not direct)
        counts["no_direct_match_queries"] += bool(not direct and not unknown)
        counts["raw_hit_queries"] += raw_hit
        counts["filtered_hit_queries"] += filtered_hit
        counts["raw_returned"] += len(ids)
        counts["filtered_returned"] += len(selected)
        counts["raw_returned_direct"] += len(direct & set(ids))
        counts["filtered_returned_direct"] += len(direct & set(selected))
        counts["raw_returned_unknown"] += len(unknown & set(ids))
        counts["filtered_returned_unknown"] += len(unknown & set(selected))
        if not direct and not unknown:
            counts["raw_no_match_rejected"] += not ids
            counts["filtered_no_match_rejected"] += not selected
        query_rows.append({"query_id": qid, "dataset": query.get("dataset"), "split": query.get("split"),
                           "query_sha256": _digest(query["text"]), "reference_status": status,
                           "direct_ids": sorted(direct), "unknown_grade_ids": sorted(unknown),
                           "raw_ids": ids, "filtered_ids": selected,
                           "raw_hit": raw_hit, "filtered_hit": filtered_hit,
                           "direct_source_lost_after_threshold": raw_hit and not filtered_hit})
        for did in dmap:
            item = by_doc.get(did)
            grid.append({"query_id": qid, "document_id": did, "relevance_grade": grades[qid, did],
                         "raw_rank": item["raw_rank"] if item else None,
                         "saved_score": item["saved_score"] if item else None,
                         "filtered_rank": item["filtered_rank"] if item else None,
                         "decision": item["decision"] if item else "outside_saved_top_k_pool_score_unobserved"})
    summary = dict(counts)
    for arm in ("raw", "filtered"):
        summary[arm + "_hit_at_3"] = counts[arm + "_hit_queries"] / counts["relevant_queries"] if counts["relevant_queries"] else None
        summary[arm + "_no_match_rejection"] = counts[arm + "_no_match_rejected"] / counts["no_direct_match_queries"] if counts["no_direct_match_queries"] else None
        known_returned = counts[arm + "_returned"] - counts[arm + "_returned_unknown"]
        summary[arm + "_precision_returned_known"] = counts[arm + "_returned_direct"] / known_returned if known_returned else None
    summary["lost_hit_queries"] = [row["query_id"] for row in query_rows if row["direct_source_lost_after_threshold"]]
    summary["direct_candidates_rejected"] = [row for row in candidate_rows if row["relevance_grade"] == 2 and not row["threshold_passed"]]
    return summary, query_rows, candidate_rows, grid


def audit(study, out, *, root=ROOT):
    study, out, root = Path(study).resolve(), Path(out).resolve(), Path(root).resolve()
    if out.exists():
        raise ValueError("Choose a fresh output directory; old audits are immutable.")
    inputs, reference = study / "relevance_inputs", study / "assistant_relevance"
    execution = _json(study / "classification/execution.json")
    index = root / execution["metadata"]["index"]
    corpus = root / execution["metadata"]["corpus"]
    prepared_path = study / "classification_inputs/prepared.json"
    source_paths = [root / "app/services/rag/retrieval.py", root / "evaluation/messages/fresh_ablation.py"]
    for path in [index / "manifest.json", index / "calibration.json", index / "chunks.jsonl", index / "embeddings.npy", corpus, prepared_path]:
        _locked_path_hash(execution, path, "input_files_sha256", root=root)
    for path in source_paths:
        _locked_path_hash(execution, path, "source_files_sha256", root=root)
    for name, expected in _json(inputs / "manifest.json")["files"].items():
        if name not in {"queries.jsonl", "corpus.jsonl", "pairs.jsonl", "rubric.json"}:
            raise ValueError("Unexpected relevance manifest file.")
        _check_hash(inputs / name, expected)
    if set(_json(inputs / "manifest.json")["files"]) != {"queries.jsonl", "corpus.jsonl", "pairs.jsonl", "rubric.json"}:
        raise ValueError("Incomplete relevance input manifest.")
    ref_manifest = _json(reference / "manifest.json")
    for file, key in ((inputs / "queries.jsonl", "query_file_sha256"),
                      (inputs / "corpus.jsonl", "corpus_file_sha256"),
                      (reference / "judgments.jsonl", "judgments_sha256")):
        _check_hash(file, ref_manifest[key])
    if ref_manifest.get("human_reviewed") is not False or ref_manifest.get("status") != "assistant_ai_relevance_not_gold":
        raise ValueError("This trace is scoped to the explicitly provisional assistant reference.")
    index_manifest, calibration = _json(index / "manifest.json"), _json(index / "calibration.json")
    if calibration["index_manifest_sha256"] != sha(index / "manifest.json") or index_manifest["corpus_sha256"] != sha(corpus) or sha(inputs / "corpus.jsonl") != sha(corpus):
        raise ValueError("Corpus, index, calibration, and reviewed source version differ.")
    if type(calibration["top_k"]) is not int or calibration["top_k"] != 3:
        raise ValueError("Only the saved top-3 retrieval contract is supported.")
    for name in ("chunks.jsonl", "embeddings.npy"):
        _check_hash(index / name, index_manifest["files"][name])
    queries, documents = _jsonl(inputs / "queries.jsonl"), _jsonl(inputs / "corpus.jsonl")
    judgments, chunks = _jsonl(reference / "judgments.jsonl"), _jsonl(index / "chunks.jsonl")
    dmap = _unique(documents, "id", "document")
    if any(q.get("split") != "dev" for q in queries):
        raise ValueError("Only frozen development queries are in scope.")
    if any(ref_manifest.get(key) != count for key, count in (("queries", len(queries)), ("documents", len(documents)), ("pairs", len(judgments)))):
        raise ValueError("Reference inventory differs from frozen manifest.")
    if len(chunks) != index_manifest["chunks"] or len(dmap) != index_manifest["documents"] or {c["document_id"] for c in chunks} != set(dmap):
        raise ValueError("Index/corpus document inventory differs.")
    _unique(chunks, "chunk_id", "chunk")
    for doc in documents:
        parsed = urlsplit(doc["source_url"])
        if (doc["summary_sha256"] != _digest(doc["text"]) or doc.get("content_kind") != "editorial_summary_not_verbatim"
                or parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password):
            raise ValueError("Invalid frozen source summary/provenance.")
    for chunk in chunks:
        doc = dmap[chunk["document_id"]]
        if chunk["text"] not in doc["text"] or chunk["source_url"] != doc["source_url"]:
            raise ValueError("Chunk is not supported by its frozen source.")
    pairs = _jsonl(inputs / "pairs.jsonl")
    pair_keys = [(p["query_id"], p["document_id"]) for p in pairs]
    qmap = _unique(queries, "id", "query")
    if len(pair_keys) != len(set(pair_keys)) or set(pair_keys) != {(qid, did) for qid in qmap for did in dmap}:
        raise ValueError("Input relevance pair grid differs.")
    for pair in pairs:
        if pair["query"] != qmap[pair["query_id"]]["text"] or pair["document_text"] != dmap[pair["document_id"]]["text"]:
            raise ValueError("Pair text differs from locked query/source.")
    prepared = _json(prepared_path)
    observed, baseline = _json(reference / "query_results.json"), _json(reference / "baseline_comparison.json")
    for row in observed:
        selected = prepared[row["query_id"]]["sources"]
        if row["retrieved_ids"] != [s["document_id"] for s in selected]:
            raise ValueError("Observed retrieval disagrees with classification sources.")
        for source in selected:
            if source["text"] != dmap[source["document_id"]]["text"]:
                raise ValueError("Classification source text differs from reviewed corpus.")
    summary, query_rows, candidates, grid = trace_rankings(queries, documents, judgments,
        baseline["rankings"]["e5"], observed, min_score=calibration["min_score"], top_k=calibration["top_k"])
    original_metrics = _json(reference / "retrieval_metrics.json")
    for ours, theirs in (("filtered_hit_queries", "hit_queries"), ("relevant_queries", "relevant_queries"),
                        ("filtered_returned", "returned"), ("filtered_returned_direct", "returned_direct"),
                        ("filtered_hit_at_3", "hit_at_3")):
        if summary[ours] != original_metrics[theirs]:
            raise ValueError("Recomputed trace disagrees with saved retrieval metrics.")
    for ours, theirs in (("raw_hit_queries", "hit_queries"), ("relevant_queries", "positive_queries"),
                        ("raw_returned", "returned"), ("raw_returned_direct", "correct")):
        if summary[ours] != baseline["summary"]["e5"][theirs]:
            raise ValueError("Recomputed trace disagrees with raw E5 summary.")
    provenance = [{"document_id": d["id"], "source_url": d["source_url"], "publisher": d["publisher"],
                   "published_at": d.get("published_at"), "retrieved_at": d.get("retrieved_at"),
                   "review_status": d.get("review_status"), "content_kind": d["content_kind"],
                   "summary_sha256": d["summary_sha256"], "source_text_sha256": d.get("source_text_sha256"),
                   "original_source_reverified_by_this_audit": False} for d in documents]
    summary.update({"schema": SCHEMA, "provider_calls": 0, "embedding_inference_calls": 0,
                    "new_labels": 0, "reference_status": ref_manifest["status"], "human_gold": False,
                    "min_score": calibration["min_score"], "top_k": calibration["top_k"],
                    "source_policy": "hash_verified_frozen_corpus_and_document_deduplication; no semantic source filter",
                    "raw_pool_limit": "Only saved top-3 scores; ranks/scores below top-3 were not persisted.",
                    "index_version": index_manifest["version"], "embedding_model": index_manifest["model_id"],
                    "embedding_revision": index_manifest["revision"]})
    locked = [study / "classification/execution.json", prepared_path, inputs / "manifest.json", reference / "manifest.json",
              *[inputs / n for n in ("queries.jsonl", "corpus.jsonl", "pairs.jsonl", "rubric.json")],
              *[reference / n for n in ("judgments.jsonl", "query_results.json", "baseline_comparison.json", "retrieval_metrics.json")],
              corpus, *[index / n for n in ("manifest.json", "calibration.json", "chunks.jsonl", "embeddings.npy")], *source_paths]
    out.mkdir(parents=True)
    for name, value in (("summary.json", summary), ("queries.jsonl", query_rows),
                        ("candidate_trace.jsonl", candidates), ("reference_grid.jsonl", grid), ("source_provenance.jsonl", provenance)):
        payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n" if name.endswith(".json") else "".join(json.dumps(v, ensure_ascii=False) + "\n" for v in value)
        (out / name).write_text(payload, encoding="utf-8")
    for name, rows in (("candidate_trace.csv", candidates), ("reference_grid.csv", grid)):
        with (out / name).open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    lines = ["# Truy vết bộ lọc RAG tuần 4", "", "Replay offline từ thứ hạng đã lưu; không gọi LLM, không chạy embedding, không sửa corpus/ngưỡng/nhãn.", "",
             f"- {summary['queries']} truy vấn dev × {len(documents)} tài liệu = {len(grid)} cặp relevance AI; không phải gold do người chấm.",
             f"- Trước lọc: Hit@3 **{summary['raw_hit_queries']}/{summary['relevant_queries']}**; {summary['raw_returned_direct']}/{summary['raw_returned']} nguồn trả về được AI chấm hỗ trợ trực tiếp.",
             f"- Sau lọc: Hit@3 **{summary['filtered_hit_queries']}/{summary['relevant_queries']}**; {summary['filtered_returned_direct']}/{summary['filtered_returned']} nguồn hỗ trợ trực tiếp.",
             f"- Ngưỡng cố định **{calibration['min_score']}**, so sánh `round(score, 6) >= min_score`; giữ tối đa {calibration['top_k']} tài liệu khác nhau.",
             f"- Từ chối khi không có nguồn trực tiếp theo AI: **{summary['filtered_no_match_rejected']}/{summary['no_direct_match_queries']}**; {summary['unresolved_queries']} truy vấn chỉ có relevance chưa xác định được báo riêng.", "",
             "Nguồn phải thuộc corpus/index đã kiểm hash. Không có bộ lọc ngữ nghĩa theo độ liên quan, độ tin cậy người gửi, thương hiệu hay thời điểm sau truy xuất trong pipeline tuần 4.", "",
             "| Truy vấn mất nguồn trực tiếp đã nằm trong top 3 | Tài liệu | Hạng cũ | Score | Lý do loại |", "|---|---|---:|---:|---|"]
    for row in summary["direct_candidates_rejected"]:
        lines.append(f"| {row['query_id']} | {row['document_id']} | {row['raw_rank']} | {row['saved_score']:.6f} | Dưới ngưỡng {calibration['min_score']} |")
    lines += ["", "`candidate_trace.csv` giải thích quyết định của 36 ứng viên top 3 đã lưu (với lượt tuần 4). `reference_grid.csv` giữ toàn bộ cặp, kể cả tài liệu không được truy xuất và grade UNKNOWN.",
              "Tài liệu ngoài top 3 có rank/score để trống: không thể kết luận nó bị loại vì ngưỡng hay thiếu liên quan chỉ từ đầu ra này. Không khôi phục thứ hạng đầy đủ bằng một lượt embedding mới.", "",
              "Đây là chẩn đoán cùng dev bằng nhãn AI. Hit@3 không phải F1 phishing. Nguồn là tóm lược biên tập; kiểm hash chỉ xác minh đúng phiên bản, không xác nhận nội dung bài gốc còn đúng hoặc URL/người gửi an toàn. Không thay chính sách app từ kết quả này."]
    (out / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    manifest = {"schema": SCHEMA, "created_at": datetime.now(timezone.utc).isoformat(),
                "inputs_sha256": {str(p.relative_to(root)) if p.is_relative_to(root) else str(p): sha(p) for p in locked},
                "code_sha256": sha(__file__), "outputs_sha256": {p.name: sha(p) for p in out.iterdir() if p.is_file()},
                "no_provider_or_embedding_execution": True, "new_annotations": False,
                "source_policy_replayed": "existing rounded-score threshold; no new semantic/source gate",
                "original_sources_reverified": False, "full_rank_inventory_available": False}
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, default=ROOT / "artifacts/evaluations/week4_dev_20261111")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = audit(args.study, args.out)
    except (ValueError, KeyError, OSError, TypeError) as exc:
        parser.exit(2, f"Retrieval trace stopped: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
