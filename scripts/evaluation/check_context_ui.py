"""Browser regression with recorded provider results; no new LLM calls.

Requires the app at --base-url and optional Playwright + Chromium installed.
The LLM path is fulfilled locally. The disabled-LLM path reaches the real app.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from app.fusion import fuse


def main():
    from playwright.sync_api import sync_playwright, expect
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--run", type=Path, default=ROOT / "artifacts/evaluations/context_regression_v2")
    args = parser.parse_args()
    rows = [json.loads(s) for s in (args.run / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    case = next(r for r in rows if r["id"] == "N26")
    assert case["llm_rag"]["status"] == "ok"
    config = json.loads((args.run / "manifest.json").read_text())["configuration"]
    decision = fuse("text", case["urls"], case["llm_rag"], case["invalid_urls"])
    fixture = {"mode": "text", "configuration": "ML / LLM độc lập + RAG", "final": decision,
        "assessments": decision["assessments"], "llm": case["llm_rag"], "urls": case["urls"],
        "invalid_urls": case["invalid_urls"], "retrieval": case["retrieval"], "ml": config["ml_status"],
        "timing": {"total_ms": case["llm_rag"]["elapsed_ms"]},
        "notice": "Nhận định hành vi áp dụng cho bản nội dung đã gửi LLM. Cảnh báo URL được đánh giá riêng tại máy."}
    out = args.run / "browser"
    out.mkdir(exist_ok=True)
    records = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for name, width, height in (("desktop", 1440, 1000), ("mobile", 390, 844)):
            page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
            errors, intercepted = [], []
            page.on("pageerror", lambda e: errors.append(str(e)))
            def handler(route):
                payload = route.request.post_data_json
                if payload.get("use_llm") is False:
                    route.continue_()
                else:
                    assert payload["consent"] is True and payload["include_ml"] is False
                    intercepted.append(True)
                    route.fulfill(status=200, content_type="application/json", body=json.dumps(fixture, ensure_ascii=False))
            page.route("**/api/analyze", handler)
            page.goto(args.base_url, wait_until="networkidle")
            expect(page.locator("#include-ml")).not_to_be_checked()
            expect(page.locator("#use-rag")).to_be_checked()
            page.locator("#input-text").fill(case["text"])
            page.locator("#analyze-button").click()
            expect(page.locator("#privacy-dialog")).to_be_visible()
            page.locator("#consent").check()
            page.locator("#confirm-send").click()
            expect(page.locator(".verdict.LOW")).to_be_visible()
            expect(page.locator(".url-assessment.HIGH")).to_contain_text("Nguy cơ cao")
            expect(page.locator(".conflict-note")).to_contain_text("URL cần cảnh giác")
            expect(page.locator(".verdict-eyebrow")).to_contain_text("HÀNH VI TRONG NỘI DUNG")
            assert page.locator(".source-link").count() > 0
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.screenshot(path=str(out / (name + ".png")), full_page=True)
            # Real local ML path, with the LLM explicitly disabled.
            page.locator("#use-llm").uncheck()
            page.locator("#input-text").fill("Thông báo tham khảo https://example.org/account")
            page.locator("#analyze-button").click()
            expect(page.locator(".verdict.UNKNOWN")).to_be_visible()
            expect(page.locator(".url-assessment.HIGH")).to_be_visible()
            assert len(intercepted) == 1 and errors == []
            records.append({"viewport": name, "width": width, "height": height, "passed": True,
                "llm_result": "replayed from completed diagnostic, no new provider request",
                "disabled_llm_path": "real local API + model", "page_errors": errors})
            page.close()
        browser.close()
    (out / "verification.json").write_text(json.dumps(records, indent=2) + "\n")
    print(json.dumps(records))


if __name__ == "__main__":
    main()
