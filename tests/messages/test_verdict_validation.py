"""Offline v3 contracts; fixture outputs are not a detection benchmark."""
import asyncio
from dataclasses import replace
import json

import httpx
import pytest

from app.services.llm.client import LLMFailure, LLMService, MESSAGE_PROMPT_VERSION, MESSAGE_RAG_PROMPT_VERSION, MESSAGE_V3_PROMPT_VERSION, MESSAGE_V3_RAG_PROMPT_VERSION, SOURCE_SCOPE_FIELDS, parse_verdict
from app.domain.schemas import MessageRAGVerdict, MessageVerdict
from app.core.settings import Settings
from app.domain.validation import FALLBACK_ACTIONS, VALIDATION_VERSION, validate_message_verdict


def verdict(**overrides):
    return {
        "context_kind": "scam_request",
        "risk_level": "HIGH",
        "summary": "Có yêu cầu gửi mã xác thực.",
        "evidence": [{"quote": "gửi mã OTP", "reason": "Yêu cầu gửi mã cho người liên hệ."}],
        "recommended_actions": ["Xác minh qua kênh đã biết."],
        **overrides,
    }


def source():
    return {
        "document_id": "VN-RAG-001", "text": "Không gửi mã OTP cho người tự nhận là nhân viên hỗ trợ.",
        "title": "Tài liệu minh họa", "context_note": "Tóm lược nguồn", "publisher": "Fixture",
        "published_at": None, "kind": "scam_warning", "scenario": "otp", "entity": "unknown",
        "document_role": "warning", "scope": None, "valid_from": None, "temporal_note": "unknown",
        "score": 0.95, "source_url": "https://example.org/guidance", "untrusted_extra": "must-not-send",
    }


def support():
    return [{"document_id": "VN-RAG-001", "source_quote": source()["text"],
             "claim": "Không gửi mã OTP cho người liên hệ."}]


def checked(payload, text="Hãy gửi mã OTP", sources=None):
    model = MessageRAGVerdict if sources is not None else MessageVerdict
    return validate_message_verdict(model.model_validate(payload), text, sources,
                                    context_explicit="context_kind" in payload)


@pytest.mark.parametrize("quote,reason,text,code", [
    (" \t", "Lý do", "Xin chào bạn", "EVIDENCE_BLANK"),
    ("gửi mã OTP", " \n", "Hãy gửi mã OTP", "EVIDENCE_BLANK"),
    ("đoạn không có", "Lý do", "Xin chào", "EVIDENCE_NOT_IN_INPUT"),
    ("[SECRET]", "Lý do", "Mã [SECRET]", "EVIDENCE_NO_BEHAVIOR_TEXT"),
    ("[PHONE] [EMAIL]", "Lý do", "Liên hệ [PHONE] [EMAIL]", "EVIDENCE_NO_BEHAVIOR_TEXT"),
    ("https://example.org", "Lý do", "Tham khảo https://example.org", "EVIDENCE_NO_BEHAVIOR_TEXT"),
    ("?!", "Lý do", "Xin chào?!", "EVIDENCE_NO_BEHAVIOR_TEXT"),
])
def test_unsupported_alarm_abstains_and_discards_model_actions_and_citations(quote, reason, text, code):
    result, warnings, validation = checked(verdict(
        evidence=[{"quote": quote, "reason": reason}],
        recommended_actions=["Nhập OTP vào đường dẫn."], knowledge_support=support()), text, [source()])
    assert result.risk_level == "UNKNOWN" and result.evidence == []
    assert result.knowledge_support == []
    assert result.recommended_actions == list(FALLBACK_ACTIONS)
    assert code in validation["reason_codes"]
    assert validation["status"] == "abstained" and warnings
    assert validation["original_risk_level"] == "HIGH"
    assert validation["structural_only"] and not validation["semantic_support_verified"]


@pytest.mark.parametrize("level", ["HIGH", "WARNING", "LOW"])
def test_explicitly_insufficient_context_cannot_have_a_classification(level):
    result, _, metadata = checked(verdict(context_kind="insufficient", risk_level=level))
    assert result.risk_level == "UNKNOWN"
    assert "CONTEXT_INSUFFICIENT" in metadata["reason_codes"]


def test_missing_or_unclassified_context_abstains_but_frozen_v2_keeps_its_contract():
    for missing in (True, False):
        payload = verdict(context_kind="unclassified")
        if missing:
            payload.pop("context_kind")
        result, _, metadata = checked(payload)
        assert result.risk_level == "UNKNOWN"
        assert ("CONTEXT_MISSING" if missing else "CONTEXT_UNCLASSIFIED") in metadata["reason_codes"]
        old, _ = parse_verdict(json.dumps(payload), "Hãy gửi mã OTP", prompt_profile="message-v2")
        assert old.risk_level == "HIGH"


@pytest.mark.parametrize("text", ["https://example.org", "(https://example.org).", "example.org https://example.net [SECRET]"])
def test_bare_url_input_cannot_become_low_message_assessment(text):
    result, _, metadata = checked(verdict(context_kind="routine", risk_level="LOW", evidence=[]), text)
    assert result.risk_level == "UNKNOWN" and result.context_kind == "insufficient"
    assert "URL_ONLY_INPUT" in metadata["reason_codes"]


def test_blank_summary_abstains_and_clears_unsupported_source_claims():
    result, _, metadata = checked(verdict(summary=" \n\t ", knowledge_support=support()), sources=[source()])
    assert result.risk_level == "UNKNOWN" and result.summary.strip()
    assert result.knowledge_support == [] and "SUMMARY_BLANK" in metadata["reason_codes"]


@pytest.mark.parametrize("field,value,code", [
    ("claim", " \n", "SOURCE_SUPPORT_BLANK"),
    ("source_quote", " " * 12, "SOURCE_SUPPORT_BLANK"),
    ("source_quote", "Một đoạn hoàn toàn khác nguồn đã cung cấp.", "SOURCE_SUPPORT_NOT_FOUND"),
    ("document_id", "VN-RAG-999", "SOURCE_SUPPORT_NOT_FOUND"),
])
def test_invalid_citation_is_removed_without_clearing_valid_input_alarm(field, value, code):
    claims = support(); claims[0][field] = value
    result, _, metadata = checked(verdict(knowledge_support=claims), sources=[source()])
    assert result.risk_level == "HIGH" and result.knowledge_support == []
    assert metadata["status"] == "filtered" and code in metadata["reason_codes"]


def test_valid_action_evidence_is_kept_even_if_context_claims_quoted_example():
    payload = verdict(context_kind="quoted_example", knowledge_support=support())
    result, _, metadata = checked(payload, sources=[source()])
    assert result.risk_level == "HIGH" and result.knowledge_support
    assert metadata["status"] == "valid" and not metadata["semantic_support_verified"]


def test_trims_nonblank_fields_and_has_no_arbitrary_minimum_quote_word_count():
    payload = verdict(summary=" Mô tả ", evidence=[{"quote": " Mã ", "reason": " Lý do "}],
                      recommended_actions=[" Xác minh qua kênh đã biết. "])
    result, _, metadata = checked(payload, "Mã đã được yêu cầu.")
    assert result.evidence[0].quote == "Mã" and result.evidence[0].reason == "Lý do"
    assert result.summary == "Mô tả" and metadata["status"] == "valid"
    assert result.recommended_actions == ["Xác minh qua kênh đã biết."]


def test_supported_low_and_explicit_unknown_are_not_forced_to_alarm():
    for risk, context in [("LOW", "routine"), ("UNKNOWN", "insufficient")]:
        result, _, metadata = checked(verdict(risk_level=risk, context_kind=context, evidence=[]), "Họp nhóm lúc 9 giờ.")
        assert result.risk_level == risk
        assert metadata["status"] == ("abstained" if risk == "UNKNOWN" else "valid")


@pytest.mark.parametrize("context,code", [("insufficient", "CONTEXT_INSUFFICIENT"),
                                         ("routine", "MODEL_ABSTAINED"), ("scam_request", "MODEL_ABSTAINED")])
def test_voluntary_unknown_also_clears_unverified_actions_and_source_claims(context, code):
    payload = verdict(context_kind=context, risk_level="UNKNOWN", knowledge_support=support(),
                      recommended_actions=["Nhập OTP vào đường dẫn."])
    result, _, metadata = checked(payload, sources=[source()])
    assert result.risk_level == "UNKNOWN" and result.knowledge_support == []
    assert result.recommended_actions == list(FALLBACK_ACTIONS)
    assert metadata["status"] == "abstained" and code in metadata["reason_codes"]
    assert metadata["original_risk_level"] == "UNKNOWN"
    old, _ = parse_verdict(json.dumps(payload), "Hãy gửi mã OTP", [source()], prompt_profile="message-v2")
    assert old.recommended_actions == ["Nhập OTP vào đường dẫn."] and old.knowledge_support


def test_public_parse_tuple_and_frozen_legacy_whitespace_behavior():
    payload = verdict(evidence=[{"quote": " ", "reason": " "}])
    current, warnings = parse_verdict(json.dumps(payload), "Chào bạn", prompt_profile="message-v3")
    assert current.risk_level == "UNKNOWN" and warnings
    old, warnings = parse_verdict(json.dumps(payload), "Chào bạn", prompt_profile="message-v2")
    assert old.risk_level == "HIGH" and not warnings
    payload.pop("context_kind")
    old, warnings = parse_verdict(json.dumps(payload), "Chào bạn")
    assert old.risk_level == "HIGH" and not warnings


@pytest.mark.parametrize("profile,use_rag", [("message-v2", False), ("message-v2", True),
                                             ("message-v3", False), ("message-v3", True)])
def test_service_versions_and_scope_metadata_are_isolated_to_v3(profile, use_rag):
    captured = []
    payload = verdict(**({"knowledge_support": support()} if use_rag else {}))
    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(payload)}}]})

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await LLMService(replace(Settings(), api_key="test-fixture"), client).analyze(
                text="Hãy gửi mã OTP", mode="text", urls=[], include_ml=False,
                endpoint="", model="", api_key="", rag_sources=[source()] if use_rag else [], prompt_profile=profile)

    result = asyncio.run(exercise())
    expected_version = {(False, False): MESSAGE_PROMPT_VERSION, (False, True): MESSAGE_RAG_PROMPT_VERSION,
                        (True, False): MESSAGE_V3_PROMPT_VERSION, (True, True): MESSAGE_V3_RAG_PROMPT_VERSION}
    assert result["prompt_version"] == expected_version[(profile == "message-v3", use_rag)]
    assert result["assessment_scope"] == "message"
    if profile == "message-v3":
        assert result["validation"]["version"] == VALIDATION_VERSION
        assert result["validation"]["status"] == "valid"
    else:
        assert "validation" not in result
    if use_rag:
        document = json.loads(captured[0]["messages"][1]["content"])["reference_documents"][0]
        assert "score" not in document and "untrusted_extra" not in document and "source_url" not in document
        if profile == "message-v3":
            assert {field: document[field] for field in SOURCE_SCOPE_FIELDS} == {field: source()[field] for field in SOURCE_SCOPE_FIELDS}
            assert document["scope"] is None and document["entity"] == "unknown"
        else:
            assert not (set(SOURCE_SCOPE_FIELDS) & set(document))


def test_v3_still_rejects_schema_invalid_outputs_instead_of_guessing_fields():
    payload = verdict(); payload["evidence"][0]["reason"] = ""
    with pytest.raises(LLMFailure) as failure:
        parse_verdict(json.dumps(payload), "Hãy gửi mã OTP", prompt_profile="message-v3")
    assert failure.value.code == "OUTPUT_INVALID"
