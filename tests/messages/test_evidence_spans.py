import json

import pytest

from app.domain.evidence_spans import SpanError, align_quote
from app.services.llm.core import CoreOutputError, parse_core
from tests.messages.test_core_message import core


@pytest.mark.parametrize("text,quote", [
    ("Hãy\ngửi\nmã\nOTP\ncho\ntôi.", "gửi mã OTP cho tôi."),
    ("Hãy chuyển tiền vào tài khoản này.", "Chuyển tiền vào tài khoản này."),
    ("Hãy\r\nGỬI\t\tmã\u00a0OTP cho tôi.", "gửi mã OTP cho tôi."),
])
def test_formatting_quotes_become_literal_bounded_source_spans(text, quote):
    result = parse_core(json.dumps(core(quotes=[quote])), text)
    actual = result["verdict"]["evidence"][0]["quote"]
    alignment = result["validation"]["quote_alignment"]
    assert result["verdict"]["risk_level"] == "HIGH"
    assert actual in text
    assert result["core_decision"]["quotes"] == [actual]
    assert alignment["provider_quotes"] == [quote] and alignment["aligned_count"] == 1
    span = alignment["spans"][0]
    assert text[span["start"]:span["end"]] == actual
    assert result["validation"]["semantic_support_verified"] is False


@pytest.mark.parametrize("text,quote", [
    ("Hãy gửi mã OTP.", "Hãy chuyển mã OTP."),
    ("Hãy gửi mã OTP.", "Hay gui ma OTP."),
    ("Hãy gửi\nmã OTP.", "Hãy gửimã OTP."),
    ("Mã [SECRET] của bạn.", "Mã [secret] của bạn."),
    ("Mã [SECRET] của bạn.", "Mã 123456 của bạn."),
    ("Xem https://example.org/CaseSensitive", "Xem https://example.org/casesensitive"),
    ("Xem https://example.org/token?K=Value", "Xem https://example.org/token?k=value"),
    ("Xem https://example.org/path", "Xem https://other.example/path"),
    ("Xem https://example.org/path", "PATH"),
    ("Xem https://example.org/token?key=value", "key=VALUE"),
    ("Masse", "Maße"),
])
def test_alignment_cannot_invent_words_accents_URL_bytes_or_masked_values(text, quote):
    with pytest.raises(SpanError, match="QUOTE_NOT_FOUND"):
        align_quote(quote, text)


def test_exact_quote_wins_and_expanded_spans_and_duplicate_alignment_are_rejected():
    literal, span = align_quote("gửi OTP", "gửi\nOTP và gửi OTP")
    assert literal == "gửi OTP" and span["match"] == "exact" and span["start"] == 11
    with pytest.raises(SpanError, match="QUOTE_SPAN_TOO_LONG"):
        align_quote("gửi OTP", "gửi" + "\n" * 250 + "OTP")
    with pytest.raises(CoreOutputError, match="QUOTE_DUPLICATE_AFTER_ALIGNMENT"):
        parse_core(json.dumps(core(quotes=["gửi OTP", "Gửi OTP"])), "gửi\nOTP")


def test_partial_URL_match_does_not_hide_later_valid_text_span():
    text = "https://example.org/path rồi mới tới path"
    literal, span = align_quote("PATH", text)
    assert literal == "path" and span["start"] == text.rfind("path")


@pytest.mark.parametrize("value,code", [
    ('not JSON', "CORE_JSON_INVALID"),
    ('{"risk_level":"HIGH","risk_level":"LOW"}', "CORE_JSON_INVALID"),
    (json.dumps(core(risk_level="unexpected-private-value")), "CORE_SCHEMA_INVALID"),
    (json.dumps(core(quotes=["không có trong bản gửi"])), "QUOTE_NOT_FOUND"),
])
def test_failure_diagnostics_do_not_copy_provider_content(value, code):
    with pytest.raises(CoreOutputError) as error:
        parse_core(value, "gửi OTP")
    diagnostic = error.value.diagnostic
    assert diagnostic["code"] == code
    assert "unexpected-private-value" not in json.dumps(diagnostic)
