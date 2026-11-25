"""Guest analysis without accounts; private records and paid-use limits remain scoped."""
from fastapi.testclient import TestClient
import pytest

from tests.api.test_workspace import application, headers, register


EXTENSION = "a" * 32
EXT_HEADERS = {"X-PhishLens-Extension": EXTENSION, "Origin": "chrome-extension://" + EXTENSION}
LOCAL = {"mode": "url", "text": "https://example.org", "use_llm": False}
AI = {"mode": "text", "text": "Hãy gửi mã OTP", "llm_text": "Hãy gửi mã OTP", "use_llm": True, "consent": True}


def test_guest_URL_AI_and_download_work_without_registering_or_storing_history(application):
    with TestClient(application) as web:
        session = web.get("/api/auth/session").json()
        assert session["guest_access"] and session["user"] is None
        assert web.get("/login").status_code == 200
        assert 'id="continue-guest"' in web.get("/login").text
        assert web.get("/api/browser/download").status_code == 200
        for body in [LOCAL, {**AI, "save_history": True, "save_content": True}]:
            result = web.post("/api/analyze", headers=headers(web), json=body)
            assert result.status_code == 200, result.text
            assert result.json()["history"]["reason"] == "guest"
        with application.state.workspace.connection() as conn:
            for table in ["users", "history", "sessions", "extension_devices", "remembered_devices", "ai_usage"]:
                assert conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0] == 0
        assert register(web)["user"]["role"] == "admin"


def test_extension_guest_needs_no_code_cookie_or_token_and_never_uses_web_account(application):
    with TestClient(application) as client:
        account = register(client)["user"]
        result = client.post("/api/extension/session", headers=EXT_HEADERS, json={})
        assert result.status_code == 200 and result.json()["guest"]
        assert result.json()["user"]["display_name"] == "Chế độ khách"
        result = client.post("/api/extension/analyze", headers=EXT_HEADERS, json={**LOCAL, "save_history": True, "save_content": True})
        assert result.status_code == 200 and result.json()["history"]["reason"] == "guest"
        assert client.get("/api/history").json()["total"] == 0
        with application.state.workspace.connection() as conn:
            assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
        assert client.get("/api/auth/session").json()["user"]["id"] == account["id"]
        assert client.post("/api/extension/disconnect", headers=EXT_HEADERS, json={}).status_code == 200


def test_web_and_extension_guests_share_persistent_AI_limit_despite_cookies_or_extension_id(application):
    with TestClient(application) as web, TestClient(application) as extension:
        assert web.post("/api/analyze", headers=headers(web), json={**AI, "consent": False}).status_code == 422
        assert extension.post("/api/extension/analyze", headers=EXT_HEADERS, json={**AI, "consent": False}).status_code == 422
        assert web.post("/api/analyze", headers=headers(web), json=AI).status_code == 200
        assert extension.post("/api/extension/analyze", headers=EXT_HEADERS, json=AI).status_code == 200
        web.cookies.clear()
        assert web.post("/api/analyze", headers=headers(web), json=AI).status_code == 429
        other = {"X-PhishLens-Extension": "b" * 32, "Origin": "chrome-extension://" + "b" * 32}
        assert extension.post("/api/extension/analyze", headers=other, json=AI).status_code == 429
        assert extension.post("/api/extension/analyze", headers=EXT_HEADERS, json=LOCAL).status_code == 200
        assert web.post("/api/analyze", headers=headers(web), json=LOCAL).status_code == 200


@pytest.mark.parametrize("origin", ["https://foreign.example", "null", "chrome-extension://" + "b" * 32])
def test_websites_cannot_use_guest_extension_API(application, origin):
    with TestClient(application) as client:
        assert client.post("/api/extension/session", headers={**EXT_HEADERS, "Origin": origin}, json={}).status_code == 403
        assert client.post("/api/extension/analyze", headers={**EXT_HEADERS, "Origin": origin}, json=AI).status_code == 403
        assert client.post("/api/analyze", headers={**headers(client), "Origin": origin}, json=AI).status_code == 403


@pytest.mark.parametrize("path", ["/api/history", "/api/admin/users", "/api/dashboard", "/api/browser/devices", "/api/feedback"])
def test_guest_cannot_read_private_data(application, path):
    with TestClient(application) as client:
        assert client.get(path).status_code == 401


def test_invalid_bearer_is_rejected_instead_of_falling_back_to_guest(application):
    with TestClient(application) as client:
        bad = {**EXT_HEADERS, "Authorization": "Bearer invalid-or-revoked"}
        assert client.post("/api/extension/session", headers=bad, json={}).status_code == 401
        assert client.post("/api/extension/analyze", headers=bad, json=AI).status_code == 401
        assert client.post("/api/extension/image-text", headers={**bad, "Content-Type": "image/png"}, content=b"fixture").status_code == 401


def test_guest_OCR_uses_shared_peer_limit_and_does_not_create_an_account(application, monkeypatch):
    with TestClient(application) as client:
        calls = []
        monkeypatch.setattr(application.state.extension_ocr, "extract", lambda data, mime: calls.append(mime) or {"text": "Ảnh minh họa", "image_saved": False})
        for _ in range(30):
            assert client.post("/api/extension/image-text", headers={**EXT_HEADERS, "Content-Type": "image/png"}, content=b"fixture").status_code == 200
        assert client.post("/api/extension/image-text", headers={**EXT_HEADERS, "Content-Type": "image/png"}, content=b"fixture").status_code == 429
        assert len(calls) == 30
        with application.state.workspace.connection() as conn:
            assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0


def test_guest_does_not_supply_provider_configuration(application):
    with TestClient(application) as client:
        assert client.post("/api/analyze", headers=headers(client), json={**AI, "endpoint": "https://foreign.example"}).status_code == 422
        assert client.post("/api/extension/analyze", headers=EXT_HEADERS, json={**AI, "api_key": "arbitrary"}).status_code == 422
        for _ in range(2):
            assert client.post("/api/extension/analyze", headers=EXT_HEADERS, json=AI).status_code == 200
