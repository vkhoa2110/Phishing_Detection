import json

import numpy as np
import pandas as pd
import pytest

from evaluation import url_probability_audit_v2 as module
from evaluation.url_calibration import fold_for, sha, write_json


def frame():
    rows = []
    for i in range(150):
        label = int(i % 3 == 0)
        rows.append({"id": f"val-{i}", "split": "val", "labels": label,
                     "url": f"https://example{i}.vn/", "domain_group": f"example{i}.vn",
                     "source": "threat" if label else "benign",
                     "tier": "bronze" if i % 4 == 0 else "silver",
                     "score": .15 + .6 * label + .02 * (i % 8)})
    return pd.DataFrame(rows)


def test_calibration_never_sees_heldout_domain_scores_labels_or_tier():
    original = frame()
    first, fits, _ = module.crossfit(original)
    changed = original.copy()
    selected = changed.domain_group.map(fold_for).eq(2)
    changed.loc[selected, "labels"] = 1 - changed.loc[selected].labels
    changed.loc[selected, "tier"] = "bronze"
    second, other, _ = module.crossfit(changed)
    assert [x for x in fits if x["fold"] == 2] == [x for x in other if x["fold"] == 2]
    for name in module.ARMS:
        np.testing.assert_array_equal(first.loc[selected, name], second.loc[selected, name])
    assert len(fits) == 10 and set(first.fold) == set(range(5))
    assert all(fit["slope"] > 0 for fit in fits)


def test_proper_scores_include_one_class_and_boundary_probabilities():
    result = module.probability_metrics([0, 0, 1, 1], [0, .5, .5, 1])
    assert result["brier"] == .125
    assert result["log_loss"] == pytest.approx(np.log(2) / 2)
    assert sum(r["n"] for r in result["reliability_bins"]) == 4
    assert result["reliability_bins"][-1]["n"] == 1
    assert module.probability_metrics([1, 1], [.8, .9])["brier"] == pytest.approx(.025)
    one = module.metrics(frame(), frame().score)["source:threat"]
    assert one["positive"] == one["n"] and "f1" not in one
    assert np.isfinite(module.logits([0, 1])).all()


@pytest.mark.parametrize("mutation", ["nan", "outside", "duplicate", "test", "no_core_positive"])
def test_invalid_or_insufficient_calibration_data_rejected(mutation):
    data = frame()
    if mutation == "nan": data.loc[0, "score"] = np.nan
    if mutation == "outside": data.loc[0, "score"] = 1.01
    if mutation == "duplicate": data.loc[0, "id"] = data.loc[1, "id"]
    if mutation == "test": data.loc[0, "split"] = "test"
    if mutation == "no_core_positive": data.loc[data.labels.eq(1), "tier"] = "bronze"
    with pytest.raises(ValueError):
        module.crossfit(data)


def test_completed_run_is_sealed_verified_without_refit_and_never_overwritten(tmp_path, monkeypatch):
    out = tmp_path / "run"
    out.mkdir()
    data = frame().drop(columns="url")
    data.to_csv(out / "input.csv.gz", index=False)
    write_json(out / "execution.json", {"configuration": module.CONFIG, "arms": module.ARMS,
        "environment": module.environment(), "input_hashes": {}, "input_sha256": sha(out / "input.csv.gz")})
    assert module.run(out)["calibrator_fits"] == 10
    monkeypatch.setattr(module.LogisticRegression, "fit", lambda *args, **kwargs: pytest.fail("verify must not refit"))
    assert module.verify(out)["refits"] == 0
    with pytest.raises(ValueError, match="already started"):
        module.run(out)
    with pytest.raises(ValueError, match="preserve"):
        module.prepare(out)
    old = (out / "summary.json").read_text()
    (out / "summary.json").write_text(old + " ")
    with pytest.raises(ValueError, match="hash mismatch"):
        module.verify(out)


def test_registered_code_or_input_changes_block_calibrator_fit(tmp_path):
    path = tmp_path / "source.py"
    path.write_text("initial")
    data = frame().drop(columns="url")
    data.to_csv(tmp_path / "input.csv.gz", index=False)
    write_json(tmp_path / "execution.json", {"configuration": module.CONFIG, "arms": module.ARMS,
        "environment": module.environment(), "input_hashes": {str(path): sha(path)}, "input_sha256": sha(tmp_path / "input.csv.gz")})
    path.write_text("changed")
    with pytest.raises(ValueError, match="source/input changed"):
        module.run(tmp_path)
    assert not (tmp_path / "fit_started.json").exists()
