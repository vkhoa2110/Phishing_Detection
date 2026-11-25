"""Account boundaries and persistence; provider is mocked, databases are temporary."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import sqlite3
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.workspace import create_app, SESSION
from app.core import accounts
from app.core.settings import Settings
from app.services.workspace import WorkspaceSettings
from tests.api.test_baseline import FakeML
from tests.api.test_candidate_app import OrderedRAG
from tests.api.test_focused_app import packet, decision

PASSWORD = "a-long-test-password"


@pytest.fixture
def application(tmp_path, monkeypatch):
    # Fast test hashes only. Production cost is independently asserted below.
    monkeypatch.setattr(accounts, "SCRYPT_N", 2 ** 10)
    return create_app("focused", replace(Settings(), root=tmp_path, api_key="server-fixture-private-key"),
        transport=httpx.MockTransport(lambda request: packet(decision())),
        model_service=FakeML(), rag_service=OrderedRAG([]),
        workspace_settings=WorkspaceSettings(database=tmp_path / "application/test.sqlite3", daily_ai_limit=2))


def register(client, email="one@example.org"):
    csrf = client.get("/api/auth/session").json()["csrf_token"]
    response = client.post("/api/auth/register", json={"email": email, "password": PASSWORD, "display_name": "Người dùng thử"}, headers={"X-CSRF-Token": csrf})
    assert response.status_code == 200, response.text
    return response.json()


def headers(client):
    return {"X-CSRF-Token": client.get("/api/auth/session").json()["csrf_token"]}


def analyze(client, **extra):
    return client.post("/api/analyze", headers=headers(client), json={"text": "Hãy gửi mã OTP https://example.org", "consent": True, **extra})


def test_production_password_hash_uses_scrypt_with_salt_and_constant_comparison():
    first, second = accounts.password_hash(PASSWORD), accounts.password_hash(PASSWORD)
    assert first.startswith("scrypt$131072$") and first != second
    assert PASSWORD not in first and accounts.password_matches(PASSWORD, first)
    assert not accounts.password_matches("incorrect", first)


def test_guest_can_open_check_but_private_data_stays_authenticated(application):
    with TestClient(application) as client:
        assert client.get("/", follow_redirects=False).status_code == 303
        assert client.get("/", follow_redirects=False).headers["location"] == "/check"
        assert client.get("/check").status_code == 200
        assert client.get("/api/status").status_code == 200
        for path in ("/api/history", "/api/dashboard", "/api/admin/users"):
            assert client.get(path).status_code == 401
        assert client.post("/api/analyze", json={"text": "Hãy gửi mã OTP", "consent": True}).status_code == 403


def test_registration_normalizes_email_and_stores_only_hashes(application):
    with TestClient(application) as client:
        data = register(client, "Mixed@Example.ORG")
        assert data["user"]["email"] == "mixed@example.org" and data["user"]["role"] == "admin"
        assert set(data["user"]) == {"id", "email", "display_name", "role", "active", "created_at"}
        with application.state.workspace.connection() as conn:
            encoded = conn.execute("SELECT password_hash FROM users").fetchone()[0]
            session = conn.execute("SELECT token_hash FROM sessions").fetchone()[0]
        assert PASSWORD not in encoded and session != client.cookies.get(SESSION)
        assert client.get("/check").status_code == 200


def test_cookie_has_protective_attributes_and_logout_revokes_it(application):
    with TestClient(application) as client:
        csrf = headers(client)
        response = client.post("/api/auth/register", headers=csrf, json={"email": "one@example.org", "display_name": "One", "password": PASSWORD})
        cookie = response.headers.get_list("set-cookie")[0].lower()
        assert "httponly" in cookie and "samesite=strict" in cookie
        token = client.cookies.get(SESSION)
        assert client.post("/api/auth/logout", headers=headers(client)).status_code == 200
        assert application.state.workspace.session_user(token) is None
        assert client.get("/api/history").status_code == 401


def test_csrf_and_cross_origin_requests_are_rejected(application):
    with TestClient(application) as client:
        assert client.post("/api/auth/register", json={"email": "one@example.org", "password": PASSWORD, "display_name": "One"}).status_code == 403
        register(client)
        assert client.patch("/api/auth/profile", json={"display_name": "New"}).status_code == 403
        assert client.patch("/api/auth/profile", headers={**headers(client), "Origin": "https://foreign.example"}, json={"display_name": "New"}).status_code == 403
        assert client.patch("/api/auth/profile", headers=headers(client), json={"display_name": "New"}).status_code == 200


def test_malformed_non_ascii_csrf_is_rejected_without_server_error(application):
    with TestClient(application) as client:
        register(client)
        response = client.patch("/api/auth/profile", headers={"X-CSRF-Token": b"\xe9"}, json={"display_name": "New"})
        assert response.status_code == 403


def test_users_cannot_read_edit_delete_or_export_each_others_history(application):
    with TestClient(application) as alice:
        register(alice)
        record = analyze(alice).json()["history"]["id"]
        with TestClient(application) as bob:
            register(bob, "two@example.org")
            assert bob.get("/api/history").json()["total"] == 0
            assert bob.get("/api/history/" + record).status_code == 404
            assert bob.patch("/api/history/" + record, headers=headers(bob), json={"favorite": True}).status_code == 404
            assert bob.delete("/api/history/" + record, headers=headers(bob)).status_code == 404
            assert bob.get("/api/admin/users").status_code == 403
            assert bob.post("/api/model/reload", headers=headers(bob), json={}).status_code == 403
            bob.delete("/api/history", headers=headers(bob))
        assert alice.get("/api/history/" + record).status_code == 200


def test_default_history_retains_no_message_text_and_opt_in_stores_only_redacted_content(application):
    with TestClient(application) as client:
        register(client)
        raw = "private.person@example.org 0912345678 OTP: 123456 https://example.org/?token=unredacted-query"
        first = analyze(client, text=raw, use_llm=False).json()["history"]["id"]
        assert client.get("/api/history/" + first).json()["snapshot"] is None
        second = analyze(client, text=raw, use_llm=False, save_content=True).json()["history"]["id"]
        snapshot = client.get("/api/history/" + second).json()["snapshot"]
        serialized = json.dumps(snapshot)
        for value in ("private.person@", "0912345678", "123456", "unredacted-query", "server-fixture-private-key"):
            assert value not in serialized
        assert snapshot["approved_text"] and "[EMAIL]" in snapshot["approved_text"]
        count = client.get("/api/history").json()["total"]
        assert analyze(client, use_llm=False, save_history=False).json()["history"]["status"] == "disabled"
        assert client.get("/api/history").json()["total"] == count


def test_history_filters_notes_favorites_and_delete(application):
    with TestClient(application) as client:
        register(client)
        record = analyze(client, use_llm=False).json()["history"]["id"]
        assert client.patch("/api/history/" + record, headers=headers(client), json={"title": "Tin ngân hàng", "note": "Kiểm tra lại", "favorite": True}).status_code == 200
        assert client.get("/api/history", params={"q": "ngân hàng", "favorite": True}).json()["total"] == 1
        assert client.get("/api/history", params={"q": "NGAN HANG", "favorite": True}).json()["total"] == 1
        assert client.get("/api/history", params={"q": "' OR 1=1 --"}).json()["total"] == 0
        assert client.patch("/api/history/" + record, headers=headers(client), json={"user_id": "foreign"}).status_code == 422
        assert client.delete("/api/history/" + record, headers=headers(client)).status_code == 200
        assert client.get("/api/history").json()["total"] == 0


def test_password_change_revokes_other_sessions_and_old_password(application):
    with TestClient(application) as first, TestClient(application) as second:
        register(first)
        second.post("/api/auth/login", headers=headers(second), json={"email": "one@example.org", "password": PASSWORD})
        assert second.get("/api/dashboard").status_code == 200
        assert first.post("/api/auth/password", headers=headers(first), json={"current_password": "wrong", "new_password": "new-long-test-password"}).status_code == 400
        changed = first.post("/api/auth/password", headers=headers(first), json={"current_password": PASSWORD, "new_password": "new-long-test-password"})
        assert changed.status_code == 200
        assert first.get("/api/dashboard").status_code == 200
        assert second.get("/api/dashboard").status_code == 401
        assert second.post("/api/auth/login", headers=headers(second), json={"email": "one@example.org", "password": PASSWORD}).status_code == 401
        assert second.post("/api/auth/login", headers=headers(second), json={"email": "one@example.org", "password": "new-long-test-password"}).status_code == 200


def test_admin_can_suspend_a_user_and_cannot_suspend_or_demote_self(application):
    with TestClient(application) as admin, TestClient(application) as member:
        admin_user = register(admin)["user"]
        user = register(member, "member@example.org")["user"]
        assert user["role"] == "user"
        assert admin.patch("/api/admin/users/" + admin_user["id"], headers=headers(admin), json={"active": False}).status_code == 400
        assert admin.patch("/api/admin/users/" + admin_user["id"], headers=headers(admin), json={"role": "user"}).status_code == 400
        assert admin.patch("/api/admin/users/" + user["id"], headers=headers(admin), json={"active": False}).status_code == 200
        assert member.get("/api/dashboard").status_code == 401
        assert member.post("/api/auth/login", headers=headers(member), json={"email": "member@example.org", "password": PASSWORD}).status_code == 401
        listing = admin.get("/api/admin/users").text
        assert PASSWORD not in listing and "password_hash" not in listing


def test_quota_consent_and_failures_do_not_allow_unbounded_provider_calls(application):
    with TestClient(application) as client:
        register(client)
        assert analyze(client, consent=False).status_code == 422
        assert client.get("/api/dashboard").json()["ai_used_24h"] == 0
        assert analyze(client).status_code == 200
        assert analyze(client).status_code == 200
        assert analyze(client).status_code == 429
        assert analyze(client, use_llm=False).status_code == 200
        assert client.get("/api/dashboard").json()["ai_used_24h"] == 2


def test_login_rate_limit_is_persistent_and_does_not_echo_password(application):
    with TestClient(application) as client:
        register(client)
        for _ in range(10):
            result = client.post("/api/auth/login", headers=headers(client), json={"email": "one@example.org", "password": "incorrect-password"})
            assert result.status_code == 401 and "incorrect-password" not in result.text
        assert client.post("/api/auth/login", headers=headers(client), json={"email": "one@example.org", "password": PASSWORD}).status_code == 429


def test_expired_session_is_not_authorized(application):
    with TestClient(application) as client:
        register(client)
        with application.state.workspace.connection(write=True) as conn:
            conn.execute("UPDATE sessions SET expires_at=?", (time.time() - 1,))
        assert client.get("/api/history").status_code == 401


def test_registration_cannot_set_admin_role_and_short_password_rejected(application):
    with TestClient(application) as client:
        body = {"email": "one@example.org", "display_name": "One", "password": PASSWORD, "role": "admin"}
        assert client.post("/api/auth/register", headers=headers(client), json=body).status_code == 422
        body.pop("role"); body["password"] = "short"
        assert client.post("/api/auth/register", headers=headers(client), json=body).status_code == 422


def test_database_records_persist_between_application_instances(application):
    with TestClient(application) as client:
        user = register(client)["user"]
        analyze(client, use_llm=False)
    store = application.state.workspace
    store.initialize()
    assert store.authenticate("one@example.org", PASSWORD)["id"] == user["id"]
    assert store.history(user["id"])["total"] == 1


def test_online_backup_is_consistent_and_never_overwrites_an_existing_file(application, tmp_path):
    from scripts.maintenance.workspace import backup
    with TestClient(application) as client:
        register(client)
        analyze(client, use_llm=False)
        destination = tmp_path / "backup.sqlite3"
        backup(application.state.workspace.settings.database, destination)
        with sqlite3.connect(destination) as conn:
            assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
            assert conn.execute("SELECT COUNT(*) FROM history").fetchone()[0] == 1
        with pytest.raises(FileExistsError):
            backup(application.state.workspace.settings.database, destination)
