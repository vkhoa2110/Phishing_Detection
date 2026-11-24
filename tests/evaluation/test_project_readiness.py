"""Evidence gates cannot turn blank reviews or software counts into quality."""
import csv
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from evaluation import project_readiness as readiness
from evaluation.data import evidence_supplement, human_review


def dump(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def pack(tmp_path, monkeypatch):
    root = tmp_path / "pack"
    root.mkdir()
    source = root / "blank.csv"
    with source.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=human_review.INPUT_COLUMNS["classification"] + human_review.SPECS["classification"].mutable)
        writer.writeheader()
        for identifier in ("A", "B", "C", "D"):
            writer.writerow({"sample_id": identifier, "text_redacted": "PRIVATE FIXTURE TEXT " + identifier})
    review = human_review.freeze("classification", source, root / "human_review", digest(source), root / "human_review.registration.json")
    rows = [
        {"id": "A", "text": "PRIVATE FIXTURE TEXT A", "split": "dev", "group_id": "shared", "label": 1, "behavior_label": 1, "urls": ["https://example.test"]},
        {"id": "B", "text": "PRIVATE FIXTURE TEXT B", "split": "dev", "group_id": "shared", "label": 1, "behavior_label": 1, "urls": ["https://example.test"]},
        {"id": "C", "text": "PRIVATE FIXTURE TEXT C", "split": "holdout", "group_id": "held", "label": 1, "behavior_label": None, "urls": ["https://example.test"]},
        {"id": "D", "text": "PRIVATE FIXTURE TEXT D", "split": "holdout", "group_id": "held", "label": 0, "behavior_label": 0, "urls": [], "base_id": "C"},
    ]
    (root / "cases.jsonl").write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    dump(root / "counts.json", {"base_cases": 3, "injection_variants": 1, "received_original_messages": 0,
        "quotas": [{"kind": "SMS", "shortfall": 2}, {"kind": "EMAIL", "shortfall": 0}]})
    dump(root / "readiness.json", {"test_status": "locked_author_exposed_holdout_not_independent_blind"})
    dump(root / "corpus_overlap.json", {"sources": {"S1": [{"document_id": "DOC1"}], "S2": []}})
    dump(root / "manifest.json", {"review_packet": review})
    # Exercise the gate/real frozen human inventory, without constructing a
    # source-backed supplement or importing inference services in a unit test.
    def verify(path, *, manifest_sha256):
        if manifest_sha256 != digest(Path(path) / "manifest.json"):
            raise ValueError("Pack anchor mismatch")
        return {"verified": True, "cases": 4, "sources": 2}
    monkeypatch.setattr(evidence_supplement, "verify", verify)
    return root, digest(root / "manifest.json"), review


def reference(monkeypatch, pack, *, wrong_text=False, wrong_packet=False):
    root, _, review = pack
    labels = [{"sample_id": name, "label": "PHISHING" if name in {"A", "B"} else "INSUFFICIENT",
        "text_sha256": human_review.text_digest("PRIVATE FIXTURE TEXT " + name), "resolution": "agreement"}
        for name in ("A", "B", "C", "D")]
    if wrong_text:
        labels[0]["text_sha256"] = "0" * 64
    verified = {"verified": True, "rows": 4, "labels": labels,
        "status": "declared_human_adjudicated_reference_not_independently_authenticated",
        "provenance": {"inventory_manifest_sha256": "0" * 64 if wrong_packet else review["manifest_sha256"]}}
    def verify(path, *, manifest_sha256):
        assert manifest_sha256 == "a" * 64
        return verified
    monkeypatch.setitem(sys.modules, "evaluation.data.adjudicated_reference", SimpleNamespace(verify=verify))
    return {"final_reference": root / "reference", "reference_sha": "a" * 64}


def checks(tmp_path, *, returncode=0, collect=False, failed=False, declared=None):
    directory = tmp_path / "checks"
    directory.mkdir()
    (directory / "junit.xml").write_text(
        '<testsuites><testsuite tests="2" failures="%d" errors="0" skipped="0">'
        '<testcase name="one">%s</testcase><testcase name="two"/></testsuite></testsuites>'
        % (int(failed), '<failure message="failed"/>' if failed else ""))
    data = {"command": ["python", "-m", "pytest"] + (["--collect-only"] if collect else []),
        "returncode": returncode, "junit": "junit.xml"}
    if declared is not None:
        data["tests"] = declared
    dump(directory / "checks.json", data)
    return directory / "checks.json"


def test_blank_reviews_are_ready_to_annotate_but_never_a_quality_claim(pack):
    result = readiness.check(*pack[:2])
    assert result["ready_for_human_annotation"] is True
    assert result["ready_for_runtime_evaluation"] is False
    assert result["ready_for_independent_quality_claim"] is False
    assert result["ready_for_release"] is False
    assert result["labels_generated"] == result["provider_calls_by_this_check"] == 0
    assert "human_reference_not_finalized" in result["blockers"]["runtime_evaluation"]
    assert result["annotation"]["completed_human_labels"] is None
    assert "PRIVATE FIXTURE TEXT" not in json.dumps(result)


def test_count_independent_components_not_number_of_similar_messages(pack):
    result = readiness.check(*pack[:2])
    assert result["data"]["components"]["dev"]["behavior_positive_URL_cases"] == 2
    assert result["data"]["components"]["dev"]["behavior_positive_URL_components"] == 1
    assert result["data"]["components"]["holdout"]["base_cases"] == 1
    assert result["data"]["components"]["holdout"]["scenario_positive_URL_cases"] == 1
    assert result["data"]["components"]["holdout"]["behavior_positive_URL_cases"] == 0
    assert result["data"]["source_overlap_count"] == 1
    assert result["data"]["source_overlap_denominator"] == 2
    assert result["data"]["collection_shortfalls"] == [{"kind": "SMS", "shortfall": 2}]


@pytest.mark.parametrize("anchor", [None, "a", "A" * 64, "0" * 64])
def test_bad_or_changed_pack_anchor_rejected(pack, anchor):
    with pytest.raises(ValueError):
        readiness.check(pack[0], anchor)


def test_wrong_annotation_packet_does_not_enable_review_gate(pack, tmp_path):
    registration = tmp_path / "registration.json"
    dump(registration, {"version": "human-review-registration-1.0", "inventory": str(pack[0] / "human_review"), "manifest_sha256": "0" * 64})
    with pytest.raises(ValueError):
        readiness.check(*pack[:2], registration=registration)


def test_finalized_reference_enables_dev_evaluation_only(pack, monkeypatch):
    result = readiness.check(*pack[:2], **reference(monkeypatch, pack))
    assert result["ready_for_runtime_evaluation"] is True
    assert result["ready_for_independent_quality_claim"] is False
    assert result["ready_for_release"] is False
    assert result["annotation"]["completed_human_labels"] == 4


@pytest.mark.parametrize("bad", ["wrong_text", "wrong_packet"])
def test_reference_must_match_exact_frozen_text_and_packet(pack, monkeypatch, bad):
    with pytest.raises(ValueError):
        readiness.check(*pack[:2], **reference(monkeypatch, pack, **{bad: True}))


def test_runtime_reference_cannot_be_swapped(pack, monkeypatch):
    ref = reference(monkeypatch, pack)
    monkeypatch.setitem(sys.modules, "evaluation.messages.runtime_evaluation", SimpleNamespace(verify=lambda *a, **kw: {
        "verified": True, "reference_sha256": "b" * 64, "split": "dev", "mode": "registered_runtime_development_evaluation"}))
    with pytest.raises(ValueError, match="differs"):
        readiness.check(*pack[:2], **ref, runtime_run=pack[0] / "runtime", run_sha="c" * 64)


@pytest.mark.parametrize("complete", [False, True])
def test_prepared_or_complete_dev_run_is_never_independent_quality(pack, monkeypatch, complete):
    ref = reference(monkeypatch, pack)
    monkeypatch.setitem(sys.modules, "evaluation.messages.runtime_evaluation", SimpleNamespace(verify=lambda *a, **kw: {
        "verified": True, "reference_sha256": ref["reference_sha"], "split": "dev", "complete": complete,
        "profile": "stable", "mode": "registered_runtime_development_evaluation"}))
    result = readiness.check(*pack[:2], **ref, runtime_run=pack[0] / "runtime", run_sha="c" * 64)
    assert result["runtime"]["complete"] is complete
    assert result["ready_for_runtime_evaluation"] is True
    assert not result["ready_for_independent_quality_claim"]
    assert not result["ready_for_release"]


def test_passing_junit_is_software_evidence_only(pack, tmp_path):
    path = checks(tmp_path, declared={"total": 2, "passed": 2, "failed": 0, "errors": 0})
    result = readiness.check(*pack[:2], checkslatest=path)
    assert result["software_verified"] is True
    assert result["software_checks"]["counts"]["passed"] == 2
    assert result["software_checks"]["current_worktree_verified"] is False
    assert not result["ready_for_runtime_evaluation"]
    assert not result["ready_for_release"]


@pytest.mark.parametrize("args", [{"returncode": 1}, {"failed": True}])
def test_failed_checks_remain_blocked_even_with_zero_returncode(pack, tmp_path, args):
    result = readiness.check(*pack[:2], checkslatest=checks(tmp_path, **args))
    assert result["software_verified"] is False


def test_collect_only_is_not_a_pass(pack, tmp_path):
    with pytest.raises(ValueError, match="Collect"):
        readiness.check(*pack[:2], checkslatest=checks(tmp_path, collect=True))


def test_inflated_reported_test_counts_rejected(pack, tmp_path):
    with pytest.raises(ValueError, match="differ"):
        readiness.check(*pack[:2], checkslatest=checks(tmp_path, declared={"passed": 1113}))


def test_tampered_junit_suite_counters_rejected(pack, tmp_path):
    path = checks(tmp_path)
    junit = path.parent / "junit.xml"
    junit.write_text(junit.read_text().replace('tests="2"', 'tests="1345"'))
    with pytest.raises(ValueError, match="counters"):
        readiness.check(*pack[:2], checkslatest=path)


def test_missing_final_reference_cannot_be_enabled_by_hash_only(pack):
    with pytest.raises(ValueError, match="requires"):
        readiness.check(*pack[:2], reference_sha="a" * 64)


def test_output_is_new_only_and_preserves_existing_evidence(pack, tmp_path):
    target = tmp_path / "new" / "check.json"
    result = readiness.check(*pack[:2], out=target)
    assert json.loads(target.read_text()) == result
    snapshot = target.read_bytes()
    with pytest.raises(ValueError, match="new"):
        readiness.check(*pack[:2], out=target)
    assert target.read_bytes() == snapshot


def test_cli_blocked_is_success_not_crash(pack, capsys):
    assert readiness.main(["--pack", str(pack[0]), "--pack-sha256", pack[1]]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "blocked"


def test_cli_invalid_hash_returns_json_error(pack, capsys):
    assert readiness.main(["--pack", str(pack[0]), "--pack-sha256", "0" * 64]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "invalid_evidence"
