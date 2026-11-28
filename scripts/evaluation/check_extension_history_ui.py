"""History range UI and virtualised pagination with fixture chat/provider only."""
import argparse
import asyncio
from dataclasses import replace
import hashlib
import json
import re
from pathlib import Path
import shutil
import socket
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

HTML = '''<!doctype html><html lang="vi"><meta charset="utf-8"><title>Hội thoại mô phỏng</title><style nonce="fixture">
*{box-sizing:border-box}body{margin:0;font:14px/1.5 system-ui;background:#edf0f7;color:#1c293d}main{display:grid;grid-template-columns:230px 1fr 180px;height:100vh}aside{background:white;padding:20px}#chatView{min-height:0;overflow:hidden}header{height:60px;padding:18px;background:white}#messageView{height:calc(100vh - 140px);overflow:auto;padding:10px 24px}.message-item{height:105px;overflow:hidden;width:85%;background:white;border-radius:12px;margin:0 0 12px;padding:12px}.message-item.tall{height:450px}.me{margin-left:auto;background:#dae9ff}.sender-name{font-size:11px;color:#74839b}time{font-size:10px;color:#74839b}.compose{height:80px;background:white;padding:18px}
</style><main><aside>SIDEBAR_PRIVATE_OTHER_CHAT</aside><section id="chatView" data-conversation-id="fixture-history"><header class="chat-title">Hội thoại có lịch sử · Mô phỏng</header><div id="messageView"></div><div class="compose" contenteditable="true">DRAFT_PRIVATE</div></section><aside>MEMBER_PRIVATE</aside></main></html>'''

SETUP = '''({total=120,delay=100,dates=true,tall=false,pageSize=20,tiny=false}={})=>{
const root=document.querySelector('#messageView');let start=Math.max(0,total-pageSize),loading=false;
window.fixture={total,requests:0};
function render(){root.replaceChildren(...Array.from({length:Math.min(pageSize,total-start)},(_,i)=>{
 const n=start+i,row=document.createElement('article');row.className='message-item'+(n%2?' me':'')+(tall?' tall':'');row.dataset.messageId='source-'+n;
 const sender=document.createElement('span');sender.className='sender-name';sender.textContent=n%2?'':'PERSON_PRIVATE';
 const text=document.createElement('div');text.className='message-text';text.textContent='Tin lịch sử '+String(n).padStart(3,'0')+'. '+(n===4?'Hãy gửi mã OTP cho nhân viên. ':'Nội dung trao đổi bình thường trong cuộc họp. ')+'Đây là văn bản mô phỏng để kiểm tra thứ tự và phân tích nhiều phần. '.repeat(3);
 if(tiny)text.textContent='Tin lịch sử '+String(n).padStart(3,'0')+'.';
 const stamp=document.createElement('time');stamp.className='message-time';const d='2026-11-'+String(22+Math.floor(n/20)).padStart(2,'0');if(dates)stamp.dateTime=d+'T10:30:00+07:00';stamp.textContent=dates?d:'10:30';
 row.append(sender,text,stamp);return row}));root.scrollTop=Math.max(0,root.scrollHeight-root.clientHeight);}
root.addEventListener('scroll',()=>{if(root.scrollTop>80||!start||loading)return;loading=true;window.fixture.requests++;setTimeout(()=>{start=Math.max(0,start-pageSize);render();loading=false},delay)});render();
}'''

PLATFORMS = {
    'zalo': ('https://chat.zalo.me/', '#chatView'),
    'messenger': ('https://www.messenger.com/t/fixture-history', '#chatView'),
    'facebook': ('https://www.facebook.com/messages/t/fixture-history', '#chatView'),
    'telegram-a': ('https://web.telegram.org/a/#fixture-history', '#MiddleColumn'),
    'telegram-k': ('https://web.telegram.org/k/#fixture-history', '#column-center .chat'),
}


def fixture(kind):
    html, setup = HTML, SETUP
    if kind in ('messenger', 'facebook'):
        html = html.replace('<section id="chatView"', '<section role="main" id="chatView"').replace('<div id="messageView">', '<div id="messageView" role="grid" aria-label="Messages in conversation">')
        setup = setup.replace("row.append(sender,text,stamp);", "row.setAttribute('role','row');text.dir='auto';sender.dataset.senderName='';if(n%2)row.dataset.fromMe='true';row.append(sender,text,stamp);")
    elif kind == 'telegram-a':
        html = html.replace('<section id="chatView"','<section id="MiddleColumn"').replace('<div id="messageView">','<div id="messageView" class="MessageList">')
        setup = setup.replace('row.append(sender,text,stamp);', "row.classList.add('Message');if(n%2)row.classList.add('own');text.classList.add('text-content');const heading=document.createElement('div');heading.className='message-title';sender.classList.add('sender-title');heading.append(sender);row.append(heading,text,stamp);")
    elif kind == 'telegram-k':
        html = html.replace('<section id="chatView"','<section id="column-center"').replace('<header class="chat-title">','<div class="chat"><header class="chat-title">').replace('</section><aside>','</div></section><aside>').replace('<div id="messageView">','<div id="messageView" class="bubbles-inner">')
        setup = setup.replace('row.append(sender,text,stamp);', "row.classList.add('bubble');row.dataset.mid=row.dataset.messageId;row.removeAttribute('data-message-id');if(n%2)row.classList.add('is-out');text.classList.add('message');const heading=document.createElement('div');heading.className='bubble-content';sender.classList.add('name');heading.append(sender);row.append(heading,text,stamp);")
    return html, setup


def main():
    import httpx
    import uvicorn
    from playwright.sync_api import sync_playwright, expect
    from app.api.workspace import create_app
    from app.core.settings import Settings
    from app.services.workspace import WorkspaceSettings
    from tests.api.test_baseline import FakeML
    from tests.api.test_candidate_app import OrderedRAG
    from tests.api.test_focused_app import packet
    from app.services.llm.conversation import SYSTEM
    from app.services.llm.decision_explanation import SYSTEM as EXPLANATION

    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True);parser.add_argument('--platform',choices=PLATFORMS,default='zalo')
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=False)
    url,chat_view=PLATFORMS[args.platform];html,setup=fixture(args.platform)
    checks,calls,errors,network=[],[],[],[];complete=False;delay={'seconds':.03}
    async def provider(request):
        body=json.loads(request.content);calls.append(body)
        assert not any(value in json.dumps(body) for value in ('SIDEBAR_PRIVATE','DRAFT_PRIVATE','MEMBER_PRIVATE','PERSON_PRIVATE'))
        await asyncio.sleep(delay['seconds'])
        if body['messages'][0]['content']==EXPLANATION:return packet({'summary':'Có yêu cầu gửi mã xác thực cho người liên hệ.','evidence':[{'index':0,'explanation':'Mã OTP có thể bị dùng để chiếm quyền tài khoản.'}]})
        assert body['messages'][0]['content']==SYSTEM
        high='Hãy gửi mã OTP cho nhân viên.' in body['messages'][1]['content']
        return packet({'risk_level':'HIGH' if high else 'LOW','context_kind':'scam_request' if high else 'routine','reason_code':'secret_request' if high else 'no_fraud_evidence','quotes':['Hãy gửi mã OTP cho nhân viên.'] if high else [],'missing_context':[]})
    app=create_app('focused',replace(Settings(),api_key='history-fixture-only'),transport=httpx.MockTransport(provider),model_service=FakeML(),rag_service=OrderedRAG([]),workspace_settings=WorkspaceSettings(database=args.out/'test.sqlite3',daily_ai_limit=100))
    sock=socket.socket();sock.bind(('127.0.0.1',0));base='http://127.0.0.1:'+str(sock.getsockname()[1])
    server=uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False));thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
    source=args.out/'test-extension';shutil.copytree(ROOT/'extensions/chromium',source)
    manifest=json.loads((source/'manifest.json').read_text());manifest['host_permissions'].append('<all_urls>');(source/'manifest.json').write_text(json.dumps(manifest))
    try:
        deadline=time.monotonic()+30
        while not server.started:
            if time.monotonic()>deadline:raise RuntimeError('Backend did not start')
            time.sleep(.05)
        with sync_playwright() as p:
            browser=p.chromium.launch_persistent_context(str(args.out/'browser-profile'),channel='chromium',headless=True,args=[f'--disable-extensions-except={source.resolve()}',f'--load-extension={source.resolve()}','--screen-info={1600x1000}','--window-size=1280,900'],viewport={'width':1280,'height':900},screen={'width':1600,'height':1000})
            browser.on('page',lambda page:page.on('pageerror',lambda error:errors.append(str(error))))
            def route(r):
                if r.request.url.startswith(base+'/'):r.continue_()
                elif r.request.url.startswith(url.split('#')[0]):r.fulfill(content_type='text/html',body=html,headers={'Content-Security-Policy':"default-src 'none';style-src 'nonce-fixture';script-src 'none'"})
                else:network.append(r.request.url);r.abort()
            browser.route('http://**/*',route);browser.route('https://**/*',route)
            worker=browser.service_workers[0] if browser.service_workers else browser.wait_for_event('serviceworker')
            worker.evaluate('base=>chrome.storage.local.set({base,theme:"dark"})',base)
            panel=browser.new_page();panel.on('dialog',lambda dialog:dialog.accept());panel.goto(worker.url.replace('background.js','check.html?panel=1'))
            expect(panel.locator('#connection-status')).to_contain_text('Sẵn sàng',timeout=30000)
            page=browser.new_page();page.goto(url);page.evaluate(setup,{});page.bring_to_front()
            panel.locator('#read-conversation').click();expect(panel.locator('#conversation-range')).to_be_visible()
            assert panel.locator('#conversation-mode').input_value()=='latest' and not calls and page.evaluate('fixture.requests')==0
            panel.set_viewport_size({'width':390,'height':850});assert panel.evaluate('document.documentElement.scrollWidth<=innerWidth');panel.screenshot(path=str(args.out/'01_ranges.png'));panel.set_viewport_size({'width':1280,'height':900})
            checks.append('range_picker_defaults_to_latest_with_count_date_all_modes_without_reading_history_or_sending_AI')
            def choose(mode,limit=100,from_date=None,to_date=None):
                panel.locator('#conversation-mode').select_option(mode);panel.locator('#conversation-max').fill(str(limit))
                if from_date:panel.locator('#conversation-from').fill(from_date)
                if to_date:panel.locator('#conversation-to').fill(to_date)
                panel.locator('#conversation-load').click()
            def loaded(count):
                expect(panel.locator('.conversation-message')).to_have_count(count,timeout=25000)
                expect(panel.locator('#conversation-loading')).to_be_hidden(timeout=25000)
            def change_range(**settings):
                panel.locator('#conversation-refresh').click();page.reload();page.evaluate(setup,settings);page.bring_to_front()
            choose('latest',50);loaded(50)
            texts=panel.locator('.conversation-message p').all_text_contents()
            assert texts[0].startswith('Tin lịch sử 070.') and texts[-1].startswith('Tin lịch sử 119.') and len(set(texts))==50
            assert page.evaluate('fixture.requests')>=2 and not calls
            expect(panel.locator('#conversation-continue')).to_be_enabled()
            checks.append('latest_50_loads_older_virtual_pages_deduplicates_overlap_and_preserves_chronological_order')
            change_range();choose('dates',200,'2026-11-27','2026-11-24')
            expect(panel.locator('#conversation-read-error')).to_contain_text('ngày',timeout=10000)
            assert not calls and page.evaluate('fixture.requests')==0
            checks.append('invalid_date_order_is_rejected_before_loading_or_AI')
            choose('dates',200,'2026-11-24','2026-11-25');loaded(40)
            expect(panel.locator('#error')).to_be_hidden()
            dates=panel.locator('.conversation-message time').all_text_contents();assert set(dates)=={'2026-11-24','2026-11-25'} and not calls
            checks.append('date_range_is_inclusive_and_loads_back_to_the_lower_boundary')
            change_range();choose('all',200);loaded(120)
            expect(panel.locator('#conversation-coverage')).to_contain_text('không tải thêm')
            panel.screenshot(path=str(args.out/'02_all_history.png'))
            assert panel.locator('.conversation-message p').first.inner_text().startswith('Tin lịch sử 000.') and not calls
            checks.append('all_available_history_collects_120_messages_and_reports_loading_boundary_without_claiming_server_completeness')
            panel.locator('#conversation-continue').click();expect(panel.locator('#review')).to_be_visible(timeout=10000)
            approved=panel.locator('#approved-text').input_value();assert len(approved)>8000 and 'Tin lịch sử 000.' in approved and 'Tin lịch sử 119.' in approved and not calls
            expect(panel.locator('#masked-note')).to_contain_text('phần');delay['seconds']=.15;panel.locator('#consent').check();panel.locator('#confirm').click()
            deadline=time.monotonic()+10
            while not calls:
                assert time.monotonic()<deadline;panel.wait_for_timeout(30)
            panel.close()
            with browser.expect_page() as opened:worker.evaluate('()=>PhishLensWorkspace.popup(null)')
            panel=opened.value;panel.on('dialog',lambda dialog:dialog.accept())
            expect(panel.locator('#result:visible, #error:visible').first).to_be_visible(timeout=20000)
            if panel.locator('#error').is_visible():
                panel.screenshot(path=str(args.out/'failure_result.png'))
                raise RuntimeError(panel.locator('#error').inner_text())
            expect(panel.locator('#result')).to_be_visible(timeout=20000)
            expect(panel.locator('.result-hero h2')).to_contain_text('nguy cơ cao')
            expect(panel.locator('.conversation-result-scope')).to_contain_text('120 tin')
            assert len(calls)>2
            saved=worker.evaluate('async()=>({local:await chrome.storage.local.get(null),session:await chrome.storage.session.get(null)})')
            assert 'Tin lịch sử' not in json.dumps(saved,ensure_ascii=False)
            checks.append('long_history_over_8000_characters_is_reviewed_then_analyzed_in_sequential_parts_with_early_phishing_retained')
            checks.append('batch_resumes_after_closing_panel_without_resubmitting_raw_chat_or_AI_requests')
            checks.append('job_pointers_store_no_raw_chat_and_range_metadata_is_present_in_results')
            panel.locator('.conversation-evidence').first.click()
            assert page.evaluate("CSS.highlights.has('phishlens-chat-evidence')")
            checks.append('history_evidence_highlights_matching_original_message_when_it_is_loaded')
            panel.screenshot(path=str(args.out/'03_batch_result.png'))
            # A new scan starts from its own conversation snapshot.
            panel.locator('#conversation-reselect').click();page.reload();page.evaluate(setup,{'total':1000,'delay':250});page.bring_to_front()
            choose('all',1500);expect(panel.locator('#conversation-loading')).to_be_visible()
            expect(panel.locator('#conversation-load-count')).to_contain_text(re.compile(r'Đã lấy [1-9][0-9]* tin'),timeout=10000)
            before=len(calls);panel.locator('#conversation-stop').click()
            expect(panel.locator('#conversation-loading')).to_be_hidden(timeout=10000)
            expect(panel.locator('#conversation-coverage')).to_contain_text('dừng theo yêu cầu')
            assert 0<panel.locator('.conversation-message').count()<1000 and len(calls)==before
            checks.append('stop_history_loading_keeps_partial_messages_and_never_calls_AI')
            change_range();choose('latest',10);loaded(10)
            assert panel.locator('.conversation-message p').first.inner_text().startswith('Tin lịch sử 110.')
            assert '2026-11-24' not in panel.locator('#conversation-coverage').inner_text()
            checks.append('latest_count_can_be_smaller_than_one_rendered_page')
            change_range(total=1000,delay=250);choose('all',1500);panel.locator('#conversation-stop').click()
            expect(panel.locator('#conversation-loading')).to_be_hidden(timeout=10000)
            expect(panel.locator('#conversation-coverage')).to_contain_text('dừng theo yêu cầu')
            assert panel.locator('.conversation-message').count()<1000 and len(calls)==before
            checks.append('immediate_stop_is_retained_even_before_the_first_scan_reply_or_message')
            if args.platform=='zalo':
                change_range(total=60,tall=True);choose('latest',50);loaded(50)
                assert panel.locator('.conversation-message p').first.inner_text().startswith('Tin lịch sử 010.') and len(calls)==before
                checks.append('tall_message_pages_do_not_look_exhausted_before_scrolling_to_the_top')
                change_range(total=2000,pageSize=2000,tiny=True);choose('latest',2000);loaded(2000)
                expect(panel.locator('#conversation-continue')).to_be_enabled()
                assert len(calls)==before
                checks.append('full_2000_message_limit_is_reachable_without_truncating_a_short_transcript')
            change_range(dates=False);choose('dates',200,'2026-11-24','2026-11-25')
            expect(panel.locator('#conversation-read-error')).to_contain_text('ngày',timeout=25000)
            assert panel.locator('.conversation-message').count()==0 and len(calls)==before
            checks.append('unknown_dates_are_not_guessed_or_included_in_date_filtered_results')
            page.reload();page.evaluate(setup,{'total':1000,'delay':250});page.bring_to_front()
            choose('all',1500);expect(panel.locator('#conversation-loading')).to_be_visible()
            page.locator(chat_view).evaluate('el=>el.dataset.conversationId="another-chat"')
            expect(panel.locator('#conversation-read-error')).to_contain_text('trò chuyện',timeout=10000)
            assert len(calls)==before
            checks.append('switching_conversation_during_collection_rejects_the_scan_without_mixing_sources')
            assert not errors and not network,(errors,network)
            with app.state.workspace.connection() as conn:assert conn.execute('SELECT COUNT(*) FROM history').fetchone()[0]==0
            complete=True;browser.close()
    finally:
        server.should_exit=True;thread.join(timeout=10);sock.close()
        result={'status':'passed' if complete else 'incomplete','platform':args.platform,'passed':len(checks),'checks':checks,'browser_errors':errors,'unexpected_network':network,'mock_provider_calls':len(calls),'real_provider_calls':0,'real_account_tested':False,'limitations':['Virtualised chat fixture and fake provider; real Zalo/Messenger/Telegram layouts and load timing require manual verification.','Optional host permissions pregranted only in isolated test manifest.'],'source_sha256':{path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in source.glob('*.js')},'source_unchanged_during_run':all(path.read_bytes()==(ROOT/'extensions/chromium'/path.name).read_bytes() for path in source.glob('*.js'))}
        (args.out/'checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
