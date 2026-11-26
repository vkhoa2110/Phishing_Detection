"""Check side-panel click ordering and fallback window layout in Chromium JS.

Window API fixtures make placement deterministic without changing the user's
desktop. The quiet-mail browser harness separately checks the real extension.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    from playwright.sync_api import sync_playwright

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(); args.out.mkdir(parents=True, exist_ok=False)
    source = ROOT / 'extensions/chromium'
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chromium', headless=True)
        context = browser.new_context()
        context.route('https://fixture.test/**', lambda route: route.fulfill(body='<html><body>Fixture</body></html>', content_type='text/html'))
        page = context.new_page(); page.goto('https://fixture.test/')
        checks = page.evaluate(r'''async ({workspace, mail}) => {
          const checks = [], assert = (value, message) => { if (!value) throw new Error(message); };
          const clone = value => JSON.parse(JSON.stringify(value));
          function fixture({native = false, state = 'normal', width = 1280, left = 30, screenArea = null} = {}) {
            const windows = new Map([[1, {id:1,type:'normal',state,left,top:40,width,height:880,incognito:false}],
              [2,{id:2,type:'normal',state:'normal',left:-1600,top:20,width:1440,height:900,incognito:false}]]);
            const storage = {}, calls = [], removed = [], messages = [], contexts = [];
            let next = 10, failCreate = false;
            const chrome = {
              runtime:{id:'a'.repeat(32),getURL:path=>'chrome-extension://'+'a'.repeat(32)+'/'+path,
                getContexts:async()=>clone(contexts),onMessage:{addListener:fn=>messages.push(fn)},
                onInstalled:{addListener(){}},onStartup:{addListener(){}},sendMessage:async()=>({})},
              storage:{session:{get:async key=>typeof key==='string'?{[key]:clone(storage[key]??null)}:clone(storage),
                set:async values=>Object.assign(storage,clone(values)),remove:async key=>{delete storage[key]}},
                local:{get:async()=>({mailAssistEnabled:true})}},
              windows:{getAll:async()=>clone([...windows.values()]),get:async id=>{
                if (!windows.has(id)) throw new Error('Closed'); return clone(windows.get(id));},
                update:async(id,change)=>{
                  const current=windows.get(id);if(!current)throw new Error('Closed');
                  if ((change.width||change.height||change.left!==undefined||change.top!==undefined)&&current.state!=='normal')throw new Error('Bounds require normal window');
                  calls.push(['update',id,clone(change)]);Object.assign(current,change);return clone(current);},
                create:async options=>{
                  if(failCreate)throw new Error('fixture creation failure');
                  const id=next++, win={id,type:'popup',state:'normal',left:0,top:0,width:440,height:850,...options};
                  windows.set(id,win);contexts.push({windowId:id,documentUrl:options.url});calls.push(['create',id]);return clone(win);},
                onRemoved:{addListener:fn=>removed.push(fn)}},
              sidePanel:{open:({windowId})=>{calls.push(['native',windowId]);return native?Promise.resolve():Promise.reject(new Error('No side panel'));}},
              tabs:{get:async id=>({id,windowId:1,url:'https://mail.google.com/mail/u/0/#inbox/fixture',active:true}),
                query:async()=>[{id:20,windowId:1,url:'https://mail.google.com/mail/u/0/#inbox/fixture',active:true}],
                onRemoved:{addListener(){}}},
              permissions:{onRemoved:{addListener(){}}},
              scripting:{executeScript:async options=>options.files?[{documentId:'fixture-doc'}]:
                [{documentId:'fixture-doc',result:options.func.toString().includes('screen.avail')?screenArea:options.func.toString().includes('PhishLensMailReader.read')?
                  {text:'Nội dung fixture',contextId:'11111111-1111-4111-8111-111111111111',provider:'Gmail'}:true}]}
            };
            globalThis.chrome=chrome;(new Function(workspace))();
            return {windows,storage,calls,messages,contexts,workspace:PhishLensWorkspace,
              fail:()=>{failCreate=true},remove:id=>{windows.delete(id);return Promise.all(removed.map(fn=>fn(id)))}};
          }
          let f=fixture(), original=clone(f.windows.get(1));
          let details=await f.workspace.open({mode:'text',text:'fixture'},1);
          let main=f.windows.get(1), side=f.windows.get(details.id);
          assert(main.left===original.left&&main.top===side.top&&main.height===side.height,'Aligned tops/heights');
          assert(main.left+main.width+8===side.left&&side.left+side.width===original.left+original.width,'Email left, details right, no overlap');
          assert(side.width>=360&&side.width<=480,'Readable result column');
          checks.push('unsupported_native_panel_tiles_email_left_and_details_right_without_overlap');
          const once=clone(main);
          await Promise.all([f.workspace.open({mode:'text',text:'second'},1),f.workspace.open({mode:'text',text:'third'},1)]);
          assert(JSON.stringify(main)===JSON.stringify(once)&&[...f.windows.values()].filter(w=>w.type==='popup').length===1,'No repeated shrinking or duplicate windows');
          checks.push('repeated_or_concurrent_details_clicks_reuse_the_same_layout_and_window');
          await f.remove(details.id); await f.workspace.popup(null,false);
          assert(JSON.stringify(f.windows.get(1))===JSON.stringify(original),'Restore bounds on close');
          checks.push('closing_details_restores_original_email_window_bounds');

          f=fixture({state:'maximized'});original=clone(f.windows.get(1));details=await f.workspace.open({},1);
          assert(f.calls.find(c=>c[0]==='update')[2].state==='normal','Normalize before applying bounds');
          await f.remove(details.id);await f.workspace.popup(null,false);
          assert(f.windows.get(1).state==='maximized'&&f.windows.get(1).width===original.width,'Restore maximized state');
          checks.push('maximized_source_is_split_and_restored_with_valid_separate_state_updates');

          f=fixture();details=await f.workspace.open({},1);f.windows.get(1).width+=40;
          const moved=clone(f.windows.get(1));await f.remove(details.id);await f.workspace.popup(null,false);
          assert(JSON.stringify(f.windows.get(1))===JSON.stringify(moved),'Respect manual window resize');
          checks.push('closing_details_preserves_a_layout_manually_changed_by_the_user');

          f=fixture();original=clone(f.windows.get(1));details=await f.workspace.open({},1);
          const otherOriginal=clone(f.windows.get(2));await f.workspace.open({},2);
          assert(JSON.stringify(f.windows.get(1))===JSON.stringify(original),'Restore previous browser');
          side=f.windows.get(details.id);main=f.windows.get(2);
          assert(main.left+main.width+8===side.left&&side.left+side.width===otherOriginal.left+otherOriginal.width,'Second monitor supports negative coordinates');
          checks.push('switching_source_windows_restores_the_old_source_and_tiles_on_the_correct_monitor');

          f=fixture({width:820});original=clone(f.windows.get(1));details=await f.workspace.open({},1);
          main=f.windows.get(1);side=f.windows.get(details.id);
          assert(main.top+main.height+8===side.top&&side.top+side.height===original.top+original.height&&side.width===820,'Narrow layout fits available bounds');
          checks.push('narrow_windows_stack_readable_views_within_the_original_area');

          f=fixture({width:1900,screenArea:{left:0,top:0,width:1280,height:800}});details=await f.workspace.open({},1);
          main=f.windows.get(1);side=f.windows.get(details.id);
          assert(main.left+main.width+8===side.left&&side.left+side.width<=1280&&side.top+side.height<=800,'Both windows inside available display');
          checks.push('oversized_or_offscreen_browser_bounds_are_clamped_to_the_available_display');

          f=fixture();original=clone(f.windows.get(1));details=await f.workspace.open({},1);
          chrome.sidePanel.open=()=>Promise.resolve();await f.workspace.open({},1);
          assert(JSON.stringify(f.windows.get(1))===JSON.stringify(original)&&f.windows.get(details.id).state==='minimized','Native panel replaces dock without overlapping window');
          checks.push('switching_to_native_panel_restores_mail_and_minimizes_the_previous_docked_window');

          f=fixture();original=clone(f.windows.get(1));f.fail();
          let failed=false;try{await f.workspace.open({},1)}catch{failed=true}
          assert(failed&&JSON.stringify(f.windows.get(1))===JSON.stringify(original)&&!f.storage.workspaceDock,'Rollback failed creation');
          checks.push('failed_window_creation_rolls_back_the_email_layout');

          f=fixture({native:true});(new Function(mail))();
          f.storage['mail-job-20']={id:'22222222-2222-4222-8222-222222222222',created:Date.now(),context:{tabId:20,id:'11111111-1111-4111-8111-111111111111'}};
          const listener=f.messages[f.messages.length-1];let reply;
          const delivered=new Promise(resolve=>{reply=resolve});
          listener({type:'MAIL_DETAILS',contextId:'11111111-1111-4111-8111-111111111111'},
            {id:'a'.repeat(32),url:'https://mail.google.com/mail/u/0/#inbox/fixture',frameId:0,tab:{id:20,windowId:1,url:'https://mail.google.com/mail/u/0/#inbox/fixture',active:true}},reply);
          assert(f.calls[0]?.[0]==='native','Native open invoked synchronously before async validation');
          const result=await delivered;
          assert(result.status==='opened'&&f.calls.filter(c=>c[0]==='native').length===1&&!f.calls.some(c=>c[0]==='create'||c[0]==='update'),'Native path uses no OS popup or browser resize');
          assert(f.storage.panelInput.job.id==='22222222-2222-4222-8222-222222222222','Existing completed job delivered');
          checks.push('mail_details_preserves_the_click_gesture_and_delivers_the_existing_job_to_native_side_panel');

          f=fixture();original=clone(f.windows.get(1));details=await f.workspace.open({},1);
          const detached=new Promise(resolve=>f.messages[0]({type:'DETACH_WORKSPACE',input:{mode:'url',text:'https://example.org'}},
            {id:'a'.repeat(32),url:chrome.runtime.getURL('check.html')},resolve));
          const detachedResult=await detached;
          assert(detachedResult.windowId===details.id&&JSON.stringify(f.windows.get(1))===JSON.stringify(original),'Explicit detach restores main and keeps singleton');
          checks.push('explicit_detach_restores_mail_and_reuses_the_existing_details_window');
          return checks;
        }''', {'workspace': (source/'workspace.js').read_text(), 'mail': (source/'mail.js').read_text()})
        context.close(); browser.close()
    report = {'passed': len(checks), 'checks': checks, 'provider_calls': 0,
        'limits': 'Actual extension JS in Chromium with deterministic browser-window API fixtures; no real Brave/OS window placement measured.',
        'source_sha256': {str(source/name): hashlib.sha256((source/name).read_bytes()).hexdigest() for name in ['workspace.js','mail.js']}}
    (args.out/'checks.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
