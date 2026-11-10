"""Optional extractive RAG workflow; fixtures are not quality evaluation."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.api.test_baseline import api_response
from tests.api.test_candidate_app import OrderedRAG, candidate, classified


@pytest.mark.parametrize("truncated", [False, True])
def test_opt_in_span_mode_keeps_verdict_redaction_and_failure_boundary(tmp_path, monkeypatch, truncated):
    monkeypatch.setenv("PHISHLENS_CANDIDATE_RAG_MODE", "span_selection")
    events, requests = [], []
    rag = OrderedRAG(events)
    def provider(request):
        body = json.loads(request.content)
        requests.append(body)
        data = json.loads(body["messages"][1]["content"])
        if len(requests) == 1:
            assert "reference_documents" not in data
            return httpx.Response(200, json=api_response(classified()))
        assert data["classification_locked"] is True
        assert data["frozen_message_verdict"] == classified()
        assert "khoa@example.org" not in json.dumps(data)
        assert "input_spans" in data and "catalog_sha256" in data
        selection = {"selections": [{"source_span_id": data["reference_documents"][0]["spans"][0]["id"],
                                     "input_span_id": data["input_spans"][0]["id"], "relation": "mechanism_match"}]}
        result = api_response(selection)
        if truncated:
            result["choices"][0].update(finish_reason="length", message={"content": None})
        return httpx.Response(200, json=result)
    with TestClient(candidate(tmp_path, provider, rag)) as client:
        status = client.get("/api/status").json()["analysis_policy"]
        assert status["explanation_mode"] == "span_selection"
        assert status["explanation_profile"] == "rag-evidence-selection-v3"
        result = client.post("/api/analyze", json={"text": "Hãy gửi mã OTP.",
            "llm_text": "Hãy gửi mã OTP. Liên hệ khoa@example.org.", "consent": True, "use_rag": True}).json()
        assert result["llm"]["verdict"] == classified()
        assert result["final"]["risk_level"] == "HIGH"
        explanation = result["post_explanation"]
        assert explanation["validation"]["classification_changed"] is False
        assert explanation["validation"]["semantic_support_verified"] is False
        assert explanation["explanation"]["actions"] == []
        if truncated:
            assert explanation["code"] == "OUTPUT_TRUNCATED" and explanation["status"] == "error"
        else:
            assert explanation["status"] == "ok"
            assert explanation["validation"]["selection_only"] is True
            assert explanation["explanation"]["support"][0]["source_span_id"].startswith("VN-RAG-001:S")
        assert len(requests) == 2 and "raw_content" not in json.dumps(result)
        assert "unit-only-secret" not in json.dumps(result)


def test_mode_is_explicit_per_app_and_invalid_configuration_fails(tmp_path, monkeypatch):
    rag = OrderedRAG([])
    def unused(request):
        raise AssertionError("Status must not call provider")
    monkeypatch.setenv("PHISHLENS_CANDIDATE_RAG_MODE", "span_selection")
    first = candidate(tmp_path, unused, rag)
    monkeypatch.delenv("PHISHLENS_CANDIDATE_RAG_MODE")
    second = candidate(tmp_path, unused, rag)
    with TestClient(first) as client_a, TestClient(second) as client_b:
        assert client_a.get("/api/status").json()["analysis_policy"]["explanation_mode"] == "span_selection"
        assert client_b.get("/api/status").json()["analysis_policy"]["explanation_mode"] == "free_text"
    monkeypatch.setenv("PHISHLENS_CANDIDATE_RAG_MODE", "invalid")
    with pytest.raises(ValueError, match="PHISHLENS_CANDIDATE_RAG_MODE"):
        candidate(tmp_path, unused, rag)
