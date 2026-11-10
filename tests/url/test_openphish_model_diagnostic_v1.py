import pytest

from evaluation.url.openphish_diagnostic import MODELS, analyze, prepare, score_cases, validate_cases


def fixtures(n=3):
    cases = [{"id": f"fixture-{i}", "url": f"https://fixture-{i}.test/"} for i in range(n)]
    policies = {name: {"fixed_0.5": .5, "historical_validation_fpr_5pct": .8} for name in MODELS}
    return cases, policies


def test_errors_and_invalid_scores_remain_unknown_in_all_case_denominator():
    cases, policies = fixtures()
    def handler(url):
        if "fixture-1" in url:
            raise ValueError("Preprocessing failure")
        return float("nan") if "fixture-2" in url else .9
    rows = score_cases(cases, {name: handler for name in MODELS})
    result, decisions = analyze(cases, rows, policies)
    for values in result.values():
        for m in values.values():
            assert m["alerts"] == 1 and m["unknown_errors"] == 2
            assert m["alert_rate_all_source_candidates"] == 1/3
            assert not {"precision", "f1", "accuracy", "false_positive_rate"} & set(m)
    assert sum(d["decision"] == "UNKNOWN" for d in decisions) == 20


def test_thresholds_are_supplied_not_chosen_from_case_scores_or_source_labels():
    cases, policies = fixtures()
    rows = score_cases(cases, {name: lambda _: .65 for name in MODELS})
    result, _ = analyze(cases, rows, policies)
    for values in result.values():
        assert values["fixed_0.5"]["alerts"] == 3
        assert values["historical_validation_fpr_5pct"]["alerts"] == 0
        assert values["historical_validation_fpr_5pct"]["threshold"] == .8


def test_missing_duplicate_and_unknown_model_rows_rejected():
    cases, policies = fixtures()
    rows = score_cases(cases, {name: lambda _: .8 for name in MODELS})
    for broken in [rows[:-1], rows[:-1] + [rows[0]], rows + [rows[0]]]:
        with pytest.raises(ValueError, match="Missing/duplicate"):
            analyze(cases, broken, policies)


def test_all_200_locked_cases_required_without_gold_promotion(tmp_path):
    cases = [{"id": f"fixture-{i}", "domain": f"fixture-{i}.test", "source_label": 1,
              "label_status": "external_source_provisional", "human_verified": False,
              "prospective_eligible": False} for i in range(200)]
    validate_cases(cases)
    with pytest.raises(ValueError, match="exactly all 200"):
        validate_cases(cases[:-1])
    cases[0]["human_verified"] = True
    with pytest.raises(ValueError, match="promote"):
        validate_cases(cases)
    out = tmp_path / "old"
    out.mkdir()
    with pytest.raises(ValueError, match="new output"):
        prepare(out)
