"""Offline contract tests; no downloads, model weights, or paid LLM calls required."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.llm_service import LLMFailure, approved_ml_metadata, parse_verdict
from app.main import create_app
from app.rag_service import (DIMENSION, RAGService, RetrievalIndex, build_index, rank_chunks,
                             read_jsonl, sha_file, write_json)
from app.settings import Settings
from evaluation.retrieval import metrics, select_threshold


def source():
    return {"document_id": "VN-RAG-001", "chunk_id": "VN-RAG-001-01", "text": "Không cung cấp mã OTP cho người tự nhận là nhân viên hỗ trợ.",
            "title": "Nguồn minh họa", "publisher": "Fixture", "source_url": "https://example.org/guidance",
            "published_at": None, "context_note": "Dùng để giải thích thủ đoạn.", "score": .9}


def verdict():
    return {"risk_level": "HIGH", "summary": "Yêu cầu gửi mã xác thực.",
            "evidence": [{"quote": "gửi mã OTP", "reason": "Yêu cầu thông tin xác thực."}],
            "recommended_actions": ["Tự xác minh qua kênh đã biết."],
            "knowledge_support": [{"document_id": "VN-RAG-001", "source_quote": source()["text"],
                                   "claim": "Không cung cấp OTP cho người liên hệ."}]}


def test_rag_citations_must_match_retrieved_document_and_source_substring():
    v, warnings = parse_verdict(json.dumps(verdict()), "Hãy gửi mã OTP", [source()])
    assert len(v.knowledge_support) == 1 and warnings
    for key, value in [("document_id", "VN-RAG-999"), ("source_quote", "Một đoạn nguồn hoàn toàn bịa đặt.")]:
        data = verdict();data["knowledge_support"][0][key] = value
        parsed, warnings = parse_verdict(json.dumps(data), "Hãy gửi mã OTP", [source()])
        assert parsed.knowledge_support == [] and warnings


def test_knowledge_cannot_supply_missing_input_evidence_or_add_arbitrary_links():
    data = verdict();data["evidence"][0]["quote"] = source()["text"]
    v, _ = parse_verdict(json.dumps(data), "Chào bạn", [source()])
    assert v.risk_level == "UNKNOWN" and v.evidence == []
    data = verdict();data["knowledge_support"][0]["url"] = "https://evil.test"
    with pytest.raises(LLMFailure):
        parse_verdict(json.dumps(data), "Hãy gửi mã OTP", [source()])
    with pytest.raises(LLMFailure):
        parse_verdict(json.dumps(verdict()), "Hãy gửi mã OTP")


def test_url_deleted_from_preview_cannot_reappear_through_metadata():
    urls = [{"id": "URL-01", "url": "https://example.org/?token=secret123", "status": "ok", "score": .9,
             "risk_level": "HIGH", "warning_threshold": .2, "high_threshold": .8}]
    assert approved_ml_metadata("Chỉ gửi câu này", urls) == []
    out = approved_ml_metadata("https://example.org/?token=REDACTED", urls)
    assert len(out) == 1 and "secret123" not in json.dumps(out)
    with pytest.raises(LLMFailure, match="5 URL"):
        approved_ml_metadata(" ".join(f'https://site{i}.example/' for i in range(6)), urls)


def test_rank_deduplicates_documents_filters_threshold_and_uses_multiple_windows():
    vectors = np.zeros((3, DIMENSION), dtype=np.float32)
    vectors[0, 0] = vectors[1, 0] = vectors[2, 1] = 1
    queries = vectors[[0, 2]]
    chunks = [{"chunk_id": "a", "document_id": "d1"}, {"chunk_id": "b", "document_id": "d1"},
              {"chunk_id": "c", "document_id": "d2"}]
    assert [d["document_id"] for d in rank_chunks(chunks, vectors, queries, 3, .9)] == ["d1", "d2"]
    assert rank_chunks(chunks, vectors, -queries, 3, .9) == []


class FakeEncoder:
    def split(self, text):
        return [text]

    def encode(self, texts, prefix):
        assert prefix == "passage: "
        vectors = np.zeros((len(texts), DIMENSION), dtype=np.float32)
        vectors[:, 0] = 1
        return vectors


def build_fixture(tmp_path):
    text = source()["text"]
    doc = {"id": "VN-RAG-001", "text": text, "summary_sha256": hashlib.sha256(text.encode()).hexdigest(),
           "content_kind": "editorial_summary_not_verbatim", "kind": "scam_warning",
           **{k: source()[k] for k in ("title", "publisher", "source_url", "published_at", "context_note")}}
    corpus = tmp_path / "documents.jsonl";corpus.write_text(json.dumps(doc))
    directory = tmp_path / "index"
    build_index(corpus, directory, FakeEncoder())
    return directory, corpus


def test_index_detects_modified_corpus_and_index_files_and_refuses_overwrite(tmp_path):
    directory, corpus = build_fixture(tmp_path)
    assert RetrievalIndex.load(directory, corpus).vectors.shape == (1, DIMENSION)
    with pytest.raises(ValueError, match="already"):
        build_index(corpus, directory, FakeEncoder())
    original = corpus.read_bytes();corpus.write_bytes(original + b"\n")
    with pytest.raises(ValueError, match="Corpus changed"):
        RetrievalIndex.load(directory, corpus)
    corpus.write_bytes(original)
    (directory / "embeddings.npy").write_bytes(b"invalid")
    with pytest.raises(ValueError, match="hash"):
        RetrievalIndex.load(directory, corpus)


def test_unavailable_or_uncalibrated_index_is_explicit_and_url_mode_skips_encoder(tmp_path):
    cfg = replace(Settings(), root=tmp_path, api_key="")
    service = RAGService(cfg)
    assert service.status()["ready"] is False
    assert service.search("Xin chào")["status"] == "unavailable"
    assert service.search("https://example.org", "url")["status"] == "empty"
    assert service.encoder is None
    directory, corpus = build_fixture(tmp_path)
    cfg = replace(cfg, rag_index_dir="index", rag_corpus="documents.jsonl")
    assert RAGService(cfg).status()["ready"] is False  # no guessed threshold
    write_json(directory / "calibration.json", {"min_score": .8, "top_k": 3, "index_manifest_sha256": "wrong"})
    assert RAGService(cfg).status()["ready"] is False


class FakeRAG:
    def __init__(self, status="ok"):
        self.seen = []
        self.result_status = status

    def status(self):
        return {"ready": True, "documents": 25, "chunks": 25}

    def search(self, text, mode):
        self.seen.append((text, mode))
        return {"status": self.result_status, "sources": [source()] if self.result_status == "ok" else [], "reason": "Fixture"}


def test_rag_api_uses_only_confirmed_redacted_text_and_separate_sources(tmp_path):
    requests, rag = [], FakeRAG()
    def handler(request):
        payload = json.loads(request.content);requests.append(payload)
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(verdict())}, "finish_reason": "stop"}]})
    cfg = replace(Settings(), root=tmp_path, api_key="")
    with TestClient(create_app(cfg, httpx.MockTransport(handler), rag_service=rag)) as c:
        assert c.post('/api/analyze', json={"text": "gửi mã OTP", "use_rag": True}).status_code == 422
        assert rag.seen == [] and requests == []
        response = c.post('/api/analyze', json={"text": "Nội dung cũ https://private.example/?token=SECRET", "llm_text": "Hãy gửi mã OTP tới demo@example.org",
                         "consent": True, "use_rag": True, "api_key": "fixture-key"})
        assert response.status_code == 200
        result = response.json();payload = requests[0];data = json.loads(payload['messages'][1]['content'])
        assert "private.example" not in json.dumps(payload) and "demo@" not in json.dumps(payload)
        assert rag.seen[0][0] == data["text"]
        assert "reference_documents" in data and "score" not in data["reference_documents"][0]
        assert result['llm']['rag'] and result['llm']['prompt_version'] == 'message-rag-2.0'
        assert result['retrieval']['sources'][0]['source_url'] == source()['source_url']


@pytest.mark.parametrize("status", ["empty", "unavailable"])
def test_empty_or_failed_retrieval_falls_back_without_fabricated_citations(tmp_path, status):
    rag = FakeRAG(status)
    def handler(request):
        data = json.loads(request.content)
        assert "reference_documents" not in json.loads(data['messages'][1]['content'])
        v = verdict();v.pop('knowledge_support')
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(v)}}]})
    with TestClient(create_app(replace(Settings(), root=tmp_path, api_key=""), httpx.MockTransport(handler), rag_service=rag)) as c:
        r = c.post('/api/analyze', json={"text": "Hãy gửi mã OTP", "use_rag": True, "consent": True, "api_key": "fixture"}).json()
        assert r['retrieval']['status'] == status and r['llm']['rag'] is False
        assert r['llm']['prompt_version'] == 'message-2.0'


def test_rag_disabled_or_llm_disabled_never_loads_the_retriever(tmp_path):
    rag = FakeRAG()
    def handler(request):
        data = json.loads(request.content)
        assert "reference_documents" not in json.loads(data['messages'][1]['content'])
        v = verdict();v.pop('knowledge_support')
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(v)}}]})
    with TestClient(create_app(replace(Settings(), root=tmp_path, api_key=""), httpx.MockTransport(handler), rag_service=rag)) as c:
        for use_llm, use_rag in [(False, True), (True, False)]:
            r = c.post('/api/analyze', json={"text": "Hãy gửi mã OTP", "use_llm": use_llm, "use_rag": use_rag,
                                           "consent": True, "api_key": "fixture"}).json()
            assert r['retrieval']['status'] == 'disabled'
        assert rag.seen == []


@pytest.mark.parametrize("envelope", [[], {"choices": None}, {"choices": [None]}, {"data": []}])
def test_malformed_provider_envelope_returns_component_error_instead_of_500(tmp_path, envelope):
    with TestClient(create_app(replace(Settings(), root=tmp_path, api_key=""),
                              httpx.MockTransport(lambda request: httpx.Response(200, json=envelope)))) as c:
        r = c.post('/api/analyze', json={"text": "Xin chào", "consent": True, "api_key": "fixture"})
        assert r.status_code == 200 and r.json()['llm']['code'] == 'RESPONSE_INVALID'


def test_calibration_rewards_no_match_rejection_and_persists_abstentions():
    rows = [{"id": "1", "relevant_ids": ["d1"], "ranked": [{"document_id": "d1", "score": .9}], "elapsed_ms": 1},
            {"id": "2", "relevant_ids": [], "ranked": [{"document_id": "d1", "score": .7}], "elapsed_ms": 1}]
    threshold, m = select_threshold(rows)
    assert threshold == .9 and m['hit_at_3'] == 1 and m['false_retrievals_no_match'] == 0
    assert metrics(rows, 0)['false_retrievals_no_match'] == 1


def test_retrieval_dev_and_test_are_disjoint_and_not_phishing_ground_truth():
    root = Path(__file__).resolve().parents[1]
    rows = sum([read_jsonl(root / f'data/evaluation/rag_retrieval_{split}_v1.jsonl') for split in ['dev', 'test']], [])
    assert len(rows) == len({r['id'] for r in rows}) == len({r['text'] for r in rows}) == 52
    assert all('label' not in r and r['annotation'].startswith('assistant_authored') for r in rows)
