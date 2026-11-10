"""Resume rejection must leave an existing experiment byte-for-byte intact."""
import asyncio
from argparse import Namespace
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd
import pytest

import evaluation.url.phishvn as benchmark


def tree_hashes(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in Path(root).rglob("*") if p.is_file()}


@pytest.fixture
def run_fixture(tmp_path, monkeypatch):
    model_path = tmp_path / "model"
    model_path.mkdir()
    for name in ("model.ubj", "config.json", "url_features.py", "url_preprocessing.py"):
        (model_path / name).write_text("fixture", encoding="utf-8")
    notebook = tmp_path / "fixture.ipynb"
    notebook.write_text("{}", encoding="utf-8")
    frames = {split: pd.DataFrame([
        {"id": f"{split}-{label}", "labels": label, "url": f"https://{split}-{label}.example/",
         "source": "fixture", "tier": "silver", "domain_group": f"{split}-{label}.example"}
        for label in (0, 1)]) for split in ("train", "val", "test")}
    calls = []

    class Predictor:
        def predict(self, urls):
            calls.append(urls)
            return [{"score": .9 if "-1." in url else .1,
                     "risk_level": "HIGH" if "-1." in url else "LOW"} for url in urls]

    class Model:
        path = model_path
        predictor = Predictor()
        spec = {"thresholds": {"warning_threshold": .5, "high_threshold": .8,
                               "validation_metrics": {"tp": 1, "fp": 0, "tn": 1, "fn": 0}},
                "validation_at_05": {"tp": 1, "fp": 0, "tn": 1, "fn": 0}}

        def __init__(self, settings):
            pass

        def load(self):
            return {"ready": True}

    monkeypatch.setattr(benchmark, "ModelService", Model)
    monkeypatch.setattr(benchmark, "notebook_constants", lambda _: {
        "CFG": {}, "FEATURE_SOURCE": "fixture", "PREPROCESSING_SOURCE": "fixture"})
    monkeypatch.setattr(benchmark, "prepare_splits", lambda *args: (frames, {}))
    monkeypatch.setattr(benchmark, "recover_fingerprint", lambda *args: ("fixture", {}))
    monkeypatch.setitem(sys.modules, "url_preprocessing", object())
    args = Namespace(out=tmp_path / "out", archive=tmp_path / "unused.zip", notebook=notebook,
                     llm_sample=2, seed=17, live=False)
    return args, model_path, calls


@pytest.mark.parametrize("change", ["seed", "model", "notebook", "live"])
def test_mismatched_resume_preserves_all_snapshot_files(run_fixture, change):
    args, model_path, calls = run_fixture
    asyncio.run(benchmark.evaluate(args))
    # Include files not written by this runner and nested assets in the assertion.
    (args.out / "assets").mkdir()
    (args.out / "assets" / "sentinel.txt").write_text("preserve me", encoding="utf-8")
    before = tree_hashes(args.out)
    count = len(calls)
    if change == "seed":
        args.seed += 1
    elif change == "model":
        (model_path / "model.ubj").write_text("changed model", encoding="utf-8")
    elif change == "notebook":
        args.notebook.write_text('{"changed": true}', encoding="utf-8")
    else:
        args.live = True
    with pytest.raises(ValueError, match="different dataset/model/prompt/configuration"):
        asyncio.run(benchmark.evaluate(args))
    assert tree_hashes(args.out) == before
    assert len(calls) == count


def test_matching_offline_resume_preserves_outputs(run_fixture):
    args, _, _ = run_fixture
    asyncio.run(benchmark.evaluate(args))
    before = tree_hashes(args.out)
    asyncio.run(benchmark.evaluate(args))
    assert tree_hashes(args.out) == before


def test_nonempty_directory_without_manifest_is_never_overwritten(run_fixture):
    args, _, calls = run_fixture
    args.out.mkdir()
    (args.out / "provenance.json").write_text('{"historical": true}', encoding="utf-8")
    before = tree_hashes(args.out)
    with pytest.raises(ValueError, match="no matching manifest"):
        asyncio.run(benchmark.evaluate(args))
    assert tree_hashes(args.out) == before
    assert calls == []


def test_unknown_checkpoint_is_rejected_before_snapshot_writes(run_fixture):
    args, _, calls = run_fixture
    asyncio.run(benchmark.evaluate(args))
    (args.out / "checkpoints.jsonl").write_text(json.dumps({
        "case_id": "unselected-id", "arm": benchmark.ARMS[0], "result": {"status": "ok"}}) + "\n")
    before = tree_hashes(args.out)
    count = len(calls)
    with pytest.raises(ValueError, match="Unknown case or arm"):
        asyncio.run(benchmark.evaluate(args))
    assert tree_hashes(args.out) == before
    assert len(calls) == count
