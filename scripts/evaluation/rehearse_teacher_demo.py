"""Rehearse the teacher demo against a running local server.

Without --live-provider: validate the demo UI and handoff, no AI requests.
With --live-provider: exactly three authored examples through the real UI:
one web classification, one extension classification + public explanation,
and one region screenshot/OCR + classification + public explanation.
No mocked verdicts, automatic retries, accounts, or outgoing emails.
The isolated browser pregrants the extension's optional website permission;
its shipped scripts remain byte-for-byte identical. Native Gmail/Outlook
integration is not exercised by this rehearsal.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    import httpx
    from playwright.sync_api import sync_playwright, expect

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8001")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--live-provider", action="store_true")
    parser.add_argument("--cases", nargs="+", choices=["web_workshop", "extension_promotion", "extension_region"],
                        default=["web_workshop", "extension_promotion", "extension_region"],
                        help="Select explicit cases; avoid resending completed examples when checking an unfinished flow.")
    args = parser.parse_args()
    parsed = urlsplit(args.base)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.path not in {"", "/"} or parsed.query or parsed.fragment or parsed.username:
        raise SystemExit("Demo chỉ kết nối PhishLens HTTP trên máy.")
    base = args.base.rstrip("/")
    with httpx.Client(trust_env=False, timeout=10) as client:
        health = client.get(base + "/api/health"); health.raise_for_status()
        if not health.json().get("ready"):
            raise SystemExit("Khởi động PhishLens trước khi chạy demo.")
        status = client.get(base + "/api/status"); status.raise_for_status()
    args.out.mkdir(parents=True, exist_ok=False)
    source = ROOT / "extensions/chromium"
    scripts = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
               for path in [*source.glob("*.js"), *ROOT.glob("app/static/demo*"), ROOT / "app/static/app.js"] if path.is_file()}
    report = {"started_utc": datetime.now(timezone.utc).isoformat(), "base": base,
              "live_provider": args.live_provider, "synthetic_examples": True,
              "human_labels": False, "gmail_outlook_integration_tested": False,
              "automatic_retries": 0, "selected_cases": args.cases, "checks": [], "results": [], "errors": [],
              "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "source_sha256": scripts}
    # Store model/profile metadata only, never an endpoint/key or browser session.
    runtime = status.json()
    report["runtime"] = {"model": runtime.get("llm", {}).get("model"),
                         "analysis_policy": runtime.get("analysis_policy"),
                         "limits": runtime.get("limits")}

    def save_result(case, data, elapsed):
        write(args.out / (case + ".json"), data)
        llm = data.get("llm", {}); note = llm.get("evidence_explanation", {})
        report["results"].append({"case": case, "elapsed_seconds": round(elapsed, 2),
            "llm_status": llm.get("status"), "risk": llm.get("verdict", {}).get("risk_level"),
            "summary": llm.get("verdict", {}).get("summary"), "prompt": llm.get("prompt_version"),
            "evidence_count": len(llm.get("verdict", {}).get("evidence", [])),
            "public_explanation_status": note.get("status"), "usage": llm.get("usage"),
            "public_explanation_usage": note.get("usage"),
            "provider_calls": data.get("execution", {}).get("runtime", {}).get("calls_attempted"),
            "urls": [{key: item.get(key) for key in ("url", "score", "risk_level", "status")} for item in data.get("urls", [])],
            "history": data.get("history"), "error_code": llm.get("code")})
        write(args.out / "checks.json", report)
        print(json.dumps(report["results"][-1], ensure_ascii=False), flush=True)

    with sync_playwright() as runner:
        browser = runner.chromium.launch(headless=True)
        web_context = browser.new_context(viewport={"width": 1280, "height": 900},
            record_video_dir=str(args.out / "videos-web"), record_video_size={"width": 1280, "height": 900})
        web = web_context.new_page()
        sent = []
        web.on("request", lambda request: sent.append(request.url) if request.url.endswith(("/api/analyze", "/api/extension/jobs/start")) else None)
        web.on("pageerror", lambda error: report["errors"].append(str(error)))
        try:
            web.goto(base + "/static/demo.html")
            expect(web.locator(".scenario")).to_have_count(4)
            expect(web.locator("#server-status")).to_have_text("Ứng dụng đã kết nối")
            for filename in ("demo.js", "app.js"):
                web.evaluate("source => { new Function(source); }", (ROOT / "app/static" / filename).read_text())
            web.screenshot(path=str(args.out / "01_demo.png"), full_page=True)
            web.locator('#mail-body a').click()
            assert web.url.startswith(base + "/static/demo.html")
            report["checks"].append("sample_link_does_not_navigate_or_fetch_destination")
            web.locator('[data-id="workshop"]').click()
            web.locator("#open-check").click()
            expect(web.locator("#input-text")).to_have_value(re.compile("Ban tổ chức Câu lạc bộ Công nghệ"))
            assert web.evaluate("sessionStorage.getItem('phishlens-demo-draft')") is None
            assert not sent and not web.locator("#privacy-dialog").is_visible()
            report["checks"].append("one_use_handoff_fills_editor_without_sending_AI")
            if args.live_provider and "web_workshop" in args.cases:
                expect(web.locator("#service-status")).not_to_have_text("Đang kết nối…", timeout=60000)
                web.locator("#use-llm").check()
                web.locator("#analyze-button").click()
                expect(web.locator("#privacy-dialog")).to_be_visible()
                assert "cau-lac-bo@example.org" not in web.locator("#preview-text").input_value()
                assert not sent
                web.screenshot(path=str(args.out / "02_web_preview.png"), full_page=True)
                web.locator("#consent").check()
                started = time.monotonic()
                with web.expect_response("**/api/analyze", timeout=95000) as response:
                    web.locator("#confirm-send").click()
                data = response.value.json()
                save_result("web_workshop", data, time.monotonic() - started)
                expect(web.locator("#result-content")).to_be_visible(timeout=10000)
                web.locator("#results-panel").scroll_into_view_if_needed()
                web.wait_for_timeout(1800)
                web.screenshot(path=str(args.out / "03_web_result.png"), full_page=True)
            else:
                web.reload()
                expect(web.locator("#input-text")).to_have_value("")
            web.goto(base + "/static/demo.html#image")
            expect(web.locator("#ocr-card")).to_be_visible()
            with web.expect_download() as download:
                web.locator("#download-image").click()
            download.value.save_as(args.out / "phishlens-uu-dai-demo.png")
            report["checks"].append("PNG_download_from_authored_SVG")
            for width in (390, 768, 1280):
                web.set_viewport_size({"width": width, "height": 900})
                assert web.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
            report["checks"].append("demo_layout_no_horizontal_overflow_at_390_768_1280")
        except Exception as error:
            report["errors"].append(type(error).__name__ + ": " + str(error))
            write(args.out / "checks.json", report)
            raise
        finally:
            web_video = web.video
            web_context.close()
            if web_video:
                web_video.save_as(args.out / "01_demo_web.webm")
            browser.close()

        if args.live_provider and any(case.startswith("extension_") for case in args.cases):
            # Pregrant the optional permission only in this isolated rehearsal.
            # No shipped script is changed; this does not test the native prompt.
            test_source = args.out / "test-extension"
            shutil.copytree(source, test_source)
            manifest = json.loads((test_source / "manifest.json").read_text())
            manifest["host_permissions"].append("<all_urls>")
            write(test_source / "manifest.json", manifest)
            for path in source.rglob("*"):
                if path.is_file() and path.name != "manifest.json":
                    assert path.read_bytes() == (test_source / path.relative_to(source)).read_bytes()
            report["optional_host_permission_pregranted_in_isolated_browser"] = True
            extension = runner.chromium.launch_persistent_context(str(args.out / "browser-profile"), channel="chromium", headless=True,
                args=[f"--disable-extensions-except={test_source.resolve()}", f"--load-extension={test_source.resolve()}", "--screen-info={1600x1000}", "--window-size=1280,900"],
                viewport={"width": 600, "height": 900}, screen={"width": 1600, "height": 1000},
                record_video_dir=str(args.out / "videos-extension"), record_video_size={"width": 600, "height": 900})
            worker = extension.service_workers[0] if extension.service_workers else extension.wait_for_event("serviceworker")
            worker.evaluate("base => chrome.storage.local.set({base,theme:'dark',aiSendMode:'review'})", base)
            extension_id = worker.url.split("/")[2]
            panel = extension.new_page()
            panel.on("pageerror", lambda error: report["errors"].append(str(error)))
            panel.on("dialog", lambda dialog: dialog.accept())
            panel.goto(f"chrome-extension://{extension_id}/check.html?panel=1")
            expect(panel.locator("#connection-status")).to_contain_text("Sẵn sàng", timeout=60000)

            def extension_result(case, started):
                expect(panel.locator("#result")).to_be_visible(timeout=95000)
                job = worker.evaluate("async () => { const {analysisCurrent} = await chrome.storage.session.get('analysisCurrent'); return PhishLensJobs.status(analysisCurrent); }")
                if job.get("status") != "complete":
                    raise RuntimeError("Kết quả job chưa hoàn tất: " + str(job.get("status")))
                save_result(case, job["result"], time.monotonic() - started)
                panel.wait_for_timeout(1600)
                panel.screenshot(path=str(args.out / (case + "_result.png")), full_page=True)
                panel.locator("main").evaluate("el => el.scrollBy({top:520,behavior:'smooth'})")
                panel.wait_for_timeout(1800)
                panel.screenshot(path=str(args.out / (case + "_evidence.png")), full_page=True)
                panel.locator("#nav-activity").click()
                expect(panel.locator(".activity-card")).not_to_have_count(0)
                current = worker.evaluate("async()=> (await chrome.storage.session.get('analysisCurrent')).analysisCurrent")
                card = panel.locator('[data-id="' + current['id'] + '"]')
                expect(card).to_have_attribute("data-status", "complete", timeout=15000)
                panel.screenshot(path=str(args.out / (case + "_recent.png")))
                card.locator('[data-action="open"]').click()
                expect(panel.locator("#result")).to_be_visible(timeout=15000)
                panel.pdf(path=str(args.out / (case + "_report.pdf")), format="A4", print_background=True)
                report["checks"].append(case + "_reopen_same_job_from_recent_and_export_PDF")
                write(args.out / "checks.json", report)

            try:
                if "extension_promotion" in args.cases:
                    samples = json.loads((ROOT / "app/static/demo-samples.json").read_text())
                    sample = samples[0]
                    text = f"Tiêu đề: {sample['subject']}\nNgười gửi hiển thị: {sample['sender']} <{sample['address']}>\n\n" + "\n\n".join(sample["paragraphs"])
                    panel.locator("#tab-text").click()
                    panel.locator("#input-text").fill(text)
                    panel.locator("#use-ai").check()
                    panel.locator("#analyze").click()
                    expect(panel.locator("#review")).to_be_visible()
                    assert "uu-dai@example.org" not in panel.locator("#approved-text").input_value()
                    panel.screenshot(path=str(args.out / "04_extension_preview.png"))
                    panel.wait_for_timeout(1500)
                    panel.locator("#consent").check()
                    started = time.monotonic(); panel.locator("#confirm").click()
                    extension_result("extension_promotion", started)
                    report["checks"].append("real_extension_guest_preview_consent_classification_public_explanation")
                    panel.locator("#new-analysis").click()
                if "extension_region" in args.cases:
                    page = extension.new_page(); page.set_viewport_size({"width": 1280, "height": 900})
                    page.goto(base + "/static/demo.html#image")
                    image = page.locator("#ocr-card"); expect(image).to_be_visible()
                    image.evaluate("async image => { await image.decode(); await document.fonts.ready; }")
                    image.scroll_into_view_if_needed(); page.bring_to_front()
                    # Finish the browser's queued scroll event before installing
                    # region.js, which correctly cancels a moving viewport.
                    page.wait_for_timeout(400)
                    worker.evaluate("() => { globalThis.demoCaptureTrace=[]; chrome.runtime.onMessage.addListener(m => { if(m.type.startsWith('REGION') || m.type==='CAPTURE_ERROR') demoCaptureTrace.push({type:m.type,reason:m.reason,message:m.message}); }); }")
                    bounds = image.bounding_box()
                    worker.evaluate("async url => { const tab = (await chrome.tabs.query({})).find(tab => tab.url === url); return PhishLensCapture.start(tab, false); }", page.url)
                    expect(page.locator("[data-phishlens-region]")).to_be_visible()
                    page.screenshot(path=str(args.out / "05_region_selection.png"))
                    x, y = bounds["x"], bounds["y"]
                    page.mouse.move(x, y); page.mouse.down()
                    page.mouse.move(x + bounds["width"], y + bounds["height"], steps=30)
                    page.mouse.up()
                    expect(page.locator("[data-phishlens-region]")).to_have_count(0)
                    expect(panel.locator("#review")).to_be_visible(timeout=30000)
                    approved = panel.locator("#approved-text").input_value()
                    write(args.out / "ocr.json", {"local_OCR": True, "approved_text": approved})
                    assert "OTP" in approved and "49.000" in approved and "example.com" in approved
                    panel.bring_to_front(); panel.screenshot(path=str(args.out / "06_OCR_preview.png"))
                    panel.wait_for_timeout(2000)
                    panel.locator("#consent").check()
                    started = time.monotonic(); panel.locator("#confirm").click()
                    extension_result("extension_region", started)
                    report["checks"].append("actual_region_capture_local_OCR_review_and_live_AI")
            except Exception as error:
                report["errors"].append(type(error).__name__ + ": " + str(error))
                report["capture_diagnostics"] = {key: panel.locator("#" + key).inner_text() for key in ("error", "ocr-status", "connection-status")}
                report["capture_trace"] = worker.evaluate("() => globalThis.demoCaptureTrace || []")
                panel.screenshot(path=str(args.out / "unfinished_extension_flow.png"))
                write(args.out / "checks.json", report)
                raise
            finally:
                panel_path = Path(panel.video.path()) if panel.video else None
                extension.close()
                if panel_path and panel_path.is_file():
                    shutil.copyfile(panel_path, args.out / "02_demo_extension.webm")
    report["finished_utc"] = datetime.now(timezone.utc).isoformat()
    report["all_live_classifications_ok"] = all(item["llm_status"] == "ok" for item in report["results"]) if args.live_provider else None
    write(args.out / "checks.json", report)
    print(json.dumps({"checks": report["checks"], "live_results": len(report["results"]), "errors": report["errors"]}, ensure_ascii=False))
    if report["errors"] or args.live_provider and (len(report["results"]) != len(args.cases) or not report["all_live_classifications_ok"]):
        raise SystemExit("Demo chưa hoàn tất mọi luồng. Kết quả được giữ nguyên, không tự gọi lại.")


if __name__ == "__main__":
    main()
