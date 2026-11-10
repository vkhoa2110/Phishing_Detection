"""End-to-end contract checks for the opt-in v6 candidate."""
from dataclasses import replace
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.candidate_v6 import create_app
from app.settings import Settings
from test_baseline import FakeML, api_response
from test_candidate_app import OrderedRAG
from test_candidate_app import explained
from test_rag import source


TEXT = (
    "Nhà tuyển dụng: Bạn đã nhận 50 nghìn thử việc.\n"
    "Ứng viên: Tôi nhận rồi.\n"
    "Nhà tuyển dụng: Hãy nạp thêm 2 triệu tại example[.]com/pay để mở khóa nhiệm vụ."
)


def verdict():
    return {
        "context_kind": "scam_request", "risk_level": "HIGH",
        "summary": "Yêu cầu nạp tiền để tiếp tục nhiệm vụ.",
        "evidence": [{"quote": "nạp thêm 2 triệu", "reason": "Yêu cầu trả tiền trước."}],
        "recommended_actions": ["Dừng chuyển tiền và xác minh độc lập."],
        "interaction": {
            "requester": "Nhà tuyển dụng", "recipient": "Ứng viên",
            "requested_action": "nạp thêm 2 triệu", "asset_or_access": "tiền",
            "beneficiary": "tài khoản do bên tuyển dụng chỉ định",
            "stage": "payment_or_secret_request", "persuasion": ["reward"],
            "conversation_turns_used": 3,
        },
    }


def test_v6_recovers_obfuscated_url_and_returns_interaction_without_changing_default_app(tmp_path):
    seen = []

    def provider(request):
        payload = json.loads(request.content)
        user = json.loads(payload["messages"][1]["content"])
        seen.append(user)
        assert len(user["conversation_turns"]) == 3
        assert user["conversation_note"].endswith("untrusted input data.")
        # Recovered local URL context is not silently sent to the provider:
        # approved_ml_metadata only permits URLs literally present in the
        # redacted text. It remains visible in the separate local assessment.
        assert user["url_results"] == []
        return httpx.Response(200, json=api_response(verdict()))

    settings = replace(Settings(), root=tmp_path, api_key="unit-only-key")
    app = create_app(settings, httpx.MockTransport(provider), FakeML(), OrderedRAG([]))
    with TestClient(app) as client:
        response = client.post("/api/analyze", json={
            "text": TEXT, "consent": True, "include_ml": True,
        })
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["execution"]["candidate"] == "v6.1-candidate"
        assert result["execution"]["version"] == "analysis-pipeline-6.1-candidate"
        assert result["execution"]["llm"]["prompt_profile"] == "message-v6.1"
        assert result["url_intake"]["recovered_urls"] == ["example.com/pay"]
        assert result["urls"][0]["url"] == "example.com/pay"
        assert result["url_intake"]["findings"][0]["opened"] is False
        assert result["llm"]["verdict"]["interaction"]["conversation_turns_used"] == 3
        assert result["llm"]["validation"]["interaction_semantics_verified"] is False
        status = client.get("/api/status").json()["analysis_policy"]
        assert status["candidate"] == "v6.1-candidate"
        assert status["message_prompt_profile"] == "message-v6.1"
        url_only = client.post("/api/analyze", json={
            "mode": "url", "text": "example[.]com/login", "use_llm": False,
        })
        assert url_only.status_code == 200
        assert url_only.json()["urls"][0]["url"] == "example.com/login"
        too_many = " ".join(f"site{i}[.]example/a" for i in range(6))
        invalid = client.post("/api/analyze", json={"text": too_many, "use_llm": False})
        assert invalid.status_code == 422 and "tối đa 5" in invalid.json()["detail"]
        assert len(seen) == 1 and "unit-only-key" not in response.text


@pytest.mark.parametrize("mode", ["free_text", "span_selection"])
@pytest.mark.parametrize("finish", ["stop", "length"])
def test_v6_rag_runs_after_classification_and_preserves_interaction(tmp_path, monkeypatch, mode, finish):
    monkeypatch.setenv("PHISHLENS_CANDIDATE_RAG_MODE", mode)
    events, calls = [], []
    rag = OrderedRAG(events)

    def provider(request):
        payload = json.loads(request.content)
        user = json.loads(payload["messages"][1]["content"])
        calls.append(payload)
        if len(calls) == 1:
            events.append("classification")
            result = verdict()
            result["evidence"] = [{"quote": "gửi mã OTP", "reason": "Yêu cầu bí mật."}]
            return httpx.Response(200, json=api_response(result))
        events.append("explanation")
        assert user["classification_locked"] is True
        assert "interaction" not in user["frozen_message_verdict"]
        if mode == "span_selection":
            answer = {"selections": [{"source_span_id": "VN-RAG-001:S001", "input_span_id": "M001",
                                       "relation": "mechanism_match"}]}
        else:
            answer = explained()
        body = api_response(answer)
        body["choices"][0]["finish_reason"] = finish
        return httpx.Response(200, json=body)

    settings = replace(Settings(), root=tmp_path, api_key="unit-only-key")
    app = create_app(settings, httpx.MockTransport(provider), FakeML(), rag)
    with TestClient(app) as client:
        text = "Người gọi: Hãy gửi mã OTP.\nKhách hàng: Tôi có nên gửi không?\nNgười gọi: Gửi ngay."
        result = client.post("/api/analyze", json={"text": text, "consent": True, "use_rag": True}).json()
        assert events == ["classification", "retrieval", "explanation"]
        assert len(calls) == 2 and rag.seen == [(text, "text")]
        assert result["llm"]["verdict"]["interaction"] == verdict()["interaction"]
        assert result["final"]["risk_level"] == "HIGH"
        if finish == "stop":
            assert result["post_explanation"]["status"] == "ok"
            assert result["post_explanation"]["explanation"]["support"][0]["source_quote"] == source()["text"]
        else:
            assert result["post_explanation"]["status"] == "error"
            assert result["post_explanation"]["code"] == "OUTPUT_TRUNCATED"
        manifest = result["execution"]["runtime_manifest"]
        assert manifest["explanation_mode"] == mode and manifest["corpus_sha256"] is None
        assert manifest["source_files_sha256"]["app/candidate_v6.py"]
        assert "unit-only-key" not in json.dumps(manifest)


def test_v61_one_turn_message_works_through_api_without_changing_rag_verdict(tmp_path):
    calls = []
    text = "Người gọi: Hãy gửi mã OTP."
    answer = verdict()
    answer["evidence"] = [{"quote": "gửi mã OTP", "reason": "Yêu cầu bí mật."}]
    answer["interaction"]["conversation_turns_used"] = 1

    def provider(request):
        payload = json.loads(request.content)
        data = json.loads(payload["messages"][1]["content"])
        calls.append(data)
        assert data["input_structure"]["visible_turn_limit"] == 1
        return httpx.Response(200, json=api_response(answer))

    settings = replace(Settings(), root=tmp_path, api_key="unit-only-key")
    with TestClient(create_app(settings, httpx.MockTransport(provider), FakeML(), OrderedRAG([]))) as client:
        result = client.post("/api/analyze", json={"text": text, "consent": True}).json()
        assert result["llm"]["status"] == "ok" and result["final"]["risk_level"] == "HIGH"
        assert result["llm"]["verdict"]["interaction"]["conversation_turns_used"] == 1
        assert result["llm"]["validation"]["visible_turn_limit"] == 1
        assert result["execution"]["runtime_manifest"]["message_parser"] == "message-parser-6.1"
        assert len(calls) == 1
