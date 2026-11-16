import asyncio
from dataclasses import replace
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.runtime import ACTIVE_BUDGET, BudgetedLLM, RequestBudget, create_app
from app.core.settings import Settings
from tests.api.test_baseline import FakeML
from tests.api.test_candidate_app import OrderedRAG
from tests.api.test_focused_app import decision, packet


def runtime(tmp_path, provider, *, timeout=1, rag=None, profile="focused"):
    return create_app(profile, replace(Settings(), root=tmp_path, api_key="server-only-fixture", timeout_seconds=timeout),
        transport=httpx.MockTransport(provider), model_service=FakeML(), rag_service=rag or OrderedRAG([]))


@pytest.mark.parametrize("override", [{"api_key": "never-echo-this-key"}, {"endpoint": "https://private.invalid"}, {"model": "override"}])
def test_connection_override_is_rejected_without_any_provider_call(tmp_path, override, caplog):
    calls = []
    with TestClient(runtime(tmp_path, lambda request: calls.append(request))) as client:
        response = client.post("/api/analyze", json={"text": "Hãy gửi mã OTP", "consent": True, **override})
        assert response.status_code == 422 and not calls
        assert "never-echo-this-key" not in response.text + caplog.text


def test_approved_text_and_approved_urls_only_reach_server_configured_provider(tmp_path, caplog):
    calls = []
    def provider(request):
        assert request.headers["authorization"] == "Bearer server-only-fixture"
        data = json.loads(request.content); calls.append(data)
        assert "private.example" not in json.dumps(data) and "person@" not in json.dumps(data)
        assert json.loads(data["messages"][1]["content"])["text"] == "Hãy gửi mã OTP"
        return packet(decision())
    with TestClient(runtime(tmp_path, provider)) as client:
        status = client.get("/api/status")
        assert status.json()["runtime"]["connection_mode"] == "server_managed"
        assert "server-only-fixture" not in status.text
        body = {"text": "person@example.org https://private.example/?token=secret", "llm_text": "Hãy gửi mã OTP", "include_ml": True}
        assert client.post("/api/analyze", json=body).status_code == 422 and not calls
        result = client.post("/api/analyze", json={**body, "consent": True})
        assert result.status_code == 200 and len(calls) == 1
        assert result.json()["execution"]["runtime"]["calls_attempted"] == 1
        assert "server-only-fixture" not in result.text + caplog.text


@pytest.mark.parametrize("failure,expected", [("length", "OUTPUT_TRUNCATED"), ("json", "OUTPUT_INVALID"),
                                              ("http", "HTTP_429"), ("timeout", "TIMEOUT")])
def test_provider_failures_keep_real_url_assessment_and_no_semantic_questions(tmp_path, failure, expected):
    async def provider(request):
        if failure == "timeout": await asyncio.sleep(.5)
        if failure == "http": return httpx.Response(429, json={"error": "rate_limited"})
        if failure == "json":
            return httpx.Response(200, json={"model": "fixture", "choices": [{"finish_reason": "stop", "message": {"content": "not json"}}]})
        return packet(decision(), finish="length")
    with TestClient(runtime(tmp_path, provider, timeout=.03)) as client:
        result = client.post("/api/analyze", json={"text": "Hãy gửi mã OTP https://example.org", "consent": True}).json()
        assert result["llm"]["status"] == "error" and result["llm"]["code"] == expected
        assert result["assessments"]["url"]["risk_level"] == "HIGH"
        assert not result["clarification"]["questions"]
        assert not result["execution"]["llm"]["semantic_uncertainty"]
        if failure == "timeout": assert result["execution"]["runtime"]["timed_out_stage"] == "analyze"


def test_classification_and_optional_explanation_share_one_deadline(tmp_path):
    calls = []
    async def provider(request):
        calls.append(True)
        await asyncio.sleep(.09)
        return packet(decision())
    with TestClient(runtime(tmp_path, provider, timeout=.15, rag=OrderedRAG([]))) as client:
        result = client.post("/api/analyze", json={"text": "Hãy gửi mã OTP", "consent": True, "use_rag": True}).json()
        assert len(calls) == 2
        assert result["llm"]["status"] == "ok" and result["llm"]["verdict"]["risk_level"] == "HIGH"
        assert result["post_explanation"]["status"] == "error" and result["post_explanation"]["code"] == "TIMEOUT"
        assert result["execution"]["runtime"]["timed_out_stage"] == "explain"
        assert result["execution"]["explanation"]["classification_changed"] is False


def test_concurrent_requests_have_independent_budgets():
    class Service:
        async def analyze(self):
            await asyncio.sleep(.01)
            return {"status": "ok"}
    wrapped = BudgetedLLM(Service())
    async def one():
        budget = RequestBudget(.1)
        token = ACTIVE_BUDGET.set(budget)
        try:
            await wrapped.analyze(); await wrapped.analyze()
            return budget
        finally: ACTIVE_BUDGET.reset(token)
    async def both(): return await asyncio.gather(one(), one())
    a, b = asyncio.run(both())
    assert a is not b and a.calls == b.calls == 2
    assert ACTIVE_BUDGET.get() is None


def test_no_new_explanation_call_starts_after_budget_expires_during_retrieval(tmp_path):
    import time
    class SlowRAG(OrderedRAG):
        def search(self, text, mode="text"):
            time.sleep(.06)
            return super().search(text, mode)
    calls = []
    def provider(request):
        calls.append(True)
        return packet(decision())
    with TestClient(runtime(tmp_path, provider, timeout=.03, rag=SlowRAG([]))) as client:
        result = client.post("/api/analyze", json={"text": "Hãy gửi mã OTP", "consent": True, "use_rag": True}).json()
        assert result["llm"]["status"] == "ok" and len(calls) == 1
        assert result["post_explanation"]["code"] == "TIMEOUT"
        assert result["execution"]["runtime"]["calls_attempted"] == 1


@pytest.mark.parametrize("profile", ["stable", "focused"])
def test_profile_is_explicit_and_timeout_is_capped_at_45_seconds(tmp_path, profile):
    with TestClient(runtime(tmp_path, lambda request: packet(decision()), timeout=90, profile=profile)) as client:
        status = client.get("/api/status").json()
        assert status["runtime"]["profile"] == profile
        assert status["limits"]["llm_request_budget_seconds"] == 45
        assert status["limits"]["llm_timeout_seconds"] == 45
