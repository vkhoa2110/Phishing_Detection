import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from evaluation.url_calibration import fold_for
from evaluation.url_source_robust_v3 import (ARMS, CONFIG, FIT_ORDER, GATES, POLICIES,
    REPRESENTATION, WEIGHTING, add_views, check_lock, evaluate, failures, fit_arm,
    export_research_model, load_research_model, prepare, run, source_weights, www_model_view)


@pytest.fixture
def preprocessing():
    path = Path(__file__).resolve().parents[1] / "models/inference_XGBoost_d6_s42/url_preprocessing.py"
    spec = importlib.util.spec_from_file_location("test_robust_preprocessing", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("url,expected", [
    ("https://WWW.Example.COM:443/Login?q=WWW.a#www.f", "[DOMAIN] Example.COM:443 [PATH] /Login?q=WWW.a#www.f"),
    ("https://name:www.password@WWW.Example.COM:443/www.path?q=www.q#www.f", "[DOMAIN] name:www.password@Example.COM:443 [PATH] /www.path?q=www.q#www.f"),
    ("https://www.user:pass@example.com/www.path", "[DOMAIN] www.user:pass@example.com [PATH] /www.path"),
    ("https://www.user@www.www.Example.COM:8443/a", "[DOMAIN] www.user@www.Example.COM:8443 [PATH] /a"),
    ("//user:pass@[2001:db8::1]:8080/www.a?www.b#www.c", "[IPv6] user:pass@[2001:db8::1]:8080 [PATH] /www.a?www.b#www.c"),
    ("https://www.127.0.0.1/a", "[DOMAIN] 127.0.0.1 [PATH] /a"),
    ("www.example.com./", "[DOMAIN] example.com. [PATH] /"),
    ("www.example.com/[PATH]?q=[DOMAIN]#[IP]", "[DOMAIN] example.com [PATH] /[PATH]?q=[DOMAIN]#[IP]"),
    ("https://awww.example.com/www.example.com", "[DOMAIN] awww.example.com [PATH] /www.example.com"),
])
def test_only_one_hostname_www_prefix_is_removed(preprocessing, url, expected):
    assert www_model_view(url, preprocessing) == expected


def frames(preprocessing):
    result = {}
    for split, n in [("train", 40), ("val", 100)]:
        rows = []
        for i in range(n):
            url = f"https://{'www.' if i % 3 else ''}{split}{i}.vn/{'otp' if i % 2 else 'news'}"
            rows.append({"id": f"{split}-{i}", "split": split, "url": url, "labels": i % 2,
                "model_input": preprocessing.format_url(url), "domain_group": f"{split}{i}.vn",
                "source": f"source{i % 5}", "tier": "silver",
                **{settings["field"]: (i % (7 + index)) / (7 + index) for index, settings in enumerate(ARMS.values())}})
        result[split] = pd.DataFrame(rows)
    add_views(result, preprocessing)
    return result


def test_weights_equalize_label_and_source_mass_without_double_balancing(preprocessing):
    train = frames(preprocessing)["train"].iloc[:23].copy()
    weights, audit = source_weights(train)
    assert np.isclose(weights.sum(), len(train))
    for label, group in train.groupby("labels"):
        assert np.isclose(weights[train.labels.eq(label)].sum(), len(train) / 2)
        k = group.source.nunique()
        for source in group.source.unique():
            mask = train.labels.eq(label) & train.source.eq(source)
            assert np.isclose(weights[mask].sum(), len(train) / (2 * k))
    model, metadata = fit_arm(frames(preprocessing), "B_source_weighted")
    assert model["classifier"].class_weight is None
    assert metadata["source_weighting"]["class_weight"] is None
    assert audit["learned_from"] == "train labels/sources/counts only"


@pytest.mark.parametrize("arm", FIT_ORDER)
def test_validation_text_labels_sources_do_not_change_learned_parameters(preprocessing, arm):
    before = frames(preprocessing)
    model, metadata = fit_arm(before, arm)
    changed = frames(preprocessing)
    changed["val"]["v3_input"] = "NEVERSEENTOKENZZZZ"
    changed["val"]["model_input"] = "NEVERSEENTOKENZZZZ"
    changed["val"]["labels"] = 1 - changed["val"].labels
    changed["val"]["source"] = "NEW_SOURCE"
    other, info = fit_arm(changed, arm)
    for field in ["vocabulary_sha256", "idf_sha256", "coefficient_sha256", "source_weighting"]:
        assert metadata[field] == info[field]
    assert "zzz" not in model["tfidf"].vocabulary_
    np.testing.assert_array_equal(model["classifier"].coef_, other["classifier"].coef_)


def test_weighting_does_not_change_vocabulary_or_idf(preprocessing):
    data = frames(preprocessing)
    a, info_a = fit_arm(data, "A_strip_www")
    c, info_c = fit_arm(data, "C_strip_www_source_weighted")
    for field in ["vocabulary_sha256", "idf_sha256"]:
        assert info_a[field] == info_c[field]
    assert a["classifier"].class_weight == "balanced"
    assert c["classifier"].class_weight is None


def test_collision_is_reported_without_merging_relabeling_or_changing_raw_identity(preprocessing):
    data = frames(preprocessing)
    data["train"].loc[0, ["url", "domain_group"]] = ["https://www.shared.vn/a", "shared.vn"]
    data["train"].loc[1, ["url", "domain_group"]] = ["https://shared.vn/a", "shared.vn"]
    data["train"]["model_input"] = data["train"].url.map(preprocessing.format_url)
    identities = data["train"][["id", "url", "labels", "domain_group"]].copy()
    audit = add_views(data, preprocessing)
    pd.testing.assert_frame_equal(data["train"][identities.columns], identities)
    assert audit["train"]["colliding_views"] == 1
    assert audit["train"]["conflicting_label_views"] == 1
    assert audit["train"]["rows_in_conflicting_views"] == 2
    assert audit["train"]["rows_removed_or_relabeled"] == 0


@pytest.mark.parametrize("field", ["id", "model_input", "v3_input", "domain_group"])
def test_train_validation_overlap_is_rejected(preprocessing, field):
    data = frames(preprocessing)
    data["val"].loc[0, field] = data["train"].iloc[0][field]
    with pytest.raises(ValueError, match="overlap"):
        fit_arm(data, "A_strip_www")


def test_heldout_scores_labels_sources_do_not_set_heldout_cutoff(preprocessing):
    data = frames(preprocessing)["val"]
    before, rows = evaluate(data)
    changed = data.copy()
    mask = changed.domain_group.map(fold_for).eq(2)
    changed.loc[mask, [settings["field"] for settings in ARMS.values()]] = 1.
    changed.loc[mask, "labels"] = 1 - changed.loc[mask].labels
    changed.loc[mask, "source"] = "CHANGED"
    after, _ = evaluate(changed)
    for family in before:
        for policy in POLICIES:
            assert before[family][policy]["folds"][2]["threshold"] == after[family][policy]["folds"][2]["threshold"]
    assert len(rows) == len(data) * 4 * 2
    assert not rows.groupby(["model", "policy", "id"]).size().gt(1).any()
    assert failures(data, rows)["char_v1_baseline/fixed_0.5"]["regressed_vs_baseline_ids"] == []


def test_exact_v1_configuration_and_fixed_three_arm_plan():
    from evaluation.url_char_baseline import CONFIG as v1
    assert CONFIG == v1
    assert len(FIT_ORDER) == 3
    assert POLICIES == {"fixed_0.5": None, "fpr_5pct": .05}
    assert ARMS["A_strip_www"]["source_weighted"] is False
    assert ARMS["B_source_weighted"]["strip_www"] is False
    assert ARMS["C_strip_www_source_weighted"]["strip_www"] is True


def test_protocol_is_not_overwritten_and_changed_source_or_repeat_fit_rejected(tmp_path):
    with pytest.raises(ValueError, match="new output"):
        prepare(tmp_path)
    protocol = {"configuration": CONFIG, "arms": ARMS, "fit_order": FIT_ORDER,
                "policies": POLICIES, "representation": REPRESENTATION,
                "weighting": WEIGHTING, "research_gates": GATES, "input_hashes": {}}
    (tmp_path / "execution.json").write_text(json.dumps(protocol))
    check_lock(tmp_path)
    (tmp_path / "fit_started.json").write_text("{}")
    with pytest.raises(ValueError, match="already started"):
        run(tmp_path)
    source = tmp_path / "source.py"
    source.write_text("changed")
    protocol["input_hashes"] = {str(source): "0" * 64}
    (tmp_path / "execution.json").write_text(json.dumps(protocol))
    with pytest.raises(ValueError, match="source/input changed"):
        check_lock(tmp_path)


def test_export_uses_original_fit_and_reconstructs_exact_scores_then_rejects_tamper(tmp_path, preprocessing):
    data = frames(preprocessing)
    model, info = fit_arm(data, "C_strip_www_source_weighted")
    (tmp_path / "execution.json").write_text("{}")
    parity = export_research_model(tmp_path, "C_strip_www_source_weighted", model, data["val"].v3_input)
    directory = tmp_path / "research_models/C_strip_www_source_weighted"
    replay = load_research_model(directory)
    np.testing.assert_array_equal(model.predict_proba(data["val"].v3_input), replay.predict_proba(data["val"].v3_input))
    assert parity == {"validation_rows": 100, "all_scores_bitwise_match": True, "new_fits_for_export": 0}
    (directory / "vocabulary.json").write_text("{}")
    with pytest.raises(ValueError, match="file hash changed"):
        load_research_model(directory)
