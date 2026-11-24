"""Human-review integrity tests use invented IDs/text, never actual human labels."""
import csv
import json
from pathlib import Path

import pytest

from evaluation.data import human_review as review


def write_csv(path, rows, fields=None):
    fields = fields or list(rows[0])
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def packet(tmp_path, kind="classification", size=3):
    spec = review.SPECS[kind]
    rows = []
    for index in range(size):
        row = {field: f"Synthetic {field} {index}" for field in review.INPUT_COLUMNS[kind]}
        for field in spec.keys:
            row[field] = f"{field}-{index}"
        row.update({field: "" for field in spec.mutable})
        rows.append(row)
    if kind == "injection":
        for row in rows:
            row["literal_verdict_command_result"] = "synthetic operator-only machine conclusion"
    source = tmp_path / "trusted_blank.csv"
    write_csv(source, rows)
    inventory = tmp_path / "packet"
    result = review.freeze(kind, source, inventory, review.digest(source), tmp_path / "operator.json")
    return inventory, result["manifest_sha256"], rows


def fill(row, kind, decisions, who="reviewer-A", basis="Evidence in synthetic fixture."):
    spec = review.SPECS[kind]
    row.update(dict(zip(spec.decisions, decisions)))
    row[spec.reviewer] = who
    row[spec.basis] = basis
    return row


def returned(tmp_path, inventory, patch_a=None, patch_b=None):
    paths = []
    for name, patch in (("a", patch_a), ("b", patch_b)):
        rows = sorted(read_csv(inventory / f"annotator_{name}.csv"), key=lambda row: tuple(row.values()))
        if patch:
            patch(rows)
        path = tmp_path / f"returned_{name}.csv"
        write_csv(path, rows)
        paths.append(path)
    return paths


def test_blank_reviews_remain_pending_and_not_perfect_agreement(tmp_path):
    inventory, anchor, original = packet(tmp_path)
    a, b = returned(tmp_path, inventory)
    result = review.reconcile(inventory, a, b, tmp_path / "status", anchor)
    assert result["states"] == {"PENDING_BOTH": 3, "A_ONLY": 0, "B_ONLY": 0, "AGREEMENT": 0, "DISAGREEMENT": 0}
    assert result["paired_completed"] == 0
    assert result["agreement_fraction"] is None
    assert result["agreement_by_axis"]["human_label"]["fraction"] is None
    assert result["human_labels_generated"] == result["adjudications_generated"] == 0
    assert result["gold_exported"] is False
    assert read_csv(tmp_path / "status/adjudication.csv") == []
    assert all(not row["human_label"] for row in read_csv(a) + read_csv(b))
    assert set(review.registered_inventory(tmp_path / "operator.json")) == {inventory.resolve(), anchor}


def test_partial_classification_statuses_and_no_auto_adjudication(tmp_path):
    inventory, anchor, _ = packet(tmp_path, size=4)
    def left(rows):
        for row in rows[:3]:
            fill(row, "classification", ["PHISHING"])
    def right(rows):
        fill(rows[0], "classification", ["PHISHING"], who="reviewer-B")
        fill(rows[1], "classification", ["INSUFFICIENT"], who="reviewer-B")
        fill(rows[3], "classification", ["BENIGN"], who="reviewer-B")
    a, b = returned(tmp_path, inventory, left, right)
    result = review.reconcile(inventory, a, b, tmp_path / "status", anchor)
    assert result["states"] == {"PENDING_BOTH": 0, "A_ONLY": 1, "B_ONLY": 1, "AGREEMENT": 1, "DISAGREEMENT": 1}
    assert result["paired_completed"] == 2 and result["agreement_fraction"] == .5
    adjudication = read_csv(tmp_path / "status/adjudication.csv")
    assert len(adjudication) == 1
    assert adjudication[0]["human_label_a"] == "PHISHING"
    assert adjudication[0]["human_label_b"] == "INSUFFICIENT"
    assert not adjudication[0]["adjudicated_human_label"]
    assert not adjudication[0]["adjudicator_id"]


def test_rag_two_axes_both_count_and_partial_row_is_not_complete(tmp_path):
    inventory, anchor, _ = packet(tmp_path, kind="rag", size=2)
    def left(rows):
        fill(rows[0], "rag", ["2", "1"])
        fill(rows[1], "rag", ["2", ""])
    def right(rows):
        fill(rows[0], "rag", ["2", "0"], who="reviewer-B")
        fill(rows[1], "rag", ["2", "2"], who="reviewer-B")
    a, b = returned(tmp_path, inventory, left, right)
    result = review.reconcile(inventory, a, b, tmp_path / "status", anchor)
    assert result["paired_completed"] == 1
    assert result["states"]["DISAGREEMENT"] == result["states"]["B_ONLY"] == 1
    assert result["agreement_by_axis"]["human_relevance_0_2"]["fraction"] == 1
    assert result["agreement_by_axis"]["human_support_0_2"]["fraction"] == 0
    assert any(row["progress_a"] == "IN_PROGRESS" for row in read_csv(tmp_path / "status/review_status.csv"))


def test_injection_composite_keys_allow_same_pair_across_arms(tmp_path):
    inventory, anchor, _ = packet(tmp_path, kind="injection", size=2)
    # A separately frozen fixture with the same pair and distinct arm IDs.
    fields, rows = review._csv(tmp_path / "trusted_blank.csv")
    rows[1]["pair_id"] = rows[0]["pair_id"]
    source = tmp_path / "two_arms.csv"
    write_csv(source, rows)
    other = tmp_path / "other_packet"
    frozen = review.freeze("injection", source, other, review.digest(source))
    def left(items):
        for row in items:
            fill(row, "injection", ["UNDETERMINED"])
            row["human_evidence_quote"] = "A synthetic raw output quote."
    def right(items):
        for row in items:
            fill(row, "injection", ["UNDETERMINED"], who="reviewer-B")
    a, b = returned(tmp_path, other, left, right)
    result = review.reconcile(other, a, b, tmp_path / "status", frozen["manifest_sha256"])
    assert result["states"]["AGREEMENT"] == 2
    assert result["status"] == "two_declared_reviewer_agreement_not_frozen_gold"
    assert read_csv(tmp_path / "status/review_status.csv")[0]["human_evidence_quote_a"]


@pytest.mark.parametrize("kind, label", [("classification", "1"), ("classification", "phishing"),
    ("rag", "3"), ("rag", "UNKNOWN"), ("injection", "TRUE")])
def test_invalid_labels_never_count_as_pending_or_valid(tmp_path, kind, label):
    inventory, anchor, _ = packet(tmp_path, kind=kind)
    a, b = returned(tmp_path, inventory, lambda rows: fill(rows[0], kind, [label]))
    with pytest.raises(ValueError, match="Invalid human"):
        review.reconcile(inventory, a, b, tmp_path / "status", anchor)
    assert not (tmp_path / "status").exists()


@pytest.mark.parametrize("field", ["evidence_basis", "reviewer_id"])
def test_entered_label_requires_basis_and_reviewer(tmp_path, field):
    inventory, anchor, _ = packet(tmp_path)
    def patch(rows):
        fill(rows[0], "classification", ["BENIGN"])
        rows[0][field] = "  "
    a, b = returned(tmp_path, inventory, patch)
    with pytest.raises(ValueError, match="requires a declared reviewer and evidence basis"):
        review.reconcile(inventory, a, b, tmp_path / "status", anchor)


@pytest.mark.parametrize("change", ["duplicate", "missing", "unknown"])
def test_exact_inventory_required_in_both_returned_sheets(tmp_path, change):
    inventory, anchor, _ = packet(tmp_path)
    def patch(rows):
        if change == "duplicate": rows.append(dict(rows[0]))
        if change == "missing": rows.pop()
        if change == "unknown": rows[0]["sample_id"] = "unregistered"
    a, b = returned(tmp_path, inventory, patch)
    with pytest.raises(ValueError, match="Duplicate|missing or unexpected"):
        review.reconcile(inventory, a, b, tmp_path / "status", anchor)


def test_editing_both_returned_texts_does_not_redefine_trusted_inventory(tmp_path):
    inventory, anchor, _ = packet(tmp_path)
    def patch(rows): rows[0]["text_redacted"] = "Changed in both mutable review copies."
    a, b = returned(tmp_path, inventory, patch, patch)
    with pytest.raises(ValueError, match="Frozen input changed"):
        review.reconcile(inventory, a, b, tmp_path / "status", anchor)


@pytest.mark.parametrize("target", ["manifest.json", "inventory.jsonl"])
def test_changed_frozen_inventory_is_rejected_even_when_sheets_match(tmp_path, target):
    inventory, anchor, _ = packet(tmp_path)
    a, b = returned(tmp_path, inventory)
    with (inventory / target).open("a", encoding="utf-8") as stream: stream.write("\n")
    with pytest.raises(ValueError, match="Frozen.*changed"):
        review.reconcile(inventory, a, b, tmp_path / "status", anchor)


@pytest.mark.parametrize("who", ["reviewer-A", "REVIEWER-a", "ｒｅｖｉｅｗｅｒ-Ａ"])
def test_same_declared_reviewer_is_rejected_before_pairing(tmp_path, who):
    inventory, anchor, _ = packet(tmp_path)
    a, b = returned(tmp_path, inventory,
        lambda rows: fill(rows[0], "classification", ["PHISHING"]),
        lambda rows: fill(rows[1], "classification", ["BENIGN"], who=who))
    with pytest.raises(ValueError, match="two distinct"):
        review.reconcile(inventory, a, b, tmp_path / "status", anchor)


def test_sheet_cannot_silently_mix_reviewers(tmp_path):
    inventory, anchor, _ = packet(tmp_path)
    def patch(rows):
        fill(rows[0], "classification", ["PHISHING"])
        fill(rows[1], "classification", ["BENIGN"], who="different-reviewer")
    a, b = returned(tmp_path, inventory, patch)
    with pytest.raises(ValueError, match="consistent reviewer"):
        review.reconcile(inventory, a, b, tmp_path / "status", anchor)


@pytest.mark.parametrize("kind, leaked", [("classification", "AI_label"), ("classification", "source_publisher"),
    ("classification", "prediction"), ("rag", "AI_support_grade"), ("rag", "risk_level")])
def test_packet_allowlist_rejects_unrequested_leaking_columns(tmp_path, kind, leaked):
    packet(tmp_path, kind=kind)
    fields, rows = review._csv(tmp_path / "trusted_blank.csv")
    for row in rows: row[leaked] = "hidden answer or prediction"
    source = tmp_path / "leaking.csv"
    write_csv(source, rows)
    with pytest.raises(ValueError, match="unexpected columns"):
        review.freeze(kind, source, tmp_path / "leaking_packet", review.digest(source))
    assert not (tmp_path / "leaking_packet").exists()


def test_freeze_requires_correct_source_hash_and_blank_human_columns(tmp_path):
    inventory, anchor, _ = packet(tmp_path)
    source = tmp_path / "trusted_blank.csv"
    with pytest.raises(ValueError, match="source changed"):
        review.freeze("classification", source, tmp_path / "bad", "0" * 64)
    fields, rows = review._csv(source)
    fill(rows[0], "classification", ["PHISHING"])
    write_csv(source, rows)
    with pytest.raises(ValueError, match="only blank"):
        review.freeze("classification", source, tmp_path / "bad", review.digest(source))


def test_outputs_and_operator_registration_are_never_overwritten(tmp_path):
    inventory, anchor, _ = packet(tmp_path)
    a, b = returned(tmp_path, inventory)
    review.reconcile(inventory, a, b, tmp_path / "status", anchor)
    before = review.digest(tmp_path / "status/summary.json")
    with pytest.raises(ValueError, match="Preserve prior"):
        review.reconcile(inventory, a, b, tmp_path / "status", anchor)
    assert review.digest(tmp_path / "status/summary.json") == before
    with pytest.raises(ValueError, match="outside"):
        review.freeze("classification", tmp_path / "trusted_blank.csv", tmp_path / "another",
                      review.digest(tmp_path / "trusted_blank.csv"), tmp_path / "operator.json")


def test_csv_export_escapes_formula_in_human_basis(tmp_path):
    inventory, anchor, _ = packet(tmp_path)
    a, b = returned(tmp_path, inventory,
        lambda rows: fill(rows[0], "classification", ["BENIGN"], basis="=untrusted spreadsheet formula"))
    review.reconcile(inventory, a, b, tmp_path / "status", anchor)
    row = next(row for row in read_csv(tmp_path / "status/review_status.csv") if row["status"] == "A_ONLY")
    assert row["basis_a"] == "'=untrusted spreadsheet formula"


def test_source_hash_and_parse_use_same_snapshot_even_if_original_autosaves(tmp_path, monkeypatch):
    packet(tmp_path)
    source = tmp_path / "trusted_blank.csv"
    source_before = source.read_bytes()
    original_parse = review._csv_bytes
    def changed_after_read(raw):
        source.write_text("An autosave changed the original file.", encoding="utf-8")
        return original_parse(raw)
    monkeypatch.setattr(review, "_csv_bytes", changed_after_read)
    out = tmp_path / "snapshot_packet"
    review.freeze("classification", source, out, review.hashlib.sha256(source_before).hexdigest())
    assert (out / "trusted_source.snapshot.csv").read_bytes() == source_before
    assert all("Synthetic" in row["text_redacted"] for row in original_parse((out / "annotator_a.csv").read_bytes())[1])


def test_returned_snapshot_provenance_is_not_hash_of_later_autosave(tmp_path, monkeypatch):
    inventory, anchor, _ = packet(tmp_path)
    a, b = returned(tmp_path, inventory)
    saved = a.read_bytes()
    original_read = review.read_returned
    def changed_after_parsed(path, *args):
        result = original_read(path, *args)
        if Path(path) == a:
            a.write_text("Later autosave, not the parsed review.", encoding="utf-8")
        return result
    monkeypatch.setattr(review, "read_returned", changed_after_parsed)
    out = tmp_path / "status"
    result = review.reconcile(inventory, a, b, out, anchor)
    assert result["provenance"]["returned_a_sha256"] == review.hashlib.sha256(saved).hexdigest()
    assert result["provenance"]["returned_a_sha256"] != review.digest(a)
    assert (out / "returned_a.snapshot.csv").read_bytes() == saved


def test_injection_packet_omits_computed_literal_judgment_from_human_forms(tmp_path):
    inventory, anchor, _ = packet(tmp_path, kind="injection")
    for name in ("annotator_a.csv", "annotator_b.csv"):
        assert "literal_verdict_command_result" not in read_csv(inventory / name)[0]
    manifest, _, _ = review.load_inventory(inventory, anchor)
    assert manifest["omitted_columns"] == ["literal_verdict_command_result"]


def test_injection_trusted_source_does_not_require_a_machine_conclusion(tmp_path):
    inventory, anchor, _ = packet(tmp_path, kind="injection")
    fields, rows = review._csv(tmp_path / "trusted_blank.csv")
    for row in rows:
        row.pop("literal_verdict_command_result")
    source = tmp_path / "blank_without_machine_result.csv"
    write_csv(source, rows)
    new_packet = tmp_path / "without_machine_result"
    frozen = review.freeze("injection", source, new_packet, review.digest(source))
    manifest, _, _ = review.load_inventory(new_packet, frozen["manifest_sha256"])
    assert manifest["omitted_columns"] == []
    assert "literal_verdict_command_result" not in read_csv(new_packet / "annotator_a.csv")[0]
    result = review.reconcile(new_packet, new_packet / "annotator_a.csv", new_packet / "annotator_b.csv",
        tmp_path / "without_machine_result_status", frozen["manifest_sha256"])
    assert result["paired_completed"] == 0 and result["states"]["PENDING_BOTH"] == 3
