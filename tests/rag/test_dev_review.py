import json

import pytest

from evaluation.rag.dev_review import parse_explanation, parse_relevance


def test_relevance_requires_every_document_and_preserves_unknown():
    request = {"documents": [{"document_id": "D1", "text": "Không gửi OTP cho người gọi."},
                             {"document_id": "D2", "text": "Phạm vi khác."}]}
    rows = [{"document_id": "D1", "grade": 2, "source_quote": "Không gửi OTP", "notes": "Fixture."},
            {"document_id": "D2", "grade": "UNKNOWN", "source_quote": "", "notes": "Chưa đủ căn cứ."}]
    result = parse_relevance(json.dumps({"judgments": rows}), request)
    assert result["judgments"][1]["grade"] == "UNKNOWN"
    with pytest.raises(ValueError):
        parse_relevance(json.dumps({"judgments": rows[:1]}), request)
    rows[0]["source_quote"] = "Chuỗi không tồn tại"
    with pytest.raises(ValueError):
        parse_relevance(json.dumps({"judgments": rows}), request)


def test_explanation_source_dimensions_are_na_only_without_citations():
    request = {"candidates": [{"candidate_id": "C1", "verdict": {"knowledge_support": []}}]}
    row = {"candidate_id": "C1", "correct_signals": 2, "relevant_sources": None,
           "claim_supported": None, "appropriate_actions": 1, "notes": "Fixture."}
    assert parse_explanation(json.dumps({"reviews": [row]}), request)["status"] == "ok"
    row["claim_supported"] = 0
    with pytest.raises(ValueError):
        parse_explanation(json.dumps({"reviews": [row]}), request)
    request["candidates"][0]["verdict"]["knowledge_support"] = [{"document_id": "D1"}]
    row.update(relevant_sources=1, claim_supported=2)
    assert parse_explanation(json.dumps({"reviews": [row]}), request)["status"] == "ok"
