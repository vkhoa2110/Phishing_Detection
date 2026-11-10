import asyncio
import json
from dataclasses import replace

import httpx
import pytest

from app.services.llm.message import MessageService, call_message, payload_for
from app.services.llm.client import LLMFailure, MESSAGE_V3_SYSTEM_PROMPT
from app.core.settings import Settings
from evaluation.messages.quality_pilot import ARMS, score, select_cases


def verdict(**changes):
    return {"risk_level": "HIGH", "context_kind": "scam_request", "summary": "Có yêu cầu gửi mã xác thực.",
            "evidence": [{"quote": "gửi OTP", "reason": "Yêu cầu bí mật cho bên liên hệ."}],
            "recommended_actions": ["Xác minh qua kênh đã biết."], **changes}


def api_body(content, reason="stop"):
    return {"choices": [{"finish_reason": reason, "message": {"content": json.dumps(content, ensure_ascii=False)}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300}}


def test_v3_control_is_identical_to_existing_production_prompt_and_payload():
    p, used = payload_for(text="Gửi mã", urls=[], include_ml=False, sources=[], model="fixture", max_tokens=8192, profile="message-v3")
    assert p["messages"][0]["content"] == MESSAGE_V3_SYSTEM_PROMPT
    assert json.loads(p["messages"][1]["content"]) == {"input_type": "text", "text": "Gửi mã", "assessment_target": "message_actions_not_url_reputation"}
    assert used is False


def test_same_validator_preserves_unknown_on_bad_quotes_for_both_prompt_profiles():
    async def execute():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=api_body(verdict())))) as client:
            outputs = []
            for profile in ARMS:
                p, _ = payload_for(text="Xin chào", urls=[], include_ml=False, sources=[], model="fixture", max_tokens=8192, profile=profile)
                outputs.append(await call_message(client, endpoint="https://provider.example", api_key="test-only", payload=p,
                                                 text="Xin chào", sources=[], timeout=1))
            return outputs
    for output in asyncio.run(execute()):
        assert output["verdict"]["risk_level"] == "UNKNOWN"
        assert output["validation"]["original_risk_level"] == "HIGH"
        assert "EVIDENCE_NOT_IN_INPUT" in output["validation"]["reason_codes"]


def test_truncation_preserves_usage_without_exposing_a_prediction():
    async def execute():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=api_body({}, "length")))) as client:
            return await call_message(client, endpoint="https://provider.example", api_key="test-only", payload={}, text="gửi OTP", sources=[], timeout=1)
    output = asyncio.run(execute())
    assert output["status"] == "error" and output["code"] == "OUTPUT_TRUNCATED"
    assert output["usage"]["total_tokens"] == 300 and "verdict" not in output


def test_configured_service_uses_v4_with_legacy_schema_and_keeps_credentials_private(tmp_path):
    requests = []
    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=api_body(verdict()))
    async def execute():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            service = MessageService(replace(Settings(), root=tmp_path, api_key="test-only-key"), client)
            return await service.analyze(text="Hãy gửi OTP", mode="text", urls=[], include_ml=False,
                endpoint="", model="fixture", api_key="", prompt_profile="message-v3")
    output = asyncio.run(execute())
    assert output["prompt_profile"] == "message-v4" and output["verdict"]["risk_level"] == "HIGH"
    assert "test-only-key" not in json.dumps(output) and "raw_content" not in output
    assert requests[0]["messages"][0]["content"] != MESSAGE_V3_SYSTEM_PROMPT


def fixture_records(candidate="improved"):
    cases = []
    for dataset, labels in (("sms", [1]*9 + [0]*42 + [None]*29), ("url_context", [1]*16+[0]*16+[None]*8)):
        for i, label in enumerate(labels):
            cases.append({"id": f"{dataset}-{i}", "dataset": dataset, "variant": "education" if label == 0 else "secret_request",
                          "targets": {"message_behavior": label}})
    records = []
    for c in cases:
        y = c["targets"]["message_behavior"]
        for arm in ARMS:
            level = "UNKNOWN" if y is None else "HIGH" if y else "LOW"
            if c["dataset"] == "sms" and y == 0 and int(c["id"].split('-')[-1]) < 20 and arm == "message-v3":
                level = "HIGH"
            if arm == "message-v4" and candidate == "abstain_all":
                level = "UNKNOWN"
            records.append({"id": c["id"], "arm": arm, "status": "ok", "verdict": {"risk_level": level}})
    return cases, records


def test_acceptance_cannot_be_gamed_by_abstaining_on_everything():
    c, r = fixture_records()
    assert score(c, r)["gates"]["passed"] is True
    c, r = fixture_records("abstain_all")
    s = score(c, r)
    assert s["gates"]["checks"]["sms_false_alarm_improved"] is True
    assert s["gates"]["passed"] is False and s["gates"]["checks"]["sms_coverage_preserved"] is False


def test_pilot_keeps_all_sms_unknowns_and_all_variants_of_sampled_domains():
    rows = select_cases()
    assert len(rows) == 120
    sms = [c for c in rows if c["dataset"] == "sms"]
    contexts = [c for c in rows if c["dataset"] == "url_context"]
    assert len(sms) == 80 and sum(c["targets"]["message_behavior"] is None for c in sms) == 29
    assert len({c["url_id"] for c in contexts}) == 8
    assert all(sum(c["url_id"] == id_ for c in contexts) == 5 for id_ in {c["url_id"] for c in contexts})
    c, r = fixture_records()
    assert score(c, r[:-1])["metrics_ready"] is False
    with pytest.raises(ValueError, match="Duplicate"):
        score(c, r + [r[0]])
