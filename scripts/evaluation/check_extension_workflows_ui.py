"""Exercise editing, consent, navigation and recovery in an isolated MV3 browser.

Uses synthetic inputs, a temporary database and a mocked provider. --audit-only
records the old interaction problems without treating them as passing checks.
"""
import argparse
import asyncio
import hashlib
from dataclasses import replace
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
    from tests.api.test_baseline import FakeML
    from tests.api.test_candidate_app import OrderedRAG
    from tests.api.test_focused_app import decision, packet
    from tests.api.test_evidence_explanation import NOTE

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=ROOT / "extensions/chromium")
    parser.add_argument("--audit-only", action="store_true")
    args = parser.parse_args(); args.out.mkdir(parents=True, exist_ok=False)
    checks, audit, calls, errors, attempts = [], {}, [], [], []
    fail_next, first_session = [False], [True]

    def provider(request):
        body = json.loads(request.content); calls.append(body)
        if fail_next[0]:
            fail_next[0] = False
            return httpx.Response(503, json={"error": {"message": "fixture unavailable"}})
        return packet(NOTE if body["messages"][0]["content"].startswith("Viết lời giải thích ngắn") else decision())

    app = create_app("focused", replace(Settings(), api_key="isolated-fixture"),
        transport=httpx.MockTransport(provider), model_service=FakeML(), rag_service=OrderedRAG([]),
        workspace_settings=WorkspaceSettings(database=args.out / "application/test.sqlite3"))

    @app.middleware("http")
    async def observe(request, call_next):
        if request.url.path == "/api/extension/analyze": attempts.append(True)
        if not args.audit_only and request.url.path == "/api/extension/session" and first_session[0]:
            first_session[0] = False
            await asyncio.sleep(3)
        return await call_next(request)

    sock = socket.socket(); sock.bind(("127.0.0.1", 0)); base = "http://127.0.0.1:" + str(sock.getsockname()[1])
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True); thread.start()
    try:
        deadline = time.monotonic() + 30
        while not server.started:
            if time.monotonic() > deadline: raise RuntimeError("Server startup failed")
            time.sleep(.05)
        with sync_playwright() as runner:
            context = runner.chromium.launch_persistent_context(str(args.out / "browser-profile"), channel="chromium", headless=True,
                args=[f"--disable-extensions-except={args.source.resolve()}", f"--load-extension={args.source.resolve()}"],
                viewport={"width": 400, "height": 760})
            context.on("page", lambda page: page.on("pageerror", lambda error: errors.append(str(error))))
            # Never fall back to the user's running app/provider in this test.
            context.route("http://**/*", lambda route: route.continue_() if route.request.url.startswith(base + "/") else route.abort())
            context.route("https://**/*", lambda route: route.abort())
            worker = context.service_workers[0] if context.service_workers else context.wait_for_event("serviceworker")
            worker.evaluate("base=>chrome.storage.local.set({base})", base)
            page = context.new_page(); page.goto(worker.url.replace("background.js", "check.html?panel=1"))
            expect(page.locator("#connection-status")).to_contain_text("Sẵn sàng", timeout=30000)
            page.locator("#tab-text").click(); page.locator("#input-text").fill("Hãy gửi mã OTP. https://example.org/check")
            page.screenshot(path=str(args.out / "01_editor.png"), full_page=True)
            audit["primary_action_inside_viewport"] = page.locator("#analyze").evaluate("el=>{const r=el.getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight}")
            page.locator("#use-ai").uncheck(); page.locator("#tab-url").click(); page.locator("#tab-text").click()
            audit["AI_choice_retained_across_modes"] = not page.locator("#use-ai").is_checked()
            page.locator("#use-ai").uncheck(); page.locator("#nav-connection").click()
            count = len(attempts); page.keyboard.press("Control+Enter"); page.wait_for_timeout(500)
            audit["settings_shortcut_cannot_submit_hidden_input"] = len(attempts) == count
            if args.audit_only:
                context.close()
            else:
                checks.append("cold_start_session_can_take_three_seconds_without_falling_back_to_another_server")
                assert all(audit.values()), audit
                checks.extend(audit)
                page.locator("#nav-check").click()
                for width, height in [(320, 640), (400, 760), (540, 850)]:
                    page.set_viewport_size({"width": width, "height": height})
                    assert not page.evaluate("document.documentElement.scrollWidth>innerWidth+1")
                    assert page.locator("#analyze").evaluate("el=>el.getBoundingClientRect().bottom<=innerHeight")
                    page.locator("#advanced-options").evaluate("el=>el.open=true")
                    page.locator("#include-ml").scroll_into_view_if_needed()
                    box = page.locator("#include-ml").bounding_box(); dock = page.locator("#action-dock").bounding_box()
                    assert box["y"] + box["height"] <= dock["y"]
                checks.append("primary_action_always_reachable_and_options_not_covered_at_320_400_540px")
                page.set_viewport_size({"width":400,"height":760})
                page.locator("#advanced-options").evaluate("el=>el.open=false")
                page.locator("#tab-text").click(); expect(page.locator("#input-text")).to_have_value("Hãy gửi mã OTP. https://example.org/check")
                expect(page.locator("#use-ai")).not_to_be_checked()
                page.locator("#input-text").fill("Hãy gửi mã OTP. Email private@example.org. https://example.org/check")
                page.locator("#use-ai").check(); page.locator("#analyze").click()
                expect(page.locator("#review")).to_be_visible(); expect(page.locator("#confirm")).to_be_disabled()
                assert not calls
                preview = page.locator("#approved-text").input_value(); assert "private@example.org" not in preview
                page.locator("#consent").check(); page.locator("#nav-connection").click(); page.locator("#connect").click()
                expect(page.locator("#connection-status")).to_contain_text("Sẵn sàng")
                expect(page.locator("#consent")).not_to_be_checked()
                checks.append("reconnecting_preserves_preview_but_invalidates_old_consent")
                page.locator("#nav-assistant").click(); page.locator("#nav-check").click()
                expect(page.locator("#approved-text")).to_have_value(preview)
                page.locator("#consent").check(); page.locator("#approved-text").fill(preview + " Thêm ngữ cảnh.")
                expect(page.locator("#consent")).not_to_be_checked(); expect(page.locator("#confirm")).to_be_disabled()
                page.screenshot(path=str(args.out / "01b_review.png"))
                checks.append("preview_and_edits_survive_navigation_and_every_edit_resets_consent")
                page.locator("#cancel").click(); expect(page.locator("#input-text")).to_have_value(preview + " Thêm ngữ cảnh.")
                page.locator("#analyze").click(); expect(page.locator("#review")).to_be_visible()
                expect(page.locator("#approved-text")).to_have_value(preview + " Thêm ngữ cảnh.")
                page.locator("#consent").check(); page.locator("#confirm").click()
                expect(page.locator("#result")).to_be_visible(timeout=30000)
                assert len(calls)==2
                page.screenshot(path=str(args.out / "02_result.png"))
                checks.append("review_back_preserves_edits_and_AI_runs_only_after_explicit_consent")
                page.locator("#edit-result").click(); expect(page.locator("#input-text")).not_to_have_value("")
                page.locator("#analyze").click(); page.locator("#consent").check(); fail_next[0]=True; page.locator("#confirm").click()
                expect(page.locator("#result")).to_be_visible(timeout=30000)
                assert len(calls)==3
                expect(page.locator("#result")).to_contain_text("Chưa hoàn tất")
                checks.append("provider_failure_keeps_URL_result_and_does_not_retry_automatically")
                page.locator("#new-analysis").click(); expect(page.locator("#input-text")).to_have_value("")
                expect(page.locator("#analyze")).to_be_disabled(); expect(page.locator("#approved-text")).to_have_value("")
                checks.append("new_analysis_clears_input_preview_and_result_without_carrying_consent")
                urls=[f"https://example.org/item-{i:02d}" for i in range(50)]
                page.locator("#input-text").fill("\n".join(urls)); page.locator("#use-ai").uncheck(); page.locator("#analyze").click()
                expect(page.locator("#result .url-row")).to_have_count(50)
                details=page.locator("#url-details"); details.locator("summary").click()
                page.locator("#url-search").fill("item-49"); expect(page.locator("#result .url-row:visible")).to_have_count(1)
                page.locator("#url-search").fill("not-present"); expect(page.locator("#url-empty")).to_be_visible()
                checks.append("50_URL_results_can_be_filtered_without_recomputing_or_sending_AI")
                page.locator("#edit-result").click(); page.locator("#clear-input").click(); expect(page.locator("#input-text")).to_have_value("")
                page.locator("#tab-image").click(); page.locator("#tab-text").click(); expect(page.locator("#input-text")).to_have_value("")
                expect(page.locator("#use-ai")).not_to_be_checked()
                page.locator("#tab-url").click()
                page.locator("#input-text").evaluate("el=>{const data=new DataTransfer();data.setData('text/plain','Khuyến mãi hôm nay. Hãy gửi mã OTP. https://example.org/offer');el.dispatchEvent(new ClipboardEvent('paste',{bubbles:true,cancelable:true,clipboardData:data}));}")
                expect(page.locator("#tab-text")).to_have_attribute("aria-selected","true")
                expect(page.locator("#input-text")).to_have_value("Khuyến mãi hôm nay. Hãy gửi mã OTP. https://example.org/offer")
                before = page.locator("#input-text").input_value()
                page.locator("#input-text").evaluate("el=>{const data=new DataTransfer();data.setData('text/plain','A'.repeat(8100));el.dispatchEvent(new ClipboardEvent('paste',{bubbles:true,cancelable:true,clipboardData:data}));}")
                expect(page.locator("#error")).to_contain_text("8.000")
                expect(page.locator("#input-text")).to_have_value(before)
                checks.append("pasted_email_switches_to_text_and_oversized_paste_keeps_existing_draft")
                assert not errors, errors
                checks.append("cleared_drafts_and_mode_preferences_remain_consistent")
                page.locator("#theme-toggle").click(); page.screenshot(path=str(args.out / "03_editor_dark.png"))
                context.close()
    finally:
        server.should_exit=True; thread.join(timeout=10); sock.close()
        report={"audit":audit,"passed":len(checks),"checks":checks,"browser_errors":errors,"mocked_provider_calls":len(calls),"external_provider_calls":0,"audit_only":args.audit_only,
            "source_sha256":{str(path.relative_to(args.source)):hashlib.sha256(path.read_bytes()).hexdigest() for path in args.source.rglob('*') if path.is_file()}}
        (args.out/"checks.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
        print(json.dumps(report,ensure_ascii=False))


if __name__ == "__main__": main()
