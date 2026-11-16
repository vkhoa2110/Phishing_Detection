import asyncio
from dataclasses import replace
import json

import httpx
import pytest

from app.core.settings import Settings
from app.services.llm.client import LLMFailure
from app.services.llm.core import CoreMessageService, build_payload, parse_core
from app.services.llm.telemetry import LAST_CLASSIFIER_CALL


def core(**changes):
    return {"risk_level": "HIGH", "context_kind": "scam_request", "reason_code": "secret_request",
            "quotes": ["Đọc mã OTP cho tôi."], "missing_context": [], **changes}


def test_core_needs_only_a_complete_grounded_decision_not_interaction():
    result = parse_core(json.dumps(core()), "Đọc mã OTP cho tôi.")
    assert result["verdict"]["risk_level"] == "HIGH"
    assert "interaction" not in result["verdict"]
    assert result["validation"]["summary_origin"] == "deterministic_reason_template"
    assert result["validation"]["semantic_support_verified"] is False
    with pytest.raises(ValueError): parse_core(json.dumps(core()), "Thông báo họp.")
    with pytest.raises(ValueError): parse_core(json.dumps(core(quotes=[])), "Đọc mã OTP cho tôi.")
    with pytest.raises(ValueError): parse_core('{"risk_level":"LOW","risk_level":"HIGH"}', "Chào bạn")
    with pytest.raises(ValueError): parse_core(json.dumps(core())[:-2], "Đọc mã OTP cho tôi.")


def test_unknown_is_semantic_and_low_does_not_carry_a_scam_reason():
    value = core(risk_level="UNKNOWN", context_kind="insufficient", reason_code="missing_context",
                 quotes=[], missing_context=["secret_destination"])
    result = parse_core(json.dumps(value), "Hỗ trợ xác minh mã của bạn.")
    assert result["core_decision"]["missing_context"] == ["secret_destination"]
    with pytest.raises(ValueError): parse_core(json.dumps(core(risk_level="LOW")), "Đọc mã OTP cho tôi.")


def test_core_payload_removes_interaction_and_does_not_reintroduce_deleted_urls():
    payload, included = build_payload(text="Chào bạn.", urls=[{"url": "https://private.example", "score": .99}],
        include_ml=False, model="fixture", max_tokens=2048, thinking="disabled")
    data = json.loads(payload["messages"][1]["content"])
    assert included is False and "private.example" not in json.dumps(payload)
    assert "interaction" not in data["output_schema"]["properties"]
    assert "summary" not in data["output_schema"]["properties"]
    assert payload["thinking"] == {"type": "disabled"}


@pytest.mark.parametrize("finish", ["stop", "length"])
def test_core_observation_keeps_usage_on_failure_without_exposing_reasoning(finish):
    def respond(request):
        return httpx.Response(200, json={"id": "fixture-1", "model": "fixture",
            "usage": {"prompt_tokens": 11, "completion_tokens": 17, "total_tokens": 28,
                      "completion_tokens_details": {"reasoning_tokens": 12}},
            "choices": [{"finish_reason": finish, "message": {"content": json.dumps(core()),
                                                               "reasoning_content": "private-thought"}}]})
    async def run():
        LAST_CLASSIFIER_CALL.set(None)
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            service = CoreMessageService(replace(Settings(), api_key="offline-fixture", max_tokens=2048), client)
            args = dict(text="Đọc mã OTP cho tôi.", mode="text", urls=[], include_ml=False,
                        endpoint="", model="fixture", api_key="")
            if finish == "length":
                with pytest.raises(LLMFailure) as error: await service.analyze(**args)
                assert error.value.code == "OUTPUT_TRUNCATED"
                result = LAST_CLASSIFIER_CALL.get()
            else:
                result = await service.analyze(**args)
                assert result["verdict"]["risk_level"] == "HIGH"
            assert "private-thought" not in json.dumps(result)
            observed = LAST_CLASSIFIER_CALL.get()
            assert observed["usage"]["total_tokens"] == 28
            assert observed["completion_token_details"]["reasoning_tokens"] == 12
    asyncio.run(run())
