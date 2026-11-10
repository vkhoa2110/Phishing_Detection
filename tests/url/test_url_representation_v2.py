from app.core.settings import ROOT as PROJECT_ROOT
import importlib.util
import json
from pathlib import Path
from urllib.parse import urlsplit

import numpy as np
import pandas as pd
import pytest

from evaluation.url.representation import CONFIG, POLICIES, REPRESENTATION, baseline_scores, check_lock, evaluate, fit_training_only, load_frames, marker_free, prepare, run
from evaluation.url.calibration import fold_for


@pytest.fixture
def preprocessing():
    path = PROJECT_ROOT / "models/inference_XGBoost_d6_s42/url_preprocessing.py"
    spec = importlib.util.spec_from_file_location("test_representation_preprocessing", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("url,expected", [
    ("https://Example.COM:443/Login?q=OTP#Section", "Example.COM:443/Login?q=OTP#Section"),
    ("example.com", "example.com"),
    ("//[2001:db8::1]:8080/a?x=1#frag", "[2001:db8::1]:8080/a?x=1#frag"),
    ("https://example.com/[PATH]?q=[DOMAIN]#[IP]", "example.com/[PATH]?q=[DOMAIN]#[IP]"),
])
def test_marker_removal_preserves_real_url_parts_and_literal_marker_text(preprocessing, url, expected):
    assert marker_free(url, preprocessing) == expected


def frames():
    result = {}
    for split, n in [("train", 30), ("val", 100)]:
        result[split] = pd.DataFrame([{"id": f"{split}-{i}", "split": split, "labels": i % 2,
            "model_input": f"[DOMAIN] {split}{i}.vn [PATH] /{'otp' if i % 2 else 'news'}",
            "v2_input": f"{split}{i}.vn/{'otp' if i % 2 else 'news'}",
            "domain_group": f"{split}{i}.vn", "source": "threat" if i % 2 else "benign",
            "tier": "silver", "baseline_score": (i % 10) / 10, "v2_score": (i % 7) / 7}
            for i in range(n)])
    return result


def test_fit_never_learns_validation_text_or_labels():
    before = frames()
    model, info = fit_training_only(before)
    changed = frames()
    changed["val"]["v2_input"] = "NEVERSEENTOKENZZZZ"
    changed["val"]["labels"] = 1 - changed["val"].labels
    updated, other = fit_training_only(changed)
    for field in ["vocabulary_sha256", "idf_sha256", "coefficient_sha256"]:
        assert info[field] == other[field]
    assert "zzz" not in model["tfidf"].vocabulary_
    np.testing.assert_array_equal(model["classifier"].coef_, updated["classifier"].coef_)


@pytest.mark.parametrize("field", ["id", "model_input", "v2_input", "domain_group"])
def test_train_validation_overlap_rejected(field):
    data = frames()
    data["val"].loc[0, field] = data["train"].iloc[0][field]
    with pytest.raises(ValueError, match="overlap"):
        fit_training_only(data)


def test_heldout_domain_scores_and_labels_do_not_influence_its_cutoff():
    frame = frames()["val"]
    before, rows = evaluate(frame)
    mask = frame.domain_group.map(fold_for).eq(2)
    changed = frame.copy()
    changed.loc[mask, ["baseline_score", "v2_score"]] = 1.
    changed.loc[mask, "labels"] = 1 - changed.loc[mask].labels
    after, _ = evaluate(changed)
    for family in before:
        for policy in POLICIES:
            assert before[family][policy]["folds"][2]["threshold"] == after[family][policy]["folds"][2]["threshold"]
        assert before[family]["fixed_0.5"]["validation_domain_crossfit"]["source:threat"]["f1"] is None
    assert not rows.groupby(["model", "policy", "id"]).size().gt(1).any()


def test_configuration_is_exact_v1_except_representation():
    from evaluation.url.character_baseline import CONFIG as original
    assert CONFIG == original
    assert POLICIES == {"fixed_0.5": None, "fpr_5pct": .05}


def test_saved_test_scores_are_not_interpreted(tmp_path):
    import gzip
    path = tmp_path / "scores.csv.gz"
    with gzip.open(path, "wt") as stream:
        stream.write("id,split,labels,source,tier,domain_group,char_score\n")
        stream.write("skip-test,test,INVALID,INVALID,INVALID,INVALID,NOT_A_NUMBER\n")
        stream.write("v,val,1,s,silver,v.vn,0.25\n")
    frame = pd.DataFrame([{"id": "v", "labels": 1, "source": "s", "tier": "silver", "domain_group": "v.vn", "url": "v.vn"}])
    class Service:
        def _scores(self, urls):
            assert urls == ["v.vn"]
            return np.array([.25])
    np.testing.assert_array_equal(baseline_scores(frame, Service(), path), [.25])


def test_loader_never_opens_official_test_member(tmp_path, monkeypatch, preprocessing):
    import hashlib
    import zipfile
    import evaluation.url.representation as module
    path = tmp_path / "tiny.zip"
    payloads = {}
    for split in ["train", "val"]:
        rows = pd.DataFrame([{"id": f"{split}-{i}", "url": f"{split}{i}.vn",
            "label": "phishing" if i else "benign", "source": "s", "tier": "silver", "split": split} for i in range(2)])
        payloads[f"data/splits/url_{split}.csv"] = rows.to_csv(index=False).encode()
    manifest = "".join(hashlib.sha256(raw).hexdigest() + "  " + name + " \n" for name, raw in payloads.items())
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("MANIFEST.txt", manifest)
        for name, raw in payloads.items():
            z.writestr(name, raw)
        z.writestr("data/splits/url_test.csv", "DO NOT READ")
    monkeypatch.setattr(module, "sha", lambda _: module.SHA256)
    original = zipfile.ZipFile.read
    seen = []
    def guarded(self, name, *args, **kwargs):
        assert "test" not in name
        seen.append(name)
        return original(self, name, *args, **kwargs)
    monkeypatch.setattr(zipfile.ZipFile, "read", guarded)
    loaded, audit = load_frames(path, preprocessing)
    assert set(loaded) == {"train", "val"}
    assert seen == ["MANIFEST.txt", "data/splits/url_train.csv", "data/splits/url_val.csv"]


def test_existing_protocol_is_not_overwritten(tmp_path):
    out = tmp_path / "old"
    out.mkdir()
    (out / "execution.json").write_text("old")
    with pytest.raises(ValueError, match="new output"):
        prepare(out)
    assert (out / "execution.json").read_text() == "old"


def test_source_drift_and_repeat_fit_are_rejected(tmp_path):
    source = tmp_path / "source.py"
    source.write_text("changed")
    protocol = {"configuration": CONFIG, "policies": POLICIES, "representation": REPRESENTATION,
                "input_hashes": {str(source): "0" * 64}}
    (tmp_path / "execution.json").write_text(json.dumps(protocol))
    with pytest.raises(ValueError, match="source/input changed"):
        check_lock(tmp_path)
    protocol["input_hashes"] = {}
    (tmp_path / "execution.json").write_text(json.dumps(protocol))
    (tmp_path / "fit_started.json").write_text("{}")
    with pytest.raises(ValueError, match="already started"):
        run(tmp_path)
