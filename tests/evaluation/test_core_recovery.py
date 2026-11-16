import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path

import httpx
import pytest

from app.core.settings import ROOT, Settings
from app.services.llm.telemetry import observe
from evaluation.common import registered
from evaluation.data.sms import sha, write_json, write_jsonl
from evaluation.messages.core_pilot import parse_response

spec = importlib.util.spec_from_file_location("core_recovery", ROOT / "scripts/evaluation/recover_core_quality.py")
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


def stopped_run(tmp_path, monkeypatch, status=429):
    settings = replace(Settings(), api_key="offline-fixture")
    monkeypatch.setattr(registered, "Settings", lambda: settings)
    parent, health = tmp_path / "parent", tmp_path / "health"
    rows = [{"key": str(i), "profile": "probe", "payload": {"model": settings.llm_model,
        "messages": [{"role": "user", "content": str(i)}], "max_tokens": 2048}} for i in range(3)]
    config = registered.register(parent, rows, stage="core_quality_dev", max_tokens=2048, token_budget=10000)
    first = {**config["schedule"][0], "started_at": "2026-11-12T00:00:00+00:00"}
    row = {**first, "http_status": status, "content": None, "finish_reason": None,
           "provider_model": None, "usage": {}, "elapsed_ms": 2,
           "parsed": {"status": "error", "code": f"HTTP_{status}"}}
    write_jsonl(parent / "attempts.jsonl", [first])
    write_jsonl(parent / "responses.jsonl", [row])
    write_jsonl(parent / "telemetry.jsonl", [observe({}, rows[0]["payload"], http_status=status)])
    write_json(parent / "summary.json", registered.summary(config, {(config["stage"], "0"): row}, "stopped_by_gate"))
    health.mkdir()
    write_json(health / "health_protocol.json", {"endpoint": config["endpoint"], "payload": {"model": config["model"]}})
    write_json(health / "health_attempt.json", {"protocol_sha256": sha(health / "health_protocol.json")})
    write_json(health / "health_result.json", {"http_status": 200, "finish_reason": "stop",
        "completed_at": datetime.now(timezone.utc).isoformat(), "usage": {"total_tokens": 14}})
    return parent, health


def test_only_unattempted_payloads_are_paced_and_parent_error_survives_merge(tmp_path, monkeypatch):
    parent, health = stopped_run(tmp_path, monkeypatch)
    before = {p.name: sha(p) for p in parent.iterdir() if p.is_file()}
    child, merged = tmp_path / "child", tmp_path / "merged"
    result = recovery.prepare(parent, health, child)
    assert result["prepared"] == 2 and result["recorded_token_budget"] == 9986
    calls, delays = [], []
    async def sleep(delay): delays.append(delay)
    monkeypatch.setattr(recovery.asyncio, "sleep", sleep)
    def respond(request):
        payload = json.loads(request.content); calls.append(payload["messages"][0]["content"])
        assert request.headers["authorization"] == "Bearer offline-fixture"
        return httpx.Response(200, json={"model": "fixture", "usage": {"total_tokens": 20},
            "choices": [{"finish_reason": "stop", "message": {"content": '{"ok":true}'}}]})
    result = asyncio.run(recovery.run(child, True, httpx.MockTransport(respond)))
    assert result["state"] == "complete" and calls == ["1", "2"]
    assert len(delays) == 1 and 0 < delays[0] <= 4
    # Re-running a complete journal must not resend provider calls.
    asyncio.run(recovery.run(child, True, httpx.MockTransport(respond)))
    assert calls == ["1", "2"]
    monkeypatch.setattr(recovery, "report", lambda out: {"arms": {}})
    recovery.merge(child, merged)
    state = json.loads((merged / "summary.json").read_text())
    assert state["completed"] == 3 and state["valid"] == 2 and state["errors"] == {"HTTP_429": 1}
    assert state["usage_missing"] == 1
    assert registered.verify(merged, parse_response)["complete"]
    assert before == {p.name: sha(p) for p in parent.iterdir() if p.is_file()}


def test_permission_error_cannot_be_recovered_by_this_amendment(tmp_path, monkeypatch):
    parent, health = stopped_run(tmp_path, monkeypatch, status=403)
    with pytest.raises(ValueError, match="HTTP 429"):
        recovery.prepare(parent, health, tmp_path / "child")


def test_unsuccessful_health_check_blocks_continuation(tmp_path, monkeypatch):
    parent, health = stopped_run(tmp_path, monkeypatch)
    path = health / "health_result.json"
    value = json.loads(path.read_text()); value["http_status"] = 429
    write_json(path, value)
    with pytest.raises(ValueError, match="health check"):
        recovery.prepare(parent, health, tmp_path / "child")
