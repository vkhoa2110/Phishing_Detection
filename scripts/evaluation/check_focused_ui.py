"""Replay focused UI clarification/consent boundaries; zero provider calls."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.domain.clarification import plan
from app.domain.decisions import fuse
from app.services.llm.core import parse_core


def fixture(text, *, failed=False):
    parsed = parse_core(json.dumps({"risk_level": "UNKNOWN", "context_kind": "insufficient",
        "reason_code": "missing_context", "quotes": [], "missing_context": ["secret_destination", "initiated_by_user"]}), text)
    llm = {**parsed, "input_used": text, "input_modified": True, "model": "UI-fixture",
           "prompt_version": "offline-UI-fixture", "usage": {"total_tokens": 1}}
    if failed:
        llm = {"status": "error", "code": "OUTPUT_TRUNCATED", "message": "Phản hồi kiểm thử bị cắt.", "rag": False}
    decision = fuse("text", [], llm, [])
    clarification = plan(llm)
    if not failed:
        clarification["notice"] += ' <img src=x onerror="window.__clarification_xss=1">'
    return {"mode": "text", "configuration": "Offline UI fixture", "final": decision,
        "assessments": decision["assessments"], "llm": llm, "urls": [], "invalid_urls": [],
        "retrieval": {"status": "disabled", "sources": [], "reason": "UI fixture"},
        "timing": {"total_ms": 1, "ml_ms": 0, "llm_ms": 1, "rag_ms": 0},
        "clarification": clarification, "notice": "UI replay, không đo chất lượng mô hình."}


def main():
    from playwright.sync_api import expect, sync_playwright
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    records = []
    host = urlsplit(args.base_url).netloc
    with sync_playwright() as browser_api:
        browser = browser_api.chromium.launch(headless=True)
        for name, width in (("desktop", 1440), ("mobile", 390)):
            page = browser.new_page(viewport={"width": width, "height": 1000})
            failures, intercepted, clarifications = [], [], []
            page.on("pageerror", lambda error: failures.append(str(error)))
            page.route("**/*", lambda route: route.continue_() if urlsplit(route.request.url).netloc == host else route.abort())
            def analyze(route):
                body = route.request.post_data_json
                approved = body.get("llm_text", "")
                assert body["consent"] is True
                assert "private.example" not in approved and "khoa@" not in approved
                intercepted.append(True)
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps(fixture(approved, failed=len(intercepted) == 2), ensure_ascii=False))
            page.route("**/api/analyze", analyze)
            page.on("request", lambda request: clarifications.append(True) if request.url.endswith("/api/clarify/preview") else None)
            page.goto(args.base_url, wait_until="networkidle")
            expect(page.locator("#api-status")).to_contain_text("Máy chủ đã cấu hình", timeout=30000)
            page.locator("#input-text").fill("Hỗ trợ mã xác minh. Liên hệ khoa@example.org https://private.example/?token=secret")
            page.locator("#analysis-form").evaluate("form => form.requestSubmit()")
            expect(page.locator("#privacy-dialog")).to_be_visible()
            assert not intercepted
            page.locator("#consent").check()
            page.locator("#preview-text").fill("Một người đề nghị hỗ trợ xác minh mã.")
            expect(page.locator("#consent")).not_to_be_checked()
            page.locator("#consent").check(); page.locator("#confirm-send").click()
            expect(page.locator("#clarification-panel")).to_be_visible()
            assert len(intercepted) == 1
            assert page.locator("#clarification-panel img").count() == 0
            assert page.evaluate("window.__clarification_xss || 0") == 0
            page.locator(".clarification-select").first.select_option("third_party")
            page.screenshot(path=str(args.out / f"{name}.png"), full_page=True)
            page.locator("#clarification-continue").click()
            expect(page.locator("#privacy-dialog")).to_be_visible()
            expect(page.locator("#consent")).not_to_be_checked()
            assert len(intercepted) == 1 and len(clarifications) == 1
            preview = page.locator("#preview-text").input_value()
            assert "đọc hoặc gửi mã" in preview and "private.example" not in preview and "khoa@" not in preview
            page.locator("#consent").check(); page.locator("#confirm-send").click()
            expect(page.locator("#result-content")).to_be_visible()
            expect(page.locator("#clarification-panel")).to_have_count(0)
            assert len(intercepted) == 2 and not failures
            overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 2")
            assert not overflow
            records.append({"viewport": name, "analysis_requests_replayed": len(intercepted),
                "local_clarification_requests": len(clarifications), "reconfirmation_checked": True,
                "private_original_restored": False, "XSS_executed": False, "horizontal_overflow": overflow,
                "page_errors": failures, "external_provider_calls": 0})
            page.close()
        browser.close()
    (args.out / "checks.json").write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(records, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
