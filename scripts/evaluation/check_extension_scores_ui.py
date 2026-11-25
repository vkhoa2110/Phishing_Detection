"""Check honest URL percentages and ordinal AI warnings in the real extension.

All extension HTTP endpoints are intercepted with explicit fixtures. No backend,
provider, user database or personal browser profile is used by this UI check.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import time

ROOT = Path(__file__).resolve().parents[2]


def main():
    from playwright.sync_api import sync_playwright, expect

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(); args.out.mkdir(parents=True, exist_ok=False)
    checks, errors, requests = [], [], []
    response = {}

    def endpoint(route):
        path = route.request.url.rsplit("/", 1)[-1]; body = route.request.post_data_json or {}
        requests.append(path)
        if path == "session":
            data = {"user": {"display_name": "Demo điểm số"}, "ml_ready": True, "llm_ready": True, "rag_ready": False, "model": "UI fixture", "ocr": {"ready": False, "message": "Không dùng OCR trong kiểm giao diện điểm số."}}
        elif path == "preview":
            data = {"text": body["text"], "masked_fields": []}
        elif path == "analyze":
            assert not body["use_llm"] or body["consent"] and body.get("llm_text")
            data = response
        else:
            raise AssertionError("Unexpected API path: " + path)
        route.fulfill(status=200, json=data, headers={"Access-Control-Allow-Origin": route.request.headers.get("origin", "*"), "Cache-Control": "no-store"})

    def fixture(mode="text", level="HIGH", urls=None):
        urls = urls or []
        llm = {"status": "disabled"} if mode == "url" else {"status": "ok", "verdict": {"risk_level": level,
            "summary": "Nhận định minh họa để kiểm cách trình bày; không phải kết quả mô hình.",
            "evidence": [{"quote": "gửi mã OTP", "reason": "Căn cứ minh họa."}] if level == "HIGH" else [],
            "recommended_actions": ["Xác minh qua kênh chính thức."]}}
        return {"mode": mode, "final": {"risk_level": level, "label": {"HIGH": "Nguy cơ cao", "LOW": "Chưa thấy dấu hiệu rõ ràng", "UNKNOWN": "Chưa đủ thông tin", "WARNING": "Cần kiểm tra thêm"}[level]},
            "llm": llm, "urls": urls, "invalid_urls": [], "assessments": {"url": {"risk_level": "HIGH" if urls else "UNKNOWN"}}, "history": {"status": "disabled"}}

    def url(score=.9234, status="ok", risk="HIGH", suffix="one"):
        return {"url": "https://example.org/" + suffix, "status": status, "score": score, "risk_level": risk, "high_threshold": .5259423982}

    with sync_playwright() as runner:
        source = ROOT / "extensions/chromium"
        context = runner.chromium.launch_persistent_context(str(args.out / "browser-profile"), channel="chromium", headless=True,
            args=[f"--disable-extensions-except={source}", f"--load-extension={source}"], viewport={"width": 390, "height": 844})
        context.route(re.compile(r"http://127\.0\.0\.1:18675/api/extension/.*"), endpoint)
        worker = context.service_workers[0] if context.service_workers else context.wait_for_event("serviceworker", timeout=15000)
        worker.evaluate("connection => chrome.storage.session.set({connection})", {"base": "http://127.0.0.1:18675", "token": "isolated-ui-fixture", "expires_at": time.time() + 3600})
        page = context.new_page(); page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(worker.url.replace("background.js", "check.html"))
        expect(page.locator("#connection-status")).to_contain_text("Sẵn sàng")

        def show(data):
            nonlocal response
            response = copy.deepcopy(data)
            if page.locator("#result").is_visible(): page.locator("#new-analysis").click()
            page.locator("#tab-" + data["mode"]).click()
            page.locator("#input-text").fill("Vui lòng gửi mã OTP." if data["mode"] == "text" else "https://example.org/")
            page.locator("#analyze").click()
            if data["mode"] == "text":
                expect(page.locator("#review")).to_be_visible(); page.locator("#consent").check(); page.locator("#confirm").click()
            expect(page.locator("#result")).to_be_visible()
            expect(page.locator("#analyze")).to_be_enabled()

        show(fixture())
        expect(page.locator(".result-hero .risk-scale-step.selected")).to_have_text("Cao")
        expect(page.locator(".assessment-card").nth(1)).not_to_contain_text("%")
        expect(page.locator(".score-explanation")).not_to_have_attribute("open", "")
        expect(page.locator(".model-score")).to_have_count(0)
        page.locator(".result-hero").scroll_into_view_if_needed(); page.screenshot(path=str(args.out / "01_AI_HIGH_no_URL_light.png"))
        page.locator("#theme-toggle").click(); page.locator(".result-hero").scroll_into_view_if_needed(); page.screenshot(path=str(args.out / "02_AI_HIGH_no_URL_dark.png"))
        checks.append("AI_HIGH_without_URL_stays_ordinal_no_fabricated_percentage")

        show(fixture(level="LOW", urls=[url()]))
        expect(page.locator(".result-hero .model-score")).to_have_count(0)
        expect(page.locator(".result-hero .risk-scale-step.selected")).to_have_text("Thấp")
        expect(page.locator(".assessment-card .model-score-heading b")).to_have_text("92,3%")
        expect(page.locator(".assessment-card .score-note")).to_contain_text("Chưa phải xác suất")
        page.locator(".result-hero").scroll_into_view_if_needed(); page.screenshot(path=str(args.out / "03_URL_HIGH_AI_LOW_scopes_separate.png"))
        checks.append("URL_numeric_score_is_scoped_separately_from_conflicting_AI_LOW")

        show(fixture(mode="url", urls=[url()]))
        expect(page.locator(".result-hero .model-score-heading b")).to_have_text("92,3%")
        expect(page.locator(".result-hero [role=meter]")).to_have_attribute("aria-valuenow", "92.34")
        expect(page.locator(".ai-score-note")).to_have_count(0)
        page.locator(".result-hero").scroll_into_view_if_needed(); page.screenshot(path=str(args.out / "04_URL_score_dark.png"))
        page.locator(".result-details summary").click()
        expect(page.locator(".url-row")).to_contain_text("52,6%")
        checks.append("URL_mode_shows_92_3_percent_model_score_with_operating_threshold_and_limit")

        show(fixture(urls=[url(), url(.05, risk="LOW", suffix="two")]))
        expect(page.locator(".result-hero .model-score, .assessment-card .model-score")).to_have_count(0)
        expect(page.locator(".url-row .model-score")).to_have_count(2)
        expect(page.locator(".url-row .model-score-heading b")).to_have_text(["92,3%", "5,0%"])
        checks.append("multiple_URLs_keep_individual_scores_no_invented_aggregate")

        for level in ("UNKNOWN", "WARNING", "LOW"):
            show(fixture(level=level))
            expect(page.locator(".model-score")).to_have_count(0)
            expect(page.locator(".risk-scale-step.selected")).to_have_count(0 if level == "UNKNOWN" else 1)
        checks.append("UNKNOWN_is_not_zero_and_AI_levels_have_no_fixed_percent_mapping")

        for score, status in [(None, "ok"), ("0.99", "ok"), (True, "ok"), (-.1, "ok"), (1.1, "ok"), (.99, "error")]:
            show(fixture(mode="url", level="UNKNOWN", urls=[url(score, status=status)]))
            expect(page.locator(".model-score")).to_have_count(0)
        checks.append("missing_invalid_out_of_range_or_failed_URL_scores_do_not_render_as_percent")

        for score, shown in [(0, "0,0%"), (1, "100,0%")]:
            show(fixture(mode="url", urls=[url(score)]))
            expect(page.locator(".result-hero .model-score-heading b")).to_have_text(shown)
            expect(page.locator(".result-hero .score-note")).to_contain_text("Chưa phải xác suất")
        checks.append("valid_zero_and_one_remain_model_scores_with_no_safety_probability_claim")

        page.set_viewport_size({"width": 320, "height": 844})
        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth + 1")
        page.locator(".result-hero").scroll_into_view_if_needed(); page.screenshot(path=str(args.out / "05_URL_score_dark_320.png"))
        checks.append("score_layout_fits_320px_and_dark_theme")
        assert not errors, errors
        context.close()
    report = {"passed": len(checks), "checks": checks, "browser_errors": errors, "API_responses": "intercepted_explicit_UI_fixtures", "external_provider_calls": 0,
        "backend_requests": 0, "source_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in (ROOT / "extensions/chromium").rglob("*") if path.is_file()}}
    (args.out / "checks.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
