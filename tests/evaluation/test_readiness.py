from evaluation.messages.readiness import gate


def metrics(**changes):
    return {"accuracy": .8, "coverage": .95, "recall": .9, "technical_errors": 2, "fp": 6, **changes}


def test_false_alarms_lost_to_errors_do_not_count_as_a_quality_improvement():
    result = gate(metrics(), metrics(accuracy=.79, coverage=.85, technical_errors=6, fp=2),
        {"alarm_to_low": 0}, human_gold=True, positives=30, positive_url_cases=20)
    assert not result["eligible_to_claim_improvement"]
    assert "false_alarm_reduction_has_real_correction" in result["failed"]
    assert "technical_errors_not_higher" in result["failed"]


def test_majority_class_accuracy_cannot_hide_lost_positive_recall():
    result = gate(metrics(), metrics(accuracy=.93, coverage=1., recall=0., technical_errors=0, fp=0),
        {"alarm_to_low": 6}, human_gold=True, positives=30, positive_url_cases=20)
    assert result["checks"]["full_set_accuracy_not_lower"]
    assert not result["checks"]["recall_not_lower"]
    assert not result["eligible_to_claim_improvement"]


def test_ai_references_and_missing_url_positives_prevent_an_independent_claim():
    result = gate(metrics(), metrics(accuracy=.85, fp=3), {"alarm_to_low": 3},
                  human_gold=False, positives=4, positive_url_cases=0)
    assert not result["eligible_to_claim_improvement"] and not result["automatic_deployment"]
    assert "independent_human_reference" in result["failed"]
