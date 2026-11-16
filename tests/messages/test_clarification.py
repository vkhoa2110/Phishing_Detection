import pytest

from app.domain.clarification import plan, preview


def test_questions_are_only_for_semantic_unknown_and_do_not_request_raw_secrets():
    assert plan({"status": "error", "code": "TIMEOUT"})["questions"] == []
    result = plan({"status": "ok", "verdict": {"risk_level": "UNKNOWN"},
        "core_decision": {"missing_context": ["secret_destination", "initiated_by_user"]}})
    assert len(result["questions"]) == 2
    assert all("code" in q and len(q["choices"]) >= 3 for q in result["questions"])


def test_preview_redacts_again_rejects_arbitrary_answers_and_stays_local():
    args = [{"code": "secret_destination", "value": "third_party"}]
    result = preview("Liên hệ khoa@example.org", args)
    assert "khoa@" not in result["text"] and result["provider_calls"] == 0
    assert result["requires_confirmation"] and result["context_is_user_reported"]
    with pytest.raises(ValueError): preview("Nội dung", args + args)
    with pytest.raises(ValueError): preview("Nội dung", [{"code": "secret_destination", "value": "arbitrary"}])
    with pytest.raises(ValueError): preview("x" * 8000, args)
