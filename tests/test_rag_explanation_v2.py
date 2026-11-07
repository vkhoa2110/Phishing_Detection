"""Offline parser-contract regression; no provider calls or semantic labels."""
import asyncio
from copy import deepcopy
import json

import httpx
import pytest

from app import rag_explanation as v1
from app.rag_explanation_v2 import (PARSER_VERSION, build_explanation_payload,
                                    call_explanation_v2, parse_explanation_v2)


TEXT = "Gửi OTP cho tôi. Không nhấp liên kết khi chưa xác minh."
VERDICT = {"risk_level": "HIGH", "context_kind": "scam_request", "summary": "Có yêu cầu gửi OTP.",
           "evidence": [{"quote": "Gửi OTP", "reason": "Yêu cầu bí mật."}], "recommended_actions": []}
SOURCES = [{"document_id": "VN-RAG-001", "text": "Không gửi OTP cho người khác. Không nhấp liên kết khi chưa xác minh.",
            "title": "Fixture", "source_url": "https://example.org"}]


def output():
    first = {"document_id": "VN-RAG-001", "source_quote": "Không gửi OTP cho người khác.",
             "input_quote": "Gửi OTP", "claim": "Không gửi OTP cho người liên hệ.",
             "relation": "mechanism_match", "scope_note": "Không xác minh người gửi cụ thể."}
    second = {**first, "source_quote": "Không nhấp liên kết khi chưa xác minh.",
              "input_quote": "Không nhấp liên kết", "claim": "Nguồn cung cấp bước xác minh.",
              "relation": "verification_step"}
    return {"support": [first, second], "actions": [{"text": "Xác minh qua kênh đã biết.",
                                                    "supporting_document_ids": ["VN-RAG-001"]}]}


def parse(value):
    return parse_explanation_v2(json.dumps(value, ensure_ascii=False), approved_text=TEXT,
                                verdict=VERDICT, sources=SOURCES)


def test_builder_and_prompt_schema_remain_exact_v1_payload():
    kwargs = {"approved_text": TEXT, "verdict": VERDICT, "sources": SOURCES,
              "model": "fixture", "max_tokens": 8192}
    assert build_explanation_payload is v1.build_explanation_payload
    assert json.dumps(build_explanation_payload(**kwargs)) == json.dumps(v1.build_explanation_payload(**kwargs))


def test_distinct_claims_share_source_without_changing_verdict_or_claiming_semantic_truth():
    original = deepcopy(VERDICT)
    data = output()
    assert v1.parse_explanation(json.dumps(data), approved_text=TEXT, verdict=VERDICT,
                               sources=SOURCES)["code"] == "SOURCE_NOT_GROUNDED"
    parsed = parse(data)
    assert parsed["status"] == "ok" and parsed["explanation"] == data
    assert parsed["validation"]["parser_version"] == PARSER_VERSION
    assert parsed["validation"]["semantic_support_verified"] is False
    assert VERDICT == original and "verdict" not in parsed


def test_exact_duplicate_claim_is_rejected_even_with_valid_quotes():
    data = output()
    data["support"][1] = deepcopy(data["support"][0])
    assert parse(data)["code"] == "DUPLICATE_CLAIM"


@pytest.mark.parametrize("field,value,code", [
    ("source_quote", "Trích đoạn không nằm trong tài liệu.", "SOURCE_NOT_GROUNDED"),
    ("input_quote", "Nội dung không có trong đầu vào", "INPUT_QUOTE_NOT_GROUNDED"),
    ("document_id", "VN-RAG-999", "SOURCE_NOT_GROUNDED"),
])
def test_second_claim_still_checks_every_quote_and_allowed_document(field, value, code):
    data = output()
    data["support"][1][field] = value
    result = parse(data)
    assert result["code"] == code and result["explanation"] == {"support": [], "actions": []}


def test_actions_require_unique_used_document_ids_and_no_decision_fields():
    data = output()
    data["actions"][0]["supporting_document_ids"] = ["VN-RAG-001", "VN-RAG-001"]
    assert parse(data)["code"] == "ACTION_SOURCE_NOT_GROUNDED"
    data["actions"][0]["supporting_document_ids"] = ["VN-RAG-999"]
    assert parse(data)["code"] == "ACTION_SOURCE_NOT_GROUNDED"
    assert parse({"support": [], "actions": []})["status"] == "no_support"
    assert parse({**output(), "risk_level": "LOW"})["code"] == "OUTPUT_INVALID"


def call(*, finish="stop", status=200, capture_raw=False, raw=None):
    raw = json.dumps(output(), ensure_ascii=False) if raw is None else raw
    async def execute():
        transport = httpx.MockTransport(lambda _: httpx.Response(status, json={
            "model": "fixture", "choices": [{"finish_reason": finish, "message": {"content": raw}}],
            "usage": {"total_tokens": 123}}))
        async with httpx.AsyncClient(transport=transport) as client:
            payload = build_explanation_payload(approved_text=TEXT, verdict=VERDICT, sources=SOURCES, model="fixture")
            return await call_explanation_v2(client, endpoint="https://provider.example/chat/completions",
                api_key="fixture-do-not-expose", payload=payload, approved_text=TEXT,
                verdict=VERDICT, sources=SOURCES, timeout=1, capture_raw=capture_raw)
    return asyncio.run(execute())


def test_transport_corrects_only_parser_bug_and_raw_capture_remains_opt_in():
    parsed = call()
    assert parsed["status"] == "ok" and "code" not in parsed and "raw_content" not in parsed
    assert parsed["usage"]["total_tokens"] == 123 and parsed["validation"]["parser_applied"] is True
    captured = call(capture_raw=True)
    assert captured["raw_content"] == json.dumps(output(), ensure_ascii=False)
    assert "fixture-do-not-expose" not in json.dumps(captured)


@pytest.mark.parametrize("kwargs,code", [
    ({"finish": "length"}, "OUTPUT_TRUNCATED"),
    ({"status": 429}, "HTTP_429"),
    ({"raw": "invalid json"}, "OUTPUT_INVALID"),
])
def test_transport_preserves_http_truncation_and_schema_errors(kwargs, code):
    result = call(**kwargs)
    assert result["status"] == "error" and result["code"] == code
    assert result["validation"]["parser_applied"] is False and "raw_content" not in result
