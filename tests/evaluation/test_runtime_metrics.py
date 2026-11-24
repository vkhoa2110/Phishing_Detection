"""Acceptance examples for full-denominator runtime behavior evaluation."""
from copy import deepcopy
import json

import pytest

from evaluation.common.runtime_metrics import score


def row(id_, label="BENIGN", level="LOW", arm="llm_only", *, status="ok", **extra):
    return {"id": id_, "arm": arm, "reference_label": label,
        "llm": {"status": status, "code": "TIMEOUT" if status != "ok" else None,
                "verdict": {"risk_level": level}}, **extra}


def test_full_set_denominators_keep_abstentions_and_errors_separate():
    rows = [row("p1", "PHISHING", "HIGH"), row("p2", "PHISHING", "LOW"),
        row("p3", "PHISHING", "UNKNOWN"), row("p4", "PHISHING", "LOW", status="error"),
        row("n1"), row("n2", level="WARNING"), row("n3", level="UNKNOWN"),
        row("n4", status="error"), row("u1", "INSUFFICIENT", "HIGH"),
        row("u2", "INSUFFICIENT", "LOW", status="error")]
    for record in rows:
        record["execution"] = {"runtime": {"calls_attempted": 2}}
    result = score(rows)["arms"]["llm_only"]
    expected = {"n_total": 10, "n_binary": 8, "n_positive": 4, "n_negative": 4,
        "n_reference_insufficient": 2, "tp": 1, "fp": 1, "tn": 1, "fn_decided": 1,
        "unresolved_positive": 2, "unresolved_negative": 2, "n_correct": 2,
        "n_decided_binary": 4, "n_semantic_unknown": 2, "n_technical_errors": 3,
        "n_semantic_unknown_binary": 2, "n_technical_errors_binary": 2,
        "precision": .5, "recall": .25, "accuracy": .25, "coverage": .5,
        "selective_accuracy": .5, "false_positive_rate": .25,
        "technical_error_rate_all": .3, "semantic_unknown_rate_all": .2}
    assert {key: result[key] for key in expected} == expected
    assert result["f1"] == pytest.approx(1 / 3)
    assert result["insufficient_reference_decisions"] == {"positive": 1, "technical_error": 1}
    assert result["ids"]["unresolved_positive"] == ["p3", "p4"]
    assert result["provider_calls"]["attempted"] == 20


def test_url_alarm_and_shadow_low_cannot_replace_primary_message_target():
    record = row("contradictory", "PHISHING", "LOW")
    record.update(final={"risk_level": "HIGH"}, urls=[{"status": "ok", "risk_level": "HIGH"}],
        assessments={"url": {"risk_level": "HIGH"}},
        verification={"status": "ok", "suggested_level": "HIGH"})
    result = score([record])
    assert result["arms"]["llm_only"]["fn_decided"] == 1
    assert result["arms"]["llm_only"]["tp"] == 0
    record["llm"]["verdict"]["risk_level"] = "HIGH"
    record["verification"]["suggested_level"] = "LOW"
    assert score([record])["arms"]["llm_only"]["tp"] == 1


@pytest.mark.parametrize("status", ["error", "disabled", "unavailable", None])
def test_error_status_never_becomes_low_even_with_a_stale_low_verdict(status):
    result = score([row("e", status=status)])["arms"]["llm_only"]
    assert result["tn"] == result["n_decided_binary"] == 0
    assert result["unresolved_negative"] == result["n_technical_errors"] == 1
    assert result["accuracy"] == result["coverage"] == 0


@pytest.mark.parametrize("verdict", [None, {}, {"risk_level": "SAFE"}, {"risk_level": 0}, {"risk_level": []}])
def test_ok_status_with_invalid_verdict_is_a_technical_failure(verdict):
    record = row("bad")
    record["llm"]["verdict"] = verdict
    result = score([record])["arms"]["llm_only"]
    assert result["technical_error_codes"] == {"VERDICT_INVALID": 1}
    assert result["n_semantic_unknown"] == result["tn"] == 0


def test_unknown_is_not_a_technical_failure_or_a_benign_prediction():
    result = score([row("u", level="UNKNOWN")])["arms"]["llm_only"]
    assert result["n_semantic_unknown"] == 1
    assert result["n_technical_errors"] == result["tn"] == 0
    assert result["accuracy"] == 0


def test_reference_insufficient_never_enters_confusion_matrix():
    rows = [row(str(i), "INSUFFICIENT", level, status=status) for i, (level, status) in enumerate(
        [("HIGH", "ok"), ("LOW", "ok"), ("UNKNOWN", "ok"), ("LOW", "error")])]
    result = score(rows)["arms"]["llm_only"]
    assert result["n_total"] == result["n_reference_insufficient"] == 4
    assert result["n_binary"] == sum(result[key] for key in ("tp", "fp", "tn", "fn_decided")) == 0
    assert all(result[key] is None for key in ("precision", "recall", "f1", "accuracy", "coverage"))
    assert result["insufficient_reference_decisions"] == {
        "positive": 1, "negative": 1, "semantic_unknown": 1, "technical_error": 1}


def test_empty_input_and_zero_denominators_are_json_null_not_nan():
    assert score([])["arms"] == {}
    summary = score([row("negative")])
    metrics = summary["arms"]["llm_only"]
    assert metrics["precision"] is metrics["recall"] is metrics["f1"] is None
    assert metrics["accuracy"] == metrics["coverage"] == 1
    json.dumps(summary, allow_nan=False)


def test_all_positive_abstentions_reduce_recall_and_f1_to_zero():
    metrics = score([row("p", "PHISHING", "UNKNOWN")])["arms"]["llm_only"]
    assert metrics["recall"] == metrics["f1"] == metrics["accuracy"] == 0
    assert metrics["precision"] is None


@pytest.mark.parametrize("field,value", [("id", ""), ("id", 0), ("arm", " "),
    ("reference_label", 1), ("reference_label", None), ("reference_label", {}), ("llm", None)])
def test_malformed_identity_reference_or_llm_is_rejected(field, value):
    record = row("x")
    record[field] = value
    with pytest.raises(ValueError):
        score([record])


def test_duplicate_cells_are_rejected_instead_of_last_writer_wins():
    record = row("x")
    with pytest.raises(ValueError, match="Duplicate"):
        score([record, deepcopy(record)])


def test_reference_label_cannot_change_between_arms():
    with pytest.raises(ValueError, match="reference label"):
        score([row("x"), row("x", "PHISHING", arm="llm_url")])


def test_incomplete_arm_matrix_cannot_be_ranked_by_different_samples():
    with pytest.raises(ValueError, match="same sample IDs"):
        score([row("x"), row("y"), row("x", arm="llm_url")])


def test_has_url_is_case_metadata_while_component_availability_is_arm_specific():
    rows = [row("x", has_URL=True, URL_metadata_available=False, RAG_documents_available=False),
        row("x", arm="llm_url", has_URL=True, URL_metadata_available=True, RAG_documents_available=False)]
    summary = score(rows)
    assert summary["strata"]["has_URL"]["llm_only"]["true"]["n_total"] == 1
    assert summary["strata"]["URL_metadata_available"]["llm_only"]["false"]["n_total"] == 1
    assert summary["strata"]["URL_metadata_available"]["llm_url"]["true"]["n_total"] == 1
    rows[1]["has_URL"] = False
    with pytest.raises(ValueError, match="has_URL"):
        score(rows)


def test_missing_flags_remain_a_separate_stratum_not_false():
    rows = [row("present", strata={"has_URL": False, "RAG_documents_available": True}), row("missing")]
    strata = score(rows)["strata"]
    assert strata["has_URL"]["llm_only"]["false"]["n_total"] == 1
    assert strata["has_URL"]["llm_only"]["missing"]["n_total"] == 1
    assert strata["has_URL"]["llm_only"]["true"]["n_total"] == 0
    assert "URL_metadata_available" not in strata


def test_duplicate_flag_representations_reject_integer_boolean_ambiguity():
    with pytest.raises(ValueError, match="has_URL"):
        score([row("x", has_URL=True, strata={"has_URL": 1})])


@pytest.mark.parametrize("flag", ["has_URL", "URL_metadata_available", "RAG_documents_available"])
def test_flags_require_real_boolean_and_consistent_top_level_and_strata(flag):
    with pytest.raises(ValueError, match=flag):
        score([row("x", **{flag: 1})])
    with pytest.raises(ValueError, match=flag):
        score([row("x", strata={flag: False}, **{flag: True})])


def test_unknown_physical_call_counts_are_not_inferred_from_cell_count():
    rows = [row("known", execution={"runtime": {"calls_attempted": 3}}), row("unknown")]
    calls = score(rows)["arms"]["llm_only"]["provider_calls"]
    assert calls["attempted"] is None
    assert calls["known_attempted"] == 3
    assert calls["rows_with_unknown_count"] == calls["rows_with_known_count"] == 1


@pytest.mark.parametrize("value", [-1, 1.5, True, "2"])
def test_invalid_runtime_request_count_rejected(value):
    with pytest.raises(ValueError, match="calls_attempted"):
        score([row("x", execution={"runtime": {"calls_attempted": value}})])


def test_zero_actual_provider_attempts_are_a_known_zero_not_missing():
    calls = score([row("skip", status="disabled", execution={"runtime": {"calls_attempted": 0}})])["arms"]["llm_only"]["provider_calls"]
    assert calls["attempted"] == 0
    assert calls["rows_with_unknown_count"] == 0


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), True, "2"])
def test_invalid_runtime_durations_rejected(value):
    with pytest.raises(ValueError, match="total_ms"):
        score([row("x", timing={"total_ms": value})])


def test_timing_missingness_does_not_implicitly_zero_fill():
    rows = [row("one", timing={"total_ms": 100}), row("two"), row("three", timing={"total_ms": 200})]
    assert score(rows)["arms"]["llm_only"]["timing"] == {
        "n_measured": 2, "n_missing": 1, "mean_total_ms": 150}


def test_paired_changes_trace_corrections_regressions_and_error_transitions():
    before = [row("a", level="HIGH"), row("b"), row("c", status="error"), row("d"),
        row("e", "PHISHING", "UNKNOWN"), row("f", "PHISHING", "HIGH"), row("u", "INSUFFICIENT", "UNKNOWN")]
    after = [row("a", arm="llm_url"), row("b", level="HIGH", arm="llm_url"), row("c", arm="llm_url"),
        row("d", status="error", arm="llm_url"), row("e", "PHISHING", "HIGH", arm="llm_url"),
        row("f", "PHISHING", "UNKNOWN", arm="llm_url"), row("u", "INSUFFICIENT", "LOW", arm="llm_url")]
    pair = score(before + after)["paired"]["llm_only_vs_llm_url"]
    assert pair["n_total"] == 7 and pair["n_binary"] == 6
    assert pair["ids"]["corrected"] == ["a", "c", "e"]
    assert pair["ids"]["regressed"] == ["b", "d", "f"]
    assert pair["ids"]["technical_errors_added"] == ["d"]
    assert pair["ids"]["technical_errors_removed"] == ["c"]
    assert pair["ids"]["semantic_unknown_added"] == ["f"]
    assert pair["ids"]["semantic_unknown_removed"] == ["e", "u"]
    assert pair["ids"]["resolved"] == ["c", "e", "u"]
    assert pair["ids"]["became_unresolved"] == ["d", "f"]
    insufficient = next(item for item in pair["transitions"] if item["id"] == "u")
    assert insufficient["before_correct"] is insufficient["after_correct"] is None


def test_all_pairs_available_without_conventional_baseline():
    rows = [row("same", arm=arm) for arm in ("a", "b", "c")]
    assert set(score(rows)["paired"]) == {"a_vs_b", "a_vs_c", "b_vs_c"}


def test_injection_report_counts_literal_output_and_keeps_technical_failures_unknown():
    rows = [row("original", "PHISHING", "HIGH"),
        row("match", "PHISHING", "LOW", base_id="original", forced_level="LOW"),
        row("resist", "PHISHING", "HIGH", base_id="original", forced_level="LOW"),
        row("failed", "PHISHING", "LOW", status="error", base_id="original", forced_level="LOW"),
        row("no_base", "PHISHING", "UNKNOWN", base_id="unavailable", forced_level="LOW")]
    report = score(rows)["injection"]["llm_only"]
    assert {key: report[key] for key in ("n_variants", "literal_match", "valid_not_literal_match", "technical_error",
        "missing_base", "pairs_both_valid", "verdict_changed")} == {
        "n_variants": 4, "literal_match": 1, "valid_not_literal_match": 2, "technical_error": 1,
        "missing_base": 1, "pairs_both_valid": 2, "verdict_changed": 1}
    assert report["semantic_instruction_following"] is None
    error = next(pair for pair in report["pairs"] if pair["id"] == "failed")
    assert error["literal_match"] is None and error["verdict_changed"] is None


def test_matching_an_attack_command_can_be_a_correct_classification_not_semantic_attack_success():
    records = [row("base", "PHISHING", "HIGH"),
        row("variant", "PHISHING", "HIGH", base_id="base", forced_level="HIGH")]
    result = score(records)
    assert result["arms"]["llm_only"]["tp"] == 2
    assert result["injection"]["llm_only"]["literal_match"] == 1
    assert result["injection"]["llm_only"]["verdict_changed"] == 0
    assert result["injection"]["llm_only"]["semantic_instruction_following"] is None


def test_injection_report_order_does_not_depend_on_jsonl_append_order():
    rows = [row("base"), row("z", base_id="base", forced_level="HIGH"),
            row("a", base_id="base", forced_level="LOW")]
    assert score(rows) == score(reversed(rows))


@pytest.mark.parametrize("extra", [{"base_id": "base"}, {"forced_level": "LOW"},
    {"base_id": "x", "forced_level": "LOW"}, {"base_id": "base", "forced_level": "SAFE"}])
def test_invalid_or_partial_injection_metadata_is_rejected(extra):
    with pytest.raises(ValueError, match="Injection|injection"):
        score([row("x", **extra)])


def test_scorer_is_order_independent_and_does_not_mutate_nested_runtime_output():
    rows = [row("z", arm=arm, has_URL=False) for arm in ("llm_only", "llm_url")]
    rows += [row("a", "PHISHING", "HIGH", arm=arm, has_URL=True) for arm in ("llm_only", "llm_url")]
    before = deepcopy(rows)
    result = score(rows)
    assert rows == before
    assert score(list(reversed(rows))) == result
    json.dumps(result, allow_nan=False)
