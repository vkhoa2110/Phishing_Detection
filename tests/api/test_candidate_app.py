"""Offline HTTP/workflow checks; provider fixtures do not measure model quality."""
from dataclasses import replace
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.candidate import create_app
import app.api.candidate as candidate_module
from app.core.settings import Settings
from tests.api.test_baseline import FakeML, api_response, completion
from tests.rag.test_rag import source


def test_candidate_url_model_is_explicit_and_never_changes_the_normal_app(tmp_path, monkeypatch):
    char, xgb = FakeML(), FakeML()
    monkeypatch.setattr(candidate_module, "CharURLService", lambda: char)
    monkeypatch.setattr(candidate_module, "ModelService", lambda settings: xgb)
    monkeypatch.delenv("PHISHLENS_CANDIDATE_URL_MODEL", raising=False)
    settings = replace(Settings(), root=tmp_path)
    assert create_app(settings).state.ml.model is char
    monkeypatch.setenv("PHISHLENS_CANDIDATE_URL_MODEL", "xgboost")
    assert create_app(settings).state.ml.model is xgb
    monkeypatch.setenv("PHISHLENS_CANDIDATE_URL_MODEL", "unknown")
    with pytest.raises(ValueError, match="PHISHLENS_CANDIDATE_URL_MODEL"):
        create_app(settings)


class OrderedRAG:
    def __init__(self, events, status="ok", broken=False):
        self.events, self.result_status, self.broken = events, status, broken
        self.seen = []

    def status(self):
        return {"ready": True, "documents": 1, "chunks": 1}

    def search(self, text, mode="text"):
        self.events.append("retrieval")
        self.seen.append((text, mode))
        if self.broken:
            raise RuntimeError("Do not expose this internal failure or credentials")
        return {"status": self.result_status, "sources": [source()] if self.result_status == "ok" else [],
                "reason": "Offline fixture"}


def classified(risk="HIGH"):
    return {**completion(risk=risk), "context_kind": "scam_request" if risk == "HIGH" else "routine",
            "evidence": completion()["evidence"] if risk == "HIGH" else []}


def explained(**changes):
    return {
        "support": [{"document_id": "VN-RAG-001", "source_quote": source()["text"],
                     "input_quote": "gửi mã OTP", "claim": "Đối chiếu yêu cầu gửi mã với hướng dẫn bảo vệ OTP.",
                     "relation": "mechanism_match", "scope_note": "Không xác minh danh tính người gửi."}],
        "actions": [{"text": "Tự xác minh bằng kênh liên hệ đã biết.", "supporting_document_ids": ["VN-RAG-001"]}],
        **changes,
    }


def candidate(tmp_path, handler, rag):
    return create_app(replace(Settings(), root=tmp_path, api_key="unit-only-secret", max_tokens=40_000),
                      transport=httpx.MockTransport(handler), model_service=FakeML(), rag_service=rag)


def test_candidate_classifies_before_retrieval_and_keeps_private_approved_input_and_usage_separate(tmp_path):
    events, requests = [], []
    rag = OrderedRAG(events)

    def provider(request):
        payload = json.loads(request.content)
        requests.append(payload)
        data = json.loads(payload["messages"][1]["content"])
        assert payload["max_tokens"] == 8192
        assert "khoa@example.org" not in json.dumps(payload)
        assert "0912345678" not in json.dumps(payload)
        if len(requests) == 1:
            events.append("classification")
            assert "reference_documents" not in data
            assert data["url_results"] == []  # Original URL removed from approved text.
            return httpx.Response(200, json=api_response(classified()))
        events.append("explanation")
        assert data["classification_locked"] is True
        assert data["approved_text"] == rag.seen[0][0]
        assert data["frozen_message_verdict"] == classified()
        body = api_response(explained())
        body["usage"] = {"prompt_tokens": 30, "completion_tokens": 60, "total_tokens": 90}
        return httpx.Response(200, json=body)

    with TestClient(candidate(tmp_path, provider, rag)) as client:
        response = client.post("/api/analyze", json={
            "text": "Hãy gửi mã OTP. https://example.org Liên hệ 0912345678",
            "llm_text": "Hãy gửi mã OTP. Liên hệ khoa@example.org.",
            "consent": True, "use_rag": True, "include_ml": True,
        })
        assert response.status_code == 200
        result = response.json()
        assert events == ["classification", "retrieval", "explanation"]
        assert result["final"]["risk_level"] == "HIGH"
        assert result["llm"]["verdict"] == classified() and result["llm"]["rag"] is False
        assert result["llm"]["usage"]["total_tokens"] == 60
        assert result["post_explanation"]["usage"]["total_tokens"] == 90
        assert result["post_explanation"]["status"] == "ok"
        assert result["post_explanation"]["validation"]["semantic_support_verified"] is False
        assert result["post_explanation"]["validation"]["classification_changed"] is False
        execution = result["execution"]
        assert execution["candidate"] == "v5-candidate" and execution["experimental"] is True
        assert execution["version"] == "analysis-pipeline-5.0-candidate"
        assert execution["llm"]["prompt_profile"] == execution["llm"]["requested_profile"] == "message-v5"
        assert execution["retrieval"]["included_in_successful_llm_call"] is False
        assert execution["retrieval"]["included_in_successful_explanation_call"] is True
        assert execution["explanation"]["stage"] == "post_classification"
        assert result["timing"]["explanation_ms"] >= 0
        assert "raw_content" not in json.dumps(result) and "unit-only-secret" not in json.dumps(result)
        status = client.get("/api/status").json()
        assert status["analysis_policy"]["message_prompt_profile"] == "message-v5"
        assert status["analysis_policy"]["rag_stage"] == "post_classification"
        assert status["analysis_policy"]["candidate"] == "v5-candidate"
        assert "unit-only-secret" not in json.dumps(status)
        assert client.get("/").headers["cache-control"] == "no-store"


@pytest.mark.parametrize("failure,code", [
    ("http", "HTTP_503"), ("quote", "SOURCE_NOT_GROUNDED"),
    ("reclassify", "OUTPUT_INVALID"), ("truncated", "OUTPUT_TRUNCATED"),
])
def test_failed_explanation_cannot_replace_successful_classifier_or_clear_url_alarm(tmp_path, failure, code):
    events, calls = [], []

    def provider(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json=api_response(classified("LOW")))
        if failure == "http":
            return httpx.Response(503)
        answer = explained()
        if failure == "quote":
            answer["support"][0]["source_quote"] = "Một nguồn bị bịa đặt không có trong tài liệu."
        elif failure == "reclassify":
            answer["risk_level"] = "HIGH"
        body = api_response(answer)
        if failure == "truncated":
            body["choices"][0]["finish_reason"] = "length"
        return httpx.Response(200, json=body)

    with TestClient(candidate(tmp_path, provider, OrderedRAG(events))) as client:
        result = client.post("/api/analyze", json={"text": "Thông báo gửi mã OTP trên https://example.org",
                                                   "consent": True, "use_rag": True}).json()
        assert result["llm"]["verdict"] == classified("LOW")
        assert result["final"]["risk_level"] == "LOW" and result["final"]["requires_review"] is True
        assert result["assessments"]["url"]["risk_level"] == "HIGH"
        assert result["post_explanation"]["status"] == "error"
        assert result["post_explanation"]["code"] == code
        assert result["post_explanation"]["explanation"] == {"support": [], "actions": []}
        assert result["execution"]["retrieval"]["included_in_successful_explanation_call"] is False


@pytest.mark.parametrize("status,broken", [("empty", False), ("unavailable", False), ("ok", True)])
def test_empty_or_broken_retrieval_preserves_classifier_without_another_provider_call(tmp_path, status, broken):
    events, calls = [], []

    def provider(request):
        calls.append(request)
        return httpx.Response(200, json=api_response(classified()))

    with TestClient(candidate(tmp_path, provider, OrderedRAG(events, status, broken))) as client:
        result = client.post("/api/analyze", json={"text": "Hãy gửi mã OTP", "consent": True, "use_rag": True}).json()
        assert len(calls) == 1 and events == ["retrieval"]
        assert result["final"]["risk_level"] == "HIGH"
        assert result["post_explanation"]["status"] == "no_support"
        assert result["execution"]["explanation"]["attempted"] is False
        assert "internal failure" not in json.dumps(result)


def test_consent_opt_in_and_classifier_failure_boundaries_are_inherited(tmp_path):
    events, calls = [], []
    rag = OrderedRAG(events)

    def provider(request):
        calls.append(request)
        return httpx.Response(500)

    with TestClient(candidate(tmp_path, provider, rag)) as client:
        assert client.post("/api/analyze", json={"text": "Hãy gửi mã OTP", "use_rag": True}).status_code == 422
        assert not calls and not rag.seen
        result = client.post("/api/analyze", json={"text": "Hãy gửi mã OTP", "consent": True, "use_rag": True}).json()
        assert len(calls) == 1 and not rag.seen
        assert result["llm"]["status"] == "error" and result["final"]["risk_level"] == "UNKNOWN"
        assert result["post_explanation"]["status"] == "disabled"
        assert result["execution"]["requested"]["rag"] is True
        assert result["execution"]["retrieval"]["attempted"] is False
        assert result["execution"]["llm"]["requested_profile"] == "message-v5"
        blocked = client.post("/api/analyze", headers={"origin": "https://foreign.example"},
                              json={"text": "Hãy gửi mã OTP", "consent": True})
        assert blocked.status_code == 403 and len(calls) == 1


def test_rag_stays_opt_in_and_url_mode_does_not_use_message_explanations(tmp_path):
    events, calls = [], []

    def provider(request):
        calls.append(request)
        return httpx.Response(200, json=api_response(classified()))

    with TestClient(candidate(tmp_path, provider, OrderedRAG(events))) as client:
        result = client.post("/api/analyze", json={"text": "Hãy gửi mã OTP", "consent": True}).json()
        assert result["post_explanation"]["status"] == "disabled" and not events
        result = client.post("/api/analyze", json={"text": "https://example.org", "mode": "url",
                                                   "consent": True, "use_rag": True}).json()
        assert len(calls) == 2 and not events
        assert result["post_explanation"]["status"] == "disabled"
        assert result["execution"]["llm"]["requested_profile"] == "legacy"
        assert result["assessments"]["message"]["status"] == "not_applicable"
        result = client.post("/api/analyze", json={"text": "Hãy gửi mã OTP", "use_llm": False, "use_rag": True}).json()
        assert len(calls) == 2 and not events
        assert result["post_explanation"]["status"] == "disabled"
