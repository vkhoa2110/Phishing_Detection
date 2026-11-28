"""Same-owner queue, cancellation before dispatch and independent owners."""
import asyncio
from dataclasses import replace
import threading
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
from tests.api.test_guest_access import AI, EXT_HEADERS


def test_queue_preserves_limits_and_cancelling_waiting_job_never_spends_ai_quota(tmp_path):
    calls, started, release = [], threading.Event(), threading.Event()

    async def provider(request):
        calls.append(request)
        if len(calls) == 1:
            started.set()
            while not release.is_set(): await asyncio.sleep(.005)
        return packet(decision())

    app = create_app("focused", replace(Settings(), api_key="fixture"), transport=httpx.MockTransport(provider),
        model_service=FakeML(), rag_service=OrderedRAG([]), workspace_settings=WorkspaceSettings(database=tmp_path/"test.sqlite3", daily_ai_limit=2))
    try:
        with TestClient(app) as client:
            def start():
                return client.post("/api/extension/jobs/start", headers=EXT_HEADERS,
                    json={"client_key": "1"*64, "request_key": str(uuid.uuid4()), "payload": AI})
            def status(identity):
                return client.post("/api/extension/jobs/status", headers=EXT_HEADERS,json={"client_key":"1"*64,"id":identity}).json()
            def cancel(identity, key="1"*64):
                return client.post("/api/extension/jobs/cancel", headers=EXT_HEADERS,json={"client_key":key,"id":identity})
            def done(identity):
                deadline = time.monotonic()+3
                while (value := status(identity))["status"] == "running":
                    assert time.monotonic()<deadline
                    time.sleep(.01)
                return value
            first = start().json(); assert started.wait(2)
            second, third = start().json(), start().json()
            assert status(second["id"])["queued"] and status(third["id"])["queued"]
            assert start().status_code == 429 and len(calls) == 1
            assert cancel(second["id"], "2"*64).status_code == 404
            assert cancel(first["id"]).status_code == 409
            cancelled = cancel(second["id"])
            assert cancelled.status_code == 200 and cancelled.json()["error"]["status"] == 499
            assert done(second["id"])["status"] == "error" and len(calls) == 1
            release.set()
            assert done(first["id"])["result"]["llm"]["status"] == "ok"
            assert done(third["id"])["result"]["llm"]["status"] == "ok"
            assert len(calls) == 2
    finally:
        release.set()


def test_different_owners_do_not_block_each_other_and_closed_queue_is_scrubbed():
    async def exercise():
        jobs, release, started = AnalysisJobs(), asyncio.Event(), asyncio.Event()
        executed = []
        async def slow():
            started.set(); await release.wait(); executed.append("first"); return {}
        async def later(): executed.append("later"); return {}
        first = jobs.start("a", "one", {}, slow)
        await started.wait()
        waiting = jobs.start("a", "two", {}, later)
        separate = jobs.start("b", "one", {}, later)
        await asyncio.sleep(.01)
        assert jobs.get("a", waiting["id"])["queued"]
        assert jobs.get("b", separate["id"])["status"] == "complete"
        release.set(); await asyncio.sleep(.01)
        assert jobs.get("a", first["id"])["status"] == "complete"
        assert jobs.get("a", waiting["id"])["status"] == "complete"
        assert not jobs.owner_locks
        await jobs.close()
        assert not jobs.jobs and not jobs.owner_locks
    asyncio.run(exercise())


def test_cancel_before_task_first_step_still_expires_and_never_executes():
    async def exercise():
        jobs = AnalysisJobs(ttl=.01)
        ran = []
        async def action(): ran.append(True); return {}
        job = jobs.start("owner", "key", {}, action)
        assert jobs.cancel_waiting("owner", job["id"])["error"]["status"] == 499
        await asyncio.sleep(.03)
        assert not ran and not jobs.jobs
        await jobs.close()
    asyncio.run(exercise())
