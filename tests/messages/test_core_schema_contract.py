"""Published generation constraints must agree with strict runtime validation."""
import json

import pytest
from pydantic import ValidationError

from app.services.llm.core import CoreOutputError, CoreVerdict, build_payload, parse_core
from tests.api.test_focused_app import decision


def test_generation_schema_exposes_runtime_quote_length_bound():
    payload, _ = build_payload(text="Hãy gửi mã OTP", urls=[], include_ml=False, model="fixture", max_tokens=2048)
    schema = json.loads(payload["messages"][1]["content"])["output_schema"]
    quote_schema = schema["properties"]["quotes"]
    assert quote_schema["maxItems"] == 2 and quote_schema["items"]["maxLength"] == 240
    assert quote_schema["items"]["minLength"] == 1
    assert "HIGH, WARNING và LOW bắt buộc missing_context=[]" in payload["messages"][0]["content"]
    valid = {**decision(), "quotes": ["a" * 240]}
    assert CoreVerdict.model_validate(valid, strict=True).quotes == valid["quotes"]
    with pytest.raises(ValidationError):
        CoreVerdict.model_validate({**valid, "quotes": ["a" * 241]}, strict=True)


@pytest.mark.parametrize("change,expected", [
    ({"missing_context": ["sender_verification"]}, {"risk_level", "missing_context"}),
    ({"context_kind": "routine"}, {"risk_level", "context_kind", "reason_code", "quotes"}),
    ({"risk_level": "LOW"}, {"risk_level", "context_kind", "reason_code"}),
    ({"risk_level": "UNKNOWN"}, {"risk_level", "reason_code"}),
])
def test_inconsistent_decisions_stay_rejected_with_safe_actionable_fields(change, expected):
    text = "Hãy gửi mã OTP cho nhân viên. PRIVATE_DIAGNOSTIC_TEXT"
    with pytest.raises(CoreOutputError) as failed:
        parse_core(json.dumps({**decision(), **change}), text)
    assert failed.value.diagnostic["code"] == "CORE_SCHEMA_INVALID"
    assert set(failed.value.diagnostic["fields"]) == expected
    assert "PRIVATE" not in json.dumps(failed.value.diagnostic)


def test_oversized_quote_is_rejected_without_echoing_it_or_turning_into_low():
    quote = "gửi mã OTP " + "PRIVATE_SPAN_" * 25
    with pytest.raises(CoreOutputError) as failed:
        parse_core(json.dumps({**decision(), "quotes": [quote]}), quote)
    assert failed.value.diagnostic == {"status": "invalid", "code": "CORE_SCHEMA_INVALID", "fields": ["quotes"]}
