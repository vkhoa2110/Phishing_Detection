"""Saved-rank audits must fail closed and never fill unseen ranks or labels."""
from copy import deepcopy
import json

import pytest

from evaluation.rag.filter_trace import _locked_path_hash, audit, sha, trace_rankings


def example():
    documents = [{"id": f"D{i}", "text": f"source {i}", "source_url": f"https://example.org/{i}"} for i in range(1, 5)]
    queries = [{"id": "positive", "text": "parcel", "split": "dev"}, {"id": "no_match", "text": "other", "split": "dev"}]
    judgments = [{"query_id": q["id"], "document_id": d["id"], "grade": 2 if q["id"] == "positive" and d["id"] == "D2" else 0,
                  "source_quote": d["text"] if q["id"] == "positive" and d["id"] == "D2" else ""}
                 for q in queries for d in documents]
    rankings = [{"id": "positive", "relevant_ids": ["D2"], "ranked": [
        {"document_id": "D1", "score": .86}, {"document_id": "D2", "score": .845857}, {"document_id": "D3", "score": .84}]},
        {"id": "no_match", "relevant_ids": [], "ranked": [
            {"document_id": "D1", "score": .2}, {"document_id": "D2", "score": .1}, {"document_id": "D3", "score": 0.}]}]
    observed = [{"query_id": "positive", "direct_ids": ["D2"], "retrieved_ids": ["D1"], "hit": False, "no_match_rejected": False},
                {"query_id": "no_match", "direct_ids": [], "retrieved_ids": [], "hit": False, "no_match_rejected": True}]
    return queries, documents, judgments, rankings, observed


def trace(data):
    return trace_rankings(*data, min_score=.849416)


def test_trace_explains_lost_hit_without_inventing_unseen_scores():
    summary, queries, candidates, grid = trace(example())
    assert summary["raw_hit_queries"] == 1 and summary["filtered_hit_queries"] == 0
    assert summary["lost_hit_queries"] == ["positive"]
    rejected = summary["direct_candidates_rejected"][0]
    assert rejected["raw_rank"] == 2 and rejected["saved_score"] == .845857
    assert rejected["decision"] == "rejected_below_frozen_threshold"
    assert rejected["semantic_source_filter_applied"] is False
    assert len(candidates) == 6 and len(grid) == 8
    unobserved = [row for row in grid if row["document_id"] == "D4"]
    assert all(row["raw_rank"] is row["saved_score"] is row["filtered_rank"] is None for row in unobserved)
    assert all(row["decision"] == "outside_saved_top_k_pool_score_unobserved" for row in unobserved)


@pytest.mark.parametrize("score, retained", [(.84941549, False), (.8494156, True), (.849416, True), (.8494164, True)])
def test_threshold_matches_runtime_six_decimal_inclusive_boundary(score, retained):
    data = example()
    data[3][0]["ranked"][1]["score"] = score
    if retained:
        data[4][0].update(retrieved_ids=["D1", "D2"], hit=True)
    _, _, candidates, _ = trace(data)
    row = next(r for r in candidates if r["query_id"] == "positive" and r["document_id"] == "D2")
    assert row["threshold_passed"] is retained


def test_unknown_reference_is_not_no_match_or_known_false_source():
    data = example()
    for row in data[2]:
        if row["query_id"] == "no_match" and row["document_id"] == "D1":
            row["grade"] = "UNKNOWN"
    data[3][1]["ranked"][0]["score"] = .9
    data[4][1]["retrieved_ids"] = ["D1"]
    # Old flags are not authoritative when unresolved relevance exists.
    summary, queries, _, _ = trace(data)
    assert summary["unresolved_queries"] == 1 and summary["no_direct_match_queries"] == 0
    assert summary["filtered_no_match_rejection"] is None
    assert summary["filtered_returned_unknown"] == 1
    assert summary["filtered_precision_returned_known"] == 0
    assert queries[1]["reference_status"] == "unresolved_relevance"


@pytest.mark.parametrize("mutation, match", [
    (lambda d: d[0].append(deepcopy(d[0][0])), "Duplicate query"),
    (lambda d: d[2].pop(), "complete query"),
    (lambda d: d[2].append(deepcopy(d[2][0])), "Duplicate relevance"),
    (lambda d: d[3].pop(), "Query inventory"),
    (lambda d: d[3][0]["ranked"].pop(), "incomplete"),
    (lambda d: d[3][0]["ranked"][1].update(document_id="D1"), "Duplicate/unknown ranked"),
    (lambda d: d[3][0]["ranked"][1].update(document_id="unknown"), "Duplicate/unknown ranked"),
    (lambda d: d[3][0]["ranked"][1].update(score=float("nan")), "finite and descending"),
    (lambda d: d[3][0]["ranked"][1].update(score=.95), "finite and descending"),
    (lambda d: d[3][0].update(relevant_ids=[]), "relevant IDs"),
    (lambda d: d[4][0].update(retrieved_ids=["D2"]), "cannot reproduce"),
    (lambda d: d[4][0].update(hit=True), "Saved hit"),
    (lambda d: d[2][1].update(source_quote="absent quote"), "exact source quote"),
    (lambda d: d[2][0].update(grade=True), "Invalid relevance"),
])
def test_changed_or_incomplete_inventories_fail_closed(mutation, match):
    data = example()
    mutation(data)
    with pytest.raises(ValueError, match=match):
        trace(data)


def test_registration_hash_prevents_silently_reusing_changed_calibration(tmp_path):
    path = tmp_path / "calibration.json"
    path.write_text('{"min_score":0.8}')
    config = {"input_files_sha256": {str(path): sha(path)}}
    _locked_path_hash(config, path, "input_files_sha256", root=tmp_path)
    path.write_text('{"min_score":0.9}')
    with pytest.raises(ValueError, match="Frozen input changed"):
        _locked_path_hash(config, path, "input_files_sha256", root=tmp_path)


def frozen_fixture(root):
    """A tiny complete sealed study, independent of ignored local artifacts."""
    from hashlib import sha256
    study, index = root / "study", root / "index"
    q, docs, judgments, rankings, observed = example()
    for doc in docs:
        doc.update(publisher="Fixture", content_kind="editorial_summary_not_verbatim",
                   summary_sha256=sha256(doc["text"].encode()).hexdigest())
    def write(path, value, jsonl=False):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(row) + "\n" for row in value) if jsonl else json.dumps(value))
        return path
    queries = write(study / "relevance_inputs/queries.jsonl", q, True)
    corpus = write(root / "corpus.jsonl", docs, True)
    reviewed = write(study / "relevance_inputs/corpus.jsonl", docs, True)
    pairs = [{"query_id": query["id"], "document_id": d["id"], "query": query["text"], "document_text": d["text"]} for query in q for d in docs]
    write(study / "relevance_inputs/pairs.jsonl", pairs, True)
    write(study / "relevance_inputs/rubric.json", {"2": "direct"})
    write(study / "relevance_inputs/manifest.json", {"files": {name: sha(study / "relevance_inputs" / name) for name in ("queries.jsonl", "corpus.jsonl", "pairs.jsonl", "rubric.json")}})
    refs = write(study / "assistant_relevance/judgments.jsonl", judgments, True)
    write(study / "assistant_relevance/manifest.json", {"human_reviewed": False, "status": "assistant_ai_relevance_not_gold",
        "queries": 2, "documents": 4, "pairs": 8, "query_file_sha256": sha(queries), "corpus_file_sha256": sha(reviewed), "judgments_sha256": sha(refs)})
    write(study / "assistant_relevance/query_results.json", observed)
    write(study / "assistant_relevance/baseline_comparison.json", {"rankings": {"e5": rankings}, "summary": {"e5": {"hit_queries": 1, "positive_queries": 1, "returned": 6, "correct": 1}}})
    write(study / "assistant_relevance/retrieval_metrics.json", {"hit_queries": 0, "relevant_queries": 1, "returned": 1, "returned_direct": 0, "hit_at_3": 0.})
    prepared = write(study / "classification_inputs/prepared.json", {"positive": {"sources": [{"document_id": "D1", "text": "source 1"}]}, "no_match": {"sources": []}})
    chunks = write(index / "chunks.jsonl", [{"chunk_id": d["id"] + "-01", "document_id": d["id"], "text": d["text"], "source_url": d["source_url"]} for d in docs], True)
    embeddings = index / "embeddings.npy"; embeddings.write_bytes(b"opaque frozen matrix; not loaded by trace")
    manifest = write(index / "manifest.json", {"corpus_sha256": sha(corpus), "chunks": 4, "documents": 4,
        "files": {"chunks.jsonl": sha(chunks), "embeddings.npy": sha(embeddings)}, "version": "fixture", "model_id": "fixture", "revision": "fixture"})
    calibration = write(index / "calibration.json", {"min_score": .849416, "top_k": 3, "index_manifest_sha256": sha(manifest)})
    sources = [write(root / name, {"test": "frozen source fixture"}) for name in ("app/services/rag/retrieval.py", "evaluation/messages/fresh_ablation.py")]
    write(study / "classification/execution.json", {"metadata": {"index": "index", "corpus": "corpus.jsonl"},
        "input_files_sha256": {str(p): sha(p) for p in [manifest, calibration, chunks, embeddings, corpus, prepared]},
        "source_files_sha256": {str(p.relative_to(root)): sha(p) for p in sources}})
    return study


def test_full_audit_writes_provenance_and_refuses_overwrite(tmp_path):
    study, out = frozen_fixture(tmp_path), tmp_path / "trace"
    summary = audit(study, out, root=tmp_path)
    assert summary["provider_calls"] == summary["embedding_inference_calls"] == summary["new_labels"] == 0
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["no_provider_or_embedding_execution"] is True
    for name, expected in manifest["outputs_sha256"].items():
        assert sha(out / name) == expected
    assert len((out / "reference_grid.jsonl").read_text().splitlines()) == 8
    with pytest.raises(ValueError, match="fresh output"):
        audit(study, out, root=tmp_path)


def test_audit_blocks_changed_inputs_before_writing_outputs(tmp_path):
    study, out = frozen_fixture(tmp_path), tmp_path / "trace"
    with (study / "relevance_inputs/queries.jsonl").open("a") as stream:
        stream.write('{"id":"new"}\n')
    with pytest.raises(ValueError, match="Frozen input changed"):
        audit(study, out, root=tmp_path)
    assert not out.exists()
