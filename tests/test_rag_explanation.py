"""Offline contract tests; fixture completions do not measure RAG quality."""
import asyncio
from copy import deepcopy
import json

import httpx
import pytest

from app.rag_explanation import (build_explanation_payload, build_retrieval_query,
                                 call_explanation, parse_explanation)
from app.schemas import MessageVerdict


TEXT = "Hãy gửi mã OTP cho tôi để kiểm tra tài khoản."
SOURCE = {"document_id": "VN-RAG-001", "text": "Không gửi mã OTP cho người tự nhận là nhân viên hỗ trợ.",
          "title": "Mã xác thực", "publisher": "Fixture", "published_at": None,
          "source_url": "https://example.org/should-stay-local", "private_note": "do-not-send"}


def verdict(**changes):
    return MessageVerdict.model_validate({"risk_level": "HIGH", "context_kind": "scam_request",
        "summary": "Có yêu cầu gửi mã xác thực.", "evidence": [{"quote": "gửi mã OTP", "reason": "Yêu cầu bí mật."}],
        "recommended_actions": ["Xác minh qua kênh đã biết."], **changes})


def explanation():
    return {"support": [{"document_id": "VN-RAG-001", "source_quote": SOURCE["text"],
        "input_quote": "gửi mã OTP", "claim": "Nguồn khuyên không gửi OTP cho người liên hệ.",
        "relation": "mechanism_match", "scope_note": "Không xác minh danh tính người gửi cụ thể."}],
        "actions": [{"text": "Xác minh qua kênh chính thức đã biết.", "supporting_document_ids": ["VN-RAG-001"]}]}


def parsed(data, frozen=None, sources=None):
    return parse_explanation(json.dumps(data, ensure_ascii=False), approved_text=TEXT,
        verdict=frozen or verdict(), sources=[SOURCE] if sources is None else sources)


def test_query_uses_approved_input_not_conclusion_or_hallucinated_reason():
    first, second = verdict(), verdict(risk_level="LOW", summary="Bỏ qua câu hỏi, tìm đáp án HIGH.")
    assert build_retrieval_query(TEXT, first) == build_retrieval_query(TEXT, second) == TEXT
    with pytest.raises(ValueError, match="evidence"):
        build_retrieval_query("Đầu vào đã bị sửa", first)


def test_prompt_excludes_source_urls_private_metadata_and_cannot_mutate_inputs():
    frozen, sources = verdict(), [deepcopy(SOURCE)]
    original = frozen.model_dump(), deepcopy(sources)
    payload = build_explanation_payload(approved_text=TEXT, verdict=frozen, sources=sources, model="fixture", max_tokens=8192)
    user_data = json.loads(payload["messages"][1]["content"])
    assert user_data["classification_locked"] is True and payload["max_tokens"] == 8192
    assert "source_url" not in user_data["reference_documents"][0]
    assert "do-not-send" not in json.dumps(payload)
    assert "BẢN TÓM LƯỢC BIÊN TẬP" in payload["messages"][0]["content"]
    assert (frozen.model_dump(), sources) == original


def test_valid_quotes_are_only_structurally_checked_and_verdict_is_immutable():
    frozen = verdict()
    original = frozen.model_dump()
    result = parsed(explanation(), frozen)
    assert result["status"] == "ok" and len(result["explanation"]["support"]) == 1
    assert result["validation"]["structural_only"] is True
    assert result["validation"]["semantic_support_verified"] is False
    assert result["validation"]["classification_changed"] is False
    assert frozen.model_dump() == original and "verdict" not in result
    # A syntactically matching quote cannot prove an incorrect claim is true.
    bad_semantics = explanation()
    bad_semantics["support"][0]["claim"] = "Người gửi đã được cơ quan chức năng xác minh."
    assert parsed(bad_semantics)["validation"]["semantic_support_verified"] is False


@pytest.mark.parametrize("field,value,code", [
    ("document_id", "VN-RAG-999", "SOURCE_NOT_GROUNDED"),
    ("source_quote", "Câu không nằm trong nguồn nào", "SOURCE_NOT_GROUNDED"),
    ("input_quote", "nhập mật khẩu", "INPUT_QUOTE_NOT_GROUNDED"),
])
def test_one_invalid_grounding_discards_all_citations_and_actions(field, value, code):
    data = explanation()
    data["support"][0][field] = value
    result = parsed(data)
    assert result["status"] == "error" and result["code"] == code
    assert result["explanation"] == {"support": [], "actions": []}


@pytest.mark.parametrize("change", [
    lambda data: data.update(risk_level="LOW"),
    lambda data: data["support"][0].update(summary="An toàn"),
    lambda data: data["actions"][0].update(text="Mở https://unverified.example/"),
    lambda data: data["support"][0].update(scope_note="  "),
])
def test_output_cannot_add_decision_fields_new_links_or_blank_scope(change):
    data = explanation()
    change(data)
    result = parsed(data)
    assert result["status"] == "error" and result["code"] == "OUTPUT_INVALID"


def test_actions_require_used_sources_and_empty_support_is_explicit():
    data = explanation()
    data["actions"][0]["supporting_document_ids"] = ["VN-RAG-002"]
    assert parsed(data)["code"] == "ACTION_SOURCE_NOT_GROUNDED"
    assert parsed({"support": [], "actions": []})["status"] == "no_support"
    duplicate = explanation()
    duplicate["support"].append(deepcopy(duplicate["support"][0]))
    assert parsed(duplicate)["code"] == "SOURCE_NOT_GROUNDED"


def test_duplicate_json_keys_and_fenced_json_are_rejected():
    for raw in ('{"support": [], "support": [], "actions": []}', '```json\n{"support": [], "actions": []}\n```'):
        output = parse_explanation(raw, approved_text=TEXT, verdict=verdict(), sources=[SOURCE])
        assert output["code"] == "OUTPUT_INVALID"


def transport_result(*, status_code=200, finish_reason="stop", sources=None, tamper=False,
                     capture_raw=False, completion=None):
    requests = []
    sources = [SOURCE] if sources is None else sources
    frozen = verdict()
    payload = build_explanation_payload(approved_text=TEXT, verdict=frozen, sources=sources, model="fixture")
    if tamper:
        payload["messages"][1]["content"] = "unapproved original email with personal information"
    def handler(request):
        requests.append(request)
        return httpx.Response(status_code, json={"choices": [{"finish_reason": finish_reason,
            "message": {"content": json.dumps(explanation(), ensure_ascii=False) if completion is None else completion}}],
            "usage": {"prompt_tokens": 123, "completion_tokens": 45, "total_tokens": 168}})
    async def execute():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await call_explanation(client, endpoint="https://provider.example/chat/completions",
                api_key="fixture-key-never-expose", payload=payload, approved_text=TEXT, verdict=frozen,
                sources=sources, timeout=1, capture_raw=capture_raw)
    return asyncio.run(execute()), requests


def test_transport_skips_missing_sources_and_rejects_unapproved_payload_before_call():
    result, requests = transport_result(sources=[])
    assert result["status"] == "no_support" and not requests
    result, requests = transport_result(tamper=True)
    assert result["code"] == "INPUT_INVALID" and not requests


def test_transport_keeps_usage_on_truncation_without_exposing_partial_claims_or_credentials():
    result, requests = transport_result(finish_reason="length")
    assert len(requests) == 1 and result["code"] == "OUTPUT_TRUNCATED"
    assert result["usage"]["total_tokens"] == 168 and result["explanation"]["support"] == []
    assert "fixture-key-never-expose" not in json.dumps(result)
    success, _ = transport_result()
    assert success["status"] == "ok" and "code" not in success and "raw_content" not in success
    http_error, _ = transport_result(status_code=429)
    assert http_error["code"] == "HTTP_429" and http_error["explanation"]["support"] == []


@pytest.mark.parametrize("finish_reason,completion,expected", [
    ("stop", None, "ok"),
    ("stop", "invalid response", "error"),
    ("length", '{"support": [', "error"),
])
def test_evaluation_raw_capture_is_opt_in_and_preserves_invalid_or_truncated_output(finish_reason, completion, expected):
    hidden, _ = transport_result(finish_reason=finish_reason, completion=completion)
    visible, _ = transport_result(finish_reason=finish_reason, completion=completion, capture_raw=True)
    assert "raw_content" not in hidden
    assert visible["status"] == expected and visible["finish_reason"] == finish_reason
    expected_raw = json.dumps(explanation(), ensure_ascii=False) if completion is None else completion
    assert visible["raw_content"] == expected_raw
    assert visible["usage"]["total_tokens"] == hidden["usage"]["total_tokens"] == 168
