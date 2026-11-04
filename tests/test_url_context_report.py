import copy

import pytest

from evaluation.url_context_score import score
from scripts.evaluation.report_url_context import check_metrics, paired_bootstrap


def fixture():
    cases = [{"id": str(i), "url_id": str(i), "task": "url_only", "variant": "url_only", "group_id": str(i),
              "targets": {"url_risk": y, "message_behavior": None, "action_risk": None}}
             for i, y in enumerate([1, 1, 0, 0])]
    urls = [{"id": str(i), "source": "fixture", "tier": "silver"} for i in range(4)]
    records = []
    for c in cases:
        for arm in ("url_model", "llm_only", "llm_url"):
            outcome = "HIGH" if c["targets"]["url_risk"] else "LOW"
            records.append({"id": c["id"], "arm": arm, "repeat": 0 if arm == "url_model" else 1, "status": "ok",
                "outputs": {"url_risk": outcome, "message_behavior": "UNKNOWN", "action_risk": "UNKNOWN"}})
    return cases, urls, records


def test_independent_metric_check_rejects_fabricated_improvement():
    cases, urls, records = fixture()
    failed = next(r for r in records if r["id"] == "0" and r["arm"] == "llm_url")
    failed.update(status="error", error_code="TEST_ERROR", outputs={})
    saved = score(cases, urls, records, 1)["metrics"]["url_only"]["url_risk"]["by_repeat"]["llm_url"]["1"]
    lookup = {(r["id"], r["arm"], r["repeat"]): r for r in records}
    check_metrics(cases, lookup, "llm_url", 1, "url_risk", saved)
    assert saved["f1"] == pytest.approx(2/3) and saved["coverage"] == .75
    fabricated = copy.deepcopy(saved)
    fabricated["f1"] = 1
    with pytest.raises(AssertionError):
        check_metrics(cases, lookup, "llm_url", 1, "url_risk", fabricated)


def test_paired_bootstrap_zero_difference_for_identical_outputs():
    cases, _, records = fixture()
    lookup = {(r["id"], r["arm"], r["repeat"]): r for r in records}
    result = paired_bootstrap(cases, lookup, 1, "url_risk", draws=100)
    assert result["ci95_mean_delta_f1_pp"] == [0, 0]
    assert result["domain_groups"] == 4


def test_paired_bootstrap_retains_positive_errors_as_losses():
    cases, _, records = fixture()
    for r in records:
        if r["arm"] == "llm_url":
            r.update(status="error", error_code="TEST_ERROR", outputs={})
    lookup = {(r["id"], r["arm"], r["repeat"]): r for r in records}
    result = paired_bootstrap(cases, lookup, 1, "url_risk", draws=100)
    assert result["ci95_mean_delta_f1_pp"] == [-100, -100]
