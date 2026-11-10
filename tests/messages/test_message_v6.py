import json

import pytest

from app.services.llm.client import LLMFailure
from app.services.llm.policy_v6 import conversation_turns, parse_v6, payload_for


def output(**interaction):
    return json.dumps({
        "context_kind": "scam_request", "risk_level": "HIGH",
        "summary": "Yêu cầu chuyển tiền để tiếp tục.",
        "evidence": [{"quote": "nạp thêm 2 triệu", "reason": "Yêu cầu trả tiền trước."}],
        "recommended_actions": ["Dừng chuyển tiền và xác minh."],
        "interaction": {
            "requester": "Nhà tuyển dụng", "recipient": "Ứng viên",
            "requested_action": "nạp thêm 2 triệu", "asset_or_access": "tiền",
            "beneficiary": "tài khoản do bên tuyển dụng chỉ định",
            "stage": "payment_or_secret_request", "persuasion": ["reward"],
            "conversation_turns_used": 2, **interaction,
        },
    }, ensure_ascii=False)


TEXT = "Nhà tuyển dụng: Bạn đã nhận 50 nghìn thử việc.\nỨng viên: Tôi nhận rồi.\nNhà tuyển dụng: Hãy nạp thêm 2 triệu để mở khóa nhiệm vụ."


def test_v6_parses_turns_and_structured_interaction():
    turns = conversation_turns(TEXT)
    assert [turn["speaker"] for turn in turns] == ["Nhà tuyển dụng", "Ứng viên", "Nhà tuyển dụng"]
    verdict, _, validation = parse_v6(output(conversation_turns_used=3), TEXT)
    assert verdict.interaction.stage == "payment_or_secret_request"
    assert verdict.risk_level == "HIGH"
    assert validation["parsed_turns"] == 3
    assert validation["interaction_semantics_verified"] is False


def test_v6_rejects_unknown_persuasion_and_fabricated_turn_count():
    with pytest.raises(LLMFailure, match="cấu trúc"):
        parse_v6(output(persuasion=["magic"]), TEXT)
    with pytest.raises(LLMFailure, match="vượt đầu vào"):
        parse_v6(output(conversation_turns_used=99), TEXT)
    with pytest.raises(LLMFailure, match="cấu trúc"):
        parse_v6(output(conversation_turns_used="3"), TEXT)


def test_v6_payload_marks_speaker_lines_as_untrusted_data():
    payload, included_ml, turns = payload_for(text=TEXT, urls=[], include_ml=False, sources=[],
                                               model="fixture", max_tokens=2048)
    user = json.loads(payload["messages"][1]["content"])
    assert turns == 3 and len(user["conversation_turns"]) == 3
    assert "untrusted" in user["conversation_note"]
    assert "interaction" in payload["messages"][0]["content"]
    assert included_ml is False


@pytest.mark.parametrize("text", [
    "Xin chào.\nTôi cần xác minh giao dịch ngân hàng.",
    "https://example.org\nhttps://example.net",
    "09:30 gặp nhau\n10:30 kết thúc",
    '“Người gọi: Đọc OTP.”\n“Khách hàng: Không.”',
])
def test_prose_timestamps_links_and_quoted_dialogue_do_not_invent_speakers(text):
    assert conversation_turns(text) == []


def test_bracketed_labels_and_multiline_continuation_keep_all_content():
    turns = conversation_turns("[Hỗ trợ] Tự mở ứng dụng.\nKhông đọc OTP cho ai.\n[Khách hàng]: Tôi hiểu.")
    assert turns == [
        {"index": 1, "speaker": "Hỗ trợ", "text": "Tự mở ứng dụng.\nKhông đọc OTP cho ai."},
        {"index": 2, "speaker": "Khách hàng", "text": "Tôi hiểu."},
    ]
