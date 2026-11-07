import json

import numpy as np
import pytest
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

from app.url_char_service import (CharURLService, ROOT, SCHEMA, _json, _learned_hashes,
                                  _sha, _versions, export)
from app.url_policy import ConservativeURLModel


@pytest.fixture
def package(tmp_path):
    preprocessing = tmp_path / "preprocessing.py"
    preprocessing.write_text("def format_url(url):\n    if not url or '\\n' in url: raise ValueError('bad URL')\n    return url\n")
    texts = ["benign.vn/news", "benign.vn/about", "fraud.vn/login", "fraud.vn/password"]
    vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(3, 5), min_df=2,
        max_features=150000, sublinear_tf=True, dtype=np.float64)
    transformed = vectorizer.fit_transform(texts)
    classifier = LogisticRegression(C=1., solver="liblinear", class_weight="balanced",
                                    max_iter=1000, random_state=42).fit(transformed, [0, 0, 1, 1])
    _json(tmp_path / "vocabulary.json", {key: int(value) for key, value in vectorizer.vocabulary_.items()})
    np.savez_compressed(tmp_path / "weights.npz", idf=vectorizer.idf_, coef=classifier.coef_,
                        intercept=classifier.intercept_, classes=classifier.classes_)
    manifest = {"schema": SCHEMA, "candidate": True, "versions": _versions(),
        "files": {name: _sha(tmp_path / name) for name in ["vocabulary.json", "weights.npz"]},
        "learned_hashes": _learned_hashes(vectorizer, classifier),
        "source_runner_sha256": _sha(ROOT / "evaluation/url_char_baseline.py"),
        "serving_source_sha256": _sha(ROOT / "app/url_char_service.py"),
        "preprocessing_sha256": _sha(preprocessing), "equivalence": {"all_scores_bitwise_match": True, "rows": 4},
        "thresholds": {"warning_threshold": .5, "high_threshold": .5259423981707284}}
    _json(tmp_path / "export.json", manifest)
    return tmp_path, preprocessing, texts, vectorizer, classifier


def service(package):
    path, preprocessing, *_ = package
    return CharURLService(path, preprocessing)


def test_json_npz_reconstruction_preserves_predictions_exactly(package):
    model = service(package)
    assert model.load()["ready"]
    _, _, texts, vectorizer, classifier = package
    expected = classifier.predict_proba(vectorizer.transform(texts))[:, 1]
    np.testing.assert_array_equal(model._scores(texts), expected)
    np.testing.assert_array_equal([row["score"] for row in model.predict(texts)], expected)
    assert model.status()["experimental"]


def test_conservative_wrapper_keeps_middle_band_unknown(package):
    model = service(package)
    model.load()
    values = iter([.49, .5, .52, .5259423981707284])
    model._scores = lambda urls: np.asarray([next(values)])
    outputs = ConservativeURLModel(model).predict(["a", "b", "c", "d"])
    assert [item["risk_level"] for item in outputs] == ["LOW", "UNKNOWN", "UNKNOWN", "HIGH"]
    assert all(item["low_threshold"] == .5 for item in outputs)


@pytest.mark.parametrize("change", ["weights", "vocabulary", "preprocessing", "versions", "threshold", "equivalence"])
def test_tampered_or_incompatible_package_refuses_serving(package, change):
    path, preprocessing, *_ = package
    manifest = json.loads((path / "export.json").read_text())
    if change in {"weights", "vocabulary"}:
        (path / ("weights.npz" if change == "weights" else "vocabulary.json")).write_bytes(b"changed")
    elif change == "preprocessing":
        preprocessing.write_text("changed")
    elif change == "versions":
        manifest["versions"]["sklearn"] = "wrong"
    elif change == "threshold":
        manifest["thresholds"]["high_threshold"] = .4
    else:
        manifest["equivalence"]["all_scores_bitwise_match"] = False
    _json(path / "export.json", manifest)
    model = service(package)
    assert not model.load()["ready"]
    assert model.predict(["example.vn"])[0]["status"] == "unavailable"


def test_bad_url_errors_without_changing_valid_neighbor(package):
    model = service(package)
    output = model.predict(["benign.vn/about", "bad\nURL", "fraud.vn/login"])
    assert [row["status"] for row in output] == ["ok", "error", "ok"]
    assert "score" not in output[1]


def test_export_existing_package_refuses_before_fitting(tmp_path):
    (tmp_path / "deployment").mkdir()
    (tmp_path / "deployment/marker").write_text("old")
    with pytest.raises(ValueError, match="tồn tại"):
        export(tmp_path)
    assert (tmp_path / "deployment/marker").read_text() == "old"
