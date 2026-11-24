from dataclasses import replace
import json

import httpx
from fastapi.testclient import TestClient

from app.api.focused import create_app
from app.core.settings import Settings
from tests.api.test_baseline import FakeML
from tests.api.test_candidate_app import OrderedRAG


def decision(level="HIGH"):
    if level == "UNKNOWN":
        return {"risk_level": level, "context_kind": "insufficient", "reason_code": "missing_context",
                "quotes": [], "missing_context": ["secret_destination"]}
    return {"risk_level": level, "context_kind": "scam_request", "reason_code": "secret_request",
            "quotes": ["gửi mã OTP"], "missing_context": []}


def packet(answer, *, finish="stop", tokens=24):
    return httpx.Response(200, json={"model": "fixture", "usage": {"total_tokens": tokens},
        "choices": [{"finish_reason": finish, "message": {"content": json.dumps(answer), "reasoning_content": "private-thought"}}]})


def app(tmp_path, provider, rag=None):
    return create_app(replace(Settings(), root=tmp_path, api_key="offline-fixture", max_tokens=40960),
                      transport=httpx.MockTransport(provider), model_service=FakeML(), rag_service=rag or OrderedRAG([]))


def test_clarification_needs_new_consent_and_never_restores_private_original_urls(tmp_path):
    calls = []
    def provider(request):
        payload = json.loads(request.content); calls.append(payload)
        assert payload["max_tokens"] == 2048 and payload["thinking"] == {"type": "disabled"}
        assert "private.example" not in json.dumps(payload)
        return packet(decision("UNKNOWN"))
    with TestClient(app(tmp_path, provider)) as client:
        base = {"text": "Bản gốc https://private.example/?token=secret", "llm_text": "Hỗ trợ xác minh mã.",
                "include_ml": True}
        assert client.post("/api/analyze", json=base).status_code == 422
        assert not calls
        result = client.post("/api/analyze", json={**base, "consent": True}).json()
        assert result["clarification"]["questions"][0]["code"] == "secret_destination"
        assert result["execution"]["llm"]["semantic_uncertainty"] is True
        assert result["llm"]["telemetry"]["reasoning_characters"] == len("private-thought")
        assert "private-thought" not in json.dumps(result)
        invalid = {"text": result["llm"]["input_used"], "answers": [{"code": "secret_destination", "value": "<script>"}]}
        assert client.post("/api/clarify/preview", json=invalid).status_code == 400
        preview = client.post("/api/clarify/preview", json={**invalid,
            "answers": [{"code": "secret_destination", "value": "third_party"}]}).json()
        assert preview["requires_confirmation"] and preview["provider_calls"] == 0
        assert "private.example" not in preview["text"]
        assert "chưa xác minh độc lập" in preview["text"]
        assert client.post("/api/analyze", json={"text": preview["text"], "consent": False}).status_code == 422
        assert len(calls) == 1


def test_optional_rag_failure_keeps_core_decision_and_usage_separate(tmp_path):
    calls, events = [], []
    def provider(request):
        calls.append(json.loads(request.content))
        return packet(decision()) if len(calls) == 1 else packet({}, finish="length", tokens=48)
    with TestClient(app(tmp_path, provider, OrderedRAG(events))) as client:
        result = client.post("/api/analyze", json={"text": "Hãy gửi mã OTP", "consent": True, "use_rag": True}).json()
        assert len(calls) == 2 and events == ["retrieval"]
        assert result["final"]["risk_level"] == "HIGH"
        assert result["llm"]["status"] == "ok" and result["post_explanation"]["status"] == "error"
        assert result["llm"]["usage"]["total_tokens"] == 24
        assert result["post_explanation"]["usage"]["total_tokens"] == 48
        assert result["execution"]["explanation"]["classification_changed"] is False
        assert result["execution"]["llm"]["requested_profile"] == "message-core-1.1"


def test_technical_failure_has_no_semantic_questions_and_keeps_url_alarm(tmp_path):
    def provider(request): return packet({}, finish="length")
    with TestClient(app(tmp_path, provider)) as client:
        result = client.post("/api/analyze", json={"text": "Hãy gửi mã OTP https://example.org", "consent": True}).json()
        assert result["llm"]["code"] == "OUTPUT_TRUNCATED"
        assert result["llm"]["usage"]["total_tokens"] == 24
        assert result["assessments"]["url"]["risk_level"] == "HIGH"
        assert not result["clarification"]["questions"]
        assert result["execution"]["llm"]["semantic_uncertainty"] is False


def test_status_declares_the_actual_profile_and_bounded_budget(tmp_path):
    with TestClient(app(tmp_path, lambda request: packet(decision()))) as client:
        result = client.get("/api/status").json()
        assert result["analysis_policy"]["message_prompt_profile"] == "message-core-1.1"
        assert result["runtime_manifest"]["max_tokens"] == 2048
        assert result["runtime_manifest"]["thinking_requested"] == "disabled"
        assert result["analysis_policy"]["interaction_required"] is False
        assert result["analysis_policy"]["explanation_mode"] == "span_selection"
