"""Offline gate/reuse/report contracts; authored outputs do not measure quality."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from evaluation.data.sms import read_jsonl, write_jsonl
from evaluation.messages import verifier_study as study


@pytest.fixture
def inventory(tmp_path):
    sms = [{"id": f"case-{i}", "text": f"Approved message {i}."} for i in range(80)]
    sms[5]["text"] = sms[4]["text"]
    refs = [{"id": row["id"], "label": 1 if i < 4 else 0 if i < 58 else None} for i, row in enumerate(sms)]
    cfg = {"stage": "control", "model": "fixture", "metadata": {"arms": list(study.control.ARMS), "labels": "fixture"}}
    cells, requests, records = [], {}, {}
    for i, case in enumerate(sms):
        for a, arm in enumerate(study.control.ARMS):
            key = f"{case['id']}::{arm}"
            cells.append({"id": case["id"], "arm": arm, "request_key": key, "URL_context_available": i % 2 == 0})
            requests[("control", key)] = {"key": key, "text": case["text"], "payload": {"model": "fixture", "original_only": arm}}
            level = "HIGH" if i == 0 or (i in (4, 5) and a < 2) else "WARNING" if i == 60 and a == 2 else "LOW"
            parsed = {"status": "error", "code": "HTTP_503"} if i == 6 and a == 0 else {"status": "ok", "verdict": {"risk_level": level}}
            records[("control", key)] = {"parsed": parsed, "content": "original bytes", "usage": {"total_tokens": 10}}
    gates, rows = study.gate_cells(tmp_path / "control", cfg, requests, records, cells, sms, refs)
    return cfg, requests, records, cells, sms, refs, gates, rows


def decisions_for(rows):
    decisions = {}
    for row in rows:
        if row["text"] == "Approved message 0.":
            decision = {"status": "error", "code": "HTTP_429"}
        elif row["text"] == "Approved message 60.":
            decision = {"status": "ok", "assessment": "insufficient", "reason_code": "missing_context", "quotes": []}
        else:
            decision = {"status": "ok", "assessment": "ordinary_content", "reason_code": "routine_or_advertising", "quotes": [row["text"]]}
        decisions[row["key"]] = decision
    return decisions


def test_gate_uses_only_completed_alarms_and_aliases_identical_text_across_ids(inventory):
    cfg, requests, records, cells, sms, refs, gates, rows = inventory
    before = deepcopy((requests, records, cells))
    assert len(gates) == 240 and len(rows) == 3
    eligible = [gate for gate in gates if gate["eligible"]]
    assert len(eligible) == 8
    shared = {gate["verifier_key"] for gate in eligible if gate["id"] in {"case-4", "case-5"}}
    assert len(shared) == 1
    failed = next(g for g in gates if g["id"] == "case-6" and g["arm"] == study.control.ARMS[0])
    assert failed["original_status"] == "error" and failed["original_error"] == "HTTP_503"
    assert not failed["eligible"] and failed["verifier_key"] is None
    for row in rows:
        assert set(row) == {"key", "text", "payload"}
        assert set(json.loads(row["payload"]["messages"][1]["content"])) == {"text", "output_schema"}
    assert (requests, records, cells) == before
    assert all(g["original_record"] == records[(cfg["stage"], g["request_key"])] for g in gates)


@pytest.mark.parametrize("damage", ["missing_cell", "duplicate_cell", "changed_text", "wrong_reference"])
def test_invalid_inventory_or_changed_approved_text_stops_preparation(inventory, tmp_path, damage):
    cfg, requests, records, cells, sms, refs, _, _ = deepcopy(inventory)
    if damage == "missing_cell": cells.pop()
    elif damage == "duplicate_cell": cells[-1] = cells[0]
    elif damage == "changed_text": requests[("control", cells[0]["request_key"])]["text"] += " Changed."
    else: refs[0]["label"] = 0
    with pytest.raises(ValueError): study.gate_cells(tmp_path, cfg, requests, records, cells, sms, refs)


def test_conditional_metrics_keep_errors_and_all_four_positives_visible(inventory):
    *_, gates, requests = inventory
    before = deepcopy(gates)
    summary, rows = study.summarize(gates, decisions_for(requests))
    first = summary["arms"][study.control.ARMS[0]]
    assert first["all_58_binary"]["before"]["n"] == first["all_58_binary"]["after"]["n"] == 58
    assert first["all_58_binary"]["before"]["fp"] == 2
    assert first["all_58_binary"]["after"]["fp"] == 0
    assert first["all_58_binary"]["after"]["tp"] == 1
    assert first["all_58_binary"]["after"]["unknown_negative"] == 1
    assert first["alarm_transitions"]["FP_to_LOW"] == 2
    assert first["alarm_transitions"]["kept_technical_error"] == 1
    assert first["alarm_transitions"]["alarm_to_UNKNOWN"] == 0
    assert first["all_80"]["original_error_codes"] == {"HTTP_503": 1}
    assert first["unknown_22_reference"]["n"] == 22
    assert summary["arms"][study.control.ARMS[2]]["alarm_transitions"]["kept_insufficient"] == 1
    assert summary["unique_verifier_requests"] == 3 and summary["aliased_alarm_cells"] == 5
    assert len(summary["all_four_positive_cases"]) == 4
    assert summary["independent_accuracy"] is None
    assert gates == before
    assert all(row["revision"]["level"] == row["original_level"] for row in rows if not row["eligible"])


def test_prepare_locks_originals_and_registers_remaining_budget_with_fixed_pacing(inventory, tmp_path, monkeypatch):
    cfg, *_, gates, rows = inventory
    control_run, out = tmp_path / "control", tmp_path / "verifier"
    control_run.mkdir()
    (control_run / "summary.json").write_text(json.dumps({"usage_missing": 0}))
    lock = control_run / "locked.json"
    lock.write_text("{}"); captured = {}
    monkeypatch.setattr(study, "_control_snapshot", lambda _: (cfg, gates, rows, 12000, 100, [lock]))
    def register(path, requests, **kwargs):
        captured.update(kwargs); captured["rows"] = requests
        path.mkdir()
        return {"max_attempts": len(requests), "metadata": kwargs["metadata"]}
    monkeypatch.setattr(study.registered, "register", register)
    result = study.prepare(control_run, out)
    assert captured["token_budget"] == 287900 and captured["max_tokens"] == 1024
    assert result["workers"] == 1 and result["timeout_seconds"] == 45
    assert result["metadata"]["pilot_unique_requests"] == 3 and result["metadata"]["pacing_seconds"] == 4
    assert result["metadata"]["aliased_alarm_cells"] == 5
    assert lock in captured["locks"]
    aliases = read_jsonl(Path(result["metadata"]["inputs"]) / "aliases.jsonl")
    assert sum(len(alias["cells"]) for alias in aliases) == 8
    assert (out / "registration.sha256").exists()


def test_exhausted_budget_creates_no_artifact(inventory, tmp_path, monkeypatch):
    cfg, *_, gates, rows = inventory
    monkeypatch.setattr(study, "_control_snapshot", lambda _: (cfg, gates, rows, 300000, 0, []))
    with pytest.raises(ValueError, match="exhausted"): study.prepare(tmp_path / "control", tmp_path / "out")
    assert not (tmp_path / "out").exists() and not (tmp_path / "out_inputs").exists()


def test_zero_union_needs_no_registration_and_preserves_pass_through(inventory, tmp_path, monkeypatch):
    cfg, *_, gates, _ = deepcopy(inventory)
    for gate in gates:
        gate.update(eligible=False, verifier_key=None, original_level="LOW", original_status="ok", original_error=None)
    control_run = tmp_path / "control"
    control_run.mkdir()
    (control_run / "summary.json").write_text(json.dumps({"usage_missing": 0}))
    monkeypatch.setattr(study, "_control_snapshot", lambda _: (cfg, gates, [], 12, 0, []))
    monkeypatch.setattr(study.registered, "register", lambda *a, **k: pytest.fail("No registration for zero union"))
    reported = []
    monkeypatch.setattr(study, "report", lambda out: reported.append(out))
    out = tmp_path / "zero"
    result = study.prepare(control_run, out)
    assert result["max_attempts"] == 0 and reported == [out]
    assert not (out / "execution.json").exists()
    assert study.verify(out)["complete"]
    summary, projected = study.summarize(gates, {})
    assert all(r["revision"]["level"] == r["original_level"] for r in projected)
    assert summary["unique_verifier_requests"] == 0


def test_report_preserves_full_original_records_and_replays_gate_binding(inventory, tmp_path, monkeypatch):
    cfg, *_, gates, requests = inventory
    out, inputs = tmp_path / "out", tmp_path / "inputs"
    out.mkdir(); inputs.mkdir()
    write_jsonl(inputs / "gate_cells.jsonl", gates)
    metadata = {"inputs": str(inputs), "control_run": "control", "control_recorded_tokens": 120,
        "healthprobe_recorded_tokens": 0, "total_recorded_token_budget": 300000}
    decisions = decisions_for(requests)
    records = {(study.STAGE, key): {"parsed": value, "usage": {"total_tokens": 10}} for key, value in decisions.items()}
    monkeypatch.setattr(study, "verify", lambda _: {"complete": True})
    monkeypatch.setattr(study.registered, "load", lambda _: ({"metadata": metadata},
        {(study.STAGE, row["key"]): {**row, "request_sha256": "registered-identity"} for row in requests}))
    monkeypatch.setattr(study.registered, "checkpoints", lambda *a: ({}, records))
    monkeypatch.setattr(study, "_control_snapshot", lambda _: (cfg, gates, requests, 120, 0, []))
    result = study.report(out)
    assert result["operations"]["combined_recorded_tokens"] == 150
    assert result["operations"]["errors"] == {"HTTP_429": 1}
    assert not result["application_promoted"]
    saved = read_jsonl(out / "gate_results.jsonl")
    assert saved[0]["original_record"] == gates[0]["original_record"]
    assert (out / "verifier_report.json").exists()
