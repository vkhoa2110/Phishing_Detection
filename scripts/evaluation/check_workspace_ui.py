"""Account/history end-to-end check on an EMPTY, ISOLATED demo database.

Creates synthetic accounts and their records; never calls the LLM provider.
Run the server with a separate PHISHLENS_DATABASE before using this script.
"""
import argparse
import json
from pathlib import Path


def main():
    from playwright.sync_api import expect, sync_playwright
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8002")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--isolated-database", action="store_true", required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    secret = "isolated-test-password-2026"
    updated_secret = "isolated-new-password-2026"
    events = []
    with sync_playwright() as runner:
        browser = runner.chromium.launch(headless=True)
        admin_context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = admin_context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        assert page.request.get(args.base_url + "/api/auth/session").json()["first_account"], "Refusing to touch a populated application database."

        def signup(target, email, name):
            target.goto(args.base_url + "/register", wait_until="networkidle")
            target.locator("#display-name").fill(name); target.locator("#email").fill(email)
            target.locator("#password").fill(secret); target.locator("#confirm-password").fill(secret)
            target.locator("#auth-submit").click(); target.wait_for_url("**/dashboard")
            expect(target.locator(".stat-card")).to_have_count(4)

        def overflow(target):
            assert not target.evaluate("document.documentElement.scrollWidth > innerWidth + 1")

        page.goto(args.base_url + "/dashboard", wait_until="networkidle")
        assert "/login" in page.url
        page.screenshot(path=str(args.out / "desktop_login.png"), full_page=True)
        signup(page, "admin-ui@example.org", "Quản trị thử nghiệm")
        expect(page.locator("[data-admin]")).to_be_visible()
        page.screenshot(path=str(args.out / "desktop_dashboard.png"), full_page=True)
        page.goto(args.base_url + "/check", wait_until="networkidle")
        expect(page.locator("#save-history")).to_be_checked()
        expect(page.locator("#save-content")).not_to_be_checked()
        page.locator("#use-llm").uncheck()
        page.locator("#input-text").fill("Kiểm tra riêng đường dẫn https://example.org/.")
        with page.expect_response("**/api/analyze") as response:
            page.locator("#analyze-button").click()
        result = response.value.json()
        assert result["llm"]["status"] == "disabled" and result["execution"]["runtime"]["calls_attempted"] == 0
        record = result["history"]["id"]
        page.locator(".history-saved a").click()
        expect(page.locator("#record-dialog")).to_be_visible()
        expect(page.locator("#record-content")).to_contain_text("không được lưu")
        page.locator("#record-title").fill("Lượt kiểm tra cần xem lại")
        attack = '<img src=x onerror="window.workspaceXSS=1">'
        page.locator("#record-note").fill(attack)
        page.locator("#record-form button[type=submit]").click()
        expect(page.locator(".record-title")).to_have_text("Lượt kiểm tra cần xem lại")
        page.locator("#favorite-record").click()
        expect(page.locator("#favorite-record")).to_contain_text("Bỏ đánh dấu")
        with page.expect_download() as download:
            page.locator("#export-record").click()
        exported = json.loads(Path(download.value.path()).read_text())
        assert exported["id"] == record and exported["snapshot"] is None
        page.locator("#close-record").click()
        page.locator("#history-search").fill("cần xem lại")
        page.locator("#history-filters button").click()
        expect(page.locator(".record-card")).to_have_count(1)
        page.locator("#history-favorite").check()
        expect(page.locator(".record-card")).to_have_count(1)
        assert page.evaluate("window.workspaceXSS || 0") == 0
        assert page.locator("#portal-content img").count() == 0
        overflow(page)
        page.screenshot(path=str(args.out / "desktop_history.png"), full_page=True)
        events.append({"case": "signup_admin_local_analysis_history_edit_favorite_export_search", "passed": True})

        member_context = browser.new_context(viewport={"width": 390, "height": 844})
        member = member_context.new_page()
        member.on("pageerror", lambda error: errors.append(str(error)))
        member.goto(args.base_url + "/register", wait_until="networkidle")
        member.screenshot(path=str(args.out / "mobile_register.png"), full_page=True)
        signup(member, "member-ui@example.org", "Thành viên thử nghiệm")
        expect(member.locator("[data-admin]")).to_be_hidden()
        assert member.request.get(args.base_url + "/api/history/" + record).status == 404
        assert member.request.get(args.base_url + "/api/admin/users").status == 403
        assert member.request.get(args.base_url + "/api/history").json()["total"] == 0
        overflow(member)
        member.screenshot(path=str(args.out / "mobile_dashboard.png"), full_page=True)
        member.goto(args.base_url + "/account", wait_until="networkidle")
        member.locator("#profile-name").fill("Thành viên đã cập nhật")
        member.locator("#portal-content .portal-form").first.locator("button[type=submit]").click()
        expect(member.locator("[data-account-name]")).to_have_text("Thành viên đã cập nhật")
        member.locator("#current-password").fill(secret)
        member.locator("#new-password").fill(updated_secret); member.locator("#repeat-password").fill(updated_secret)
        member.locator("#portal-content .portal-form").last.locator("button[type=submit]").click()
        expect(member.locator("#workspace-toast")).to_contain_text("Đã đổi mật khẩu")
        overflow(member)
        member.screenshot(path=str(args.out / "mobile_account.png"), full_page=True)
        member.goto(args.base_url + "/check", wait_until="networkidle")
        member.locator("#use-llm").uncheck(); member.locator("#save-content").check()
        member.locator("#input-text").fill("Liên hệ demo@example.org. https://example.org/?secret=do-not-store")
        with member.expect_response("**/api/analyze") as saved_response:
            member.locator("#analyze-button").click()
        saved_result = saved_response.value.json()
        assert saved_result["execution"]["runtime"]["calls_attempted"] == 0
        member.locator(".history-saved a").click()
        expect(member.locator("#record-dialog")).to_be_visible()
        member.locator("#record-content details summary").click()
        expect(member.locator("#record-content pre")).to_contain_text("[EMAIL]")
        assert "do-not-store" not in member.locator("#record-content").inner_text()
        member.locator("#close-record").click(); overflow(member)
        events.append({"case": "member_isolation_profile_password_opt_in_redacted_history", "passed": True})

        page.goto(args.base_url + "/admin", wait_until="networkidle")
        expect(page.locator(".admin-user")).to_have_count(2)
        member_row = page.locator(".admin-user").filter(has_text="member-ui@example.org")
        page.once("dialog", lambda dialog: dialog.accept())
        member_row.get_by_role("button", name="Khóa tài khoản", exact=True).click()
        expect(member_row).to_contain_text("Đã khóa")
        assert member.request.get(args.base_url + "/api/history").status == 401
        page.once("dialog", lambda dialog: dialog.accept())
        member_row.get_by_role("button", name="Mở khóa", exact=True).click()
        expect(member_row).to_contain_text("Đang hoạt động")
        page.screenshot(path=str(args.out / "desktop_admin.png"), full_page=True)
        member.goto(args.base_url + "/login", wait_until="networkidle")
        member.locator("#email").fill("member-ui@example.org"); member.locator("#password").fill(updated_secret)
        member.locator("#auth-submit").click(); member.wait_for_url("**/dashboard")
        member.locator("[data-logout]").click(); member.wait_for_url("**/login")
        assert member.request.get(args.base_url + "/api/history").status == 401
        events.append({"case": "admin_suspend_unlock_session_revocation_new_password_login_logout", "passed": True})
        page.set_viewport_size({"width": 320, "height": 844}); page.goto(args.base_url + "/dashboard", wait_until="networkidle"); overflow(page)
        assert not errors, errors
        browser.close()
    report = {"cases": events, "passed": len(events), "browser_errors": errors, "provider_calls": 0,
              "real_local_URL_model": True, "temporary_accounts_only": True, "private_history_access_denied": True}
    (args.out / "checks.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
