import json

import numpy as np
import pandas as pd
import pytest

from evaluation.url.calibration import POLICIES, alarm, choose_cutoff, evaluate, fold_for, group_metrics, prevalence_scenarios, run, validate


def sample():
    rows = []
    for domain in range(30):
        for label in [0, 1]:
            rows.append({"id": f"{domain}-{label}", "url": f"domain{domain}.vn/{label}",
                         "domain_group": f"domain{domain}.vn", "source": "positive" if label else "benign",
                         "tier": "silver", "labels": label, "score": (domain + label) / 32})
    frame = pd.DataFrame(rows)
    frame["fold"] = frame.domain_group.map(fold_for)
    return frame


def test_negative_only_threshold_selection_handles_ties_under_greater_equal():
    frame = pd.DataFrame({"labels": [0, 0, 0, 0, 1], "score": [.8, .8, .4, .1, 1.],
                          "source": ["a"] * 5})
    threshold = choose_cutoff(frame, .25)
    assert threshold > .8
    assert alarm(frame.score[:4], threshold).sum() == 0
    changed = frame.copy()
    changed.loc[changed.labels.eq(1), "score"] = .01
    assert choose_cutoff(changed, .25) == threshold
    # Exact boundaries use >=, so the tie must be removed as a group.
    assert alarm([.8, threshold], threshold).tolist() == [False, True]


def test_worst_source_constraint_prevents_large_source_hiding_small_source_errors():
    frame = pd.DataFrame({"labels": [0] * 101, "source": ["big"] * 100 + ["small"],
                          "score": [.1] * 100 + [.95]})
    global_cutoff = choose_cutoff(frame, .05)
    source_cutoff = choose_cutoff(frame, .05, per_source=True)
    assert alarm([.95], global_cutoff)[0]
    assert not alarm([.95], source_cutoff)[0]


def test_impossible_budget_disables_alarms_instead_of_claiming_urls_safe():
    frame = pd.DataFrame({"labels": [0, 1], "score": [1., 1.], "source": ["a", "b"]})
    assert choose_cutoff(frame, 0) is None
    assert not alarm(frame.score, None).any()
    with pytest.raises(ValueError, match="benign"):
        choose_cutoff(frame.loc[frame.labels.eq(1)], .05)


def test_crossfit_keeps_domains_together_and_does_not_use_heldout_labels_or_scores():
    frame = sample()
    assert set(frame.fold) == set(range(5))
    original, predictions = evaluate(frame, {"warning_threshold": .1, "high_threshold": .5})
    assert not predictions.groupby(["policy", "domain_group"]).fold.nunique().gt(1).any()
    fold = 2
    changed = frame.copy()
    mask = changed.fold.eq(fold)
    changed.loc[mask, "score"] = .99
    changed.loc[mask, "labels"] = 1 - changed.loc[mask, "labels"]
    updated, _ = evaluate(changed, {"warning_threshold": .1, "high_threshold": .5})
    for policy in POLICIES:
        before = original["policies"][policy]["folds"][fold]
        after = updated["policies"][policy]["folds"][fold]
        assert before["threshold"] == after["threshold"]
        assert before["calibration_n"] == after["calibration_n"]


def test_source_metrics_and_hypothetical_priors_do_not_misrepresent_precision():
    frame = sample()
    measured = group_metrics(frame, np.ones(len(frame), dtype=bool))
    assert measured["source:positive"]["precision"] is None
    assert measured["source:benign"]["f1"] is None
    assert measured["source:positive"]["recall"] == 1
    scenario = prevalence_scenarios(.8, .1)[1]
    assert scenario["expected_tp"] == 80
    assert scenario["expected_fp"] == 990
    assert scenario["expected_fn"] == pytest.approx(20)
    assert scenario["expected_precision"] == pytest.approx(80 / 1070)


@pytest.mark.parametrize("field,value", [("score", np.nan), ("score", 1.1), ("labels", 2), ("domain_group", "")])
def test_invalid_saved_validation_is_rejected(field, value):
    frame = sample()
    frame.loc[0, field] = value
    with pytest.raises(ValueError):
        validate(frame)


def test_existing_experiment_is_preserved_before_loading_any_inputs(tmp_path):
    out = tmp_path / "old"
    out.mkdir()
    execution = out / "execution.json"
    execution.write_text(json.dumps({"old": True}))
    before = execution.read_bytes()
    with pytest.raises(ValueError, match="new output"):
        run(out)
    assert execution.read_bytes() == before
