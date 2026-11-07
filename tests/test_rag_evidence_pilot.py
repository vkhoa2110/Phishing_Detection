"""Mock provider validates bounded execution/provenance, not model quality."""
import asyncio
from dataclasses import replace
import json

import httpx
import pytest

from app.settings import Settings
from evaluation import rag_evidence_pilot as pilot
from evaluation.message_data import read_jsonl, write_json, write_jsonl
from evaluation.url_context_run import append, canonical_sha
from test_baseline import completion
from test_rag import source


def prepared(tmp_path, monkeypatch):
    monkeypatch.setattr(pilot, "Settings", lambda: replace(Settings(), api_key="unit-only-secret"))
    origin = tmp_path / "origin"
    origin.mkdir()
    cases = [{"id": f"CASE-{i:02}", "dataset": "sms" if i < 8 else "url_context",
              "text": f"Hãy gửi mã OTP. Mã ca {i}."} for i in range(16)]
    write_json(origin / "execution.json", {"configuration": {"selections": {"rag_with_sources": [c["id"] for c in cases]}}})
    write_jsonl(origin / "cases.jsonl", cases)
    write_jsonl(origin / "predictions.jsonl", [{"id": c["id"], "arm": "v5_plain", "status": "ok",
                    "verdict": {**completion(), "context_kind": "scam_request"}} for c in cases])
    write_json(origin / "prepared.json", {c["id"]: {"retrieval": {"sources": [source()]}} for c in cases})
    out = tmp_path / "run"
    config, selected = pilot.prepare(out, origin)
    return out, config, selected


def provider(counter, truncate_first=False):
    def handle(request):
        counter.append(json.loads(request.content))
        body = json.loads(counter[-1]["messages"][1]["content"])
        if "input_spans" in body:
            raw = {"selections": [{"source_span_id": body["reference_documents"][0]["spans"][0]["id"],
                                   "input_span_id": body["input_spans"][0]["id"], "relation": "mechanism_match"}]}
        else:
            raw = {"support": [{"document_id": "VN-RAG-001", "source_quote": source()["text"],
                                "input_quote": "gửi mã OTP", "claim": "Đối chiếu yêu cầu OTP.",
                                "relation": "mechanism_match", "scope_note": "Chưa xác minh người gửi."}], "actions": []}
        truncated = truncate_first and len(counter) == 1
        return httpx.Response(200, json={"model": counter[-1]["model"], "choices": [{
            "finish_reason": "length" if truncated else "stop",
            "message": {"content": None if truncated else json.dumps(raw, ensure_ascii=False)}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 8192 if truncated else 20,
                      "total_tokens": 8292 if truncated else 120}})
    return httpx.MockTransport(handle)


def test_full_paired_run_keeps_error_raw_usage_and_never_resends(tmp_path, monkeypatch):
    out, config, _ = prepared(tmp_path, monkeypatch)
    calls = []
    transport = provider(calls, truncate_first=True)
    assert asyncio.run(pilot.run(out, live=False))["API_calls"] == 0 and calls == []
    result = asyncio.run(pilot.run(out, live=True, transport=transport))
    assert result["state"] == "complete" and len(calls) == 32
    assert sum(x["errors"].get("OUTPUT_TRUNCATED", 0) for x in result["arms"].values()) == 1
    assert sum(x["valid_responses"] for x in result["arms"].values()) == 31
    assert pilot.verify(out)["records"] == 32
    asyncio.run(pilot.run(out, live=True, transport=transport))
    assert len(calls) == 32
    pilot.report(out)
    sheet = out / "relevance_blind.csv"
    sheet.write_text(sheet.read_text() + "human edit\n")
    pilot.report(out)
    assert sheet.read_text().endswith("human edit\n")
    records = read_jsonl(out / "predictions.jsonl")
    assert "unit-only-secret" not in json.dumps(records)
    record = records[0]
    record["payload_sha256"] = "0" * 64
    write_jsonl(out / "predictions.jsonl", records)
    with pytest.raises(ValueError, match="mismatch"):
        pilot.verify(out)


def test_interrupted_attempt_becomes_error_not_a_second_paid_request(tmp_path, monkeypatch):
    out, config, cases = prepared(tmp_path, monkeypatch)
    item = config["schedule"][0]
    case = next(c for c in cases if c["id"] == item["id"])
    append(out / "attempts.jsonl", {**item, "payload_sha256": canonical_sha(pilot.payload(case, item["arm"], config)),
                                  "frozen_verdict_sha256": canonical_sha(case["verdict"])})
    calls = []
    result = asyncio.run(pilot.run(out, live=True, transport=provider(calls)))
    assert len(calls) == 31 and result["completed"] == 32
    assert sum(a["errors"].get("INTERRUPTED_REQUEST", 0) for a in result["arms"].values()) == 1
    assert pilot.verify(out)["records"] == 32


def test_fatal_gate_and_hash_lock_prevent_more_calls(tmp_path, monkeypatch):
    out, config, _ = prepared(tmp_path, monkeypatch)
    calls = []
    def limited(request):
        calls.append(request)
        return httpx.Response(429)
    transport = httpx.MockTransport(limited)
    assert asyncio.run(pilot.run(out, live=True, transport=transport))["state"] == "stopped_by_gate"
    assert len(calls) == 2
    asyncio.run(pilot.run(out, live=True, transport=transport))
    assert len(calls) == 2
    (out / "cases.jsonl").write_text("[]\n")
    with pytest.raises(ValueError, match="changed"):
        asyncio.run(pilot.run(out, live=True, transport=transport))
    assert len(calls) == 2


def test_nonstop_completion_is_error_for_both_contracts(tmp_path, monkeypatch):
    out, _, _ = prepared(tmp_path, monkeypatch)
    calls = []
    successful = provider(calls)
    def incomplete(request):
        response = successful.handle_request(request)
        body = json.loads(response.content)
        body["choices"][0]["finish_reason"] = "content_filter"
        return httpx.Response(200, json=body)
    result = asyncio.run(pilot.run(out, live=True, transport=httpx.MockTransport(incomplete)))
    assert result["state"] == "stopped_by_gate"
    assert 0 < len(calls) <= 4
    assert all(r["status"] == "error" and r["code"] == "RESPONSE_INCOMPLETE"
               for r in read_jsonl(out / "predictions.jsonl"))
    checked = pilot.verify(out)
    assert checked["raw_replay_count"] == 0 and checked["complete"] is False
