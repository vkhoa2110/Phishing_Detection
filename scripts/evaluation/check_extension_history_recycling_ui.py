"""Regress real DOM scroll/recycling shapes missed by the first history fixture.

Uses browser-native scrolling, a bounded virtual message list and shipped reader
code. Optional 0.16 baseline reproduces both user-reported failures. No account,
private API, AI request, application store or clipboard read is involved.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]

HTML = '''<!doctype html><html lang="vi"><meta charset="utf-8"><style>
*{box-sizing:border-box}body{margin:0;font:14px system-ui}aside{position:absolute;width:200px}main{margin-left:220px;height:700px}#messageView{height:500px;overflow:visible}#outer{height:380px;padding-bottom:32px;overflow:hidden}#viewport{height:360px;overflow-y:auto}article{flex-shrink:0;height:80px;padding:12px;background:#eef2fa;border-bottom:1px solid #aaa}.sender-name,.message-sender-name{font-size:10px}time{font-size:10px}.zl-avatar{width:1px;height:1px}
</style><aside>PRIVATE_OTHER_CHAT</aside><main role="main" id="chatView" data-conversation-id="fixture"><header><h1>Hội thoại mô phỏng</h1></header><div id="messageView"><div id="outer"><div id="viewport"><div id="messageViewScroll" role="grid" aria-label="Messages in conversation"></div></div></div></div><div contenteditable="true" role="textbox">PRIVATE_DRAFT</div></main></html>'''

SETUP = '''({platform,total=150,stable=false,nested=true,reverse=false,edit=false,repeats=false,delayed=false,emptyGap=false})=>{
 const viewport=document.querySelector('#viewport'),list=document.querySelector('#messageViewScroll');
 if(!nested){document.querySelector('#outer').style.overflow='visible';document.querySelector('#outer').style.padding='0'}
 if(platform==='zalo'){list.removeAttribute('role');list.removeAttribute('aria-label')}
 if(reverse){viewport.style.display='flex';viewport.style.flexDirection='column-reverse';list.style.display='contents'}
 let start=total-15,loading=false,edited=false;window.fixture={requests:0};
 function render(){list.replaceChildren(...Array.from({length:15},(_,i)=>{
  const n=start+i,row=document.createElement('article');row.dataset.n=String(n);row.id='slot-'+i;row.dataset.id='layout-slot-'+i;
  if(stable)row.dataset.messageId='message-'+n;
  if(platform==='zalo'){row.dataset.component='bubble-message';row.id='bubble-message-'+n;}
  else row.setAttribute('role','row');
  const cell=document.createElement('div');cell.setAttribute('role','gridcell');const text=document.createElement('div');text.className='message-text';text.dir='auto';text.dataset.adRenderingRole='message';text.dataset.component='message-text-content';
  text.textContent=repeats&&n%10===0?'OK':`Tin ${String(n).padStart(3,'0')} · Nội dung mô phỏng`;
  const sender=document.createElement('span');sender.className=platform==='zalo'?'message-sender-name':'sender-name';sender.dataset.senderName='';sender.textContent='PRIVATE_SENDER';
  const stamp=document.createElement('time');stamp.dateTime='2026-11-27T10:30:00+07:00';stamp.textContent='10:30';cell.append(text);row.append(sender,cell,stamp);return row;
 }));if(reverse){for(const row of [...list.children].reverse())viewport.append(row);list.replaceChildren();list.append(...[...viewport.querySelectorAll('article')]);viewport.scrollTop=0}else viewport.scrollTop=Math.max(0,viewport.scrollHeight-viewport.clientHeight)}
 function onScroll(){
  const maximum=viewport.scrollHeight-viewport.clientHeight;
  if(edit&&!edited&&viewport.scrollTop<maximum-50){const row=list.querySelector('[data-n="140"]');if(row){row.querySelector('.message-text').textContent='Tin 140 · Bản nội dung đã cập nhật';edited=true}}
  if((reverse?viewport.scrollTop>-maximum+70:viewport.scrollTop>70)||!start||loading)return;
  loading=true;fixture.requests++;if(emptyGap)list.replaceChildren();
  if(delayed){const busy=document.createElement('div');busy.role='progressbar';busy.id='busy';document.querySelector('#messageView').append(busy)}
  setTimeout(()=>{document.querySelector('#busy')?.remove();start=Math.max(0,start-10);render();loading=false},delayed?1800:80);
 }
 viewport.addEventListener('scroll',onScroll);render();
 window.updateMetadata=()=>{for(const row of list.querySelectorAll('article')){row.querySelector('time').textContent='Đã đọc · 10:31';row.querySelector('[data-sender-name]')?.remove();const avatar=document.createElement('span');avatar.className='zl-avatar';row.append(avatar)}};
}'''


def main():
    from playwright.sync_api import sync_playwright
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True);parser.add_argument('--baseline',type=Path)
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=False)
    names=['conversation-platforms.js','conversation-reader.js','conversation-history.js']
    sources={name:(ROOT/'extensions/chromium'/name).read_text() for name in names}
    old={}
    if args.baseline:
        with ZipFile(args.baseline) as z:old={name:z.read(name).decode() for name in names}
    checks=[];reproduced=[];errors=[];reports=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='chromium',headless=True)
        def run(platform,code,**options):
            page=browser.new_page(viewport={'width':1280,'height':900});page.on('pageerror',lambda error:errors.append(str(error)))
            url='https://chat.zalo.me/' if platform=='zalo' else 'https://www.messenger.com/t/fixture'
            page.route('**/*',lambda route:route.fulfill(content_type='text/html',body=HTML));page.goto(url)
            page.evaluate(SETUP,{'platform':platform,**options});page.evaluate('()=>{window.chrome={runtime:{sendMessage:()=>Promise.resolve({})}}}')
            for name in names:page.evaluate(code[name])
            started=page.evaluate('()=>PhishLensConversationHistory.start({mode:"latest",limit:50})');sid=started['id'];deadline=time.monotonic()+35
            result=started
            while result['state']=='running' and time.monotonic()<deadline:
                page.wait_for_timeout(200);result=page.evaluate('id=>PhishLensConversationHistory.status(id)',sid)
            return page,result
        for platform,options in [('zalo',{'nested':True}),('messenger',{'nested':False})]:
            if old:
                page,result=run(platform,old,**options)
                assert result['state']=='error' if platform=='messenger' else result['state']=='complete' and len(result['result']['messages'])==15,(platform,result)
                reproduced.append({'platform':platform,'state':result['state'],'count':result.get('count'),'error':result.get('error'),'reason':result.get('reason')});page.close()
            page,result=run(platform,sources,**options)
            assert result['state']=='complete',result
            texts=[row['text'] for row in result['result']['messages']]
            assert len(texts)==50 and texts[0].startswith('Tin 100') and texts[-1].startswith('Tin 149'),texts
            assert 'PRIVATE_' not in json.dumps(result),result
            reports.append({'platform':platform,'diagnostics':result['diagnostics'],'scope':result['result']['scope']})
            page.screenshot(path=str(args.out/(platform+'_loaded.png')))
            page.close();checks.append(platform+'_50_messages_beyond_the_first_15_with_correct_chronological_order')
        for name,options in [('repeated_text',{'repeats':True}),('reverse_scroll',{'reverse':True}),('empty_virtual_page',{'emptyGap':True}),('slow_pagination',{'delayed':True})]:
            page,result=run('messenger',sources,nested=False,**options)
            assert result['state']=='complete' and len(result['result']['messages'])==50,(name,result)
            if name=='repeated_text':assert sum(row['text']=='OK' for row in result['result']['messages'])==5,result
            if name=='reverse_scroll':assert result['result']['messages'][0]['text'].startswith('Tin 100'),result
            page.close();checks.append(name+'_collects_all_50_requested_messages')
        page,result=run('messenger',sources,nested=False,stable=True,edit=True)
        assert result['state']=='complete' and result['result']['updated_messages']>=1,result
        assert any('Bản nội dung đã cập nhật' in row['text'] for row in result['result']['messages'])
        snapshot=result['result'];ids=[item['id'] for item in snapshot['messages']]
        page.locator('#messageViewScroll').evaluate('el=>el.setAttribute("aria-label","Messages in conversation · 1 unread")')
        page.evaluate('updateMetadata()');assert page.evaluate('([id,ids])=>PhishLensConversationReader.validate(id,ids)',[snapshot['id'],ids])['valid']
        checks.append('live_edit_during_collection_keeps_latest_text_and_metadata_rerender_is_not_an_edit')
        page.locator('#messageViewScroll [data-n="100"] .message-text').evaluate('el=>el.textContent="EDIT_AFTER_REVIEW"')
        rejected=page.evaluate('([id,ids])=>{try{PhishLensConversationReader.validate(id,ids);return false}catch{return true}}',[snapshot['id'],ids]);assert rejected
        checks.append('real_message_edit_after_snapshot_invalidates_submission')
        page.close()
        page,result=run('zalo',sources,nested=True)
        page.evaluate('()=>{const view=document.querySelector("#chatView"),header=view.querySelector("header");view.removeAttribute("data-conversation-id");header.id="header";header.querySelector("h1").className="header-title";view.before(header)}')
        snapshot=page.evaluate('()=>PhishLensConversationReader.read()');ids=[item['id'] for item in snapshot['messages']]
        page.locator('header#header .header-title').evaluate('el=>el.textContent="Cuộc trò chuyện khác"')
        assert page.evaluate('([id,ids])=>{try{PhishLensConversationReader.validate(id,ids);return false}catch{return true}}',[snapshot['id'],ids])
        checks.append('real_Zalo_sibling_header_detects_conversation_switch_without_test_only_ID_attribute')
        page.close();browser.close()
    assert not errors,errors
    report={'passed':len(checks),'checks':checks,'baseline_failures_reproduced':reproduced,'collection':reports,'browser_errors':errors,'real_accounts_tested':False,'provider_calls':0,'source_sha256':{name:hashlib.sha256(text.encode()).hexdigest() for name,text in sources.items()},'source_unchanged_during_run':all((ROOT/'extensions/chromium'/name).read_text()==code for name,code in sources.items())}
    (args.out/'checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
