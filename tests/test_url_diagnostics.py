import csv
import hashlib
import json

import pytest

from evaluation.url_diagnostics import diagnose, load_inputs, measures, projected_precision, wilson95


def row(label, score, source="fixture", tier="silver", domain="example.org"):
    return {"label": label, "score": score, "source": source, "tier": tier, "domain_group": domain}


def test_counts_undefined_metrics_and_threshold_boundary():
    m = measures([row(0, .1), row(0, .5), row(1, .4), row(1, .9)], .5)
    assert (m["tp"], m["fp"], m["tn"], m["fn"]) == (1, 1, 1, 1)
    assert m["recall"] == m["precision"] == m["false_positive_rate"] == .5
    assert m["precision_at_assumed_prevalence"]["0.01"] == pytest.approx(.01)
    benign = measures([row(0, .1)], .5)
    assert benign["precision"] is None and benign["recall"] is None
    assert benign["recall_wilson95"] is None and benign["false_positive_rate"] == 0
    assert all(p is None for p in benign["precision_at_assumed_prevalence"].values())
    phishing = measures([row(1, .9)], .5)
    assert phishing["false_positive_rate"] is None
    assert phishing["false_positive_rate_wilson95"] is None
    empty = measures([], .5)
    assert empty["n"] == 0 and empty["accuracy"] is None and empty["f1"] is None


def test_wilson_interval_stays_in_range_including_zero_errors():
    assert wilson95(0, 0) is None
    all_right = wilson95(10, 10)
    assert all_right["lower"] == pytest.approx(.7224672001371107)
    assert all_right["upper"] == pytest.approx(1)
    zero_errors = wilson95(0, 10)
    assert zero_errors["lower"] == pytest.approx(0)
    assert zero_errors["upper"] == pytest.approx(.2775327998628892)
    middle = wilson95(50, 100)
    assert middle["lower"] == pytest.approx(.4038315303659957)
    assert middle["upper"] == pytest.approx(.5961684696340044)
    for bad in [(2, 1), (-1, 10), (True, 1), (1.0, 2)]:
        with pytest.raises(ValueError):
            wilson95(*bad)


def test_prevalence_projection_is_conditional_and_not_accuracy():
    assert projected_precision(.9, .1, .01) == pytest.approx(1 / 12)
    assert projected_precision(.9, .1, .5) == pytest.approx(.9)
    assert projected_precision(0, 0, .1) is None
    assert projected_precision(None, .1, .1) is None
    for value in (0, 1, float("nan")):
        with pytest.raises(ValueError):
            projected_precision(.9, .1, value)


@pytest.fixture
def snapshot(tmp_path):
    run = tmp_path / "source"
    run.mkdir()
    rows = [row(0, .1, "benign", "silver"), row(0, .8, "benign", "gold"),
            row(1, .4, "positive", "silver"), row(1, .9, "positive", "bronze")]
    path = run / "test_predictions.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "labels", "score", "source", "tier", "domain_group"])
        writer.writeheader()
        for i, item in enumerate(rows):
            writer.writerow({"id": f"id-{i}", "labels": item["label"],
                             **{k: item[k] for k in ("score", "source", "tier", "domain_group")}})
    stored = {name: {"threshold": threshold, **measures(rows, threshold)}
              for name, threshold in (("warning", .3), ("high", .8), ("fixed_0.5", .5))}
    (run / "url_model_metrics.json").write_text(json.dumps({"test": stored}), encoding="utf-8")
    (run / "manifest.json").write_text('{"configuration": {"fixture": true}}', encoding="utf-8")
    return run


def hashes(path):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in path.iterdir() if p.is_file()}


def test_report_preserves_source_and_existing_output(snapshot, tmp_path):
    before = hashes(snapshot)
    out = tmp_path / "diagnostics"
    result = diagnose(snapshot, out)
    assert hashes(snapshot) == before
    assert {k: v["sha256"] for k, v in result["inputs"].items()} == before
    warning = result["thresholds"]["warning"]
    assert warning["all"]["n"] == 4 and warning["gold_silver"]["n"] == 3
    assert warning["by_source"]["benign"]["recall"] is None
    assert warning["by_source"]["positive"]["false_positive_rate"] is None
    assert "chưa bootstrap theo domain" in (out / "report.md").read_text()
    assert json.loads((out / "summary.json").read_text()) == result
    before_output = hashes(out)
    with pytest.raises(ValueError, match="already exists"):
        diagnose(snapshot, out)
    assert hashes(out) == before_output


@pytest.mark.parametrize("corruption", ["nan", "label", "duplicate", "counts", "threshold"])
def test_invalid_inputs_fail_without_creating_output(snapshot, tmp_path, corruption):
    if corruption in {"nan", "label", "duplicate"}:
        path = snapshot / "test_predictions.csv"
        with path.open(newline="") as f:
            reader = csv.DictReader(f)
            fields, rows = reader.fieldnames, list(reader)
        if corruption == "nan":
            rows[0]["score"] = "nan"
        elif corruption == "label":
            rows[0]["labels"] = "2"
        else:
            rows[1]["id"] = rows[0]["id"]
        with path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    else:
        path = snapshot / "url_model_metrics.json"
        data = json.loads(path.read_text())
        data["test"]["warning"]["tp" if corruption == "counts" else "threshold"] = 100
        path.write_text(json.dumps(data))
    out = tmp_path / "diagnostics"
    with pytest.raises(ValueError):
        diagnose(snapshot, out)
    assert not out.exists()


def test_missing_snapshot_columns_are_rejected(snapshot):
    (snapshot / "test_predictions.csv").write_text("id,labels,score\na,0,.1\n")
    with pytest.raises(ValueError, match="required columns"):
        load_inputs(snapshot)
