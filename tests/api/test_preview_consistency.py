from dataclasses import replace
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.runtime import create_app
from app.core.privacy import redact
from app.core.settings import Settings
from tests.api.test_baseline import FakeML
from tests.api.test_candidate_app import OrderedRAG
from tests.api.test_focused_app import packet


@pytest.mark.parametrize("original", [
    "https://r-926922334292.example/info",
    "https://0912345678.example/path",
    "www.r-926922334292.example/info",
    "https://example.org/customer/0912345678?token=synthetic-secret#private",
    "https://user:synthetic-secret@r-926922334292.example/path?token=synthetic-secret",
    "https://r-[NUMBER].example/info",
])
def test_masked_URL_is_finished_in_preview_and_remains_stable(original):
    preview, _ = redact(original)
    assert "926922334292" not in preview and "0912345678" not in preview
    assert "synthetic-secret" not in preview
    assert "[URL_KHONG_PHAN_TACH_DUOC]" not in preview
    assert "REDACTED" in preview
    assert redact(preview)[0] == preview


@pytest.mark.parametrize("profile", ["stable", "focused", "verifier-shadow"])
def test_confirmed_preview_reaches_provider_unchanged_and_new_edits_still_get_masked(tmp_path, profile):
    calls = []
    def provider(request):
        payload = json.loads(request.content)
        data = json.loads(payload["messages"][1]["content"])
        calls.append(data)
        if "reason_code" in data.get("output_schema", {}).get("properties", {}):
            return packet({"risk_level": "LOW", "context_kind": "routine", "reason_code": "no_fraud_evidence",
                           "quotes": [], "missing_context": []})
        return packet({"risk_level": "LOW", "context_kind": "routine", "summary": "Thông báo thông thường.",
                       "evidence": [], "recommended_actions": ["Tự kiểm tra trong ứng dụng đã cài."]})
    settings = replace(Settings(), root=tmp_path, api_key="server-fixture-only")
    app = create_app(profile, settings, transport=httpx.MockTransport(provider),
                     model_service=FakeML(), rag_service=OrderedRAG([]))
    raw = "Tự kiểm tra cập nhật. https://r-926922334292.example/info"
    with TestClient(app) as client:
        approved = client.post("/api/preview", json={"text": raw}).json()["text"]
        assert not calls
        result = client.post("/api/analyze", json={"text": raw, "llm_text": approved,
                             "consent": True, "include_ml": True}).json()
        assert result["llm"]["status"] == "ok"
        assert calls[0]["text"] == approved
        assert result["urls"][0]["url"] == "https://r-926922334292.example/info"
        edited = approved + " OTP: 123456"
        client.post("/api/analyze", json={"text": raw, "llm_text": edited, "consent": True})
        assert "123456" not in calls[-1]["text"] and "[SECRET]" in calls[-1]["text"]


def test_invalid_core_diagnostic_keeps_URL_and_usage_without_leaking_answer(tmp_path):
    def provider(request):
        return packet({"risk_level": "private-invalid-value", "secret_extra": "do-not-echo"})
    app = create_app("focused", replace(Settings(), root=tmp_path, api_key="server-fixture-only"),
        transport=httpx.MockTransport(provider), model_service=FakeML(), rag_service=OrderedRAG([]))
    with TestClient(app) as client:
        response = client.post("/api/analyze", json={"text": "Hãy gửi mã OTP https://example.org", "consent": True})
    result = response.json()
    assert result["llm"]["status"] == "error" and result["llm"]["code"] == "OUTPUT_INVALID"
    assert result["llm"]["telemetry"]["output_validation"]["code"] == "CORE_SCHEMA_INVALID"
    assert result["llm"]["usage"]["total_tokens"] == 24
    assert result["assessments"]["url"]["risk_level"] == "HIGH"
    assert "private-invalid-value" not in response.text and "do-not-echo" not in response.text
