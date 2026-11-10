import json

import numpy as np
import pytest

from app.services.url.character import CharURLService, _sha
from scripts.maintenance.repackage_character import repackage
from tests.url.test_url_char_service import package


def snapshot(package, tmp_path):
    source, preprocessing, urls, vectorizer, classifier = package
    baseline = tmp_path / "baseline"
    baseline.mkdir()
    (baseline / "baseline.json").write_text(json.dumps({
        "git_commit": "fixture-before-move", "character_validation_rows": len(urls)}))
    (baseline / "char_export_before.json").write_bytes((source / "export.json").read_bytes())
    (baseline / "validation_urls.json").write_text(json.dumps(urls))
    scores = classifier.predict_proba(vectorizer.transform(urls))[:, 1]
    np.save(baseline / "char_validation_scores.npy", scores)
    return source, preprocessing, baseline, urls, scores


def test_repackaging_preserves_weights_manifest_and_exact_scores(package, tmp_path):
    source, preprocessing, baseline, urls, scores = snapshot(package, tmp_path)
    before = {name: _sha(source / name) for name in ("export.json", "weights.npz", "vocabulary.json")}
    target = tmp_path / "repackaged"
    proof = repackage(source, baseline, target, preprocessing=preprocessing)
    assert proof["validation_rows"] == len(urls) and proof["fits"] == 0
    assert before == {name: _sha(source / name) for name in before}
    assert all(_sha(target / name) == before[name] for name in ("weights.npz", "vocabulary.json"))
    runtime = CharURLService(target, preprocessing)
    assert runtime.load()["ready"]
    np.testing.assert_array_equal(runtime._scores(urls), scores)
    with pytest.raises(ValueError, match="Destination exists"):
        repackage(source, baseline, target, preprocessing=preprocessing)


def test_changed_scores_refuse_package_and_remove_temporary_files(package, tmp_path):
    source, preprocessing, baseline, urls, scores = snapshot(package, tmp_path)
    np.save(baseline / "char_validation_scores.npy", scores + .01)
    target = tmp_path / "rejected"
    with pytest.raises(ValueError, match="Scores changed"):
        repackage(source, baseline, target, preprocessing=preprocessing)
    assert not target.exists() and not list(tmp_path.glob(".repackage-*"))
