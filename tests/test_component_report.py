import copy

import pytest

from evaluation import component_ablation as runner
from scripts.evaluation import report_components as reporting


def fixture(tmp_path):
    cases = [{"id": "S" + str(i), "dataset": "sms", "group_id": "sms:" + str(i),
              "targets": {"url_risk": None, "message_behavior": label, "action_risk": None}}
             for i, label in enumerate((1, 0, None))]
    cases += [{"id": "C" + str(label), "dataset": "url_context", "group_id": "url:" + str(label), "variant": "fixture",
               "targets": {t: label for t in runner.TARGETS}} for label in (1, 0)]
    prepared = {c["id"]: {"urls": [] if c["dataset"] == "sms" else [{"risk_level": "HIGH"}],
                 "retrieval": {"sources": []}, "reputation": []} for c in cases}
    records = [{"id": c["id"], "arm": a, "status": "ok", "outputs": {
        t: "UNKNOWN" if c["targets"][t] is None else "HIGH" if c["targets"][t] else "LOW" for t in runner.TARGETS},
        "usage": {}, "elapsed_ms": 1} for c in cases for a in runner.ARMS]
    runner.write_json(tmp_path / "execution.json", {})
    runner.write_json(tmp_path / "prepared.json", prepared)
    config = {"provider_call_budget": len(records), "scope": "unit_test_not_actual_experiment"}
    summary = runner.export(tmp_path, config, cases, prepared, records,
                            [{"id": r["id"], "arm": r["arm"]} for r in records], {"stop_reason": "all_calls_completed"})
    return cases, prepared, records, runner.lookup_records(cases, records), summary


def test_bootstrap_keeps_equal_predictions_equal_and_references_unknown_separate(tmp_path):
    cases, prepared, records, lookup, summary = fixture(tmp_path)
    extra = reporting.augment(cases, prepared, lookup, summary)
    for dataset, targets in extra["paired"].items():
        for target, comparisons in targets.items():
            for comparison in comparisons.values():
                assert comparison["counts"]["improved"] == comparison["counts"]["regressed"] == 0
                assert comparison["bootstrap"]["ci95_delta_f1_pp"] == [0.0, 0.0]
    assert summary["metrics"]["sms"]["message_behavior"]["llm_only"]["reference_unknown_count"] == 1
    assert extra["url_model"]["url_context"]["false_positive_rate"] == 1


def test_independent_sklearn_metric_checker_rejects_a_fabricated_component_score(tmp_path):
    cases, prepared, records, lookup, summary = fixture(tmp_path)
    subset = [c for c in cases if c["dataset"] == "sms"]
    triple = {(id_, arm, 1): r for (id_, arm), r in lookup.items()}
    saved = copy.deepcopy(summary["metrics"]["sms"]["message_behavior"]["llm_only"])
    reporting.check_metrics(subset, triple, "llm_only", 1, "message_behavior", saved)
    saved["f1"] = .123
    with pytest.raises(AssertionError):
        reporting.check_metrics(subset, triple, "llm_only", 1, "message_behavior", saved)


def test_negative_change_bootstrap_is_not_forced_positive(tmp_path):
    cases, prepared, records, lookup, summary = fixture(tmp_path)
    for c in cases:
        if c["dataset"] == "url_context":
            lookup[(c["id"], "llm_url_rag")]["outputs"]["url_risk"] = "LOW" if c["targets"]["url_risk"] else "HIGH"
    result = reporting.paired_bootstrap([c for c in cases if c["dataset"] == "url_context"], lookup, "url_risk", "llm_only", "llm_url_rag")
    assert result["ci95_delta_f1_pp"] == [-100.0, -100.0]
