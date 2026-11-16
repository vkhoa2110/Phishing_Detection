import asyncio
import gzip
import json

import httpx
import pytest

from app.services.llm.telemetry import MAX_BYTES, ObservedTransport, observe


def test_observation_stores_numeric_counts_but_no_reasoning_or_untrusted_usage_fields():
    secret = "private-reasoning-and-user-data"
    row = observe({"model": "fixture", "id": "request-1", "usage": {"total_tokens": 32,
        "secret": secret, "completion_tokens_details": {"reasoning_tokens": 17, "secret": secret}},
        "choices": [{"finish_reason": "length", "message": {"content": "", "reasoning_content": secret}}]},
        {"model": "fixture", "max_tokens": 32}, http_status=200)
    assert row["content_characters"] == 0 and row["reasoning_characters"] == len(secret)
    assert row["reasoning_field_present"]
    assert row["completion_token_details"] == {"reasoning_tokens": 17}
    assert secret not in json.dumps(row)
    unknown = observe({}, {"max_tokens": 32}, http_status=200)
    assert not unknown["reasoning_field_present"] and unknown["completion_token_details"] == {}


def test_observed_transport_handles_compression_and_never_logs_authorization(tmp_path):
    packet = json.dumps({"model": "fixture", "choices": [{"finish_reason": "stop",
        "message": {"content": "ok", "reasoning_content": "private-thought"}}]}).encode()
    def respond(request):
        return httpx.Response(200, content=gzip.compress(packet), headers={"Content-Encoding": "gzip", "x-request-id": "request-2"})
    path = tmp_path / "observed.jsonl"
    async def run():
        async with httpx.AsyncClient(transport=ObservedTransport(path, httpx.MockTransport(respond))) as client:
            response = await client.post("https://provider.example", json={"max_tokens": 64},
                                         headers={"Authorization": "Bearer private-key"})
            assert response.json()["model"] == "fixture"
    asyncio.run(run())
    row = json.loads(path.read_text())
    assert row["request_id"] == "request-2" and row["reasoning_characters"] == len("private-thought")
    assert "private-key" not in path.read_text() and "private-thought" not in path.read_text()


def test_observed_transport_bounds_large_responses(tmp_path):
    def respond(request): return httpx.Response(200, content=b"x" * (MAX_BYTES + 1))
    path = tmp_path / "observed.jsonl"
    async def run():
        async with httpx.AsyncClient(transport=ObservedTransport(path, httpx.MockTransport(respond))) as client:
            with pytest.raises(httpx.RemoteProtocolError):
                await client.post("https://provider.example", json={"max_tokens": 64})
    asyncio.run(run())
    assert json.loads(path.read_text())["transport_error"] == "OUTPUT_TOO_LARGE"
