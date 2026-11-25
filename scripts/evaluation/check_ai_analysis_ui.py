"""Check visible AI analysis on desktop/mobile using fixtures; no provider calls."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.domain.clarification import plan
from app.domain.decisions import fuse
from app.services.llm.core import parse_core


def fixture(name, ml):
    risk = name if name in {"HIGH", "WARNING", "LOW", "UNKNOWN"} else "LOW"
    text = 'Hãy gửi mã xác thực cho tôi. <img src=x onerror="window.fixtureExecuted=1">'
    alarm = risk in {"HIGH", "WARNING"}
    llm = {**parse_core(json.dumps({"risk_level": risk,
        "context_kind": "scam_request" if alarm else "insufficient" if risk == "UNKNOWN" else "routine",
        "reason_code": "secret_request" if alarm else "missing_context" if risk == "UNKNOWN" else "no_fraud_evidence",
        "quotes": [text] if alarm else [],
        "missing_context": ["requested_action", "initiated_by_user"] if risk == "UNKNOWN" else []}), text),
        "model": "UI fixture", "input_used": text, "prompt_version": "UI fixture",
        "usage": {"total_tokens": 1}}
    if name == "error":
        llm = {"status": "error", "code": "TIMEOUT", "message": "Lỗi chờ AI mô phỏng.", "rag": False}
    elif name == "disabled":
        llm = {"status": "disabled", "message": "Chưa bật AI.", "rag": False}
    mode = "url" if name == "url" else "text"
    urls = [{"id": "URL-1", "url": "https://example.org/", "status": "ok", "risk_level": "HIGH",
             "score": .9, "warning_threshold": .5, "high_threshold": .7}] if name in {"conflict", "url"} else []
    decision = fuse(mode, urls, llm, [])
    return {"mode": mode, "llm": llm, "final": decision, "assessments": decision["assessments"],
        "urls": urls, "invalid_urls": [], "ml": ml, "clarification": plan(llm),
        "retrieval": {"status": "disabled", "sources": []},
        "timing": {"total_ms": 1}, "notice": "Kiểm giao diện bằng fixture; không chấm chất lượng model."}


def main():
    from playwright.sync_api import expect, sync_playwright
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    with urlopen(args.base_url + "/api/status", timeout=30) as response:
        status = json.load(response)
    host = urlsplit(args.base_url).netloc
    records = []
    paths = [ROOT / p for p in ("app/static/app.js", "app/static/index.html", "app/static/styles.css")]
    before = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    with sync_playwright() as runner:
        browser = runner.chromium.launch(headless=True)
        for viewport, width in (("desktop", 1440), ("mobile", 390), ("small_mobile", 320)):
            page = browser.new_page(viewport={"width": width, "height": 1000})
            errors, requests = [], []
            selected = {"body": fixture("LOW", status["ml"])}
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("**/*", lambda route: route.continue_() if urlsplit(route.request.url).netloc == host else route.abort())
            page.route("**/api/status", lambda route: route.fulfill(json={**status, "llm": {**status["llm"], "has_api_key": True}}))

            def analyze(route):
                body = route.request.post_data_json
                assert body["consent"] is True
                requests.append(body["mode"])
                route.fulfill(json=deepcopy(selected["body"]))

            page.route("**/api/analyze", analyze)
            page.goto(args.base_url, wait_until="networkidle")
            expect(page.locator("#api-status")).to_contain_text("Máy chủ đã cấu hình")
            for name in ("HIGH", "WARNING", "LOW", "UNKNOWN", "error", "disabled", "conflict", "url"):
                selected["body"] = fixture(name, status["ml"])
                page.locator("#tab-url" if name == "url" else "#tab-text").click()
                page.locator("#input-text").fill("https://example.org/" if name == "url" else "Nội dung kiểm giao diện.")
                page.locator("#analyze-button").click()
                expect(page.locator("#privacy-dialog")).to_be_visible()
                page.locator("#consent").check()
                page.locator("#confirm-send").click()
                panel = page.locator("#ai-analysis")
                expect(panel).to_be_visible()
                assert not panel.evaluate("el => Boolean(el.closest('details'))")
                assert panel.bounding_box()["y"] < page.locator(".actions-section").bounding_box()["y"]
                expect(page.locator(".technical-details")).not_to_have_attribute("open", "")
                if name in {"error", "disabled"}:
                    expect(panel.locator(".ai-assessment")).to_have_count(0)
                    expect(panel.locator(".ai-status")).to_have_text("AI đang tắt" if name == "disabled" else "AI chưa hoàn tất")
                    expect(panel.locator("#clarification-panel")).to_have_count(0)
                else:
                    expect(panel.locator(".ai-status")).to_have_text("Đã nhận kết quả AI")
                    expect(panel.locator(".analysis-summary")).to_have_text(selected["body"]["llm"]["verdict"]["summary"])
                    expect(panel.locator(".ai-model")).to_have_text("UI fixture")
                    expect(panel.locator(".evidence-item")).to_have_count(1 if name in {"HIGH", "WARNING"} else 0)
                if name == "UNKNOWN":
                    expect(panel.locator("#clarification-panel")).to_be_visible()
                    expect(panel.locator(".clarification-select")).to_have_count(2)
                if name == "conflict":
                    expect(page.locator(".result-main > :first-child")).to_have_class("url-assessment HIGH")
                    expect(panel.locator(".ai-assessment")).to_contain_text("Chưa thấy dấu hiệu")
                if name == "url":
                    expect(panel.locator("h4").first).to_have_text("Nhận xét đường dẫn bằng AI")
                    expect(panel.locator(".ai-context")).to_have_count(0)
                assert panel.locator("img, script, a.url-text").count() == 0
                assert page.evaluate("window.fixtureExecuted || 0") == 0
                assert not page.evaluate("document.documentElement.scrollWidth > innerWidth + 1")
                assert not errors, errors
                if name in {"HIGH", "LOW"}:
                    page.locator("#results-panel").screenshot(path=str(args.out / f"{viewport}_{name}.png"), animations="disabled")
                records.append({"viewport": viewport, "case": name, "AI_analysis_visible_outside_details": True,
                    "before_recommendations": True, "XSS_executed": False, "overflow": False, "page_errors": []})
            assert len(requests) == 8
            page.close()
        browser.close()
    after = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    assert before == after
    summary = {"passed": len(records), "cases": records, "provider_calls": 0, "source_sha256": after}
    (args.out / "checks.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"passed": len(records), "provider_calls": 0, "source_unchanged": True}))


if __name__ == "__main__":
    main()
