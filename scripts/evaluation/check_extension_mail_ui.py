"""MV3 Gmail/Outlook DOM fixtures, explicit AI consent, and public explanations.

No real mailbox is opened. Optional hosts are pregranted in a test-only copy.
The provider is mocked; the API, database, extension and browser are real.
"""
import argparse
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

GMAIL = '''<!doctype html><html><meta charset="utf-8"><body style="font:18px system-ui;padding:25px"><main role="main"><div role="listbox">INBOX_PRIVATE_OTHER_EMAIL</div><h2 class="hP">Khuyến mãi dành riêng cho bạn</h2><div class="adn"><span class="gD" email="promotion@example.org">An Gia</span><div class="ii gt"><div class="a3s aiL"><p>Nhận voucher ưu đãi. Vui lòng gửi mã OTP cho nhân viên.</p><p>Chuyển trước phí xác nhận để nhận quà.</p><a href="https://example.org/claim?offer=AG42">Nhận quà</a><span hidden>HIDDEN_PRIVATE_BODY</span><button>FORM_CONTROL_NOT_MESSAGE</button></div></div></div><div role="dialog"><div contenteditable="true" class="a3s aiL">DRAFT_PRIVATE_TEXT</div></div></main></body></html>'''
OUTLOOK = '''<!doctype html><html><meta charset="utf-8"><body style="font:18px system-ui;padding:25px"><main role="main"><aside>INBOX_PRIVATE_OTHER_EMAIL</aside><section data-testid="reading-pane"><h1 data-testid="message-subject">Thông báo ưu đãi Outlook</h1><span data-testid="message-sender">sales@example.org</span><div data-testid="message-body" role="document" class="allowTextSelection"><p>Vui lòng gửi mã OTP để nhận ưu đãi.</p><a href="https://nam.safelinks.protection.outlook.com/?url=https%3A%2F%2Fexample.org%2Fredeem">Mở ưu đãi</a></div></section></main></body></html>'''

# A link-heavy opened email exercises the complete extraction/preview/API path.
GMAIL = GMAIL.replace('<span hidden>', ''.join(
    f'<a href="https://example.org/item-{i:02d}">Sản phẩm {i}</a>' for i in range(49)
) + '<span hidden>')


def main():
    import httpx
    import uvicorn
    from fastapi.responses import HTMLResponse
    from playwright.sync_api import sync_playwright, expect
    from app.api.workspace import create_app
    from app.core.settings import Settings
    from app.services.workspace import WorkspaceSettings
    from tests.api.test_baseline import FakeML
    from tests.api.test_candidate_app import OrderedRAG
    from tests.api.test_focused_app import decision, packet
    from app.services.llm.decision_explanation import SYSTEM

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(); args.out.mkdir(parents=True, exist_ok=False)
    errors, calls, checks, external = [], [], [], []
    def provider(request):
        payload = json.loads(request.content); calls.append(payload)
        assert all(value not in json.dumps(payload) for value in ['INBOX_PRIVATE', 'DRAFT_PRIVATE', 'HIDDEN_PRIVATE'])
        if payload['messages'][0]['content'] == SYSTEM:
            return packet({'summary': 'Email yêu cầu chuyển phí trước và chia sẻ mã xác thực để nhận ưu đãi. Các yêu cầu này cần được xác minh qua kênh đã biết.',
                'evidence': [{'index': 0, 'explanation': 'Đoạn này yêu cầu gửi OTP cho người khác. Mã có thể dùng để xác nhận đăng nhập hoặc giao dịch.'}]})
        return packet(decision())
    app = create_app('focused', replace(Settings(), api_key='isolated-test-key'), transport=httpx.MockTransport(provider),
        model_service=FakeML(), rag_service=OrderedRAG([]), workspace_settings=WorkspaceSettings(database=args.out/'application/test.sqlite3'))
    sock = socket.socket(); sock.bind(('127.0.0.1',0)); base = 'http://127.0.0.1:'+str(sock.getsockname()[1])
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False)); thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
    source=args.out/'test-extension';shutil.copytree(ROOT/'extensions/chromium',source)
    manifest=json.loads((source/'manifest.json').read_text());manifest['host_permissions'].append('<all_urls>');(source/'manifest.json').write_text(json.dumps(manifest))
    try:
        deadline=time.monotonic()+30
        while not server.started:
            if time.monotonic()>deadline:raise RuntimeError('Server startup')
            time.sleep(.05)
        with sync_playwright() as p:
            context=p.chromium.launch_persistent_context(str(args.out/'browser-profile'),channel='chromium',headless=True,
                args=[f'--disable-extensions-except={source.resolve()}',f'--load-extension={source.resolve()}'],viewport={'width':1280,'height':900})
            context.on('page',lambda page:page.on('pageerror',lambda err:errors.append(str(err))))
            def network(route):
                if route.request.url.startswith(base+'/'):route.continue_()
                elif route.request.url.startswith('https://mail.google.com/'):route.fulfill(content_type='text/html',body=GMAIL)
                elif route.request.url.startswith('https://outlook.office.com/'):route.fulfill(content_type='text/html',body=OUTLOOK)
                else:external.append(route.request.url);route.abort()
            context.route('http://**/*', network); context.route('https://**/*', network)
            worker=context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
            extension=worker.url.replace('background.js','check.html?panel=1')
            worker.evaluate('base=>chrome.storage.local.set({base})',base)
            panel=context.new_page();panel.on('dialog',lambda dialog:dialog.accept());panel.goto(extension)
            expect(panel.locator('#connection-status')).to_contain_text('Sẵn sàng',timeout=30000)
            mail=context.new_page();mail.goto('https://mail.google.com/mail/u/0/#inbox/fixture');mail.bring_to_front()
            panel.locator('#nav-check').click(); expect(panel.locator('#read-email')).to_be_visible()
            assert not calls and not worker.evaluate("async()=> (await chrome.storage.local.get('mailAssistEnabled')).mailAssistEnabled")
            checks.append('mail_assistant_off_by_default_no_mailbox_network_or_provider_access')
            panel.locator('#read-email').click();expect(panel.locator('#review')).to_be_visible()
            text=panel.locator('#approved-text').input_value()
            assert 'Khuyến mãi dành riêng' in text and 'gửi mã OTP' in text and 'https://example.org/claim?offer=' in text, repr(text)
            assert 'https://example.org/claim?offer=AG42' in panel.locator('#input-text').input_value()
            assert all(v not in text for v in ['INBOX_PRIVATE','DRAFT_PRIVATE','HIDDEN_PRIVATE','FORM_CONTROL_NOT_MESSAGE'])
            assert not calls
            expect(panel.locator('#consent')).not_to_be_checked()
            expect(panel.locator('#input-hint')).to_contain_text('50 URL')
            assert text.count('https://example.org/') == 50
            checks.append('manual_Gmail_reads_only_open_message_subject_and_actual_anchor_URL_not_inbox_draft_or_hidden_text')
            panel.locator('#consent').check();panel.locator('#confirm').click()
            expect(panel.locator('.ai-explanation')).to_contain_text('chuyển phí trước',timeout=30000)
            expect(panel.locator('.evidence-item')).to_contain_text('xác nhận đăng nhập')
            assert len(calls)==2
            assert len(panel.locator('#result .url-row').all()) == 50
            checks.append('email_with_50_distinct_URLs_is_extracted_previewed_and_scored_without_truncation')
            assert panel.locator('#result').inner_text().count('Nguy cơ cao')>=1
            panel.screenshot(path=str(args.out/'01_AI_explanation.png'),full_page=True)
            checks.append('one_classification_plus_one_public_explanation_after_consent_keeps_original_HIGH_verdict')
            panel.locator('#nav-assistant').click();panel.locator('#mail-assist-enabled').check()
            expect(mail.locator('[data-phishlens-mail]')).to_be_visible()
            panel.locator('#nav-check').click();panel.locator('.new-check').filter(has_text='Kiểm tra nội dung khác').click()
            # A new opened message updates the preview without calling AI or preserving consent.
            mail.locator('.a3s.aiL').first.evaluate("el=>el.innerHTML='<p>Thư thứ hai: vui lòng gửi mã OTP cho bộ phận khuyến mãi.</p><a href=\"https://example.org/new-offer\">Nhận ưu đãi mới</a>'")
            expect(panel.locator('#review')).to_be_visible(timeout=15000)
            expect(panel.locator('#approved-text')).to_have_value(__import__('re').compile('.*Thư thứ hai.*',__import__('re').S))
            assert len(calls)==2;expect(panel.locator('#consent')).not_to_be_checked()
            panel.locator('#consent').check()
            mail.locator('.a3s.aiL').first.evaluate("el=>el.firstElementChild.textContent='Thư thứ ba: vui lòng gửi mã OTP.'")
            expect(panel.locator('#approved-text')).to_have_value(__import__('re').compile('.*Thư thứ ba.*',__import__('re').S))
            expect(panel.locator('#consent')).not_to_be_checked();assert len(calls)==2
            checks.append('opt_in_opened_message_changes_refresh_preview_and_reset_consent_without_provider_calls')
            edited=panel.locator('#approved-text').input_value()+'\nGhi chú đang chỉnh sửa.'
            panel.locator('#approved-text').fill(edited)
            mail.locator('.a3s.aiL').first.evaluate("el=>el.firstElementChild.textContent='Thư thứ tư: vui lòng gửi mã OTP.'")
            panel.wait_for_timeout(800)
            assert panel.locator('#approved-text').input_value()==edited and len(calls)==2
            checks.append('automatic_mail_changes_preserve_user_edited_preview_and_require_fresh_consent')
            panel.locator('#cancel').click()
            # Multiple expanded messages must not be mixed into a fabricated single mail.
            mail.locator('[role=main]').evaluate("el=>{const extra=document.createElement('div');extra.className='a3s aiL';extra.textContent='Another expanded message';el.append(extra)}")
            panel.locator('#read-email').click();expect(panel.locator('#error')).to_contain_text('nhiều thư')
            assert len(calls)==2
            checks.append('multiple_expanded_messages_fail_closed_instead_of_combining_unrelated_mail')
            panel.locator('#nav-assistant').click();panel.locator('#mail-assist-enabled').uncheck()
            expect(mail.locator('[data-phishlens-mail]')).to_have_count(0)
            outlook=context.new_page();outlook.goto('https://outlook.office.com/mail/inbox/id/fixture');outlook.bring_to_front()
            panel.locator('#nav-check').click();panel.locator('#read-email').click()
            expect(panel.locator('#review')).to_be_visible()
            assert 'Thông báo ưu đãi Outlook' in panel.locator('#approved-text').input_value()
            assert 'https://example.org/redeem' in panel.locator('#approved-text').input_value()
            assert 'INBOX_PRIVATE' not in panel.locator('#approved-text').input_value()
            panel.screenshot(path=str(args.out/'02_Outlook_review.png'),full_page=True)
            checks.append('Outlook_reads_open_body_and_unwraps_SafeLinks_without_opening_any_destination')
            panel.locator('#cancel').click()
            outlook.locator('[data-testid=message-body]').evaluate("el=>el.textContent='A'.repeat(8100)")
            panel.locator('#read-email').click();expect(panel.locator('#error')).to_contain_text('8.000')
            assert len(calls)==2
            checks.append('oversized_email_rejected_without_silent_truncation_or_provider_calls')
            panel.locator('#nav-assistant').click();panel.locator('#mail-assist-enabled').uncheck()
            expect(mail.locator('[data-phishlens-mail]')).to_have_count(0)
            assert 'phishlens-email' not in [r['id'] for r in worker.evaluate('()=>chrome.scripting.getRegisteredContentScripts()')]
            assert not external and not errors,(external,errors)
            checks.append('disable_unregisters_mail_observer_removes_button_no_external_mailbox_or_link_requests')
            with app.state.workspace.connection() as conn:
                assert conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]==0
                assert conn.execute('SELECT COUNT(*) FROM history').fetchone()[0]==0
            checks.append('guest_mail_checks_create_no_account_or_personal_history')
            context.close()
    finally:
        server.should_exit=True;thread.join(timeout=10);sock.close()
    report={'passed':len(checks),'checks':checks,'browser_errors':errors,'mocked_provider_calls':len(calls),'external_provider_calls':0,
        'mailbox_pages':'intercepted_Gmail_and_Outlook_DOM_fixtures_no_real_account','native_permission_dialog_automated':False,
        'source_sha256':{str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in (ROOT/'extensions/chromium').rglob('*') if f.is_file()}}
    (args.out/'checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
