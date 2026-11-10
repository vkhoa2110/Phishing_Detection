"""Prepare a blinded, authored development pack for interaction analysis.

The command is offline. It locks provider payloads and a private design map but
does not call an LLM or promote the authored references to independent gold.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from app.message_policy_v6 import payload_for
from app.message_policy_v5 import payload_for as payload_for_v5
from app.settings import Settings


CASES = [
    {
        "id": "CV-01", "risk": "HIGH", "stage": "payment_or_secret_request",
        "text": "Nhà tuyển dụng: Em làm thử nhiệm vụ này, chị trả 50 nghìn.\nỨng viên: Em nhận được rồi.\nNhà tuyển dụng: Nạp 2 triệu vào tài khoản chị gửi để mở khóa nhiệm vụ tiếp theo.",
        "requester": "Nhà tuyển dụng", "recipient": "Ứng viên",
        "action": "nạp 2 triệu", "asset": "tiền", "beneficiary": "tài khoản do nhà tuyển dụng chỉ định",
    },
    {
        "id": "CV-02", "risk": "LOW", "stage": "trust_building",
        "text": "Nhà tuyển dụng: Mời bạn phỏng vấn tại văn phòng lúc 9 giờ.\nỨng viên: Tôi xác nhận tham gia.\nNhà tuyển dụng: Bạn mang CCCD để lễ tân đối chiếu, không gửi ảnh hay mã xác thực qua chat.",
        "requester": "Nhà tuyển dụng", "recipient": "Ứng viên",
        "action": "mang CCCD để lễ tân đối chiếu", "asset": "giấy tờ định danh", "beneficiary": None,
    },
    {
        "id": "CV-03", "risk": "HIGH", "stage": "payment_or_secret_request",
        "text": "Người gọi: Tài khoản của anh có giao dịch lạ.\nKhách hàng: Tôi phải làm gì?\nNgười gọi: Đọc mã OTP vừa nhận để tôi hủy giao dịch ngay.",
        "requester": "Người gọi", "recipient": "Khách hàng",
        "action": "đọc mã OTP", "asset": "mã xác thực", "beneficiary": "người gọi",
    },
    {
        "id": "CV-04", "risk": "LOW", "stage": "unknown",
        "text": "Khách hàng: Tôi vừa tự yêu cầu đặt lại mật khẩu trong ứng dụng.\nHỗ trợ: Hãy nhập mã trên chính màn hình ứng dụng. Không đọc mã cho nhân viên.\nKhách hàng: Tôi đã hoàn tất.",
        "requester": "Hỗ trợ", "recipient": "Khách hàng",
        "action": "tự nhập mã trong ứng dụng", "asset": "mã xác thực", "beneficiary": None,
    },
    {
        "id": "CV-05", "risk": "HIGH", "stage": "recovery",
        "text": "Nạn nhân: Tôi đã mất tiền vì sàn đầu tư.\nNgười hỗ trợ: Tôi lấy lại được tiền nếu chị giữ bí mật.\nNgười hỗ trợ: Chuyển trước 5 triệu phí pháp lý vào tài khoản cá nhân để nhận tiền hoàn.",
        "requester": "Người hỗ trợ", "recipient": "Nạn nhân",
        "action": "chuyển trước 5 triệu phí pháp lý", "asset": "tiền", "beneficiary": "tài khoản cá nhân",
    },
    {
        "id": "CV-06", "risk": "LOW", "stage": "single_message",
        "text": "Người bán: Đơn của bạn đã sẵn sàng.\nNgười mua: Tôi thanh toán thế nào?\nNgười bán: Thanh toán trong ứng dụng nơi bạn đã đặt đơn; nếu ứng dụng không hiện đơn thì đừng chuyển khoản.",
        "requester": "Người bán", "recipient": "Người mua",
        "action": "thanh toán trong ứng dụng đã đặt đơn", "asset": "tiền", "beneficiary": "đơn hàng trong ứng dụng",
    },
]


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def prepare_paired(out: Path, *, model: str | None = None, max_tokens: int = 2048) -> dict:
    """Paired history/prefix/profile contrasts; per-prefix labels stay blank.

    A final HIGH label is deliberately not copied to earlier prefixes or to an
    isolated last turn. Reviewers must judge only the text the model sees.
    """
    if out.exists():
        raise ValueError("Choose a new output directory; conversation packs are immutable.")
    model = model or Settings().llm_model
    rows, private = [], []
    for case in CASES:
        lines = case["text"].splitlines()
        for prefix in range(1, len(lines) + 1):
            for history in ("full_history", "last_turn_only"):
                text = "\n".join(lines[:prefix]) if history == "full_history" else lines[prefix - 1]
                for profile, builder in (("message-v5", payload_for_v5), ("message-v6", payload_for)):
                    built = builder(text=text, urls=[], include_ml=False, sources=[],
                                    model=model, max_tokens=max_tokens)
                    key = f"{case['id']}::p{prefix}::{history}::{profile}"
                    row = {"key": key, "text": text, "payload": built[0]}
                    row["request_sha256"] = digest(json.dumps(row, sort_keys=True, ensure_ascii=False))
                    rows.append(row)
                    private.append({"key": key, "blind_id": "CVP-" + digest(key)[:12],
                                    "case_id": case["id"], "prefix": prefix,
                                    "history": history, "profile": profile,
                                    "risk_reference": None, "reference_status": "requires_independent_review"})
    out.mkdir(parents=True)
    for filename, values in (("requests.jsonl", rows), ("private_design_map.jsonl", private)):
        (out / filename).write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in values))
    # One review item for each distinct displayed input. Pair identity/profile
    # and future turns never appear in the sheet shown to the reviewer.
    review_inputs = {digest(row["text"]): row["text"] for row in rows}
    with (out / "input_review.csv").open("w", newline="") as stream:
        fields = ["blind_input_id", "input_text", "risk_reference", "actionable_evidence_quote",
                  "reviewer_id", "notes"]
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader()
        for key, text in sorted(review_inputs.items()):
            writer.writerow({**dict.fromkeys(fields, ""), "blind_input_id": "CVI-" + key[:12], "input_text": text})
    root = Path(__file__).resolve().parents[1]
    protocol = {"schema": "conversation-prefix-paired-1.0", "created_at": datetime.now(timezone.utc).isoformat(),
        "threads": len(CASES), "requests": len(rows), "unique_inputs": len(review_inputs), "provider_calls": 0,
        "model": model, "max_tokens": max_tokens, "profiles": ["message-v5", "message-v6"],
        "history_conditions": ["full_history", "last_turn_only"], "prefixes": [1, 2, 3],
        "requests_sha256": hashlib.sha256((out / "requests.jsonl").read_bytes()).hexdigest(),
        "private_map_sha256": hashlib.sha256((out / "private_design_map.jsonl").read_bytes()).hexdigest(),
        "source_files_sha256": {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in (
            "app/message_policy_v5.py", "app/message_policy_v6.py", "evaluation/conversation_structure_v1.py")},
        "semantic_labels": "blank; final-thread labels are not prefix gold",
        "matched_output_function": False,
        "limitations": "Six authored development threads; v6 emits additional interaction fields. "
            "Same max token cap is not equal reasoning or output work. No accuracy or early-warning result yet."}
    (out / "protocol.json").write_text(json.dumps(protocol, ensure_ascii=False, indent=2) + "\n")
    return protocol


def prepare(out: Path) -> dict:
    if out.exists():
        raise ValueError("Choose a new output directory; conversation packs are immutable.")
    out.mkdir(parents=True)
    public, private = [], []
    for case in CASES:
        payload, included_ml, turns = payload_for(
            text=case["text"], urls=[], include_ml=False, sources=[],
            model="MODEL_TO_BE_FILLED", max_tokens=2048,
        )
        if included_ml or turns != 3:
            raise ValueError("Conversation fixture no longer matches its contract: " + case["id"])
        public.append({"key": case["id"], "text": case["text"], "payload": payload})
        private.append({key: case[key] for key in (
            "id", "risk", "stage", "requester", "recipient", "action", "asset", "beneficiary"
        )})
    requests = out / "requests.jsonl"
    requests.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in public))
    (out / "private_design_map.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in private)
    )
    fields = ["blind_id", "output_status", "risk_correct_0_1", "requester_correct_0_1",
              "recipient_correct_0_1", "requested_action_correct_0_2",
              "asset_and_beneficiary_correct_0_2", "stage_correct_0_1",
              "unsupported_inference_0_1", "reviewer_id", "notes"]
    with (out / "blind_review.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader()
        for case in sorted(CASES, key=lambda item: digest(item["id"])):
            writer.writerow({"blind_id": "CVB-" + digest(case["id"])[:12], **{field: "" for field in fields[1:]}})
    protocol = {
        "schema": "conversation-structure-v1-1.0", "created_at": datetime.now(timezone.utc).isoformat(),
        "cases": len(CASES), "provider_calls": 0, "turns_per_case": 3,
        "risk_distribution": {risk: sum(case["risk"] == risk for case in CASES) for risk in ("HIGH", "LOW")},
        "requests_sha256": hashlib.sha256(requests.read_bytes()).hexdigest(),
        "review_status": "blank human review sheet",
        "limitations": "Authored development contrasts; design references are not independent human gold.",
    }
    (out / "protocol.json").write_text(json.dumps(protocol, ensure_ascii=False, indent=2) + "\n")
    return protocol


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["prepare", "prepare-paired"])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model")
    parser.add_argument("--max-tokens", type=int, default=2048)
    args = parser.parse_args()
    result = (prepare_paired(args.out, model=args.model, max_tokens=args.max_tokens)
              if args.command == "prepare-paired" else prepare(args.out))
    print(json.dumps(result, ensure_ascii=False, indent=2))
