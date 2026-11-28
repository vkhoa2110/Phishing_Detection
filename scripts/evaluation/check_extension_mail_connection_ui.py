"""Email checks after a cold worker start, without first opening the extension UI.

Real Chromium extension, isolated Gmail/Outlook DOM, temporary backend database
and mock AI only. The worker fetch guard prevents touching the user's running
backend, including the default discovery ports. Optional ZIP baseline reproduces
the missing-connection failure before exercising recovery and consent controls.
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
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


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
    from scripts.evaluation.check_extension_mail_annotations_ui import GMAIL, OUTLOOK

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--baseline', type=Path)
    args = parser.parse_args(); args.out.mkdir(parents=True, exist_ok=False)
    calls, checks, errors, external, baseline = [], [], [], [], None
    hold, started, release = threading.Event(), threading.Event(), threading.Event()

    async def provider(request):
        payload = json.loads(request.content); calls.append(payload)
        assert all(word not in json.dumps(payload) for word in ['INBOX_PRIVATE', 'DRAFT_PRIVATE', 'HIDDEN_PRIVATE'])
        if payload['messages'][0]['content'] == SYSTEM:
            return packet(NOTE)
        if hold.is_set():
            started.set(); deadline = time.monotonic() + 30
            while not release.is_set():
                assert time.monotonic() < deadline, 'Held fixture not released'
                await asyncio.sleep(.02)
            hold.clear()
        return packet(decision())

    app = create_app('focused', replace(Settings(), api_key='isolated-fixture'), transport=httpx.MockTransport(provider),
        model_service=FakeML(), rag_service=OrderedRAG([]), workspace_settings=WorkspaceSettings(database=args.out/'application/test.sqlite3'))
    sock = socket.socket(); sock.bind(('127.0.0.1', 0)); base = 'http://127.0.0.1:' + str(sock.getsockname()[1])
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True); thread.start()
    hashes = {file.name: hashlib.sha256(file.read_bytes()).hexdigest() for file in (ROOT/'extensions/chromium').glob('*.js')}

    def make_source(name, archive=None):
        source = args.out/name
        if archive:
            source.mkdir()
            with ZipFile(archive) as saved:
                # Explicit current allowlist, without trusting archive paths.
                from scripts.maintenance.package_extension import FILES
                for filename in FILES:
                    if filename not in saved.namelist(): continue
                    target = source/filename; target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(saved.read(filename))
        else:
            shutil.copytree(ROOT/'extensions/chromium', source)
        manifest = json.loads((source/'manifest.json').read_text())
        manifest['host_permissions'].append('<all_urls>')
        (source/'manifest.json').write_text(json.dumps(manifest))
        return source

    try:
        deadline = time.monotonic() + 30
        while not server.started:
            assert time.monotonic() < deadline
            time.sleep(.05)
        with sync_playwright() as p:
            def browser(source, name):
                context = p.chromium.launch_persistent_context(str(args.out/name), channel='chromium', headless=True,
                    args=[f'--disable-extensions-except={source.resolve()}', f'--load-extension={source.resolve()}', '--screen-info={1600x1000}', '--window-size=1280,900'],
                    viewport={'width': 1200, 'height': 850}, screen={'width': 1600, 'height': 1000})
                context.on('page', lambda page: (page.on('pageerror', lambda error: errors.append(str(error))), page.on('dialog', lambda dialog: dialog.accept())))

                def network(route):
                    url = route.request.url
                    if url.startswith(base+'/'): route.continue_()
                    elif url.startswith('https://mail.google.com/'): route.fulfill(content_type='text/html', body=GMAIL)
                    elif url.startswith('https://outlook.office.com/'): route.fulfill(content_type='text/html', body=OUTLOOK)
                    else: external.append(url); route.abort()
                context.route('http://**/*', network); context.route('https://**/*', network)
                worker = context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
                worker.evaluate('''base=>{
                  globalThis.fixtureNet={offline:false,invalid:false,delay:false,dropStart:false,statusOffline:false,requests:[]};
                  const original=fetch;
                  globalThis.fetch=async(url,init)=>{
                    const value=new URL(url),net=fixtureNet;
                    if(![base,"http://127.0.0.1:8001","http://127.0.0.1:8000","http://localhost:9876"].includes(value.origin))throw new Error("External fetch blocked");
                    net.requests.push({origin:value.origin,path:value.pathname,body:JSON.parse(init.body)});
                    if(net.offline||(net.statusOffline&&value.pathname.endsWith("/jobs/status")))throw new TypeError("fixture offline");
                    if(net.delay&&value.pathname.endsWith("/session"))await new Promise(r=>setTimeout(r,500));
                    if(net.invalid&&value.origin==="http://localhost:9876")return new Response(JSON.stringify({other_application:true}),{headers:{"Content-Type":"application/json"}});
                    const response=await original(base+value.pathname,init);
                    if(net.dropStart&&value.pathname.endsWith("/jobs/start")){net.dropStart=false;net.statusOffline=true;throw new TypeError("fixture lost start reply")}
                    return response;
                  };
                  return chrome.storage.local.set({base,aiSendMode:"direct",mailAssistEnabled:true});
                }''', base)
                mail = context.new_page()
                mail.goto('https://mail.google.com/mail/u/0/#inbox/cold-start'); mail.bring_to_front()
                worker.evaluate('()=>PhishLensMail.sync()')
                expect(mail.locator('[data-phishlens-mail][data-status="idle"]')).to_be_attached(timeout=15000)
                return context, worker, mail

            def click(mail):
                box = mail.locator('[data-phishlens-mail]').bounding_box()
                mail.mouse.click(box['x']+90, box['y']+23)

            if args.baseline:
                context, worker, mail = browser(make_source('baseline-extension', args.baseline), 'baseline-profile')
                before = len(calls); click(mail)
                expect(mail.locator('[data-phishlens-mail][data-status="error"]')).to_be_attached(timeout=10000)
                baseline = {'message': mail.locator('[data-phishlens-mail]').get_attribute('title'), 'provider_calls': len(calls)-before}
                assert baseline['provider_calls'] == 0 and 'Mở PhishLens để kết nối ứng dụng trên máy' in baseline['message']
                mail.screenshot(path=str(args.out/'00_baseline_missing_connection.png')); context.close()

            context, worker, mail = browser(make_source('test-extension'), 'browser-profile')
            pages = len(context.pages); mail.wait_for_timeout(600)
            assert not calls and worker.evaluate('()=>fixtureNet.requests.length') == 0
            checks.append('opening_email_with_no_connection_never_sends_content_or_opens_the_extension_UI')
            click(mail)
            expect(mail.locator('[data-phishlens-mail][data-status="complete"]')).to_be_attached(timeout=15000)
            assert len(context.pages) == pages
            access = worker.evaluate('async()=> (await chrome.storage.local.get("connection")).connection')
            assert access['guest'] and access['base'] == base
            assert worker.evaluate('()=>fixtureNet.requests[0]') == {'origin': base, 'path': '/api/extension/session', 'body': {}}
            checks.append('first_trusted_click_connects_locally_and_finishes_without_first_opening_check_html')
            mail.screenshot(path=str(args.out/'01_cold_start_complete.png'))

            counter = 0
            def fresh_email():
                nonlocal counter
                counter += 1
                worker.evaluate('''async()=>{
                    await chrome.storage.local.remove("connection");await chrome.storage.session.clear();
                    fixtureNet.requests=[];
                }''')
                mail.evaluate('value=>{location.hash="#inbox/connection-case-"+value;document.querySelector("h2.hP").textContent="Khuyến mãi kiểm thử "+value}', counter)
                expect(mail.locator('[data-phishlens-mail][data-status="idle"]')).to_be_attached(timeout=10000)

            fresh_email(); worker.evaluate('base=>chrome.storage.local.set({connection:{base,guest:true,expires_at:1}})', base)
            before = len(calls); click(mail)
            expect(mail.locator('[data-phishlens-mail][data-status="complete"]')).to_be_attached(timeout=15000)
            assert len(calls) > before
            checks.append('expired_guest_access_is_renewed_on_the_same_mail_button')

            fresh_email(); worker.evaluate('()=>{fixtureNet.offline=true}')
            before = len(calls); click(mail)
            expect(mail.locator('[data-phishlens-mail][data-status="error"]')).to_be_attached(timeout=10000)
            assert len(calls) == before and 'Khởi động PhishLens' in mail.locator('[data-phishlens-mail]').get_attribute('title')
            worker.evaluate('()=>{fixtureNet.offline=false}'); click(mail)
            expect(mail.locator('[data-phishlens-mail][data-status="complete"]')).to_be_attached(timeout=15000)
            assert len(context.pages) == pages
            checks.append('offline_error_recovers_from_the_main_retry_button_after_backend_returns')

            fresh_email(); worker.evaluate('()=>chrome.storage.local.set({autoConnectDisabled:true})')
            before = len(calls); click(mail)
            expect(mail.locator('[data-phishlens-mail][data-status="error"]')).to_be_attached(timeout=10000)
            assert len(calls) == before and worker.evaluate('()=>fixtureNet.requests.length') == 0
            assert 'tạm ngừng' in mail.locator('[data-phishlens-mail]').get_attribute('title')
            assert worker.evaluate('async()=> (await chrome.storage.local.get("autoConnectDisabled")).autoConnectDisabled')
            checks.append('explicit_connection_pause_is_respected_without_probe_or_AI')
            worker.evaluate('()=>chrome.storage.local.set({autoConnectDisabled:false})')

            fresh_email(); worker.evaluate('base=>chrome.storage.local.set({connection:{base,token:"expired-fixture",expires_at:1}})', base)
            before = len(calls); click(mail)
            expect(mail.locator('[data-phishlens-mail][data-status="error"]')).to_be_attached(timeout=10000)
            assert len(calls) == before and worker.evaluate('()=>fixtureNet.requests.length') == 0
            assert 'tài khoản đã hết hạn' in mail.locator('[data-phishlens-mail]').get_attribute('title')
            checks.append('expired_account_is_not_silently_downgraded_to_guest')

            fresh_email(); worker.evaluate('()=>{fixtureNet.invalid=true;return chrome.storage.local.set({base:"http://localhost:9876"})}')
            click(mail)
            expect(mail.locator('[data-phishlens-mail][data-status="complete"]')).to_be_attached(timeout=15000)
            invalid = worker.evaluate('()=>fixtureNet.requests.filter(x=>x.origin==="http://localhost:9876")')
            assert invalid and all(item['path'].endswith('/session') and item['body'] == {} for item in invalid)
            assert worker.evaluate('async()=> (await chrome.storage.local.get("connection")).connection.base') == 'http://127.0.0.1:8001'
            checks.append('unrelated_local_service_receives_no_mail_and_falls_back_to_validated_default_backend')
            worker.evaluate('base=>{fixtureNet.invalid=false;return chrome.storage.local.set({base})}', base)

            fresh_email(); worker.evaluate('()=>{fixtureNet.delay=true}')
            before = len(calls)
            result = worker.evaluate('async()=>await Promise.all([PhishLensJobs.request("session",{}),PhishLensJobs.request("session",{})])')
            assert all(item['guest'] for item in result) and len(calls) == before
            assert worker.evaluate('()=>fixtureNet.requests.length') == 3  # One shared probe, two callers.
            checks.append('concurrent_actions_share_one_connection_probe_without_sending_AI')

            fresh_email()
            pending = worker.evaluate('''()=>{
                globalThis.pauseResult=PhishLensJobs.request("session",{}).then(()=>({unexpected:true}),e=>({error:e.message}));return true;
            }''')
            assert pending
            worker.evaluate('()=>chrome.storage.local.set({autoConnectDisabled:true})')
            result = worker.evaluate('()=>pauseResult')
            assert 'tạm ngừng' in result['error']
            assert not worker.evaluate('async()=> (await chrome.storage.local.get("connection")).connection')
            checks.append('pausing_during_discovery_prevents_saving_or_using_the_new_connection')
            worker.evaluate('()=>{fixtureNet.delay=false;return chrome.storage.local.set({autoConnectDisabled:false})}')

            fresh_email(); hold.set(); started.clear(); release.clear()
            worker.evaluate('()=>{fixtureNet.dropStart=true}'); before = len(calls); click(mail)
            try:
                expect(mail.locator('[data-phishlens-mail][data-status="error"]')).to_be_attached(timeout=15000)
            except AssertionError:
                print('lost-reply-diagnostic', {'state':mail.locator('[data-phishlens-mail]').get_attribute('data-status'),
                    'message':mail.locator('[data-phishlens-mail]').get_attribute('title'), 'provider_delta':len(calls)-before,
                    'network':worker.evaluate('()=>({dropStart:fixtureNet.dropStart,requests:fixtureNet.requests.map(x=>({origin:x.origin,path:x.path}))})')},flush=True)
                raise
            worker.evaluate('()=>{fixtureNet.statusOffline=false}'); click(mail)
            expect(mail.locator('[data-phishlens-mail][data-status="running"]')).to_be_attached(timeout=10000)
            assert started.is_set() and len(calls) == before+1
            assert worker.evaluate('()=>fixtureNet.requests.filter(x=>x.path.endsWith("/jobs/start")).length') == 1
            release.set()
            expect(mail.locator('[data-phishlens-mail][data-status="complete"]')).to_be_attached(timeout=15000)
            checks.append('retry_after_lost_start_reply_joins_the_running_job_instead_of_resending_email')

            fresh_email(); worker.evaluate('()=>chrome.storage.local.set({aiSendMode:"review"})')
            before = len(calls)
            mail.goto('https://outlook.office.com/mail/inbox/id/cold-review'); mail.bring_to_front()
            worker.evaluate('()=>PhishLensMail.sync()')
            expect(mail.locator('[data-phishlens-mail][data-status="idle"]')).to_be_attached(timeout=10000)
            click(mail)
            deadline = time.monotonic()+15
            while len(context.pages) <= pages:
                assert time.monotonic() < deadline
                mail.wait_for_timeout(50)
            review = next(page for page in context.pages if page.url.startswith(worker.url.replace('background.js','check.html')))
            expect(review.locator('#review')).to_be_visible(timeout=15000)
            expect(review.locator('#confirm')).to_be_disabled()
            assert len(calls) == before
            checks.append('Outlook_review_mode_still_waits_for_explicit_consent_after_cold_start')
            for file in (ROOT/'extensions/chromium').glob('*.js'):
                review.evaluate('source=>{new Function(source);return true}', file.read_text())
            assert not errors, errors
            assert not external, external
            checks.append('all_extension_scripts_parse_and_only_isolated_mock_backends_are_contacted')
            context.close()
    finally:
        release.set(); server.should_exit = True; thread.join(timeout=10)
    report = {'checks_passed':len(checks),'checks':checks,'baseline':baseline,'mocked_provider_calls':len(calls),'external_provider_calls':0,
        'source_sha256':hashes,'source_unchanged_during_run':hashes=={file.name:hashlib.sha256(file.read_bytes()).hexdigest() for file in (ROOT/'extensions/chromium').glob('*.js')},
        'limits':'Isolated Chromium Gmail/Outlook DOM and fake provider, without a real mailbox or Brave session. Default ports redirected inside the test worker.'}
    (args.out/'checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({key:value for key,value in report.items() if key!='source_sha256'},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
