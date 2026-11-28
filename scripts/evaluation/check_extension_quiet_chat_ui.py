"""Check quiet URL alerts and Messenger DOM layouts using isolated fixtures.

No real account, inbox or provider. Optional host permissions are pregranted in
the test copy only. URL scores are fixtures, not a detection-quality benchmark.
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


def chat(layout):
    rows = ''.join(f'<div role="row" data-message-id="m{i}"><div role="gridcell"><div dir="auto" data-ad-rendering-role="message">Tin kiểm tra {i}: không gửi mã OTP.</div></div></div>' for i in range(4))
    plain_rows = rows.replace(' data-ad-rendering-role="message"', '')
    unidentified_rows = rows.replace(' role="row"', '').replace(' data-message-id=', ' data-unused=')
    composer = '<div contenteditable="true" role="textbox">PRIVATE_DRAFT</div>'
    inbox = '<nav><div role="grid" aria-label="Messages"><div role="row"><a href="/t/other"><span dir="auto">PRIVATE_OTHER_THREAD</span></a></div></div></nav>'
    if layout == 'labelled': body = f'<div role="grid" aria-label="Messages in conversation">{rows}</div>'
    elif layout == 'unlabelled': body = f'<div role="grid">{rows}</div>'
    elif layout == 'gridcells': body = f'<div role="grid">{plain_rows}</div>'
    elif layout == 'log': body = f'<div role="log">{rows}</div>'
    elif layout == 'marker': body = f'<div data-scope="messages_table">{rows}</div>'
    elif layout == 'nested': body = f'<div role="grid" data-scope="messages_table"><div role="grid" aria-label="Messages">{rows}</div></div>'
    elif layout == 'scroll': body = f'<div style="overflow-y:auto;height:350px">{rows}</div>'
    elif layout == 'body-markers': body = f'<div data-scope="messages_table">{unidentified_rows}</div>'
    elif layout == 'contacts-only': body = '<div role="grid" aria-label="Messages"><div role="row"><a href="/t/other"><span dir="auto">PRIVATE_OTHER_THREAD</span></a></div></div>'
    elif layout == 'ambiguous': body = f'<div role="grid" aria-label="Messages">{rows}</div><div role="grid" aria-label="Messages">{rows}</div>'
    elif layout == 'hidden': body = f'<div hidden role="grid" aria-label="Messages">PRIVATE_HIDDEN</div><div role="grid" aria-label="Messages">{rows}</div>'
    elif layout == 'inbox-in-main': body = f'<div role="grid"><div role="row"><a href="/t/other"><span dir="auto">PRIVATE_OTHER_THREAD</span></a></div></div><div role="grid">{rows}</div>'
    else: raise ValueError(layout)
    view = f'<main role="main" data-conversation-id="fixture"><h1>Hội thoại mô phỏng</h1>{body}{composer}</main>'
    if layout == 'marker': view = view.replace('<main role="main"', '<section').replace('</main>', '</section>')
    return '<!doctype html><html lang="vi"><meta charset="utf-8"><style>body{font:15px system-ui}main,section{margin-left:220px}nav{position:absolute;left:0;width:200px}[role=row]{padding:18px;border-bottom:1px solid #ddd}[contenteditable]{padding:12px}</style>' + inbox + view + '</html>'


def main():
    import httpx
    import uvicorn
    from playwright.sync_api import sync_playwright, expect
    from app.api.workspace import create_app
    from app.core.settings import Settings
    from app.services.workspace import WorkspaceSettings
    from tests.api.test_baseline import FakeML
    from tests.api.test_candidate_app import OrderedRAG

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(); args.out.mkdir(parents=True, exist_ok=False)
    checks, analyses, providers, errors = [], [], [], []

    class Model(FakeML):
        def predict(self, urls):
            analyses.extend(urls)
            result = super().predict(urls)
            for row in result:
                if '/low/' in row['url']: row.update(score=.1, risk_level='LOW')
                if '/uncertain/' in row['url']: row.update(score=.51, risk_level='WARNING')
                if '/moderate/' in row['url']: row.update(score=.65, risk_level='HIGH', high_threshold=.6)
            return result

    def provider(request):
        providers.append(True); raise AssertionError('No AI should be called')

    app = create_app('focused', replace(Settings(), api_key='fixture-only'), transport=httpx.MockTransport(provider), model_service=Model(), rag_service=OrderedRAG([]), workspace_settings=WorkspaceSettings(database=args.out/'application.sqlite3'))
    sock = socket.socket(); sock.bind(('127.0.0.1', 0)); base = 'http://127.0.0.1:' + str(sock.getsockname()[1])
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False))
    thread = threading.Thread(target=server.run, kwargs={'sockets':[sock]}, daemon=True); thread.start()
    source = args.out/'test-extension'; shutil.copytree(ROOT/'extensions/chromium', source)
    hashes = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'extensions/chromium').glob('*') if p.is_file()}
    manifest = json.loads((source/'manifest.json').read_text()); manifest['host_permissions'].append('<all_urls>'); (source/'manifest.json').write_text(json.dumps(manifest))
    try:
        deadline=time.monotonic()+30
        while not server.started:
            if time.monotonic()>deadline: raise RuntimeError('Backend startup')
            time.sleep(.05)
        with sync_playwright() as p:
            browser=p.chromium.launch_persistent_context(str(args.out/'profile'),channel='chromium',headless=True,args=[f'--disable-extensions-except={source.resolve()}',f'--load-extension={source.resolve()}','--screen-info={1600x1000}','--window-size=1280,900'],viewport={'width':1280,'height':900})
            browser.on('page',lambda page:page.on('pageerror',lambda error:errors.append(str(error))))
            def route(r):
                if r.request.url.startswith(base+'/'):r.continue_()
                elif r.request.url.startswith('https://www.messenger.com/t/fixture-'):r.fulfill(content_type='text/html',body=chat(r.request.url.split('fixture-')[1].split('?')[0]))
                elif r.request.url.startswith('https://'):r.fulfill(content_type='text/html',body='<!doctype html><meta charset="utf-8"><h1>Trang mô phỏng</h1><p>PRIVATE_PAGE_CONTENT</p>')
                else:r.abort()
            browser.route('http://**/*',route);browser.route('https://**/*',route)
            worker=browser.service_workers[0] if browser.service_workers else browser.wait_for_event('serviceworker')
            worker.evaluate('base=>chrome.storage.local.set({base,theme:"dark",floatingEnabled:true})',base)
            panel=browser.new_page();panel.goto(worker.url.replace('background.js','check.html?panel=1'));expect(panel.locator('#connection-status')).to_contain_text('Sẵn sàng',timeout=30000)
            page=browser.new_page();page.goto('https://risk.example/high/first');page.bring_to_front()
            tab=lambda:worker.evaluate('async()=> (await chrome.tabs.query({active:true,lastFocusedWindow:true}))[0].id')
            def state():return worker.evaluate('async id=>PhishLensAssistant.state(await chrome.tabs.get(id))',tab())
            def wait_status(status):
                deadline=time.monotonic()+10
                while time.monotonic()<deadline:
                    value=state()
                    if value['page']['status']==status:return value
                    page.wait_for_timeout(50)
                raise AssertionError(state())
            def dock():return page.locator('[data-phishlens-dock]')
            def shadow():return worker.evaluate('async id=>(await chrome.scripting.executeScript({target:{tabId:id},func:()=>{const host=document.querySelector("[data-phishlens-dock]");return host?chrome.dom.openOrClosedShadowRoot(host).textContent:"";}}))[0].result',tab())
            panel.locator('#nav-assistant').click();expect(panel.locator('#floating-enabled')).not_to_be_checked()
            assert not analyses
            checks.append('legacy_dock_preference_becomes_quiet_no_automatic_read_or_AI')
            panel.locator('#auto-check-enabled').check();wait_status('ok');expect(dock()).to_be_visible(timeout=10000)
            assert 'URL có dấu hiệu rủi ro' in shadow()
            page.screenshot(path=str(args.out/'01_risk_notice.png'))
            page.wait_for_timeout(8500);expect(dock()).to_be_hidden()
            assert worker.evaluate('id=>chrome.action.getBadgeText({tabId:id})',tab())=='!'
            checks.append('HIGH_strong_URL_notice_auto_hides_entire_overlay_after_8_seconds_badge_remains')
            for suffix in ('reload','query'):
                page.goto('https://risk.example/high/first?variant='+suffix);wait_status('ok');page.wait_for_timeout(250);expect(dock()).to_be_hidden()
            checks.append('same_hostname_navigation_and_reload_do_not_repeat_notice_within_30_minutes')
            other=browser.new_page();other.goto('https://risk.example/high/another-tab');other.bring_to_front();page=other;wait_status('ok');page.wait_for_timeout(250);expect(dock()).to_be_hidden()
            checks.append('cooldown_is_shared_across_tabs')
            for path in ('low','uncertain','moderate'):
                page.goto(f'https://signal-{path}.example/{path}/test');value=wait_status('ok');page.wait_for_timeout(200);expect(dock()).to_be_hidden()
                assert not value['page']['noticeEligible'] and not worker.evaluate('id=>chrome.action.getBadgeText({tabId:id})',tab())
            checks.append('LOW_UNKNOWN_and_HIGH_below_notification_threshold_do_not_interrupt')
            before=len(analyses)
            for url in ('https://drive.google.com/drive/u/0/my-drive','https://www.google.com/','https://www.messenger.com/t/fixture-labelled','https://mail.google.com/mail/u/0/'):
                page.goto(url);wait_status('app_surface');page.wait_for_timeout(150);expect(dock()).to_be_hidden()
            assert len(analyses)==before
            checks.append('exact_application_shell_addresses_skip_passive_URL_scoring_and_do_not_claim_LOW')
            manual=worker.evaluate('async id=>PhishLensAssistant.check(await chrome.tabs.get(id),true)',tab());assert manual['risk']=='HIGH' and not manual['noticeEligible']
            checks.append('manual_checks_on_application_shells_still_return_original_model_score')
            page.goto('https://drive.google.com.attacker.example/drive/u/0/my-drive');wait_status('ok');expect(dock()).to_be_visible()
            # Dismiss the actual closed-shadow button using its DOM rectangle.
            point=worker.evaluate('async id=>(await chrome.scripting.executeScript({target:{tabId:id},func:()=>{const s=chrome.dom.openOrClosedShadowRoot(document.querySelector("[data-phishlens-dock]"));const r=[...s.querySelectorAll("button")].find(button=>button.getAttribute("aria-label")==="Ẩn thông báo này").getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};}}))[0].result',tab())
            page.mouse.click(point['x'],point['y']);expect(dock()).to_be_hidden()
            checks.append('lookalike_hostname_is_not_exempt_close_button_hides_notice_and_dock')
            panel.locator('#floating-enabled').check();expect(dock()).to_be_visible();panel.locator('#floating-enabled').uncheck();expect(dock()).to_be_hidden()
            checks.append('persistent_tool_button_requires_separate_explicit_pin')
            panel.locator('#auto-check-enabled').uncheck()
            for layout in ('labelled','unlabelled','gridcells','log','marker','nested','scroll','body-markers','hidden','inbox-in-main','contacts-only','ambiguous'):
                page.goto('https://www.messenger.com/t/fixture-'+layout);page.bring_to_front()
                value=worker.evaluate('async id=>{await chrome.scripting.executeScript({target:{tabId:id},files:["conversation-platforms.js","conversation-reader.js"]});return (await chrome.scripting.executeScript({target:{tabId:id},func:()=>{try{return PhishLensConversationReader.read()}catch(e){return {error:e.message}}}}))[0].result}',tab())
                if layout in ('contacts-only','ambiguous'):assert value.get('error'),(layout,value)
                else:
                    assert len(value['messages'])==4,(layout,value)
                    assert 'PRIVATE_' not in json.dumps(value,ensure_ascii=False),(layout,value)
                checks.append('messenger_layout_'+layout)
            page.goto('https://www.messenger.com/t/fixture-unlabelled');page.bring_to_front();panel.locator('#nav-check').click();panel.locator('#read-conversation').click();expect(panel.locator('#conversation-range')).to_be_visible()
            panel.locator('#conversation-presets [data-count="200"]').click();assert panel.locator('#conversation-max').input_value()=='200'
            panel.locator('#conversation-mode').select_option('visible');panel.locator('#conversation-load').click();expect(panel.locator('#conversation-messages .conversation-message')).to_have_count(4)
            assert worker.evaluate('async()=> (await chrome.storage.local.get("conversationRange")).conversationRange.messenger')=={'mode':'visible','limit':200}
            panel.locator('#conversation-cancel').click();panel.locator('#read-conversation').click();assert panel.locator('#conversation-mode').input_value()=='visible'
            panel.set_viewport_size({'width':390,'height':850});panel.screenshot(path=str(args.out/'02_chat_scope.png'),full_page=True)
            checks.append('scope_presets_and_per_platform_preference_restore_without_saving_chat_text')
            assert not providers and not errors,errors
            browser.close()
        report={'passed':len(checks),'checks':checks,'browser_errors':errors,'provider_calls':len(providers),'fixture_URL_predictions':len(analyses),'real_logged_in_accounts_tested':False,'notification_threshold':.85,'notice_duration_ms':8000,'hostname_cooldown_ms':1800000,'test_manifest_pregrants_optional_hosts':True,'source_sha256':hashes,'source_unchanged_during_run':all(hashlib.sha256((ROOT/'extensions/chromium'/name).read_bytes()).hexdigest()==sha for name,sha in hashes.items())}
        (args.out/'checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps({'passed':len(checks),'provider_calls':len(providers),'out':str(args.out)},ensure_ascii=False))
    finally:
        server.should_exit=True;thread.join(timeout=15);sock.close()


if __name__=='__main__':main()
