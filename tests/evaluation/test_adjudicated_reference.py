"""Synthetic operator/reviewer fixtures test sealing; these are not human labels."""
import csv
import json
from pathlib import Path

import pytest

from evaluation.data import adjudicated_reference as ref
from evaluation.data import human_review as review


def csv_write(path, rows, fields=None):
    with Path(path).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def csv_read(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def json_write(path, obj):
    Path(path).write_text(json.dumps(obj) + "\n", encoding="utf-8")


def fixture(tmp_path, *, complete=True, disagreement=True):
    rows = [{"sample_id": f"RV-{index:024d}", "text_redacted": f"Synthetic visible message {index}.",
             "human_label": "", "evidence_basis": "", "reviewer_id": "", "notes": ""} for index in range(3)]
    source = tmp_path / "blank.csv"
    csv_write(source, rows)
    packet, registration = tmp_path / "packet", tmp_path / "operator.registration.json"
    review.freeze("classification", source, packet, review.digest(source), registration)
    labels = ("PHISHING", "BENIGN", "INSUFFICIENT")
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    for dest, who in ((a, "fixture-A"), (b, "fixture-B")):
        returned = [dict(row) for row in rows]
        for index, row in enumerate(returned):
            if complete or index != 2:
                label = "BENIGN" if dest == b and index == 2 and disagreement else labels[index]
                row.update(human_label=label, evidence_basis="Synthetic fixture basis only.", reviewer_id=who)
        csv_write(dest, list(reversed(returned)) if dest == b else returned)
    template = tmp_path / "templates"
    ref.init_review(registration, a, b, template)
    attestation = template / "attestation.json"
    attest = json.loads(attestation.read_text())
    attest.update(human_origin_confirmed=True, reviewer_independence_attested=True,
                  operator_id="fixture-operator", reviewer_a_id="fixture-A", reviewer_b_id="fixture-B")
    json_write(attestation, attest)
    adjudication = template / "adjudication.csv"
    decisions = csv_read(adjudication)
    for row in decisions:
        row.update(final_label="INSUFFICIENT", adjudication_basis="A synthetic manual evidence statement.",
                   adjudicator_id="fixture-adjudicator")
    csv_write(adjudication, decisions, ref.DECISION_FIELDS)
    return {"registration": registration, "a": a, "b": b, "attestation": attestation,
            "adjudication": adjudication, "out": tmp_path / "sealed"}


def sealed(tmp_path, **kwargs):
    args = fixture(tmp_path, **kwargs)
    manifest = ref.finalize(**args)
    return args, manifest, review.digest(args["out"] / "manifest.json")


def reseal(out, patch):
    manifest_path = out / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    patch(manifest)
    json_write(manifest_path, manifest)
    return review.digest(manifest_path)


def test_pending_init_preserves_blank_human_metadata_and_na_metrics(tmp_path):
    args = fixture(tmp_path, complete=False)
    # A new truly blank packet must not imply agreement or zero accuracy.
    inventory, _ = review.registered_inventory(args["registration"])
    out = tmp_path / "blank_templates"
    result = ref.init_review(args["registration"], inventory / "annotator_a.csv", inventory / "annotator_b.csv", out)
    assert result["rows"] == 3 and result["paired_completed"] == 0
    assert result["agreement_fraction"] is None
    assert result["finalized_reference_ready"] is False
    assert result["states"]["PENDING_BOTH"] == 3
    assert "accuracy" not in result
    attest = json.loads((out / "attestation.json").read_text())
    assert attest["human_origin_confirmed"] is attest["reviewer_independence_attested"] is False
    assert all(attest[key] == "" for key in ("operator_id", "reviewer_a_id", "reviewer_b_id"))
    assert csv_read(out / "adjudication.csv") == []
    assert all(not row["human_label"] for row in csv_read(inventory / "annotator_a.csv"))


def test_complete_disagreements_have_blank_manual_template_and_no_auto_label(tmp_path):
    args = fixture(tmp_path)
    out = tmp_path / "fresh_templates"
    readiness = ref.init_review(args["registration"], args["a"], args["b"], out)
    assert readiness["paired_completed"] == 3 and readiness["states"]["DISAGREEMENT"] == 1
    row, = csv_read(out / "adjudication.csv")
    assert (row["human_label_a"], row["human_label_b"]) == ("INSUFFICIENT", "BENIGN")
    assert not row["final_label"] and not row["adjudicator_id"] and not row["adjudication_basis"]


def test_roundtrip_all_three_labels_no_text_source_design_or_prediction_export(tmp_path):
    args, manifest, anchor = sealed(tmp_path)
    result = ref.verify(args["out"], anchor)
    assert result["verified"] is True and result["status"] == ref.STATUS
    assert result["scope"] == "visible_message_actions"
    assert result["rows"] == 3
    assert result["label_counts"] == {"PHISHING": 1, "BENIGN": 1, "INSUFFICIENT": 1}
    assert result["independently_authenticated"] is False
    assert manifest["agreements"] == 2 and manifest["manual_adjudications"] == 1
    assert result["inventory_manifest_sha256"] == review.digest(tmp_path / "packet/manifest.json")
    assert result["registration_sha256"] == review.digest(args["registration"])
    for row in result["labels"]:
        assert set(row) == {"sample_id", "label", "text_sha256", "resolution"}
        index = int(row["sample_id"].split("-")[1])
        assert row["text_sha256"] == review.text_digest(f"Synthetic visible message {index}.")
    assert result["labels"][2]["resolution"] == "manual_adjudication"


def test_agreements_require_attestation_but_no_manual_decision_rows(tmp_path):
    args, manifest, anchor = sealed(tmp_path, disagreement=False)
    assert manifest["manual_adjudications"] == 0 and manifest["agreements"] == 3
    assert csv_read(args["out"] / "adjudication.snapshot.csv") == []
    assert all(row["resolution"] == "agreement" for row in ref.verify(args["out"], anchor)["labels"])


def test_incomplete_pairs_cannot_be_finalized_even_with_true_attestation(tmp_path):
    args = fixture(tmp_path, complete=False)
    with pytest.raises(ValueError, match="Every frozen sample"):
        ref.finalize(**args)
    assert not args["out"].exists()


@pytest.mark.parametrize("field,value", [
    ("human_origin_confirmed", False), ("human_origin_confirmed", "true"),
    ("reviewer_independence_attested", 1), ("reviewer_independence_attested", False),
    ("operator_id", "  "), ("reviewer_a_id", ""), ("reviewer_b_id", "wrong-reviewer"),
    ("reviewer_b_id", "fixture-A"), ("scope", "historical_scenario_label"),
    ("version", "unregistered")])
def test_attestation_failures_do_not_write_a_reference(tmp_path, field, value):
    args = fixture(tmp_path)
    data = json.loads(args["attestation"].read_text())
    data[field] = value
    json_write(args["attestation"], data)
    with pytest.raises(ValueError, match="attest|Attest|operator|reviewer",):
        ref.finalize(**args)
    assert not args["out"].exists()


def test_attested_identity_normalization_matches_existing_review_rules(tmp_path):
    args = fixture(tmp_path)
    data = json.loads(args["attestation"].read_text())
    data["reviewer_a_id"] = " ＦＩＸＴＵＲＥ-Ａ "
    data["reviewer_b_id"] = "FIXTURE-b"
    json_write(args["attestation"], data)
    ref.finalize(**args)
    assert ref.verify(args["out"], review.digest(args["out"] / "manifest.json"))["verified"]


@pytest.mark.parametrize("leak", ["AI_label", "source", "prediction"])
def test_unrequested_attestation_fields_rejected(tmp_path, leak):
    args = fixture(tmp_path)
    data = json.loads(args["attestation"].read_text())
    data[leak] = "machine result"
    json_write(args["attestation"], data)
    with pytest.raises(ValueError, match="schema"):
        ref.finalize(**args)


@pytest.mark.parametrize("change", ["missing", "duplicate", "unknown", "agreement_override", "wrong_a", "wrong_b",
                                      "label", "empty_basis", "empty_adjudicator", "source_column"])
def test_manual_decisions_must_resolve_exact_conflicts_with_human_evidence(tmp_path, change):
    args = fixture(tmp_path)
    rows = csv_read(args["adjudication"])
    fields = list(ref.DECISION_FIELDS)
    if change == "missing": rows.clear()
    if change == "duplicate": rows.append(dict(rows[0]))
    if change == "unknown": rows[0]["sample_id"] = "RV-unregistered"
    if change == "agreement_override": rows[0]["sample_id"] = "RV-000000000000000000000000"
    if change == "wrong_a": rows[0]["human_label_a"] = "BENIGN"
    if change == "wrong_b": rows[0]["human_label_b"] = "PHISHING"
    if change == "label": rows[0]["final_label"] = "1"
    if change == "empty_basis": rows[0]["adjudication_basis"] = "  "
    if change == "empty_adjudicator": rows[0]["adjudicator_id"] = ""
    if change == "source_column":
        fields.append("AI_reference")
        rows[0]["AI_reference"] = "PHISHING"
    csv_write(args["adjudication"], rows, fields)
    with pytest.raises(ValueError, match="Manual|manual|Every"):
        ref.finalize(**args)
    assert not args["out"].exists()


@pytest.mark.parametrize("change", ["text", "AI_column", "duplicate_id", "same_person"])
def test_existing_frozen_review_validation_cannot_be_bypassed(tmp_path, change):
    args = fixture(tmp_path)
    rows = csv_read(args["b"])
    if change == "text": rows[0]["text_redacted"] = "Shared changed text cannot change the inventory."
    if change == "AI_column":
        for row in rows: row["AI_label"] = "BENIGN"
    if change == "duplicate_id": rows.append(dict(rows[0]))
    if change == "same_person":
        for row in rows: row["reviewer_id"] = "ＦＩＸＴＵＲＥ-Ａ"
    csv_write(args["b"], rows)
    with pytest.raises(ValueError):
        ref.finalize(**args)
    assert not args["out"].exists()


@pytest.mark.parametrize("target", ref.SEALED_FILES)
def test_sealed_snapshot_mutation_is_detected(tmp_path, target):
    args, _, anchor = sealed(tmp_path)
    with (args["out"] / target).open("ab") as stream:
        stream.write(b"\n")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        ref.verify(args["out"], anchor)


@pytest.mark.parametrize("target", ["operator.registration.json", "packet/manifest.json", "packet/inventory.jsonl"])
def test_original_operator_trust_anchors_must_remain_unchanged(tmp_path, target):
    args, _, anchor = sealed(tmp_path)
    with (tmp_path / target).open("ab") as stream:
        stream.write(b"\n")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        ref.verify(args["out"], anchor)


def test_reference_manifest_requires_external_pin_not_a_self_reported_hash(tmp_path):
    args, _, anchor = sealed(tmp_path)
    path = args["out"] / "manifest.json"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        ref.verify(args["out"], anchor)
    with pytest.raises(ValueError, match="anchor"):
        ref.verify(args["out"], None)


@pytest.mark.parametrize("change", ["label", "duplicate", "unknown", "text_sha256", "resolution", "source_label"])
def test_rehashed_export_still_must_replay_exact_human_decisions(tmp_path, change):
    args, _, _ = sealed(tmp_path)
    path = args["out"] / "reference.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    if change == "label": rows[0]["label"] = "BENIGN"
    if change == "duplicate": rows.append(dict(rows[0]))
    if change == "unknown": rows[0]["sample_id"] = "not-in-inventory"
    if change == "text_sha256": rows[0]["text_sha256"] = "0" * 64
    if change == "resolution": rows[2]["resolution"] = "agreement"
    if change == "source_label": rows[0]["scenario_label"] = "PHISHING"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    anchor = reseal(args["out"], lambda manifest: manifest["files_sha256"].update({"reference.jsonl": review.digest(path)}))
    with pytest.raises(ValueError, match="labels, mappings, counts"):
        ref.verify(args["out"], anchor)


def test_unregistered_helper_or_extra_manifest_fields_are_rejected(tmp_path):
    args, _, _ = sealed(tmp_path)
    anchor = reseal(args["out"], lambda manifest: manifest["helpers_sha256"].update({"evaluation/data/human_review.py": "0" * 64}))
    with pytest.raises(ValueError, match="helpers changed"):
        ref.verify(args["out"], anchor)
    anchor = reseal(args["out"], lambda manifest: manifest.update({"gold": True}))
    with pytest.raises(ValueError, match="gold/identity"):
        ref.verify(args["out"], anchor)


def test_duplicate_json_fields_cannot_hide_machine_supplied_attestation(tmp_path):
    args = fixture(tmp_path)
    raw = args["attestation"].read_text().rstrip()
    args["attestation"].write_text(raw[:-1] + ', "human_origin_confirmed": false}')
    with pytest.raises(ValueError, match="Duplicate JSON"):
        ref.finalize(**args)


def test_inputs_cannot_be_overwritten_and_returned_originals_are_not_modified(tmp_path):
    args, _, _ = sealed(tmp_path)
    before = {str(path): path.read_bytes() for path in args.values() if path.is_file()}
    with pytest.raises(ValueError, match="preserve"):
        ref.finalize(**args)
    with pytest.raises(ValueError, match="preserve"):
        ref.init_review(args["registration"], args["a"], args["b"], args["out"])
    assert before == {str(path): path.read_bytes() for path in args.values() if path.is_file()}


def test_nonclassification_packet_cannot_be_used_as_a_phishing_reference(tmp_path):
    source, packet, registration = tmp_path / "rag.csv", tmp_path / "rag", tmp_path / "registration.json"
    spec = review.SPECS["rag"]
    row = {key: "Synthetic " + key for key in review.INPUT_COLUMNS["rag"]}
    row.update({key: "" for key in spec.mutable})
    csv_write(source, [row])
    review.freeze("rag", source, packet, review.digest(source), registration)
    with pytest.raises(ValueError, match="classification"):
        ref.init_review(registration, packet / "annotator_a.csv", packet / "annotator_b.csv", tmp_path / "out")


@pytest.mark.parametrize("change", ["bool_count", "extra_class", "negative_rows", "fractional_agreements"])
def test_rehashed_manifest_cannot_falsify_denominator_types(tmp_path, change):
    args, _, _ = sealed(tmp_path)
    def patch(manifest):
        if change == "bool_count": manifest["label_counts"]["PHISHING"] = True
        if change == "extra_class": manifest["label_counts"]["AI_UNKNOWN"] = 0
        if change == "negative_rows": manifest["rows"] = -1
        if change == "fractional_agreements": manifest["agreements"] = 2.0
    anchor = reseal(args["out"], patch)
    with pytest.raises(ValueError, match="counts must"):
        ref.verify(args["out"], anchor)


def test_returned_snapshot_not_a_later_autosave_is_sealed(tmp_path, monkeypatch):
    args = fixture(tmp_path)
    original = args["a"].read_bytes()
    read_returned = review.read_returned
    def capture_then_autosave(path, *rest):
        result = read_returned(path, *rest)
        if Path(path) == args["a"]:
            Path(path).write_text("An editor replaced the input after the read snapshot.\n")
        return result
    monkeypatch.setattr(review, "read_returned", capture_then_autosave)
    ref.finalize(**args)
    assert args["a"].read_bytes() != original
    assert (args["out"] / "returned_a.snapshot.csv").read_bytes() == original
    assert ref.verify(args["out"], review.digest(args["out"] / "manifest.json"))["verified"]


def test_cli_init_reports_pending_and_finalize_returns_no_fabricated_labels(tmp_path, monkeypatch, capsys):
    import sys
    args = fixture(tmp_path)
    inventory, _ = review.registered_inventory(args["registration"])
    out = tmp_path / "cli_templates"
    monkeypatch.setattr(sys, "argv", ["adjudicated_reference", "init", "--registration", str(args["registration"]),
        "--a", str(inventory / "annotator_a.csv"), "--b", str(inventory / "annotator_b.csv"), "--out", str(out)])
    ref.main()
    assert json.loads(capsys.readouterr().out)["paired_completed"] == 0
    monkeypatch.setattr(sys, "argv", ["adjudicated_reference", "finalize", "--registration", str(args["registration"]),
        "--a", str(inventory / "annotator_a.csv"), "--b", str(inventory / "annotator_b.csv"), "--out", str(tmp_path / "bad"),
        "--attestation", str(out / "attestation.json"), "--adjudication", str(out / "adjudication.csv")])
    with pytest.raises(SystemExit) as exc:
        ref.main()
    assert exc.value.code == 2
    assert not (tmp_path / "bad").exists()
