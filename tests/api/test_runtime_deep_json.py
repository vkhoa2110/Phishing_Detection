"""Untrusted provider JSON must not erase an earlier successful assessment."""
from dataclasses import replace
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.runtime import create_app
from app.core.settings import Settings
from tests.api.test_baseline import FakeML
from tests.api.test_candidate_app import OrderedRAG
from tests.api.test_focused_app import decision, packet


def nested_response(location):
    nested = "[" * 15000 + "0" + "]" * 15000
    if location == "content":
        return httpx.Response(200, json={"model": "fixture", "choices": [
            {"finish_reason": "stop", "message": {"content": nested}}]})
    return httpx.Response(200, content=(
        '{"model":"fixture","unused":' + nested + ',"choices":[]}'
    ).encode(), headers={"content-type": "application/json"})


def runtime(tmp_path, provider, profile="verifier-shadow"):
    settings = replace(Settings(), root=tmp_path, api_key="offline-fixture", timeout_seconds=2)
    return create_app(profile, settings, transport=httpx.MockTransport(provider),
                      model_service=FakeML(), rag_service=OrderedRAG([]))


@pytest.mark.parametrize("location,expected", [("content", "OUTPUT_INVALID"), ("envelope", "RESPONSE_INVALID")])
def test_nested_verifier_json_preserves_completed_primary_and_url(tmp_path, location, expected):
    calls = []

    def provider(request):
        payload = json.loads(request.content)
        calls.append(payload)
        return packet(decision()) if len(calls) == 1 else nested_response(location)

    with TestClient(runtime(tmp_path, provider)) as client:
        response = client.post("/api/analyze", json={
            "text": "Hãy gửi mã OTP https://example.org", "consent": True})
    assert response.status_code == 200
    data = response.json()
    assert len(calls) == 2
    assert data["llm"]["status"] == "ok"
    assert data["llm"]["verdict"]["risk_level"] == data["final"]["risk_level"] == "HIGH"
    assert data["assessments"]["url"]["risk_level"] == "HIGH"
    assert data["verification"]["status"] == "error" and data["verification"]["code"] == expected
    assert data["verification"]["suggested_level"] == "HIGH"
    assert not data["verification"]["applied"]
    assert data["execution"]["runtime"]["calls_attempted"] == 2


@pytest.mark.parametrize("profile", ["stable", "focused", "verifier-shadow"])
@pytest.mark.parametrize("location", ["content", "envelope"])
def test_nested_primary_json_retains_url_and_does_not_start_verifier(tmp_path, profile, location):
    calls = []

    def provider(request):
        calls.append(True)
        return nested_response(location)

    with TestClient(runtime(tmp_path, provider, profile)) as client:
        response = client.post("/api/analyze", json={
            "text": "Hãy gửi mã OTP https://example.org", "consent": True})
    assert response.status_code == 200 and len(calls) == 1
    data = response.json()
    assert data["llm"]["status"] == "error"
    assert data["llm"]["code"] in {"RESPONSE_INVALID", "OUTPUT_INVALID"}
    assert data["final"]["risk_level"] == "UNKNOWN"
    assert data["assessments"]["url"]["risk_level"] == "HIGH"
    if profile == "verifier-shadow":
        assert data["verification"]["status"] == "skipped" and not data["verification"]["attempted"]


@pytest.mark.parametrize("profile", ["focused", "verifier-shadow"])
@pytest.mark.parametrize("location", ["content", "envelope"])
def test_nested_explanation_json_cannot_erase_completed_classification(tmp_path, profile, location):
    calls = []

    def provider(request):
        calls.append(True)
        if len(calls) == 1:
            return packet(decision())
        if len(calls) == 2:
            return nested_response(location)
        return packet({"assessment": "supported_alarm", "reason_code": "dangerous_request", "quotes": ["gửi mã OTP"]})

    with TestClient(runtime(tmp_path, provider, profile)) as client:
        response = client.post("/api/analyze", json={
            "text": "Hãy gửi mã OTP https://example.org", "consent": True, "use_rag": True})
    assert response.status_code == 200
    data = response.json()
    assert len(calls) == (3 if profile == "verifier-shadow" else 2)
    assert data["llm"]["status"] == "ok" and data["final"]["risk_level"] == "HIGH"
    assert data["assessments"]["url"]["risk_level"] == "HIGH"
    assert data["post_explanation"]["status"] == "error"
    assert data["post_explanation"]["code"] in {"RESPONSE_INVALID", "OUTPUT_INVALID"}
    if profile == "verifier-shadow":
        assert data["verification"]["status"] == "ok"
        assert data["verification"]["suggested_level"] == "HIGH" and not data["verification"]["applied"]
