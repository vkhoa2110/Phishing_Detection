"""Recent jobs, background use, scoped results and PDF export in Chromium.

Temporary application database, synthetic mailbox and fake provider. No personal
profile, real inbox or external AI calls. Exercises shipped extension code.
"""
import argparse
import asyncio
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    import httpx
    import uvicorn
    from fastapi.responses import JSONResponse
    from playwright.sync_api import sync_playwright, expect
    from app.api.workspace import create_app
    from app.core.settings import Settings
    from app.services.workspace import WorkspaceSettings
    from tests.api.test_baseline import FakeML
    from tests.api.test_candidate_app import OrderedRAG
    from tests.api.test_focused_app import decision, packet
    from app.services.llm.decision_explanation import SYSTEM
    from tests.api.test_evidence_explanation import NOTE
    from scripts.evaluation.check_extension_mail_annotations_ui import GMAIL

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(); args.out.mkdir(parents=True, exist_ok=False)
    checks, calls, errors, external = [], [], [], []
    started, hold, release = threading.Event(), threading.Event(), threading.Event()
    config = {'level':'HIGH', 'offline':False}

    async def provider(request):
        payload = json.loads(request.content); calls.append(payload)
        assert not any(value in json.dumps(payload) for value in ['INBOX_PRIVATE','DRAFT_PRIVATE','HIDDEN_PRIVATE'])
        if payload['messages'][0]['content']==SYSTEM: return packet(NOTE)
        if config['level']=='BROKEN': return packet({'risk_level':'HIGH','summary':'Not the requested core schema'})
        if hold.is_set():
            started.set(); deadline = time.monotonic()+40
            while not release.is_set():
                assert time.monotonic()<deadline, 'Held mock call timed out'
                await asyncio.sleep(.02)
            hold.clear()
        if config['level']=='LOW':
            return packet({'risk_level':'LOW','context_kind':'routine','reason_code':'no_fraud_evidence','quotes':[],'missing_context':[]})
        return packet(decision())

    app = create_app('focused', replace(Settings(), api_key='isolated-fixture'), transport=httpx.MockTransport(provider),
        model_service=FakeML(), rag_service=OrderedRAG([]), workspace_settings=WorkspaceSettings(database=args.out/'application/test.sqlite3'))

    @app.middleware('http')
    async def transport(request, next_call):
        if config['offline'] and request.url.path.endswith('/jobs/status'):
            return JSONResponse({'detail':'Fixture network interruption'},status_code=503)
        return await next_call(request)

    sock=socket.socket(); sock.bind(('127.0.0.1',0)); base='http://127.0.0.1:'+str(sock.getsockname()[1])
    server=uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True); thread.start()
    source=args.out/'test-extension'; shutil.copytree(ROOT/'extensions/chromium',source)
    manifest=json.loads((source/'manifest.json').read_text()); manifest['host_permissions'].append('<all_urls>')
    (source/'manifest.json').write_text(json.dumps(manifest))
    hashes={file.name:hashlib.sha256(file.read_bytes()).hexdigest() for file in source.glob('*.js')}
    try:
        deadline=time.monotonic()+30
        while not server.started:
            assert time.monotonic()<deadline
            time.sleep(.05)
        with sync_playwright() as p:
            context=p.chromium.launch_persistent_context(str(args.out/'browser-profile'),channel='chromium',headless=True,
                args=[f'--disable-extensions-except={source.resolve()}',f'--load-extension={source.resolve()}','--screen-info={1600x1000}','--window-size=1280,900'],
                viewport={'width':430,'height':900},screen={'width':1600,'height':1000})
            context.on('page',lambda page:page.on('pageerror',lambda error:errors.append(str(error))))
            def network(route):
                if route.request.url.startswith(base+'/'): route.continue_()
                elif route.request.url.startswith('https://mail.google.com/'): route.fulfill(content_type='text/html',body=GMAIL)
                else: external.append(route.request.url); route.abort()
            context.route('http://**/*',network); context.route('https://**/*',network)
            worker=context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
            worker.evaluate('base=>chrome.storage.local.set({base,aiSendMode:"direct",mailAssistEnabled:true})',base)
            ui_url=worker.url.replace('background.js','check.html?panel=1')
            accept_dialog=lambda dialog:dialog.accept()
            page=context.new_page(); page.on('dialog',accept_dialog); page.goto(ui_url)
            expect(page.locator('#connection-status')).to_contain_text('Sẵn sàng',timeout=30000)
            page.locator('#nav-activity').click()
            expect(page.locator('#activity-empty-title')).to_have_text('Các kết quả sẽ ở đây')
            assert not calls
            checks.append('empty_recent_list_is_usable_without_sending_AI')

            page.locator('#nav-check').click(); page.locator('#input-text').fill('https://example.org/recent?token=PRIVATE_TOKEN_987')
            page.locator('#analyze').click(); expect(page.locator('#result')).to_be_visible(timeout=15000)
            assert not calls
            page.locator('#nav-activity').click()
            expect(page.locator('.activity-card')).to_have_count(1,timeout=10000)
            expect(page.locator('.activity-card .activity-state')).to_contain_text('Nguy cơ cao')
            local_id=page.locator('.activity-card').get_attribute('data-id')
            checks.append('local_URL_analysis_is_indexed_without_an_AI_call')

            page.locator('#nav-check').click(); page.locator('#new-analysis').click(); page.locator('#tab-text').click()
            page.locator('#input-text').fill('BẢN NHÁP CHƯA GỬI')
            page.locator('#nav-activity').click()
            page.remove_listener('dialog',accept_dialog)
            page.once('dialog',lambda dialog:dialog.dismiss())
            page.locator('.activity-card [data-action=open]').click()
            expect(page.locator('body')).to_have_attribute('data-view','activity')
            expect(page.locator('#input-text')).to_have_value('BẢN NHÁP CHƯA GỬI')
            assert not calls
            page.on('dialog',accept_dialog)
            checks.append('declining_to_replace_an_unsent_draft_keeps_the_draft_and_current_view')

            page.locator('.activity-card [data-action=open]').click()
            expect(page.locator('#result')).to_be_visible()
            assert not calls
            page.locator('#new-analysis').click(); page.locator('#tab-text').click()
            page.locator('#input-text').fill('Vui lòng gửi mã OTP cho nhân viên. https://example.org/check?token=PRIVATE_TOKEN_987')
            page.locator('#advanced-options summary').click(); page.locator('#explain-evidence').uncheck()
            hold.set(); page.locator('#analyze').click()
            expect(page.locator('#job-background')).to_be_visible(timeout=15000)
            page.locator('#job-background').click()
            expect(page.locator('body')).to_have_attribute('data-busy','false',timeout=10000)
            expect(page.locator('#activity-screen')).to_be_visible()
            expect(page.locator('.activity-card')).to_have_count(2,timeout=10000)
            page.locator('[data-activity-filter=running]').click()
            expect(page.locator('.activity-card')).to_have_count(1)
            running_id=page.locator('.activity-card').get_attribute('data-id')
            assert started.is_set() and len(calls)==1
            checks.append('background_button_leaves_AI_running_and_unlocks_the_extension')

            page.locator('#nav-check').click()
            page.locator('#input-text').fill('Vui lòng gửi mã OTP. PRIVATE_QUEUE_CANCEL_RECENT')
            page.locator('#analyze').click()
            expect(page.locator('#job-cancel-queued')).to_be_visible(timeout=10000)
            page.locator('#job-background').click()
            expect(page.locator('body')).to_have_attribute('data-busy','false',timeout=10000)
            page.locator('[data-activity-filter=all]').click()
            queued=page.locator('.activity-card').filter(has_text='Đang chờ xử lý')
            expect(queued).to_have_count(1,timeout=10000)
            queued_id=queued.get_attribute('data-id')
            queued.locator('[data-action=cancel]').click()
            expect(page.locator(f'[data-id="{queued_id}"] .activity-state')).to_have_text('Đã hủy',timeout=10000)
            assert len(calls)==1
            page.locator(f'[data-id="{queued_id}"] [data-action=remove]').click()
            expect(page.locator('.activity-card')).to_have_count(2,timeout=10000)
            checks.append('second_AI_request_waits_and_can_be_cancelled_from_recent_without_provider_dispatch')

            page.locator('#nav-check').click()
            page.locator('#input-text').fill('Vui lòng gửi mã OTP. PRIVATE_QUEUE_CANCEL_PROGRESS')
            page.locator('#analyze').click()
            expect(page.locator('#job-cancel-queued')).to_be_visible(timeout=10000)
            page.locator('#job-cancel-queued').click()
            expect(page.locator('body')).to_have_attribute('data-busy','false',timeout=10000)
            expect(page.locator('#activity-screen')).to_be_visible()
            cancelled=page.locator('.activity-card').filter(has_text='Đã hủy')
            expect(cancelled).to_have_count(1,timeout=10000)
            cancelled.locator('[data-action=remove]').click()
            assert len(calls)==1
            checks.append('progress_view_can_cancel_a_waiting_request_without_erasing_an_unsent_input_or_calling_AI')

            page.locator('[data-activity-filter=all]').click()
            page.locator(f'[data-id="{local_id}"] [data-action=open]').click()
            expect(page.locator('#result')).to_be_visible(timeout=10000)
            assert len(calls)==1
            checks.append('completed_results_remain_openable_while_another_job_runs')
            page.close(); release.set()
            page=context.new_page(); page.on('dialog',accept_dialog); page.goto(ui_url)
            expect(page.locator('#connection-status')).to_contain_text('Sẵn sàng',timeout=30000)
            page.locator('#nav-activity').click()
            expect(page.locator(f'[data-id="{running_id}"]')).to_have_attribute('data-status','complete',timeout=15000)
            before=len(calls); page.locator(f'[data-id="{running_id}"] [data-action=open]').click()
            expect(page.locator('#result')).to_be_visible(timeout=10000)
            assert len(calls)==before
            expect(page.locator('.hero-next-action')).to_contain_text('Nên làm ngay')
            expect(page.locator('.result-coverage')).to_contain_text('1/1')
            checks.append('closing_and_reopening_UI_retains_all_pointers_and_does_not_resend_AI')

            page.locator('#new-analysis').click(); page.locator('#tab-text').click()
            page.locator('#input-text').fill('Thông báo lịch họp nhóm vào sáng thứ Sáu. https://example.org/meeting')
            if not page.locator('#advanced-options').evaluate('el=>el.open'): page.locator('#advanced-options summary').click()
            page.locator('#explain-evidence').uncheck(); config['level']='LOW'
            page.locator('#analyze').click(); expect(page.locator('#result')).to_be_visible(timeout=15000)
            expect(page.locator('.result-hero')).to_have_class('result-hero LOW')
            expect(page.locator('.scope-notice')).to_contain_text('Liên kết vẫn cần kiểm tra riêng')
            expect(page.locator('.assessment-card').nth(0)).to_contain_text('Nguy cơ cao')
            assert page.locator('.assessment-card').nth(1).inner_text().find('%')<0
            checks.append('conflicting_URL_HIGH_and_content_LOW_keep_separate_results_and_clear_explanation')

            before=len(calls); page.evaluate('()=>{window.print=()=>{window.fixturePrint=(window.fixturePrint||0)+1}}')
            page.locator('#print-result').click(); assert page.evaluate('()=>window.fixturePrint')==1
            page.pdf(path=str(args.out/'PhishLens_result.pdf'),format='A4',print_background=True)
            text=subprocess.check_output(['pdftotext',str(args.out/'PhishLens_result.pdf'),'-']).decode()
            info=subprocess.check_output(['pdfinfo',str(args.out/'PhishLens_result.pdf')]).decode()
            assert next(line.split(':',1)[1].strip() for line in info.splitlines() if line.startswith('Pages:'))=='1',info
            assert 'PhishLens' in text and 'Liên kết vẫn cần kiểm tra riêng' in text and 'example.org/meeting' in text
            assert 'Tiếp tục · Duyệt' not in text and 'Các kết quả sẽ ở đây' not in text
            assert len(calls)==before
            checks.append('print_button_and_actual_PDF_include_scoped_result_and_URLs_without_extra_AI')
            for width in (320,430,600):
                page.set_viewport_size({'width':width,'height':900})
                assert not page.evaluate('document.documentElement.scrollWidth>innerWidth+1')
            page.locator('#theme-toggle').click(); page.locator('#nav-activity').click()
            page.set_viewport_size({'width':430,'height':900})
            for width in (320,430,600):
                page.set_viewport_size({'width':width,'height':900})
                assert not page.evaluate('document.documentElement.scrollWidth>innerWidth+1')
            checks.append('result_and_recent_list_fit_320_430_600px_with_keyboard_focus_and_dark_theme')

            registry=worker.evaluate('()=>chrome.storage.session.get("analysisActivity")')
            encoded=json.dumps(registry,ensure_ascii=False)
            assert not any(word in encoded for word in ('PRIVATE_TOKEN_987','gửi mã OTP','example.org','Thông báo lịch họp','input_used','recommended_actions'))
            assert len(registry['analysisActivity'])==3
            checks.append('session_registry_has_no_raw_input_URL_mail_subject_quotes_or_complete_results')
            # Terminate the real extension worker, retaining storage.session.
            cdp=context.new_cdp_session(page); versions=[]
            cdp.on('ServiceWorker.workerVersionUpdated',lambda event:versions.extend(event['versions']))
            cdp.send('ServiceWorker.enable')
            deadline=time.monotonic()+10
            while not any(item.get('scriptURL')==worker.url and item.get('runningStatus')=='running' for item in versions):
                assert time.monotonic()<deadline, 'Extension worker version was not reported'
                page.wait_for_timeout(50)
            version=next(item for item in reversed(versions) if item.get('scriptURL')==worker.url and item.get('runningStatus')=='running')
            worker.evaluate('()=>{globalThis.fixtureBeforeRestart=true}')
            versions.clear()
            cdp.send('ServiceWorker.stopWorker',{'versionId':version['versionId']})
            page.locator('#activity-refresh').click()
            deadline=time.monotonic()+10
            while not (any(value['runningStatus']=='stopped' for value in versions) and versions[-1]['runningStatus']=='running'):
                assert time.monotonic()<deadline, 'CDP did not confirm worker stop and restart'
                page.wait_for_timeout(50)
            try:
                previous_scope_gone=worker.evaluate('()=>typeof globalThis.fixtureBeforeRestart')=='undefined'
            except Exception as error:
                previous_scope_gone='Execution context was destroyed' in str(error) or 'Target closed' in str(error)
            assert previous_scope_gone
            (args.out/'worker_restart.json').write_text(json.dumps({'versions':versions,'previous_scope_gone':True},indent=2)+'\n')
            expect(page.locator('.activity-card')).to_have_count(3,timeout=10000)
            before=len(calls)
            page.locator(f'[data-id="{running_id}"] [data-action=open]').click(); expect(page.locator('#result')).to_be_visible(timeout=10000)
            assert len(calls)==before
            page.locator('#nav-activity').click()
            checks.append('real_worker_termination_and_restart_preserve_pointers_client_identity_and_completed_results')
            access=page.evaluate('async()=> (await chrome.storage.local.get("connection")).connection')
            page.evaluate('access=>chrome.storage.local.set({connection:{...access,token:"different-account-fixture",guest:false}})',access)
            page.locator('#activity-refresh').click(); expect(page.locator('.activity-card')).to_have_count(0,timeout=10000)
            page.evaluate('connection=>chrome.storage.local.set({connection})',access)
            page.locator('#activity-refresh').click(); expect(page.locator('.activity-card')).to_have_count(3,timeout=10000)
            checks.append('different_account_connection_cannot_list_previous_guest_job_pointers')

            config['offline']=True; page.locator('#activity-refresh').click()
            expect(page.locator('.activity-state').first).to_have_text('Chưa lấy được trạng thái',timeout=10000)
            assert len(calls)==before
            config['offline']=False; page.locator('#activity-refresh').click()
            expect(page.locator('.activity-card[data-status=complete]')).to_have_count(3,timeout=10000)
            checks.append('temporary_status_failure_keeps_cached_results_and_never_becomes_a_safe_verdict')

            # A source-bound mail is added using the genuine in-page helper.
            mail=context.new_page(); mail.goto('https://mail.google.com/mail/u/0/#inbox/recent-fixture'); mail.bring_to_front()
            page.evaluate('()=>chrome.runtime.sendMessage({type:"SET_MAIL_ASSIST",enabled:true})'); config['level']='HIGH'
            expect(mail.locator('[data-phishlens-mail]')).to_be_attached(timeout=10000)
            mail.wait_for_timeout(700)
            expect(page.locator('body')).to_have_attribute('data-view','activity')
            checks.append('passive_mail_changes_do_not_replace_recent_list_or_steal_the_current_view')
            box=mail.locator('[data-phishlens-mail]').bounding_box(); mail.mouse.click(box['x']+80,box['y']+22)
            expect(mail.locator('[data-phishlens-mail][data-status=complete]')).to_be_attached(timeout=15000)
            page.bring_to_front(); page.locator('#activity-refresh').click()
            expect(page.locator('.activity-card')).to_have_count(4,timeout=10000)
            mail_card=page.locator('.activity-card').filter(has_text='Email · Gmail')
            expect(mail_card).to_have_count(1); mail_id=mail_card.get_attribute('data-id')
            pages=len(context.pages); mail_card.locator('[data-action=source]').click()
            assert len(context.pages)==pages
            assert page.evaluate('async()=> (await chrome.tabs.query({active:true,lastFocusedWindow:true}))[0].url').startswith('https://mail.google.com/')
            checks.append('inline_email_joins_the_same_list_and_source_action_reuses_its_tab')
            mail.close(); page.bring_to_front(); before=len(calls)
            page.locator(f'[data-id="{mail_id}"] [data-action=open]').click(); expect(page.locator('#result')).to_be_visible(timeout=10000)
            assert len(calls)==before
            checks.append('completed_email_result_is_readable_after_its_source_tab_closes')

            parallel=page.evaluate('''async()=>await Promise.all(["left","right"].map(side=>chrome.runtime.sendMessage({type:"START_ANALYSIS",payload:{mode:"url",text:"https://example.org/parallel-"+side,use_llm:false,include_ml:false,use_rag:false,consent:false,save_history:false,save_content:false},kind:"url"})))''')
            page.locator('#nav-activity').click(); page.locator('#activity-refresh').click()
            expect(page.locator('.activity-card')).to_have_count(6,timeout=10000)
            expect(page.locator('.activity-card[data-status=complete]')).to_have_count(6,timeout=10000)
            assert len(calls)==before and len({item['record']['id'] for item in parallel})==2
            checks.append('simultaneous_job_starts_are_both_retained_without_AI_calls_or_lost_storage_writes')

            config['level']='BROKEN'
            bad=page.evaluate('''()=>chrome.runtime.sendMessage({type:"START_ANALYSIS",kind:"text",payload:{mode:"text",text:"Vui lòng gửi mã OTP",llm_text:"Vui lòng gửi mã OTP",use_llm:true,consent:true,include_ml:false,use_rag:false,save_history:false,save_content:false}})''')
            page.locator('#activity-refresh').click()
            failed=page.locator('[data-id="'+bad['record']['id']+'"]')
            expect(failed.locator('.activity-state')).to_have_text('AI chưa hoàn tất',timeout=10000)
            failed.locator('[data-action=open]').click(); expect(page.locator('#result')).to_be_visible(timeout=10000)
            expect(page.locator('.result-hero')).to_have_class('result-hero UNKNOWN')
            expect(page.locator('.scope-notice')).to_contain_text('Phần nội dung chưa được phân tích xong')
            assert len(calls)==before+1
            before=len(calls)
            checks.append('invalid_provider_output_is_a_technical_error_in_recent_and_never_a_LOW_or_semantic_question')

            page.locator('#nav-activity').click(); config['offline']=False
            app.state.extension_jobs.jobs.clear()
            page.locator('#activity-refresh').click()
            expect(page.locator('.activity-card[data-status=expired]')).to_have_count(7,timeout=10000)
            assert len(calls)==before
            page.locator('#activity-clear').click(); expect(page.locator('.activity-card')).to_have_count(0)
            assert len(calls)==before
            checks.append('backend_expiry_is_explicit_and_cleaning_finished_pointers_never_resubmits_jobs')
            page.reload(); expect(page.locator('#connection-status')).to_contain_text('Sẵn sàng',timeout=10000)
            expect(page.locator('#error')).to_be_hidden(); expect(page.locator('#result')).to_be_hidden()
            assert len(calls)==before
            checks.append('reopening_after_clearing_recent_does_not_resurrect_a_removed_job')
            for file in source.glob('*.js'): page.evaluate('source=>{new Function(source);return true}',file.read_text())
            assert not errors,errors
            assert not external,external
            assert all('PRIVATE_QUEUE_CANCEL' not in json.dumps(payload) for payload in calls)
            context.close()
    finally:
        release.set(); server.should_exit=True; thread.join(timeout=10)
    report={'passed':len(checks),'checks':checks,'mock_provider_calls':len(calls),'real_provider_calls':0,'real_mailbox_used':False,
        'source_sha256':hashes,'source_unchanged_during_run':all(hashlib.sha256((ROOT/'extensions/chromium'/name).read_bytes()).hexdigest()==sha for name,sha in hashes.items()),
        'limitations':'Isolated Chromium with synthetic Gmail and fake provider; no real Brave/mail account or native print dialog tested. PDF rendering uses Chromium print engine.'}
    (args.out/'checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({key:value for key,value in report.items() if key!='source_sha256'},ensure_ascii=False,indent=2))


if __name__=='__main__': main()
