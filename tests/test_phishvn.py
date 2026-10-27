import hashlib
import io
import json
import zipfile
from urllib.parse import urlsplit

import pandas as pd
import pytest

import evaluation.phishvn as benchmark


class Preprocessing:
    @staticmethod
    def parse_url_parts(url):
        parsed = urlsplit(url)
        return parsed, parsed.hostname

    @staticmethod
    def format_url(url):
        return "[DOMAIN] " + url


def archive_fixture(tmp_path, monkeypatch, leak=False, corrupt_manifest=False):
    contents = {}
    for split in ("train", "val", "test"):
        rows = [{"id": split + "-" + label, "url": f"https://{split}-{label}.org/path", "label": label,
                 "tier": "silver", "source": "fixture", "split": split} for label in ("benign", "phishing")]
        if split == "train":
            rows.append({**rows[0], "id": "duplicate"})
        if leak and split in ("train", "val"):
            rows[1]["url"] = f"https://{split}.shared.org/"
        contents[f"data/splits/url_{split}.csv"] = pd.DataFrame(rows).to_csv(index=False).encode()
    manifest = "\n".join(f"{hashlib.sha256(content).hexdigest()}  {name}  {len(content)}" for name, content in contents.items())
    archive = tmp_path / "fixture.zip"
    with zipfile.ZipFile(archive, "w") as out:
        out.writestr("MANIFEST.txt", manifest.replace("data/splits/url_test.csv", "wrong-name.csv") if corrupt_manifest else manifest)
        for name, content in contents.items():
            out.writestr(name, content)
    expected = hashlib.sha256(archive.read_bytes()).hexdigest()
    monkeypatch.setattr(benchmark, "SHA256", expected)
    return archive, {"DATA_SHA256": expected, "DATA_SCOPE": "all", "SMOKE_TEST": False}


def test_official_split_preparation_hashes_cleaning_and_labels(tmp_path, monkeypatch):
    archive, cfg = archive_fixture(tmp_path, monkeypatch)
    frames, audit = benchmark.prepare_splits(archive, cfg, Preprocessing)
    assert list(frames) == ["train", "val", "test"]
    assert audit["train"]["raw"] == 3 and audit["train"]["clean"] == 2
    assert audit["train"]["duplicates"] == 1
    assert all(frame.labels.tolist() == [0, 1] for frame in frames.values())
    assert all(audit[split]["benign"] == audit[split]["phishing"] == 1 for split in frames)


def test_domain_overlap_between_official_splits_is_rejected(tmp_path, monkeypatch):
    archive, cfg = archive_fixture(tmp_path, monkeypatch, leak=True)
    with pytest.raises(ValueError, match="domain_group"):
        benchmark.prepare_splits(archive, cfg, Preprocessing)


def test_corrupted_archive_or_manifest_is_rejected(tmp_path, monkeypatch):
    archive, cfg = archive_fixture(tmp_path, monkeypatch, corrupt_manifest=True)
    with pytest.raises(ValueError, match="MANIFEST mismatch"):
        benchmark.prepare_splits(archive, cfg, Preprocessing)
    archive.write_bytes(archive.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="Archive/config"):
        benchmark.prepare_splits(archive, cfg, Preprocessing)


def test_notebook_configuration_is_read_without_executing_cells(tmp_path):
    path = tmp_path / "train.ipynb"
    path.write_text(json.dumps({"cells": [{"cell_type": "code", "source": [
        "CFG = {'DATA_SCOPE': 'all'}\nFEATURE_SOURCE = 'feature'\nPREPROCESSING_SOURCE = 'preprocess'\nraise RuntimeError('must never execute')"]}]}), encoding="utf-8")
    assert benchmark.notebook_constants(path) == {"CFG": {"DATA_SCOPE": "all"}, "FEATURE_SOURCE": "feature", "PREPROCESSING_SOURCE": "preprocess"}


def test_changed_training_fingerprint_cannot_be_called_unseen_holdout():
    cfg = {"RUN_BERT": False}
    frames = {"train": pd.DataFrame({"id": ["train"]}), "val": pd.DataFrame({"id": ["val"]}), "test": pd.DataFrame({"id": ["test"]})}
    with pytest.raises(ValueError, match="fingerprint"):
        benchmark.recover_fingerprint(cfg, {"FEATURE_SOURCE": "", "PREPROCESSING_SOURCE": ""}, frames,
                                     {"versions": {}, "fingerprint": "000000000000"})


def test_paired_url_evaluation_keeps_model_out_of_llm_only_decision():
    selected = pd.DataFrame([{"id": "x", "url": "https://example.org", "labels": 0, "source": "fixture", "tier": "silver"}])
    predictions = {"x": {"status": "ok", "risk_level": "HIGH"}}
    low = {"status": "ok", "verdict": {"risk_level": "LOW"}}
    rows = benchmark.paired_rows(selected, predictions, {("x", arm): low for arm in benchmark.ARMS})
    assert rows[0]["mode"] == "url"
    assert rows[0]["levels"]["llm_only"] == "LOW"
    assert rows[0]["levels"]["fusion_with_url_model"] == "HIGH"


def test_url_threshold_metrics_use_positive_class_and_preserve_scores():
    m = benchmark.binary_metrics([0, 0, 1, 1], [.1, .7, .4, .9], .5)
    assert (m["tp"], m["fp"], m["tn"], m["fn"]) == (1, 1, 1, 1)
    assert m["precision"] == m["recall"] == m["f1"] == m["accuracy"] == .5
    assert m["roc_auc"] == .75
