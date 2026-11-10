"""Render a local, prediction-blind official-origin review worksheet.

Reads only verified reference metadata; never reads model scores or risk labels.
The static file has no API, external assets, autosave or automatic navigation.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evaluation.data.sms import read_jsonl, sha
from evaluation.data.official_urls import REVIEW_FIELDS, verify


def blind_records(rows):
    """An explicit field projection prevents predictions entering the worksheet."""
    return [{"id": row["id"], "url": row["url"], "publisher": row["publisher"],
             "region": row["region"], "tags": row["tags"],
             "source_url": row["evidence"]["source_url"],
             "final_source_url": row["evidence"]["final_url"],
             "retrieved_at": row["evidence"]["retrieved_at"],
             "route_publication": {key: row["evidence"]["route_publication"].get(key, "") for key in ("relation", "href", "title", "anchor")},
             "separate_source": row["url"] != row["evidence"]["source_url"]} for row in rows]


TEMPLATE = r'''<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'none'; connect-src 'none'; form-action 'none'; base-uri 'none'; object-src 'none'">
<title>Phiếu review URL · PhishLens</title>
<style>
:root{color-scheme:light;font:15px/1.55 system-ui,sans-serif;color:#152b3d;background:#f3f6f8;--accent:#086b63}
*{box-sizing:border-box}body{margin:0}button,input,select,textarea{font:inherit}button{cursor:pointer}a{color:inherit}
header{background:#fff;border-bottom:1px solid #dce5e9;padding:24px max(20px,calc((100vw - 1120px)/2))}
.eyebrow{color:var(--accent);font-weight:750;font-size:.8rem;letter-spacing:.12em}h1{font-size:clamp(1.5rem,3vw,2.1rem);margin:5px 0 8px;line-height:1.25}p{margin:8px 0}.muted{color:#587080}.wrap{max-width:1160px;margin:0 auto;padding:24px 20px 60px}
.notice{background:#fff8e9;border:1px solid #ead5a5;border-radius:12px;padding:18px 20px}.notice strong{color:#785511}
details{margin:12px 0}summary{cursor:pointer;font-weight:650}ul{padding-left:22px}.toolbar{display:flex;align-items:end;gap:14px;flex-wrap:wrap;margin:24px 0 16px}
.reviewer{flex:1;min-width:220px}.reviewer label{font-weight:650;display:block;margin-bottom:5px}input,select,textarea{border:1px solid #b9cbd2;border-radius:8px;background:#fff;padding:10px 12px;width:100%;color:#152b3d}input:focus,select:focus,textarea:focus{outline:3px solid #b9e1d8;outline-offset:1px}textarea{min-height:95px;resize:vertical}button{border:0;border-radius:8px;background:var(--accent);color:#fff;padding:11px 18px;font-weight:700}button.secondary{background:#fff;color:var(--accent);border:1px solid #99bcb6}.status{min-height:24px;color:#845c18;font-weight:600;overflow-wrap:anywhere}.progress{font-size:.9rem;color:#496371;margin-bottom:20px}
.cards{display:grid;gap:18px}.card{background:#fff;border:1px solid #d8e2e7;border-radius:14px;padding:22px;box-shadow:0 3px 12px #173c4c06}.card-head{display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;margin-bottom:8px}.badge{padding:3px 9px;background:#eaf4f0;color:#206052;font-size:.78rem;border-radius:16px;font-weight:650}.id{font-size:.8rem;color:#637a86}.url{display:block;font:500 .92rem/1.6 ui-monospace,monospace;background:#f2f6f8;border-radius:8px;padding:12px;overflow-wrap:anywhere;white-space:pre-wrap;word-break:break-word;user-select:all}.tags{display:flex;gap:6px;flex-wrap:wrap;margin:10px 0}.tag{font-size:.76rem;border:1px solid #dae6e9;padding:2px 7px;border-radius:5px;color:#53707a}.evidence{background:#f8fafb;border-radius:9px;padding:12px 14px;margin:12px 0;font-size:.88rem}.evidence p{margin:5px 0;overflow-wrap:anywhere}.evidence code{font-size:.8rem;word-break:break-word}.fields{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:18px}.field label{display:block;font-weight:650;margin-bottom:5px}.field small{color:#5c7480;display:block;margin-top:4px}.rationale{grid-column:1/-1}.complete{border-color:#71b29d}.bottom{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-top:25px}.foot{font-size:.82rem;color:#5b737d;margin-top:24px;overflow-wrap:anywhere}.group-title{font-weight:700;margin:0}.pill{background:#eef4f6;border-radius:8px;padding:10px 13px;font-size:.85rem;color:#4b6875}
@media(max-width:600px){header{padding:20px}.wrap{padding:18px 12px 40px}.card{padding:15px}.fields{grid-template-columns:1fr}.rationale{grid-column:auto}.toolbar{gap:10px}.toolbar button{flex:1}.reviewer{min-width:100%}.notice{padding:14px}.bottom button{width:100%}}
</style></head><body>
<header><div class="eyebrow">PHISHLENS · REVIEW CỤC BỘ</div><h1>Đánh giá URL theo chứng cứ</h1><p class="muted">Phiếu mù với dự đoán. Bạn tự đánh giá nguồn gốc và rủi ro riêng biệt.</p></header>
<main class="wrap">
<section class="notice"><strong>Nguồn chính thức chưa đủ để gán nhãn an toàn.</strong><p>Các URL dưới đây được AI chọn để đối chiếu nguồn gốc. Chưa có nhãn rủi ro đã xác minh. Trang chính thức vẫn có thể bị xâm nhập hoặc chứa nội dung do người dùng đăng.</p>
<details><summary>Hướng dẫn đánh giá và sử dụng kết quả</summary><ul>
<li><b>Nguồn gốc:</b> xem chứng cứ có hỗ trợ tuyến chính thức của tổ chức hay không. Self-link hoặc chính trang tự phục vụ là chứng cứ yếu hơn một tài liệu khác dẫn đường.</li>
<li><b>Nhãn 0:</b> chỉ chọn khi đã đối chiếu chứng cứ phù hợp và có cơ sở cho hành vi/dịch vụ hợp lệ của URL cụ thể. Tên miền quen thuộc hoặc không thấy từ đáng ngờ chưa đủ.</li>
<li><b>Nhãn 1:</b> cần chứng cứ cụ thể về lừa đảo hoặc abuse. Từ “login”, “payment”, đường dẫn dài không tự chứng minh rủi ro.</li>
<li><b>UNKNOWN:</b> dùng khi thiếu ngữ cảnh hoặc chưa đủ chứng cứ. Để trống nghĩa là chưa đánh giá, khác UNKNOWN đã được xem xét.</li>
<li>Ghi lý do, phạm vi và nguồn đã kiểm tra. Mỗi người đánh giá độc lập bằng mã riêng; một phiếu của một người chưa tạo thành gold.</li>
</ul><p>Trang này không mở URL, gọi API hay lưu vào trình duyệt. Đóng/tải lại trang sẽ mất phần chưa tải CSV. CSV là bản review mới, không thay thế dữ liệu gốc và không tự nâng nhãn thành gold.</p></details></section>
<div class="toolbar"><div class="reviewer"><label for="reviewer">Mã người đánh giá</label><input id="reviewer" autocomplete="off" spellcheck="false" maxlength="80" placeholder="Ví dụ: reviewer-khoa"></div><button id="download-top" type="button">Tải bản review CSV</button></div>
<div id="status" class="status" role="status" aria-live="polite"></div><p id="progress" class="progress"></p><div id="cards" class="cards"></div>
<div class="bottom"><p class="muted">Nhãn chưa chọn được giữ trống trong CSV.</p><button id="download-bottom" type="button">Tải bản review CSV</button></div>
<p class="foot">Dữ liệu: official_url_reference_v1 · Khóa tham chiếu: <span id="fingerprint"></span>. Chỉ chứa metadata đã kiểm tra, không kèm điểm hay kết luận của hệ thống.</p>
</main><script id="review-data" type="application/json">__PAYLOAD__</script>
<script>
'use strict';
const data = JSON.parse(document.getElementById('review-data').textContent);
const state = new Map(data.records.map(row => [row.id, {origin_assessment:'',risk_label:'',rationale:''}]));
const tags = {login:'Đăng nhập',password_reset:'Khôi phục mật khẩu',payment:'Thanh toán',query:'Có query',long_path:'Đường dẫn dài',article:'Bài viết',homepage:'Trang chủ',university:'Đại học',government:'Công',bank:'Ngân hàng',utility:'Điện lực',support:'Hỗ trợ'};
function el(tag,text,className){const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(className)node.className=className;return node;}
function validDecision(value){return (value.origin_assessment!=='' || value.risk_label!=='') && value.rationale.trim()!=='';}
function progress(){let decisions=0,risks=0;for(const value of state.values()){if(validDecision(value))decisions++;if(value.risk_label!=='' && value.rationale.trim())risks++;}document.getElementById('progress').textContent=`${decisions}/${data.records.length} mẫu có đánh giá và lý do · ${risks} mẫu có nhãn rủi ro (kể cả UNKNOWN)`;}
function option(value,label){const node=el('option',label);node.value=value;return node;}
function selectField(row,field,title,choices,help){const wrap=el('div',undefined,'field');const id=`${row.id}-${field}`;const label=el('label',title);label.htmlFor=id;const select=el('select');select.id=id;select.dataset.field=field;for(const [value,text] of choices)select.append(option(value,text));select.addEventListener('change',()=>{state.get(row.id)[field]=select.value;refreshCard(row.id);});wrap.append(label,select,el('small',help));return wrap;}
function refreshCard(id){document.getElementById(`card-${id}`).classList.toggle('complete',validDecision(state.get(id)));progress();document.getElementById('status').textContent='';}
function addEvidenceLine(box,label,value){const p=el('p');p.append(el('b',label+' '),el('span',value));box.append(p);}
for(const row of data.records){
 const card=el('article',undefined,'card');card.id=`card-${row.id}`;
 const head=el('div',undefined,'card-head');head.append(el('strong',row.publisher),el('span',row.region==='VN'?'Việt Nam':'Quốc tế','badge'),el('span',row.id,'id'));card.append(head,el('code',row.url,'url'));
 const tagbox=el('div',undefined,'tags');for(const tag of row.tags)tagbox.append(el('span',tags[tag]||tag,'tag'));card.append(tagbox);
 const evidence=el('div',undefined,'evidence');addEvidenceLine(evidence,'Chứng cứ:',row.separate_source?'Tài liệu khác của tổ chức dẫn tuyến này.':(row.route_publication.relation==='published_link'?'Chính trang chứa self-link; chưa phải xác nhận độc lập.':'Chính tuyến trả tài liệu HTML; chưa phải xác nhận độc lập.'));
 addEvidenceLine(evidence,'Nguồn:',row.source_url);if(row.final_source_url!==row.source_url)addEvidenceLine(evidence,'Nguồn sau chuyển hướng:',row.final_source_url);
 if(row.route_publication.title)addEvidenceLine(evidence,'Tiêu đề nguồn:',row.route_publication.title);
 if(row.route_publication.anchor)addEvidenceLine(evidence,'Văn bản liên kết:',row.route_publication.anchor);
 addEvidenceLine(evidence,'Thu lúc (UTC):',row.retrieved_at);card.append(evidence);
 const fields=el('div',undefined,'fields');fields.append(selectField(row,'origin_assessment','1. Đánh giá nguồn gốc',[
 ['','Chưa đánh giá'],['supported','Có chứng cứ hỗ trợ tuyến chính thức'],['insufficient','Chứng cứ nguồn gốc chưa đủ'],['conflicting','Có chứng cứ mâu thuẫn'],['UNKNOWN','UNKNOWN — chưa thể quyết định']], 'Đánh giá này không tự quyết định nhãn rủi ro.'));
 fields.append(selectField(row,'risk_label','2. Nhãn rủi ro URL',[
 ['','Chưa đánh giá'],['0','0 — Có cơ sở về hành vi/dịch vụ hợp lệ'],['1','1 — Có chứng cứ lừa đảo hoặc abuse'],['UNKNOWN','UNKNOWN — chưa đủ căn cứ']], 'Không suy nhãn từ độ dài URL hoặc từ khóa riêng lẻ.'));
 const notes=el('div',undefined,'field rationale');const label=el('label','3. Lý do và chứng cứ đã đối chiếu');label.htmlFor=`${row.id}-rationale`;const input=el('textarea');input.id=label.htmlFor;input.dataset.field='rationale';input.maxLength=8000;input.placeholder='Nêu chứng cứ, nguồn đã đối chiếu và điều còn chưa xác minh. Không nhập dữ liệu cá nhân.';input.addEventListener('input',()=>{state.get(row.id).rationale=input.value;refreshCard(row.id);});notes.append(label,input);fields.append(notes);card.append(fields);document.getElementById('cards').append(card);
}
document.getElementById('fingerprint').textContent=data.records_sha256;progress();
function safeCSV(value){let text=String(value??'');if(/^[\s]*[=+@-]/.test(text))text="'"+text;return '"'+text.replace(/"/g,'""')+'"';}
function download(){
 const status=document.getElementById('status');const reviewer=document.getElementById('reviewer').value.trim();if(!reviewer){status.textContent='Nhập mã người đánh giá trước khi tải CSV.';document.getElementById('reviewer').focus();return;}
 let count=0;for(const row of data.records){const value=state.get(row.id);if((value.origin_assessment||value.risk_label) && !value.rationale.trim()){status.textContent=`Mẫu ${row.id} đã chọn đánh giá nhưng chưa có lý do. Vui lòng bổ sung.`;document.getElementById(`${row.id}-rationale`).focus();return;}if(value.rationale.trim() && !value.origin_assessment && !value.risk_label){status.textContent=`Mẫu ${row.id} có ghi chú nhưng chưa chọn đánh giá nguồn gốc hoặc nhãn rủi ro.`;return;}if(validDecision(value))count++;}
 if(count===0){status.textContent='Chưa có quyết định kèm lý do để tải. Bạn có thể chọn UNKNOWN nếu đã xem xét nhưng thiếu chứng cứ.';return;}
 const lines=[data.csv_fields.map(safeCSV).join(',')];for(const row of data.records){const value=state.get(row.id);const record={id:row.id,url:row.url,publisher:row.publisher,tags:row.tags.join('|'),origin_assessment:value.origin_assessment,risk_label:value.risk_label,rationale:value.rationale.trim(),reviewer_id:validDecision(value)?reviewer:''};lines.push(data.csv_fields.map(key=>safeCSV(record[key])).join(','));}
 const blob=new Blob(['\ufeff'+lines.join('\r\n')+'\r\n'],{type:'text/csv;charset=utf-8'});const href=URL.createObjectURL(blob);const anchor=el('a');anchor.href=href;anchor.download=`official_url_reference_v1_review_${reviewer.replace(/[^a-zA-Z0-9_-]/g,'_').slice(0,60)}_${new Date().toISOString().replace(/[:.]/g,'-')}.csv`;document.body.append(anchor);anchor.click();anchor.remove();setTimeout(()=>URL.revokeObjectURL(href),1000);status.textContent=`Đã tạo CSV mới: ${count}/${data.records.length} mẫu có đánh giá và lý do. Dữ liệu tham chiếu gốc được giữ nguyên.`;
}
document.getElementById('download-top').addEventListener('click',download);document.getElementById('download-bottom').addEventListener('click',download);
</script></body></html>
'''


def render_review(records_dir, out):
    records_dir, out = Path(records_dir), Path(out)
    if out.exists():
        raise ValueError("Choose a new output file; never overwrite a review artifact.")
    result = verify(records_dir)
    rows = blind_records(read_jsonl(records_dir / "records.jsonl"))
    payload = json.dumps({"records": rows, "records_sha256": sha(records_dir / "records.jsonl"), "csv_fields": REVIEW_FIELDS}, ensure_ascii=False)
    # Inline JSON must not close its script element, including hostile evidence.
    payload = payload.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(TEMPLATE.replace("__PAYLOAD__", payload), encoding="utf-8")
    return {"output": str(out.resolve()), "records": len(rows), "reference_verified": result["verified"], "API_calls": 0, "external_requests": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path, default=ROOT / "data/annotation/official_url_reference_v1")
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts/evaluations/official_url_reference_v1/review/index.html")
    args = parser.parse_args()
    print(json.dumps(render_review(args.records, args.out), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
