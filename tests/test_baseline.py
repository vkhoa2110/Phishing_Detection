import json
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient

from app.fusion import fuse, fuse_legacy
from app.llm_service import LLMFailure, normalize_endpoint, parse_verdict
from app.main import create_app
from app.privacy import redact
from app.settings import Settings
from app.urls import extract_urls


class FakeML:
    """Chỉ dùng trong kiểm thử, không đóng vai mô hình trong ứng dụng."""
    def load(self, reload=False):
        return self.status()

    def status(self):
        return {"ready": True, "run_id": "test-fixture", "feature_count": 21, "message": "ok"}

    def predict(self, urls):
        return [{"id": f"URL-{i:02}", "url": u, "status": "ok", "score": .9,
                 "risk_level": "HIGH", "warning_threshold": .4, "high_threshold": .8}
                for i, u in enumerate(urls, 1)]


def settings(tmp_path):
    return replace(Settings(), root=tmp_path, api_key="", timeout_seconds=1)


def completion(risk="HIGH", quote="gửi mã OTP"):
    return {"risk_level": risk, "summary": "Yêu cầu thông tin xác thực cần được kiểm tra.",
            "evidence": [{"quote": quote, "reason": "Nội dung yêu cầu gửi thông tin xác thực."}],
            "recommended_actions": ["Xác minh qua kênh chính thức đã biết."]}


def api_response(verdict):
    return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(verdict, ensure_ascii=False)}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 40, "total_tokens": 60}}


def test_redaction_covers_values_not_domain():
    text = "Gửi tới khoa@example.org, số 0912345678, OTP: 123456. https://bank.example/login?token=secret123#private"
    masked, fields = redact(text)
    for secret in ["khoa@", "0912345678", "123456", "secret123", "#private"]:
        assert secret not in masked
    assert "bank.example" in masked
    assert fields


def test_bare_query_and_url_auth_redaction():
    masked, _ = redact("example.org?token=hidden https://user:pass@example.org/a")
    assert "hidden" not in masked and "user:pass" not in masked


def test_url_dedup_and_punctuation():
    urls, invalid = extract_urls("Xem (https://example.org/a). https://example.org/a hoặc example.com?x=1", "text")
    assert urls == ["https://example.org/a", "example.com?x=1"]
    assert invalid == []


def test_email_is_not_url():
    assert extract_urls("Liên hệ khoa@example.org để trao đổi", "text") == ([], [])


def test_invalid_and_too_many_urls():
    with pytest.raises(ValueError):
        extract_urls("javascript:alert(1)", "url")
    with pytest.raises(ValueError):
        extract_urls(" ".join(f"https://site{i}.example/" for i in range(6)), "text")


@pytest.mark.parametrize("ml,llm,mode,expected", [
    ("HIGH", "LOW", "text", "HIGH"),
    ("WARNING", "LOW", "text", "WARNING"),
    ("LOW", "HIGH", "text", "HIGH"),
    ("LOW", "WARNING", "text", "WARNING"),
    ("LOW", "LOW", "text", "LOW"),
    ("LOW", None, "text", "UNKNOWN"),
    ("LOW", None, "url", "LOW"),
    (None, "LOW", "text", "LOW"),
    (None, None, "text", "UNKNOWN"),
])
def test_legacy_fusion(ml, llm, mode, expected):
    urls = [{"status": "ok", "risk_level": ml}] if ml else []
    llm_data = {"status": "ok", "verdict": {"risk_level": llm}} if llm else {"status": "error"}
    assert fuse_legacy(mode, urls, llm_data, [])["risk_level"] == expected


def test_missing_url_classifier_does_not_become_safe():
    result = fuse("text", [{"status": "unavailable"}], {"status": "ok", "verdict": {"risk_level": "LOW"}}, [])
    assert result["scope"] == "message" and result["risk_level"] == "LOW"
    assert result["assessments"]["url"]["risk_level"] == "UNKNOWN"
    assert result["requires_review"]


def test_invalid_quote_is_not_accepted():
    verdict, warnings = parse_verdict(json.dumps(completion(quote="không có trong đầu vào")), "xin chào")
    assert verdict.risk_level == "UNKNOWN" and verdict.evidence == [] and warnings


def test_code_fence_supported_and_extra_sources_rejected():
    verdict, _ = parse_verdict("```json\n" + json.dumps(completion()) + "\n```", "Hãy gửi mã OTP")
    assert verdict.risk_level == "HIGH"
    payload = completion(); payload["sources"] = ["nguồn bịa"]
    with pytest.raises(LLMFailure):
        parse_verdict(json.dumps(payload), "gửi mã OTP")


def test_endpoint_restrictions(tmp_path):
    s = settings(tmp_path)
    assert normalize_endpoint("https://mkp-api.fptcloud.com", s).endswith("/v1/chat/completions")
    assert normalize_endpoint("https://mkp-api.fptcloud.com/v1", s).endswith("/v1/chat/completions")
    for endpoint in ["http://mkp-api.fptcloud.com/v1/chat/completions", "https://127.0.0.1/v1/chat/completions", "https://evil.test/chat/completions", "https://mkp-api.fptcloud.com@evil.test/v1/chat/completions"]:
        with pytest.raises(LLMFailure):
            normalize_endpoint(endpoint, s)


def test_no_consent_no_api_call(tmp_path):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=api_response(completion()))
    with TestClient(create_app(settings(tmp_path), httpx.MockTransport(handler), FakeML())) as c:
        assert c.post("/api/analyze", json={"text": "gửi mã OTP", "use_llm": True}).status_code == 422
        assert not calls


def test_api_masks_text_and_ml_metadata(tmp_path):
    captured = []
    def handler(request):
        captured.append(json.loads(request.content))
        assert request.headers["authorization"] == "Bearer test-key"
        return httpx.Response(200, json=api_response(completion()))
    with TestClient(create_app(settings(tmp_path), httpx.MockTransport(handler), FakeML())) as c:
        response = c.post("/api/analyze", json={"text": "Hãy gửi mã OTP tới khoa@example.org; https://example.org/?token=supersecret", "consent": True, "api_key": "test-key"})
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["final"]["risk_level"] == "HIGH" and result["llm"]["status"] == "ok"
        assert "test-key" not in response.text
        sent = json.dumps(captured)
        assert "supersecret" not in sent and "khoa@" not in sent
        assert captured[0]["stream"] is False
        assert "rag" not in json.loads(captured[0]["messages"][1]["content"])


@pytest.mark.parametrize("code", [401, 402, 404, 429, 500])
def test_api_errors_keep_ml(tmp_path, code):
    def handler(request):
        return httpx.Response(code, json={"secret": "provider internal data"})
    with TestClient(create_app(settings(tmp_path), httpx.MockTransport(handler), FakeML())) as c:
        response = c.post("/api/analyze", json={"mode": "url", "text": "https://example.org", "consent": True, "api_key": "secret-key"})
        result = response.json()
        assert result["final"]["risk_level"] == "HIGH"
        assert result["llm"]["status"] == "error"
        assert "secret-key" not in response.text and "provider internal data" not in response.text


def test_model_only_does_not_call_fpt(tmp_path):
    def handler(request):
        pytest.fail("Không được gọi API khi tắt LLM.")
    with TestClient(create_app(settings(tmp_path), httpx.MockTransport(handler), FakeML())) as c:
        result = c.post("/api/analyze", json={"text": "https://example.org", "mode": "url", "use_llm": False}).json()
        assert result["llm"]["status"] == "disabled" and result["urls"][0]["status"] == "ok"


def test_baseline_without_model_and_key_is_honest(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as c:
        assert c.get("/api/status").json()["ml"]["ready"] is False
        result = c.post("/api/analyze", json={"text": "Xin chào", "consent": True}).json()
        assert result["final"]["risk_level"] == "UNKNOWN"
        assert result["llm"]["code"] == "API_KEY_MISSING"


def test_input_limits_origin_and_validation_do_not_echo_key(tmp_path):
    with TestClient(create_app(settings(tmp_path), model_service=FakeML())) as c:
        response = c.post("/api/analyze", json={"text": "x" * 8001, "api_key": "secret-value"})
        assert response.status_code == 422 and "secret-value" not in response.text
        assert c.post("/api/preview", json={"text": "hello"}, headers={"Origin": "https://evil.test"}).status_code == 403
        assert c.get("/").status_code == 200
        assert "no-store" in c.get("/api/status").headers["cache-control"]


def test_include_ml_can_be_disabled_and_no_url_is_not_invented(tmp_path):
    calls = []
    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=api_response({"risk_level": "LOW", "summary": "Chưa thấy dấu hiệu rõ ràng.", "evidence": [], "recommended_actions": []}))
    with TestClient(create_app(settings(tmp_path), httpx.MockTransport(handler), FakeML())) as c:
        r = c.post("/api/analyze", json={"text": "Thông báo họp nhóm", "consent": True, "api_key": "test-key", "include_ml": False}).json()
        assert r["llm"]["included_ml"] is False and r["final"]["risk_level"] == "LOW"
        assert "url_results" not in json.loads(calls[0]["messages"][1]["content"])


def test_timeout_preserves_url_result(tmp_path):
    def handler(request):
        raise httpx.ReadTimeout("timeout", request=request)
    with TestClient(create_app(settings(tmp_path), httpx.MockTransport(handler), FakeML())) as c:
        r = c.post("/api/analyze", json={"text": "https://example.org/", "mode": "url", "consent": True, "api_key": "test-key"}).json()
        assert r["llm"]["code"] == "TIMEOUT" and r["final"]["risk_level"] == "HIGH"


def test_invalid_json_does_not_remove_ml_warning(tmp_path):
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "not JSON"}}]})
    with TestClient(create_app(settings(tmp_path), httpx.MockTransport(handler), FakeML())) as c:
        r = c.post("/api/analyze", json={"text": "https://example.org/", "mode": "url", "consent": True, "api_key": "test-key"}).json()
        assert r["llm"]["code"] == "OUTPUT_INVALID" and r["final"]["risk_level"] == "HIGH"

