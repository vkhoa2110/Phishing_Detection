"""One opted-in live classification, optionally followed by a public explanation.

Uses a new isolated database/profile and synthetic text. No RAG or verifier,
no retry, no quality/F1 claim. Requires an explicit --live-provider flag.
"""
import argparse
import json
from pathlib import Path
import socket
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    import uvicorn
    from playwright.sync_api import sync_playwright, expect
    from app.api.workspace import create_app
    from app.core.settings import Settings
    from app.services.workspace import WorkspaceSettings
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--live-provider", action="store_true", required=True)
    parser.add_argument("--explain-evidence", action="store_true", help="Allow one additional public explanation call within the shared budget.")
    args = parser.parse_args()
    if not Settings().api_key:
        raise SystemExit("Chưa cấu hình key ở máy chủ.")
    args.out.mkdir(parents=True, exist_ok=False)
    app = create_app("focused", workspace_settings=WorkspaceSettings(database=args.out / "application/test.sqlite3"))
    sock = socket.socket(); sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]; base = f"http://127.0.0.1:{port}"
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True); thread.start()
    report = {"live_provider": True, "synthetic_input": True, "isolated_account_database_and_browser": True, "retries": 0}
    try:
        deadline = time.monotonic() + 30
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline: raise RuntimeError("Isolated server did not start")
            time.sleep(.1)
        with sync_playwright() as runner:
            source = ROOT / "extensions/chromium"
            context = runner.chromium.launch_persistent_context(str(args.out / "browser-profile"), channel="chromium", headless=True,
                args=[f"--disable-extensions-except={source}", f"--load-extension={source}"], viewport={"width": 590, "height": 860})
            worker = context.service_workers[0] if context.service_workers else context.wait_for_event("serviceworker")
            worker.evaluate("base=>chrome.storage.local.set({base})", base)
            text = "Chúc mừng bạn nhận voucher mua sắm tại An Gia Store. Truy cập https://example.com/khuyen-mai/nhan-qua để đăng ký. Hãy nhập số thẻ, ngày hết hạn và mã bảo mật ở mặt sau thẻ để nhận ưu đãi. Bạn cần thanh toán trước phí xác nhận để nhận quà. Khi ngân hàng gửi mã OTP, vui lòng gửi mã OTP cho nhân viên để kích hoạt voucher trong 10 phút."
            with context.expect_page() as opened:
                worker.evaluate("text => handleContext({menuItemId: 'phishlens-selection', selectionText: text})", text)
            page = opened.value; page.wait_for_load_state("domcontentloaded")
            expect(page.locator("#connection-status")).to_contain_text("Sẵn sàng", timeout=60000)
            page.evaluate('enabled=>document.getElementById("explain-evidence").checked=enabled', args.explain_evidence)
            page.locator("#use-ai").check(); page.locator("#analyze").click(); expect(page.locator("#review")).to_be_visible()
            assert not page.locator("#use-rag").is_checked() and not page.locator("#save-content").is_checked()
            page.locator("#consent").check()
            with page.expect_response("**/api/extension/analyze", timeout=90000) as response:
                page.locator("#confirm").click()
            data = response.value.json()
            llm = data.get("llm", {}); observed = llm.get("telemetry", {})
            report.update(http_status=response.value.status, llm_status=llm.get("status"), error_code=llm.get("code"), risk=llm.get("verdict", {}).get("risk_level"),
                finish_reason=observed.get("finish_reason"), usage=llm.get("usage"), prompt=llm.get("prompt_version"),
                provider_calls=data.get("execution", {}).get("runtime", {}).get("calls_attempted"), history=data.get("history"),
                rag_requested=False, verifier_requested=False)
            explanation = llm.get("evidence_explanation", {})
            report["public_explanation"] = {"requested": args.explain_evidence, "status": explanation.get("status"),
                "code": explanation.get("code"), "prompt": explanation.get("prompt_version"),
                "usage": explanation.get("usage"), "finish_reason": explanation.get("telemetry", {}).get("finish_reason"),
                "classification_changed": explanation.get("classification_changed"), "evidence_count": len(explanation.get("evidence", [])),
                "summary_characters": len(explanation.get("summary", ""))}
            report["public_explanation"]["telemetry"] = explanation.get("telemetry", {})
            expect(page.locator("#result")).to_be_visible()
            page.screenshot(path=str(args.out / "extension_live_AI.png"), full_page=True)
            context.close()
    finally:
        server.should_exit = True; thread.join(timeout=15); sock.close()
        (args.out / "checks.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))
    if report.get("llm_status") != "ok" or report.get("provider_calls") != (2 if args.explain_evidence else 1) or (args.explain_evidence and report.get("public_explanation", {}).get("status") != "ok"):
        raise SystemExit("Live smoke chưa hoàn tất hợp lệ; đã giữ kết quả, không gọi lại tự động.")


if __name__ == "__main__":
    main()
