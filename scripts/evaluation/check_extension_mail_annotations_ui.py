"""Check in-email highlights, link inspection and stale-result guards in Chromium.

Uses intercepted Gmail/Outlook pages, a temporary database and mocked provider.
No real mailbox, destination website or external AI service is contacted.
"""
import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re
import shutil
import socket
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.evaluation.check_extension_mail_ui import GMAIL, OUTLOOK

GMAIL = re.sub(r'<a href="https://example.org/item-\d+">Sản phẩm \d+</a>', '', GMAIL)
GMAIL = GMAIL.replace('gửi mã OTP', '<b>gửi</b> mã <em>OTP</em>').replace('>Nhận quà</a>', '>https://voucher.example</a>')
GMAIL = GMAIL.replace('<span hidden>', '<span hidden>gửi mã OTP ')


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

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(); args.out.mkdir(parents=True, exist_ok=False)
    checks, calls, external, errors = [], [], [], []
    hold, started, release = threading.Event(), threading.Event(), threading.Event()

    def provider(request):
        payload = json.loads(request.content); calls.append(payload)
        assert all(value not in json.dumps(payload) for value in ['INBOX_PRIVATE', 'DRAFT_PRIVATE', 'HIDDEN_PRIVATE'])
        data = json.loads(payload['messages'][-1]['content'])
        if payload['messages'][0]['content'] == SYSTEM:
            return packet({'summary': 'Email yêu cầu chia sẻ mã xác thực hoặc chuyển phí trước khi nhận ưu đãi.',
                'evidence': [{'index': item['index'], 'explanation': 'Yêu cầu gửi OTP cho người khác có thể làm lộ mã xác nhận.' if item['index'] == 0 else 'Yêu cầu chuyển phí trước khi nhận quà cần được xác minh.'} for item in data['evidence']]})
        if hold.is_set():
            started.set(); assert release.wait(timeout=20), 'Held response not released'
            hold.clear()
        answer = decision()
        if 'Chuyển trước phí xác nhận' in data['text']: answer['quotes'].append('Chuyển trước phí xác nhận')
        return packet(answer)

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
            if time.monotonic() > deadline: raise RuntimeError('Server startup')
            time.sleep(.05)
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(str(args.out/'browser-profile'), channel='chromium', headless=True,
                args=[f'--disable-extensions-except={source.resolve()}', f'--load-extension={source.resolve()}'], viewport={'width': 1100, 'height': 850})
            context.on('page', lambda page: page.on('pageerror', lambda error: errors.append(str(error))))
            def network(route):
                if route.request.url.startswith(base+'/'): route.continue_()
                elif route.request.url.startswith('https://mail.google.com/'): route.fulfill(content_type='text/html', body=GMAIL)
                elif route.request.url.startswith('https://outlook.office.com/'): route.fulfill(content_type='text/html', body=OUTLOOK,
                    headers={'Content-Security-Policy': "default-src 'none'; style-src 'none'; script-src 'none'"})
                else: external.append(route.request.url); route.abort()
            context.route('http://**/*', network); context.route('https://**/*', network)
            worker = context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
            worker.evaluate('base => chrome.storage.local.set({base})', base)
            panel = context.new_page(); panel.on('dialog', lambda dialog: dialog.accept())
            panel.goto(worker.url.replace('background.js', 'check.html?panel=1'))
            expect(panel.locator('#connection-status')).to_contain_text('Sẵn sàng', timeout=30000)
            mail = context.new_page(); mail.goto('https://mail.google.com/mail/u/0/#inbox/fixture'); mail.bring_to_front()
            expect(panel.locator('#read-email')).to_be_visible()
            original = mail.locator('.a3s.aiL').first.inner_html()
            original_text = mail.locator('[role=main]').inner_text()
            tab_id = worker.evaluate("async()=> (await chrome.tabs.query({url:'https://mail.google.com/*'}))[0].id")

            def isolated():
                return worker.evaluate('async tabId => (await chrome.scripting.executeScript({target:{tabId},func: () => {return globalThis.PhishLensMailAnnotations ? {status:PhishLensMailAnnotations.status(), ranges:[...CSS.highlights.get("phishlens-mail-evidence")||[]].map(r=>r.toString()), names:[...CSS.highlights.keys()]} : null}}))[0].result', tab_id)

            def shadow(selector, mode='text'):
                # CDP can inspect a closed shadow root without exposing it to the web page.
                cdp = context.new_cdp_session(mail)
                try:
                    tree = cdp.send('DOM.getDocument', {'depth': -1, 'pierce': True})['root']
                    def find(node):
                        if 'data-phishlens-annotations' in node.get('attributes', []): return node
                        for child in node.get('children', []) + node.get('shadowRoots', []):
                            found = find(child)
                            if found: return found
                    host = find(tree); assert host and host.get('shadowRoots'), 'Annotation host missing'
                    obj = cdp.send('DOM.resolveNode', {'backendNodeId': host['shadowRoots'][0]['backendNodeId']})['object']['objectId']
                    value = cdp.send('Runtime.callFunctionOn', {'objectId': obj, 'functionDeclaration': '''function(selector,mode){const node=this.querySelector(selector);if(!node)return null;if(mode==='rect'){const r=node.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height}}if(mode==='hidden')return node.hidden;if(mode==='background')return getComputedStyle(node).backgroundColor;return node.textContent}''',
                        'arguments': [{'value': selector}, {'value': mode}], 'returnByValue': True})
                    return value['result'].get('value')
                finally: cdp.detach()

            def click_shadow(selector):
                box = shadow(selector, 'rect'); assert box and box['width'] and box['height'], selector
                mail.mouse.click(box['x'] + box['width']/2, box['y'] + box['height']/2)

            def analyze():
                panel.locator('#consent').check(); panel.locator('#confirm').click()
                expect(panel.locator('#mail-show-marks')).to_have_text('Xem dấu hiệu trên thư', timeout=30000)
                expect(mail.locator('[data-phishlens-annotations]')).to_have_count(1)

            panel.locator('#read-email').click(); expect(panel.locator('#review')).to_be_visible()
            assert not calls and mail.locator('[data-phishlens-annotations]').count() == 0
            checks.append('no_annotations_or_provider_call_before_explicit_analysis_consent')
            analyze()
            state = isolated(); assert state['status']['evidence'] == 2 and state['status']['links'] == 1, state
            assert state['ranges'] == ['gửi mã OTP', 'Chuyển trước phí xác nhận'], state
            assert mail.locator('.a3s.aiL').first.inner_html() == original
            assert mail.locator('[role=main]').inner_text() == original_text
            assert len(calls) == 2
            checks.append('completed_analysis_maps_two_quotes_across_inline_nodes_without_rewriting_email_or_hidden_content')
            mail.locator('em').first.click()
            assert shadow('.card', 'hidden') is False and 'lộ mã xác nhận' in shadow('.content')
            mail.screenshot(path=str(args.out/'01_inline_explanation.png'))
            checks.append('click_highlighted_quote_opens_matching_public_explanation_on_original_email')
            mail.keyboard.press('Escape'); assert shadow('.card', 'hidden') is True
            assert isolated()['status']['active']
            checks.append('Escape_collapses_card_but_keeps_highlights_and_keyboard_accessible_overview')
            url = mail.url; mail.locator('a').first.click()
            assert mail.url == url and not external
            assert 'https://voucher.example' in shadow('.display') and shadow('.domain') == 'example.org'
            assert 'voucher.example' in shadow('.comparison') and 'example.org' in shadow('.comparison')
            assert 'https://example.org/claim?offer=AG42' in shadow('code')
            assert shadow('.risk') == 'Nguy cơ cao'
            mail.screenshot(path=str(args.out/'02_link_destination.png'))
            checks.append('click_link_inspects_displayed_domain_actual_destination_and_URL_risk_without_navigation_or_network')
            mail.keyboard.press('Escape'); mail.locator('a').first.focus(); mail.keyboard.press('Enter')
            assert shadow('.card', 'hidden') is False and shadow('.domain') == 'example.org'
            checks.append('keyboard_Enter_on_email_link_opens_inspector_without_opening_destination')
            mail.emulate_media(color_scheme='dark'); mail.set_viewport_size({'width': 360, 'height': 740})
            box = shadow('.card', 'rect'); assert box['x'] >= 0 and box['x'] + box['width'] <= 361, box
            mail.screenshot(path=str(args.out/'03_mobile_dark.png'))
            mail.emulate_media(color_scheme='light'); mail.set_viewport_size({'width': 1100, 'height': 850})
            checks.append('closed_shadow_inspector_fits_360px_viewport_and_dark_theme')
            panel.locator('#mail-hide-marks').click(); expect(mail.locator('[data-phishlens-annotations]')).to_have_count(0)
            assert not isolated()['status']['active']
            panel.locator('#mail-show-marks').click(); expect(mail.locator('[data-phishlens-annotations]')).to_have_count(1)
            assert len(calls) == 2 and shadow('.card', 'hidden') is False
            checks.append('hide_and_reapply_reuse_result_without_extra_AI_requests')

            # A page or unrelated extension cannot invoke annotation operations.
            response = worker.evaluate('async tabId => (await chrome.scripting.executeScript({target:{tabId},func:()=>chrome.runtime.sendMessage({type:"ANNOTATE_EMAIL"})}))[0].result', tab_id)
            assert response.get('error') and isolated()['status']['active']
            checks.append('mail_content_script_cannot_submit_its_own_annotation_payload')
            context_one = panel.evaluate('async tabId => (await chrome.runtime.sendMessage({type:"READ_EMAIL",tabId})).context', tab_id)
            mail.locator('.a3s.aiL').first.evaluate("el=>el.querySelector('p').textContent='Thư mới, không có yêu cầu gửi mã.'")
            expect(mail.locator('[data-phishlens-annotations]')).to_have_count(0)
            assert not isolated()['status']['active']
            panel.locator('#mail-show-marks').click()
            expect(panel.locator('.mail-result-tools')).to_contain_text('Email đã thay đổi')
            assert mail.locator('[data-phishlens-annotations]').count() == 0 and len(calls) == 2
            checks.append('message_body_changes_clear_marks_and_refuse_to_apply_old_result_to_new_mail')
            mail.locator('.a3s.aiL').first.evaluate('(el, html)=>el.innerHTML=html', original)
            panel.locator('#mail-show-marks').click(); expect(panel.locator('#review')).to_be_visible()
            hold.set(); panel.locator('#consent').check(); panel.locator('#confirm').click()
            deadline = time.monotonic() + 10
            while not started.is_set():
                if time.monotonic() > deadline: raise RuntimeError('Analysis did not start')
                panel.wait_for_timeout(30)
            mail.locator('h2.hP').evaluate("el=>el.textContent='Đã chuyển sang một email khác'")
            release.set()
            expect(panel.locator('.mail-result-tools')).to_contain_text('Email đã thay đổi', timeout=30000)
            assert mail.locator('[data-phishlens-annotations]').count() == 0
            expect(panel.locator('.assessment-card').last).to_contain_text('Nguy cơ cao')
            checks.append('switching_mail_while_AI_is_pending_preserves_result_but_never_paints_new_mail')

            panel.locator('#new-analysis').click()
            outlook = context.new_page(); outlook.goto('https://outlook.office.com/mail/inbox/id/fixture'); outlook.bring_to_front()
            panel.locator('#nav-check').click(); panel.locator('#read-email').click(); expect(panel.locator('#review')).to_be_visible()
            tab_id = worker.evaluate("async()=> (await chrome.tabs.query({url:'https://outlook.office.com/*'}))[0].id")
            mail = outlook
            analyze(); assert isolated()['status']['evidence'] == 1
            assert shadow('.card', 'background') == 'rgb(255, 255, 255)'
            checks.append('constructed_stylesheets_work_when_webmail_CSP_disallows_inline_styles')
            outlook.locator('a').click(); assert shadow('.domain') == 'example.org' and 'https://example.org/redeem' in shadow('code')
            assert not external
            outlook.screenshot(path=str(args.out/'04_Outlook_SafeLinks.png'))
            checks.append('Outlook_SafeLinks_are_unwrapped_locally_and_checked_against_original_URL_result')
            outlook.evaluate("location.hash='#another-message'")
            expect(outlook.locator('[data-phishlens-annotations]')).to_have_count(0)
            checks.append('route_changes_invalidate_annotations_even_if_rendered_message_text_is_identical')

            # Adversarial quote text is never injected as HTML or matched outside the body.
            outlook.bring_to_front()
            new_context = panel.evaluate('async tabId => (await chrome.runtime.sendMessage({type:"READ_EMAIL",tabId})).context', tab_id)
            payload = {'type': 'ANNOTATE_EMAIL', 'context': new_context, 'evidence': [
                {'quote': 'INBOX_PRIVATE_OTHER_EMAIL', 'reason': 'Must never highlight inbox'},
                {'quote': 'gửi mã OTP', 'reason': '<img src="https://bad.example/x" onerror="alert(1)"> literal text'}], 'urls': []}
            payload['batchId'] = panel.evaluate('crypto.randomUUID()')
            response = panel.evaluate('payload=>chrome.runtime.sendMessage(payload)', payload)
            assert response['evidence'] == 1 and response['unmatched'] == 1
            outlook.locator('[data-testid=message-body] p').click()
            if shadow('.card', 'hidden'): click_shadow('.dock'); click_shadow('[data-evidence-index="0"]')
            assert '<img src=' in shadow('.content')
            assert not external
            checks.append('unmatched_inbox_quotes_are_omitted_and_explanation_HTML_is_rendered_as_inert_text')
            # Link retargeting must clear the old model result immediately.
            outlook.locator('a').evaluate("el=>el.href='https://other.example/new'")
            expect(outlook.locator('[data-phishlens-annotations]')).to_have_count(0)
            checks.append('changing_anchor_destination_invalidates_annotations_without_rechecking_or_opening_URL')
            # A snapshot from another document must never be accepted.
            bad = {**payload, 'context': {**context_one, 'tabId': tab_id}}
            response = panel.evaluate('payload=>chrome.runtime.sendMessage(payload)', bad)
            assert response.get('error') and outlook.locator('[data-phishlens-annotations]').count() == 0
            checks.append('document_and_snapshot_identity_reject_cross_tab_or_stale_annotation_requests')
            panel.locator('#new-analysis').click(); outlook.bring_to_front()
            panel.locator('#nav-check').click(); panel.locator('#read-email').click(); expect(panel.locator('#review')).to_be_visible()
            panel.locator('#cancel').click(); panel.locator('#use-ai').uncheck(); panel.locator('#analyze').click()
            expect(panel.locator('#mail-show-marks')).to_have_text('Xem dấu hiệu trên thư', timeout=30000)
            assert isolated()['status']['evidence'] == 0 and isolated()['status']['links'] == 1 and len(calls) == 6
            checks.append('local_only_email_check_shows_URL_inspection_without_inventing_AI_evidence_or_calling_provider')
            # Exercise the real capture overlay's hide/restore handoff. Stub only
            # REGION_SELECTED so this assertion needs no OS screenshot or OCR.
            visibility = worker.evaluate('''async tabId => {
                await chrome.scripting.executeScript({target:{tabId},files:['region.js']});
                return (await chrome.scripting.executeScript({target:{tabId},func:async()=>{
                    const original=chrome.runtime.sendMessage;
                    let hidden=null;
                    chrome.runtime.sendMessage=(message,...args)=>{
                        if(message.type==='REGION_SELECTED'){
                            hidden=getComputedStyle(document.querySelector('[data-phishlens-annotations]')).visibility;
                            chrome.runtime.sendMessage=original;return Promise.resolve({});
                        }
                        return original(message,...args);
                    };
                    PhishLensRegion.start('fixture-capture-handoff','viewport');
                    try {
                        await new Promise(resolve=>setTimeout(resolve,300));
                        return {hidden,restored:getComputedStyle(document.querySelector('[data-phishlens-annotations]')).visibility};
                    } finally {chrome.runtime.sendMessage=original;}
                }}))[0].result;
            }''', tab_id)
            assert visibility == {'hidden': 'hidden', 'restored': 'visible'}, visibility
            checks.append('capture_handoff_hides_email_inspector_and_restores_it_without_screenshot_or_OCR_request')
            # A disable action must remove the in-page UI even when it was added manually.
            panel.evaluate('()=>chrome.runtime.sendMessage({type:"SET_MAIL_ASSIST",enabled:false})')
            expect(outlook.locator('[data-phishlens-annotations]')).to_have_count(0)
            assert not isolated()['status']['active']
            checks.append('turning_off_mail_assistant_removes_annotations_and_click_interception')
            assert not errors and not external, (errors, external)
            with app.state.workspace.connection() as conn:
                assert conn.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 0
                assert conn.execute('SELECT COUNT(*) FROM history').fetchone()[0] == 0
            checks.append('guest_annotations_create_no_account_history_or_additional_provider_calls')
            context.close()
    finally:
        release.set(); server.should_exit = True; thread.join(timeout=10); sock.close()
    report = {'passed': len(checks), 'checks': checks, 'browser_errors': errors, 'unexpected_network': external,
        'mocked_provider_calls': len(calls), 'external_provider_calls': 0,
        'mailbox_pages': 'intercepted_Gmail_and_Outlook_DOM_fixtures_no_real_account',
        'source_sha256': {str(f.relative_to(ROOT)): hashlib.sha256(f.read_bytes()).hexdigest() for f in (ROOT/'extensions/chromium').rglob('*') if f.is_file()}}
    (args.out/'checks.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__': main()
