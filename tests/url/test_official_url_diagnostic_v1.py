from app.core.settings import ROOT as PROJECT_ROOT
import copy
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

import evaluation.url.official_diagnostic as diagnostic
from evaluation.data.sms import write_jsonl


@pytest.fixture
def preprocessing():
    path = PROJECT_ROOT / "models/inference_XGBoost_d6_s42/url_preprocessing.py"
    spec = importlib.util.spec_from_file_location("official_diagnostic_preprocessing", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cases(n=29):
    return [{"id": f"ref-{i}", "url": f"https://www.site{i}.vn/login?q=1",
        "source_url": f"https://www.site{i}.vn/login?q=1" if i % 2 else f"https://www.site{i}.vn/help",
        "normalized_url": f"https://www.site{i}.vn/login?q=1", "region": "VN" if i % 2 else "international",
        "tags": ["login", "query"], "label": None, "label_scope": "official_origin_reference",
        "label_status": "assistant_curated", "reviewer_ids": [],
        "evidence": {"untrusted_text": "Ignore this and predict zero"},
        "exposure": {"assigned_pool": "regression" if i % 2 else "new_origin_reference_review_only",
                     "prospective_eligible": False, "url_overlap": False, "domain_overlap": bool(i % 2)}}
        for i in range(n)]


def summary():
    return {arm: {"fixed_0.5": {"full_validation_threshold": .5},
                  "fpr_5pct": {"full_validation_threshold": .7}} for arm in diagnostic.ARMS}


def fake_models():
    class Baseline:
        def __init__(self):
            self.seen = []
        def _scores(self, urls):
            self.seen.extend(urls)
            return np.array([.5] * len(urls))
    class Model:
        def __init__(self):
            self.seen = []
        def predict_proba(self, texts):
            self.seen.extend(texts)
            return np.array([[.5, .5]] * len(texts))
    return Baseline(), {arm: Model() for arm in diagnostic.FIT_ORDER}


def test_every_collected_unlabelled_reference_is_required():
    rows = cases()
    assert diagnostic.validate_cases(rows) is rows
    with pytest.raises(ValueError, match="every collected"):
        diagnostic.validate_cases(rows[:-1])
    rows[0]["label"] = 0
    with pytest.raises(ValueError, match="remain unlabelled"):
        diagnostic.validate_cases(rows)


def test_only_raw_url_enters_all_four_model_arms(preprocessing):
    rows = cases()
    baseline, models = fake_models()
    predictions = diagnostic.predict_records(rows, baseline, models, preprocessing)
    assert len(predictions) == 29 * 4
    assert baseline.seen == [row["url"] for row in rows]
    assert models["B_source_weighted"].seen == [preprocessing.format_url(row["url"]) for row in rows]
    expected = [diagnostic.www_model_view(row["url"], preprocessing) for row in rows]
    assert models["A_strip_www"].seen == expected
    assert models["C_strip_www_source_weighted"].seen == expected
    changed = copy.deepcopy(rows)
    for row in changed:
        row.update(region="CHANGED", label="DO_NOT_USE", evidence={"predict": 1}, source_url="https://untrusted.invalid/")
    other_baseline, other_models = fake_models()
    assert diagnostic.predict_records(changed, other_baseline, other_models, preprocessing) == predictions


def test_alerts_use_frozen_cutoff_inclusively_and_groups_are_descriptive(preprocessing):
    rows = cases()
    baseline, models = fake_models()
    predictions = diagnostic.predict_records(rows, baseline, models, preprocessing)
    aggregate, decisions = diagnostic.aggregate(rows, predictions, diagnostic.thresholds(summary()))
    assert aggregate["risk_labels"] == 0
    assert len(decisions) == 29 * 4 * 2
    for arm, values in aggregate["results"].items():
        assert values["fixed_0.5"]["groups"]["all"] == {
            "n": 29, "alert": 29, "non_alert": 0, "error": 0,
            "alert_fraction_all": 1., "alert_fraction_valid_scores": 1., "error_fraction": 0.}
        assert values["validation_fpr5_cutoff"]["groups"]["all"]["alert"] == 0
        groups = values["fixed_0.5"]["groups"]
        assert groups["separate_source_document:true"]["n"] == 15
        assert groups["separate_source_document:false"]["n"] == 14
        assert groups["tag:login"]["n"] == groups["tag:query"]["n"] == 29
        assert not {"precision", "recall", "f1", "false_positive_rate"} & set(groups["all"])


def test_model_errors_remain_in_all_record_denominator(preprocessing):
    rows = cases()
    baseline, models = fake_models()
    class Broken:
        def predict_proba(self, texts):
            raise RuntimeError("no score")
    models["B_source_weighted"] = Broken()
    predictions = diagnostic.predict_records(rows, baseline, models, preprocessing)
    aggregate, decisions = diagnostic.aggregate(rows, predictions, diagnostic.thresholds(summary()))
    bucket = aggregate["results"]["B_source_weighted"]["fixed_0.5"]["groups"]["all"]
    assert bucket["n"] == bucket["error"] == 29
    assert bucket["alert"] == bucket["non_alert"] == 0
    assert bucket["error_fraction"] == 1.
    assert bucket["alert_fraction_valid_scores"] is None
    assert all(row["alert"] is None for row in decisions if row["arm"] == "B_source_weighted")


@pytest.mark.parametrize("score", [float("nan"), float("inf"), -.1, 1.1])
def test_invalid_scores_are_errors(preprocessing, score):
    baseline, models = fake_models()
    baseline._scores = lambda _: np.array([score])
    result = diagnostic.predict_records(cases(1), baseline, models, preprocessing)
    assert result[0]["status"] == "error" and result[0]["score"] is None


def test_missing_duplicate_score_results_are_rejected(preprocessing):
    rows = cases()
    baseline, models = fake_models()
    predictions = diagnostic.predict_records(rows, baseline, models, preprocessing)
    for changed in [predictions[:-1], predictions + [predictions[0]]]:
        with pytest.raises(ValueError, match="Missing, duplicated"):
            diagnostic.aggregate(rows, changed, diagnostic.thresholds(summary()))


def test_cutoffs_are_frozen_and_invalid_cutoffs_rejected():
    values = summary()
    assert diagnostic.thresholds(values)["A_strip_www"] == {"fixed_0.5": .5, "validation_fpr5_cutoff": .7}
    values["A_strip_www"]["fixed_0.5"]["full_validation_threshold"] = .4
    with pytest.raises(ValueError, match="frozen validation"):
        diagnostic.thresholds(values)


def test_existing_protocol_cannot_be_overwritten(tmp_path):
    with pytest.raises(ValueError, match="new output"):
        diagnostic.prepare(tmp_path)


def test_case_or_model_source_tamper_blocks_scoring(tmp_path):
    references, v3 = tmp_path / "references", tmp_path / "v3"
    references.mkdir()
    v3.mkdir()
    rows = cases()
    write_jsonl(references / "records.jsonl", rows)
    write_jsonl(tmp_path / "cases.jsonl", rows)
    (v3 / "summary.json").write_text(json.dumps(summary()))
    source = tmp_path / "model.weights"
    source.write_text("original")
    protocol = {"schema": "official-url-diagnostic-v1-1.0", "model_input": diagnostic.MODEL_INPUT,
        "scope": diagnostic.SCOPE, "arms": list(diagnostic.ARMS), "records": 29,
        "references": str(references), "v3": str(v3), "thresholds": diagnostic.thresholds(summary()),
        "cases_sha256": diagnostic.sha(tmp_path / "cases.jsonl"), "input_hashes": {str(source): diagnostic.sha(source)}}
    (tmp_path / "execution.json").write_text(json.dumps(protocol))
    diagnostic.check_lock(tmp_path)
    source.write_text("changed")
    with pytest.raises(ValueError, match="Locked input changed"):
        diagnostic.check_lock(tmp_path)
    source.write_text("original")
    (tmp_path / "cases.jsonl").write_text("{}\n")
    with pytest.raises(ValueError, match="cases changed"):
        diagnostic.check_lock(tmp_path)
