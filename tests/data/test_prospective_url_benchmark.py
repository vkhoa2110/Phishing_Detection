"""Synthetic fixtures test the contract; none are exported as evaluation data."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from evaluation.data.sms import sha, write_json, write_jsonl
from evaluation.data.prospective_urls import normalize_url, prepare, register, report, utc, verify

CREATED = datetime(2026, 11, 7, tzinfo=timezone.utc)
COLLECTED = datetime(2026, 11, 10, tzinfo=timezone.utc)


def registration(tmp_path, *, now=CREATED):
    exclusions = tmp_path / "exclusions.jsonl"
    write_jsonl(exclusions, [{"url": "https://old-" + name.replace("_", "-") + ".test/", "exposure": name,
                              "campaign": "old-" + name} for name in ("train", "validation", "historical_test", "adaptive")])
    model = tmp_path / "model"
    model.mkdir()
    (model / "weights.bin").write_bytes(b"fixture weights")
    (model / "vocabulary.json").write_text('{"fixture": 0}')
    corpus = tmp_path / "corpus.jsonl"
    write_jsonl(corpus, [{"id": "fixture-source", "text": "Fixture only."}])
    thresholds = tmp_path / "thresholds.json"
    write_json(thresholds, {"candidate": {"low": .4, "high": .8}})
    protocol = tmp_path / "protocol"
    register(protocol, exclusions=[exclusions], model_locks={"candidate": model}, corpus_lock=corpus,
             thresholds=thresholds, collection_start="2026-11-07T00:00:00Z", cutoff="2026-11-09T00:00:00Z",
             quotas={"positive": 2, "negative": 2, "sources_per_class": 2}, now=now)
    snapshot = tmp_path / "evidence.txt"
    snapshot.write_text("Synthetic evidence fixture; this is not a source label.")
    return protocol, snapshot


def record(snapshot, number=0, *, stage="calibration", label=0, status="human_verified"):
    return {"id": "fixture-" + str(number), "url": f"https://future-{number}.test/login?q=a",
            "domain": f"future-{number}.test", "campaign": "fixture-campaign-" + str(number),
            "collected_at": "2026-11-08T00:00:00Z" if stage == "calibration" else "2026-11-10T00:00:00Z",
            "source": "fixture-publisher-" + str(number % 2), "label": label,
            "label_status": status, "label_scope": "url_risk", "tier": "declared_fixture",
            "reviewer_ids": ["fixture-reviewer-a", "fixture-reviewer-b"] if status == "human_verified" else [],
            "rationale": "Synthetic test fixture, not a human judgement.",
            "evidence": {"url": "https://primary.test/notice", "publisher": "Fixture primary publisher",
                         "kind": "primary", "published_at": "2026-11-07T00:00:00Z",
                         "snapshot_path": str(snapshot), "snapshot_sha256": sha(snapshot)}}


def build(tmp_path, rows, protocol):
    incoming = tmp_path / "incoming.jsonl"
    write_jsonl(incoming, rows)
    pack = tmp_path / "pack"
    result = prepare(protocol, incoming, pack, now=COLLECTED)
    return pack, result


def test_normalization_uses_hostname_private_psl_and_preserves_meaningful_path_query():
    assert normalize_url("HTTPS://EXAMPLE.COM.:443#fragment") == ("https://example.com/", "example.com")
    assert normalize_url("https://name.github.io/a?next=https%3A%2F%2Fexternal.test/")[1] == "name.github.io"
    assert normalize_url("https://example.com@attacker.test/a")[1] == "attacker.test"
    assert normalize_url("https://example.com/a?q=1")[0] != normalize_url("https://example.com/a?q=2")[0]
    assert normalize_url("https://[2001:db8::1]:443/") == ("https://[2001:db8::1]/", "2001:db8::1")


@pytest.mark.parametrize("url", ["file:///etc/passwd", "https://example.com\\@evil.test/", " https://example.com", "https://a..test/", "https://example.com:invalid/",
                                  "http://127.1/a", "http://0177.0.0.1/a", "http://0x7f.0x0.0x0.0x1/a", "http://[fe80::1%25eth0]/"])
def test_ambiguous_or_unsupported_urls_fail_without_fetching(url):
    with pytest.raises(ValueError):
        normalize_url(url)


def test_requires_explicit_utc_and_registration_before_future_test(tmp_path):
    with pytest.raises(ValueError, match="UTC"):
        utc("2026-11-07T00:00:00")
    protocol, _ = registration(tmp_path)
    old = (protocol / "protocol.json").read_bytes()
    with pytest.raises(ValueError, match="new output"):
        register(protocol, exclusions=[], model_locks={}, corpus_lock="", thresholds="", collection_start="", cutoff="")
    assert (protocol / "protocol.json").read_bytes() == old
    late = tmp_path / "late"
    late.mkdir()
    with pytest.raises(ValueError, match="precede"):
        registration(late, now=COLLECTED)


def test_empty_incoming_is_explicitly_not_ready_and_test_metrics_blocked(tmp_path):
    protocol, _ = registration(tmp_path)
    pack, manifest = build(tmp_path, [], protocol)
    assert not manifest["readiness"]["ready"]
    assert manifest["accepted"] == manifest["excluded_historical"] == 0
    assert verify(pack)[0]["readiness"] == manifest["readiness"]
    predictions = tmp_path / "predictions.jsonl"
    write_jsonl(predictions, [])
    with pytest.raises(ValueError, match="blocked"):
        report(pack, predictions, tmp_path / "results", stage="test")


@pytest.mark.parametrize("field", ["policies", "test_cutoff", "exclusion_index", "quotas_per_stage"])
def test_registration_metadata_cannot_be_changed_before_prepare(tmp_path, field):
    protocol, snapshot = registration(tmp_path)
    path = protocol / "protocol.json"
    data = json.loads(path.read_text())
    if field == "policies":
        data[field]["candidate"]["high"] = .99
    elif field == "test_cutoff":
        data[field] = "2026-11-20T00:00:00Z"
    elif field == "exclusion_index":
        data[field]["domains"] = []
    else:
        data[field]["negative"] = 1
    write_json(path, data)
    with pytest.raises(ValueError, match="metadata changed"):
        build(tmp_path, [record(snapshot)], protocol)


def test_copied_policies_are_checked_against_threshold_source(tmp_path):
    protocol, snapshot = registration(tmp_path)
    path = protocol / "protocol.json"
    data = json.loads(path.read_text())
    data["policies"]["candidate"]["high"] = .99
    write_json(path, data)
    # A sidecar is not an authentication boundary. Even rewriting it cannot
    # silently disagree with the separately locked threshold source.
    (protocol / "protocol.json.sha256").write_text(sha(path))
    with pytest.raises(ValueError, match="threshold source"):
        build(tmp_path, [record(snapshot)], protocol)


def test_provisional_records_do_not_satisfy_human_gate_and_blind_sheet_has_no_labels_scores(tmp_path):
    protocol, snapshot = registration(tmp_path)
    pack, manifest = build(tmp_path, [record(snapshot, status="external_source_provisional")], protocol)
    assert manifest["readiness"]["stages"]["calibration"]["provisional_records"] == 1
    assert not manifest["readiness"]["ready"]
    import csv
    with (pack / "calibration_blind_review.csv").open(encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        assert not {"score", "label_status", "model", "source_label"} & set(reader.fieldnames)
        row = next(reader)
    assert row["label"] == row["rationale"] == row["reviewer_id"] == ""


@pytest.mark.parametrize("change,match", [
    ({"label_status": "ai_gold"}, "status/scope"),
    ({"label_scope": "official_origin_reference", "label": 0}, "Official origin"),
    ({"reviewer_ids": ["same", "same"]}, "distinct"),
    ({"reviewer_ids": ["only-one"]}, "two declared"),
    ({"domain": "different.test"}, "Declared domain"),
    ({"collected_at": "2026-11-20T00:00:00Z"}, "future"),
    ({"score": .9}, "unknown fields"),
    ({"source": "source "}, "unpadded"),
    ({"campaign": "campaign "}, "unpadded"),
    ({"reviewer_ids": ["alice", " alice"]}, "distinct"),
    ({"reviewer_ids": ["alice", "Alice"]}, "distinct"),
])
def test_metadata_must_not_manufacture_gold_or_leak_predictions(tmp_path, change, match):
    protocol, snapshot = registration(tmp_path)
    row = {**record(snapshot), **change}
    with pytest.raises(ValueError, match=match):
        build(tmp_path, [row], protocol)
    assert not (tmp_path / "pack").exists()


def test_official_origin_reference_never_counts_as_benign(tmp_path):
    protocol, snapshot = registration(tmp_path)
    row = {**record(snapshot), "label_scope": "official_origin_reference", "label": None}
    _, manifest = build(tmp_path, [row], protocol)
    status = manifest["readiness"]["stages"]["calibration"]
    assert status["official_origin_references"] == 1
    assert not status["verified_class_counts"]


def test_historical_domain_and_campaign_are_excluded_as_regression_not_future_data(tmp_path):
    protocol, snapshot = registration(tmp_path)
    rows = [record(snapshot, 0), record(snapshot, 1)]
    rows[0].update(url="https://new.old-train.test/new-path", domain="old-train.test")
    rows[1]["campaign"] = "old-adaptive"
    pack, manifest = build(tmp_path, rows, protocol)
    assert manifest["accepted"] == 0 and manifest["excluded_historical"] == 2
    excluded = [json.loads(line) for line in (pack / "excluded_regression.jsonl").read_text().splitlines()]
    assert excluded[0]["exclusion_reasons"] == ["domains"]
    assert excluded[1]["exclusion_reasons"] == ["campaigns"]


@pytest.mark.parametrize("shared", ["domain", "campaign"])
def test_domain_campaign_isolation_is_enforced_before_export(tmp_path, shared):
    protocol, snapshot = registration(tmp_path)
    a, b = record(snapshot, 0), record(snapshot, 1, stage="test")
    if shared == "domain":
        b.update(url=a["url"] + "&different=true", domain=a["domain"])
    else:
        b["campaign"] = a["campaign"]
    with pytest.raises(ValueError, match="Cross-stage"):
        build(tmp_path, [a, b], protocol)


def test_duplicate_domains_do_not_inflate_quota(tmp_path):
    protocol, snapshot = registration(tmp_path)
    a, b = record(snapshot, 0), record(snapshot, 1)
    b.update(url=a["url"] + "&different=true", domain=a["domain"])
    with pytest.raises(ValueError, match="one URL per"):
        build(tmp_path, [a, b], protocol)


@pytest.mark.parametrize("mutation", ["snapshot", "weights", "corpus", "records", "added_weight"])
def test_evidence_model_corpus_and_export_hashes_are_checked(tmp_path, mutation):
    protocol, snapshot = registration(tmp_path)
    pack, _ = build(tmp_path, [record(snapshot)], protocol)
    target = {"snapshot": snapshot, "weights": tmp_path / "model/weights.bin", "corpus": tmp_path / "corpus.jsonl", "records": pack / "records.jsonl", "added_weight": tmp_path / "model/new.bin"}[mutation]
    target.write_bytes((target.read_bytes() if target.exists() else b"") + b"changed")
    with pytest.raises(ValueError, match="changed"):
        verify(pack)


def test_empty_or_unmatched_evidence_is_rejected(tmp_path):
    protocol, snapshot = registration(tmp_path)
    row = record(snapshot)
    row["evidence"]["snapshot_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="hash"):
        build(tmp_path, [row], protocol)


def test_frozen_report_counts_errors_unknown_and_keeps_provisional_separate(tmp_path):
    protocol, snapshot = registration(tmp_path)
    rows = [record(snapshot, 0, label=1), record(snapshot, 1, label=0),
            record(snapshot, 2, label=1, status="external_source_provisional")]
    pack, _ = build(tmp_path, rows, protocol)
    predictions = tmp_path / "predictions.jsonl"
    write_jsonl(predictions, [{"id": row["id"], "model": "candidate", "status": "error" if i == 0 else "ok", "score": None if i == 0 else .9} for i, row in enumerate(rows)])
    result = report(pack, predictions, tmp_path / "results")
    human = result["metrics"]["candidate"]["human_verified"]
    provisional = result["metrics"]["candidate"]["external_source_provisional"]
    assert human["unknown_positive"] == 1 and human["recall"] == 0 and human["fp"] == 1
    assert provisional["tp"] == 1 and provisional["n"] == 1
    assert human["fpr_wilson95"]["n"] == 1
    assert "prior-sensitivity" in result["caveat"]
    assert provisional["precision"] is None and provisional["f1"] is None


def test_source_diversity_human_gate_and_campaign_unknown_block_readiness(tmp_path):
    protocol, snapshot = registration(tmp_path)
    rows = [record(snapshot, i, label=(i // 2) % 2, stage="calibration" if i < 4 else "test") for i in range(8)]
    pack, manifest = build(tmp_path, rows, protocol)
    assert manifest["readiness"]["ready"]
    assert verify(pack)[0]["readiness"]["ready"]
    changed = deepcopy(rows)
    changed[0]["campaign"] = None
    other = tmp_path / "unknown.jsonl"
    write_jsonl(other, changed)
    new = prepare(protocol, other, tmp_path / "unknown-pack", now=COLLECTED)
    assert "unresolved_campaign_isolation" in new["readiness"]["stages"]["calibration"]["blockers"]
    same_source = deepcopy(rows)
    for row in same_source:
        row["source"] = "one-source"
    source_input = tmp_path / "same-source.jsonl"
    write_jsonl(source_input, same_source)
    new = prepare(protocol, source_input, tmp_path / "same-source-pack", now=COLLECTED)
    assert "insufficient_class_source_diversity" in new["readiness"]["stages"]["test"]["blockers"]
