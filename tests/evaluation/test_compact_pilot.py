import asyncio
import csv
from dataclasses import replace
import json

import httpx
import pytest

from app.core.settings import Settings
from evaluation.data.sms import read_jsonl, write_json
import evaluation.messages.compact_pilot as pilot
from evaluation.messages.url_context import append


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.setattr(pilot, "Settings", lambda: replace(Settings(), api_key="unit-only-secret"))
    out = tmp_path / "run"
    pilot.prepare(out)
    return out


def provider(calls, *, first_finish="stop", wrong_turn_once=False):
    changed_turn = False

    def handle(request):
        nonlocal changed_turn
        body = json.loads(request.content)
        calls.append(body)
        data = json.loads(body["messages"][1]["content"])
        verdict = {"risk_level": "LOW", "context_kind": "routine", "summary": "Offline fixture.",
                   "evidence": [], "recommended_actions": []}
        if "output_schema" in data:
            turns = data["input_structure"]["visible_turn_limit"]
            if wrong_turn_once and not changed_turn:
                turns += 1
                changed_turn = True
            verdict["interaction"] = {"requested_action": "unknown", "stage": "unknown",
                                      "conversation_turns_used": turns}
        return httpx.Response(200, json={"model": body["model"], "usage": {"total_tokens": 42},
            "choices": [{"finish_reason": first_finish if len(calls) == 1 else "stop",
                         "message": {"content": json.dumps(verdict)}}]})
    return httpx.MockTransport(handle)


def test_registration_keeps_all_threads_pairs_and_no_risk_references(prepared):
    config, requests = pilot.load(prepared)
    assert config["threads"] == 6 and config["unique_inputs"] == 12
    assert config["max_attempts"] == 24
    pairs = {}
    for row in requests.values():
        pairs.setdefault((row["case_id"], row["history"]), []).append(row)
        assert "risk" not in row and "risk_reference" not in row
        assert row["payload"]["max_tokens"] == 2048
        data = json.loads(row["payload"]["messages"][1]["content"])
        assert "url_results" not in data and "reference_documents" not in data
    assert len(pairs) == 12 and all(len(rows) == 2 and rows[0]["text"] == rows[1]["text"] for rows in pairs.values())
    with pytest.raises(ValueError, match="fresh directory"):
        pilot.prepare(prepared)


def test_once_only_raw_replay_keeps_truncation_and_turn_errors(prepared):
    calls = []
    transport = provider(calls, first_finish="length", wrong_turn_once=True)
    assert asyncio.run(pilot.run(prepared))["API_calls"] == 0 and calls == []
    result = asyncio.run(pilot.run(prepared, live=True, transport=transport))
    assert result["state"] == "complete" and len(calls) == 24
    assert result["accuracy"] is None and result["F1"] is None
    records = read_jsonl(prepared / "responses.jsonl")
    assert sum(row["parsed"].get("code") == "OUTPUT_TRUNCATED" for row in records) == 1
    assert sum(row["parsed"].get("diagnostic") == "TURN_COUNT" for row in records) == 1
    assert "unit-only-secret" not in json.dumps(records)
    assert pilot.verify(prepared)["complete"] is True
    pilot.report(prepared)
    review = prepared / "output_review.csv"
    rows = list(csv.DictReader(review.open(encoding="utf-8-sig")))
    assert len(rows) == 24 and all(not r["reviewer_id"] and not r["risk_reference"] for r in rows)
    review.write_text(review.read_text(encoding="utf-8-sig") + "reviewer edit\n", encoding="utf-8-sig")
    pilot.report(prepared)
    assert review.read_text(encoding="utf-8-sig").endswith("reviewer edit\n")
    asyncio.run(pilot.run(prepared, live=True, transport=transport))
    assert len(calls) == 24


def test_interrupted_attempt_is_retained_without_another_call(prepared):
    config, _ = pilot.load(prepared)
    append(prepared / "attempts.jsonl", {**config["schedule"][0], "started_at": pilot.now()})
    calls = []
    result = asyncio.run(pilot.run(prepared, live=True, transport=provider(calls)))
    assert len(calls) == 23 and result["completed"] == 24
    assert sum(v["errors"].get("INTERRUPTED_REQUEST", 0) for v in result["profiles"].values()) == 1
    assert pilot.verify(prepared)["complete"]


def test_fatal_http_stops_and_remains_stopped_on_restart(prepared):
    calls = []
    def fail(request):
        calls.append(request)
        return httpx.Response(429)
    transport = httpx.MockTransport(fail)
    result = asyncio.run(pilot.run(prepared, live=True, transport=transport))
    assert result["state"] == "stopped_by_gate" and len(calls) == 2
    asyncio.run(pilot.run(prepared, live=True, transport=transport))
    assert len(calls) == 2 and not pilot.verify(prepared)["complete"]
    pilot.report(prepared)


def test_recorded_token_budget_is_persisted_as_a_stop(prepared):
    path = prepared / "execution.json"
    config = json.loads(path.read_text())
    config["recorded_token_stop_budget"] = 1
    write_json(path, config)
    calls = []
    result = asyncio.run(pilot.run(prepared, live=True, transport=provider(calls)))
    assert result["state"] == "stopped_by_gate" and len(calls) == 2


@pytest.mark.parametrize("change", ["requests", "source"])
def test_changed_registration_refuses_before_provider_call(prepared, change):
    if change == "requests":
        with (prepared / "requests.jsonl").open("a") as stream:
            stream.write("\n")
    else:
        path = prepared / "execution.json"
        config = json.loads(path.read_text())
        config["source_files_sha256"]["app/services/llm/compact.py"] = "0" * 64
        write_json(path, config)
    calls = []
    with pytest.raises(ValueError, match="changed"):
        asyncio.run(pilot.run(prepared, live=True, transport=provider(calls)))
    assert calls == []


def test_changed_sealed_usage_is_refused_and_not_resent(prepared):
    calls = []
    transport = provider(calls)
    asyncio.run(pilot.run(prepared, live=True, transport=transport))
    path = prepared / "responses.jsonl"
    rows = read_jsonl(path)
    rows[0]["usage"]["total_tokens"] += 1
    from evaluation.data.sms import write_jsonl
    write_jsonl(path, rows)
    with pytest.raises(ValueError, match="Sealed"):
        asyncio.run(pilot.run(prepared, live=True, transport=transport))
    assert len(calls) == 24


def test_connection_continuation_only_sends_unattempted_keys_and_retains_errors(prepared, tmp_path):
    from scripts.evaluation.continue_compact_pilot import prepare as continue_pack, report as combined_report
    failed = []
    def offline(request):
        failed.append(request)
        raise httpx.ConnectError("Offline fixture", request=request)
    stopped = asyncio.run(pilot.run(prepared, live=True, transport=httpx.MockTransport(offline)))
    assert stopped["state"] == "stopped_by_gate" and len(failed) == 4
    before = {name: pilot.sha(prepared / name) for name in pilot.SEALED}
    child = tmp_path / "continuation"
    continuation = continue_pack(prepared, child)
    assert continuation["requests_prepared"] == 20 and continuation["prior_errors_retained"] == 4
    _, parent_requests = pilot.load(prepared)
    _, child_requests = pilot.load(child)
    parent_attempts, _ = pilot.checkpoints(prepared, pilot.load(prepared)[0])
    assert set(child_requests) == set(parent_requests) - set(parent_attempts)
    calls = []
    asyncio.run(pilot.run(child, live=True, transport=provider(calls)))
    combined = combined_report(child)
    assert len(calls) == 20 and combined["completed"] == 24
    assert combined["continuation"]["resent_keys"] == 0
    assert all(v["valid"] == 10 and v["errors"]["CONNECTION_ERROR"] == 2 for v in combined["profiles"].values())
    assert before == {name: pilot.sha(prepared / name) for name in before}
    assert combined["F1"] is None and combined["accuracy"] is None
    with (prepared / "responses.jsonl").open("a") as stream:
        stream.write("\n")
    with pytest.raises(ValueError, match="Parent run changed"):
        combined_report(child)


def test_http_limit_stop_cannot_be_bypassed_as_connection_continuation(prepared, tmp_path):
    from scripts.evaluation.continue_compact_pilot import prepare as continue_pack
    transport = httpx.MockTransport(lambda request: httpx.Response(429))
    asyncio.run(pilot.run(prepared, live=True, transport=transport))
    with pytest.raises(ValueError, match="connection-only"):
        continue_pack(prepared, tmp_path / "rejected")
