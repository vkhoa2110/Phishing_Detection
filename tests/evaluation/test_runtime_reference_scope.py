"""Integrate real human-review seals with the runner, using synthetic fixtures.

The source-backed supplement verifier has its own suite; here a minimal pack
hash gate isolates registration/mapping behavior. No actual human labels, model
loads, .env reads, or provider requests are needed for these tests.
"""
import csv
import json
from pathlib import Path

import pytest

from evaluation import project_readiness
from evaluation.data import adjudicated_reference as reference
from evaluation.data import evidence_supplement, human_review
from evaluation.messages import runtime_evaluation as runtime


def write_json(path, value):
    Path(path).write_text(json.dumps(value) + "\n", encoding="utf-8")


def write_jsonl(path, rows):
    Path(path).write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def write_csv(path, rows, fields=None):
    with Path(path).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def fixture_pack(directory, monkeypatch):
    directory.mkdir()
    cases = [{"id": "case-" + name, "text": "Synthetic visible message " + name,
              "split": "dev" if name != "C" else "holdout", "urls": ["https://example.test"] if name == "A" else [],
              "group_id": "group-" + name, "label": 0 if name == "A" else 1,
              "behavior_label": 0 if name == "A" else 1} for name in ("A", "B", "C")]
    # The intentionally contradictory design references must never supply the
    # runner's reference_label; the final synthetic review seal is authoritative.
    review_rows = [{"sample_id": "RV-" + name, "text_redacted": case["text"], "human_label": "",
                    "evidence_basis": "", "reviewer_id": "", "notes": ""}
                   for name, case in zip(("A", "B", "C"), cases)]
    blank = directory / "blank.csv"
    write_csv(blank, review_rows)
    packet, registration = directory / "human_review", directory / "human_review.registration.json"
    review = human_review.freeze("classification", blank, packet, human_review.digest(blank), registration)
    write_json(directory / "manifest.json", {"review_packet": review})
    write_jsonl(directory / "cases.jsonl", cases)
    write_jsonl(directory / "review_ID_key_OPERATOR_ONLY.jsonl",
                [{"sample_id": r["sample_id"], "case_id": c["id"]} for r, c in zip(review_rows, cases)])
    write_json(directory / "counts.json", {"base_cases": 3, "injection_variants": 0, "received_original_messages": 0})
    write_json(directory / "readiness.json", {"test_status": "locked_author_exposed_holdout_not_independent_blind"})
    write_json(directory / "corpus_overlap.json", {"sources": {}})
    def validate_pack(path, *, manifest_sha256):
        if human_review.digest(Path(path) / "manifest.json") != manifest_sha256:
            raise ValueError("Synthetic pack manifest changed.")
        return {"verified": True, "cases": 3, "sources": 0}
    monkeypatch.setattr(evidence_supplement, "verify", validate_pack)
    return directory, human_review.digest(directory / "manifest.json")


def fixture_reference(pack, out):
    """Create declared review fixtures solely inside pytest's temporary storage."""
    packet = pack / "human_review"
    a, b = out.parent / (out.name + "_a.csv"), out.parent / (out.name + "_b.csv")
    for target, who in ((a, "fixture-human-A"), (b, "fixture-human-B")):
        with (packet / "annotator_a.csv").open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        for row in rows:
            row.update(human_label={"RV-A": "PHISHING", "RV-B": "BENIGN", "RV-C": "INSUFFICIENT"}[row["sample_id"]],
                       evidence_basis="Synthetic fixture evidence.", reviewer_id=who)
        write_csv(target, rows)
    templates = out.parent / (out.name + "_templates")
    registration = pack / "human_review.registration.json"
    reference.init_review(registration, a, b, templates)
    attestation = templates / "attestation.json"
    data = json.loads(attestation.read_text())
    data.update(human_origin_confirmed=True, reviewer_independence_attested=True,
                operator_id="fixture-operator", reviewer_a_id="fixture-human-A", reviewer_b_id="fixture-human-B")
    write_json(attestation, data)
    reference.finalize(registration, a, b, attestation, templates / "adjudication.csv", out)
    return out, human_review.digest(out / "manifest.json")


@pytest.fixture
def pack(tmp_path, monkeypatch):
    return fixture_pack(tmp_path / "pack", monkeypatch)


def deny_model_and_environment(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Missing/invalid human references must stop before app, models, settings or providers.")
    monkeypatch.setattr(runtime, "create_app", denied)
    monkeypatch.setattr(runtime, "Settings", denied)


def test_real_review_seal_supplies_dev_labels_and_never_uses_scenario_labels(pack, tmp_path):
    frozen, pack_sha = pack
    sealed, ref_sha = fixture_reference(frozen, tmp_path / "reference")
    rows = runtime._scope(frozen, pack_sha, sealed, ref_sha)
    assert [row["id"] for row in rows] == ["case-A", "case-B"]
    assert [row["reference_label"] for row in rows] == ["PHISHING", "BENIGN"]
    assert [row["has_URL"] for row in rows] == [True, False]
    assert all(row["id"] != "case-C" for row in rows)
    assert all("label" not in row and "behavior_label" not in row for row in rows)


@pytest.mark.parametrize("wrong", ["missing", "blank_inventory", "bad_reference_anchor"])
def test_prepare_rejects_missing_or_provisional_reference_before_any_app_work(pack, tmp_path, monkeypatch, wrong):
    frozen, pack_sha = pack
    sealed, ref_sha = fixture_reference(frozen, tmp_path / "reference")
    if wrong == "missing": sealed = tmp_path / "never_created"
    if wrong == "blank_inventory":
        sealed = frozen / "human_review"
        ref_sha = human_review.digest(sealed / "manifest.json")
    if wrong == "bad_reference_anchor": ref_sha = "0" * 64
    deny_model_and_environment(monkeypatch)
    out = tmp_path / "run"
    with pytest.raises((ValueError, FileNotFoundError)):
        runtime.prepare(out, frozen, pack_sha, sealed, ref_sha)
    assert not out.exists()


def test_blank_reviews_cannot_form_a_reference_even_with_a_completed_attestation(pack, tmp_path, monkeypatch):
    frozen, _ = pack
    packet = frozen / "human_review"
    templates = tmp_path / "templates"
    registration = frozen / "human_review.registration.json"
    result = reference.init_review(registration, packet / "annotator_a.csv", packet / "annotator_b.csv", templates)
    data = json.loads((templates / "attestation.json").read_text())
    data.update(human_origin_confirmed=True, reviewer_independence_attested=True,
                operator_id="fixture-operator", reviewer_a_id="fixture-A", reviewer_b_id="fixture-B")
    write_json(templates / "attestation.json", data)
    deny_model_and_environment(monkeypatch)
    with pytest.raises(ValueError, match="Every frozen sample"):
        reference.finalize(registration, packet / "annotator_a.csv", packet / "annotator_b.csv",
                           templates / "attestation.json", templates / "adjudication.csv", tmp_path / "reference")
    assert result["paired_completed"] == 0 and result["agreement_fraction"] is None
    assert not (tmp_path / "reference").exists()


def test_even_identical_text_and_ids_cannot_import_reviews_from_another_frozen_packet(pack, tmp_path, monkeypatch):
    frozen, pack_sha = pack
    other, _ = fixture_pack(tmp_path / "different_packet", monkeypatch)
    sealed, ref_sha = fixture_reference(other, tmp_path / "reference")
    deny_model_and_environment(monkeypatch)
    with pytest.raises(ValueError, match="different frozen packet"):
        runtime.prepare(tmp_path / "run", frozen, pack_sha, sealed, ref_sha)


@pytest.mark.parametrize("change", ["duplicate_case_mapping", "unknown_sample_mapping", "missing_mapping", "text_changed"])
def test_scope_checks_exact_mapping_and_reviewed_input_after_validating_seal(pack, tmp_path, change):
    frozen, pack_sha = pack
    sealed, ref_sha = fixture_reference(frozen, tmp_path / "reference")
    if change == "text_changed":
        rows = [json.loads(line) for line in (frozen / "cases.jsonl").read_text().splitlines()]
        rows[0]["text"] += " An unreviewed change."
        write_jsonl(frozen / "cases.jsonl", rows)
    else:
        path = frozen / "review_ID_key_OPERATOR_ONLY.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        if change == "duplicate_case_mapping": rows[0]["case_id"] = rows[1]["case_id"]
        if change == "unknown_sample_mapping": rows[0]["sample_id"] = "RV-outside-frozen-inventory"
        if change == "missing_mapping": rows.pop()
        write_jsonl(path, rows)
    with pytest.raises(ValueError, match="mapping|text differs"):
        runtime._scope(frozen, pack_sha, sealed, ref_sha)


def test_project_readiness_calls_real_reference_verifier_with_compatible_keyword(pack, tmp_path):
    frozen, pack_sha = pack
    sealed, ref_sha = fixture_reference(frozen, tmp_path / "reference")
    result = project_readiness.check(frozen, pack_sha, final_reference=sealed, reference_sha=ref_sha)
    assert result["ready_for_runtime_evaluation"] is True
    assert result["annotation"]["completed_human_labels"] == 3
    assert result["ready_for_independent_quality_claim"] is False
    assert result["ready_for_release"] is False
    assert result["provider_calls_by_this_check"] == result["labels_generated"] == 0
