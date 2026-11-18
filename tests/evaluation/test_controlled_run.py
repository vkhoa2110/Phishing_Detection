import asyncio
import json
from dataclasses import replace

import httpx
import pytest

from evaluation.common import controlled_run, registered
from evaluation.data.sms import sha, write_json


def parser(content, request):
    return {"status": "ok", "answer": json.loads(content)["answer"]}


@pytest.fixture
def run_folder(tmp_path, monkeypatch):
    settings = controlled_run.Settings()
    monkeypatch.setattr(controlled_run, "Settings", lambda: replace(settings, api_key="offline-unit-fixture"))
    rows = [{"key": str(i), "text": str(i), "payload": {"model": settings.llm_model, "max_tokens": 64,
             "messages": [{"role": "user", "content": str(i)}]}} for i in range(3)]
    out = tmp_path / "run"
    config = registered.register(out, rows, stage="controlled_unit", max_tokens=64,
        metadata={"pacing_seconds": 0, "pilot_unique_requests": 1}, token_budget=1000)
    config["workers"] = 1
    write_json(out / "execution.json", config)
    (out / "registration.sha256").write_text(sha(out / "execution.json") + "\n")
    return out


def good_response():
    return httpx.Response(200, json={"model": "offline-unit", "usage": {"total_tokens": 4},
        "choices": [{"finish_reason": "stop", "message": {"content": '{"answer":"ok"}'}}]})


def test_operational_pilot_pauses_then_only_unattempted_keys_resume(run_folder):
    seen = []
    def provider(request):
        seen.append(json.loads(request.content)["messages"][0]["content"])
        return good_response()
    first = asyncio.run(controlled_run.run(run_folder, parser, live=True, limit=1, inner=httpx.MockTransport(provider)))
    assert first["state"] == "pilot_paused" and first["completed"] == 1 and seen == ["0"]
    assert not registered.verify(run_folder, parser)["complete"]
    final = asyncio.run(controlled_run.run(run_folder, parser, live=True, inner=httpx.MockTransport(provider)))
    assert final["state"] == "complete" and seen == ["0", "1", "2"]
    assert registered.verify(run_folder, parser)["complete"]
    asyncio.run(controlled_run.run(run_folder, parser, live=True, inner=httpx.MockTransport(provider)))
    assert len(seen) == 3


def test_fatal_http_gate_is_not_bypassed_by_resuming(run_folder):
    seen = []
    def provider(request):
        seen.append(True)
        return httpx.Response(429, json={"error": "synthetic quota response"})
    first = asyncio.run(controlled_run.run(run_folder, parser, live=True, limit=1, inner=httpx.MockTransport(provider)))
    assert first["state"] == "stopped_by_gate" and first["errors"] == {"HTTP_429": 1}
    second = asyncio.run(controlled_run.run(run_folder, parser, live=True, inner=httpx.MockTransport(provider)))
    assert second["state"] == "stopped_by_gate" and len(seen) == 1


def test_pilot_size_is_enforced_before_first_send(run_folder):
    with pytest.raises(ValueError, match="pilot size"):
        asyncio.run(controlled_run.run(run_folder, parser, live=True, inner=httpx.MockTransport(lambda request: pytest.fail("no send"))))
    assert not (run_folder / "attempts.jsonl").exists()


def test_token_gate_preserves_remaining_pending_inventory(run_folder):
    def provider(request):
        response = good_response()
        value = response.json()
        value["usage"]["total_tokens"] = 1001
        return httpx.Response(200, json=value)
    result = asyncio.run(controlled_run.run(run_folder, parser, live=True, limit=1, inner=httpx.MockTransport(provider)))
    assert result["state"] == "stopped_by_gate" and result["completed"] == 1
    assert not (run_folder / "result_hashes.json").exists()


def test_interrupted_attempt_is_retained_and_never_resent(run_folder):
    config, _ = registered.load(run_folder)
    first = {**config["schedule"][0], "started_at": "2026-11-18T00:00:00+00:00"}
    controlled_run.append(run_folder / "attempts.jsonl", first)
    seen = []
    def provider(request):
        seen.append(json.loads(request.content)["messages"][0]["content"])
        return good_response()
    result = asyncio.run(controlled_run.run(run_folder, parser, live=True, inner=httpx.MockTransport(provider)))
    assert seen == ["1", "2"] and result["errors"] == {"INTERRUPTED_REQUEST": 1}
    assert registered.verify(run_folder, parser)["complete"]


def test_dry_run_does_not_open_a_transport(run_folder):
    result = asyncio.run(controlled_run.run(run_folder, parser, inner=httpx.MockTransport(lambda request: pytest.fail("no send"))))
    assert result["API_calls"] == 0 and result["requests"] == 3
    assert not (run_folder / "attempts.jsonl").exists()
