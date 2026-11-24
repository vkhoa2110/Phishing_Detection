"""Protect latency evidence against hidden failures and invalid statistics."""
import math
from types import SimpleNamespace

import numpy as np
import pytest

from evaluation.url.latency import dependency_versions, percentile, register, summarize, validate_prediction


def test_percentiles_match_linear_interpolation_without_rounding_raw_samples():
    samples = [10.05, .001, 21.3, 8.0, .12, 1.4, 3.75]
    for quantile in (0, 5, 50, 95, 100):
        assert percentile(samples, quantile) == pytest.approx(np.percentile(samples, quantile))
    assert summarize([{"total_ms": n} for n in (1.0, 1000.0, 1000.01)])["within_one_second"] == 2


@pytest.mark.parametrize("samples", [[], [math.nan], [math.inf], [-.01]])
def test_invalid_or_empty_measurements_cannot_produce_a_report(samples):
    with pytest.raises(ValueError):
        summarize([{"total_ms": value} for value in samples])


@pytest.mark.parametrize("prediction", [
    [],
    [{"url": "https://example.org", "status": "unavailable"}],
    [{"url": "https://example.net", "status": "ok", "score": .4}],
    [{"url": "https://example.org", "status": "ok", "score": math.nan}],
    [{"url": "https://example.org", "status": "ok", "score": True}],
])
def test_failures_and_wrong_urls_are_not_timed_as_success(prediction):
    with pytest.raises(ValueError):
        validate_prediction(prediction, "https://example.org")


def test_registration_rejects_small_sample_before_creating_output(tmp_path):
    destination = tmp_path / "too-few"
    with pytest.raises(ValueError, match="30 observations"):
        register(destination, rounds=5, warmup=3)
    assert not destination.exists()


def test_existing_run_cannot_be_overwritten(tmp_path):
    destination = tmp_path / "existing"
    destination.mkdir()
    sentinel = destination / "observations.csv"
    sentinel.write_text("preserved previous run\n")
    with pytest.raises(FileExistsError):
        register(destination, rounds=20, warmup=3)
    assert sentinel.read_text() == "preserved previous run\n"


def test_local_model_without_distribution_metadata_still_reports_module_version(monkeypatch):
    import evaluation.url.latency as latency

    def version(name):
        if name == "xgboost":
            raise latency.importlib.metadata.PackageNotFoundError(name)
        return "fixture-version"

    monkeypatch.setattr(latency.importlib.metadata, "version", version)
    monkeypatch.setattr(latency.importlib, "import_module", lambda module: SimpleNamespace(__version__="local-xgb"))
    versions = dependency_versions()
    assert versions["xgboost"]["version"] == "local-xgb"
    assert "metadata missing" in versions["xgboost"]["source"]
    assert versions["numpy"]["source"] == "distribution_metadata"
