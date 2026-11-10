"""Bounded once-only execution and replay with a mock, not quality labels."""
import asyncio
from dataclasses import replace
import json

import httpx
import pytest

from app.settings import Settings
from evaluation import rag_controlled_v1 as controlled, v6_pilot as pilot
from evaluation.conversation_structure_v1 import prepare_paired
from evaluation.v6_pilot_report import report
from evaluation.message_data import read_jsonl, write_jsonl
from evaluation.url_context_run import append


def prepare(tmp_path, monkeypatch):
    monkeypatch.setattr(pilot, "Settings", lambda: replace(Settings(), api_key="unit-only-secret"))
    docs = controlled.load_docs()
    monkeypatch.setattr(controlled, "retrieve", lambda cases: {
        case["id"]: [controlled.as_source(docs[case["document_id"]])] for case in cases})
    origin = tmp_path / "origin"
    controlled.prepare(origin / "rag_controlled")
    prepare_paired(origin / "conversation_paired")
    out = tmp_path / "run"
    pilot.prepare(origin, out)
    return out


def provider(calls, first_finish="stop"):
    def handle(request):
        payload = json.loads(request.content)
        calls.append(payload)
        user = json.loads(payload["messages"][1]["content"])
        if "classification_locked" in user:
            answer = {"selections": []}
        else:
            answer = {"risk_level": "LOW", "context_kind": "routine", "summary": "Offline fixture.",
                      "evidence": [], "recommended_actions": []}
            if "PHÂN TÍCH TƯƠNG TÁC" in payload["messages"][0]["content"]:
                answer["interaction"] = {"requested_action": "unknown", "stage": "unknown", "conversation_turns_used": 0}
        return httpx.Response(200, json={"model": payload["model"], "usage": {"total_tokens": 42},
            "choices": [{"finish_reason": first_finish if len(calls) == 1 else "stop",
                         "message": {"content": json.dumps(answer, ensure_ascii=False)}}]})
    return httpx.MockTransport(handle)


def test_full_pilot_keeps_truncation_and_never_resends(tmp_path, monkeypatch):
    out = prepare(tmp_path, monkeypatch)
    calls = []
    transport = provider(calls, "length")
    assert asyncio.run(pilot.run(out))["API_calls"] == 0
    result = asyncio.run(pilot.run(out, live=True, transport=transport))
    assert result["state"] == "complete" and len(calls) == 102
    assert sum(group["errors"].get("OUTPUT_TRUNCATED", 0) for group in result["groups"].values()) == 1
    assert result["accuracy"] is None and result["F1"] is None
    assert pilot.verify(out)["complete"] is True
    report(out)
    review = out / "conversation_output_review.csv"
    review.write_text(review.read_text(encoding="utf-8-sig") + "reviewer edit\n", encoding="utf-8-sig")
    report(out)
    assert review.read_text(encoding="utf-8-sig").endswith("reviewer edit\n")
    asyncio.run(pilot.run(out, live=True, transport=transport))
    assert len(calls) == 102
    records = read_jsonl(out / "responses.jsonl")
    assert "unit-only-secret" not in json.dumps(records)
    records[0]["usage"]["total_tokens"] += 1
    write_jsonl(out / "responses.jsonl", records)
    with pytest.raises(ValueError, match="Sealed"):
        asyncio.run(pilot.run(out, live=True, transport=transport))
    assert len(calls) == 102


def test_interrupted_attempt_is_error_and_is_not_retried(tmp_path, monkeypatch):
    out = prepare(tmp_path, monkeypatch)
    config, _ = pilot.load(out)
    append(out / "attempts.jsonl", {**config["schedule"][0], "started_at": pilot.now()})
    calls = []
    result = asyncio.run(pilot.run(out, live=True, transport=provider(calls)))
    assert result["completed"] == 102 and len(calls) == 101
    assert sum(group["errors"].get("INTERRUPTED_REQUEST", 0) for group in result["groups"].values()) == 1
    assert pilot.verify(out)["complete"] is True


def test_fatal_http_stops_paid_calls_and_persists_gate(tmp_path, monkeypatch):
    out = prepare(tmp_path, monkeypatch)
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(429)
    transport = httpx.MockTransport(handle)
    assert asyncio.run(pilot.run(out, live=True, transport=transport))["state"] == "stopped_by_gate"
    assert len(calls) == 2
    asyncio.run(pilot.run(out, live=True, transport=transport))
    assert len(calls) == 2 and pilot.verify(out)["complete"] is False
