"""Direct on-page region selection, real screenshots/OCR and guest reconnection.

Uses an isolated account/browser and a mocked provider. --pregrant-hosts makes a
test-only manifest copy grant all_urls up front: headless Chromium cannot accept
its native optional-permission dialog. All shipped JS is copied byte for byte.
The report explicitly distinguishes this from testing that native dialog.
"""
import argparse
import base64
from dataclasses import replace
import hashlib
from io import BytesIO
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
    from PIL import Image, ImageDraw, ImageFont
    from playwright.sync_api import sync_playwright, expect
    from fastapi.responses import HTMLResponse
    import uvicorn
    from app.api.workspace import create_app
    from app.core.settings import Settings
    from app.services.workspace import WorkspaceSettings

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pregrant-hosts", action="store_true")
    parser.add_argument("--headed", action="store_true", help="Use a real browser window (DISPLAY/Xvfb required on Linux).")
    args = parser.parse_args(); args.out.mkdir(parents=True, exist_ok=False)
    calls, errors, checks, ocr_calls = [], [], [], []
    image = Image.new("RGB", (900, 290), "white"); draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 30)
    for index, line in enumerate(["THÔNG BÁO XÁC MINH TÀI KHOẢN", "Vui lòng gửi mã OTP cho nhân viên.", "https://xac-minh.example/verify"]):
        draw.text((30, 32 + index * 76), line, fill="#172236", font=font)
    encoded = BytesIO(); image.save(encoded, format="PNG")
    html = '<!doctype html><html lang="vi"><meta charset="utf-8"><title>Trang demo khoanh vùng</title><body style="margin:0;background:#eaf0f6;font:18px system-ui;min-height:1800px"><div style="padding:28px"><h2>Trang minh họa · chọn tin nhắn bên dưới</h2><p>Phần ngoài vùng chọn: OUTSIDE-PRIVATE-CONTENT</p><img id="target" style="display:block;width:min(800px,calc(100vw - 64px));height:auto;border-radius:12px" src="data:image/png;base64,' + base64.b64encode(encoded.getvalue()).decode() + '"><p>Nội dung ngoài vùng sẽ không được gửi OCR.</p></div></body></html>'

    def provider(request):
        from tests.api.test_evidence_explanation import NOTE
        from tests.api.test_focused_app import packet as explanation_packet
        calls.append(json.loads(request.content))
        if json.loads(request.content)["messages"][0]["content"].startswith("Viết lời giải thích ngắn"):
            return explanation_packet(NOTE)
        answer = {"risk_level": "HIGH", "context_kind": "scam_request", "reason_code": "secret_request", "quotes": ["gửi mã OTP"], "missing_context": []}
        return httpx.Response(200, json={"model": "region-ui-fixture", "usage": {"total_tokens": 25}, "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(answer)}}]})
    app = create_app("focused", replace(Settings(), api_key="isolated-fixture"), transport=httpx.MockTransport(provider), workspace_settings=WorkspaceSettings(database=args.out / "application/test.sqlite3"))

    @app.get("/region-fixture")
    async def fixture():
        return HTMLResponse(html)

    sock = socket.socket(); sock.bind(("127.0.0.1", 0)); base = "http://127.0.0.1:" + str(sock.getsockname()[1])
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False)); thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True); thread.start()
    source = ROOT / "extensions/chromium"
    if args.pregrant_hosts:
        test_source = args.out / "test-extension"; shutil.copytree(source, test_source)
        manifest = json.loads((test_source / "manifest.json").read_text()); manifest["host_permissions"].append("<all_urls>")
        (test_source / "manifest.json").write_text(json.dumps(manifest))
        for item in source.rglob("*"):
            if item.is_file() and item.name != "manifest.json":
                assert item.read_bytes() == (test_source / item.relative_to(source)).read_bytes()
        source = test_source.resolve()
    report = {}
    try:
        deadline = time.monotonic() + 30
        while not server.started:
            if time.monotonic() > deadline or not thread.is_alive(): raise RuntimeError("Server startup")
            time.sleep(.1)
        with sync_playwright() as runner:
            def launch(restored_id=None):
                context = runner.chromium.launch_persistent_context(str(args.out / "browser-profile"), channel="chromium", headless=not args.headed,
                    args=[f"--disable-extensions-except={source}", f"--load-extension={source}", "--window-size=1440,1000", "--force-device-scale-factor=1.5"], no_viewport=True)
                context.on("page", lambda page: page.on("pageerror", lambda reason: errors.append(str(reason))))
                context.on("response", lambda response: ocr_calls.append(response) if response.url.endswith("/api/extension/image-text") else None)
                if restored_id:
                    # MV3 may stay asleep on headless restart until a page sends a message.
                    context.new_page().goto(f"chrome-extension://{restored_id}/check.html?panel=1")
                worker = context.service_workers[0] if context.service_workers else context.wait_for_event("serviceworker", timeout=15000)
                return context, worker, worker.url.split("/")[2]
            context, worker, extension_id = launch()
            # Parse every shipped JS file, including the helpers, in Chromium's JS engine.
            parser_page = context.new_page()
            for path in (ROOT / "extensions/chromium").glob("*.js"):
                parser_page.evaluate("source => { new Function(source); }", path.read_text())
            parser_page.close()
            web = context.new_page(); web.goto(base + "/check")
            worker.evaluate("base => chrome.storage.local.set({base})", base)
            panel = context.new_page(); panel.goto(f"chrome-extension://{extension_id}/check.html?panel=1")
            expect(panel.locator("#connection-status")).to_contain_text("Sẵn sàng", timeout=60000)
            assert panel.evaluate("() => chrome.storage.local.get('connection')")["connection"]["guest"]
            assert "connection" not in panel.evaluate("() => chrome.storage.session.get(null)")
            panel.screenshot(path=str(args.out / "01_region_home_light.png"), full_page=True)
            if args.pregrant_hosts:
                panel.locator("#nav-assistant").click()
                panel.locator("#floating-enabled").check()
                expect(panel.locator("#floating-note")).to_contain_text("Nút ở góc trang")
                panel.locator("#nav-check").click()
            context.route(base + "/region-fixture", lambda route: route.fulfill(content_type="text/html", body=html))
            target = context.new_page(); target.goto(base + "/region-fixture"); target.bring_to_front()
            target.evaluate("""() => {
                Object.assign(document.body.style,{margin:'0',background:'#eaf0f6',font:'18px system-ui',minHeight:'1800px'});
                document.querySelector('body>div').style.padding='28px';
                Object.assign(document.querySelector('#target').style,{display:'block',width:'min(800px,calc(100vw - 64px))',height:'auto',borderRadius:'12px'});
            }""")
            expect(target.locator("#target")).to_be_visible()
            dock = target.locator("[data-phishlens-dock]")
            expect(dock).to_be_visible()
            assert not calls and not ocr_calls
            checks.append("optional_floating_helper_idle_has_no_OCR_or_provider_calls")
            worker.evaluate("() => { globalThis.regionTrace=[]; chrome.runtime.onMessage.addListener(message => { regionTrace.push({type:message.type,reason:message.reason}); }); }")
            # Drive the panel button first: opening a second native panel beside
            # this automated extension-page harness would create two receivers.
            panel.locator("#quick-capture").click()
            box = dock.bounding_box()
            try:
                expect(target.locator("[data-phishlens-region]")).to_be_visible(timeout=10000)
            except AssertionError:
                target.screenshot(path=str(args.out / "capture_error.png"))
                print("capture_error", panel.locator("#error").inner_text(), "page_errors", errors, "trace", worker.evaluate("() => regionTrace"), "dock_bounds",box, "viewport",target.evaluate("({width:innerWidth,height:innerHeight,dpr:devicePixelRatio})"))
                raise
            tab_id = worker.evaluate("async () => (await chrome.tabs.query({active:true,lastFocusedWindow:true}))[0].id")
            job = worker.evaluate("async id => (await chrome.storage.session.get('region-job-' + id))['region-job-' + id]", tab_id)
            target.screenshot(path=str(args.out / "02_direct_page_selection.png"))
            bounds = target.locator("#target").bounding_box()
            x, y, width, height = bounds["x"], bounds["y"], bounds["width"], bounds["height"]
            target.mouse.move(x, y); target.mouse.down(); target.mouse.move(x + width, y + height, steps=15)
            target.mouse.up()
            expect(target.locator("[data-phishlens-region]")).to_have_count(0)
            try:
                expect(panel.locator("#review")).to_be_visible(timeout=30000)
            except AssertionError:
                print("review_error", panel.locator("#error").inner_text(), "trace",worker.evaluate("() => regionTrace"), "tabs",worker.evaluate("async () => (await chrome.tabs.query({})).map(t=>({id:t.id,windowId:t.windowId,active:t.active,url:t.url}))"), "viewport",target.evaluate("({width:innerWidth,height:innerHeight,dpr:devicePixelRatio})"))
                raise
            assert len(ocr_calls) == 1 and len(calls) == 0
            ocr = ocr_calls[0].json(); assert ocr_calls[0].status == 200, ocr
            assert "gửi mã OTP" in ocr["text"] and "OUTSIDE-PRIVATE-CONTENT" not in ocr["text"]
            actual_dpr = target.evaluate("devicePixelRatio")
            full = worker.evaluate("""async () => {
                const tab=(await chrome.tabs.query({active:true,lastFocusedWindow:true}))[0];
                const uri=await chrome.tabs.captureVisibleTab(tab.windowId,{format:'png'});
                const bitmap=await createImageBitmap(new Blob([Uint8Array.from(atob(uri.split(',')[1]),c=>c.charCodeAt(0))],{type:'image/png'}));
                return {width:bitmap.width,height:bitmap.height,uri};
            }""")
            (args.out / "raw_capture_fixture_only.png").write_bytes(base64.b64decode(full.pop("uri").split(",")[1]))
            viewport = target.evaluate("({width:innerWidth,height:innerHeight,dpr:devicePixelRatio})")
            print("capture_dimensions", {"css": [width, height], "reported_DPR": actual_dpr, "OCR": [ocr["width"], ocr["height"]], "full":full,"viewport":viewport})
            assert abs(ocr["width"] - round(width * full["width"] / viewport["width"])) <= 2
            assert abs(ocr["height"] - round(height * full["height"] / viewport["height"])) <= 2
            assert not ocr["image_saved"] and ocr["provider_calls"] == 0
            expect(panel.locator("#consent")).not_to_be_checked()
            panel.screenshot(path=str(args.out / "03_automatic_OCR_review.png"), full_page=True)
            checks.append("trusted_page_pointer_rectangle_real_capture_at_1_5_DPR_crop_only_OCR_auto_review_zero_AI")
            # A page helper cannot read persistent extension credentials.
            isolation = worker.evaluate("""async tabId => (await chrome.scripting.executeScript({target:{tabId},func:async () => {
                try { return {data:await chrome.storage.local.get('connection')}; } catch { return {denied:true}; }
            }}))[0].result""", tab_id)
            assert isolation.get("denied") or not isolation.get("data", {}).get("connection")
            stored = panel.evaluate("async () => ({local:await chrome.storage.local.get(null),session:await chrome.storage.session.get(null)})")
            assert set(stored["local"]) <= {"base", "theme", "connection", "floatingEnabled", "autoConnectDisabled"}
            assert not any(key.startswith("region-job-") for key in stored["session"])
            assert "data:image" not in json.dumps(stored)
            checks.append("content_script_cannot_read_trusted_storage_no_screenshot_in_storage")
            # Replay the consumed nonce from the genuine isolated content context.
            replay = worker.evaluate("""async args => (await chrome.scripting.executeScript({target:{tabId:args.id},func:async nonce => chrome.runtime.sendMessage({type:'REGION_SELECTED',nonce,rect:{x:20,y:20,width:100,height:100},viewport:{width:innerWidth,height:innerHeight,scrollX,scrollY}}),args:[args.nonce]}))[0].result""", {"id": tab_id, "nonce": job["nonce"]})
            assert "hết hạn" in replay["error"] and len(ocr_calls) == 1
            checks.append("consumed_region_nonce_replay_rejected_without_OCR_or_provider")
            panel.locator("#consent").check(); panel.locator("#confirm").click()
            expect(panel.locator("#result")).to_contain_text("Nguy cơ cao", timeout=30000)
            assert len(calls) == 2 and "data:image" not in json.dumps(calls) and "OUTSIDE-PRIVATE-CONTENT" not in json.dumps(calls)
            checks.append("explicit_consent_classification_and_explanation_text_only_AI_calls")
            panel.locator("#theme-toggle").click(); panel.set_viewport_size({"width": 320, "height": 844})
            assert not panel.evaluate("document.documentElement.scrollWidth > innerWidth + 1")
            panel.screenshot(path=str(args.out / "04_result_dark_320.png"), full_page=True)
            target.bring_to_front(); box = dock.bounding_box(); target.mouse.click(box["x"] + 22, box["y"] + 22)
            expect(target.locator("[data-phishlens-region]")).to_be_visible(); target.keyboard.press("Escape")
            expect(target.locator("[data-phishlens-region]")).to_have_count(0)
            # Cancellation message is async; use a browser assertion to wait for job cleanup.
            panel.wait_for_function("async id => !(await chrome.storage.session.get('region-job-'+id))['region-job-'+id]", arg=tab_id)
            assert len(ocr_calls) == 1 and len(calls) == 2
            checks.append("trusted_floating_button_opens_overlay_before_any_review_UI_and_Escape_cancels_without_network")
            # The existing panel's primary action also starts selection on the active web tab.
            panel.locator("#result-capture").click()
            expect(target.locator("[data-phishlens-region]")).to_be_visible(timeout=10000)
            target.evaluate("scrollTo(0,100)")
            expect(target.locator("[data-phishlens-region]")).to_have_count(0)
            expect(panel.locator("#error")).to_contain_text("trang thay đổi")
            assert len(ocr_calls) == 1 and len(calls) == 2
            checks.append("panel_primary_region_action_and_scroll_cancel_with_explanation_no_network")
            panel.on("dialog", lambda dialog: dialog.accept())
            target.evaluate("scrollTo(0,0)"); target.bring_to_front()
            # Wait for the scroll event/paint before starting a new selection;
            # a genuine scroll during selection must still cancel the crop.
            target.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
            window_count = len(worker.evaluate("() => chrome.windows.getAll()"))
            worker.evaluate("async tabId=>PhishLensCapture.start(await chrome.tabs.get(tabId))", tab_id)
            expect(target.locator("[data-phishlens-region]")).to_be_visible()
            assert len(worker.evaluate("() => chrome.windows.getAll()")) == window_count
            target.screenshot(path=str(args.out / "05_immediate_overlay_full_capture_button.png"))
            target.keyboard.press("Escape")
            expect(target.locator("[data-phishlens-region]")).to_have_count(0)
            checks.append("page_initiated_capture_displays_selector_without_opening_panel_or_window_first")
            panel.locator("#result-capture").click()
            expect(target.locator("[data-phishlens-region]")).to_be_visible()
            target.keyboard.press("a")
            expect(panel.locator("#review")).to_be_visible(timeout=30000)
            assert len(ocr_calls) == 2 and len(calls) == 2
            full_ocr = ocr_calls[-1].json()
            assert full_ocr["width"] > ocr["width"] and "OUTSIDE" in full_ocr["text"]
            panel.screenshot(path=str(args.out / "06_full_viewport_OCR_review.png"), full_page=True)
            checks.append("full_viewport_button_uses_same_local_OCR_and_explicit_AI_consent_without_auto_provider_calls")
            panel.locator("#cancel").click(); target.bring_to_front()
            worker.evaluate("async tabId=>PhishLensCapture.start(await chrome.tabs.get(tabId))", tab_id)
            expect(target.locator("[data-phishlens-region]")).to_be_visible()
            bounds = target.locator("#target").bounding_box()
            with context.expect_page() as popup:
                target.mouse.move(bounds["x"],bounds["y"]); target.mouse.down()
                target.mouse.move(bounds["x"]+bounds["width"],bounds["y"]+bounds["height"],steps=10); target.mouse.up()
            review_window = popup.value
            try:
                expect(review_window.locator("#review")).to_be_visible(timeout=30000)
            except AssertionError:
                review_window.screenshot(path=str(args.out / "popup_failure.png"), full_page=True)
                print("popup_failure", review_window.locator("#error").inner_text(), "ocr",len(ocr_calls), "calls",len(calls), "errors",errors)
                raise
            assert len(ocr_calls) == 3 and len(calls) == 2
            expect(review_window.locator("#consent")).not_to_be_checked()
            review_window.close()
            checks.append("page_initiated_selection_opens_review_only_after_capture_and_OCR_with_no_extra_click")
            # Guest reconnection survives browser restart independently of web sessions.
            with app.state.workspace.connection(write=True) as conn:
                conn.execute("UPDATE sessions SET expires_at=?", (time.time() - 1,))
            context.close(); context, worker, restored_id = launch(extension_id); assert restored_id == extension_id
            panel = context.new_page(); panel.goto(f"chrome-extension://{extension_id}/check.html?panel=1")
            expect(panel.locator("#connection-status")).to_contain_text("Sẵn sàng", timeout=30000)
            expect(panel.locator("#floating-enabled")).to_be_checked()
            checks.append("browser_restart_restores_guest_connection_without_web_session_or_code")
            panel.locator("#nav-assistant").click(); panel.locator("#floating-enabled").uncheck(); expect(panel.locator("#floating-note")).to_contain_text("Tùy chọn")
            assert not worker.evaluate("() => chrome.scripting.getRegisteredContentScripts()")
            panel.locator("#settings-toggle").click(); panel.locator("#disconnect").click()
            expect(panel.locator("#connection-status")).to_contain_text("Đã tạm ngừng")
            assert "connection" not in panel.evaluate("() => chrome.storage.local.get(null)")
            checks.append("disable_floating_unregisters_helper_disconnect_erases_guest_connection")
            assert not errors, errors
            context.close()
            report = {"passed": len(checks), "checks": checks, "browser_errors": errors, "real_on_page_pointer_selection": True, "real_captureVisibleTab": True,
                "real_vietnamese_OCR": True, "mocked_provider_calls": len(calls), "external_provider_calls": 0, "test_manifest_pregranted_optional_hosts": args.pregrant_hosts,
                "headed_browser": args.headed,
                "native_permission_dialog_automated": False, "actual_OS_toolbar_and_shortcut_not_automated": True,
                "ocr_crop": {key: ocr[key] for key in ("width", "height", "image_saved", "provider_calls")},
                "source_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in (ROOT / "extensions/chromium").rglob("*") if path.is_file()}}
    finally:
        server.should_exit = True; thread.join(timeout=15); sock.close()
    (args.out / "checks.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
