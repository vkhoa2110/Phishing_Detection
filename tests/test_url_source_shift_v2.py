import json

import numpy as np
import pandas as pd
import pytest

from evaluation.url_source_shift_v2 import (CONFIG, FIT_ORDER, POSITIVE_SOURCES, THRESHOLD,
    check_lock, exclusion_training, fit_training, majority_source, prepare, run,
    source_metrics, validate_frames)


def frames():
    result = {}
    sources = ["benign_a", "benign_b", *POSITIVE_SOURCES]
    for split in ["train", "val"]:
        rows = []
        for source in sources:
            for i in range(8):
                label = int(source in POSITIVE_SOURCES)
                rows.append({"id": f"{split}-{source}-{i}", "split": split, "labels": label,
                    "source": source, "tier": "silver", "domain_group": f"{split}-{source}-{i}.vn",
                    "model_input": f"[DOMAIN] {split}-{source}-{i}.vn [PATH] /{'login' if label else 'news'}",
                    "v2_input": f"{split}-{source}-{i}.vn/", "url": f"{split}-{source}-{i}.vn"})
        result[split] = pd.DataFrame(rows)
    return result


def test_exact_five_fits_and_fixed_v1_configuration():
    from evaluation.url_char_baseline import CONFIG as baseline
    assert CONFIG == baseline
    assert len(FIT_ORDER) == 5
    assert THRESHOLD == .5


def test_no_test_frame_is_accepted():
    data = frames()
    validate_frames(data)
    data["test"] = data["val"].copy()
    with pytest.raises(ValueError, match="Only train/validation"):
        validate_frames(data)


@pytest.mark.parametrize("source", POSITIVE_SOURCES)
def test_exclusion_preserves_all_negatives_and_other_positives(source):
    train = frames()["train"]
    selected = exclusion_training(train, source)
    expected = train.loc[~(train.labels.eq(1) & train.source.eq(source))]
    assert selected.id.tolist() == expected.id.tolist()
    assert set(selected.loc[selected.labels.eq(0), "id"]) == set(train.loc[train.labels.eq(0), "id"])
    model, info = fit_training(selected, "labels")
    # These source-specific ngrams occur solely in excluded positive rows.
    marker = {"chongluadao": "onglu", "openphish": "enphi", "tinnhiemmang": "emmang"}[source]
    if len(marker) <= 5:
        assert marker not in model["tfidf"].vocabulary_
    assert info["train_n"] == len(expected)
    assert "1:" + source not in info["train_source_by_label"]


def test_validation_text_labels_and_sources_never_enter_fit():
    data = frames()
    selected = data["train"].loc[data["train"].labels.eq(1)]
    first, info = fit_training(selected, "source")
    data["val"]["model_input"] = "ZZZZUNSEEN"
    data["val"]["source"] = "invented"
    data["val"]["labels"] = 1 - data["val"].labels
    second, other = fit_training(data["train"].loc[data["train"].labels.eq(1)], "source")
    for key in ["vocabulary_sha256", "idf_sha256", "coefficient_sha256"]:
        assert info[key] == other[key]
    assert "zzz" not in first["tfidf"].vocabulary_
    np.testing.assert_array_equal(first["classifier"].coef_, second["classifier"].coef_)


def test_source_majority_baseline_uses_training_counts_and_deterministic_tie():
    train = pd.DataFrame({"source": ["b", "a", "b", "a"]})
    assert majority_source(train) == "a"
    m = source_metrics(["a", "b", "b", "b"], ["a"] * 4, ["a", "b"])
    assert m["accuracy"] == .25
    assert m["balanced_accuracy"] == .5
    assert m["macro_f1"] == .2
    assert m["confusion_rows_reference_columns_prediction"] == [[1, 0], [3, 0]]


def test_validation_rows_rejected_for_fit():
    with pytest.raises(ValueError, match="training-only"):
        fit_training(frames()["val"], "source")


def test_no_overwrite_or_refit_and_source_drift_rejected(tmp_path):
    out = tmp_path / "run"
    out.mkdir()
    with pytest.raises(ValueError, match="new output"):
        prepare(out)
    source = tmp_path / "changed.py"
    source.write_text("new")
    protocol = {"configuration": CONFIG, "fit_order": FIT_ORDER, "URL_threshold": THRESHOLD,
        "positive_sources": POSITIVE_SOURCES, "input_hashes": {str(source): "0" * 64}}
    (out / "execution.json").write_text(json.dumps(protocol))
    with pytest.raises(ValueError, match="source/input changed"):
        check_lock(out)
    protocol["input_hashes"] = {}
    (out / "execution.json").write_text(json.dumps(protocol))
    (out / "fit_started.json").write_text("{}")
    with pytest.raises(ValueError, match="already started"):
        run(out)
