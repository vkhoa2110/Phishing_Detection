"""Quiet email jobs and singleton details in real Chromium, with isolated fixtures.

Intercepted mailbox DOM, temporary database and fake async AI provider only.
The fallback window path simulates a browser without a usable Side Panel API.
"""
import argparse
import asyncio
from dataclasses import replace
import json
from pathlib import Path
import shutil
import socket
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.evaluation.check_extension_mail_annotations_ui import GMAIL


def main():
    import httpx
    import uvicorn
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
    calls, checks, errors, external = [], [], [], []
    hold, started, release = threading.Event(), threading.Event(), threading.Event()

    async def provider(request):
        payload = json.loads(request.content); calls.append(payload)
        assert all(word not in json.dumps(payload) for word in ['INBOX_PRIVATE', 'DRAFT_PRIVATE', 'HIDDEN_PRIVATE'])
        if payload['messages'][0]['content'] == SYSTEM:
            return packet(NOTE)
        if hold.is_set():
            started.set()
            deadline = time.monotonic() + 45
            while not release.is_set():
                assert time.monotonic() < deadline, 'Held fake provider not released'
                await asyncio.sleep(.02)
            hold.clear()
        return packet(decision())

    app = create_app('focused', replace(Settings(), api_key='isolated-fixture'), transport=httpx.MockTransport(provider),
        model_service=FakeML(), rag_service=OrderedRAG([]), workspace_settings=WorkspaceSettings(database=args.out/'application/test.sqlite3'))
    sock = socket.socket(); sock.bind(('127.0.0.1', 0)); base = 'http://127.0.0.1:' + str(sock.getsockname()[1])
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True); thread.start()
    source = args.out/'test-extension'; shutil.copytree(ROOT/'extensions/chromium', source)
    manifest = json.loads((source/'manifest.json').read_text()); manifest['host_permissions'].append('<all_urls>')
    (source/'manifest.json').write_text(json.dumps(manifest))
    try:
        deadline = time.monotonic() + 30
        while not server.started:
            assert time.monotonic() < deadline
            time.sleep(.05)
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(str(args.out/'browser-profile'), channel='chromium', headless=True,
                args=[f'--disable-extensions-except={source.resolve()}', f'--load-extension={source.resolve()}', '--screen-info={1600x1000}', '--window-size=1280,900'],
                viewport={'width': 1200, 'height': 850}, screen={'width': 1600, 'height': 1000})
            context.on('page', lambda page: (page.on('pageerror', lambda error: errors.append(str(error))), page.on('dialog', lambda dialog: dialog.accept())))
            def network(route):
                if route.request.url.startswith(base+'/'): route.continue_()
                elif route.request.url.startswith('https://mail.google.com/'): route.fulfill(content_type='text/html', body=GMAIL)
                else: external.append(route.request.url); route.abort()
            context.route('http://**/*', network); context.route('https://**/*', network)
            worker = context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
            worker.evaluate('base => chrome.storage.local.set({base, aiSendMode:"direct", mailAssistEnabled:true})', base)
            ui_url = worker.url.replace('background.js', 'check.html?panel=1')
            setup = context.new_page(); setup.goto(ui_url)
            expect(setup.locator('#connection-status')).to_contain_text('Sẵn sàng', timeout=30000)
            setup.close()
            mail = context.new_page(); mail.goto('https://mail.google.com/mail/u/0/#inbox/quiet-one'); mail.bring_to_front()
            worker.evaluate('()=>PhishLensMail.sync()')
            expect(mail.locator('[data-phishlens-mail][data-status="idle"]')).to_be_attached(timeout=15000)
            mail.wait_for_timeout(800); assert not calls
            checks.append('opening_mail_never_sends_AI_or_opens_a_details_window')
            tab_id = worker.evaluate('async()=> (await chrome.tabs.query({url:"https://mail.google.com/*"}))[0].id')
            def message(kind, **data):
                result = worker.evaluate('async ({tabId,message}) => (await chrome.scripting.executeScript({target:{tabId},func:async message=>{const mail=PhishLensMailReader.read();return chrome.runtime.sendMessage({...message,contextId:mail.contextId})},args:[message]}))[0].result', {'tabId': tab_id, 'message': {'type': kind, **data}})
                if result.get('error'): print('mail-action-error', kind, result['error'], flush=True)
                return result
            hold.set(); before_pages = len(context.pages)
            box = mail.locator('[data-phishlens-mail]').bounding_box()
            mail.mouse.click(box['x']+80, box['y']+24)
            expect(mail.locator('[data-phishlens-mail][data-status="running"]')).to_be_attached(timeout=10000)
            deadline = time.monotonic() + 10
            while not started.is_set():
                assert time.monotonic() < deadline
                mail.wait_for_timeout(30)
            for _ in range(4):
                assert message('OPEN_EMAIL')['status'] == 'running'
            assert len(context.pages) == before_pages and len(calls) == 1
            mail.screenshot(path=str(args.out/'01_inline_running.png'))
            checks.append('trusted_check_click_runs_inline_and_four_repeated_clicks_join_one_job')

            original = mail.locator('.a3s:not([contenteditable])').inner_html()
            mail.evaluate('()=>{location.hash="#inbox/quiet-two"; document.querySelector(".a3s").textContent="Lịch họp nhóm lúc 9 giờ sáng mai."}')
            expect(mail.locator('[data-phishlens-mail][data-status="idle"]')).to_be_attached()
            release.set(); mail.wait_for_timeout(1800)
            assert mail.locator('[data-phishlens-annotations]').count() == 0
            checks.append('late_results_never_mark_a_different_email_or_trigger_another_AI_call')
            before = len(calls)
            mail.evaluate('html=>{location.hash="#inbox/quiet-one";document.querySelector(".a3s").innerHTML=html}', original)
            expect(mail.locator('[data-phishlens-mail][data-status="complete"]')).to_be_attached(timeout=15000)
            assert len(calls) == before and mail.locator('[data-phishlens-annotations]').count() == 1
            assert len(context.pages) == before_pages
            mail.screenshot(path=str(args.out/'02_inline_result.png'))
            checks.append('returning_to_the_same_email_reuses_the_finished_job_and_restores_evidence')

            # Exercise the fallback used when Side Panel is unavailable/rejected.
            worker.evaluate('()=>{chrome.sidePanel.open=()=>Promise.reject(new Error("fixture: no Side Panel"))}')
            with context.expect_page() as opened:
                assert message('MAIL_DETAILS')['status'] == 'opened'
            details = opened.value
            expect(details.locator('#result')).to_be_visible(timeout=15000)
            count = len(calls)
            for _ in range(3): assert message('MAIL_DETAILS')['status'] == 'opened'
            details.wait_for_timeout(600)
            assert len(calls) == count
            windows = worker.evaluate('async()=> (await chrome.windows.getAll()).filter(w=>w.type==="popup").map(w=>w.id)')
            assert len(windows) == 1
            details.locator('#detach').click(); details.wait_for_timeout(300)
            assert worker.evaluate('async()=> (await chrome.windows.getAll()).filter(w=>w.type==="popup").length') == 1
            checks.append('explicit_details_and_detach_reuse_exactly_one_fallback_window_without_extra_AI')
            expect(details.locator('#mail-actions')).to_have_js_property('hidden', False)
            details.locator('#result-capture').click()
            expect(mail.locator('[data-phishlens-region]')).to_be_visible(timeout=10000)
            mail.keyboard.press('Escape')
            expect(mail.locator('[data-phishlens-region]')).to_have_count(0)
            assert len(calls) == count
            checks.append('reused_detached_window_keeps_the_original_mail_tab_for_read_and_capture_actions')

            details.close(); mail.bring_to_front(); hold.set(); started.clear(); release.clear()
            box = mail.locator('[data-phishlens-mail]').bounding_box()
            mail.mouse.click(box['x']+box['width']-23, box['y']+23)
            expect(mail.locator('[data-phishlens-mail][data-status="running"]')).to_be_attached(timeout=10000)
            deadline = time.monotonic() + 10
            while not started.is_set():
                assert time.monotonic() < deadline
                mail.wait_for_timeout(30)
            restored = context.new_page(); restored.goto(ui_url)
            expect(restored.locator('#progress')).to_be_visible(timeout=10000)
            restored.close(); mail.bring_to_front()
            release.set()
            try:
                expect(mail.locator('[data-phishlens-mail][data-status="complete"]')).to_be_attached(timeout=15000)
            except AssertionError:
                print('job-close-diagnostic', {'helper_state': mail.locator('[data-phishlens-mail]').get_attribute('data-status'),
                    'helper_message': mail.locator('[data-phishlens-mail]').get_attribute('title'), 'job': message('MAIL_JOB_STATUS')}, flush=True)
                raise
            before = len(calls)
            with context.expect_page() as reopened: assert message('MAIL_DETAILS')['status'] == 'opened'
            details = reopened.value; expect(details.locator('#result')).to_be_visible(timeout=15000)
            assert len(calls) == before
            checks.append('explicit_recheck_starts_once_and_closing_the_waiting_UI_does_not_cancel_analysis')
            details.close(); mail.bring_to_front(); mail.reload()
            expect(mail.locator('[data-phishlens-mail][data-status="complete"]')).to_be_attached(timeout=15000)
            assert len(calls) == before
            checks.append('mail_tab_reload_recovers_cached_result_without_resending_content')

            worker.evaluate('()=>chrome.storage.local.set({aiSendMode:"review"})')
            with context.expect_page() as review: assert message('OPEN_EMAIL', recheck=True)['status'] == 'review'
            details = review.value
            expect(details.locator('#review')).to_be_visible(timeout=15000)
            expect(details.locator('#confirm')).to_be_disabled()
            assert len(calls) == before
            assert message('OPEN_EMAIL', recheck=True)['status'] == 'review'
            details.wait_for_timeout(500)
            assert worker.evaluate('async()=> (await chrome.windows.getAll()).filter(w=>w.type==="popup").length') == 1
            assert len(calls) == before
            checks.append('review_mode_requires_confirmation_and_repeated_review_uses_the_same_window')
            for file in source.glob('*.js'):
                details.evaluate('source=>{new Function(source);return true}', file.read_text())
            assert not errors, errors
            assert not external, external
            assert not any(key.startswith('input-') for key in worker.evaluate('()=>chrome.storage.session.get(null)'))
            checks.append('all_extension_scripts_parse_and_no_external_destinations_are_contacted')
            details.screenshot(path=str(args.out/'03_review_in_shared_window.png'))
            context.close()
    finally:
        release.set(); server.should_exit = True; thread.join(timeout=10)
    report = {'checks_passed': len(checks), 'checks': checks, 'mocked_provider_calls': len(calls), 'external_provider_calls': 0,
        'limits': 'Chromium fixtures; fallback Side Panel rejection simulated. No real Gmail/Outlook account or Brave installation.'}
    (args.out/'checks.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
