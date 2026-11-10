"""Runtime/calibration parity and hash-bound source scope, without model downloads."""
import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pytest

from app.services.rag.retrieval import DIMENSION, MODEL_ID, MODEL_REVISION, RAGService, RetrievalIndex, SCOPE_METADATA_FIELDS, build_index, rank_chunks, sha_file, write_json
from evaluation.rag.metrics import metrics


@pytest.mark.parametrize("threshold", [.860278, .860279, .860280])
def test_runtime_threshold_matches_saved_evaluation_scores(threshold):
    values = [.8602788, .8602791, .8602781]
    vectors = np.zeros((len(values), DIMENSION), dtype=np.float32)
    for i, value in enumerate(values):
        vectors[i, 0] = value
        vectors[i, 1] = np.sqrt(1 - value * value)
    query = np.zeros((1, DIMENSION), dtype=np.float32)
    query[0, 0] = 1
    chunks = [{"document_id": f"VN-RAG-{i + 1:03}", "chunk_id": f"{i + 1:03}-01"}
              for i in range(len(values))]
    ranked = rank_chunks(chunks, vectors, query)
    runtime = rank_chunks(chunks, vectors, query, min_score=threshold)
    assert runtime == [item for item in ranked if item["score"] >= threshold]
    # The first two round to the same score; the higher raw cosine stays first.
    assert [item["document_id"] for item in ranked] == ["VN-RAG-002", "VN-RAG-001", "VN-RAG-003"]
    rows = [{"id": "boundary", "relevant_ids": ["VN-RAG-001"],
             "ranked": ranked, "elapsed_ms": 0}]
    runtime_hit = any(item["document_id"] == "VN-RAG-001" for item in runtime)
    assert metrics(rows, threshold)["hit_at_3"] == float(runtime_hit)
    if threshold == .860279:
        assert runtime_hit  # Previously rejected raw 0.8602788 at rounded threshold.


class FixtureEncoder:
    def split(self, text):
        if text.startswith("Nguồn minh họa 1:"):
            return [text[:20], text[20:]]
        return [text]

    def encode(self, texts, prefix):
        assert prefix == "passage: "
        vectors = np.zeros((len(texts), DIMENSION), dtype=np.float32)
        vectors[:, 0] = 1
        return vectors


def make_index(tmp_path):
    documents = []
    for number in range(1, 4):
        text = f"Nguồn minh họa {number}: tự xác minh thông tin qua kênh đã biết."
        documents.append({
            "id": f"VN-RAG-{number:03}", "text": text,
            "summary_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "content_kind": "editorial_summary_not_verbatim", "kind": "mixed_guidance",
            "title": f"Nguồn {number}", "publisher": "Đơn vị minh họa",
            "source_url": f"https://example.org/source-{number}",
            "published_at": "2026-06-18", "context_note": "Không xác minh người gửi.",
        })
    documents[0].update({
        "scenario": "electricity_service", "entity": "Đơn vị A",
        "document_role": "legitimate_workflow", "scope": "Vận hành thử tại khu vực A",
        "valid_from": "2026-06-15", "temporal_note": "Chưa xác nhận triển khai cuối cùng.",
    })
    documents[1].update({"entity": "Đơn vị B", "valid_from": None})
    corpus = tmp_path / "documents.jsonl"
    corpus.write_text("".join(json.dumps(doc, ensure_ascii=False) + "\n" for doc in documents), encoding="utf-8")
    directory = tmp_path / "index"
    build_index(corpus, directory, FixtureEncoder())
    return directory, corpus, documents


def test_scope_joins_matching_source_without_mutating_frozen_index(tmp_path):
    directory, corpus, documents = make_index(tmp_path)
    original_files = {path.name: sha_file(path) for path in directory.iterdir()}
    legacy = RetrievalIndex.load(directory, corpus)
    scoped = RetrievalIndex.load(directory, corpus, include_scope=True)
    assert all(not set(SCOPE_METADATA_FIELDS) & chunk.keys() for chunk in legacy.chunks)
    assert scoped.manifest == legacy.manifest
    np.testing.assert_array_equal(scoped.vectors, legacy.vectors)
    documents_by_id = {document["id"]: document for document in documents}
    assert len(scoped.chunks) == 4  # The first source has two chunks, not one row per source.
    for original, enriched in zip(legacy.chunks, scoped.chunks):
        document = documents_by_id[original["document_id"]]
        assert {key: enriched[key] for key in original} == original
        for key in SCOPE_METADATA_FIELDS:
            if key in document:
                assert enriched[key] == document[key]
            else:
                assert key not in enriched
    # An unknown validity date stays unknown despite a known publication date.
    assert scoped.chunks[2]["valid_from"] is None
    assert "valid_from" not in scoped.chunks[3]
    assert "document_role" not in scoped.chunks[3]
    assert {path.name: sha_file(path) for path in directory.iterdir()} == original_files


def test_scope_rejects_changed_corpus_metadata_before_joining(tmp_path):
    directory, corpus, _ = make_index(tmp_path)
    corpus.write_text(corpus.read_text(encoding="utf-8").replace("Đơn vị A", "Đơn vị khác"), encoding="utf-8")
    with pytest.raises(ValueError, match="Corpus changed"):
        RetrievalIndex.load(directory, corpus, include_scope=True)


def test_runtime_scope_is_explicitly_opted_in(tmp_path, monkeypatch):
    directory, corpus, _ = make_index(tmp_path)
    write_json(directory / "calibration.json", {
        "index_manifest_sha256": sha_file(directory / "manifest.json"), "min_score": .8, "top_k": 3,
    })
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    names = ("config.json", "model.safetensors", "tokenizer.json", "tokenizer_config.json")
    for name in names:
        (model_dir / name).write_text("Fixture; never loaded.", encoding="utf-8")
    write_json(model_dir / "phishlens_model.json", {
        "model_id": MODEL_ID, "revision": MODEL_REVISION,
        "files": {name: sha_file(model_dir / name) for name in names},
    })
    monkeypatch.setattr("app.services.rag.retrieval.importlib.util.find_spec", lambda name: object())
    settings = SimpleNamespace(root=tmp_path, rag_index_dir=directory.name,
                               rag_corpus=corpus.name, rag_model_dir=model_dir.name)
    ordinary = RAGService(settings)
    enabled = RAGService(settings, include_scope=True)
    assert "scope" not in ordinary.inspect()[0].chunks[0]
    assert enabled.inspect()[0].chunks[0]["scope"] == "Vận hành thử tại khu vực A"
    assert ordinary.encoder is enabled.encoder is None
