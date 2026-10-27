import asyncio
from collections import Counter, defaultdict
import json

import httpx
import pytest

from app.llm_service import LLMService
from app.settings import Settings
from app.urls import extract_urls
from evaluation.metrics import measure, paired_comparison
from evaluation.run import (ARMS, DATASET, assemble_rows, call_arm, load_checkpoints,
                            load_dataset, prepare_manifest, summarize)


def test_dataset_balanced_has_real_urls_and_opposite_context_controls():
    cases = load_dataset(DATASET)
    assert len(cases) == 60
    assert Counter(c["label"] for c in cases) == {0: 30, 1: 30}
    assert len({c["category"] for c in cases}) == 6
    assert all(len(extract_urls(c["text"], "text")[0]) >= 1 for c in cases)
    groups = defaultdict(list)
    for case in cases:
        if case.get("pair_id"):
            groups[case["pair_id"]].append(case)
    assert len(groups) == 6
    for pair in groups.values():
        assert {c["label"] for c in pair} == {0, 1}
        assert len(pair) == 2
        assert extract_urls(pair[0]["text"], "text") == extract_urls(pair[1]["text"], "text")


def test_metrics_do_not_hide_abstentions_or_errors():
    result = measure([1, 1, 1, 0, 0, 0], ["HIGH", "LOW", "UNKNOWN", "WARNING", "LOW", "UNKNOWN"])
    assert {k: result[k] for k in ("tp", "fp", "tn", "fn", "unknown_positive", "unknown_negative")} == {
        "tp": 1, "fp": 1, "tn": 1, "fn": 1, "unknown_positive": 1, "unknown_negative": 1}
    assert result["accuracy"] == pytest.approx(2 / 6)
    assert result["selective_accuracy"] == .5
    assert result["coverage"] == pytest.approx(4 / 6)
    assert result["recall"] == pytest.approx(1 / 3)
    assert result["precision"] == .5
    assert result["f1"] == .4
    assert result["false_positive_rate"] == pytest.approx(1 / 3)


def test_all_unknown_is_never_scored_as_safe_or_as_success():
    result = measure([0, 1], ["UNKNOWN", "UNKNOWN"])
    assert result["accuracy"] == 0 and result["recall"] == 0 and result["f1"] == 0
    assert result["coverage"] == 0 and result["selective_accuracy"] is None
    assert result["precision"] is None and result["tn"] == 0 and result["fn"] == 0


def test_paired_statistics_track_improvements_and_regressions():
    result = paired_comparison([1, 1, 0, 0], ["HIGH", "LOW", "LOW", "LOW"], ["HIGH", "HIGH", "WARNING", "WARNING"])
    assert result["improved"] == 1 and result["regressed"] == 2
    assert result["accuracy_delta"] == -.25
    assert result["both_correct"] == 1 and result["both_wrong"] == 0
    assert paired_comparison([1] * 6, ["LOW"] * 6, ["HIGH"] * 6)["mcnemar_exact_p"] == .03125


def test_invalid_metric_inputs_fail_explicitly():
    with pytest.raises(ValueError):
        measure([1, 0], ["HIGH"])
    with pytest.raises(ValueError):
        measure([2], ["HIGH"])
    with pytest.raises(ValueError):
        paired_comparison([1], [], ["HIGH"])


def test_no_model_baseline_isolated_from_url_model_and_fusion():
    case = {"id": "fixture", "label": 0, "category": "fixture", "text": "Đọc https://example.org", "rationale": "ordinary"}
    urls = [{"status": "ok", "risk_level": "HIGH", "score": .9}]
    low = {"status": "ok", "verdict": {"risk_level": "LOW"}}
    rows = assemble_rows([case], {"fixture": (urls, [], 1)}, {("fixture", a): low for a in ARMS})
    assert rows[0]["levels"] == {"url_model_only": "HIGH", "llm_only": "LOW", "llm_with_url_model": "LOW",
                                   "fusion_independent": "HIGH", "fusion_with_url_model": "HIGH"}
    summary = summarize(rows)
    assert summary["metrics"]["llm_only"]["tn"] == 1
    assert summary["metrics"]["fusion_with_url_model"]["fp"] == 1


def test_pending_hybrid_not_reported_as_completed_but_api_errors_keep_ml():
    case = {"id": "fixture", "label": 1, "category": "fixture", "text": "Đọc https://example.org", "rationale": "fixture"}
    ml = {"fixture": ([{"status": "ok", "risk_level": "HIGH"}], [], 1)}
    rows = assemble_rows([case], ml, {})
    assert rows[0]["levels"]["fusion_with_url_model"] == "UNKNOWN"
    assert summarize(rows)["complete_pairs"] == 0
    rows = assemble_rows([case], ml, {("fixture", "llm_with_url_model"): {"status": "error", "code": "TIMEOUT"}})
    assert rows[0]["levels"]["fusion_with_url_model"] == "HIGH"
    assert summarize(rows)["error_codes"]["llm_with_url_model"] == {"TIMEOUT": 1}


def test_both_arms_send_same_text_without_label_leakage_and_no_ml_in_baseline():
    payloads = []
    def transport(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
            "risk_level": "LOW", "summary": "Bình thường", "evidence": [], "recommended_actions": []})}}]})
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            from dataclasses import replace
            service = LLMService(replace(Settings(), api_key="fixture-only-not-a-real-key"), client)
            case = {"text": "Đọc https://example.org/?token=private", "label": 1, "rationale": "MUST_NOT_LEAK", "id": "SECRET_LABEL_ID"}
            urls = [{"id": "URL-01", "url": "https://example.org/?token=private", "status": "ok", "score": .9,
                     "risk_level": "HIGH", "warning_threshold": .4, "high_threshold": .8}]
            for arm in ARMS:
                await call_arm(service, case, urls, arm)
    asyncio.run(exercise())
    first, second = [json.loads(p["messages"][1]["content"]) for p in payloads]
    assert first["text"] == second["text"]
    assert "url_results" not in first and len(second["url_results"]) == 1
    assert set(first) == {"text", "input_type"}
    assert set(second) == {"text", "input_type", "url_results"}
    assert all(word not in json.dumps(payloads) for word in ("MUST_NOT_LEAK", "SECRET_LABEL_ID", "private"))
    assert payloads[0]["messages"][0] == payloads[1]["messages"][0]


def test_resume_checks_dataset_model_configuration_and_reuses_checkpoint(tmp_path):
    config = {"dataset_sha256": "original", "model": "original"}
    manifest = prepare_manifest(tmp_path, config)
    assert prepare_manifest(tmp_path, config) == manifest
    with pytest.raises(ValueError, match="different"):
        prepare_manifest(tmp_path, {**config, "model": "changed"})
    checkpoint = tmp_path / "checkpoints.jsonl"
    item = {"case_id": "P01", "arm": "llm_only", "result": {"status": "ok", "verdict": {"risk_level": "HIGH"}}}
    checkpoint.write_text(json.dumps(item) + "\n", encoding="utf-8")
    assert load_checkpoints(checkpoint)[("P01", "llm_only")] == item["result"]
    checkpoint.write_text((json.dumps(item) + "\n") * 2, encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate checkpoint"):
        load_checkpoints(checkpoint)


def test_dataset_rejects_invalid_labels_or_missing_urls(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text(json.dumps({"id": "x", "label": 2, "text": "https://example.org", "category": "x", "rationale": "x"}), encoding="utf-8")
    with pytest.raises(ValueError, match="labels"):
        load_dataset(path)
    path.write_text(json.dumps({"id": "x", "label": 1, "text": "no link", "category": "x", "rationale": "x"}), encoding="utf-8")
    with pytest.raises(ValueError, match="valid URLs"):
        load_dataset(path)


def mock_live_run(monkeypatch, tmp_path, failure_code=None):
    from argparse import Namespace
    from dataclasses import replace
    from app.llm_service import LLMFailure
    import evaluation.run as runner
    original_settings = Settings()
    model_path = tmp_path / "model"
    model_path.mkdir()
    (model_path / "fixture.json").write_text("{}", encoding="utf-8")
    class Model:
        path = model_path
        def __init__(self, settings):
            pass
        def load(self):
            return {"ready": True}
        def predict(self, urls):
            return [{"id": "URL-01", "url": url, "status": "ok", "risk_level": "HIGH", "score": .9,
                     "warning_threshold": .4, "high_threshold": .8} for url in urls]
    calls = []
    class Service:
        def __init__(self, settings, client):
            pass
        async def analyze(self, **kwargs):
            calls.append(kwargs)
            if failure_code:
                raise LLMFailure(failure_code, "fixture failure")
            return {"status": "ok", "verdict": {"risk_level": "LOW"}, "usage": {"total_tokens": 7}}
    monkeypatch.setattr(runner, "ModelService", Model)
    monkeypatch.setattr(runner, "LLMService", Service)
    monkeypatch.setattr(runner, "Settings", lambda: replace(original_settings, api_key="fixture-key"))
    dataset = tmp_path / "data.jsonl"
    dataset.write_text("\n".join(json.dumps(case, ensure_ascii=False) for case in load_dataset(DATASET)[:2]), encoding="utf-8")
    args = Namespace(dataset=dataset, out=tmp_path / "out", live=True, max_new_calls=1,
                     max_tokens=4096, timeout=90, workers=1, seed=17)
    return runner, args, calls


def test_live_budget_resume_and_cache_make_no_duplicate_calls(monkeypatch, tmp_path):
    runner, args, calls = mock_live_run(monkeypatch, tmp_path)
    first = asyncio.run(runner.evaluate(args))
    assert len(calls) == 1 and first["run_state"]["new_api_calls"] == 1
    assert first["run_state"]["stop_reason"] == "call_budget_reached"
    args.max_new_calls = 3
    second = asyncio.run(runner.evaluate(args))
    assert len(calls) == 4 and second["complete_pairs"] == 2
    third = asyncio.run(runner.evaluate(args))
    assert len(calls) == 4 and third["run_state"]["new_api_calls"] == 0
    assert len(load_checkpoints(args.out / "checkpoints.jsonl")) == 4


def test_auth_or_balance_failure_stops_without_retry(monkeypatch, tmp_path):
    runner, args, calls = mock_live_run(monkeypatch, tmp_path, "HTTP_402")
    args.max_new_calls = 10
    result = asyncio.run(runner.evaluate(args))
    assert len(calls) == 1
    assert result["run_state"]["stop_reason"] == "HTTP_402"
    assert sum(result["status_counts"][arm].get("error", 0) for arm in ARMS) == 1
