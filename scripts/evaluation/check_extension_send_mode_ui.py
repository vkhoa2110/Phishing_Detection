"""Exercise optional immediate AI sending with real extension/API privacy flow.

Uses synthetic text, intercepted Gmail, an isolated database and a mock provider.
No real mailbox or external provider is contacted. Optional hosts are pregranted
only in the test manifest; the native permissions dialog is not automated.
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

from scripts.evaluation.check_extension_mail_ui import GMAIL


def main():
    import httpx
    import uvicorn
    from fastapi.responses import JSONResponse
    from playwright.sync_api import sync_playwright, expect
    from app.api.workspace import create_app
    from app.core.settings import Settings
    from app.services.workspace import WorkspaceSettings
    from app.services.llm.decision_explanation import SYSTEM
    from tests.api.test_baseline import FakeML
    from tests.api.test_candidate_app import OrderedRAG
    from tests.api.test_focused_app import decision, packet
    from tests.api.test_evidence_explanation import NOTE

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(); args.out.mkdir(parents=True, exist_ok=False)
    calls, attempts, checks, errors, external = [], [], [], [], []
    fail_preview, fail_ai, delay_preview = [False], [False], [False]
    preview_started = threading.Event()
    text = 'Hãy gửi mã OTP cho nhân viên. Liên hệ private.person@example.org. https://example.org/login?token=PRIVATE_TOKEN_987'

    def provider(request):
        payload = json.loads(request.content); calls.append(payload)
        approved = json.loads(payload['messages'][-1]['content'])['text']
        assert 'private.person@example.org' not in approved and 'PRIVATE_TOKEN_987' not in approved
        assert all(value not in approved for value in ['INBOX_PRIVATE', 'DRAFT_PRIVATE', 'HIDDEN_PRIVATE'])
        if fail_ai[0]:
            fail_ai[0] = False
            return httpx.Response(503, json={'error': {'message': 'fixture unavailable'}})
        return packet(NOTE if payload['messages'][0]['content'] == SYSTEM else decision())

    app = create_app('focused', replace(Settings(), api_key='isolated-fixture'), transport=httpx.MockTransport(provider),
        model_service=FakeML(), rag_service=OrderedRAG([]), workspace_settings=WorkspaceSettings(database=args.out/'application/test.sqlite3'))

    @app.middleware('http')
    async def observe(request, call_next):
        if request.url.path == '/api/extension/preview':
            if fail_preview[0]:
                fail_preview[0] = False
                return JSONResponse({'detail': 'Không chuẩn bị được bản gửi.'}, status_code=503)
            if delay_preview[0]:
                delay_preview[0] = False; preview_started.set(); await asyncio.sleep(1)
        if request.url.path in ['/api/extension/analyze', '/api/extension/jobs/start']:
            body = await request.json(); attempts.append(body.get('payload', body))
        return await call_next(request)

    sock = socket.socket(); sock.bind(('127.0.0.1', 0)); base = 'http://127.0.0.1:' + str(sock.getsockname()[1])
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True); thread.start()
    source = args.out/'test-extension'; shutil.copytree(ROOT/'extensions/chromium', source)
    manifest = json.loads((source/'manifest.json').read_text()); manifest['host_permissions'].append('<all_urls>')
    (source/'manifest.json').write_text(json.dumps(manifest))
    try:
        deadline = time.monotonic() + 30
        while not server.started:
            if time.monotonic() > deadline: raise RuntimeError('Server startup')
            time.sleep(.05)
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(str(args.out/'browser-profile'), channel='chromium', headless=True,
                args=[f'--disable-extensions-except={source.resolve()}', f'--load-extension={source.resolve()}'], viewport={'width': 400, 'height': 800})
            context.on('page', lambda page: page.on('pageerror', lambda error: errors.append(str(error))))
            def network(route):
                if route.request.url.startswith(base+'/'): route.continue_()
                elif route.request.url.startswith('https://mail.google.com/'): route.fulfill(content_type='text/html', body=GMAIL)
                else: external.append(route.request.url); route.abort()
            context.route('http://**/*', network); context.route('https://**/*', network)
            worker = context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
            worker.evaluate('base => chrome.storage.local.set({base})', base)
            page = context.new_page(); page.on('dialog', lambda dialog: dialog.accept())
            url = worker.url.replace('background.js', 'check.html?panel=1'); page.goto(url)
            expect(page.locator('#connection-status')).to_contain_text('Sẵn sàng', timeout=30000)
            page.locator('#nav-connection').click(); expect(page.locator('#send-review')).to_be_checked()
            assert not calls and not attempts
            checks.append('fresh_install_defaults_to_review_and_changing_settings_never_sends_content')
            for width in [320, 400, 540]:
                page.set_viewport_size({'width': width, 'height': 800})
                assert not page.evaluate('document.documentElement.scrollWidth>innerWidth+1')
            page.set_viewport_size({'width': 400, 'height': 800})
            page.screenshot(path=str(args.out/'01_review_default.png'))
            checks.append('settings_choices_fit_320_400_540px_without_horizontal_overflow')
            page.locator('#nav-check').click(); page.locator('#tab-text').click(); page.locator('#input-text').fill(text)
            page.locator('#analyze').click(); expect(page.locator('#review')).to_be_visible()
            expect(page.locator('#confirm')).to_be_disabled(); assert not calls and not attempts
            assert 'private.person@example.org' not in page.locator('#approved-text').input_value()
            checks.append('default_mode_still_requires_preview_and_explicit_checkbox_confirmation')
            # Selecting immediate mode must not send an already open draft by itself.
            page.locator('#nav-connection').click(); page.locator('#send-direct').check()
            assert not calls and not attempts
            page.locator('#nav-check').click(); expect(page.locator('.consent-label')).to_be_hidden()
            expect(page.locator('#confirm')).to_be_enabled()
            page.locator('#approved-text').fill(text)
            page.locator('#confirm').click(); expect(page.locator('#result')).to_be_visible(timeout=30000)
            assert len(attempts) == 1 and attempts[-1]['consent'] is True
            assert 'private.person@example.org' not in attempts[-1]['llm_text'] and 'PRIVATE_TOKEN_987' not in attempts[-1]['llm_text']
            checks.append('immediate_mode_on_existing_preview_sends_only_after_button_and_remasks_user_edits')
            before = len(calls); page.reload(); expect(page.locator('#connection-status')).to_contain_text('Sẵn sàng')
            page.locator('#nav-connection').click(); expect(page.locator('#send-direct')).to_be_checked()
            assert len(calls) == before
            page.screenshot(path=str(args.out/'02_immediate_setting.png'))
            checks.append('choice_survives_panel_reload_and_reload_does_not_call_AI')
            page.locator('#nav-check').click(); expect(page.locator('#result')).to_be_visible(); page.locator('#new-analysis').click(); page.locator('#tab-text').click(); page.locator('#input-text').fill(text)
            expect(page.locator('#analyze-label')).to_have_text('Phân tích ngay')
            page.locator('#input-text').press('Control+Enter')
            expect(page.locator('#result')).to_be_visible(timeout=30000)
            expect(page.locator('#review')).to_be_hidden(); assert len(attempts) == 2
            assert attempts[-1]['consent'] and 'PRIVATE_TOKEN_987' not in attempts[-1]['llm_text']
            page.screenshot(path=str(args.out/'03_direct_result.png'))
            checks.append('one_explicit_shortcut_runs_redaction_and_analysis_without_review_or_checkbox')

            page.locator('#new-analysis').click(); page.locator('#input-text').fill(text)
            before = len(calls); count = len(attempts); fail_preview[0] = True
            page.locator('#analyze').click(); expect(page.locator('#error')).to_contain_text('Không chuẩn bị')
            assert len(calls) == before and len(attempts) == count
            checks.append('redaction_preview_failure_never_falls_back_to_sending_raw_input')
            fail_ai[0] = True; page.locator('#analyze').click()
            expect(page.locator('#result')).to_be_visible(timeout=30000)
            expect(page.locator('#result')).to_contain_text('Chưa hoàn tất')
            assert len(calls) == before + 1 and len(attempts) == count + 1
            page.wait_for_timeout(400); assert len(calls) == before + 1
            checks.append('immediate_mode_provider_failure_keeps_URL_result_and_never_retries_automatically')
            page.locator('#new-analysis').click(); page.locator('#input-text').fill(text)
            page.locator('#use-ai').uncheck(); before = len(calls); page.locator('#analyze').click()
            expect(page.locator('#result')).to_be_visible(); assert len(calls) == before and not attempts[-1]['use_llm']
            checks.append('turning_AI_off_still_uses_local_only_analysis_even_with_immediate_preference')
            page.locator('#new-analysis').click(); page.locator('#input-text').fill(text); page.locator('#use-ai').check()
            delay_preview[0] = True; before = len(calls); count = len(attempts); page.locator('#analyze').click()
            deadline = time.monotonic() + 10
            while not preview_started.is_set():
                if time.monotonic() > deadline: raise RuntimeError('Preview did not start')
                page.wait_for_timeout(20)
            worker.evaluate("()=>chrome.storage.local.set({aiSendMode:'review'})")
            expect(page.locator('#review')).to_be_visible(timeout=10000)
            expect(page.locator('#confirm')).to_be_disabled(); assert len(calls) == before and len(attempts) == count
            checks.append('revoking_immediate_preference_during_redaction_restores_review_before_any_provider_call')
            page.locator('#cancel').click(); page.locator('#clear-input').click()
            page.locator('#nav-connection').click(); page.locator('#send-direct').check()
            mail = context.new_page(); mail.goto('https://mail.google.com/mail/u/0/#inbox/send-mode-fixture'); mail.bring_to_front()
            page.locator('#nav-assistant').click(); before = len(calls); count = len(attempts)
            page.locator('#mail-assist-enabled').check(); page.locator('#nav-check').click()
            expect(page.locator('#input-text')).to_have_value(__import__('re').compile('.*Khuyến mãi dành riêng.*', __import__('re').S), timeout=15000)
            expect(page.locator('#review')).to_be_hidden(); expect(page.locator('#analyze-label')).to_have_text('Phân tích ngay')
            assert len(calls) == before and len(attempts) == count
            checks.append('opening_mail_with_immediate_mode_only_prepares_editor_without_sending_AI')
            page.locator('#analyze').click(); expect(page.locator('#result')).to_be_visible(timeout=30000)
            expect(page.locator('#mail-show-marks')).to_have_text('Xem dấu hiệu trên thư')
            assert len(attempts) == count + 1
            checks.append('explicit_email_check_sends_once_and_preserves_in_email_annotations')
            before = len(calls); count = len(attempts)
            mail.locator('.a3s.aiL').first.evaluate("el=>el.querySelector('p').textContent='Thư mới: hãy gửi mã OTP cho nhân viên.'")
            expect(page.locator('#input-text')).to_have_value(__import__('re').compile('.*Thư mới.*', __import__('re').S), timeout=15000)
            expect(page.locator('#review')).to_be_hidden(); assert len(calls) == before and len(attempts) == count
            checks.append('switching_opened_email_never_sends_AI_automatically_in_immediate_mode')
            page.locator('#read-email').click(); expect(page.locator('#result')).to_be_visible(timeout=30000)
            assert len(attempts) == count + 1
            checks.append('manual_read_email_button_can_run_immediate_analysis_without_extra_confirmation')
            # Direct email checking stays on the message, including repeated clicks.
            mail.bring_to_front(); count = len(attempts); pages_before = len(context.pages)
            tab_id = worker.evaluate("async()=> (await chrome.tabs.query({url:'https://mail.google.com/*'}))[0].id")
            response = worker.evaluate('async tabId => (await chrome.scripting.executeScript({target:{tabId},func:()=>chrome.runtime.sendMessage({type:"OPEN_EMAIL",recheck:true})}))[0].result', tab_id)
            assert response.get('status') in ['running', 'complete'], response
            deadline = time.monotonic() + 30
            while mail.locator('[data-phishlens-mail][data-status="complete"]').count() == 0:
                assert time.monotonic() < deadline, 'Inline result not completed'
                mail.wait_for_timeout(200)
            assert len(context.pages) == pages_before and len(attempts) == count + 1
            response = worker.evaluate('async tabId => (await chrome.scripting.executeScript({target:{tabId},func:()=>chrome.runtime.sendMessage({type:"OPEN_EMAIL"})}))[0].result', tab_id)
            assert response['status'] == 'complete' and len(attempts) == count + 1
            checks.append('email_helper_runs_inline_and_reuses_completed_result_without_new_window_or_AI_call')
            page.locator('#nav-connection').click(); page.locator('#send-review').check(); page.locator('#nav-check').click()
            page.locator('#new-analysis').click(); page.locator('#input-text').fill(text); before = len(calls)
            page.locator('#analyze').click(); expect(page.locator('#review')).to_be_visible()
            expect(page.locator('.consent-label')).to_be_visible(); expect(page.locator('#confirm')).to_be_disabled()
            assert len(calls) == before
            checks.append('switching_back_to_review_immediately_restores_per_check_confirmation')
            assert not errors and not external, (errors, external)
            context.close()
    finally:
        server.should_exit = True; thread.join(timeout=10); sock.close()
    report = {'passed': len(checks), 'checks': checks, 'browser_errors': errors, 'unexpected_network': external,
        'mocked_provider_calls': len(calls), 'analysis_requests': len(attempts), 'external_provider_calls': 0,
        'mailbox_pages': 'intercepted_Gmail_fixture_no_real_account', 'native_permission_dialog_automated': False,
        'source_sha256': {str(f.relative_to(ROOT)): hashlib.sha256(f.read_bytes()).hexdigest() for f in (ROOT/'extensions/chromium').rglob('*') if f.is_file()}}
    (args.out/'checks.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__': main()
