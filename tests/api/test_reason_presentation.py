import json

from fastapi.testclient import TestClient

from app.domain.claim_grounding import VERSION, NEUTRAL_SUMMARY
from tests.api.test_focused_app import packet
from tests.api.test_runtime import runtime
from tests.api.test_candidate_app import OrderedRAG


def test_deployed_focused_warns_about_mismatched_reason_and_does_not_send_it_to_rag(tmp_path):
    calls = []
    text = "Cập nhật địa chỉ giao hàng https://example.org"
    decision = {"risk_level": "HIGH", "context_kind": "scam_request", "reason_code": "payment_redirection",
                "quotes": ["Cập nhật địa chỉ giao hàng"], "missing_context": []}
    def provider(request):
        payload = json.loads(request.content); calls.append(payload)
        if len(calls) == 1: return packet(decision)
        assert "Nội dung yêu cầu đổi nơi nhận tiền" not in json.dumps(payload, ensure_ascii=False)
        assert NEUTRAL_SUMMARY in json.dumps(payload, ensure_ascii=False)
        return packet({}, finish="length")
    with TestClient(runtime(tmp_path, provider, rag=OrderedRAG([]))) as client:
        status = client.get("/api/status").json()
        assert status["runtime"]["reason_presentation"] == VERSION
        result = client.post("/api/analyze", json={"text": text, "consent": True, "use_rag": True}).json()
    assert len(calls) == 2
    assert result["llm"]["verdict"]["risk_level"] == result["final"]["risk_level"] == "HIGH"
    assert result["assessments"]["url"]["risk_level"] == "HIGH"
    assert result["llm"]["verdict"]["summary"] == NEUTRAL_SUMMARY
    assert result["llm"]["core_decision"] == decision
    assert result["llm"]["claim_grounding"]["status"] == "needs_review"
    assert result["llm"]["warnings"] and result["final"]["requires_review"]
    assert result["post_explanation"]["status"] == "error"
    assert result["execution"]["llm"]["reason_presentation"] == VERSION
    assert result["execution"]["runtime"]["calls_attempted"] == 2


def test_preserved_research_factory_is_not_rewritten(tmp_path):
    from tests.api.test_focused_app import app
    decision = {"risk_level": "HIGH", "context_kind": "scam_request", "reason_code": "advance_fee",
                "quotes": ["Cập nhật địa chỉ"], "missing_context": []}
    with TestClient(app(tmp_path, lambda request: packet(decision))) as client:
        result = client.post("/api/analyze", json={"text": "Cập nhật địa chỉ", "consent": True}).json()
        assert "claim_grounding" not in result["llm"]
        assert result["llm"]["verdict"]["summary"].startswith("Nội dung yêu cầu đóng thêm tiền")
