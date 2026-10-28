"""Render provisional AI annotations as a searchable offline HTML review sheet."""
import argparse
import hashlib
import json
from pathlib import Path

TEMPLATE = r'''<!doctype html><html lang="vi"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Rà soát nhãn AI sơ bộ — SMS Việt Nam</title>
<style>
:root{font:16px/1.55 system-ui,sans-serif;color:#182537;background:#f2f5fa}*{box-sizing:border-box}
body{max-width:1120px;margin:auto;padding:28px 20px}h1{font-size:28px;line-height:1.25;margin:0 0 10px}
header{padding:26px;background:#fff;border:1px solid #dce4ee;border-radius:16px}p{margin:8px 0}
.notice{background:#fff4d6;border-left:4px solid #b77900;padding:12px 16px;margin-top:18px}
.stats{display:flex;gap:12px;flex-wrap:wrap;margin:20px 0}.stat{background:white;padding:12px 18px;border-radius:10px;border:1px solid #dce4ee}
.toolbar{display:flex;gap:12px;align-items:end;flex-wrap:wrap;margin:20px 0}label{display:flex;flex-direction:column;gap:5px;font-weight:600;font-size:14px}
input,select{font:inherit;padding:10px;border:1px solid #adbacd;border-radius:8px;background:#fff;max-width:100%}
label.search{flex:1;min-width:200px}.check{flex-direction:row;align-items:center;padding:10px 0}
article{background:#fff;border:1px solid #dce4ee;border-radius:12px;padding:20px;margin:14px 0;overflow-wrap:anywhere}
.meta{display:flex;gap:10px;align-items:center;flex-wrap:wrap;font-size:13px;color:#495b72}.badge{font-weight:700;padding:4px 9px;border-radius:6px}
.label-0{background:#e4f2f3;color:#07505a}.label-1{background:#ffe7e7;color:#8d1823}.label-UNKNOWN{background:#fff1c8;color:#705000}
.text{white-space:pre-wrap;margin:16px 0;font-size:17px}.reason{padding-top:12px;border-top:1px solid #e5eaf1}
.quote{border-left:3px solid #7186a0;padding-left:12px;white-space:pre-wrap}.small{font-size:13px;color:#495b72}
a{color:#164fb0}button{cursor:pointer}#empty{background:white;padding:20px;border-radius:10px}
@media(max-width:520px){body{padding:16px 12px}header{padding:18px}h1{font-size:23px}article{padding:16px}.toolbar>label{width:100%}.stat{flex:1;min-width:110px}}
</style><header><h1>Rà soát nhãn AI sơ bộ</h1>
<p>200 SMS bên ngoài đã được che dữ liệu. Mỗi nhãn kèm lý do để bạn kiểm tra và sửa sau.</p>
<div class="notice"><strong>Chưa có người kiểm chứng — không phải gold.</strong>
Nhãn 0 chỉ nghĩa là chưa thấy hành vi lừa đảo rõ trong văn bản; không xác nhận người gửi hay URL an toàn.
Mức chắc chắn do AI tự đánh giá, chưa được hiệu chỉnh. Muốn gán nhãn mù độc lập, dùng hai phiếu trống và không xem trang này trước.</div>
<p class="small" id="model"></p><p><a href="review_all.csv" download>Tải toàn bộ CSV</a> · <a href="priority_review.csv" download>Tải danh sách ưu tiên rà soát</a></p></header>
<div class="stats" id="stats"></div>
<div class="toolbar"><label class="search">Tìm nội dung hoặc lý do<input id="search" type="search" placeholder="Ví dụ: OTP, quảng cáo, nhận thưởng"></label>
<label>Nhãn AI<select id="label"><option value="all">Tất cả</option><option value="1">1 — Có dấu hiệu lừa đảo</option><option value="0">0 — Chưa thấy lừa đảo rõ</option><option value="UNKNOWN">UNKNOWN — Thiếu ngữ cảnh</option></select></label>
<label class="check"><input id="priority" type="checkbox">Chỉ các mẫu ưu tiên</label></div>
<p class="small" id="count" aria-live="polite"></p><main id="rows"></main><p id="empty" hidden>Không có mẫu khớp bộ lọc.</p>
<script id="data" type="application/json">__DATA__</script>
<script>
'use strict';
const data=JSON.parse(document.getElementById('data').textContent), rows=data.rows;
const labels={'0':'0 — Chưa thấy lừa đảo rõ','1':'1 — Có dấu hiệu lừa đảo','UNKNOWN':'UNKNOWN — Thiếu ngữ cảnh'};
const confidence={high:'cao',medium:'vừa',low:'thấp'};
function node(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e}
document.getElementById('model').textContent='Mô hình gán nhãn: '+data.model+'. Chỉ dùng văn bản đã che; không dùng nhãn nguồn, ML hoặc RAG.';
for(const k of ['0','1','UNKNOWN']){const n=rows.filter(r=>String(r.label===null?'UNKNOWN':r.label)===k).length;document.getElementById('stats').append(node('div',n+' · '+labels[k],'stat'))}
function render(){const q=document.getElementById('search').value.toLocaleLowerCase('vi'),label=document.getElementById('label').value,priority=document.getElementById('priority').checked;
 const selected=rows.filter(r=>(label==='all'||String(r.label===null?'UNKNOWN':r.label)===label)&&(!priority||r.label===null||r.label===1||r.confidence!=='high')&&(!q||(r.text+' '+r.notes+' '+r.id).toLocaleLowerCase('vi').includes(q)));
 const root=document.getElementById('rows');root.replaceChildren();
 for(const r of selected){const card=node('article'),meta=node('div',undefined,'meta'),k=String(r.label===null?'UNKNOWN':r.label);
  meta.append(node('span',labels[k],'badge label-'+k),node('span',r.id),node('span','AI tự đánh giá: '+confidence[r.confidence]));
  card.append(meta,node('div',r.text,'text'),node('div',r.notes,'reason'));
  if(r.evidence_quote)card.append(node('p','Đoạn AI viện dẫn:','small'),node('div',r.evidence_quote,'quote'));
  card.append(node('p','Nhóm nội dung: '+r.category+(r.annotation_available?'':' · Chưa có phản hồi AI hợp lệ'),'small'));root.append(card)}
 document.getElementById('count').textContent='Đang hiện '+selected.length+'/'+rows.length+' mẫu.';document.getElementById('empty').hidden=selected.length>0;
}
for(const id of ['search','label','priority'])document.getElementById(id).addEventListener('input',render);render();
</script></html>'''


def render(directory):
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest.get("status") != "ai_preliminary": raise ValueError("Expected provisional AI annotations.")
    path = directory / "labels.jsonl"
    if hashlib.sha256(path.read_bytes()).hexdigest() != manifest["files"]["labels.jsonl"]:
        raise ValueError("Annotation file changed.")
    rows = [json.loads(line) for line in path.read_text().splitlines() if line]
    if any(r.get("annotation_status") != "ai_preliminary" or r.get("independent_human_review") is not False for r in rows):
        raise ValueError("All labels must be explicitly provisional AI labels.")
    data = {"model": manifest["configuration"]["model"], "rows": rows}
    serialized = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    output = TEMPLATE.replace("__DATA__", serialized).replace("200 SMS", f"{len(rows)} SMS")
    (directory / "index.html").write_text(output, encoding="utf-8")
    return directory / "index.html"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    print(render(parser.parse_args().directory))


if __name__ == "__main__": main()
