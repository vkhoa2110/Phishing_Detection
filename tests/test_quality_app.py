import json
from dataclasses import replace

import httpx
from fastapi.testclient import TestClient

from app.quality import create_app
from app.settings import Settings
from test_baseline import api_response, completion, FakeML
from test_rag import FakeRAG


class MiddleML(FakeML):
    def predict(self, urls):
        return [{**r, "score": .6, "risk_level": "WARNING"} for r in super().predict(urls)]


def test_quality_factory_uses_v4_and_keeps_uncertain_urls_separate_from_real_otp_requests(tmp_path):
    requests = []
    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=api_response({**completion(), "context_kind": "scam_request"}))
    settings = replace(Settings(), root=tmp_path, api_key="unit-test-key", max_tokens=40960)
    with TestClient(create_app(settings, httpx.MockTransport(handle), MiddleML(), FakeRAG())) as client:
        result = client.post("/api/analyze", json={"text": "Hãy gửi mã OTP. https://example.org", "consent": True}).json()
        assert result["final"]["risk_level"] == "HIGH"
        assert result["urls"][0]["risk_level"] == "UNKNOWN" and result["urls"][0]["raw_risk_level"] == "WARNING"
        assert result["llm"]["prompt_profile"] == "message-v4"
        assert result["execution"]["llm"]["requested_profile"] == "message-v4"
        assert result["execution"]["llm"]["requested_schema_profile"] == "message-v3"
        assert requests[0]["max_tokens"] == 8192
        assert "unit-test-key" not in json.dumps(result)
        status = client.get("/api/status").json()
        assert status["analysis_policy"]["message_prompt_profile"] == "message-v4"
        assert status["analysis_policy"]["pipeline_version"] == "analysis-pipeline-4.0"
        assert client.get("/").status_code == 200


def test_uncertain_url_is_never_treated_as_safe_on_llm_failure(tmp_path):
    settings = replace(Settings(), root=tmp_path, api_key="unit-test-key")
    with TestClient(create_app(settings, httpx.MockTransport(lambda _: httpx.Response(500)), MiddleML(), FakeRAG())) as client:
        result = client.post("/api/analyze", json={"mode": "url", "text": "https://example.org", "consent": True}).json()
        assert result["final"]["risk_level"] == "UNKNOWN" and result["final"]["requires_review"]
        assert result["llm"]["status"] == "error"
        assert client.post("/api/analyze", json={"text": "xin chào"}).status_code == 422


def test_low_message_does_not_clear_high_url_and_sources_are_passed_as_scoped_data(tmp_path):
    requests = []
    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=api_response({**completion(risk="LOW"), "context_kind": "routine", "evidence": [], "knowledge_support": []}))
    with TestClient(create_app(replace(Settings(), root=tmp_path, api_key="unit-test-key"), httpx.MockTransport(handle), FakeML(), FakeRAG())) as client:
        result = client.post("/api/analyze", json={"text": "Thông báo https://example.org", "consent": True, "use_rag": True}).json()
        assert result["final"]["risk_level"] == "LOW" and result["assessments"]["url"]["risk_level"] == "HIGH"
        assert result["final"]["requires_review"] and result["llm"]["rag"] is True
        assert "reference_documents" in json.loads(requests[0]["messages"][1]["content"])
