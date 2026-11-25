"""Public explanation is optional, uses approved text, and cannot replace a verdict."""
import asyncio
from dataclasses import replace
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.workspace import create_app
from app.core.settings import Settings
from app.services.workspace import WorkspaceSettings
from tests.api.test_baseline import FakeML
from tests.api.test_candidate_app import OrderedRAG
from tests.api.test_focused_app import decision, packet
from tests.api.test_guest_access import EXT_HEADERS, AI

NOTE = {"summary": "Nội dung yêu cầu gửi mã xác thực cho người khác. Điều này có thể làm lộ quyền truy cập tài khoản.",
        "evidence": [{"index": 0, "explanation": "Mã OTP có thể dùng để xác nhận đăng nhập hoặc giao dịch; cần xác minh bên nhận trước khi chia sẻ."}]}


def application(tmp_path, provider, timeout=1, daily_limit=100):
    return create_app("focused", replace(Settings(), api_key="private-test-key", timeout_seconds=timeout),
        transport=httpx.MockTransport(provider), model_service=FakeML(), rag_service=OrderedRAG([]),
        workspace_settings=WorkspaceSettings(database=tmp_path / "test.sqlite3", daily_ai_limit=daily_limit))


def test_optional_explanation_uses_only_approved_text_and_keeps_completed_verdict(tmp_path):
    calls = []
    def provider(request):
        body = json.loads(request.content); calls.append(body)
        assert "deleted.example" not in json.dumps(body)
        if len(calls) == 2:
            sent = json.loads(body["messages"][1]["content"])
            assert sent["text"] == AI["llm_text"] and sent["evidence"] == [{"index": 0, "quote": "gửi mã OTP"}]
            return packet(NOTE)
        return packet(decision())
    with TestClient(application(tmp_path, provider)) as client:
        base = {**AI, "text": AI["text"] + " https://deleted.example/private"}
        with_note = client.post("/api/extension/analyze", headers=EXT_HEADERS, json={**base, "explain_evidence": True}).json()
        assert len(calls) == 2
        without = client.post("/api/extension/analyze", headers=EXT_HEADERS, json=base).json()
        assert len(calls) == 3
        assert with_note["llm"]["verdict"] == without["llm"]["verdict"]
        assert with_note["final"] == without["final"] and with_note["urls"] == without["urls"]
        assert with_note["llm"]["evidence_explanation"]["summary"] == NOTE["summary"]
        assert with_note["execution"]["runtime"]["calls_attempted"] == 2
        assert "evidence_explanation" not in without["llm"]
        assert with_note["history"]["reason"] == "guest"
        assert "private-test-key" not in json.dumps(with_note) and "private-thought" not in json.dumps(with_note)
        with client.app.state.workspace.connection() as conn:
            assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0


@pytest.mark.parametrize("invalid", ["json", "index", "duplicate", "length", "http", "timeout"])
def test_explanation_failures_preserve_classification_and_never_retry(tmp_path, invalid):
    calls = []
    async def provider(request):
        calls.append(True)
        if len(calls) == 1: return packet(decision())
        if invalid == "timeout": await asyncio.sleep(.15)
        if invalid == "http": return httpx.Response(429)
        value = {**NOTE}
        if invalid == "index": value["evidence"] = [{"index": 1, "explanation": "Giải thích không thuộc trích dẫn đầu vào."}]
        if invalid == "duplicate": value["evidence"] = NOTE["evidence"] * 2
        if invalid == "json": value = {"risk_level": "LOW"}
        return packet(value, finish="length" if invalid == "length" else "stop")
    with TestClient(application(tmp_path, provider, timeout=.06 if invalid == "timeout" else 1)) as client:
        result = client.post("/api/extension/analyze", headers=EXT_HEADERS, json={**AI, "explain_evidence": True}).json()
    assert len(calls) == 2
    assert result["llm"]["status"] == "ok" and result["llm"]["verdict"]["risk_level"] == "HIGH"
    assert result["llm"]["evidence_explanation"]["status"] == "error"
    if invalid == "timeout": assert result["execution"]["runtime"]["timed_out_stage"] == "describe_evidence"


def test_explanation_opt_in_cannot_bypass_consent(tmp_path):
    calls = []
    def provider(request): calls.append(True); return packet(decision())
    with TestClient(application(tmp_path, provider)) as client:
        assert client.post("/api/extension/analyze", headers=EXT_HEADERS, json={**AI, "consent": False, "explain_evidence": True}).status_code == 422
        assert not calls


def test_explanation_shares_remaining_deadline_with_classification(tmp_path):
    calls = []
    async def provider(request):
        calls.append(True)
        await asyncio.sleep(.06)
        return packet(decision() if len(calls) == 1 else NOTE)
    with TestClient(application(tmp_path, provider, timeout=.1)) as client:
        result = client.post("/api/extension/analyze", headers=EXT_HEADERS, json={**AI, "explain_evidence": True}).json()
    assert len(calls) == 2
    assert result["llm"]["status"] == "ok" and result["llm"]["evidence_explanation"]["code"] == "TIMEOUT"
    assert result["execution"]["runtime"]["timed_out_stage"] == "describe_evidence"


def test_extra_explanation_keeps_request_quota_and_next_request_is_rejected(tmp_path):
    calls = []
    def provider(request):
        calls.append(True)
        return packet(decision() if len(calls) == 1 else NOTE)
    with TestClient(application(tmp_path, provider, daily_limit=1)) as client:
        first = client.post("/api/extension/analyze", headers=EXT_HEADERS, json={**AI, "explain_evidence": True})
        assert first.status_code == 200 and len(calls) == 2
        assert client.post("/api/extension/analyze", headers=EXT_HEADERS, json=AI).status_code == 429
        assert len(calls) == 2
