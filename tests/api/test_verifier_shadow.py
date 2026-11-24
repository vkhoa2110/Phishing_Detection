"""Offline contracts for optional verification; fixtures are not quality scores."""
import asyncio
from dataclasses import replace
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.runtime import create_app
from app.api.verifier_shadow import create_app as create_raw_shadow
from app.core.settings import Settings
from tests.api.test_baseline import FakeML, completion
from tests.api.test_candidate_app import OrderedRAG
from tests.api.test_focused_app import decision, packet


@pytest.fixture(autouse=True)
def fixed_candidate_settings(monkeypatch):
    monkeypatch.delenv("PHISHLENS_CORE_MAX_TOKENS", raising=False)
    monkeypatch.delenv("PHISHLENS_CORE_THINKING", raising=False)
    monkeypatch.delenv("PHISHLENS_FOCUSED_RETRIEVAL", raising=False)
    monkeypatch.delenv("PHISHLENS_CANDIDATE_RAG_MODE", raising=False)


def app(tmp_path, provider, *, profile="verifier-shadow", timeout=1, rag=None, raw=False):
    settings = replace(Settings(), root=tmp_path, api_key="shadow-server-only-key",
                       timeout_seconds=timeout, max_tokens=40960)
    kwargs = dict(transport=httpx.MockTransport(provider), model_service=FakeML(),
                  rag_service=rag or OrderedRAG([]))
    return create_raw_shadow(settings, **kwargs) if raw else create_app(profile, settings, **kwargs)


def core(level="HIGH"):
    if level == "LOW":
        return {"risk_level": "LOW", "context_kind": "routine", "reason_code": "no_fraud_evidence",
                "quotes": [], "missing_context": []}
    return decision(level)


def opinion(kind="ordinary_content"):
    return {"assessment": kind,
            "reason_code": {"ordinary_content": "routine_or_advertising",
                            "supported_alarm": "dangerous_request", "insufficient": "missing_context"}[kind],
            "quotes": [] if kind == "insufficient" else ["gửi mã OTP"]}


def payload(request):
    body = json.loads(request.content)
    return body, json.loads(body["messages"][1]["content"])


def assert_primary_and_url_preserved(result, level="HIGH"):
    assert result["llm"]["status"] == "ok"
    assert result["llm"]["verdict"]["risk_level"] == level
    assert result["llm"]["core_decision"] == core(level)
    assert result["final"]["risk_level"] == level
    assert result["urls"][0]["status"] == "ok"
    assert result["assessments"]["url"]["risk_level"] == "HIGH"
    assert result["verification"]["verdict_changed"] is False
    assert result["verification"]["applied"] is False


@pytest.mark.parametrize("level", ["HIGH", "WARNING"])
def test_valid_alarm_gets_blind_second_opinion_without_applying_low_revision(tmp_path, level):
    requests = []

    def provider(request):
        body, data = payload(request)
        requests.append(data)
        if len(requests) == 1:
            return packet(core(level), tokens=21)
        assert set(data) == {"text", "output_schema"}
        assert data["text"] == "Hãy gửi mã OTP https://example.org"
        assert set(data["output_schema"]["properties"]) == {"assessment", "reason_code", "quotes"}
        assert body["max_tokens"] == 1024 and body["thinking"] == {"type": "disabled"}
        assert "reference_documents" not in data and "url_results" not in data
        return packet(opinion(), tokens=13)

    with TestClient(app(tmp_path, provider)) as client:
        result = client.post("/api/analyze", json={"text": "Hãy gửi mã OTP https://example.org",
                                                  "consent": True, "include_ml": True}).json()
    assert len(requests) == 2
    assert_primary_and_url_preserved(result, level)
    verification = result["verification"]
    assert verification["status"] == "ok" and verification["attempted"] is True
    assert verification["suggested_level"] == "LOW" and verification["revision_status"] == "revised_low"
    assert verification["semantic_support_verified"] is False
    assert result["llm"]["usage"]["total_tokens"] == 21
    assert verification["usage"]["total_tokens"] == 13
    assert result["execution"]["runtime"]["calls_attempted"] == 2


@pytest.mark.parametrize("level", ["LOW", "UNKNOWN"])
def test_completed_non_alarm_never_calls_verifier(tmp_path, level):
    calls = []

    def provider(request):
        calls.append(request)
        return packet(core(level))

    with TestClient(app(tmp_path, provider)) as client:
        result = client.post("/api/analyze", json={"text": "Hãy gửi mã OTP", "consent": True}).json()
    assert len(calls) == 1
    assert result["verification"]["skip_reason"] == "not_completed_alarm"
    assert not result["verification"]["attempted"]
    assert result["llm"]["verdict"]["risk_level"] == level


@pytest.mark.parametrize("mode,use_llm,reason,expected_calls", [
    ("text", False, "llm_disabled", 0),
    ("url", False, "not_message_mode", 0),
    ("url", True, "not_message_mode", 1),
])
def test_disabled_and_url_modes_skip_shadow(tmp_path, mode, use_llm, reason, expected_calls):
    calls = []

    def provider(request):
        calls.append(request)
        return packet(completion())

    with TestClient(app(tmp_path, provider)) as client:
        result = client.post("/api/analyze", json={"text": "https://example.org", "mode": mode,
                                                  "use_llm": use_llm, "consent": use_llm}).json()
    assert len(calls) == expected_calls
    assert result["verification"]["skip_reason"] == reason
    assert not result["verification"]["attempted"]
    assert result["urls"][0]["status"] == "ok"


def test_failed_primary_has_no_verifier_and_keeps_url(tmp_path):
    calls = []

    def provider(request):
        calls.append(request)
        return packet({}, finish="length")

    with TestClient(app(tmp_path, provider)) as client:
        result = client.post("/api/analyze", json={"text": "Hãy gửi mã OTP https://example.org", "consent": True}).json()
    assert len(calls) == 1
    assert result["llm"]["code"] == "OUTPUT_TRUNCATED"
    assert result["verification"]["skip_reason"] == "classification_not_completed"
    assert result["assessments"]["url"]["risk_level"] == "HIGH"


@pytest.mark.parametrize("kind", ["supported_alarm", "insufficient"])
def test_support_and_semantic_insufficiency_are_distinct_non_applied_results(tmp_path, kind):
    calls = []

    def provider(request):
        calls.append(request)
        return packet(core()) if len(calls) == 1 else packet(opinion(kind))

    with TestClient(app(tmp_path, provider)) as client:
        result = client.post("/api/analyze", json={"text": "Hãy gửi mã OTP https://example.org", "consent": True}).json()
    assert_primary_and_url_preserved(result)
    verification = result["verification"]
    assert verification["status"] == "ok" and verification["revision_status"] == kind
    assert verification["suggested_level"] == "HIGH"
    assert verification["needs_review"] == (kind == "insufficient")


@pytest.mark.parametrize("failure,code", [
    ("length", "OUTPUT_TRUNCATED"), ("json", "OUTPUT_INVALID"),
    ("http", "HTTP_503"), ("connection", "CONNECTION_ERROR"),
    ("quote", "OUTPUT_INVALID"), ("missing_model", "RESPONSE_INVALID"),
    ("unfinished", "RESPONSE_INCOMPLETE"),
])
def test_verifier_failures_cannot_erase_primary_or_url(tmp_path, failure, code):
    calls = []

    def provider(request):
        calls.append(request)
        if len(calls) == 1:
            return packet(core())
        if failure == "http":
            return httpx.Response(503)
        if failure == "connection":
            raise httpx.ConnectError("private transport detail must not appear", request=request)
        if failure == "json":
            return httpx.Response(200, json={"model": "fixture", "choices": [{"finish_reason": "stop", "message": {"content": "not json"}}]})
        answer = opinion()
        if failure == "quote":
            answer["quotes"] = ["not present in approved text"]
        response = packet(answer, finish="length" if failure == "length" else "stop")
        if failure in {"missing_model", "unfinished"}:
            body = json.loads(response.content)
            if failure == "missing_model":
                body.pop("model")
            else:
                body["choices"][0]["finish_reason"] = "tool_calls"
            response = httpx.Response(200, json=body)
        return response

    with TestClient(app(tmp_path, provider)) as client:
        result = client.post("/api/analyze", json={"text": "Hãy gửi mã OTP https://example.org", "consent": True}).json()
    assert len(calls) == 2
    assert_primary_and_url_preserved(result)
    assert result["verification"]["status"] == "error" and result["verification"]["code"] == code
    assert result["verification"]["revision_status"] == "technical_error"
    assert result["verification"]["suggested_level"] == "HIGH" and result["verification"]["needs_review"]
    assert "private transport detail" not in json.dumps(result)


def test_second_opinion_uses_only_redacted_approved_text_after_original_url_removed(tmp_path):
    calls = []

    def provider(request):
        body, data = payload(request)
        calls.append(data)
        rendered = json.dumps(body, ensure_ascii=False)
        for private in ("original-private.example", "secret123", "0912345678", "khoa@example.org"):
            assert private not in rendered
        if len(calls) == 1:
            assert data["url_results"] == []
            return packet(core())
        assert set(data) == {"text", "output_schema"}
        assert "[EMAIL]" in data["text"]
        return packet(opinion())

    with TestClient(app(tmp_path, provider)) as client:
        response = client.post("/api/analyze", json={
            "text": "Hãy gửi mã OTP https://original-private.example/?token=secret123. 0912345678",
            "llm_text": "Hãy gửi mã OTP. Liên hệ khoa@example.org.",
            "consent": True, "include_ml": True,
        })
    result = response.json()
    assert response.status_code == 200 and len(calls) == 2
    assert calls[1]["text"] == result["llm"]["input_used"] == calls[0]["text"]
    assert result["urls"][0]["url"].startswith("https://original-private.example/")


def test_classification_explanation_verification_share_deadline(tmp_path):
    events, calls = [], []

    async def provider(request):
        _, data = payload(request)
        calls.append(data)
        await asyncio.sleep(.08)
        if len(calls) == 1:
            events.append("classification")
            return packet(core())
        if "classification_locked" in data:
            events.append("explanation")
            return packet({"selections": []})
        return packet(opinion())

    with TestClient(app(tmp_path, provider, timeout=.20, rag=OrderedRAG(events))) as client:
        result = client.post("/api/analyze", json={"text": "Hãy gửi mã OTP https://example.org",
                                                  "consent": True, "use_rag": True}).json()
    assert len(calls) == 3 and events == ["classification", "retrieval", "explanation"]
    assert_primary_and_url_preserved(result)
    assert result["post_explanation"]["status"] == "no_support"
    assert result["verification"]["code"] == "TIMEOUT"
    assert result["execution"]["runtime"]["timed_out_stage"] == "verify"
    assert result["execution"]["runtime"]["calls_attempted"] == 3


def test_exhausted_budget_during_retrieval_starts_no_more_provider_requests(tmp_path):
    calls = []

    class SlowRAG(OrderedRAG):
        def search(self, text, mode="text"):
            time.sleep(.10)
            return super().search(text, mode)

    def provider(request):
        calls.append(request)
        return packet(core())

    with TestClient(app(tmp_path, provider, timeout=.04, rag=SlowRAG([]))) as client:
        result = client.post("/api/analyze", json={"text": "Hãy gửi mã OTP https://example.org",
                                                  "consent": True, "use_rag": True}).json()
    assert len(calls) == 1
    assert_primary_and_url_preserved(result)
    assert result["post_explanation"]["code"] == "TIMEOUT"
    assert result["verification"]["code"] == "TIMEOUT" and not result["verification"]["attempted"]
    assert result["execution"]["runtime"]["calls_attempted"] == 1


def test_raw_factory_skips_verification_without_managed_budget(tmp_path):
    calls = []

    def provider(request):
        calls.append(request)
        return packet(core())

    with TestClient(app(tmp_path, provider, raw=True)) as client:
        result = client.post("/api/analyze", json={"text": "Hãy gửi mã OTP", "consent": True}).json()
    assert len(calls) == 1
    assert result["verification"]["skip_reason"] == "managed_budget_required"


@pytest.mark.parametrize("profile", ["stable", "focused"])
def test_existing_profiles_do_not_add_verifier_calls(tmp_path, profile):
    calls = []

    def provider(request):
        calls.append(request)
        if profile == "stable":
            return packet({**completion(), "context_kind": "scam_request"})
        return packet(core())

    with TestClient(app(tmp_path, provider, profile=profile)) as client:
        result = client.post("/api/analyze", json={"text": "Hãy gửi mã OTP", "consent": True}).json()
    assert len(calls) == 1 and result["llm"]["status"] == "ok"
    assert "verification" not in result


@pytest.mark.parametrize("profile,cap,thinking", [
    ("stable", 8192, "default"), ("focused", 2048, "disabled"), ("verifier-shadow", 2048, "disabled"),
])
def test_effective_llm_status_shows_applied_caps_without_connection_secrets(tmp_path, profile, cap, thinking):
    with TestClient(app(tmp_path, lambda request: packet(core()), profile=profile, timeout=90)) as client:
        status = client.get("/api/status").json()
    effective = status["runtime"]["effective_llm"]
    assert set(effective) == {"model", "prompt_profile", "max_tokens", "thinking_requested", "rag_stage"}
    assert effective["max_tokens"] == cap and effective["thinking_requested"] == thinking
    assert "endpoint" not in effective and "key" not in effective
    assert "shadow-server-only-key" not in json.dumps(status)
    assert status["limits"]["llm_request_budget_seconds"] == 45
    if profile == "verifier-shadow":
        assert status["analysis_policy"]["verifier_applies_revision"] is False
        assert status["runtime_manifest"]["verification"]["automatic_revision"] is False


def test_shadow_profile_preserves_focused_primary_and_first_payload(tmp_path):
    outputs, first_payloads = {}, {}
    for profile in ("focused", "verifier-shadow"):
        requests = []

        def provider(request):
            body, _ = payload(request)
            requests.append(body)
            return packet(core()) if len(requests) == 1 else packet(opinion())

        with TestClient(app(tmp_path, provider, profile=profile)) as client:
            outputs[profile] = client.post("/api/analyze", json={"text": "Hãy gửi mã OTP https://example.org",
                                                                 "consent": True, "include_ml": True}).json()
        first_payloads[profile] = requests[0]
    assert first_payloads["focused"] == first_payloads["verifier-shadow"]
    for field in ("final", "assessments", "urls", "invalid_urls", "clarification", "post_explanation", "configuration"):
        assert outputs["focused"][field] == outputs["verifier-shadow"][field], field
    for field in ("verdict", "core_decision", "warnings", "validation", "input_used", "claim_grounding"):
        assert outputs["focused"]["llm"][field] == outputs["verifier-shadow"]["llm"][field], field
