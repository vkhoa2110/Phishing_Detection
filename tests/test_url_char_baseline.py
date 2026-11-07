import json

import numpy as np
import pandas as pd
import pytest

from evaluation.url_char_baseline import (CONFIG, POLICIES, check_lock, compare,
                                          fit_training_only, prepare)
from evaluation.url_calibration import fold_for


def frames():
    def frame(split, count):
        return pd.DataFrame([{"id": f"{split}-{i}", "split": split, "labels": i % 2,
            "model_input": f"[DOMAIN] {split}{i}.vn [PATH] /{'login' if i % 2 else 'news'}",
            "domain_group": f"{split}{i}.vn", "source": "positive" if i % 2 else "benign",
            "tier": "silver", "xgb_score": (i % 10) / 10, "char_score": (i % 7) / 7}
            for i in range(count)])
    return {split: frame(split, 100 if split == "val" else 20) for split in ["train", "val", "test"]}


def test_vectorizer_and_classifier_fit_only_training_rows():
    first = frames()
    model, info = fit_training_only(first)
    changed = frames()
    for split in ["val", "test"]:
        changed[split]["model_input"] = "ZZZZZZZZZZZ"
        changed[split]["labels"] = 1 - changed[split].labels
    updated, other = fit_training_only(changed)
    assert "zzz" not in model["tfidf"].vocabulary_
    assert info["vocabulary_sha256"] == other["vocabulary_sha256"]
    assert info["idf_sha256"] == other["idf_sha256"]
    np.testing.assert_array_equal(model["classifier"].coef_, updated["classifier"].coef_)


@pytest.mark.parametrize("field", ["id", "model_input", "domain_group"])
def test_train_evaluation_overlap_is_rejected(field):
    data = frames()
    data["val"].loc[0, field] = data["train"].iloc[0][field]
    with pytest.raises(ValueError, match="overlap"):
        fit_training_only(data)


def test_no_test_labels_or_scores_influence_any_threshold():
    data = frames()
    before, _ = compare(data["val"], data["test"])
    changed = data["test"].copy()
    changed["labels"] = 1 - changed.labels
    changed["char_score"], changed["xgb_score"] = 1., 0.
    after, _ = compare(data["val"], changed)
    for model in before:
        for policy in POLICIES:
            assert before[model][policy]["full_validation_threshold"] == after[model][policy]["full_validation_threshold"]
            assert before[model][policy]["folds"] == after[model][policy]["folds"]


def test_crossfit_heldout_fold_does_not_influence_its_cutoff():
    data = frames()
    before, decisions = compare(data["val"], data["test"])
    changed = data["val"].copy()
    mask = changed.domain_group.map(fold_for).eq(2)
    changed.loc[mask, "labels"] = 1 - changed.loc[mask, "labels"]
    changed.loc[mask, ["char_score", "xgb_score"]] = 1.
    after, _ = compare(changed, data["test"])
    for model in before:
        for policy in POLICIES:
            assert before[model][policy]["folds"][2]["threshold"] == after[model][policy]["folds"][2]["threshold"]
    assert not decisions.loc[decisions.split.eq("val_domain_crossfit")].groupby(["model", "policy", "id"]).size().gt(1).any()
    assert before["Char_TFIDF_LogReg"]["fixed_0.5"]["validation_domain_crossfit"]["source:positive"]["f1"] is None


def test_existing_output_is_preserved_before_loading_or_fitting(tmp_path):
    path = tmp_path / "old"
    path.mkdir()
    (path / "execution.json").write_text('{"old":true}')
    with pytest.raises(ValueError, match="new output"):
        prepare(path)
    assert (path / "execution.json").read_text() == '{"old":true}'


def test_source_drift_prevents_fit(tmp_path):
    source = tmp_path / "source.py"
    source.write_text("changed")
    (tmp_path / "execution.json").write_text(json.dumps({"input_hashes": {str(source): "0" * 64},
        "configuration": CONFIG, "policies": POLICIES}))
    with pytest.raises(ValueError, match="Registered input/source changed"):
        check_lock(tmp_path)
