"""Conversation scope, consent, prompt isolation and degraded results."""
from dataclasses import replace
import json

import httpx
from fastapi.testclient import TestClient
import pytest

from app.api.workspace import create_app
from app.core.settings import Settings
from app.services.workspace import WorkspaceSettings
from app.services.llm.conversation import PROFILE, SYSTEM
from app.services.llm.core import SYSTEM as MESSAGE_SYSTEM
from tests.api.test_baseline import FakeML
from tests.api.test_candidate_app import OrderedRAG
from tests.api.test_focused_app import decision, packet
from tests.api.test_guest_access import EXT_HEADERS

TEXT = "ĐOẠN HỘI THOẠI ĐÃ CHỌN\n[Tin 01 | Bạn]\nTôi đã nhận hoa hồng.\n[Tin 02 | Người 1]\nHãy gửi mã OTP cho nhân viên. https://example.org/claim"
BODY = {"mode": "text", "text": TEXT, "llm_text": TEXT, "use_llm": True,
        "consent": True, "analysis_target": "conversation"}


def application(tmp_path, calls, profile="focused", finish="stop", answer=None):
    def provider(request):
        calls.append(json.loads(request.content))
        return packet(answer if answer is not None else decision(), finish=finish)
    return create_app(profile, replace(Settings(), api_key="synthetic-test-only"),
        transport=httpx.MockTransport(provider), model_service=FakeML(), rag_service=OrderedRAG([]),
        workspace_settings=WorkspaceSettings(database=tmp_path / "test.sqlite3"))


@pytest.mark.parametrize("profile", ["focused", "stable", "verifier-shadow"])
def test_explicit_conversation_uses_separate_prompt_and_preserves_URLs(tmp_path, profile):
    calls = []
    with TestClient(application(tmp_path, calls, profile)) as client:
        assert client.post("/api/extension/session", headers=EXT_HEADERS, json={}).json()["conversation_analysis_available"]
        response = client.post("/api/extension/analyze", headers=EXT_HEADERS, json=BODY)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["analysis_target"] == "conversation"
        assert data["llm"]["status"] == "ok" and data["llm"]["prompt_version"] == PROFILE
        assert data["llm"]["assessment_scope"] == "selected_conversation"
        assert data["urls"][0]["status"] == "ok"
        assert data["history"]["reason"] == "guest"
        assert calls[0]["messages"][0]["content"] == SYSTEM
        assert "[Tin 02 | Người 1]" in calls[0]["messages"][1]["content"]


def test_conversation_target_does_not_leak_to_next_ordinary_request(tmp_path):
    calls = []
    with TestClient(application(tmp_path, calls)) as client:
        for payload in (BODY, {k: v for k, v in BODY.items() if k != "analysis_target"}):
            assert client.post("/api/extension/analyze", headers=EXT_HEADERS, json=payload).status_code == 200
    assert [call["messages"][0]["content"] for call in calls] == [SYSTEM, MESSAGE_SYSTEM]


@pytest.mark.parametrize("change", [{"mode": "url"}, {"use_rag": True}, {"consent": False}, {"llm_text": None}, {"analysis_target": "untrusted_override"}])
def test_invalid_conversation_scope_or_consent_sends_nothing(tmp_path, change):
    calls = []
    with TestClient(application(tmp_path, calls)) as client:
        assert client.post("/api/extension/analyze", headers=EXT_HEADERS, json={**BODY, **change}).status_code == 422
    assert not calls


@pytest.mark.parametrize("finish,answer", [("length", None), ("stop", {**decision(), "quotes": ["NOT IN APPROVED CONVERSATION"]})])
def test_invalid_provider_reply_keeps_URL_and_UNKNOWN(tmp_path, finish, answer):
    calls = []
    with TestClient(application(tmp_path, calls, finish=finish, answer=answer)) as client:
        response = client.post("/api/extension/analyze", headers=EXT_HEADERS, json=BODY)
        assert response.status_code == 200
        data = response.json()
        assert data["llm"]["status"] == "error" and data["urls"][0]["status"] == "ok"
        assert data["assessments"]["message"]["risk_level"] == "UNKNOWN"
    assert len(calls) == 1
