"""Real QR decoder + shipped Chromium image workflow, isolated local backend.

Images are authored QR fixtures; URL model and provider are test doubles.
No private browser profile, real message or external API is accessed.
"""
import argparse
import base64
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
    from PIL import Image
    from playwright.sync_api import sync_playwright, expect
    import uvicorn
    import zxingcpp
    from app.api.workspace import create_app
    from app.core.settings import Settings
    from app.services.image_text import ImageTextService
    from app.services.workspace import WorkspaceSettings
    from tests.api.test_baseline import FakeML
    from tests.api.test_candidate_app import OrderedRAG

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(); args.out.mkdir(parents=True, exist_ok=False)
    checks, calls, requests, errors, external = [], [], [], [], []

    def provider(request):
        calls.append(request.url.path)
        raise AssertionError("QR workflow must not call the AI provider")

    app = create_app("focused", replace(Settings(), api_key="isolated-qr-fixture"),
        transport=httpx.MockTransport(provider), model_service=FakeML(), rag_service=OrderedRAG([]),
        workspace_settings=WorkspaceSettings(database=args.out / "application/test.sqlite3"))
    reader = ImageTextService(); reader._status = {"ready": False, "qr_ready": True}
    extract_image = reader.extract
    decoded = []
    def record_image(payload, mime):
        (args.out/f"read-{len(decoded):02d}.png").write_bytes(payload)
        result = extract_image(payload, mime)
        decoded.append({"width": result["width"], "height": result["height"], "qr": result["qr"]})
        (args.out/"decoded.json").write_text(json.dumps(decoded, ensure_ascii=False, indent=2))
        return result
    reader.extract = record_image
    app.state.extension_ocr = reader

    @app.middleware("http")
    async def observe(request, next_call):
        if request.url.path == "/qr-demo":
            from fastapi.responses import HTMLResponse
            return HTMLResponse(demo_html)
        if request.url.path.endswith("/jobs/start"):
            data = await request.json(); requests.append(data["payload"])
        return await next_call(request)

    url = "https://example.org/promotion?coupon=QR_DEMO"
    def image(text, filename):
        path = args.out / filename
        Image.fromarray(zxingcpp.create_barcode(text, zxingcpp.BarcodeFormat.QRCode).to_image(scale=6)).save(path)
        return path
    qr = image(url, "qr-url.png")
    wifi = image("WIFI:T:WPA;S:Fixture;P:DO_NOT_SEND_THIS;;", "qr-wifi.png")
    markup = image('<img src=x onerror="window.QR_EXECUTED=true">', "qr-text.png")
    blank = args.out / "blank.png"; Image.new("RGB", (320, 220), "white").save(blank)
    demo_html = '<html><body style="background:white"><img style="position:absolute;left:30px;top:160px" src="data:image/png;base64,' + base64.b64encode(qr.read_bytes()).decode() + '"></body></html>'

    sock = socket.socket(); sock.bind(("127.0.0.1", 0)); base = "http://127.0.0.1:" + str(sock.getsockname()[1])
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True); thread.start()
    source = ROOT / "extensions/chromium"
    source_files = [*source.glob("*.js"), source/"check.html", source/"check.css", source/"manifest.json", ROOT/"app/services/image_text.py", ROOT/"app/services/qr_codes.py"]
    source_hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files}
    fixture_extension = args.out / "test-extension"; shutil.copytree(source, fixture_extension)
    manifest = json.loads((fixture_extension/"manifest.json").read_text())
    manifest["host_permissions"].append("<all_urls>")  # Automate capture without a toolbar user gesture.
    (fixture_extension/"manifest.json").write_text(json.dumps(manifest))
    try:
        deadline = time.monotonic() + 30
        while not server.started:
            assert time.monotonic() < deadline
            time.sleep(.05)
        with sync_playwright() as runner:
            context = runner.chromium.launch_persistent_context(str(args.out / "browser-profile"), channel="chromium", headless=True,
                args=[f"--disable-extensions-except={fixture_extension.resolve()}", f"--load-extension={fixture_extension.resolve()}"], viewport={"width": 430, "height": 900})
            def network(route):
                if route.request.url.startswith(base + "/"): route.continue_()
                else: external.append(route.request.url); route.abort()
            context.route("http://**/*", network); context.route("https://**/*", network)
            worker = context.service_workers[0] if context.service_workers else context.wait_for_event("serviceworker", timeout=15000)
            worker.evaluate("connection => chrome.storage.local.set({base:connection.base,connection})", {"base": base, "guest": True, "expires_at": time.time() + 3600})
            page = context.new_page(); page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("dialog", lambda dialog: dialog.accept())
            page.goto(worker.url.replace("background.js", "check.html?capture=1"))
            expect(page.locator("#connection-status")).to_contain_text("Sẵn sàng")

            def read(path):
                page.locator("#tab-image").click()
                page.locator("#image-file").set_input_files(path)
                expect(page.locator("#image-preview")).to_be_visible()
                expect(page.locator("#image-name")).to_contain_text(path.name)
                expect(page.locator("#read-image")).to_be_enabled()
                page.locator("#read-image").click()
                expect(page.locator("#read-image")).to_be_enabled(timeout=15000)

            read(qr)
            expect(page.locator("#image-qr")).to_be_visible()
            expect(page.locator(".image-qr-value")).to_have_text(url)
            expect(page.locator("#image-qr a")).to_have_count(0)
            assert not calls and not requests
            expect(page.locator("#text-input")).to_be_hidden()
            expect(page.locator(".analysis-options")).to_be_hidden()
            expect(page.locator("#submit-area")).to_be_hidden()
            checks.append("QR_works_without_Tesseract_and_exposes_exact_URL_without_opening_or_AI")
            page.locator("#image-qr").scroll_into_view_if_needed(); page.screenshot(path=str(args.out / "01_QR_decoded.png"))
            page.locator(".image-qr-card button").click()
            expect(page.locator("#result")).to_be_visible(timeout=15000)
            assert len(requests) == 1 and requests[0]["use_llm"] is False and requests[0]["text"] == url
            assert not calls
            checks.append("one_click_QR_URL_check_uses_local_model_and_never_enables_AI")
            page.locator("#result").scroll_into_view_if_needed(); page.screenshot(path=str(args.out / "02_QR_URL_result.png"))
            page.locator("#edit-result").click(); page.locator("#tab-image").click()
            expect(page.locator("#image-qr")).to_be_visible()
            checks.append("image_and_QR_remain_available_when_switching_back_from_URL_result")

            read(wifi)
            expect(page.locator("#image-qr")).to_be_visible()
            expect(page.locator(".image-qr-card button")).to_have_count(0)
            expect(page.locator(".image-qr-card details")).not_to_have_attribute("open", "")
            expect(page.locator("#input-text")).to_have_value("")
            assert not calls and len(requests) == 1
            checks.append("WiFi_or_other_non_URL_QR_is_collapsed_and_never_added_to_AI_input")

            read(markup)
            page.locator(".image-qr-card summary").click()
            expect(page.locator(".image-qr-value")).to_contain_text("<img")
            assert page.evaluate("window.QR_EXECUTED === undefined")
            expect(page.locator("#image-qr img")).to_have_count(0)
            checks.append("QR_HTML_is_rendered_as_literal_text_without_DOM_execution")
            for width in (320, 430, 600):
                page.set_viewport_size({"width": width, "height": 900})
                assert not page.evaluate("document.documentElement.scrollWidth > innerWidth + 1")
            page.locator("#theme-toggle").click()
            page.locator("#image-qr").scroll_into_view_if_needed(); page.screenshot(path=str(args.out / "03_QR_data_dark.png"))
            checks.append("QR_layout_wraps_in_dark_theme_and_320_430_600px")

            page.locator("#remove-image").click()
            expect(page.locator("#image-qr")).to_be_hidden()
            expect(page.locator("#image-qr-codes")).to_be_empty()
            checks.append("removing_image_removes_decoded_payloads_from_UI")
            read(blank)
            expect(page.locator("#image-qr")).to_be_hidden()
            expect(page.locator("#result")).to_be_hidden()
            expect(page.locator("#analyze")).to_be_disabled()
            checks.append("blank_image_does_not_reuse_old_URL_or_invent_LOW_result")

            # Partial failure must preserve successful OCR and report unread QR.
            original_extract = reader.extract
            reader.extract = lambda *unused: {"text": "Fixture OCR preserved", "notice": "Fixture", "ocr_status": "ok",
                "qr": {"status": "timeout", "codes": [], "truncated": False}}
            read(qr)
            expect(page.locator("#input-text")).to_have_value("Fixture OCR preserved")
            expect(page.locator("#ocr-status")).to_contain_text("Chưa đọc được QR")
            expect(page.locator("#image-qr")).to_be_hidden()
            reader.extract = original_extract
            checks.append("QR_timeout_retains_OCR_text_and_reports_incomplete_read")

            # Current crop only: cutting the QR out must drop its prior payload.
            large = Image.new("RGB", (800, 600), "white"); large.paste(Image.open(qr), (450, 300))
            large_path = args.out / "crop.png"; large.save(large_path)
            read(large_path)
            expect(page.locator("#image-qr")).to_be_visible()
            canvas = page.locator("#image-canvas"); canvas.scroll_into_view_if_needed(); box = canvas.bounding_box()
            page.mouse.move(box["x"]+5, box["y"]+5); page.mouse.down()
            page.mouse.move(box["x"]+box["width"]*.35, box["y"]+box["height"]*.35); page.mouse.up()
            page.locator("#read-image").click(); expect(page.locator("#read-image")).to_be_enabled(timeout=15000)
            expect(page.locator("#image-qr")).to_be_hidden()
            checks.append("crop_reads_only_selected_pixels_and_clears_previous_QR")

            # Real region selection -> captureVisibleTab -> worker RAM -> reader.
            # OCR text is explicit fixture data here, to exercise the direct-send
            # guard even when QR and text coexist in the captured region.
            page.locator("#remove-image").click()
            reader._status["ready"] = True
            reader._read_text = lambda payload: "Visible fixture offer. Send OTP to the agent."
            worker.evaluate("() => chrome.storage.local.set({aiSendMode:'direct'})")
            web = context.new_page(); web.goto(base + "/qr-demo"); web.bring_to_front()
            expect(web.locator("img")).to_be_visible()
            worker.evaluate("async base => { const tabs=await chrome.tabs.query({}); const tab=tabs.find(t=>t.url===base+'/qr-demo'); return PhishLensCapture.start(tab,false); }", base)
            expect(web.locator("[data-phishlens-region]")).to_be_visible()
            box = web.locator("img").bounding_box()
            web.mouse.move(box["x"]-8,box["y"]-8); web.mouse.down()
            web.mouse.move(box["x"]+box["width"]+8,box["y"]+box["height"]+8); web.mouse.up()
            try:
                expect(page.locator("#image-qr")).to_be_visible(timeout=20000)
            except AssertionError:
                page.screenshot(path=str(args.out/"capture_failure.png"))
                (args.out/"capture_failure.json").write_text(json.dumps({"body": page.locator("body").inner_text(), "errors": errors, "requests": requests,
                    "region": worker.evaluate("() => chrome.storage.session.get(null)")}, ensure_ascii=False, indent=2))
                raise
            expect(page.locator("#input-text")).to_have_value("Visible fixture offer. Send OTP to the agent.")
            expect(page.locator("#review")).to_be_hidden()
            assert not calls and len(requests) == 1
            page.bring_to_front(); page.locator("#image-qr").scroll_into_view_if_needed()
            page.screenshot(path=str(args.out / "04_QR_region_with_text.png"))
            checks.append("real_region_capture_decodes_QR_and_does_not_auto_send_OCR_in_direct_mode")
            data = worker.evaluate("() => Promise.all([chrome.storage.local.get(null),chrome.storage.session.get(null)])")
            assert all(marker not in json.dumps(data) for marker in ["QR_DEMO", "DO_NOT_SEND_THIS", "QR_EXECUTED", "Fixture OCR preserved"])
            checks.append("decoded_payloads_and_OCR_are_not_persisted_in_extension_storage")
            assert not calls and not errors and not external, (calls, errors, external)
            context.close()
    finally:
        server.should_exit = True; thread.join(timeout=10); sock.close()
    report = {"passed": len(checks), "checks": checks, "provider_calls": len(calls), "local_analysis_jobs": len(requests),
        "browser_errors": errors, "external_requests": external, "QR_decoder": "real zxing-cpp", "URL_model": "fixture",
        "test_permission_override": "<all_urls> in temporary manifest only for automated capture",
        "source_sha256": source_hashes}
    assert source_hashes == {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files}, "Source changed during verification"
    (args.out / "checks.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps({"passed": len(checks), "provider_calls": len(calls), "report": str(args.out/"checks.json")}))


if __name__ == "__main__":
    main()
