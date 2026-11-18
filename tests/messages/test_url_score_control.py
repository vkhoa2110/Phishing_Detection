from collections import Counter
from copy import deepcopy
import json

import pytest

from evaluation.common import registered
from evaluation.data.sms import sha, write_json, write_jsonl
from evaluation.messages import url_score_control as control


def metadata(index, *, url=None, score=None):
    score = .1 + index * .1 if score is None else score
    return {"id": f"URL-{index:02}", "url": url or f"https://host{index}.example/", "score": score,
            "risk_level": "LOW" if score < .5 else "UNKNOWN" if score < .8 else "HIGH",
            "warning_threshold": .8, "high_threshold": .8}


def inputs(*, multi=False):
    sms, prepared = [], {}
    for i in range(5):
        rows = [metadata(i + 1)] if i < 4 else []
        if multi and i == 0:
            rows.append(metadata(9))
        case_id = f"case-{i}"
        text = "Thông báo. " + " ".join(row["url"] for row in rows)
        sms.append({"id": case_id, "text": text})
        prepared[case_id] = {"real_metadata": rows,
            "raw_url_results": [{**row, "status": "ok"} for row in rows],
            "operating_url_results": [{**row, "status": "ok", "raw_risk_level": "WARNING"} for row in rows],
            "intake": {"urls": [row["url"] for row in rows]}}
    return sms, prepared


def test_cycle_transfers_entire_score_pack_preserves_distribution_and_receiver_identity():
    _, source = inputs(multi=True)
    before = deepcopy(source)
    changed, mapping = control.permute_metadata(source)
    assert source == before
    assert changed == control.permute_metadata(source)[0]
    assert len(mapping) == 5
    assert Counter(json.dumps(control._score_pack(row), sort_keys=True)
                   for case in source.values() for row in case["real_metadata"]) == Counter(
        json.dumps(control._score_pack(row), sort_keys=True)
        for case in changed.values() for row in case["permuted_metadata"])
    edges = {}
    for transfer in mapping:
        recipient = changed[transfer["receiver_case_id"]]["permuted_metadata"][transfer["receiver_index"]]
        donor = source[transfer["donor_case_id"]]["real_metadata"][transfer["donor_index"]]
        original = source[transfer["receiver_case_id"]]["real_metadata"][transfer["receiver_index"]]
        assert recipient == {"id": original["id"], "url": original["url"], **control._score_pack(donor)}
        assert recipient["url"] != donor["url"]
        assert transfer["donor_status"] == "ok"
        assert set(recipient) == set(control.METADATA_FIELDS)
        edges[(transfer["receiver_case_id"], transfer["receiver_index"])] = (
            transfer["donor_case_id"], transfer["donor_index"])
    node = next(iter(edges))
    visited = set()
    while node not in visited:
        visited.add(node)
        node = edges[node]
    assert len(visited) == len(mapping) and node == next(iter(edges))


def test_bad_or_unavailable_donor_cannot_enter_the_control():
    _, prepared = inputs()
    prepared["case-0"]["operating_url_results"][0]["status"] = "unavailable"
    with pytest.raises(ValueError, match="status-ok"):
        control.permute_metadata(prepared)
    _, prepared = inputs()
    prepared["case-0"]["real_metadata"][0]["raw_risk_level"] = "HIGH"
    with pytest.raises(ValueError, match="complete score pack"):
        control.permute_metadata(prepared)


def test_different_record_is_insufficient_when_donor_url_is_identical():
    _, prepared = inputs()
    for case in prepared.values():
        for row in case["real_metadata"] + case["operating_url_results"]:
            row["url"] = "https://same.example/"
    with pytest.raises(ValueError, match="different-URL cycle"):
        control.permute_metadata(prepared)


def test_equal_scores_stay_equal_instead_of_forcing_a_treatment_difference():
    _, prepared = inputs()
    for case in prepared.values():
        for row in case["real_metadata"] + case["operating_url_results"]:
            row.update(score=.1, risk_level="LOW")
    _, mapping = control.permute_metadata(prepared)
    assert all(row["score_unchanged"] and row["pack_unchanged"] for row in mapping)


def test_payloads_differ_only_in_metadata_and_missing_metadata_aliases_all_arms():
    sms, prepared = inputs(multi=True)
    prepared, mapping = control.permute_metadata(prepared)
    requests, cells, pilot_ids, pilot_count = control.requests_for(sms, prepared, "fixture")
    by_key = {r["key"]: r for r in requests}
    assert len(cells) == 15 and len(requests) == 13
    assert pilot_count == 12 and len(pilot_ids) == 4
    assert [r["case_id"] for r in requests[:12]] == [case_id for case_id in pilot_ids for _ in control.ARMS]
    for case in sms:
        selected = [cell for cell in cells if cell["id"] == case["id"]]
        if not prepared[case["id"]]["real_metadata"]:
            assert len({cell["request_key"] for cell in selected}) == 1
        common = []
        for cell in selected:
            payload = deepcopy(by_key[cell["request_key"]]["payload"])
            assert payload["thinking"] == {"type": "disabled"} and payload["max_tokens"] == 2048
            data = json.loads(payload["messages"][1]["content"])
            actual = data.pop("url_results", [])
            expected = [] if cell["arm"] == control.ARMS[0] else prepared[case["id"]][
                "real_metadata" if cell["arm"] == control.ARMS[1] else "permuted_metadata"]
            assert actual == expected
            payload["messages"][1]["content"] = data
            common.append(payload)
        assert common[0] == common[1] == common[2]
    shuffled, _, shuffled_pilot, _ = control.requests_for(list(reversed(sms)), prepared, "fixture")
    assert shuffled == requests and shuffled_pilot == pilot_ids
    assert len(mapping) == 5


@pytest.fixture
def frozen_scope(tmp_path, monkeypatch):
    pack, labels = tmp_path / "pack", tmp_path / "labels"
    pack.mkdir(); labels.mkdir()
    sms = [{"id": f"frozen-{i}", "text": f"Tin nhắn thứ {i}.", "dataset": "sms", "split": "dev"} for i in range(80)]
    refs = [{"id": case["id"], "label": 0 if i < 54 else 1 if i < 58 else None} for i, case in enumerate(sms)]
    write_jsonl(pack / "sms.jsonl", sms)
    write_jsonl(labels / "labels.jsonl", refs)
    sms_sha, refs_sha = sha(pack / "sms.jsonl"), sha(labels / "labels.jsonl")
    write_json(pack / "manifest.json", {"status": "development_only_not_gold", "reserve_inference": False,
        "files": {"sms.jsonl": sms_sha}})
    write_json(labels / "labels_manifest.json", {"status": "ai_preliminary_not_gold", "independent_human_gold": False,
        "reference_judge": "fixture_assistant", "label_file_sha256": refs_sha,
        "pack_manifest_sha256": sha(pack / "manifest.json")})
    monkeypatch.setattr(control, "KNOWN_SMS_SHA256", sms_sha)
    monkeypatch.setattr(control, "KNOWN_LABELS_SHA256", refs_sha)
    return pack, labels, sms, refs


def test_scope_rejects_reserve_and_altered_reference_before_scoring(frozen_scope):
    pack, labels, sms, refs = frozen_scope
    assert control.load_scope(pack, labels)[:2] == (sms, refs)
    sms[0]["split"] = "reserve"
    write_jsonl(pack / "sms.jsonl", sms)
    with pytest.raises(ValueError, match="no reserve"):
        control.load_scope(pack, labels)
    sms[0]["split"] = "dev"
    write_jsonl(pack / "sms.jsonl", sms)
    refs[0]["label"] = 1
    write_jsonl(labels / "labels.jsonl", refs)
    with pytest.raises(ValueError, match="reference unchanged"):
        control.load_scope(pack, labels)


def test_score_cases_scores_raw_intake_before_approved_filter_and_keeps_failures():
    class LocalModel:
        calls = []
        def load(self): return {"ready": True}
        def predict(self, urls):
            self.calls.append(list(urls))
            return [{"id": f"URL-{i:02}", "url": url, "status": "ok", "score": .6,
                     "risk_level": "WARNING", "warning_threshold": .5, "high_threshold": .8}
                    if i == 1 else {"id": f"URL-{i:02}", "url": url, "status": "error"}
                    for i, url in enumerate(urls, 1)]
    model = LocalModel()
    sms = [{"id": "visible", "text": "https://a.example/ https://b.example/"},
           {"id": "obfuscated", "text": "https://hidden[.]example/"}, {"id": "plain", "text": "Xin chào."}]
    result = control.score_cases(sms, model)
    assert model.calls == [["https://a.example/", "https://b.example/"], ["https://hidden.example/"]]
    assert result["visible"]["real_metadata"][0]["risk_level"] == "UNKNOWN"
    assert result["visible"]["operating_url_results"][1]["status"] == "error"
    assert len(result["visible"]["real_metadata"]) == 1
    assert result["obfuscated"]["real_metadata"] == [] and result["plain"]["real_metadata"] == []


def test_report_refuses_incomplete_run_and_transitions_keep_unknown_distinct(tmp_path, monkeypatch):
    monkeypatch.setattr(registered, "verify", lambda *args: {"complete": False})
    with pytest.raises(ValueError, match="Complete and verify"):
        control.report(tmp_path)
    assert control._transitions([0, 0, 1], ["HIGH", "WARNING", "HIGH"], ["LOW", "UNKNOWN", "UNKNOWN"]) == {
        "false_alarm_to_correct_low": 1, "false_alarm_to_unknown_or_error": 1, "correct_decision_lost": 1}


def test_failed_local_preflight_keeps_diagnostics_and_never_registers(frozen_scope, tmp_path, monkeypatch):
    pack, labels, sms, _ = frozen_scope
    class FailedModel:
        def status(self): return {"ready": False, "message": "offline fixture failure"}
    monkeypatch.setattr(control, "CharURLService", FailedModel)
    scored = {row["id"]: {"raw_url_results": [{"id": "URL-01", "url": "https://fixture.example/",
               "status": "unavailable"}]} for row in sms}
    monkeypatch.setattr(control, "score_cases", lambda *args: scored)
    monkeypatch.setattr(registered, "register", lambda *args, **kwargs: pytest.fail("No registration on local failure"))
    out = tmp_path / "local_failure"
    with pytest.raises(ValueError, match="diagnostics retained"):
        control.prepare(out, pack, labels)
    assert not out.exists()
    diagnostics = out.with_name(out.name + "_inputs")
    assert json.loads((diagnostics / "prepared.json").read_text()) == scored
    assert json.loads((diagnostics / "local_preflight.json").read_text())["API_calls"] == 0


def test_prepare_pins_workers_timeout_assets_inputs_and_budget(frozen_scope, tmp_path, monkeypatch):
    pack, labels, sms, _ = frozen_scope
    small_sms, prepared = inputs()
    for i, case in enumerate(sms[:4]):
        case["text"] = small_sms[i]["text"]
    write_jsonl(pack / "sms.jsonl", sms)
    new_sha = sha(pack / "sms.jsonl")
    monkeypatch.setattr(control, "KNOWN_SMS_SHA256", new_sha)
    manifest = json.loads((pack / "manifest.json").read_text()); manifest["files"]["sms.jsonl"] = new_sha
    write_json(pack / "manifest.json", manifest)
    manifest = json.loads((labels / "labels_manifest.json").read_text())
    manifest["pack_manifest_sha256"] = sha(pack / "manifest.json")
    write_json(labels / "labels_manifest.json", manifest)
    assets = tmp_path / "model"; assets.mkdir()
    (assets / "export.json").write_text("{}")
    preprocessor = tmp_path / "preprocessing.py"; preprocessor.write_text("fixture = True\n")
    class LocalModel:
        path = assets
        preprocessing_path = preprocessor
        def status(self): return {"ready": True, "fixture": True}
    monkeypatch.setattr(control, "CharURLService", LocalModel)
    def scored(rows, model):
        result = {}
        for i, row in enumerate(rows):
            original = prepared[f"case-{i}"] if i < 4 else prepared["case-4"]
            result[row["id"]] = deepcopy(original)
        return result
    monkeypatch.setattr(control, "score_cases", scored)
    out = tmp_path / "registered"
    cfg = control.prepare(out, pack, labels)
    assert cfg["workers"] == 1 and cfg["timeout_seconds"] == 45
    assert cfg["max_tokens"] == 2048 and cfg["recorded_token_stop_budget"] == 300000
    assert cfg["max_attempts"] == 88 and cfg["metadata"]["logical_cells"] == 240
    assert cfg["metadata"]["pilot_unique_requests"] == 12 and cfg["metadata"]["pacing_seconds"] == 4
    assert cfg["metadata"]["reserve_inference"] is False
    assert str(preprocessor) in cfg["input_files_sha256"]
    assert any(path.endswith("permutation_mapping.jsonl") for path in cfg["input_files_sha256"])
    loaded, requests = registered.load(out)
    assert loaded == cfg and len(requests) == 88
    assert registered.verify(out, control.parse_response) == {"verified": True, "complete": False, "attempts": 0, "API_calls": 0}
    # Replay a sealed offline fixture through the real parser/reporter. One
    # truncated response remains an error and a miss in its reference arm.
    answer = {"risk_level": "LOW", "context_kind": "routine", "reason_code": "no_fraud_evidence",
              "quotes": [], "missing_context": []}
    attempts, responses = [], []
    for i, schedule in enumerate(cfg["schedule"]):
        attempt = {**schedule, "started_at": "2026-11-18T00:00:00+00:00"}
        raw = {**attempt, "content": json.dumps(answer), "http_status": 200,
               "provider_model": "offline-unit", "finish_reason": "length" if i == 0 else "stop",
               "usage": {"total_tokens": 3}, "elapsed_ms": 10}
        raw["parsed"] = registered.parsed(raw, requests[(cfg["stage"], schedule["key"])], control.parse_response)
        attempts.append(attempt); responses.append(raw)
    write_jsonl(out / "attempts.jsonl", attempts)
    write_jsonl(out / "responses.jsonl", responses)
    records = {(row["pack"], row["key"]): row for row in responses}
    write_json(out / "summary.json", registered.summary(cfg, records, "complete"))
    write_json(out / "result_hashes.json", {name: sha(out / name) for name in registered.SEALED})
    result = control.report(out)
    assert result["logical_cells"] == 240 and result["aliased_cells"] == 152
    assert result["physical_run"]["usage"]["total_tokens"] == 264
    assert result["arms"][control.ARMS[0]]["n"] == 58
    assert result["arms"][control.ARMS[0]]["unknown_negative"] == 1
    assert result["arms"][control.ARMS[0]]["technical_errors_all_80"] == 1
    assert result["URL_subset"][control.ARMS[0]]["positive_cases"] == 0
    assert result["independent_accuracy"] is None and len(result["paired"]) == 3
    assert len(json.loads((out / "analysis_manifest.json").read_text())["artifacts_sha256"]) == 3
    with pytest.raises(ValueError, match="fresh"):
        control.prepare(out, pack, labels)
