"""Workflow boundaries and degraded execution, using offline provider fixtures."""
from dataclasses import replace
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.services.analysis import PIPELINE_VERSION
from app.api.legacy import create_app
from app.core.settings import Settings
from tests.api.test_baseline import FakeML, api_response, completion
from tests.rag.test_rag import FakeRAG


def app(tmp_path, handler, rag=None, ml=None):
    return create_app(replace(Settings(), root=tmp_path, api_key="fixture"),
                      httpx.MockTransport(handler), model_service=ml or FakeML(), rag_service=rag or FakeRAG())


def test_invalid_approved_text_is_rejected_before_any_component_runs(tmp_path):
    class NoML(FakeML):
        def predict(self, urls):
            pytest.fail("Invalid request must be rejected before running the model")
    def provider(request):
        pytest.fail("Invalid request must not call the provider")
    rag = FakeRAG()
    with TestClient(app(tmp_path, provider, rag, NoML())) as client:
        response = client.post("/api/analyze", json={"text": "https://example.org", "consent": True,
                                                     "llm_text": "   ", "use_rag": True})
        assert response.status_code == 422
        response = client.post("/api/analyze", json={"text": "https://example.org", "consent": True,
            "llm_text": " ".join(f"https://site{i}.example" for i in range(6)), "use_rag": True})
        assert response.status_code == 422
        assert not rag.seen


def test_requested_rag_unavailable_does_not_claim_rag_was_used(tmp_path):
    def provider(request):
        data = json.loads(request.content)
        assert "reference_documents" not in json.loads(data["messages"][1]["content"])
        return httpx.Response(200, json=api_response({**completion(), "context_kind": "scam_request"}))
    with TestClient(app(tmp_path, provider, FakeRAG("unavailable"))) as client:
        result = client.post("/api/analyze", json={"text": "Hãy gửi mã OTP", "consent": True,
                                                   "use_rag": True, "include_ml": True}).json()
        execution = result["execution"]
        assert execution["version"] == PIPELINE_VERSION
        assert execution["requested"] == {"llm": True, "rag": True, "url_context": True}
        assert execution["retrieval"]["attempted"] is True
        assert execution["retrieval"]["status"] == "unavailable"
        assert execution["retrieval"]["included_in_successful_llm_call"] is False
        assert execution["llm"]["included_url_context"] is False
        assert result["final"]["risk_level"] == "HIGH"
        assert result["llm"]["validation"]["semantic_support_verified"] is False
        assert all(result["timing"][key] >= 0 for key in ("ml_ms", "rag_ms", "llm_ms", "total_ms"))


def test_disabled_llm_and_url_mode_do_not_start_retrieval(tmp_path):
    rag, calls = FakeRAG(), []
    def provider(request):
        calls.append(request)
        return httpx.Response(200, json=api_response(completion(quote="https://example.org")))
    with TestClient(app(tmp_path, provider, rag)) as client:
        result = client.post("/api/analyze", json={"text": "https://example.org", "use_llm": False,
                                                   "use_rag": True}).json()
        assert not calls and not rag.seen
        assert result["execution"]["requested"]["rag"] is True
        assert result["execution"]["retrieval"]["attempted"] is False
        assert result["final"]["risk_level"] == "UNKNOWN"
        result = client.post("/api/analyze", json={"text": "https://example.org", "mode": "url",
                                                   "consent": True, "use_rag": True}).json()
        assert len(calls) == 1 and not rag.seen
        assert result["execution"]["retrieval"]["attempted"] is False
        assert result["assessments"]["message"]["status"] == "not_applicable"
        assert result["llm"]["prompt_profile"] == "legacy"


def test_v3_rejects_whitespace_evidence_and_retains_independent_url_alarm(tmp_path):
    bad = {**completion(quote=" "), "context_kind": "scam_request"}
    bad["recommended_actions"] = ["Nhập OTP vào đường dẫn."]
    with TestClient(app(tmp_path, lambda request: httpx.Response(200, json=api_response(bad)))) as client:
        result = client.post("/api/analyze", json={"text": "Thông báo https://example.org", "consent": True}).json()
        assert result["final"]["risk_level"] == "UNKNOWN"
        assert result["assessments"]["url"]["risk_level"] == "HIGH"
        assert result["final"]["requires_review"]
        assert result["llm"]["validation"]["status"] == "abstained"
        assert "EVIDENCE_BLANK" in result["llm"]["validation"]["reason_codes"]
        assert "Nhập OTP vào đường dẫn." not in result["llm"]["verdict"]["recommended_actions"]
        policy = client.get("/api/status").json()["analysis_policy"]
        assert policy["pipeline_version"] == PIPELINE_VERSION
        assert policy["message_prompt_profile"] == "message-v3"


def test_retrieved_sources_are_reported_as_unused_when_llm_fails(tmp_path):
    with TestClient(app(tmp_path, lambda request: httpx.Response(500))) as client:
        result = client.post("/api/analyze", json={"text": "https://example.org yêu cầu gửi mã OTP",
                                                   "consent": True, "use_rag": True}).json()
        assert result["execution"]["retrieval"]["source_count"] == 1
        assert result["execution"]["retrieval"]["included_in_successful_llm_call"] is False
        assert result["execution"]["llm"]["status"] == "error"
        assert result["execution"]["llm"]["requested_profile"] == "message-v3"
        assert result["final"]["risk_level"] == "UNKNOWN"
        assert result["assessments"]["url"]["risk_level"] == "HIGH"
