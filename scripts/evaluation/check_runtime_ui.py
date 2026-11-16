"""Browser replay of server-managed settings and exact consent destination; no LLM."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.evaluation.check_focused_ui import fixture


def main():
    import httpx
    from playwright.sync_api import expect, sync_playwright
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-url", default="http://127.0.0.1:8001")
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    if a.out.exists(): raise ValueError("Preserve previous browser checks.")
    a.out.mkdir(parents=True)
    status = httpx.get(a.base_url + "/api/status", timeout=30).json()
    assert status["runtime"]["connection_mode"] == "server_managed"
    host, provider = urlsplit(a.base_url).netloc, urlsplit(status["llm"]["endpoint"]).hostname
    records = []
    with sync_playwright() as runner:
        browser = runner.chromium.launch(headless=True)
        for name, width in (("desktop", 1440), ("mobile", 390)):
            page = browser.new_page(viewport={"width": width, "height": 900})
            calls, errors = [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("**/*", lambda route: route.continue_() if urlsplit(route.request.url).netloc == host else route.abort())
            def analyze(route):
                body = route.request.post_data_json
                assert not set(body) & {"api_key", "endpoint", "model"}
                assert body["consent"] and "private.example" not in body["llm_text"]
                calls.append(body)
                route.fulfill(status=200, content_type="application/json", body=json.dumps(fixture(body["llm_text"])))
            page.route("**/api/analyze", analyze)
            page.goto(a.base_url, wait_until="networkidle")
            page.locator("#settings-button").click()
            page.locator(".api-settings summary").click()
            expect(page.locator("#connection-fields")).to_be_hidden()
            expect(page.locator("#server-connection-summary")).to_contain_text(provider)
            # Even programmatically filled hidden fields must never be sent.
            page.evaluate('document.getElementById("api-key").value="client-secret-never-send"')
            page.screenshot(path=str(a.out / f"{name}.png"), full_page=True)
            page.locator("#close-settings").click()
            page.locator("#input-text").fill("Hỗ trợ mã xác minh https://private.example/?token=secret")
            page.locator("#analysis-form").evaluate("form => form.requestSubmit()")
            expect(page.locator("#privacy-dialog")).to_be_visible()
            expect(page.locator("#preview-provider")).to_contain_text(provider)
            assert not calls
            page.locator("#preview-text").fill("Hỗ trợ mã xác minh. Email mới fresh@example.org")
            page.locator("#consent").check(); page.locator("#confirm-send").click()
            expect(page.locator("#consent")).not_to_be_checked()
            expect(page.locator("#preview-error")).to_contain_text("chuẩn hóa thêm")
            assert not calls and "fresh@example.org" not in page.locator("#preview-text").input_value()
            page.locator("#consent").check(); page.locator("#confirm-send").click()
            expect(page.locator("#result-content")).to_be_visible()
            assert len(calls) == 1 and not errors
            assert not page.evaluate("document.documentElement.scrollWidth > innerWidth + 2")
            records.append({"viewport": name, "server_connection_fields_hidden": True,
                "no_client_credentials_or_overrides_in_request": True, "consent_destination_matches_server": True,
                "new_PII_in_edited_preview_masked_before_new_consent": True,
                "analysis_calls_replayed": len(calls), "provider_calls": 0, "page_errors": errors})
            page.close()
        page = browser.new_page()
        missing = deepcopy(status); missing["llm"]["has_api_key"] = False
        page.route("**/*", lambda route: route.continue_() if urlsplit(route.request.url).netloc == host else route.abort())
        page.route("**/api/status", lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(missing)))
        unexpected = []
        page.route("**/api/analyze", lambda route: (unexpected.append(True), route.abort()))
        page.goto(a.base_url, wait_until="networkidle")
        page.locator("#input-text").fill("Thông báo họp.")
        page.locator("#analysis-form").evaluate("form => form.requestSubmit()")
        expect(page.locator("#form-error")).to_contain_text("Dịch vụ AI chưa sẵn sàng")
        assert not unexpected
        records.append({"missing_server_key_blocks_AI": True, "asks_consumer_for_key": False, "provider_calls": 0})
        browser.close()
    (a.out / "checks.json").write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(records, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
