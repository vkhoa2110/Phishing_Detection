"""Audit text-action references separately from unverified whole-message risk."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path

from app.services.llm.client import approved_ml_metadata
from evaluation.common import registered
from evaluation.data.sms import read_jsonl, sha, spreadsheet_cell, write_json, write_jsonl
from evaluation.messages.core_pilot import parse_response


def review_rows(cases):
    """Hide model predictions and preliminary AI labels from the review worksheet."""
    return [{"id": c["id"], "text": c["text"], "behavior_label": "", "whole_message_label": "",
        "url_evidence_status": "", "evidence_source_url": "", "evidence_observed_at": "",
        "reviewer": "", "notes": ""} for c in sorted(cases, key=lambda c: c["id"])]


def run(study, out):
    study, out = Path(study), Path(out)
    if out.exists(): raise ValueError("Preserve existing review work.")
    if not registered.verify(study, parse_response)["complete"]:
        raise ValueError("Audit a complete study, including all failures.")
    config, _ = registered.load(study)
    meta = config["metadata"]
    pack, labels = Path(meta["pack"]), Path(meta["labels"])
    cases = read_jsonl(pack / "sms.jsonl")
    references = {r["id"]: r for r in read_jsonl(labels / "labels.jsonl")}
    if set(references) != {c["id"] for c in cases}:
        raise ValueError("Case/reference inventories differ.")
    source = Path(meta["URL_scores_origin"])
    prepared = json.loads(source.read_text())
    rows = []
    for case in cases:
        reference = references[case["id"]]
        context = bool(approved_ml_metadata(case["text"], prepared[case["id"]]["url_results"]))
        rows.append({"id": case["id"], "AI_behavior_label": reference["label"],
            "reference_notes": reference.get("notes", ""), "URL_context_available": context,
            "whole_message_gold": None, "URL_gold": None,
            "human_reviewed": reference.get("human_reviewed") is True,
            "negative_reference_proves_safe_URL": False})
    counts = Counter(("with_URL" if r["URL_context_available"] else "without_URL") + "_" +
        ("UNKNOWN" if r["AI_behavior_label"] is None else str(r["AI_behavior_label"])) for r in rows)
    out.mkdir(parents=True)
    write_jsonl(out / "inherited_reference_scope.jsonl", rows)
    review = review_rows(cases)
    with (out / "whole_message_review.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(review[0]))
        writer.writeheader()
        writer.writerows({k: spreadsheet_cell(v) for k, v in row.items()} for row in review)
    write_json(out / "manifest.json", {"case_sha256": sha(pack / "sms.jsonl"),
        "labels_sha256": sha(labels / "labels.jsonl"), "URL_cache_sha256": sha(source),
        "study_seal_sha256": sha(study / "result_hashes.json"), "audit_source_sha256": sha(__file__),
        "counts": dict(counts), "whole_message_gold_created": 0, "API_calls": 0,
        "reserve_inference": False, "review_is_not_yet_completed": True})
    (out / "report.md").write_text("""# Phạm vi nhãn: hành vi trong text và rủi ro toàn thông điệp

Các tỷ lệ Accuracy/F1 hiện tại đo mức khớp reference AI sơ bộ về hành vi được nêu trong text. Nhiều nhãn 0 có ghi chú rõ chưa xác minh URL/người gửi. Không được đổi cách diễn giải thành “SMS/URL an toàn”, hoặc dùng số bất đồng này như số cảnh báo sai đã xác minh ngoài thực tế.

Có 26 nhãn 0 và 13 UNKNOWN nhận thêm URL context; không có nhãn 1 ở nhóm này. Bốn nhãn 1 đều không có URL context. Thiết kế hiện tại không đo được lợi ích Recall khi model URL phát hiện đường dẫn độc hại trong một thông điệp có lời văn bình thường.

`whole_message_review.csv` chứa đúng 80 SMS dev, không lộ điểm model hoặc nhãn AI trong phiếu. Chưa có hàng nào được chấm; 120 reserve chưa được mở. File reference kế bên chỉ phục vụ kiểm nguồn gốc nhãn cũ, không đưa cho người chấm khi muốn giữ mù.

## Rubric cần thống nhất trước khi gán nhãn

- `behavior_label`: `dangerous_request`, `none_observed`, `unclear`. Xét yêu cầu lấy bí mật, tiền hoặc quyền truy cập và dấu hiệu dẫn dụ trong nội dung. `none_observed` không chứng minh người gửi đáng tin.
- `whole_message_label`: `phishing`, `benign`, `unknown`. Cần đủ bằng chứng về toàn tình huống, có thể bao gồm nguồn xác nhận URL/người gửi; không tự sao chép nhãn hành vi.
- `url_evidence_status`: `supported_malicious`, `supported_legitimate`, `unverified`, `no_url`. Ghi nguồn bằng chứng và thời điểm; model score, chuỗi tên miền hoặc bài cảnh báo chung không tự là nhãn chuẩn.
- Trường `evidence_source_url` là trang bằng chứng, không yêu cầu truy cập trực tiếp URL nghi vấn. Thiếu bằng chứng thì giữ `unknown`/`unverified`; không giả nhãn để đủ hai lớp.

Phiếu này chưa là benchmark mới. Trước khi công bố chất lượng toàn thông điệp cần review độc lập, phân xử bất đồng, khóa dữ liệu, kiểm trùng miền/campaign và ghi rõ mục tiêu đánh giá. Không sửa nhãn AI cũ theo output vừa quan sát; không tối ưu prompt để tự động LOW cho những SMS chỉ đang thiếu bằng chứng.
""")
    return dict(counts)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--study", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(run(a.study, a.out), indent=2))
