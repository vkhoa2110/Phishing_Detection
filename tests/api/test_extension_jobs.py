"""Durable-in-process extension analysis, ownership and paid-call idempotency."""
import asyncio
from dataclasses import replace
import time
import uuid

import httpx
from fastapi.testclient import TestClient
import pytest

from app.api.workspace import create_app
from app.core.settings import Settings
from app.services.analysis_jobs import AnalysisJobs
from app.services.workspace import WorkspaceSettings
from tests.api.test_baseline import FakeML
from tests.api.test_candidate_app import OrderedRAG
from tests.api.test_focused_app import decision, packet
from tests.api.test_guest_access import AI, LOCAL, EXT_HEADERS


@pytest.fixture
def application(tmp_path):
    calls = []

    async def provider(request):
        calls.append(request)
        await asyncio.sleep(.08)
        return packet(decision())

    app = create_app("focused", replace(Settings(), api_key="fixture-only"), transport=httpx.MockTransport(provider),
        model_service=FakeML(), rag_service=OrderedRAG([]),
        workspace_settings=WorkspaceSettings(database=tmp_path / "test.sqlite3", daily_ai_limit=2))
    app.state.fixture_calls = calls
    return app


def start(client, payload=AI, **extra):
    return client.post("/api/extension/jobs/start", headers=EXT_HEADERS,
        json={"client_key": "1" * 64, "request_key": str(uuid.uuid4()), "payload": payload, **extra})


def status(client, identity, key="1" * 64, headers=EXT_HEADERS):
    return client.post("/api/extension/jobs/status", headers=headers, json={"id": identity, "client_key": key})


def completed(client, identity):
    deadline = time.monotonic() + 3
    while True:
        response = status(client, identity)
        assert response.status_code == 200, response.text
        result = response.json()
        if result["status"] != "running":
            return result
        assert time.monotonic() < deadline
        time.sleep(.015)


def test_closed_request_does_not_cancel_job_and_duplicate_starts_charge_once(application):
    with TestClient(application) as client:
        key = str(uuid.uuid4())
        first = start(client, request_key=key).json()
        assert first["status"] == "running"
        assert start(client, request_key=key).json()["id"] == first["id"]
        assert status(client, key).json()["id"] == first["id"]
        result = completed(client, first["id"])
        assert result["status"] == "complete" and result["result"]["llm"]["status"] == "ok"
        assert start(client, request_key=key).json() == result
        assert len(application.state.fixture_calls) == 1
        assert start(client, {**AI, "text": "Nội dung khác"}, request_key=key).status_code == 409
        # Explicit recheck uses a new idempotency key and the same existing quota.
        second = start(client).json()
        assert second["id"] != first["id"]
        assert completed(client, second["id"])["status"] == "complete"
        rejected = completed(client, start(client).json()["id"])
        assert rejected["status"] == "error" and rejected["error"]["status"] == 429
        assert len(application.state.fixture_calls) == 2
        with application.state.workspace.connection() as conn:
            assert conn.execute("SELECT COUNT(*) FROM history").fetchone()[0] == 0


def test_results_are_bound_to_private_browser_session_and_extension_origin(application):
    with TestClient(application) as client:
        identity = start(client, LOCAL).json()["id"]
        assert completed(client, identity)["status"] == "complete"
        assert status(client, identity, key="2" * 64).status_code == 404
        other = {"X-PhishLens-Extension": "b" * 32, "Origin": "chrome-extension://" + "b" * 32}
        assert status(client, identity, headers=other).status_code == 404
        assert status(client, identity, headers={**EXT_HEADERS, "Origin": "https://foreign.example"}).status_code == 403
        assert status(client, identity, headers={**EXT_HEADERS, "Authorization": "Bearer revoked"}).status_code == 401
        assert client.get("/api/extension/jobs/status", headers=EXT_HEADERS).status_code == 405
        assert client.post("/api/extension/jobs/list", headers=EXT_HEADERS, json={}).status_code == 404


@pytest.mark.parametrize("change", [{"consent": False}, {"llm_text": None}, {"api_key": "override"}])
def test_job_rejects_unapproved_or_provider_override_before_sending(application, change):
    with TestClient(application) as client:
        assert start(client, {**AI, **change}).status_code == 422
        assert not application.state.fixture_calls and not application.state.extension_jobs.jobs


def test_expiry_scrubs_RAM_without_polling_and_shutdown_cancels_tasks():
    async def exercise():
        jobs = AnalysisJobs(ttl=.02, capacity=1)

        async def result():
            return {"private": "temporary"}

        first = jobs.start("owner", "one", {}, result)
        await asyncio.sleep(.005)
        assert jobs.get("owner", first["id"])["result"] == {"private": "temporary"}
        with pytest.raises(Exception) as full:
            jobs.start("owner", "two", {}, result)
        assert full.value.status_code == 429
        await asyncio.sleep(.04)
        assert not jobs.jobs
        cancelled = asyncio.Event()

        async def running():
            try:
                await asyncio.sleep(100)
            finally:
                cancelled.set()

        jobs.start("owner", "two", {}, running)
        await asyncio.sleep(0)
        await jobs.close()
        assert cancelled.is_set() and not jobs.jobs

    asyncio.run(exercise())
