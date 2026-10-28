import json
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient

from app.fusion import POLICY_VERSION, assess_urls, fuse
from app.llm_service import MESSAGE_PROMPT_VERSION, parse_verdict
from app.main import create_app
from app.schemas import AnalyzeInput
from app.settings import Settings
from test_baseline import FakeML, api_response, completion


@pytest.mark.parametrize("url_level", ["HIGH", "WARNING", "LOW", None])
@pytest.mark.parametrize("message_level", ["HIGH", "WARNING", "LOW", "UNKNOWN"])
def test_message_and_url_targets_stay_distinct(url_level, message_level):
    urls = [{"status": "ok", "risk_level": url_level}] if url_level else []
    llm = {"status": "ok", "verdict": {"risk_level": message_level}}
    result = fuse("text", urls, llm, [])
    assert result["risk_level"] == message_level
    assert result["scope"] == "message" and result["policy_version"] == POLICY_VERSION
    assert result["assessments"]["url"]["risk_level"] == (url_level or "UNKNOWN")
    assert result["conflict"] == bool((url_level in {"HIGH", "WARNING"} and message_level == "LOW")
        or (url_level == "LOW" and message_level in {"HIGH", "WARNING"}))
    if url_level in {"HIGH", "WARNING"}:
        assert result["requires_review"]


@pytest.mark.parametrize("status", ["disabled", "error", "pending", "unavailable"])
def test_failed_or_disabled_content_does_not_inherit_ml_verdict(status):
    urls = [{"status": "ok", "risk_level": "HIGH"}]
    result = fuse("text", urls, {"status": status}, [])
    assert result["risk_level"] == "UNKNOWN" and result["requires_review"]
    assert result["assessments"]["url"]["risk_level"] == "HIGH"
    assert fuse("url", urls, {"status": status}, [])["risk_level"] == "HIGH"


def test_partial_urls_are_not_silently_marked_low_or_cleared_by_content():
    urls = [{"status": "ok", "risk_level": "LOW"}, {"status": "error"}]
    url = assess_urls(urls, ["https://bad input"])
    assert url["risk_level"] == "UNKNOWN" and not url["complete"]
    assert url["processed"] == 1 and url["total"] == 3
    urls[0]["risk_level"] = "HIGH"
    assert assess_urls(urls, [])["risk_level"] == "HIGH"
    assert assess_urls(urls, [])["status"] == "partial"


def test_url_mode_does_not_claim_to_have_evaluated_message_actions():
    r = fuse("url", [{"status": "ok", "risk_level": "LOW"}],
             {"status": "ok", "verdict": {"risk_level": "HIGH"}}, [])
    assert r["scope"] == "url" and r["risk_level"] == "LOW"
    assert r["assessments"]["message"]["status"] == "not_applicable"


def test_context_hint_never_bypasses_evidence_validation():
    v = {**completion(quote="not in input"), "context_kind": "quoted_example"}
    parsed, warnings = parse_verdict(json.dumps(v), "Nội dung", prompt_profile="message-v2")
    assert parsed.risk_level == "UNKNOWN" and warnings
    v = {**completion(), "context_kind": "quoted_example"}
    parsed, _ = parse_verdict(json.dumps(v), "Hãy gửi mã OTP", prompt_profile="message-v2")
    assert parsed.risk_level == "HIGH"  # A claimed educational context does not auto-clear a request.


def test_api_defaults_do_not_send_ml_metadata_but_keep_url_alarm_visible(tmp_path):
    captured = []
    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json=api_response({**completion("LOW", "Đừng mở"), "context_kind": "quoted_example"}))
    cfg = replace(Settings(), root=tmp_path, api_key="test-fixture")
    with TestClient(create_app(cfg, httpx.MockTransport(handler), FakeML())) as client:
        r = client.post("/api/analyze", json={"text": "Bài tập: Đừng mở https://example.org/otp", "consent": True}).json()
        assert r["final"]["risk_level"] == "LOW" and r["final"]["conflict"]
        assert r["assessments"]["url"]["risk_level"] == "HIGH"
        assert r["llm"]["prompt_version"] == MESSAGE_PROMPT_VERSION
        body = json.loads(captured[0]["messages"][1]["content"])
        assert "url_results" not in body
        assert body["assessment_target"] == "message_actions_not_url_reputation"
        assert "MỤC TIÊU CỦA LƯỢT NÀY" in captured[0]["messages"][0]["content"]
        assert client.get("/api/status").json()["analysis_policy"]["default_include_ml"] is False
        assert AnalyzeInput(text="Test").include_ml is False


def test_text_api_failure_retains_url_alarm_without_claiming_message_is_scam(tmp_path):
    def handler(request):
        return httpx.Response(500)
    with TestClient(create_app(replace(Settings(), root=tmp_path, api_key="fixture"),
                               httpx.MockTransport(handler), FakeML())) as client:
        r = client.post("/api/analyze", json={"text": "Thông báo https://example.org", "consent": True}).json()
        assert r["final"]["risk_level"] == "UNKNOWN" and r["llm"]["status"] == "error"
        assert r["assessments"]["url"]["risk_level"] == "HIGH"
