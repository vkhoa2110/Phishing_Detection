"""Load the real MV3 extension in isolated Chromium and a fresh local app.

Real URL/RAG assets, synthetic accounts, mocked provider. Never touches the user's
database or browser profile. Context-menu handlers are invoked programmatically;
this does not assert interaction with the operating system's context-menu UI.
"""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import socket
import subprocess
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

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    calls, errors, checks = [], [], []

    def provider(request):
        from tests.api.test_evidence_explanation import NOTE
        from tests.api.test_focused_app import packet as explanation_packet
        calls.append(json.loads(request.content))
        if json.loads(request.content)["messages"][0]["content"].startswith("Viết lời giải thích ngắn"):
            return explanation_packet(NOTE)
        answer = {"risk_level": "HIGH", "context_kind": "scam_request", "reason_code": "secret_request", "quotes": ["gửi mã OTP"], "missing_context": []}
        return httpx.Response(200, json={"model": "isolated-ui-fixture", "usage": {"total_tokens": 25}, "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(answer)}}]})

    app = create_app("focused", replace(Settings(), api_key="isolated-fixture-not-a-real-key"), transport=httpx.MockTransport(provider),
        workspace_settings=WorkspaceSettings(database=args.out / "application/test.sqlite3"))
    sock = socket.socket(); sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True); thread.start()
    try:
        deadline = time.monotonic() + 30
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline: raise RuntimeError("Isolated server did not start")
            time.sleep(.1)
        with sync_playwright() as runner:
            source = ROOT / "extensions/chromium"
            context = runner.chromium.launch_persistent_context(str(args.out / "browser-profile"), channel="chromium", headless=True,
                args=[f"--disable-extensions-except={source}", f"--load-extension={source}"], viewport={"width": 1440, "height": 1000})
            context.on("page", lambda page: page.on("pageerror", lambda error: errors.append(str(error))))
            worker = context.service_workers[0] if context.service_workers else context.wait_for_event("serviceworker")
            extension_id = worker.url.split("/")[2]
            assert len(extension_id) == 32
            launched = subprocess.run([sys.executable, str(ROOT / "launch.py"), "--port", str(port), "--no-browser"], capture_output=True, text=True, timeout=15)
            assert launched.returncode == 0 and "đang chạy" in launched.stdout
            checks.append("launcher_reuses_healthy_application_without_starting_duplicate_server")
            web = context.new_page(); web.goto(base + "/register", wait_until="networkidle")
            web.locator("#display-name").fill("Người thử extension"); web.locator("#email").fill("extension-ui@example.org")
            web.locator("#password").fill("isolated-extension-password"); web.locator("#confirm-password").fill("isolated-extension-password")
            web.locator("#auth-submit").click(); web.wait_for_url("**/dashboard")
            web.goto(base + "/account", wait_until="networkidle")
            issued = web.evaluate("() => PhishLensWorkspace.request('/api/browser/pairing',{method:'POST',body:{}})")
            paired = httpx.post(base + "/api/extension/connect", headers={"X-PhishLens-Extension":extension_id}, json={"code":issued["code"]}).json()
            worker.evaluate("connection=>chrome.storage.session.set({connection})", {"base":base,"token":paired["token"],"expires_at":paired["expires_at"]})
            worker.evaluate("base=>chrome.storage.local.set({base})", base)
            with web.expect_download() as download: web.get_by_role("link", name="Tải extension (.zip)").click()
            assert Path(download.value.path()).stat().st_size > 1000

            with context.expect_page() as opened:
                worker.evaluate("() => openCheck({mode: 'url', text: 'https://example.org/'})")
            extension = opened.value; extension.wait_for_load_state("domcontentloaded")
            extension.set_viewport_size({"width": 590, "height": 860})
            expect(extension.locator("#input-text")).to_have_value("https://example.org/")
            expect(extension.locator("#connection-status")).to_contain_text("Sẵn sàng", timeout=60000)
            extension.locator("#analyze").click()
            expect(extension.locator("#result")).to_contain_text("Chưa dùng AI", timeout=30000)
            assert len(calls) == 0
            extension.screenshot(path=str(args.out / "extension_local_URL.png"), full_page=True)
            persistent = extension.evaluate("() => chrome.storage.local.get(null)")
            assert set(persistent) == {"base"}
            memory = extension.evaluate("() => chrome.storage.session.get(null)")
            assert not any(key.startswith("input-") for key in memory)
            checks.append("legacy_account_connection_API_fixture_URL_history_no_AI_no_persistent_token_or_input")

            text = 'Vui lòng gửi mã OTP cho nhân viên tại https://example.org/verify. Liên hệ private.person@example.org.'
            with context.expect_page() as selected:
                worker.evaluate("text => handleContext({menuItemId: 'phishlens-selection', selectionText: text})", text)
            chosen = selected.value; chosen.wait_for_load_state("domcontentloaded")
            chosen.set_viewport_size({"width": 590, "height": 860})
            expect(chosen.locator("#connection-status")).to_contain_text("Sẵn sàng", timeout=30000)
            expect(chosen.locator("#input-text")).to_have_value(text)
            assert chosen.locator('#tab-text').get_attribute('aria-selected') == 'true'
            chosen.locator("#use-ai").check(); chosen.locator("#advanced-options summary").click(); chosen.locator("#save-content").check(); chosen.locator("#analyze").click()
            expect(chosen.locator("#review")).to_be_visible()
            assert calls == [] and "private.person@example.org" not in chosen.locator("#approved-text").input_value()
            chosen.locator("#consent").check(); chosen.locator("#approved-text").fill("Hãy gửi mã OTP. Liên hệ changed.person@example.org")
            expect(chosen.locator("#consent")).not_to_be_checked(); expect(chosen.locator("#confirm")).to_be_disabled()
            chosen.locator("#consent").check(); chosen.locator("#confirm").click()
            expect(chosen.locator("#error")).to_contain_text("xem lại")
            assert len(calls) == 0 and "changed.person@example.org" not in chosen.locator("#approved-text").input_value()
            chosen.locator("#consent").check(); chosen.locator("#confirm").click()
            expect(chosen.locator("#result")).to_contain_text("Nguy cơ cao", timeout=30000)
            assert len(calls) == 2 and "changed.person@example.org" not in json.dumps(calls)
            assert not chosen.evaluate("document.documentElement.scrollWidth > innerWidth + 1")
            chosen.screenshot(path=str(args.out / "extension_AI_fixture.png"), full_page=True)
            checks.append("selection_handler_preview_edit_reconsent_re_redaction_one_mocked_AI_call")

            with context.expect_page() as link_page:
                worker.evaluate("() => handleContext({menuItemId: 'phishlens-link', linkUrl: 'https://example.org/before-opening'})")
            link = link_page.value; expect(link.locator("#input-text")).to_have_value("https://example.org/before-opening")
            assert len(calls) == 2
            checks.append("link_context_handler_takes_target_without_opening_or_AI")

            web.goto(base + "/history", wait_until="networkidle")
            web.locator(".record-title").first.click(); expect(web.locator("#record-dialog")).to_be_visible()
            web.locator("#record-content .feedback-box summary").click()
            form = web.locator("#record-content .product-form")
            attack = '<img src=x onerror="window.productXSS=1">'
            form.locator("textarea").fill(attack); form.locator("input[type=checkbox]").check(); form.get_by_role("button", name="Gửi phản hồi", exact=True).click()
            expect(form).to_contain_text("Đã gửi")
            web.locator("#close-record").click(); web.goto(base + "/feedback", wait_until="networkidle")
            expect(web.locator(".feedback-card")).to_contain_text(attack)
            assert web.evaluate("window.productXSS || 0") == 0 and web.locator(".feedback-card img").count() == 0
            web.goto(base + "/admin", wait_until="networkidle")
            expect(web.locator("#admin-feedback .feedback-card")).to_have_count(1)
            card = web.locator("#admin-feedback .feedback-card"); card.locator("select").select_option("reviewed"); card.locator("textarea").fill("Đã xem xét phản hồi thử nghiệm.")
            card.get_by_role("button", name="Lưu xử lý", exact=True).click()
            expect(web.locator("#admin-feedback")).to_contain_text("Đã xem xét phản hồi thử nghiệm.")
            web.screenshot(path=str(args.out / "admin_feedback.png"), full_page=True)
            web.goto(base + "/feedback", wait_until="networkidle"); expect(web.locator(".feedback-card")).to_contain_text("Đã xem xét phản hồi thử nghiệm.")
            web.set_viewport_size({"width": 390, "height": 844})
            assert not web.evaluate("document.documentElement.scrollWidth > innerWidth + 1")
            web.screenshot(path=str(args.out / "mobile_feedback.png"), full_page=True)
            web.set_viewport_size({"width": 320, "height": 844})
            assert not web.evaluate("document.documentElement.scrollWidth > innerWidth + 1")
            checks.append("feedback_opt_in_XSS_literal_admin_review_owner_response_mobile")

            web.goto(base + "/account", wait_until="networkidle")
            web.get_by_role("button", name="Thu hồi kết nối", exact=True).click()
            expect(web.locator(".device-list")).to_contain_text("Chưa có extension")
            link.locator("#analyze").click(); expect(link.locator("#error")).to_contain_text("thu hồi")
            assert len(calls) == 2
            checks.append("web_revocation_immediately_blocks_existing_extension_window")
            assert not errors, errors
            context.close()
    finally:
        server.should_exit = True; thread.join(timeout=15); sock.close()
    report = {"passed": len(checks), "checks": checks, "browser_errors": errors, "real_MV3_extension": True,
        "real_local_models": True, "external_provider_calls": 0, "mocked_provider_calls": len(calls), "context_menu_handler_invoked_programmatically": True,
        "isolated_database_and_browser_profile": True}
    (args.out / "checks.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
