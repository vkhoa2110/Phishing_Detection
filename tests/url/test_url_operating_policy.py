import copy
import math

from app.services.url.policy import operating_prediction


def raw(score, high=.47):
    return {"id": "URL-01", "url": "https://example.org", "status": "ok", "score": score,
            "risk_level": "HIGH" if high is not None and score >= high else "WARNING" if score >= .11 else "LOW",
            "warning_threshold": .11, "high_threshold": high}


def test_abstention_never_turns_a_previous_alarm_into_low_or_changes_scores():
    for value in [0, .1099, .11, .3, .4699, .47, .9, 1]:
        before = raw(value)
        original = copy.deepcopy(before)
        after = operating_prediction(before)
        assert before == original
        assert after["score"] == before["score"]
        if before["risk_level"] != "LOW":
            assert after["risk_level"] != "LOW"
        assert after["risk_level"] == ("LOW" if value < .11 else "HIGH" if value >= .47 else "UNKNOWN")
        assert after["warning_threshold"] == .47 and after["low_threshold"] == .11
        assert operating_prediction(after) == after


def test_missing_high_cutoff_does_not_reinstate_the_noisy_low_warning_band():
    assert operating_prediction(raw(.8, high=None))["risk_level"] == "UNKNOWN"
    assert operating_prediction(raw(.05, high=None))["risk_level"] == "LOW"


def test_bad_scores_and_model_errors_never_become_low():
    for score in [math.nan, math.inf, -1, 2]:
        result = operating_prediction(raw(score))
        assert result["status"] == "error" and result["risk_level"] == "UNKNOWN"
    error = {"url": "https://example.org", "status": "unavailable", "message": "missing model"}
    assert operating_prediction(error) == error
