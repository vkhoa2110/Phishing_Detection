import json
import zipfile

import pytest

from evaluation.messages.fresh_ablation import ARMS, bind_requests, parse_response, training_domains


@pytest.mark.parametrize("urls,sources,expected", [(False, False, 1), (True, False, 2), (False, True, 2), (True, True, 4)])
def test_same_information_controls_share_one_response(urls, sources, expected):
    case = {"id": "fixture", "text": "Tự mở ứng dụng để xem đơn hàng.", "dataset": "sms"}
    prepared = {case["id"]: {"url_context": [{"url": "https://example.org", "score": .8}] if urls else [],
        "sources": [{"document_id": "VN-RAG-001", "text": "Kiểm tra độc lập."}] if sources else []}}
    requests, cells = bind_requests([case], prepared, "fixture-model")
    assert len(cells) == 4 and len(requests) == expected
    assert {cell["arm"] for cell in cells} == set(ARMS)
    assert len({r["payload"]["messages"][0]["content"] for r in requests}) == 1
    schemas = [json.loads(r["payload"]["messages"][1]["content"])["output_schema"] for r in requests]
    assert all(schema == schemas[0] for schema in schemas)
    for row in requests:
        data = json.loads(row["payload"]["messages"][1]["content"])
        assert set(data) == {"text", "assessment_target", "url_results", "reference_documents", "output_schema"}
        assert row["payload"]["max_tokens"] == 4096


def test_schema_and_evidence_validation_are_identical_without_sources():
    request = {"text": "Chào bạn.", "sources": []}
    answer = {"risk_level": "HIGH", "context_kind": "scam_request", "summary": "Fixture.",
              "evidence": [], "recommended_actions": [], "knowledge_support": []}
    parsed = parse_response(json.dumps(answer), request)
    assert parsed["verdict"]["risk_level"] == "UNKNOWN"
    assert "ALARM_WITHOUT_BEHAVIOR_EVIDENCE" in parsed["validation"]["reason_codes"]
    with pytest.raises(ValueError):
        parse_response('{"risk_level":"LOW","risk_level":"HIGH"}', request)


def test_domain_exposure_audit_reads_train_only(tmp_path):
    archive = tmp_path / "fixture.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("data/splits/url_train.csv", "url,label\nhttps://login.example.org/path,phishing\nhttps://safe.vn/,benign\n")
        package.writestr("data/splits/url_test.csv", b"not readable as CSV; must never be used")
    assert training_domains(archive) == {"example.org", "safe.vn"}


def test_report_keeps_truncation_and_reference_unknown_with_shared_outputs(tmp_path, monkeypatch):
    """A failed positive must reduce recall; an unknown reference must stay separate."""
    import asyncio
    from dataclasses import replace
    import httpx
    from app.core.settings import Settings
    from evaluation.common import registered
    from evaluation.data.sms import write_json, write_jsonl
    from evaluation.messages import fresh_ablation

    monkeypatch.setattr(registered, "Settings", lambda: replace(Settings(), api_key="offline-fixture"))
    cases = [{"id": key, "group_id": key, "dataset": "sms", "text": text} for key, text in (
        ("detected", "Hãy đọc mã OTP cho tôi."), ("truncated", "Chuyển phí nhận thưởng ngay."),
        ("normal", "Tự mở ứng dụng để xem hóa đơn."), ("unknown", "Hãy đọc mã OTP cho tôi nhưng chưa rõ ngữ cảnh."))]
    monkeypatch.setattr(fresh_ablation, "cases", lambda _: (cases, []))
    prepared = {r["id"]: {"url_context": [], "sources": [], "url_train_domain_overlap": False} for r in cases}
    requests, cells = bind_requests(cases, prepared, Settings().llm_model)
    inputs, labels, pack, out = [tmp_path / name for name in ("inputs", "labels", "pack", "run")]
    for path in (inputs, labels, pack): path.mkdir()
    write_json(inputs / "prepared.json", prepared)
    write_jsonl(inputs / "cells.jsonl", cells)
    write_jsonl(labels / "labels.jsonl", [{"id": key, "label": label} for key, label in
        (("detected", 1), ("truncated", 1), ("normal", 0), ("unknown", None))])
    write_jsonl(pack / "authored_design.jsonl", [])
    registered.register(out, requests, stage="offline", max_tokens=4096, metadata={
        "inputs": str(inputs), "labels": str(labels), "pack": str(pack), "reference_quality": "Offline fixture only"})
    calls = []
    def handle(request):
        data = json.loads(request.content)
        text = json.loads(data["messages"][1]["content"])["text"]
        calls.append(text)
        high = "OTP" in text
        answer = {"risk_level": "HIGH" if high else "LOW", "context_kind": "scam_request" if high else "routine",
            "summary": "Offline fixture.", "evidence": [{"quote": text, "reason": "Offline fixture."}],
            "recommended_actions": [], "knowledge_support": []}
        return httpx.Response(200, json={"model": data["model"], "usage": {"total_tokens": 1},
            "choices": [{"finish_reason": "length" if text.startswith("Chuyển") else "stop",
                         "message": {"content": json.dumps(answer)}}]})
    asyncio.run(registered.run(out, parse_response, live=True, transport=httpx.MockTransport(handle)))
    result = fresh_ablation.results(out)
    assert len(calls) == 4 and result["logical_cells"] == 16 and result["identical_payloads_reused"] == 12
    for arm in ARMS:
        metric = result["groups"]["sms"][arm]
        assert metric["n"] == 3 and metric["reference_unknown"] == 1
        assert metric["tp"] == 1 and metric["unknown_positive"] == 1
        assert metric["recall"] == .5 and metric["f1"] == pytest.approx(2 / 3)
        assert metric["technical_errors"] == 1 and metric["coverage"] == pytest.approx(2 / 3)
