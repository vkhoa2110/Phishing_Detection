"""Replay all saved responses to audit presentation, never infer new labels."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path

from app.domain.claim_grounding import VERSION, guard_presentation
from evaluation.common import registered
from evaluation.data.sms import sha, spreadsheet_cell, write_json, write_jsonl
from evaluation.messages.core_pilot import parse_response


def audit(study, out):
    study, out = Path(study), Path(out)
    if out.exists(): raise ValueError("Keep existing audits immutable; choose a new output directory.")
    verification = registered.verify(study, parse_response)
    if not verification["complete"]: raise ValueError("Audit the complete inventory, including technical errors.")
    config, requests = registered.load(study)
    _, records = registered.checkpoints(study, config)
    rows, review = [], []
    for key, request in requests.items():
        original = records[key]["parsed"]
        before = original.get("verdict", {})
        presented = guard_presentation({**original, "input_used": request["text"]})
        after = presented.get("verdict", {})
        for name in ("risk_level", "context_kind", "recommended_actions"):
            if before.get(name) != after.get(name): raise ValueError("The presentation layer changed a decision.")
        if original.get("core_decision") != presented.get("core_decision") or original["status"] != presented["status"]:
            raise ValueError("A raw decision or error was changed.")
        old_quotes = [e["quote"] for e in before.get("evidence", [])]
        if old_quotes != [e["quote"] for e in after.get("evidence", [])]: raise ValueError("A quote changed.")
        grounding = presented.get("claim_grounding", {})
        row = {"request_key": request["key"], "case_id": request["case_id"], "profile": request["profile"],
               "technical_status": original["status"], "error": original.get("code"),
               "risk_before": before.get("risk_level"), "risk_after": after.get("risk_level"),
               "reason_code": original.get("core_decision", {}).get("reason_code"),
               "summary_before": before.get("summary"), "summary_after": after.get("summary"),
               "quotes": old_quotes, "claim_grounding": grounding or None,
               "classification_changed": False, "technical_status_changed": False}
        rows.append(row)
        if grounding.get("status") == "needs_review":
            review.append({"request_key": request["key"], "case_id": request["case_id"],
                "approved_text": request["text"], "model_reason_code": row["reason_code"],
                "quotes": json.dumps(old_quotes, ensure_ascii=False), "summary_before": row["summary_before"],
                "summary_after": row["summary_after"], "human_support_before_0_2": "",
                "human_support_after_0_2": "", "reviewer": "", "notes": ""})
    counts = Counter((r["claim_grounding"] or {}).get("status", "not_applied") for r in rows)
    reasons = Counter(r["reason_code"] for r in rows if (r["claim_grounding"] or {}).get("status") == "needs_review")
    result = {"purpose": "Retrospective presentation audit, not a new phishing accuracy evaluation",
              "version": VERSION, "requests": len(rows), "counts": dict(counts),
              "review_by_reason": dict(reasons), "changed_summaries": sum(r["summary_before"] != r["summary_after"] for r in rows),
              "classification_changes": 0, "technical_status_changes": 0, "API_calls": 0,
              "human_gold_created": 0, "semantic_support_verified": False,
              "F1_change": 0, "independent_F1": None, "reserve_inference": False}
    out.mkdir(parents=True)
    write_jsonl(out / "per_request.jsonl", rows)
    write_json(out / "metrics.json", result)
    if review:
        with (out / "review.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(review[0]))
            writer.writeheader()
            writer.writerows({k: spreadsheet_cell(v) for k, v in r.items()} for r in review)
    write_json(out / "manifest.json", {"source_study": str(study.resolve()), "verification": verification,
        "result_seal_sha256": sha(study / "result_hashes.json"), "execution_sha256": sha(study / "execution.json"),
        "guard_source_sha256": sha(Path("app/domain/claim_grounding.py")), "audit_source_sha256": sha(__file__),
        "metrics_sha256": sha(out / "metrics.json"), "per_request_sha256": sha(out / "per_request.jsonl")})
    (out / "report.md").write_text(f"""# Kiểm tra lời giải thích từ phản hồi đã lưu

Phạm vi: toàn bộ **{len(rows)}** request vật lý của lượt đã khóa; không chỉ chọn mẫu model sai. Không gọi lại API, không mở reserve, không đổi nhãn. Nhóm v6.1 và lỗi kỹ thuật được giữ trong mẫu số và không áp dụng bộ diễn giải core.

| Kết quả kiểm tra | Số request |
|---|---:|
| Thiếu cue hoặc có phủ định/ngôn ngữ phòng tránh: cần review | {counts['needs_review']} |
| Có các cue tối thiểu trong cùng mệnh đề | {counts['lexical_cues_present']} |
| Core LOW/UNKNOWN, không có khẳng định cơ chế cảnh báo | {counts['not_applicable']} |
| Profile khác hoặc lỗi, không áp dụng | {counts['not_applied']} |
| Đổi mức kết luận hoặc trạng thái kỹ thuật | 0 |

Đã điều chỉnh {result['changed_summaries']} phần tóm tắt. Cơ chế luôn được ghi là nhận định AI; thiếu cue thì dùng tóm tắt trung tính. Trích dẫn, reason_code gốc, risk level và lỗi không đổi. Vì vậy Accuracy/Recall/F1 của lượt cũ **không tăng**, cũng không được diễn giải lại.

Đây là kiểm tra cần có từ khóa/hành động, **không phải kiểm chứng ngữ nghĩa**. Cùng mệnh đề có thể vẫn sai vai người nói, sai mục đích, không nguy hiểm hoặc là trích dẫn. Cảnh báo bị cờ không đồng nghĩa tin an toàn; vượt qua kiểm tra không đồng nghĩa lý do đúng. Bộ quy tắc được xây sau khi xem dev, không phải holdout. Cần chấm độc lập chất lượng giải thích và nhãn toàn thông điệp.

`per_request.jsonl` truy ngược trước/sau theo request và case ID. `review.csv` chỉ là phiếu mở, chưa có điểm người chấm; rubric 0 = cơ chế không được trích dẫn hỗ trợ, 1 = hỗ trợ một phần/còn suy diễn, 2 = cơ chế được hỗ trợ trực tiếp. Không dùng phiếu cơ chế này làm nhãn phishing.
""", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.study, args.out), ensure_ascii=False, indent=2))
