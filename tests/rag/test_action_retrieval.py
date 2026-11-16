from copy import deepcopy

from app.services.rag.action_retrieval import actions, rerank


def document(identifier, text, score):
    return {"document_id": identifier, "title": "Hướng dẫn", "text": text, "score": score, "context_note": ""}


def test_action_filter_rejects_an_unrelated_high_cosine_source_without_mutation():
    candidates = [document("VN-RAG-001", "Kiểm tra vé máy bay qua hãng.", .95),
                  document("VN-RAG-002", "Không gửi mã OTP cho người gọi.", .90)]
    before = deepcopy(candidates)
    selected = rerank("Họ yêu cầu tôi đọc mã OTP cho người hỗ trợ.", candidates)
    assert [s["document_id"] for s in selected] == ["VN-RAG-002"]
    assert selected[0]["score"] == .90 and selected[0]["action_overlap"] == ["authentication"]
    assert candidates == before


def test_missing_action_coverage_can_abstain_and_cannot_prove_a_scam():
    candidates = [document("VN-RAG-001", "Bảo vệ mã OTP và tài khoản.", .99)]
    assert rerank("Xử lý nợ xấu CIC", candidates) == []
    assert actions("Tôi tự nhập OTP và không đọc cho người gọi.") == {"authentication"}
    selected = rerank("Tôi tự nhập OTP và không đọc cho người gọi.", candidates)
    assert "risk_level" not in selected[0]
