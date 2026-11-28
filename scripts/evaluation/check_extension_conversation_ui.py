"""Conversation selection through the real extension and scoped backend.

Chat DOM and AI replies are fixtures. No real account, private chat, destination
URL or external provider is contacted. Optional host permission is pregranted
in an isolated manifest copy; shipped JavaScript stays unchanged.
"""
import argparse
import asyncio
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import socket
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

ZALO = """<!doctype html><html lang="vi"><meta charset="utf-8"><title>Zalo · Hội thoại minh họa</title><style nonce="fixture">
*{box-sizing:border-box}body{margin:0;font:15px/1.6 system-ui;color:#26304a;background:#eef1f7}main{display:grid;grid-template-columns:240px 1fr 220px;height:100vh}aside{background:white;padding:25px;border-right:1px solid #dde3ef}.chat-title{background:white;padding:20px;font-weight:700}#messageView{height:calc(100vh - 140px);overflow:auto;padding:15px 28px}.message-item{width:80%;background:white;border-radius:12px;padding:10px 15px;margin:0 0 10px}.me{margin-left:auto;background:#dceaff}.sender-name{font-size:11px;color:#8091aa}.message-time{font-size:10px;color:#8a97ac}.compose{background:white;padding:18px}.hidden{display:none}.message-item.limit-compact{height:18px;padding:0;margin:0}.message-item.limit-long{height:22px;overflow:hidden;padding:0;margin:0}
</style><main><aside><h3>Danh sách trò chuyện</h3><p>SIDEBAR_PRIVATE</p><p>Khách hàng khác</p></aside><section id="chatView" data-conversation-id="alpha"><header class="chat-title">Hội thoại thử nghiệm · Không phải tài khoản thật</header><div id="messageView">
<article class="message-item" data-message-id="a"><span class="sender-name">PERSON_PRIVATE_A</span><div class="message-text">Chào bạn, nhiệm vụ đầu đã hoàn thành.</div><time class="message-time">14:01</time></article>
<article class="message-item me" data-message-id="b"><div class="message-text">Tôi đã nhận hoa hồng 20.000 đồng.</div><time class="message-time">14:02</time></article>
<article class="message-item" data-message-id="c"><span class="sender-name">PERSON_PRIVATE_A</span><div class="message-text">Muốn rút tiền, hãy chuyển trước 2.000.000 đồng phí xác nhận. <a href="https://example.org/rut-tien">Xem điều kiện</a></div><time class="message-time">14:03</time></article>
<article class="message-item" data-message-id="d"><span class="sender-name">PERSON_PRIVATE_B</span><div class="message-text">Không hỏi ngân hàng, cứ làm theo hướng dẫn trong nhóm.</div></article>
<article class="message-item hidden" data-message-id="secret"><div class="message-text">HIDDEN_PRIVATE</div></article>
<div hidden>UNLOADED_PRIVATE_HISTORY</div></div><div class="compose" contenteditable="true">DRAFT_PRIVATE</div></section><aside><h3>Thông tin nhóm</h3>MEMBER_PRIVATE</aside></main></html>"""

PLATFORMS = {
    "zalo": ("https://chat.zalo.me/", "zalo", "Zalo Web", "chat-assist-enabled"),
    "messenger": ("https://www.messenger.com/t/fixture-alpha", "messenger", "Messenger", "chat-assist-messenger"),
    "facebook": ("https://www.facebook.com/messages/t/fixture-alpha", "messenger", "Messenger", "chat-assist-messenger"),
    "telegram-a": ("https://web.telegram.org/a/#fixture-alpha", "telegram", "Telegram Web", "chat-assist-telegram"),
    "telegram-k": ("https://web.telegram.org/k/#fixture-alpha", "telegram", "Telegram Web", "chat-assist-telegram"),
}


def fixture(kind):
    """Separate rendered structures; class/attribute names follow public Web A/K
    source. Messenger's accessibility structure remains an unverified adapter.
    Keeping IDs used by this harness does not affect the non-Zalo selectors.
    """
    text = ZALO
    if kind in ("messenger", "facebook"):
        text = text.replace('<section id="chatView"', '<section role="main" id="chatView"')
        text = text.replace('<div id="messageView">', '<div id="messageView" role="grid" aria-label="Messages in conversation">')
        text = text.replace('<article ', '<article role="row" ').replace('class="message-text"', 'class="message-text" dir="auto"')
        text = text.replace('class="sender-name"', 'class="sender-name" data-sender-name=""').replace('class="message-item me"', 'class="message-item me" data-from-me="true"')
    elif kind == "telegram-a":
        text = text.replace('<section id="chatView"', '<section id="MiddleColumn"').replace('</section><aside>', '</section><aside>')
        text = text.replace('<div id="messageView">', '<div id="messageView" class="MessageList">')
        text = text.replace('class="message-item', 'class="Message message-item').replace('message-item me"', 'message-item me own"')
        text = text.replace('class="message-text"', 'class="message-text text-content"')
        text = text.replace('<span class="sender-name">', '<div class="message-title"><span class="sender-title sender-name">').replace('</span><div class="message-text', '</span></div><div class="message-text')
    elif kind == "telegram-k":
        text = text.replace('<section id="chatView"', '<section id="column-center"').replace('<header class="chat-title">', '<div class="chat"><header class="chat-title">').replace('</section><aside>', '</div></section><aside>')
        text = text.replace('<div id="messageView">', '<div id="messageView" class="bubbles-inner">')
        text = text.replace('class="message-item', 'class="bubble message-item').replace('message-item me"', 'message-item me is-out"')
        text = text.replace('data-message-id=', 'data-mid=').replace('class="message-text"', 'class="message-text message"')
        text = text.replace('<span class="sender-name">', '<div class="bubble-content"><span class="sender-name name">').replace('</span><div class="message-text', '</span></div><div class="message-text')
    return text


def main():
    import httpx
    import uvicorn
    from playwright.sync_api import sync_playwright, expect
    from app.api.workspace import create_app
    from app.core.settings import Settings
    from app.services.workspace import WorkspaceSettings
    from app.services.llm.conversation import SYSTEM
    from app.services.llm.decision_explanation import SYSTEM as EXPLANATION
    from tests.api.test_baseline import FakeML
    from tests.api.test_candidate_app import OrderedRAG
    from tests.api.test_focused_app import packet

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--platform", choices=PLATFORMS, default="zalo")
    args = parser.parse_args(); args.out.mkdir(parents=True, exist_ok=False)
    url, platform_id, label, toggle = PLATFORMS[args.platform]
    html = fixture(args.platform)
    chat_view = "#MiddleColumn" if args.platform == "telegram-a" else "#column-center .chat" if args.platform == "telegram-k" else "#chatView"
    message_id = "data-mid" if args.platform == "telegram-k" else "data-message-id"
    checks, calls, external, errors = [], [], [], []
    complete = False
    delay = {"seconds": .08}

    async def provider(request):
        body = json.loads(request.content); calls.append(body)
        assert not any(value in json.dumps(body) for value in ("SIDEBAR_PRIVATE", "DRAFT_PRIVATE", "HIDDEN_PRIVATE", "UNLOADED_PRIVATE_HISTORY", "MEMBER_PRIVATE", "PERSON_PRIVATE"))
        await asyncio.sleep(delay["seconds"])
        if body["messages"][0]["content"] == EXPLANATION:
            return packet({"summary": "Đoạn hội thoại yêu cầu nạp thêm tiền trước khi được rút, cần xác minh bên nhận.",
                "evidence": [{"index": 0, "explanation": "Yêu cầu đóng tiền trước để rút tiền có nguy cơ dẫn dụ chuyển thêm tiền."}]})
        assert body["messages"][0]["content"] == SYSTEM
        return packet({"risk_level": "HIGH", "context_kind": "scam_request", "reason_code": "advance_fee",
                       "quotes": ["chuyển trước 2.000.000 đồng phí xác nhận"], "missing_context": []})

    app = create_app("focused", replace(Settings(), api_key="conversation-fixture-only"), transport=httpx.MockTransport(provider),
        model_service=FakeML(), rag_service=OrderedRAG([]), workspace_settings=WorkspaceSettings(database=args.out / "application/test.sqlite3"))
    sock = socket.socket(); sock.bind(("127.0.0.1", 0)); base = "http://127.0.0.1:" + str(sock.getsockname()[1])
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True); thread.start()
    source = args.out / "test-extension"; shutil.copytree(ROOT / "extensions/chromium", source)
    manifest = json.loads((source / "manifest.json").read_text()); manifest["host_permissions"].append("<all_urls>")
    (source / "manifest.json").write_text(json.dumps(manifest))
    report = {}
    try:
        deadline = time.monotonic() + 30
        while not server.started:
            if time.monotonic() > deadline: raise RuntimeError("Server did not start")
            time.sleep(.05)
        with sync_playwright() as runner:
            context = runner.chromium.launch_persistent_context(str(args.out / "browser-profile"), channel="chromium", headless=True,
                args=[f"--disable-extensions-except={source.resolve()}", f"--load-extension={source.resolve()}", "--screen-info={1600x1000}", "--window-size=1280,900"],
                viewport={"width": 1280, "height": 900}, screen={"width": 1600, "height": 1000})
            context.on("page", lambda page: page.on("pageerror", lambda error: errors.append(str(error))))
            def network(route):
                if route.request.url.startswith(base + "/"): route.continue_()
                elif route.request.url.startswith(url.split("#")[0]): route.fulfill(content_type="text/html", body=html, headers={"Content-Security-Policy": "default-src 'none'; style-src 'nonce-fixture'; img-src data:; script-src 'none'"})
                else: external.append(route.request.url); route.abort()
            context.route("http://**/*", network); context.route("https://**/*", network)
            worker = context.service_workers[0] if context.service_workers else context.wait_for_event("serviceworker")
            detected = worker.evaluate("""() => ({yes:['https://chat.zalo.me/','https://www.messenger.com/t/a','https://www.facebook.com/messages/t/a','https://web.facebook.com/messages/','https://web.telegram.org/a/#a','https://web.telegram.org/k/#a'].map(url=>PhishLensChatPlatforms.detect(url)?.id),no:['http://chat.zalo.me/','https://chat.zalo.me.attacker.invalid/','https://www.facebook.com/','https://www.facebook.com/messages-fake/','https://web.telegram.org.attacker.invalid/a/','https://web.telegram.org/a/:123','https://web.telegram.org:9000/a/','https://user:password@web.telegram.org/a/'].map(url=>PhishLensChatPlatforms.detect(url))})""")
            assert detected["yes"] == ["zalo", "messenger", "messenger", "messenger", "telegram", "telegram"] and not any(detected["no"])
            checks.append("platform_registry_rejects_lookalikes_nonHTTPS_Facebook_feed_credentials_and_custom_ports")
            worker.evaluate("base => chrome.storage.local.set({base,theme:'dark'})", base)
            panel = context.new_page(); panel.on("dialog", lambda dialog: dialog.accept())
            panel.goto(worker.url.replace("background.js", "check.html?panel=1"))
            expect(panel.locator("#connection-status")).to_contain_text("Sẵn sàng", timeout=30000)
            def load_visible():
                expect(panel.locator("#conversation-picker")).to_be_visible()
                panel.locator("#conversation-mode").select_option("visible")
                panel.locator("#conversation-load").click()
                expect(panel.locator("#conversation-continue")).to_be_visible()
            page = context.new_page(); page.goto(url); page.bring_to_front()
            expect(panel.locator("#read-conversation")).to_be_visible()
            assert not calls and page.locator("[data-phishlens-chat-helper]").count() == 0
            checks.append("chat_opening_does_not_read_or_send_AI_and_helper_is_off_by_default")
            panel.locator("#nav-assistant").click(); panel.locator("#" + toggle).check()
            expect(page.locator("[data-phishlens-chat-helper]")).to_be_visible()
            site_preferences = worker.evaluate("async()=> (await chrome.storage.local.get('chatAssistSites')).chatAssistSites")
            assert site_preferences == {key: key == platform_id for key in ("zalo", "messenger", "telegram")}
            assert not calls
            panel.locator("#" + toggle).uncheck()
            expect(page.locator("[data-phishlens-chat-helper]")).to_have_count(0)
            assert "phishlens-" + platform_id not in [row["id"] for row in worker.evaluate("()=>chrome.scripting.getRegisteredContentScripts()")]
            panel.locator("#nav-check").click()
            checks.append("optional_platform_helper_registers_and_unregisters_without_reading_or_sending_chat")
            panel.locator("#read-conversation").click()
            load_visible()
            expect(panel.locator("#conversation-picker")).to_be_visible()
            expect(panel.locator(".conversation-message")).to_have_count(4)
            expect(panel.locator("#conversation-source")).to_contain_text(label)
            text = panel.locator("#conversation-messages").inner_text()
            assert not any(value in text for value in ("SIDEBAR_PRIVATE", "DRAFT_PRIVATE", "HIDDEN_PRIVATE", "MEMBER_PRIVATE", "PERSON_PRIVATE"))
            assert [el.input_value() for el in panel.locator(".conversation-message select").all()] == ["Người 1", "Bạn", "Người 1", "Người 2"]
            assert not calls
            checks.append("reader_scopes_to_visible_chat_excludes_sidebar_composer_hidden_history_and_anonymizes_senders")
            panel.screenshot(path=str(args.out / "01_conversation_selection.png"))
            panel.set_viewport_size({"width": 390, "height": 850})
            assert panel.evaluate("document.documentElement.scrollWidth <= innerWidth")
            panel.screenshot(path=str(args.out / "01_conversation_selection_narrow.png"))
            panel.set_viewport_size({"width": 1280, "height": 900})
            checks.append("conversation_picker_fits_a_390px_panel_without_horizontal_overflow")
            panel.locator(".conversation-message input").first.uncheck()
            panel.locator(".conversation-message select").last.select_option("Người khác")
            panel.locator("#conversation-continue").click()
            expect(panel.locator("#review")).to_be_visible()
            assert "chuyển trước" in panel.locator("#approved-text").input_value()
            approved = panel.locator("#approved-text").input_value()
            assert "nhiệm vụ đầu" not in approved and "Tôi đã nhận hoa hồng" in approved and "https://example.org/rut-tien" in approved
            assert "Tin 01 | Bạn" in approved and "Tin 03 | Người khác" in approved and not calls
            assert label.upper() in approved
            assert not panel.locator("#consent").is_checked()
            checks.append("selected_turns_preserve_order_roles_actual_URL_and_wait_for_consent")
            panel.locator("#consent").check(); panel.locator("#confirm").click()
            expect(panel.locator("#result")).to_be_visible(timeout=15000)
            assert len(calls) == 2 and "ĐOẠN HỘI THOẠI" in panel.locator(".result-hero").inner_text()
            expect(panel.locator(".conversation-evidence")).to_be_visible()
            panel.screenshot(path=str(args.out / "02_conversation_result.png"))
            panel.locator(".conversation-evidence").click()
            assert page.evaluate("CSS.highlights.has('phishlens-chat-evidence')")
            checks.append("classification_and_public_explanation_use_conversation_prompt_and_focus_only_selected_messages")
            stored = worker.evaluate("async () => ({local:await chrome.storage.local.get(null),session:await chrome.storage.session.get(null)})")
            serialized = json.dumps(stored, ensure_ascii=False)
            assert not any(term in serialized for term in ("Tôi đã nhận", "chuyển trước", "PERSON_PRIVATE", "Muốn rút"))
            checks.append("extension_storage_contains_job_pointers_not_raw_chat_or_transcript")
            # A changed conversation must invalidate both source highlighting and sending.
            page.locator(chat_view).evaluate("el=>el.dataset.conversationId='beta'")
            expect(panel.locator("#error")).to_contain_text("thay đổi", timeout=5000)
            assert not page.evaluate("CSS.highlights.has('phishlens-chat-evidence')")
            assert len(calls) == 2
            checks.append("conversation_identity_change_clears_marks_and_rejects_stale_context_without_new_AI")
            # Selecting a new snapshot and then mutating a selected message blocks consent.
            panel.locator("#conversation-reselect").click()
            load_visible()
            expect(panel.locator("#conversation-picker")).to_be_visible()
            panel.locator("#conversation-continue").click()
            expect(panel.locator("#review")).to_be_visible()
            assert "chuyển trước" in panel.locator("#approved-text").input_value()
            panel.locator("#consent").check()
            page.locator('[' + message_id + '="c"] .message-text').evaluate("el=>el.firstChild.textContent='Tin đã bị chỉnh sửa.'")
            expect(panel.locator("#consent")).not_to_be_checked(timeout=5000)
            assert len(calls) == 2
            checks.append("selected_message_edit_resets_consent_before_submission")
            # Restore fixture, select, and use the explicit saved direct preference.
            page.reload(); page.bring_to_front()
            panel.locator("#conversation-reselect").click()
            load_visible()
            expect(panel.locator("#conversation-picker")).to_be_visible()
            panel.locator("#conversation-all").click()
            expect(panel.locator("#conversation-continue")).to_be_disabled()
            checks.append("empty_selection_is_not_submittable")
            panel.locator("#conversation-all").click()
            panel.locator("#conversation-cancel").click()
            panel.locator("#cancel").click()
            # Fresh editor clears the invalid earlier snapshot.
            panel.locator("#clear-input").click()
            worker.evaluate("() => chrome.storage.local.set({aiSendMode:'direct'})")
            panel.locator("#read-conversation").click(); load_visible(); expect(panel.locator("#conversation-picker")).to_be_visible()
            delay["seconds"] = .5
            panel.locator("#conversation-continue").click()
            expect(panel.locator("#progress")).to_be_visible()
            assert not panel.locator("#review").is_visible()
            deadline = time.monotonic() + 10
            while len(calls) < 3:
                if time.monotonic() > deadline: raise RuntimeError("Conversation job was not sent: " + panel.locator("#error").inner_text())
                panel.wait_for_timeout(40)
            panel.close()
            with context.expect_page() as opened:
                worker.evaluate("() => PhishLensWorkspace.popup(null)")
            panel = opened.value; panel.on("dialog", lambda dialog: dialog.accept())
            expect(panel.locator("#result")).to_be_visible(timeout=20000)
            assert len(calls) == 4
            checks.append("saved_direct_mode_runs_only_after_explicit_selection_and_resumes_after_closing_panel")
            # Explicit limits must block selection, never silently truncate it.
            # Duplicate a rendered text message, preserving each platform's structure.
            page.locator("#messageView").evaluate("""el=>{const template=el.querySelector('article').cloneNode(true);el.replaceChildren(...Array.from({length:31},(_,i)=>{const row=template.cloneNode(true);row.classList.add('limit-compact');row.querySelector('.message-text').textContent='Tin '+(i+1);row.setAttribute(row.hasAttribute('data-mid')?'data-mid':'data-message-id','limit-'+i);return row}))}""")
            panel.locator("#conversation-reselect").click()
            load_visible()
            expect(panel.locator(".conversation-message")).to_have_count(31)
            expect(panel.locator("#conversation-continue")).to_be_disabled()
            panel.locator("#conversation-all").click()
            expect(panel.locator("#conversation-limit")).to_contain_text("30 tin")
            expect(panel.locator("#conversation-continue")).to_be_disabled()
            checks.append("more_than_30_visible_turns_requires_explicit_smaller_selection")
            page.locator("#messageView").evaluate("""el=>{const template=el.querySelector('article').cloneNode(true);el.replaceChildren(...['x','y'].map((v,i)=>{const row=template.cloneNode(true);row.classList.remove('limit-compact');row.classList.add('limit-long');row.querySelector('.message-text').textContent=v.repeat(4500);row.setAttribute(row.hasAttribute('data-mid')?'data-mid':'data-message-id','long-'+i);return row}))}""")
            panel.locator("#conversation-refresh").click()
            load_visible()
            expect(panel.locator(".conversation-message")).to_have_count(2)
            expect(panel.locator("#conversation-limit")).to_contain_text("8.000")
            expect(panel.locator("#conversation-continue")).to_be_disabled()
            assert len(calls) == 4
            checks.append("combined_transcript_over_8000_characters_is_blocked_without_truncation_or_AI")
            panel.locator("#conversation-cancel").click()
            # Unsupported/ambiguous layouts fail without falling back to body.innerText.
            page.locator(chat_view).evaluate("el=>{el.removeAttribute('id');el.removeAttribute('role');el.removeAttribute('class')}")
            page.locator("#messageView").evaluate("el=>{el.removeAttribute('id');el.removeAttribute('class');el.removeAttribute('role')}")
            panel.locator("#new-analysis").click()
            panel.locator("#read-conversation").click()
            panel.locator("#conversation-mode").select_option("visible")
            panel.locator("#conversation-load").click()
            expect(panel.locator("#conversation-read-error")).to_contain_text("Chưa")
            assert len(calls) == 4
            checks.append("unrecognized_chat_layout_fails_closed_instead_of_reading_the_whole_page")
            # More reader checks use the same shipped extension, no provider calls.
            page.reload(); page.bring_to_front()
            tab_id = worker.evaluate("async prefix => (await chrome.tabs.query({})).find(tab=>tab.url?.startsWith(prefix)).id", url.split("#")[0])
            def read_now():
                return worker.evaluate("async id => {try{return await PhishLensConversation.read(id)}catch(e){return {error:e.message}}}", tab_id)
            page.locator("#messageView article").first.evaluate("""el=>{const quoted=document.createElement('div');quoted.className='reply';quoted.textContent='QUOTED_OTHER_SENDER';el.querySelector('.message-text').append(quoted)}""")
            assert "QUOTED_OTHER_SENDER" not in json.dumps(read_now())
            checks.append("quoted_reply_preview_is_not_attributed_as_current_speaker_request")
            value = read_now(); timing_context = {**value["context"], "messageIds": [item["id"] for item in value["messages"]]}
            page.locator("#messageView time").first.evaluate("el=>el.textContent='Đã đọc · 14:01'")
            assert worker.evaluate("value => PhishLensConversation.validate(value)", timing_context)["valid"]
            checks.append("time_or_read_receipt_changes_do_not_invalidate_unchanged_message_text")
            page.locator("style").evaluate("el=>el.textContent+=' .fixture-spacer{height:2000px}'")
            page.locator("#messageView").evaluate("""el=>{const spacer=document.createElement('div');spacer.className='fixture-spacer';const row=el.querySelector('article').cloneNode(true);row.querySelector('.message-text').textContent='OFFSCREEN_HISTORY_PRIVATE';el.append(spacer,row)}""")
            assert "OFFSCREEN_HISTORY_PRIVATE" not in json.dumps(read_now())
            checks.append("loaded_history_outside_scroll_viewport_is_excluded")
            page.reload(); page.bring_to_front()
            value = read_now(); source_context = {**value["context"], "messageIds": [item["id"] for item in value["messages"]]}
            worker.evaluate("value => PhishLensConversation.validate(value)", source_context)
            page.locator("#messageView article").first.evaluate("el=>el.setAttribute(el.hasAttribute('data-mid')?'data-mid':'data-message-id','recycled-message')")
            rejected = worker.evaluate("async value => {try{await PhishLensConversation.validate(value);return false}catch{return true}}", source_context)
            assert rejected
            checks.append("recycled_message_node_with_new_source_ID_invalidates_selected_context")
            page.reload(); page.bring_to_front()
            page.locator("#messageView").evaluate("el=>el.parentElement.append(el.cloneNode(true))")
            ambiguous = read_now()
            assert ambiguous.get("error") and "messages" not in ambiguous
            checks.append("multiple_message_panes_fail_closed_without_combining_conversations")
            if platform_id == "messenger":
                page.reload(); page.bring_to_front()
                page.locator("#messageView").evaluate("el=>{for(const node of el.querySelectorAll('[data-from-me]'))node.removeAttribute('data-from-me');for(const node of el.querySelectorAll('[data-sender-name]'))node.remove()}")
                # Alignment and CSS class 'me' alone must not manufacture a speaker.
                assert all(row["speaker"] == "Chưa rõ người gửi" for row in read_now()["messages"])
                checks.append("missing_Messenger_speaker_metadata_remains_unknown_for_user_to_review")
            if platform_id == "zalo":
                worker.evaluate("async()=>{await chrome.storage.local.remove('chatAssistSites');await chrome.storage.local.set({chatAssistEnabled:true});await PhishLensConversation.sync()}")
                assert worker.evaluate("async()=> (await chrome.storage.local.get('chatAssistSites')).chatAssistSites") == {"zalo": True, "messenger": False, "telegram": False}
                checks.append("legacy_Zalo_preference_migrates_without_enabling_new_platforms")
            assert len(calls) == 4
            assert not external and not errors, (external, errors)
            with app.state.workspace.connection() as conn:
                assert conn.execute("SELECT COUNT(*) FROM history").fetchone()[0] == 0
                assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
            checks.append("guest_conversation_check_creates_no_account_or_history_and_no_external_network")
            complete = True
            context.close()
    finally:
        server.should_exit = True; thread.join(timeout=10); sock.close()
        report = {"status": "passed" if complete else "incomplete", "passed": len(checks), "checks": checks, "browser_errors": errors, "unexpected_network": external,
            "platform": args.platform, "mocked_provider_calls": len(calls), "real_provider_calls": 0, "real_chat_account_tested": False,
            "limitations": ["Chat DOM fixture and provider fixtures; production chat layouts and native permission dialog require manual confirmation."],
            "source_sha256": {"extensions/chromium/" + path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in source.glob("*.js")},
            "source_unchanged_during_run": all(path.read_bytes() == (ROOT / "extensions/chromium" / path.name).read_bytes() for path in source.glob("*.js"))}
        (args.out / "checks.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__": main()
