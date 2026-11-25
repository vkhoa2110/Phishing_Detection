"""Real MV3 + local Vietnamese OCR, image editing and consent in isolated Chromium.
The provider is mocked; no recipient data or personal browser profile is used.
"""
import argparse
from dataclasses import replace
import json
import re
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
    from PIL import Image, ImageDraw, ImageFont
    from playwright.sync_api import sync_playwright, expect
    from app.api.workspace import create_app
    from app.core.settings import Settings
    from app.services.workspace import WorkspaceSettings
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(); args.out.mkdir(parents=True, exist_ok=False)
    calls, errors, checks = [], [], []
    fixture = args.out / "tin_nhan_minh_hoa.png"
    image = Image.new("RGB", (1100, 420), "white"); draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 32)
    for index, line in enumerate(["THÔNG BÁO XÁC MINH TÀI KHOẢN", "Vui lòng gửi mã OTP cho nhân viên.", "https://xac-minh.example/verify", "Liên hệ private.person@example.org"]):
        draw.text((45, 42 + index * 77), line, fill="#172236", font=font)
    image.save(fixture)
    def provider(request):
        from tests.api.test_evidence_explanation import NOTE
        from tests.api.test_focused_app import packet as explanation_packet
        calls.append(json.loads(request.content))
        if json.loads(request.content)["messages"][0]["content"].startswith("Viết lời giải thích ngắn"):
            return explanation_packet(NOTE)
        answer = {"risk_level": "HIGH", "context_kind": "scam_request", "reason_code": "secret_request", "quotes": ["gửi mã OTP"], "missing_context": []}
        return httpx.Response(200, json={"model": "image-ui-fixture", "usage": {"total_tokens": 25}, "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(answer)}}]})
    app = create_app("focused", replace(Settings(), api_key="isolated-fixture"), transport=httpx.MockTransport(provider),
        workspace_settings=WorkspaceSettings(database=args.out / "application/test.sqlite3"))
    assert app.state.extension_ocr.status()["ready"], "Install optional local vie+eng OCR before this integration check."
    sock = socket.socket(); sock.bind(("127.0.0.1", 0)); base = "http://127.0.0.1:" + str(sock.getsockname()[1])
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True); thread.start()
    try:
        deadline = time.monotonic() + 30
        while not server.started:
            if time.monotonic() > deadline or not thread.is_alive(): raise RuntimeError("Server startup")
            time.sleep(.1)
        with sync_playwright() as runner:
            source = ROOT / "extensions/chromium"
            context = runner.chromium.launch_persistent_context(str(args.out / "browser-profile"), channel="chromium", headless=True,
                args=[f"--disable-extensions-except={source}", f"--load-extension={source}"], viewport={"width": 390, "height": 844})
            context.on("page", lambda page: page.on("pageerror", lambda error: errors.append(str(error))))
            worker = context.service_workers[0] if context.service_workers else context.wait_for_event("serviceworker")
            extension_id = worker.url.split("/")[2]
            options = worker.evaluate("() => chrome.sidePanel.getOptions({})")
            assert options["path"] == "check.html?panel=1" and options["enabled"]
            assert worker.evaluate("() => chrome.sidePanel.getPanelBehavior()")["openPanelOnActionClick"]
            checks.append("side_panel_manifest_options_and_toolbar_behavior")
            web = context.new_page(); web.goto(base + "/check")
            worker.evaluate("base => chrome.storage.local.set({base})", base)
            page = context.new_page(); page.goto(f"chrome-extension://{extension_id}/check.html?panel=1", wait_until="domcontentloaded")
            expect(page.locator("#connection-status")).to_contain_text("Sẵn sàng", timeout=60000)
            page.screenshot(path=str(args.out / "01_home_light.png"), full_page=True)
            page.locator("#tab-image").click()
            page.screenshot(path=str(args.out / "02_upload_light.png"), full_page=True)
            page.locator("#image-file").set_input_files(str(fixture))
            expect(page.locator("#image-preview")).to_be_visible()
            assert not calls
            # Real pointer drag crops the fourth line out before upload to OCR.
            canvas = page.locator("#image-canvas"); canvas.scroll_into_view_if_needed(); box = canvas.bounding_box()
            page.mouse.move(box["x"] + 2, box["y"] + 2); page.mouse.down()
            page.mouse.move(box["x"] + box["width"] - 2, box["y"] + box["height"] * .62, steps=8); page.mouse.up()
            expect(page.locator("#crop-selection")).to_be_visible()
            with page.expect_response("**/api/extension/image-text", timeout=30000) as ocr_response:
                page.locator("#read-image").click()
            ocr = ocr_response.value.json()
            assert ocr_response.value.status == 200, ocr
            assert "gửi mã OTP" in ocr["text"] and "private.person" not in ocr["text"] and ocr["height"] < 420
            expect(page.locator("#input-text")).to_have_value(re.compile("gửi mã OTP"))
            assert len(calls) == 0 and ocr["provider_calls"] == 0 and not ocr["image_saved"]
            page.screenshot(path=str(args.out / "03_crop_OCR_light.png"), full_page=True)
            checks.append("upload_preview_pointer_crop_real_vietnamese_OCR_no_provider_no_image_saved")
            # Re-read the full image to verify PII redaction later.
            page.locator("#reset-crop").click(); page.once("dialog", lambda dialog: dialog.accept())
            with page.expect_response("**/api/extension/image-text", timeout=30000) as full_response:
                page.locator("#read-image").click()
            assert "private.person@example.org" in full_response.value.json()["text"]
            page.locator("#input-text").fill(full_response.value.json()["text"] + "\nGhi chú do người dùng sửa.")
            page.locator("#analyze").click(); expect(page.locator("#review")).to_be_visible()
            assert len(calls) == 0 and "private.person@example.org" not in page.locator("#approved-text").input_value()
            expect(page.locator("#provider-note")).to_contain_text("Ảnh gốc không được gửi")
            page.locator("#consent").check()
            page.locator("#approved-text").fill(page.locator("#approved-text").input_value() + "\nĐã xem lại.")
            expect(page.locator("#consent")).not_to_be_checked()
            page.locator("#consent").check()
            approved = page.locator("#approved-text").input_value()
            clipboard_image = """bytes => {const transfer=new DataTransfer();transfer.items.add(new File([new Uint8Array(bytes)],'clipboard.png',{type:'image/png'}));document.dispatchEvent(new ClipboardEvent('paste',{bubbles:true,clipboardData:transfer}));}"""
            page.locator("#nav-connection").click()
            page.evaluate(clipboard_image, list(fixture.read_bytes()))
            page.locator("#nav-check").click()
            expect(page.locator("#approved-text")).to_have_value(approved)
            expect(page.locator("#consent")).to_be_checked()
            page.once("dialog", lambda dialog: dialog.dismiss())
            page.evaluate(clipboard_image, list(fixture.read_bytes()))
            expect(page.locator("#review")).to_be_visible()
            expect(page.locator("#approved-text")).to_have_value(approved)
            assert not calls
            checks.append("image_paste_in_settings_is_ignored_and_cancelled_replacement_keeps_approved_text_and_consent")
            page.locator("#confirm").click()
            expect(page.locator("#result")).to_contain_text("Nguy cơ cao", timeout=30000)
            assert len(calls) == 2 and "private.person@example.org" not in json.dumps(calls)
            assert not page.evaluate("document.documentElement.scrollWidth > innerWidth + 1")
            page.screenshot(path=str(args.out / "04_result_light.png"), full_page=True)
            checks.append("OCR_edit_preview_redaction_reconsent_one_mocked_text_only_AI_call")
            page.locator("#theme-toggle").click(); expect(page.locator("html")).to_have_attribute("data-theme", "dark")
            page.screenshot(path=str(args.out / "05_result_dark.png"), full_page=True)
            page.locator("#edit-result").click()
            page.locator("#tab-image").click()
            page.evaluate("""() => {
              const transfer = new DataTransfer();
              transfer.items.add(new File(['bad'], 'fake.svg', {type: 'image/svg+xml'}));
              document.querySelector('#input-area').dispatchEvent(new DragEvent('drop', {bubbles: true, dataTransfer: transfer}));
            }""")
            expect(page.locator("#error")).to_contain_text("Chưa hỗ trợ")
            page.locator("#remove-image").click(); expect(page.locator("#image-preview")).to_be_hidden()
            assert page.locator("#input-text").input_value() == ""
            assert len(calls) == 2
            page.set_viewport_size({"width": 320, "height": 844})
            assert not page.evaluate("document.documentElement.scrollWidth > innerWidth + 1")
            page.screenshot(path=str(args.out / "06_upload_dark_320.png"), full_page=True)
            stored = page.evaluate("() => chrome.storage.local.get(null)")
            assert set(stored) == {"base", "theme", "connection", "autoConnectDisabled"}
            assert stored["connection"]["guest"] and "token" not in stored["connection"]
            memory = page.evaluate("() => chrome.storage.session.get(null)")
            assert not memory
            checks.append("dark_theme_320px_invalid_drop_image_clear_no_image_or_result_in_storage")
            # Browser paste event uses a real File, not a remote image URL.
            content = list(fixture.read_bytes())
            page.evaluate("""bytes => {
              const transfer = new DataTransfer();
              transfer.items.add(new File([new Uint8Array(bytes)], 'clipboard.png', {type: 'image/png'}));
              document.dispatchEvent(new ClipboardEvent('paste', {bubbles: true, clipboardData: transfer}));
            }""", content)
            expect(page.locator("#image-preview")).to_be_visible()
            assert page.locator("#image-name").inner_text().startswith("Ảnh từ clipboard")
            checks.append("clipboard_image_event_loads_local_preview_without_network_or_AI")
            # Delivery to an already-open panel is event-driven and window-scoped.
            window_id = page.evaluate("async () => (await chrome.windows.getCurrent()).id")
            worker.evaluate("windowId => chrome.storage.session.set({panelInput: {mode:'url',text:'https://example.org/from-menu',windowId,created:Date.now()}})", window_id)
            expect(page.locator("#input-text")).to_have_value("https://example.org/from-menu")
            expect(page.locator("#tab-url")).to_have_attribute("aria-selected", "true")
            page.locator("#tab-image").click(); page.locator("#capture-tab").click()
            expect(page.locator("#error")).to_contain_text("Mở trang web")
            assert len(calls) == 2
            checks.append("live_panel_storage_delivery_and_actionable_capture_error_on_restricted_page")
            assert not errors, errors
            context.close()
    finally:
        server.should_exit = True; thread.join(timeout=15); sock.close()
    report = {"passed": len(checks), "checks": checks, "browser_errors": errors, "real_vietnamese_english_OCR": True,
        "real_MV3_extension": True, "mocked_provider_calls": len(calls), "external_provider_calls": 0,
        "image_and_clipboard_events_programmatic": True, "crop_pointer_actions": True, "actual_browser_toolbar_click_not_automated": True}
    (args.out / "checks.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
