"""Guest web and MV3 extension, real local models, isolated database, mocked AI."""
import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import socket
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    import httpx
    import uvicorn
    from playwright.sync_api import sync_playwright, expect
    from app.api.workspace import create_app
    from app.core.settings import Settings
    from app.services.workspace import WorkspaceSettings
    from tests.api.test_focused_app import decision, packet

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(); args.out.mkdir(parents=True, exist_ok=False)
    calls, requests, errors, checks = [], [], [], []

    def provider(request):
        from tests.api.test_evidence_explanation import NOTE
        from tests.api.test_focused_app import packet as explanation_packet
        calls.append(True)
        if json.loads(request.content)["messages"][0]["content"].startswith("Viết lời giải thích ngắn"):
            return explanation_packet(NOTE)
        return packet(decision())

    app = create_app("focused", replace(Settings(), api_key="isolated-guest-fixture"), transport=httpx.MockTransport(provider),
        workspace_settings=WorkspaceSettings(database=args.out / "application/test.sqlite3"))

    @app.middleware("http")
    async def observe(request, call_next):
        requests.append(request.url.path)
        return await call_next(request)

    sock = socket.socket(); sock.bind(("127.0.0.1", 0)); base = "http://127.0.0.1:" + str(sock.getsockname()[1])
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True); thread.start()
    source = ROOT / "extensions/chromium"
    try:
        deadline = time.monotonic() + 30
        while not server.started:
            if time.monotonic() > deadline or not thread.is_alive(): raise RuntimeError("Isolated startup failed")
            time.sleep(.1)
        with sync_playwright() as runner:
            def launch():
                context = runner.chromium.launch_persistent_context(str(args.out / "browser-profile"), channel="chromium", headless=True,
                    args=[f"--disable-extensions-except={source}", f"--load-extension={source}"], viewport={"width": 1280, "height": 900})
                context.on("page", lambda page: page.on("pageerror", lambda reason: errors.append(str(reason))))
                return context

            context = launch()
            worker = context.service_workers[0] if context.service_workers else context.wait_for_event("serviceworker", timeout=15000)
            extension_url = worker.url.replace("background.js", "check.html?panel=1")
            worker.evaluate("base=>chrome.storage.local.set({base})", base)
            web = context.new_page(); web.goto(base); web.wait_for_url("**/check")
            expect(web.locator("#analyze-button")).to_be_enabled()
            expect(web.locator("[data-guest]").first).to_be_visible()
            expect(web.locator(".history-options")).to_be_hidden()
            assert web.locator('[data-workspace]:visible').count() == 0
            expect(web.locator("#service-status")).to_contain_text("Sẵn sàng")
            web.locator("#install-guide").click(); expect(web.locator("#how-dialog")).to_be_visible()
            expect(web.locator("#extension-install")).to_have_attribute("open", "")
            web.locator("#close-how").click()
            web.locator('[data-sample="normal"]').click(); expect(web.locator("#input-text")).to_have_value(__import__("re").compile(".*họp.*"))
            web.evaluate("window.scrollTo(0,0)"); web.wait_for_timeout(150)
            web.screenshot(path=str(args.out / "01_web_guest.png"))
            for width in [390,320]:
                web.set_viewport_size({"width":width,"height":844})
                assert not web.evaluate("document.documentElement.scrollWidth>innerWidth+1")
            web.screenshot(path=str(args.out / "01b_web_mobile_320.png"))
            web.set_viewport_size({"width":1280,"height":900})
            checks.append("first_use_examples_install_help_and_web_layout_fit_320px")
            web.locator("#tab-url").click(); web.locator("#input-text").fill("https://example.org/")
            web.locator("#use-llm").uncheck(); web.locator("#analyze-button").click(); expect(web.locator("#result-content")).to_be_visible()
            assert not calls
            checks.append("web_opens_directly_without_login_URL_model_works_no_account_history_controls")
            web.locator("#tab-text").click(); web.locator("#input-text").fill("Vui lòng gửi mã OTP. Email private@example.org.")
            web.locator("#use-llm").check(); web.locator("#analyze-button").click()
            expect(web.locator("#privacy-dialog")).to_be_visible(); assert not calls
            assert "private@example.org" not in web.locator("#preview-text").input_value()
            expect(web.locator("#confirm-send")).to_be_disabled()
            web.locator("#consent").check(); web.locator("#confirm-send").click()
            expect(web.locator("#ai-analysis")).to_be_visible(); assert len(calls) == 1
            checks.append("guest_web_AI_redaction_preview_consent_one_mocked_provider_call")
            expect(web.locator(".technical-details")).not_to_have_attribute("open", "")
            with web.expect_download() as downloaded: web.locator("#download-result").click()
            exported = json.loads(Path(downloaded.value.path()).read_text())
            assert exported["history"]["reason"] == "guest" and exported["llm"]["status"] == "ok"
            web.emulate_media(media="print")
            expect(web.locator("#analysis-form")).to_be_hidden(); expect(web.locator("#ai-analysis")).to_be_visible()
            web.pdf(path=str(args.out / "guest_result.pdf"))
            web.emulate_media(media="screen")
            assert (args.out / "guest_result.pdf").read_bytes().startswith(b"%PDF")
            checks.append("result_JSON_download_is_direct_print_layout_keeps_results_and_hides_form")

            page = context.new_page(); page.goto(extension_url); page.set_viewport_size({"width": 390, "height": 844})
            expect(page.locator("#connection-status")).to_contain_text("Sẵn sàng")
            assert page.locator("#pair-code").count() == 0 and page.locator("#remember-connection").count() == 0
            expect(page.locator("#guest-history-note")).to_be_hidden()
            expect(page.locator("#connection-mode")).to_have_text("Khách")
            expect(page.locator("#history-option")).to_be_hidden()
            page.screenshot(path=str(args.out / "02_extension_guest.png"), full_page=True)
            page.locator("#input-text").fill("https://example.org/"); page.locator("#analyze").click()
            expect(page.locator("#result")).to_be_visible(); assert len(calls) == 1
            assert page.locator(".result-meta").count() == 0
            checks.append("fresh_extension_auto_connects_no_code_login_or_token_local_URL_result_guest_notice")
            page.locator("#new-analysis").click(); page.locator("#tab-text").click(); page.locator("#input-text").fill("Vui lòng gửi mã OTP. Email private@example.org.")
            page.locator("#analyze").click(); expect(page.locator("#review")).to_be_visible(); assert len(calls) == 1
            assert "private@example.org" not in page.locator("#approved-text").input_value()
            page.locator("#consent").check(); page.locator("#confirm").click()
            expect(page.locator("#result")).to_be_visible(); assert len(calls) == 3
            checks.append("guest_extension_AI_keeps_preview_and_explicit_consent_no_history")
            assert "/api/browser/pairing" not in requests and "/api/extension/connect" not in requests
            assert "/api/auth/register" not in requests and "/api/auth/login" not in requests
            with app.state.workspace.connection() as conn:
                for table in ["users", "history", "sessions", "extension_devices", "remembered_devices", "ai_usage"]:
                    assert conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0] == 0
            checks.append("guest_flows_never_register_pair_or_store_users_history_sessions_or_AI_account_rows")

            page.locator("#nav-connection").click(); page.locator("#disconnect").click(); expect(page.locator("#connection-status")).to_contain_text("Đã tạm ngừng")
            page.reload(); expect(page.locator("#connection-status")).to_contain_text("Đã tạm ngừng")
            context.route(base + "/api/extension/session", lambda route: route.abort())
            page.locator("#connect").click(); expect(page.locator("#error")).to_contain_text("Chưa kết nối được")
            expect(page.locator("#analyze")).to_be_disabled()
            context.unroute(base + "/api/extension/session")
            page.locator("#connect").click(); expect(page.locator("#connection-status")).to_contain_text("Sẵn sàng")
            checks.append("manual_pause_survives_reload_service_offline_then_retry_needs_no_code_or_login")
            page.locator("#theme-toggle").click(); page.set_viewport_size({"width": 320, "height": 844})
            assert not page.evaluate("document.documentElement.scrollWidth>innerWidth+1")
            page.screenshot(path=str(args.out / "03_guest_dark_320.png"), full_page=True)
            storage = page.evaluate("() => chrome.storage.local.get(null)")
            assert storage["connection"]["guest"] and "token" not in storage["connection"]
            context.close(); context = launch()
            page = context.new_page(); page.goto(extension_url)
            expect(page.locator("#connection-status")).to_contain_text("Sẵn sàng")
            checks.append("guest_connection_restores_after_browser_restart_no_stored_authentication_token")
            web = context.new_page(); web.goto(base + "/login")
            web.locator("#continue-guest").click(); web.wait_for_url("**/check")
            web.goto(base + "/register"); web.locator("#display-name").fill("Tùy chọn tài khoản")
            web.locator("#email").fill("guest-to-member@example.org"); web.locator("#password").fill("isolated-guest-password")
            web.locator("#confirm-password").fill("isolated-guest-password"); web.locator("#auth-submit").click(); web.wait_for_url("**/dashboard")
            with app.state.workspace.connection() as conn:
                assert conn.execute("SELECT COUNT(*) FROM history").fetchone()[0] == 0
                assert conn.execute("SELECT role FROM users").fetchone()[0] == "admin"
            web.goto(base + "/check"); expect(web.locator(".history-options")).to_be_visible()
            web.locator("#tab-url").click(); web.locator("#input-text").fill("https://example.org/")
            web.locator("#use-llm").uncheck(); web.locator("#analyze-button").click(); expect(web.locator("#result-content")).to_be_visible()
            with app.state.workspace.connection() as conn: assert conn.execute("SELECT COUNT(*) FROM history").fetchone()[0] == 1
            page.reload(); expect(page.locator("#connection-status")).to_contain_text("Sẵn sàng")
            assert not errors, errors
            checks.append("optional_login_preserves_private_history_for_future_web_checks_extension_stays_guest")
            context.close()
        report = {"passed": len(checks), "checks": checks, "browser_errors": errors, "real_URL_RAG_assets": True,
            "mocked_provider_calls": len(calls), "external_provider_calls": 0, "isolated_database_and_browser_profile": True,
            "guest_registration_or_pairing_requests": 0, "guest_personal_history_rows": 0,
            "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in [*source.rglob("*.js"), source / "check.html", ROOT / "app/api/workspace.py", ROOT / "app/api/browser_extension.py", ROOT / "app/static/workspace.js", ROOT / "app/static/app.js"]}}
        (args.out / "checks.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n"); print(json.dumps(report, ensure_ascii=False))
    except Exception:
        (args.out / "failure.json").write_text(json.dumps({"browser_errors": errors, "requests": requests}, ensure_ascii=False, indent=2))
        raise
    finally:
        server.should_exit = True; thread.join(timeout=15); sock.close()


if __name__ == "__main__":
    main()
