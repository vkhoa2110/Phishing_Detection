"""Selection-only contracts and mocked one-attempt transport, no semantic labels."""
import asyncio
from copy import deepcopy
import json

import httpx
import pytest

from app.services.rag.evidence import CATALOG_VERSION, INPUT_SPAN_CHARS, PROFILE, SOURCE_SPAN_CHARS, build_evidence_payload, call_evidence, evidence_catalog, parse_evidence


TEXT = "Hãy gửi mã OTP cho tôi để kiểm tra tài khoản."
VERDICT = {"risk_level": "HIGH", "context_kind": "scam_request", "summary": "Yêu cầu mã xác thực.",
           "evidence": [{"quote": "gửi mã OTP", "reason": "Yêu cầu bí mật."}], "recommended_actions": []}
SOURCE = {"document_id": "VN-RAG-001", "text": "Không gửi mã OTP cho người tự nhận là nhân viên hỗ trợ.",
          "title": "Mã xác thực", "publisher": "Fixture", "scope": "Quy tắc chung",
          "source_url": "https://example.org/local-only", "private_note": "do-not-send"}


def output():
    return {"selections": [{"source_span_id": "VN-RAG-001:S001", "input_span_id": "M001",
                            "relation": "mechanism_match"}]}


def parsed(data, **kwargs):
    return parse_evidence(json.dumps(data, ensure_ascii=False), approved_text=TEXT,
                          verdict=VERDICT, sources=[SOURCE], **kwargs)


def test_catalog_is_deterministic_bound_to_full_content_and_preserves_metadata():
    original = deepcopy(SOURCE), deepcopy(VERDICT)
    args = dict(approved_text=TEXT, verdict=VERDICT, sources=[SOURCE])
    catalog = evidence_catalog(**args)
    assert evidence_catalog(**args) == catalog
    assert catalog["catalog_version"] == CATALOG_VERSION
    assert catalog["reference_documents"][0]["scope"] == SOURCE["scope"]
    assert "private_note" not in str(catalog) and "source_url" not in str(catalog)
    changed = deepcopy(SOURCE)
    changed["text"] += " Nguồn cập nhật."
    assert evidence_catalog(**{**args, "sources": [changed]})["catalog_sha256"] != catalog["catalog_sha256"]
    assert evidence_catalog(**{**args, "approved_text": TEXT + " "})["catalog_sha256"] != catalog["catalog_sha256"]
    assert (SOURCE, VERDICT) == original


def test_unicode_paragraph_and_long_unbroken_segments_have_exact_offsets_and_bounded_quotes():
    message = "Đây là ví dụ TP. Hồ Chí Minh. " * 40 + "\n\n" + "ơ" * 301
    source = {**SOURCE, "text": "Tài liệu TS. Nguyễn Văn A. " * 100 + "\n" + "ự" * 501}
    verdict = {**VERDICT, "evidence": []}
    catalog = evidence_catalog(approved_text=message, verdict=verdict, sources=[source])
    for text, spans, limit in [(message, catalog["input_spans"], INPUT_SPAN_CHARS),
                               (source["text"], catalog["reference_documents"][0]["spans"], SOURCE_SPAN_CHARS)]:
        assert len(spans) > 1
        assert len({span["id"] for span in spans}) == len(spans)
        for span in spans:
            assert text[span["start"]:span["end"]] == span["text"]
            assert 0 < len(span["text"]) <= limit
        assert "".join(text.split()) == "".join("".join(span["text"].split()) for span in spans)


def test_rendered_support_copies_quotes_without_model_claims_actions_or_verdict_mutation():
    original = deepcopy(VERDICT)
    result = parsed(output())
    support = result["explanation"]["support"][0]
    assert result["status"] == "ok" and result["prompt_profile"] == PROFILE
    assert support["source_quote"] == SOURCE["text"] and support["input_quote"] == TEXT
    assert support["source_metadata"]["scope"] == SOURCE["scope"]
    assert result["explanation"]["actions"] == []
    assert result["validation"]["semantic_support_verified"] is False
    assert result["validation"]["classification_changed"] is False
    assert result["validation"]["claims_generated_by_model"] is False
    assert VERDICT == original and "verdict" not in result


@pytest.mark.parametrize("change,code", [
    ({"source_span_id": "VN-RAG-999:S001"}, "SPAN_NOT_ALLOWED"),
    ({"source_span_id": "VN-RAG-001:S999"}, "SPAN_NOT_ALLOWED"),
    ({"input_span_id": "M999"}, "SPAN_NOT_ALLOWED"),
    ({"source_span_id": "VN-RAG-001:S" + "1" * 100}, "OUTPUT_INVALID"),
    ({"input_span_id": "M0001"}, "OUTPUT_INVALID"),
    ({"relation": "classification_override"}, "OUTPUT_INVALID"),
    ({"source_span_id": 1}, "OUTPUT_INVALID"),
    ({"claim": "Đây chắc chắn là website lừa đảo"}, "OUTPUT_INVALID"),
])
def test_unknown_or_malformed_ids_and_generated_claims_are_rejected(change, code):
    data = output()
    data["selections"][0].update(change)
    result = parsed(data)
    assert result["code"] == code and result["explanation"] == {"support": [], "actions": []}


def test_duplicate_selection_extra_verdict_fields_and_excess_selections_fail_closed():
    data = output()
    data["selections"] *= 2
    assert parsed(data)["code"] == "DUPLICATE_SELECTION"
    data["selections"] *= 2
    assert parsed(data)["code"] == "OUTPUT_INVALID"
    assert parsed({**output(), "risk_level": "LOW"})["code"] == "OUTPUT_INVALID"
    assert parsed({**output(), "actions": []})["code"] == "OUTPUT_INVALID"
    assert parsed({"selections": []})["status"] == "no_support"


@pytest.mark.parametrize("raw", ['{"selections":[],"selections":[]}', 'NaN', 'x' * 4097])
def test_strict_json_and_visible_output_limit(raw):
    assert parse_evidence(raw, approved_text=TEXT, verdict=VERDICT, sources=[SOURCE])["code"] == "OUTPUT_INVALID"


def test_payload_binds_catalog_only_and_rejects_invalid_input_evidence():
    args = dict(approved_text=TEXT, verdict=VERDICT, sources=[SOURCE], model="fixture", max_tokens=8192)
    payload = build_evidence_payload(**args)
    data = json.loads(payload["messages"][1]["content"])
    assert data["classification_locked"] is True and data["schema"]["properties"]["selections"]["maxItems"] == 2
    assert payload["max_tokens"] == 8192 and "thinking" not in payload and "response_format" not in payload
    assert "source_url" not in str(data) and "do-not-send" not in str(data)
    with pytest.raises(ValueError):
        build_evidence_payload(**{**args, "approved_text": "Đầu vào khác"})
    with pytest.raises(ValueError):
        build_evidence_payload(**{**args, "max_tokens": 8193})


def call(*, finish="stop", status=200, capture_raw=False, raw=None, mutation=None, sources=None):
    raw = json.dumps(output(), ensure_ascii=False) if raw is None else raw
    requests = []
    async def execute():
        def handler(request):
            requests.append(request)
            return httpx.Response(status, json={"model": "fixture", "choices": [{"finish_reason": finish,
                "message": {"content": raw}}], "usage": {"total_tokens": 345, "completion_tokens": 42}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            checked_sources = [SOURCE] if sources is None else sources
            payload = build_evidence_payload(approved_text=TEXT, verdict=VERDICT, sources=checked_sources, model="fixture")
            if mutation:
                mutation(payload)
            return await call_evidence(client, endpoint="https://provider.example/chat/completions",
                api_key="fixture-secret-do-not-expose", payload=payload, approved_text=TEXT,
                verdict=VERDICT, sources=checked_sources, timeout=1, capture_raw=capture_raw)
    return asyncio.run(execute()), requests


def test_transport_is_one_attempt_usage_preserved_and_raw_capture_opt_in():
    result, requests = call()
    assert result["status"] == "ok" and len(requests) == 1
    assert result["usage"]["total_tokens"] == 345 and "raw_content" not in result
    assert "fixture-secret-do-not-expose" not in json.dumps(result)
    captured, _ = call(capture_raw=True)
    assert captured["raw_content"] == json.dumps(output(), ensure_ascii=False)


@pytest.mark.parametrize("kwargs,code", [
    ({"finish": "length", "raw": None}, "OUTPUT_TRUNCATED"),
    ({"finish": "tool_calls"}, "RESPONSE_INCOMPLETE"),
    ({"status": 429}, "HTTP_429"),
    ({"raw": "not json"}, "OUTPUT_INVALID"),
])
def test_transport_preserves_failures_and_does_not_retry(kwargs, code):
    result, requests = call(**kwargs)
    assert result["code"] == code and len(requests) == 1
    assert result["validation"]["classification_changed"] is False and "raw_content" not in result


def test_no_sources_skip_provider_and_altered_payload_cannot_be_sent():
    result, requests = call(sources=[])
    assert result["status"] == "no_support" and requests == []
    result, requests = call(mutation=lambda payload: payload.update(thinking={"type": "disabled"}))
    assert result["code"] == "INPUT_INVALID" and requests == []
