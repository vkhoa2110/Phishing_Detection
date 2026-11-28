"""Large approved conversations: coverage, limits, cancellation and isolation."""
import asyncio
from dataclasses import replace
import json
import time
import uuid

import httpx
from fastapi.testclient import TestClient
import pytest

from app.api.workspace import create_app
from app.core.settings import Settings
from app.services.conversation_batch import windows
from app.services.workspace import WorkspaceSettings
from tests.api.test_baseline import FakeML
from tests.api.test_candidate_app import OrderedRAG
from tests.api.test_focused_app import packet
from tests.api.test_guest_access import EXT_HEADERS

SCOPE = {"mode": "latest", "requested_limit": 100, "collected_count": 100, "stop_reason": "requested_count", "complete": True}
LONG = "ĐOẠN HỘI THOẠI\n" + "\n".join(f"[Tin {i:03} | Người 1]\nNội dung cuộc họp bình thường số {i}. " + "abcde " * 30 for i in range(100))


def application(tmp_path, calls, *, quota=100, delay=.005, fail_after=None):
    async def provider(request):
        body = json.loads(request.content); calls.append(body)
        await asyncio.sleep(delay)
        if fail_after is not None and len(calls) > fail_after:
            return httpx.Response(429, json={"error": {"message": "fixture limit"}})
        return packet({"risk_level": "LOW", "context_kind": "routine", "reason_code": "no_fraud_evidence", "quotes": [], "missing_context": []})
    return create_app("focused", replace(Settings(), api_key="batch-fixture-only"), transport=httpx.MockTransport(provider),
        model_service=FakeML(), rag_service=OrderedRAG([]), workspace_settings=WorkspaceSettings(database=tmp_path / "test.sqlite3", daily_ai_limit=quota))


def payload(text=LONG, **change):
    return {"text": text, "llm_text": text, "use_llm": True, "consent": True, "scope": SCOPE, **change}


def start(client, data, key=None):
    return client.post("/api/extension/conversation/start", headers=EXT_HEADERS,
        json={"client_key": "1" * 64, "request_key": key or str(uuid.uuid4()), "payload": data})


def poll(client, identity, key="1" * 64):
    return client.post("/api/extension/jobs/status", headers=EXT_HEADERS, json={"client_key": key, "id": identity})


def finished(client, identity):
    deadline = time.monotonic() + 8
    while True:
        data = poll(client, identity).json()
        if data["status"] != "running": return data
        assert time.monotonic() < deadline
        time.sleep(.015)


@pytest.mark.parametrize("text", [LONG, " ".join(f"{i:05}" for i in range(4000)), "\n[Tin 01 | Bạn]\n" + " ".join(f"word{i}" for i in range(5000))], ids=["many_turns","long_unstructured_text","single_long_turn"])
def test_windows_cover_every_character_and_keep_original_overlap(text):
    parts = windows(text)
    assert len(parts) > 1 and all(0 < len(part) <= 7600 for part in parts)
    previous_end = 0
    for part in parts:
        start_at = text.find(part, max(0, previous_end - 1200))
        assert 0 <= start_at <= previous_end
        previous_end = start_at + len(part)
    assert previous_end == len(text)


def test_preview_masks_large_input_without_provider_calls_and_keeps_normal_limit(tmp_path):
    calls = []
    with TestClient(application(tmp_path, calls)) as client:
        text = LONG + "\nEmail: fixture.person@example.org"
        response = client.post("/api/extension/conversation/preview", headers=EXT_HEADERS, json={"text": text})
        assert response.status_code == 200, response.text
        assert response.json()["parts"] > 1 and "fixture.person@example.org" not in response.json()["text"]
        assert not calls
        assert client.post("/api/extension/preview", headers=EXT_HEADERS, json={"text": text}).status_code == 422
        assert client.post("/api/extension/conversation/preview", headers=EXT_HEADERS, json={"text": "x" * 200001}).status_code == 422


def test_long_batch_idempotency_progress_approved_only_and_no_history(tmp_path):
    calls = []
    with TestClient(application(tmp_path, calls)) as client:
        approved = LONG.replace("bình thường", "hợp lệ")
        data = payload(LONG + "\nRAW_PRIVATE_REMOVED", llm_text=approved)
        key = str(uuid.uuid4()); first = start(client, data, key).json()
        assert start(client, data, key).json()["id"] == first["id"]
        result = finished(client, first["id"])
        assert result["status"] == "complete", result
        batch = result["result"]["conversation_batch"]
        assert batch["complete"] and batch["completed_parts"] == len(windows(approved)) == len(calls)
        assert result["result"]["final"]["risk_level"] == "LOW"
        assert result["progress"]["completed"] == batch["total_parts"]
        assert all("RAW_PRIVATE_REMOVED" not in json.dumps(call) for call in calls)
        assert poll(client, first["id"], key="2" * 64).status_code == 404
        assert start(client, payload("Other text"), key).status_code == 409
        with client.app.state.workspace.connection() as conn:
            assert conn.execute("SELECT COUNT(*) FROM history").fetchone()[0] == 0


@pytest.mark.parametrize("changes", [{"consent": False}, {"llm_text": ""}, {"endpoint": "https://override.invalid"}, {"scope": {**SCOPE, "collected_count": 2001}}, {"scope": {**SCOPE, "mode": "dates", "from_date": "2026-02-30"}}, {"scope": {**SCOPE, "mode": "dates", "from_date": "2026-11-27", "to_date": "2026-11-20"}}])
def test_invalid_or_unapproved_batch_never_calls_provider(tmp_path, changes):
    calls = []
    with TestClient(application(tmp_path, calls)) as client:
        assert start(client, payload(**changes)).status_code == 422
        assert not calls and not client.app.state.extension_jobs.jobs


def test_quota_stop_preserves_partial_results_without_low_for_unchecked_parts(tmp_path):
    calls = []
    with TestClient(application(tmp_path, calls, quota=1)) as client:
        first = start(client, payload()).json()
        result = finished(client, first["id"])["result"]
        batch = result["conversation_batch"]
        assert batch["completed_parts"] == 1 and batch["total_parts"] > 1 and not batch["complete"]
        assert batch["stopped"]["status"] == 429 and result["final"]["risk_level"] == "UNKNOWN"
        assert len(calls) == 1


def test_cancel_is_owned_and_stops_after_inflight_part(tmp_path):
    calls = []
    with TestClient(application(tmp_path, calls, delay=.2)) as client:
        first = start(client, payload()).json(); identity = first["id"]
        deadline = time.monotonic() + 4
        while not calls:
            assert time.monotonic() < deadline; time.sleep(.01)
        body = {"client_key": "2" * 64, "id": identity}
        assert client.post("/api/extension/conversation/cancel", headers=EXT_HEADERS, json=body).status_code == 404
        body["client_key"] = "1" * 64
        assert client.post("/api/extension/conversation/cancel", headers=EXT_HEADERS, json=body).status_code == 200
        result = finished(client, identity)["result"]
        assert result["conversation_batch"]["stopped"] == "user_cancelled"
        assert len(calls) == 1 and result["final"]["risk_level"] == "UNKNOWN"


def test_provider_failure_stops_without_retrying_or_hiding_missing_coverage(tmp_path):
    calls = []
    with TestClient(application(tmp_path, calls, fail_after=1)) as client:
        first = start(client, payload()).json(); result = finished(client, first["id"])["result"]
        assert not result["conversation_batch"]["complete"]
        assert result["conversation_batch"]["stopped"] == "provider_error" and len(calls) == 2
        assert result["final"]["risk_level"] == "UNKNOWN"


def test_local_only_batch_does_not_invent_an_AI_assessment(tmp_path):
    calls = []
    with TestClient(application(tmp_path, calls)) as client:
        first = start(client, payload(use_llm=False, consent=False)).json()
        result = finished(client, first["id"])["result"]
        assert not calls and result["llm"]["status"] == "disabled"
        assert result["final"]["risk_level"] == "UNKNOWN"


@pytest.mark.parametrize('levels,total,expected', [(['LOW'],2,'UNKNOWN'),(['HIGH','LOW'],3,'HIGH'),(['WARNING','LOW'],2,'WARNING'),(['LOW','UNKNOWN'],2,'UNKNOWN'),(['LOW','LOW'],2,'LOW')])
def test_window_aggregation_keeps_warnings_and_unknown_for_incomplete_coverage(levels,total,expected):
    from app.services.conversation_batch import aggregate
    results=[{'mode':'text','llm':{'status':'ok','verdict':{'risk_level':level,'evidence':[]}},'urls':[], 'invalid_urls':[], 'timing':{}, 'execution':{}} for level in levels]
    result=aggregate(results,total,SCOPE)
    assert result['final']['risk_level']==expected
    assert result['assessments']['message']['risk_level']==expected
    assert result['final']['assessments']==result['assessments']
