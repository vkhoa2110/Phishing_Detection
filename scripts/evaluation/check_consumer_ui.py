"""Exercise the consumer UI with recorded AI responses and real local URL checks.

No provider calls: every /api/analyze request with use_llm=true is fulfilled
in the browser. WARNING/UNKNOWN and failure/XSS cases are UI fixtures, not
measurements of model accuracy. Requires a running local app and Playwright.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from app.fusion import fuse


def main():
    from playwright.sync_api import expect, sync_playwright

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--run", type=Path, default=ROOT / "artifacts/evaluations/context_regression_v2")
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts/evaluations/consumer_ui_v1")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    rows = {r["id"]: r for r in (json.loads(s) for s in (args.run / "results.jsonl").read_text().splitlines())}
    config = json.loads((args.run / "manifest.json").read_text())["configuration"]
    with urlopen(args.base_url + "/api/status", timeout=45) as response:
        status = json.load(response)
    assert status["ml"]["ready"], "Local URL model is needed for the real-API checks."

    def fixture(case_id="N26", level=None):
        case = deepcopy(rows[case_id])
        if level:
            case["llm_rag"]["verdict"]["risk_level"] = level
        decision = fuse("text", case["urls"], case["llm_rag"], case["invalid_urls"])
        return {"mode": "text", "configuration": "UI replay", "final": decision,
            "assessments": decision["assessments"], "llm": case["llm_rag"], "urls": case["urls"],
            "invalid_urls": case["invalid_urls"], "retrieval": case["retrieval"], "ml": config["ml_status"],
            "timing": {"total_ms": case["llm_rag"]["elapsed_ms"]},
            "notice": "Nhận định nội dung và cảnh báo đường dẫn được đánh giá riêng. Kết quả không bảo đảm an toàn."}

    records = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for viewport, width, height in (("desktop", 1440, 1000), ("tablet", 820, 1180), ("mobile", 390, 844), ("small-mobile", 320, 740)):
            page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
            errors, requests, local_requests = [], [], []
            replay = {"body": fixture(), "fail": False, "edited": False}
            page.on("pageerror", lambda error: errors.append(str(error)))
            # Keep readiness reproducible without claiming the provider is reachable.
            page.route("**/api/status", lambda route: route.fulfill(json={**status, "llm": {**status["llm"], "has_api_key": True}}))

            def handler(route):
                payload = route.request.post_data_json
                if payload.get("use_llm") is False:
                    local_requests.append(True)
                    route.continue_()
                    return
                assert payload["consent"] is True
                assert payload["include_ml"] is False
                requests.append({"edited": payload["llm_text"].endswith("Bản đã sửa để kiểm tra giao diện.")})
                if replay["fail"]:
                    route.fulfill(status=503, json={"detail": "Lỗi kết nối mô phỏng cho kiểm tra giao diện."})
                else:
                    body = deepcopy(replay["body"])
                    if replay["edited"]:
                        body["llm"]["input_modified"] = True
                        body["llm"]["input_used"] = payload["llm_text"]
                    route.fulfill(status=200, json=body)

            page.route("**/api/analyze", handler)

            def no_overflow():
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), viewport
                assert page.evaluate("Array.from(document.querySelectorAll('dialog[open]')).every(d => d.scrollWidth <= d.clientWidth)"), viewport + " dialog"

            def submit(case_id="N26", edit=False):
                page.locator("#input-text").fill(rows[case_id]["text"])
                page.locator("#analyze-button").click()
                expect(page.locator("#privacy-dialog")).to_be_visible()
                expect(page.locator("#confirm-send")).to_be_disabled()
                if edit:
                    page.locator("#consent").check()
                    page.locator("#preview-text").fill(page.locator("#preview-text").input_value() + "\nBản đã sửa để kiểm tra giao diện.")
                    expect(page.locator("#consent")).not_to_be_checked()
                    expect(page.locator("#confirm-send")).to_be_disabled()
                page.locator("#consent").check()
                page.locator("#confirm-send").click()
                expect(page.locator("#result-content")).to_be_visible()
                expect(page.locator("#analyze-button")).to_be_enabled()

            page.goto(args.base_url, wait_until="networkidle")
            expect(page.locator("#results-panel")).to_be_hidden()
            expect(page.locator("#service-status")).to_contain_text("Sẵn sàng")
            no_overflow()
            page.screenshot(path=str(args.out / f"{viewport}-initial.png"), full_page=True)

            # Settings, keyboard close, key concealment, and help dialog.
            page.locator("#settings-button").click()
            expect(page.locator("#use-rag")).to_be_checked()
            expect(page.locator("#include-ml")).not_to_be_checked()
            page.locator(".api-settings > summary").click()
            page.locator("#api-key").fill("ui-test-only")
            page.locator("#show-key").click()
            expect(page.locator("#api-key")).to_have_attribute("type", "text")
            no_overflow()
            page.keyboard.press("Escape")
            expect(page.locator("#api-key")).to_have_attribute("type", "password")
            page.locator("#settings-button").click()
            page.locator("#api-key").fill("")
            page.locator("#done-settings").click()
            page.locator("#how-button").click()
            no_overflow()
            page.keyboard.press("Escape")

            # Each input mode has its own draft and examples.
            page.locator('[data-sample="normal"]').click()
            draft = page.locator("#input-text").input_value()
            page.locator("#tab-url").click()
            page.locator('[data-sample="normal"]').click()
            expect(page.locator("#input-text")).to_have_value("https://example.org/")
            page.locator("#tab-text").click()
            expect(page.locator("#input-text")).to_have_value(draft)

            # Cancellation and empty/editable previews cannot send a request.
            page.locator("#analyze-button").click()
            expect(page.locator("#preview-provider")).to_contain_text("mkp-api.fptcloud.com")
            page.locator("#preview-text").fill(" ")
            page.locator("#consent").check()
            page.locator("#confirm-send").click()
            expect(page.locator("#preview-error")).to_be_visible()
            assert not requests
            no_overflow()
            page.locator("#cancel-preview").click()
            assert not requests

            replay["edited"] = True
            submit(edit=True)
            assert requests[-1]["edited"] is True
            expect(page.locator(".verdict.LOW")).to_be_visible()
            expect(page.locator(".url-assessment.HIGH")).to_be_visible()
            assert page.locator(".result-main > :first-child").get_attribute("class") == "url-assessment HIGH"
            expect(page.locator(".conflict-note")).to_contain_text("URL cần cảnh giác")
            expect(page.locator(".inline-warning").filter(has_text="Bạn đã sửa bản gửi AI")).to_be_visible()
            assert page.locator(".source-link").count() > 0
            assert page.locator("a.url-text").count() == 0
            no_overflow()
            page.screenshot(path=str(args.out / f"{viewport}-conflicting-result.png"), full_page=True)
            page.locator(".technical-details > summary").click()
            with page.expect_download() as download:
                page.locator("#download-result").click()
            downloaded = json.loads(Path(download.value.path()).read_text())
            assert downloaded["final"]["risk_level"] == "LOW"
            page.locator(".technical-details > summary").click()
            page.locator("#new-check").click()
            expect(page.locator("#input-text")).to_be_focused()

            replay["edited"] = False
            replay["body"] = fixture("P26")
            submit("P26")
            expect(page.locator(".verdict.HIGH")).to_be_visible()
            expect(page.locator(".actions-section")).to_be_visible()
            no_overflow()
            page.screenshot(path=str(args.out / f"{viewport}-high-result.png"), full_page=True)

            for level in ("WARNING", "UNKNOWN"):
                replay["body"] = fixture(level=level)
                submit()
                expect(page.locator(".verdict." + level)).to_be_visible()
                no_overflow()

            # Untrusted result strings and malformed source links stay inert.
            attack = '<img src=x onerror="window.uiInjected=true">'
            replay["body"] = fixture()
            replay["body"]["llm"]["verdict"]["summary"] = attack
            replay["body"]["llm"]["verdict"]["evidence"] = [{"quote": attack, "reason": attack}]
            replay["body"]["urls"][0]["url"] = "https://example.org/" + "a" * 600
            replay["body"]["retrieval"]["sources"][0]["source_url"] = "javascript:alert(1)"
            replay["body"]["retrieval"]["sources"][0]["title"] = attack
            submit()
            expect(page.locator(".analysis-summary")).to_have_text(attack)
            assert page.locator("#result-content img, #result-content script").count() == 0
            assert page.locator('#result-content a[href^="javascript:"]').count() == 0
            assert page.evaluate("window.uiInjected !== true")
            no_overflow()

            # Recover from an API failure, then exercise the real local path.
            replay["fail"] = True
            page.locator("#input-text").fill(draft)
            page.locator("#analyze-button").click()
            expect(page.locator("#privacy-dialog")).to_be_visible()
            expect(page.locator("#confirm-send")).to_be_disabled()
            page.locator("#consent").check()
            page.locator("#confirm-send").click()
            expect(page.locator("#form-error")).to_contain_text("Lỗi kết nối mô phỏng")
            expect(page.locator("#results-panel")).to_be_hidden()
            expect(page.locator("#analyze-button")).to_be_enabled()
            page.locator("#use-llm").uncheck()
            page.locator("#input-text").fill(draft)
            page.locator("#analyze-button").click()
            expect(page.locator(".verdict.UNKNOWN")).to_be_visible()
            assert page.locator(".url-item").count() == 0
            page.locator("#tab-url").click()
            page.locator("#input-text").fill("https://example.org/account")
            page.locator("#analyze-button").click()
            expect(page.locator("#result-content")).to_be_visible()
            expect(page.locator(".verdict-eyebrow")).to_contain_text("ĐÁNH GIÁ ĐƯỜNG DẪN")
            assert page.locator(".url-item").count() == 1
            no_overflow()
            page.locator("#input-text").fill("not-a-url")
            page.locator("#analyze-button").click()
            expect(page.locator("#form-error")).to_be_visible()
            expect(page.locator("#input-text")).to_be_enabled()
            page.locator("#clear-button").click()
            expect(page.locator("#input-text")).to_be_empty()
            expect(page.locator("#results-panel")).to_be_hidden()
            assert len(local_requests) == 3
            assert errors == [], errors
            records.append({"viewport": viewport, "size": [width, height], "passed": True,
                "replayed_ai_requests": len(requests), "real_local_requests": len(local_requests),
                "provider_requests": 0, "page_errors": errors})
            page.close()

        # Unconfigured and disconnected states need actionable UI, not a permanent spinner.
        page = browser.new_page(viewport={"width": 390, "height": 844})
        unexpected = []
        page.route("**/api/analyze", lambda route: (unexpected.append(True), route.abort()))
        no_key = deepcopy(status)
        no_key["llm"]["has_api_key"] = False
        page.route("**/api/status", lambda route: route.fulfill(json=no_key))
        page.goto(args.base_url, wait_until="networkidle")
        page.locator("#input-text").fill("Một tin nhắn cần kiểm tra.")
        page.locator("#analyze-button").click()
        expect(page.locator("#settings-dialog")).to_be_visible()
        expect(page.locator("#api-key")).to_be_focused()
        assert not unexpected
        page.unroute("**/api/status")
        page.route("**/api/status", lambda route: route.abort())
        page.reload(wait_until="networkidle")
        expect(page.locator("#connection-error")).to_be_visible()
        expect(page.locator("#service-status")).to_contain_text("Chưa kết nối")
        page.close()
        browser.close()
    report = {"checks": records, "missing_key_and_disconnected_states": "passed", "provider_requests": 0,
        "note": "UI behavior checks; recorded/simulated AI output is not a model-quality benchmark."}
    (args.out / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
