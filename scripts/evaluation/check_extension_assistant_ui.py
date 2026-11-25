"""Exercise opt-in background URL assistance and the floating UI in Chromium.

Real extension and local account API; deterministic URL model fixture. No real
LLM, websites, personal account/profile or project database. Test manifest grants
the optional host permission up front; its native Chrome dialog is not automated.
"""
import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
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

    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(); args.out.mkdir(parents=True, exist_ok=False)
    provider_calls, analyses, predictions, checks, errors = [], [], [], [], []

    class URLFixture(FakeML):
        def predict(self, urls):
            predictions.extend(urls)
            if any("/slow/" in item for item in urls): time.sleep(.7)
            rows = super().predict(urls)
            for row in rows:
                if "/low/" in row["url"]: row.update(score=.1, risk_level="LOW")
            return rows

    def provider(request):
        provider_calls.append(True)
        raise AssertionError("Background assistant must never call a provider")

    app = create_app("focused", replace(Settings(), api_key="isolated-fixture"), transport=httpx.MockTransport(provider), model_service=URLFixture(), rag_service=OrderedRAG([]), workspace_settings=WorkspaceSettings(database=args.out / "application/test.sqlite3"))

    @app.middleware("http")
    async def observe(request, call_next):
        if request.url.path == "/api/extension/analyze":
            body = json.loads(await request.body()); analyses.append(body)
            if "/unavailable/" in body["text"]:
                from fastapi.responses import JSONResponse
                return JSONResponse({"detail": "Isolated service unavailable fixture"}, status_code=503)
        return await call_next(request)

    sock = socket.socket(); sock.bind(("127.0.0.1", 0)); base = "http://127.0.0.1:" + str(sock.getsockname()[1])
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False)); thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True); thread.start()
    source = args.out / "test-extension"; shutil.copytree(ROOT / "extensions/chromium", source)
    manifest = json.loads((source / "manifest.json").read_text()); manifest["host_permissions"].append("<all_urls>")
    (source / "manifest.json").write_text(json.dumps(manifest))
    for path in (ROOT / "extensions/chromium").rglob("*"):
        if path.is_file() and path.name != "manifest.json": assert path.read_bytes() == (source / path.relative_to(ROOT / "extensions/chromium")).read_bytes()
    report = {}
    try:
        deadline = time.monotonic() + 30
        while not server.started:
            if time.monotonic() > deadline or not thread.is_alive(): raise RuntimeError("Server startup")
            time.sleep(.1)
        with sync_playwright() as runner:
            # The shipping manifest starts without broad host access. Calling its
            # configuration handler cannot bypass Chrome's optional permission.
            production = ROOT / "extensions/chromium"
            guard = runner.chromium.launch_persistent_context(str(args.out / "permission-profile"), channel="chromium", headless=True,
                args=[f"--disable-extensions-except={production}", f"--load-extension={production}"])
            first_worker = guard.service_workers[0] if guard.service_workers else guard.wait_for_event("serviceworker", timeout=15000)
            first_worker.evaluate("() => chrome.storage.local.set({autoConnectDisabled:true})")
            guard_page = guard.new_page(); guard_page.goto(first_worker.url.replace("background.js", "check.html"))
            denied = guard_page.evaluate("() => chrome.runtime.sendMessage({type:'CONFIGURE_ASSISTANT',key:'autoCheckEnabled',enabled:true})")
            assert denied.get("error") and not first_worker.evaluate("async () => (await chrome.storage.local.get('autoCheckEnabled')).autoCheckEnabled")
            assert not analyses; guard.close()
            checks.append("shipping_manifest_has_no_broad_host_access_configuration_cannot_bypass_permission")
            context = runner.chromium.launch_persistent_context(str(args.out / "browser-profile"), channel="chromium", headless=True, args=[f"--disable-extensions-except={source.resolve()}", f"--load-extension={source.resolve()}"], viewport={"width": 1200, "height": 900})
            context.on("page", lambda page: page.on("pageerror", lambda reason: errors.append(str(reason))))
            # A synthetic page is fulfilled in-browser; its external URL is never visited.
            context.route("https://shop.example/**", lambda route: route.fulfill(content_type="text/html", body='<!doctype html><html><meta charset="utf-8"><title>Trang minh họa</title><body><h1>Trang minh họa mua sắm</h1><p id="private">PRIVATE-PAGE-CONTENT-NEVER-SENT</p></body></html>'))
            worker = context.service_workers[0] if context.service_workers else context.wait_for_event("serviceworker", timeout=15000)
            extension_id = worker.url.split("/")[2]
            web = context.new_page(); web.goto(base + "/check")
            worker.evaluate("base => chrome.storage.local.set({base})", base)
            panel = context.new_page(); panel.goto(f"chrome-extension://{extension_id}/check.html?panel=1"); expect(panel.locator("#connection-status")).to_contain_text("Sẵn sàng")
            panel.set_viewport_size({"width": 390, "height": 844}); panel.screenshot(path=str(args.out / "01_connection_light.png"), full_page=True)

            expect(panel.locator("#intro")).to_be_visible(); expect(panel.locator("#toast")).to_be_hidden()
            panel.screenshot(path=str(args.out / "02_home_light.png"), full_page=True)
            target = context.new_page(); target.goto("https://shop.example/high/start?token=fixture-secret"); target.bring_to_front()
            assert not analyses and not provider_calls
            panel.locator("#nav-assistant").click(); expect(panel.locator("#assistant-screen")).to_be_visible()
            panel.locator("#floating-enabled").check(); expect(target.locator("[data-phishlens-dock]")).to_be_visible()
            assert not analyses
            checks.append("new_navigation_onboarding_floating_opt_in_does_not_analyze_page_or_call_AI")
            panel.locator("#auto-check-enabled").check()
            panel.wait_for_function("() => document.querySelector('#page-indicator').classList.contains('HIGH')", timeout=15000)
            assert len(analyses) == 1 and len(predictions) == 1 and not provider_calls
            assert analyses[0]["use_llm"] is False and analyses[0]["save_history"] is False and analyses[0]["save_content"] is False and analyses[0]["use_rag"] is False
            assert "PRIVATE-PAGE-CONTENT" not in json.dumps(analyses)
            with app.state.workspace.connection() as conn: assert conn.execute("SELECT COUNT(*) FROM history").fetchone()[0] == 0
            panel.screenshot(path=str(args.out / "03_assistant_enabled_light.png"), full_page=True)
            target.screenshot(path=str(args.out / "04_contextual_URL_warning.png"))
            checks.append("opt_in_automatic_URL_check_calls_real_local_API_without_AI_DOM_or_history")
            # A content helper can request only a limited public state, not credentials.
            tab_id = worker.evaluate("async () => (await chrome.tabs.query({active:true,lastFocusedWindow:true}))[0].id")
            public_state = worker.evaluate("async id => (await chrome.scripting.executeScript({target:{tabId:id},func:()=>chrome.runtime.sendMessage({type:'GET_ASSISTANT'})}))[0].result", tab_id)
            assert public_state["page"]["risk"] == "HIGH" and "token" not in json.dumps(public_state) and "fixture-secret" not in json.dumps(public_state)
            stored = panel.evaluate("() => chrome.storage.session.get(null)")
            records = {key: value for key, value in stored.items() if key.startswith("assistant-tab-")}
            assert records and "fixture-secret" not in json.dumps(records) and "https://" not in json.dumps(records)
            assert worker.evaluate("id => chrome.action.getBadgeText({tabId:id})", tab_id) == "!"
            checks.append("HIGH_badge_and_helper_public_state_reveal_no_credentials_URL_queries_or_DOM")
            web.bring_to_front(); web.wait_for_timeout(150); assert len(analyses) == 1
            target.bring_to_front()
            checks.append("own_local_application_is_excluded_from_passive_URL_checks")
            # Re-activation must reuse the recent score, even while the panel is closed.
            panel.close(); target.bring_to_front(); context.new_page().close(); target.bring_to_front()
            target.wait_for_timeout(250); assert len(analyses) == 1
            target.goto("https://shop.example/low/next"); expect(target.locator("[data-phishlens-dock]")).to_be_visible()
            target.wait_for_function("() => document.readyState==='complete'")
            deadline = time.monotonic() + 10
            while len(predictions) < 2 and time.monotonic() < deadline: target.wait_for_timeout(50)
            assert len(analyses) == 2 and not provider_calls
            checks.append("panel_closed_navigation_still_checks_URL_recent_page_score_is_cached")
            before = len(analyses)
            target.evaluate("history.pushState({}, '', '/high/spa-route')")
            deadline = time.monotonic() + 10
            while len(analyses) == before and time.monotonic() < deadline: target.wait_for_timeout(50)
            deadline = time.monotonic() + 10
            while worker.evaluate("id=>chrome.action.getBadgeText({tabId:id})", tab_id) != "!" and time.monotonic() < deadline: target.wait_for_timeout(50)
            assert len(analyses) == before + 1 and analyses[-1]["text"].endswith("/high/spa-route")
            assert worker.evaluate("id=>chrome.action.getBadgeText({tabId:id})", tab_id) == "!"
            checks.append("single_page_application_URL_change_refreshes_score_without_page_reload")
            before = len(analyses)
            worker.evaluate("async () => {await chrome.storage.local.set({assistantPausedUntil:Date.now()+3600000});await PhishLensAssistant.refresh();}")
            assert worker.evaluate("id=>chrome.action.getBadgeText({tabId:id})", tab_id) == ""
            worker.evaluate("async id => {await chrome.storage.local.remove('assistantPausedUntil');await PhishLensAssistant.check(await chrome.tabs.get(id));}", tab_id)
            assert worker.evaluate("id=>chrome.action.getBadgeText({tabId:id})", tab_id) == "!" and len(analyses) == before
            checks.append("resume_restores_cached_warning_badge_without_duplicate_URL_request")
            # Floating main button is draggable. Its menu works with keyboard arrows.
            dock = target.locator("[data-phishlens-dock]"); box = dock.bounding_box()
            target.mouse.move(box["x"] + 22, box["y"] + 22); target.mouse.down(); target.mouse.move(48, 310, steps=12); target.mouse.up()
            target.wait_for_timeout(100)
            moved = dock.bounding_box(); assert moved["x"] < 40 and moved["y"] < box["y"] - 30
            assert not target.locator("[data-phishlens-region]").count()
            assert worker.evaluate("() => chrome.storage.local.get('dockPosition')")["dockPosition"]["edge"] == "left"
            target.mouse.click(moved["x"] + moved["width"] - 14, moved["y"] + 25)
            target.screenshot(path=str(args.out / "05_draggable_floating_menu.png"))
            # Initial focus is item 1; down four selects pause after the new full-capture item.
            target.keyboard.press("ArrowDown"); target.keyboard.press("ArrowDown"); target.keyboard.press("ArrowDown"); target.keyboard.press("ArrowDown"); target.keyboard.press("Enter")
            target.wait_for_timeout(100)
            assert worker.evaluate("() => chrome.storage.local.get('assistantPausedUntil')")["assistantPausedUntil"] > time.time() * 1000
            alarm = worker.evaluate("() => chrome.alarms.get('phishlens-resume')"); assert alarm and not alarm.get("periodInMinutes")
            before = len(analyses); target.goto("https://shop.example/high/paused"); expect(target.locator("[data-phishlens-dock]")).to_be_visible(); target.wait_for_timeout(200); assert len(analyses) == before
            checks.append("drag_position_persists_without_capture_menu_keyboard_pause_uses_one_shot_alarm")
            # Resume via settings, then hide this hostname using the floating menu.
            panel = context.new_page(); panel.goto(f"chrome-extension://{extension_id}/check.html?panel=1"); expect(panel.locator("#connection-status")).to_contain_text("Sẵn sàng")
            panel.locator("#nav-assistant").click(); expect(panel.locator("#pause-assistant")).to_contain_text("Bật lại")
            target.bring_to_front(); panel.locator("#pause-assistant").click(); expect(panel.locator("#assistant-status-title")).to_contain_text("Tự kiểm URL")
            target.wait_for_timeout(250)
            box = target.locator("[data-phishlens-dock]").bounding_box(); target.mouse.click(box["x"] + box["width"] - 14, box["y"] + 25)
            for _ in range(5): target.keyboard.press("ArrowDown")
            target.keyboard.press("Enter"); expect(target.locator("[data-phishlens-dock]")).to_be_hidden()
            before = len(analyses); target.goto("https://shop.example/high/hidden-site"); target.wait_for_timeout(200); assert len(analyses) == before
            hidden = worker.evaluate("() => chrome.storage.local.get('hiddenSites')")["hiddenSites"]; assert len(hidden) == 1 and len(hidden[0]) == 64 and "shop.example" not in json.dumps(hidden)
            panel.locator("#reset-hidden-sites").click(); expect(target.locator("[data-phishlens-dock]")).to_be_visible()
            checks.append("resume_and_per_site_hide_suppress_checks_reset_restores_helper_hash_only_preference")
            target.goto("https://shop.example/unavailable/page"); target.wait_for_timeout(250)
            unavailable = worker.evaluate("async id => PhishLensAssistant.state(await chrome.tabs.get(id))", tab_id)
            assert unavailable["page"]["status"] == "unavailable" and not unavailable["page"].get("risk")
            assert worker.evaluate("id => chrome.action.getBadgeText({tabId:id})", tab_id) == ""
            checks.append("service_failure_is_unavailable_not_LOW_or_safe_no_misleading_badge")
            # Pausing during an in-flight request must suppress its late warning.
            before = len(analyses); target.goto("https://shop.example/slow/high/pending")
            deadline = time.monotonic() + 5
            while len(analyses) == before and time.monotonic() < deadline: target.wait_for_timeout(20)
            panel.locator("#pause-assistant").click(); expect(panel.locator("#assistant-status-title")).to_contain_text("tạm nghỉ")
            target.wait_for_timeout(1000)
            assert worker.evaluate("id=>chrome.action.getBadgeText({tabId:id})", tab_id) == ""
            checks.append("pause_aborts_in_flight_request_and_prevents_late_badge_or_warning")
            panel.locator("#auto-check-enabled").uncheck(); panel.locator("#pause-assistant").click()
            before = len(analyses); target.goto("https://shop.example/high/disabled"); target.wait_for_timeout(200); assert len(analyses) == before
            panel.locator("#theme-toggle").click(); panel.set_viewport_size({"width": 320, "height": 844}); assert not panel.evaluate("document.documentElement.scrollWidth > innerWidth+1")
            panel.screenshot(path=str(args.out / "06_assistant_dark_320.png"), full_page=True)
            checks.append("automatic_option_off_stops_requests_settings_fit_dark_320px")
            target.goto("https://shop.example/slow/high/concurrency")
            before = len(analyses)
            concurrent = worker.evaluate("async id => {const tab=await chrome.tabs.get(id);return Promise.all(Array.from({length:8},()=>PhishLensAssistant.check(tab,true)));}", tab_id)
            assert len(analyses) == before + 1 and sum(record["status"] == "ok" for record in concurrent) == 1
            checks.append("simultaneous_manual_focus_and_navigation_work_is_deduplicated_per_tab")
            assert not errors, errors
            with app.state.workspace.connection() as conn:
                assert conn.execute("SELECT COUNT(*) FROM history").fetchone()[0] == 0
                assert conn.execute("SELECT COUNT(*) FROM ai_usage").fetchone()[0] == 0
            assert not provider_calls
            context.close()
            report = {"passed": len(checks), "checks": checks, "browser_errors": errors, "external_provider_calls": 0, "provider_calls": len(provider_calls), "local_analysis_requests": len(analyses),
                "real_account_extension_API": True, "deterministic_URL_model_fixture": True, "page_content_not_sent": True, "history_rows": 0, "AI_usage_rows": 0,
                "native_optional_permission_dialog_automated": False, "test_manifest_pregrants_optional_hosts": True,
                "source_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in (ROOT / "extensions/chromium").rglob("*") if path.is_file()}}
    finally:
        server.should_exit = True; thread.join(timeout=15); sock.close()
    (args.out / "checks.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n"); print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
