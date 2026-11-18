import json

import pytest

from evaluation.url import intake_audit as audit


@pytest.fixture
def inputs(tmp_path):
    source = tmp_path / "before.py"
    source.write_text('VERSION = "fixture-before"\ndef inspect_url_intake(text, mode):\n    return {"urls": [], "invalid_urls": []}\n')
    protocol = tmp_path / "protocol.json"
    locks = {name: audit.sha(audit.ROOT / name) for name in (
        "app/services/url/parsing.py", "app/services/url/authority.py")}
    locks["app/services/url/intake.py"] = audit.sha(source)
    audit.write_json(protocol, {"source_before_sha256": locks})
    cases = tmp_path / "cases.jsonl"
    cases.write_bytes(audit.DEFAULT_CASES.read_bytes())
    return {"before_source": source, "before_sha256": audit.sha(source),
            "before_protocol": protocol, "cases_path": cases, "dev_pack": None,
            "out": tmp_path / "result"}


def test_audit_records_contracts_and_seals_reference_without_quality_claim(inputs):
    summary = audit.run(**inputs)
    assert summary["contract_cases"] == summary["after_matches_current_contract"] == 32
    assert summary["new_phishing_quality_metrics"] is None
    assert summary["live_provider_calls"] == summary["model_inference_calls"] == 0
    manifest = json.loads((inputs["out"] / "manifest.json").read_text())
    resource = "app/services/url/resources/iana_tlds.txt"
    assert manifest["source_sha256"][resource] == audit.sha(audit.ROOT / resource)
    for name, digest in manifest["artifacts_sha256"].items():
        assert audit.sha(inputs["out"] / name) == digest


def test_old_source_changes_are_rejected_before_writing_output(inputs):
    inputs["before_source"].write_text("VERSION = 'tampered'\n")
    with pytest.raises(ValueError, match="source hash changed"):
        audit.run(**inputs)
    assert not inputs["out"].exists()


def test_shared_dependency_hash_mismatch_blocks_old_source_replay(inputs):
    value = json.loads(inputs["before_protocol"].read_text())
    value["source_before_sha256"]["app/services/url/parsing.py"] = "bad-pin"
    audit.write_json(inputs["before_protocol"], value)
    with pytest.raises(ValueError, match="shared dependency changed"):
        audit.run(**inputs)


def test_audit_never_overwrites_previous_output(inputs):
    inputs["out"].mkdir()
    sentinel = inputs["out"] / "previous.txt"
    sentinel.write_text("retained")
    with pytest.raises(ValueError, match="new output"):
        audit.run(**inputs)
    assert sentinel.read_text() == "retained"


@pytest.mark.parametrize("mutation", ["duplicate_id", "phishing_gold"])
def test_contract_inventory_rejects_duplicates_and_phishing_labels(inputs, mutation):
    rows = audit.read_jsonl(inputs["cases_path"])
    if mutation == "duplicate_id":
        rows[1]["id"] = rows[0]["id"]
    else:
        rows[0]["phishing_label"] = 1
    inputs["cases_path"].write_text("".join(json.dumps(row) + "\n" for row in rows))
    with pytest.raises(ValueError):
        audit.run(**inputs)


def test_contract_mismatch_remains_a_failure_in_export(inputs):
    rows = audit.read_jsonl(inputs["cases_path"])
    rows[0]["expected_urls"] = ["https://deliberately-wrong.example/"]
    inputs["cases_path"].write_text("".join(json.dumps(row) + "\n" for row in rows))
    result = audit.run(**inputs)
    assert result["current_failed_ids"] == [rows[0]["id"]]
    assert result["after_matches_current_contract"] == 31


def test_dev_sms_cannot_be_modified_after_its_manifest(tmp_path):
    sms = tmp_path / "sms.jsonl"
    sms.write_text("".join(json.dumps({"id": str(i), "text": "Thông báo họp."}) + "\n" for i in range(80)))
    audit.write_json(tmp_path / "manifest.json", {"files": {"sms.jsonl": audit.sha(sms)}})
    assert len(audit.known_dev(tmp_path)) == 80
    sms.write_text(sms.read_text() + "\n")
    with pytest.raises(ValueError, match="hash changed"):
        audit.known_dev(tmp_path)


def test_dev_sms_requires_exact_eighty_unique_ids(tmp_path):
    sms = tmp_path / "sms.jsonl"
    sms.write_text("".join(json.dumps({"id": "duplicate", "text": "Thông báo họp."}) + "\n" for _ in range(80)))
    audit.write_json(tmp_path / "manifest.json", {"files": {"sms.jsonl": audit.sha(sms)}})
    with pytest.raises(ValueError, match="eighty unique"):
        audit.known_dev(tmp_path)
