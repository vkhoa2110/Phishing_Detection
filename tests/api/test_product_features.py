"""Extension trust boundaries, opt-in feedback and quota parity. No provider calls."""
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor
import json
import time
import zipfile

from fastapi.testclient import TestClient
import pytest

from tests.api.test_workspace import application, register, headers, analyze, PASSWORD
from app.services.product_features import ProductStore
from app.services.workspace import WorkspaceError

EXTENSION = "a" * 32
ORIGIN = "chrome-extension://" + EXTENSION


def connect(web, extension):
    issued = web.post("/api/browser/pairing", headers=headers(web), json={})
    assert issued.status_code == 200
    response = extension.post("/api/extension/connect", headers={"X-PhishLens-Extension": EXTENSION, "Origin": ORIGIN}, json={"code": issued.json()["code"]})
    assert response.status_code == 200, response.text
    return {"X-PhishLens-Extension": EXTENSION, "Authorization": "Bearer " + response.json()["token"], "Origin": ORIGIN}


def test_pairing_is_authenticated_csrf_protected_one_time_and_stores_hashes(application):
    with TestClient(application) as web, TestClient(application) as ext:
        assert web.post("/api/browser/pairing", json={}).status_code == 401
        register(web)
        assert web.post("/api/browser/pairing", json={}).status_code == 403
        issued = web.post("/api/browser/pairing", headers=headers(web), json={}).json()
        eheaders = {"X-PhishLens-Extension": EXTENSION, "Origin": ORIGIN}
        first = ext.post("/api/extension/connect", headers=eheaders, json={"code": issued["code"]})
        assert first.status_code == 200
        assert ext.post("/api/extension/connect", headers=eheaders, json={"code": issued["code"]}).status_code == 401
        with application.state.workspace.connection() as conn:
            assert conn.execute("SELECT COUNT(*) FROM extension_pairing").fetchone()[0] == 0
            assert conn.execute("SELECT token_hash FROM extension_devices").fetchone()[0] != first.json()["token"]


def test_expired_pairing_and_replaced_code_are_rejected(application):
    with TestClient(application) as web, TestClient(application) as ext:
        register(web)
        old = web.post("/api/browser/pairing", headers=headers(web), json={}).json()["code"]
        new = web.post("/api/browser/pairing", headers=headers(web), json={}).json()["code"]
        with application.state.workspace.connection(write=True) as conn:
            conn.execute("UPDATE extension_pairing SET expires_at=?", (time.time() - 1,))
        for code in (old, new):
            assert ext.post("/api/extension/connect", headers={"X-PhishLens-Extension": EXTENSION}, json={"code": code}).status_code == 401


def test_simultaneous_pairing_exchange_can_only_create_one_device(application):
    with TestClient(application) as web:
        register(web)
        code = web.post("/api/browser/pairing", headers=headers(web), json={}).json()["code"]
        products = ProductStore(application.state.workspace)
        def attempt(_):
            try:
                products.connect(code, ORIGIN)
                return "connected"
            except WorkspaceError as exc:
                return exc.status
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(attempt, [1, 2]), key=str) == [401, "connected"]
        assert len(web.get("/api/browser/devices").json()["items"]) == 1


def test_extension_preflight_is_scoped_and_web_origins_cannot_exchange_codes(application):
    with TestClient(application) as web, TestClient(application) as ext:
        register(web)
        code = web.post("/api/browser/pairing", headers=headers(web), json={}).json()["code"]
        response = ext.options("/api/extension/connect", headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization, content-type, x-phishlens-extension"})
        assert response.status_code == 200 and response.headers["access-control-allow-origin"] == ORIGIN
        assert "access-control-allow-credentials" not in response.headers
        for origin in ("https://foreign.example", "null", "chrome-extension://" + "b" * 32):
            assert ext.post("/api/extension/connect", headers={"Origin": origin, "X-PhishLens-Extension": EXTENSION}, json={"code": code}).status_code == 403
        assert ext.post("/api/extension/connect", json={"code": code}).status_code == 403
        assert ext.post("/api/extension/connect", headers={"X-PhishLens-Extension": EXTENSION}, json={"code": code}).status_code == 200


def test_extension_token_has_no_web_admin_or_foreign_extension_authority(application):
    with TestClient(application) as web, TestClient(application) as ext:
        register(web)
        auth = connect(web, ext)
        response = ext.post("/api/extension/session", headers=auth, json={})
        assert response.status_code == 200 and "server-fixture-private-key" not in response.text
        for path in ("/api/admin/users", "/api/history", "/api/browser/devices"):
            assert ext.get(path, headers=auth).status_code == 401
        assert ext.post("/api/extension/admin/users", headers=auth, json={}).status_code == 404
        assert ext.post("/api/extension/session", headers={**auth, "X-PhishLens-Extension": "b" * 32, "Origin": "chrome-extension://" + "b" * 32}, json={}).status_code == 401
        assert ext.post("/api/extension/session", headers={k: v for k, v in auth.items() if k != "Origin"}, json={}).status_code == 200


def test_extension_local_analysis_preview_consent_and_shared_quota(application):
    with TestClient(application) as web, TestClient(application) as ext:
        register(web)
        auth = connect(web, ext)
        preview = ext.post("/api/extension/preview", headers=auth, json={"mode": "text", "text": "private@example.org hãy gửi mã OTP"})
        assert preview.status_code == 200 and "private@example.org" not in preview.text
        payload = {"mode": "text", "text": "Hãy gửi mã OTP https://example.org", "use_llm": False}
        local = ext.post("/api/extension/analyze", headers=auth, json=payload)
        assert local.status_code == 200 and local.json()["llm"]["status"] == "disabled"
        assert web.get("/api/history").json()["total"] == 1
        payload["use_llm"] = True
        assert ext.post("/api/extension/analyze", headers=auth, json=payload).status_code == 422
        assert web.get("/api/dashboard").json()["ai_used_24h"] == 0
        payload.update(consent=True, llm_text=payload["text"])
        assert ext.post("/api/extension/analyze", headers=auth, json=payload).status_code == 200
        assert analyze(web).status_code == 200
        assert ext.post("/api/extension/analyze", headers=auth, json=payload).status_code == 429
        assert ext.post("/api/extension/analyze", headers=auth, json={**payload, "api_key": "never-echo"}).status_code == 422


@pytest.mark.parametrize("action", ["logout", "password", "revoke", "expire", "suspend"])
def test_extension_is_revoked_with_session_password_or_user_state(application, action):
    with TestClient(application) as web, TestClient(application) as ext:
        user = register(web)["user"]
        auth = connect(web, ext)
        if action == "logout":
            web.post("/api/auth/logout", headers=headers(web))
        elif action == "password":
            web.post("/api/auth/password", headers=headers(web), json={"current_password": PASSWORD, "new_password": PASSWORD + "new"})
        elif action == "revoke":
            identity = web.get("/api/browser/devices").json()["items"][0]["id"]
            web.delete("/api/browser/devices/" + identity, headers=headers(web))
        else:
            with application.state.workspace.connection(write=True) as conn:
                if action == "expire": conn.execute("UPDATE sessions SET expires_at=?", (time.time() - 1,))
                else: conn.execute("UPDATE users SET active=0 WHERE id=?", (user["id"],))
        assert ext.post("/api/extension/session", headers=auth, json={}).status_code == 401


def test_device_list_and_revocation_are_owned(application):
    with TestClient(application) as alice, TestClient(application) as bob, TestClient(application) as ext:
        register(alice); register(bob, "bob@example.org"); connect(alice, ext)
        identity = alice.get("/api/browser/devices").json()["items"][0]["id"]
        assert bob.get("/api/browser/devices").json()["items"] == []
        assert bob.delete("/api/browser/devices/" + identity, headers=headers(bob)).status_code == 404


def test_feedback_default_shares_no_text_title_private_note_or_identity(application):
    with TestClient(application) as admin, TestClient(application) as user:
        register(admin); register(user, "member@example.org")
        record = analyze(user, text="https://example.org/?secret=do-not-share", use_llm=False, save_content=True).json()["history"]["id"]
        user.patch("/api/history/" + record, headers=headers(user), json={"title": "private-title", "note": "private-note"})
        response = user.post("/api/feedback", headers=headers(user), json={"history_id": record, "kind": "false_alarm", "comment": "Liên hệ private@example.org"})
        assert response.status_code == 200
        serialized = admin.get("/api/admin/feedback").text
        for value in ("do-not-share", "private-title", "private-note", "private@example.org", "member@example.org"):
            assert value not in serialized
        assert "[EMAIL]" in serialized and '"status":"pending"' in serialized
        assert user.get("/api/admin/feedback").status_code == 403


def test_feedback_sharing_is_opt_in_and_requires_owned_saved_content(application):
    with TestClient(application) as admin, TestClient(application) as user:
        register(admin); register(user, "member@example.org")
        bare = analyze(user, use_llm=False).json()["history"]["id"]
        assert user.post("/api/feedback", headers=headers(user), json={"history_id": bare, "kind": "unclear", "share_content": True}).status_code == 400
        record = analyze(user, text="Hãy gửi mã OTP secret.person@example.org", use_llm=False, save_content=True).json()["history"]["id"]
        payload = {"history_id": record, "kind": "missed_risk", "share_content": True}
        assert admin.post("/api/feedback", headers=headers(admin), json=payload).status_code == 404
        assert user.post("/api/feedback", headers=headers(user), json=payload).status_code == 200
        shared = admin.get("/api/admin/feedback").json()["items"][0]["shared_snapshot"]["result"]
        assert "secret.person@example.org" not in json.dumps(shared) and "[EMAIL]" in shared["approved_text"]
        assert user.post("/api/feedback", headers=headers(user), json=payload).status_code == 409


def test_feedback_review_is_admin_only_visible_to_owner_and_deletable(application):
    with TestClient(application) as admin, TestClient(application) as alice, TestClient(application) as bob:
        register(admin); register(alice, "alice@example.org"); register(bob, "bob@example.org")
        record = analyze(alice, use_llm=False).json()["history"]["id"]
        identity = alice.post("/api/feedback", headers=headers(alice), json={"history_id": record, "kind": "unclear"}).json()["id"]
        assert bob.get("/api/feedback").json()["total"] == 0
        assert bob.delete("/api/feedback/" + identity, headers=headers(bob)).status_code == 404
        assert alice.patch("/api/admin/feedback/" + identity, headers=headers(alice), json={"status": "reviewed"}).status_code == 403
        assert admin.patch("/api/admin/feedback/" + identity, headers=headers(admin), json={"status": "reviewed", "review_note": "Đã xem xét"}).status_code == 200
        assert alice.get("/api/feedback").json()["items"][0]["review_note"] == "Đã xem xét"
        assert admin.get("/api/admin/feedback?status=pending").json()["total"] == 0
        assert alice.delete("/api/feedback/" + identity, headers=headers(alice)).status_code == 200
        assert admin.get("/api/admin/feedback").json()["total"] == 0


def test_deleting_history_also_removes_shared_feedback_and_data_migration_is_repeatable(application):
    with TestClient(application) as client:
        register(client)
        record = analyze(client, use_llm=False, save_content=True).json()["history"]["id"]
        client.post("/api/feedback", headers=headers(client), json={"history_id": record, "kind": "other", "share_content": True})
        application.state.workspace.initialize()
        assert client.get("/api/feedback").json()["total"] == 1
        client.delete("/api/history/" + record, headers=headers(client))
        assert client.get("/api/feedback").json()["total"] == 0


def test_extension_zip_contains_only_allowlisted_assets_and_health_exposes_no_accounts(application):
    with TestClient(application) as client:
        health = client.get("/api/health")
        assert health.status_code == 200 and "browser_extension" in health.json()["features"]
        assert "user" not in health.text and "endpoint" not in health.text
        assert client.get("/api/browser/download").status_code == 200
        register(client)
        response = client.get("/api/browser/download")
        assert response.status_code == 200
        with zipfile.ZipFile(BytesIO(response.content)) as archive:
            assert "manifest.json" in archive.namelist() and "images.js" in archive.namelist()
            manifest = json.loads(archive.read("manifest.json"))
            assert manifest["manifest_version"] == 3 and "<all_urls>" not in manifest["host_permissions"]
            assert manifest["optional_host_permissions"] == ["<all_urls>"]
            assert not manifest.get("content_scripts")
            assert {"region.js", "region-capture.js", "floating.js"} <= set(archive.namelist())
            assert not any(".env" in name or "sqlite" in name or ".." in name for name in archive.namelist())


def remembered(web, ext):
    code = web.post("/api/browser/pairing", headers=headers(web), json={}).json()["code"]
    response = ext.post("/api/extension/connect", headers={"X-PhishLens-Extension": EXTENSION, "Origin": ORIGIN}, json={"code": code, "remember": True})
    assert response.status_code == 200
    data = response.json()
    assert data["remember"] is True and abs(data["expires_at"] - time.time() - 30 * 86400) < 5
    return {"X-PhishLens-Extension": EXTENSION, "Origin": ORIGIN, "Authorization": "Bearer " + data["token"]}, data


@pytest.mark.parametrize("action", ["logout", "expire_session", "restart_store"])
def test_remembered_device_survives_web_session_end_and_store_restart(application, action):
    with TestClient(application) as web, TestClient(application) as ext:
        register(web)
        auth, data = remembered(web, ext)
        if action == "logout":
            assert web.post("/api/auth/logout", headers=headers(web)).status_code == 200
        elif action == "expire_session":
            with application.state.workspace.connection(write=True) as conn:
                conn.execute("UPDATE sessions SET expires_at=?", (time.time() - 1,))
        else:
            application.state.workspace.initialize()
            products = ProductStore(application.state.workspace)
            assert products.extension_user(data["token"], ORIGIN)
        assert ext.post("/api/extension/session", headers=auth, json={}).status_code == 200
        with application.state.workspace.connection() as conn:
            assert conn.execute("SELECT token_hash FROM remembered_devices").fetchone()[0] != data["token"]


@pytest.mark.parametrize("action", ["password", "revoke", "expire", "suspend", "disconnect"])
def test_remembered_device_revocation_limits_and_origin_are_enforced(application, action):
    with TestClient(application) as web, TestClient(application) as ext, TestClient(application) as bob:
        admin = register(bob, "bob@example.org")["user"]
        user = register(web)["user"]
        auth, data = remembered(web, ext)
        assert bob.delete("/api/browser/devices/" + data["id"], headers=headers(bob)).status_code == 404
        assert web.get("/api/browser/devices").json()["items"][0]["remembered"] == 1
        foreign = {**auth, "X-PhishLens-Extension": "b" * 32, "Origin": "chrome-extension://" + "b" * 32}
        assert ext.post("/api/extension/session", headers=foreign, json={}).status_code == 401
        if action == "password":
            assert web.post("/api/auth/password", headers=headers(web), json={"current_password": PASSWORD, "new_password": PASSWORD + "new"}).status_code == 200
        elif action == "revoke":
            assert web.delete("/api/browser/devices/" + data["id"], headers=headers(web)).status_code == 200
        elif action == "disconnect":
            assert ext.post("/api/extension/disconnect", headers=auth, json={}).status_code == 200
        elif action == "expire":
            with application.state.workspace.connection(write=True) as conn:
                conn.execute("UPDATE remembered_devices SET expires_at=?", (time.time() - 1,))
        else:
            application.state.workspace.update_user(admin["id"], user["id"], {"active": False})
        assert ext.post("/api/extension/session", headers=auth, json={}).status_code == 401


def test_remembered_device_limit_preserves_unused_code_and_no_plaintext_tokens(application):
    with TestClient(application) as web, TestClient(application) as ext:
        register(web)
        for _ in range(10):
            remembered(web, ext)
        code = web.post("/api/browser/pairing", headers=headers(web), json={}).json()["code"]
        response = ext.post("/api/extension/connect", headers={"X-PhishLens-Extension": EXTENSION}, json={"code": code, "remember": True})
        assert response.status_code == 409
        identity = web.get("/api/browser/devices").json()["items"][0]["id"]
        web.delete("/api/browser/devices/" + identity, headers=headers(web))
        assert ext.post("/api/extension/connect", headers={"X-PhishLens-Extension": EXTENSION}, json={"code": code, "remember": True}).status_code == 200


def test_v2_database_migration_preserves_accounts_history_and_session_devices(application):
    with TestClient(application) as web, TestClient(application) as ext:
        user = register(web)["user"]
        auth = connect(web, ext)
        history = analyze(web, use_llm=False).json()["history"]["id"]
        with application.state.workspace.connection(write=True) as conn:
            conn.execute("DROP TABLE remembered_devices")
            conn.execute("PRAGMA user_version=2")
        application.state.workspace.initialize()
        assert web.get("/api/auth/session").json()["user"]["id"] == user["id"]
        assert web.get("/api/history/" + history).status_code == 200
        assert ext.post("/api/extension/session", headers=auth, json={}).status_code == 200
        remembered(web, ext)
        with application.state.workspace.connection() as conn:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
            assert conn.execute("SELECT COUNT(*) FROM extension_devices").fetchone()[0] == 1
            assert conn.execute("SELECT COUNT(*) FROM remembered_devices").fetchone()[0] == 1
