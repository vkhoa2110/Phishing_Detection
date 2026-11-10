import copy
import json

import pytest

import evaluation.url.reputation as experiment


def source_row(**values):
    return {"id": "source-1", "url": "https://bank.example/", "source": "tinnhiem_org",
            "tier": "gold", "labels": 0, "scraped_at": "2026-07-16T00:00:00+00:00",
            "domain_group": "bank.example", **values}


def test_knowledge_filters_popularity_and_model_scores_do_not_affect_source_evidence():
    rows = [source_row(), source_row(id="threat-1", source="tinnhiemmang", labels=1, tier="silver", url="https://bad.example"),
            source_row(id="popular-1", source="tranco"), source_row(id="bronze-1", tier="bronze"),
            source_row(id="bad-date", scraped_at="not a date"), source_row(id="bad-url", url="https://u:p@bank.example")]
    entries, audit = experiment.build_evidence(rows)
    assert len(entries) == 2 and audit == {"trusted": 1, "malicious": 1, "excluded_source_tier_or_label": 2,
                                         "excluded_invalid_url_or_time": 2}
    assert entries[0].expires_at == "2026-08-15T00:00:00+00:00"
    assert entries[1].expires_at == "2026-07-23T00:00:00+00:00"
    changed = [{**r, "score": 1.0, "risk_level": "HIGH", "model_prediction": "phishing"} for r in reversed(rows)]
    assert sorted(experiment.build_evidence(changed)[0], key=lambda x: x.id) == sorted(entries, key=lambda x: x.id)


def test_known_sampling_is_score_blind_reproducible_and_one_url_per_domain(monkeypatch):
    monkeypatch.setattr(experiment, "KNOWN_QUOTAS", (("tinnhiem_org", "gold", 3),))
    rows = [source_row(id=f"id-{i}", url=f"https://site{i // 2}.example/{i}", domain_group=f"site{i // 2}.example") for i in range(10)]
    entries, _ = experiment.build_evidence(rows)
    first = experiment.select_known(entries, rows)
    second = experiment.select_known(list(reversed(entries)), [{**r, "score": i / 10} for i, r in enumerate(reversed(rows))])
    assert first == second and len({r["domain_group"] for r in first}) == 3
    assert all(r["reference"].endswith("not_independent") for r in first)
    with pytest.raises(ValueError, match="Insufficient"):
        experiment.select_known(entries[:1], rows)


def test_unknown_routing_does_not_gain_or_lose_accuracy_while_known_replays_are_separate():
    cases = [{"id": "k0", "label": 0, "cohort": "known_replay"}, {"id": "k1", "label": 1, "cohort": "known_replay"},
             {"id": "n0", "label": 0, "cohort": "unknown_dev"}, {"id": "n1", "label": 1, "cohort": "unknown_dev"}]
    baseline = [{"status": "ok", "risk_level": "HIGH"} for _ in cases]
    routed = [{"risk_level": level, "model_called": i >= 2,
               "reputation": {"risk_level": level if i < 2 else "UNKNOWN", "state": "known" if i < 2 else "miss"}}
              for i, level in enumerate(["LOW", "HIGH", "HIGH", "HIGH"])]
    result = experiment.summarize(cases, baseline, routed)
    new = result["unknown_dev"]
    assert new["arms"]["url_model"]["f1"] == new["arms"]["lookup_then_model"]["f1"] == pytest.approx(2 / 3)
    assert new["arms"]["lookup_then_model"]["model_inputs"] == 2
    assert new["arms"]["lookup_only"]["coverage"] == 0
    assert result["known_replay"]["arms"]["lookup_then_model"]["model_skip_rate"] == 1
    assert result["designed_mix"]["arms"]["lookup_then_model"]["model_skip_rate"] == .5
    assert result["designed_mix"]["paired_ml_to_hybrid"]["improved"] == 1


def test_input_verification_rejects_knowledge_changes(tmp_path):
    p = tmp_path / "knowledge.jsonl"
    p.write_text("original")
    (tmp_path / "execution.json").write_text(json.dumps({"source_hashes": {}, "prepared_hashes": {p.name: experiment.sha(p)}}))
    experiment.verify_inputs(tmp_path)
    p.write_text("changed")
    with pytest.raises(ValueError, match="changed"):
        experiment.verify_inputs(tmp_path)


def test_report_keeps_replays_and_unknown_separate_and_discloses_expiry():
    cases = [{"label": 0, "cohort": "known_replay"}, {"label": 1, "cohort": "unknown_dev"}]
    baseline = [{"status": "ok", "risk_level": "HIGH"} for _ in cases]
    rows = [{"risk_level": "LOW", "model_called": False, "reputation": {"risk_level": "LOW", "state": "known"}},
            {"risk_level": "HIGH", "model_called": True, "reputation": {"risk_level": "UNKNOWN", "state": "miss"}}]
    metrics = experiment.summarize(cases, baseline, rows)
    summary = {"execution": {"knowledge_entries": 1}, "scenarios": {
        "historical": {"as_of": "fixture-historical", "metrics": metrics},
        "after_expiry": {"as_of": "fixture-later", "metrics": copy.deepcopy(metrics)}}, "actual_model_inputs": 3}
    text = experiment.report(summary)
    assert "không phải kết quả dự đoán trên URL chưa biết" in text
    assert "Giữ nguyên kho đến khi hết hạn" in text
    assert "không đại diện lưu lượng thực" in text
