import asyncio
import json

import httpx
import pytest

from app.services.llm.client import LLMFailure
from app.services.llm.policy_v6 import parse_v6
from app.services.llm.compact import call_v61, parse_v61, payload_for, visible_input


def verdict(**changes):
    return {"context_kind": "routine", "risk_level": "LOW", "summary": "Thông báo trạng thái đơn hàng.",
            "evidence": [], "recommended_actions": [],
            "interaction": {"requested_action": "unknown", "stage": "single_message",
                            "conversation_turns_used": 1}, **changes}


@pytest.mark.parametrize("text", [
    "Người bán: Đơn của bạn đã sẵn sàng.",
    "[Người bán] Đơn của bạn đã sẵn sàng.",
    "Đơn của bạn đã sẵn sàng.",
    "Xin chào.\nTôi cần xác minh giao dịch ngân hàng.",
])
def test_one_visible_message_has_a_limit_of_one_without_fabricating_roles(text):
    parsed, _, validation = parse_v61(json.dumps(verdict(), ensure_ascii=False), text)
    assert parsed.risk_level == "LOW" and validation["visible_turn_limit"] == 1
    assert validation["compact_output_enforced"] is True
    if text.startswith(("Đơn", "Xin")):
        assert visible_input(text)["turns"] == []
    else:
        assert len(visible_input(text)["turns"]) == 1


def test_old_parser_remains_frozen_and_new_parser_rejects_invented_extra_turns():
    text = "Người bán: Đơn đã sẵn sàng."
    answer = verdict()
    with pytest.raises(LLMFailure, match="vượt đầu vào"):
        parse_v6(json.dumps(answer), text)
    answer["interaction"]["conversation_turns_used"] = 2
    with pytest.raises(LLMFailure, match="vượt phần nội dung"):
        parse_v61(json.dumps(answer), text)


@pytest.mark.parametrize("change", [
    {"summary": "x" * 241},
    {"recommended_actions": ["Bước một.", "Bước hai.", "Bước ba."]},
    {"recommended_actions": ["x" * 181]},
    {"evidence": [{"quote": "x", "reason": "x"}] * 3},
])
def test_compact_contract_rejects_long_output_instead_of_trimming_it(change):
    with pytest.raises(LLMFailure, match="JSON"):
        parse_v61(json.dumps(verdict(**change)), "Đơn đã sẵn sàng.")


def test_missing_behavior_evidence_still_abstains_and_unknown_fields_are_rejected():
    parsed, _, validation = parse_v61(json.dumps(verdict(risk_level="HIGH", context_kind="scam_request")),
                                     "Người gọi: Xin chào.")
    assert parsed.risk_level == "UNKNOWN"
    assert "ALARM_WITHOUT_BEHAVIOR_EVIDENCE" in validation["reason_codes"]
    with pytest.raises(LLMFailure):
        parse_v61(json.dumps(verdict(extra_field="not allowed")), "Xin chào.")
    with pytest.raises(LLMFailure):
        parse_v61('{"risk_level":"LOW","risk_level":"HIGH"}', "Xin chào.")


def test_payload_publishes_matching_turn_limit_and_schema_without_rag():
    text = "Hỗ trợ: Tự mở ứng dụng.\nKhông gửi OTP.\nKhách hàng: Tôi hiểu."
    payload, included, count = payload_for(text=text, urls=[], include_ml=False, sources=[],
                                            model="fixture", max_tokens=2048)
    data = json.loads(payload["messages"][1]["content"])
    assert count == data["input_structure"]["visible_turn_limit"] == 2
    assert len(data["conversation_turns"]) == 2 and included is False
    assert data["output_schema"]["properties"]["summary"]["maxLength"] == 240
    assert data["output_schema"]["properties"]["recommended_actions"]["maxItems"] == 2
    assert "Không gửi OTP." in data["conversation_turns"][0]["text"]
    with pytest.raises(ValueError, match="before RAG"):
        payload_for(text=text, urls=[], include_ml=False, sources=[{}], model="fixture", max_tokens=2048)


@pytest.mark.parametrize("finish,expected", [("stop", "ok"), ("length", "error"), ("content_filter", "error")])
def test_one_attempt_transport_corrects_turn_validation_but_never_accepts_truncation(finish, expected):
    calls = []
    text = "Người bán: Đơn đã sẵn sàng."

    def provider(request):
        calls.append(request)
        return httpx.Response(200, json={"model": "fixture", "usage": {"total_tokens": 123}, "choices": [{
            "finish_reason": finish, "message": {"content": json.dumps(verdict())}}]})

    async def execute():
        payload, _, _ = payload_for(text=text, urls=[], include_ml=False, sources=[], model="fixture", max_tokens=2048)
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            return await call_v61(client, endpoint="https://example.org/chat", api_key="unit-only-key", payload=payload,
                                  text=text, timeout=1)
    result = asyncio.run(execute())
    assert result["status"] == expected and len(calls) == 1
    assert result["usage"]["total_tokens"] == 123
    if finish == "length":
        assert result["code"] == "OUTPUT_TRUNCATED" and "verdict" not in result
