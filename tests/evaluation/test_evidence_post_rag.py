"""Offline contracts for the bounded, frozen-verdict RAG stage."""
import asyncio
import csv
import json
from types import SimpleNamespace

import httpx
import pytest

from app.services.llm.core import parse_core
from evaluation.common import registered
from evaluation.data.sms import read_jsonl, write_json, write_jsonl
from evaluation.rag import evidence_post_pilot as study


TEXT = "Đây là thông báo lịch hẹn khám bạn đã đặt."
VERDICT = parse_core(json.dumps({"risk_level": "LOW", "context_kind": "routine",
    "reason_code": "no_fraud_evidence", "quotes": [], "missing_context": []}), TEXT)["verdict"]
SOURCE = {"document_id": "VN-RAG-001", "text": "Thông báo lịch hẹn khám được gửi khi khách hàng đặt lịch khám.",
          "title": "Lịch khám", "publisher": "Cơ sở y tế", "source_url": "https://example.org/appointment"}
PARENT_LOADER = study._parent


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    parent = tmp_path / "classification"
    parent.mkdir()
    pinputs = tmp_path / "classification_inputs"
    pinputs.mkdir()
    for name in (*registered.SEALED, "result_hashes.json", "registration.sha256"):
        (parent / name).write_text("parent frozen " + name)
    (pinputs / "cases.jsonl").write_text("{}\n")
    settings = SimpleNamespace(root=tmp_path, rag_corpus="corpus.jsonl", rag_index_dir="index", rag_model_dir="model", llm_model="mock")
    (tmp_path / "corpus.jsonl").write_text("{}\n")
    (tmp_path / "index").mkdir()
    (tmp_path / "index/manifest.json").write_text("{}")
    (tmp_path / "model").mkdir()
    (tmp_path / "model/weights").write_text("mock weights")
    monkeypatch.setattr(registered, "Settings", lambda: SimpleNamespace(llm_model="mock", endpoint="https://example.org/api"))
    monkeypatch.setattr(registered, "normalize_endpoint", lambda value, settings: value)
    cases = [{"id": "a", "text": TEXT, "group_id": "g", "label": 0, "source_ids": ["DO_NOT_SEND"]}]
    frozen = [{"id": "a", "arm": arm, "classification_request_key": "classifier-1",
               "classification": {"status": "ok", "verdict": VERDICT}} for arm in study.ARMS]
    monkeypatch.setattr(study, "_parent", lambda p: (parent, pinputs, cases, {}, frozen))
    return SimpleNamespace(parent=parent, settings=settings, cases=cases, frozen=frozen, out=tmp_path / "post")


class Retriever:
    def __init__(self, status="ok", sources=None):
        self.status = status
        self.sources = [SOURCE] if sources is None else sources
        self.queries = []

    def search(self, query, mode):
        self.queries.append((query, mode))
        return {"status": self.status, "sources": self.sources}


def test_aliases_identical_post_payloads_and_hides_reference_labels(fixture):
    retriever = Retriever()
    result = study.prepare(fixture.parent, fixture.out, settings=fixture.settings, retriever=retriever)
    assert result["requests"] == 1
    assert result["logical_cells"] == 2
    assert retriever.queries == [(TEXT, "text")]
    config, requests = registered.load(fixture.out)
    request = next(iter(requests.values()))
    body = json.dumps(request["payload"], ensure_ascii=False)
    assert "DO_NOT_SEND" not in body
    assert '"label"' not in body
    assert request["payload"]["thinking"] == {"type": "disabled"}
    assert request["payload"]["max_tokens"] == 2048
    assert config["workers"] == 1
    assert config["timeout_seconds"] == 45
    assert config["recorded_token_stop_budget"] == 80000
    assert config["metadata"]["pilot_unique_requests"] == 1
    assert config["metadata"]["pacing_seconds"] == 4
    assert study.verify(fixture.out)["classification_changed"] is False


@pytest.mark.parametrize("status,expected", [("empty", "no_sources"), ("unavailable", "retrieval_unavailable")])
def test_no_sources_and_unavailable_are_distinct_sealed_offline_states(fixture, status, expected):
    result = study.prepare(fixture.parent, fixture.out, settings=fixture.settings, retriever=Retriever(status, []))
    assert result["requests"] == 0
    assert study.verify(fixture.out)["complete"]
    assert asyncio.run(study.run(fixture.out, live=True))["API_calls"] == 0
    report = study.report(fixture.out)
    assert report["logical_statuses"] == {expected: 2}
    assert report["F1_improvement"] is None
    with (fixture.out / "semantic_review.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 2
    assert all(row["relevance_0_2"] == row["entails_0_2"] == "" for row in rows)


def test_classifier_errors_never_retrieve_or_register(fixture):
    for cell in fixture.frozen:
        cell["classification"] = {"status": "error", "code": "OUTPUT_TRUNCATED"}
    retriever = Retriever()
    assert study.prepare(fixture.parent, fixture.out, settings=fixture.settings, retriever=retriever)["requests"] == 0
    assert not retriever.queries
    report = study.report(fixture.out)
    assert report["logical_statuses"] == {"classifier_error": 2}
    assert all(row["code"] == "OUTPUT_TRUNCATED" for row in read_jsonl(fixture.out / "selections.jsonl"))


def test_different_frozen_verdicts_do_not_alias_same_text(fixture):
    changed = dict(VERDICT)
    changed["summary"] = "Nhận định khác đã được khóa."
    fixture.frozen[1]["classification"] = {"status": "ok", "verdict": changed}
    result = study.prepare(fixture.parent, fixture.out, settings=fixture.settings, retriever=Retriever())
    assert result["requests"] == 2


def test_evidence_empty_selection_is_operationally_valid(fixture):
    study.prepare(fixture.parent, fixture.out, settings=fixture.settings, retriever=Retriever())
    _, requests = registered.load(fixture.out)
    request = next(iter(requests.values()))
    parsed = study.parse_response('{"selections":[]}', request)
    assert parsed["status"] == "ok"
    assert parsed["explanation_status"] == "no_support"
    assert parsed["validation"]["semantic_support_verified"] is False
    assert study.parse_response('{"selections":[{"source_span_id":"VN-RAG-999:S001",'
        '"input_span_id":"M001","relation":"mechanism_match"}]}', request)["status"] == "error"


@pytest.mark.parametrize("target", ["model/weights", "corpus.jsonl", "classification/responses.jsonl", "classification_inputs/cases.jsonl"])
def test_mutated_assets_or_parent_are_detected_even_empty(fixture, target):
    study.prepare(fixture.parent, fixture.out, settings=fixture.settings, retriever=Retriever("empty", []))
    (fixture.out.parent / target).write_text("tampered")
    with pytest.raises(ValueError, match="changed"):
        study.verify(fixture.out)


def test_no_overwrite_existing_run_or_sidecar(fixture):
    study.prepare(fixture.parent, fixture.out, settings=fixture.settings, retriever=Retriever("empty", []))
    with pytest.raises(ValueError, match="fresh"):
        study.prepare(fixture.parent, fixture.out, settings=fixture.settings, retriever=Retriever())


def test_complete_mocked_run_report_preserves_verdict_and_source_url(fixture, monkeypatch):
    study.prepare(fixture.parent, fixture.out, settings=fixture.settings, retriever=Retriever())
    config, requests = registered.load(fixture.out)
    key, request = next(iter(requests.items()))
    parsed = study.parse_response('{"selections":[{"source_span_id":"VN-RAG-001:S001",'
        '"input_span_id":"M001","relation":"verification_step"}]}', request)
    row = {"parsed": parsed, "usage": {"total_tokens": 12}}
    monkeypatch.setattr(study, "verify", lambda out: {"complete": True})
    monkeypatch.setattr(study, "_load", lambda out: (fixture.out.parent / "post_inputs", config, requests, {key: row}))
    result = study.report(fixture.out)
    assert result["classification_changed"] is False
    assert result["physical_requests"] == 1
    assert result["logical_cells"] == 2
    assert result["recorded_tokens"] == 12
    with (fixture.out / "semantic_review.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    assert all(row["source_url"] == SOURCE["source_url"] for row in rows)
    assert all(row["relevance_0_2"] == row["entails_0_2"] == "" for row in rows)


def test_once_only_mock_transport_replay_retains_no_support(fixture, monkeypatch):
    study.prepare(fixture.parent, fixture.out, settings=fixture.settings, retriever=Retriever())
    settings = SimpleNamespace(api_key="offline-test-key", llm_model="mock", endpoint="https://example.org/api")
    monkeypatch.setattr(study.controlled_run, "Settings", lambda: settings)
    monkeypatch.setattr(study.controlled_run, "normalize_endpoint", lambda value, settings: value)
    observed = []
    def response(request):
        observed.append(json.loads(request.content))
        return httpx.Response(200, json={"model": "mock", "choices": [{"finish_reason": "stop",
            "message": {"content": '{"selections":[]}'}}], "usage": {"total_tokens": 15}})
    transport = httpx.MockTransport(response)
    result = asyncio.run(study.run(fixture.out, live=True, limit=1, inner=transport))
    assert result["state"] == "complete"
    assert result["valid"] == 1
    assert study.verify(fixture.out)["complete"]
    assert study.report(fixture.out)["logical_explanation_statuses"] == {"no_support": 2}
    asyncio.run(study.run(fixture.out, live=True, limit=1, inner=transport))
    assert len(observed) == 1


@pytest.mark.parametrize("defect", ["incomplete", "alias", "profile", "text", "inventory"])
def test_parent_contract_rejects_incomplete_or_different_classifiers(tmp_path, monkeypatch, defect):
    parent, inputs = tmp_path / "classification", tmp_path / "classification_inputs"
    parent.mkdir(); inputs.mkdir()
    write_jsonl(inputs / "cases.jsonl", [{"id": "a", "text": TEXT}])
    cells = [{"id": "a", "arm": arm, "request_key": "k"} for arm in (*study.BASE_ARMS.values(), *study.ARMS)]
    if defect == "alias": cells[-1]["request_key"] = "other"
    if defect == "inventory": cells.pop()
    write_jsonl(inputs / "cells.jsonl", cells)
    write_json(inputs / "prepared.json", {"a": {}})
    request = {"profile": "other" if defect == "profile" else "core", "text": "Other" if defect == "text" else TEXT}
    config = {"stage": "classifier", "metadata": {"inputs": str(inputs)}}
    monkeypatch.setattr(registered, "verify", lambda p, parser: {"complete": defect != "incomplete"})
    monkeypatch.setattr(registered, "load", lambda p: (config, {("classifier", "k"): request}))
    monkeypatch.setattr(registered, "checkpoints", lambda p, c: ({}, {("classifier", "k"): {"parsed": {"status": "ok", "verdict": VERDICT}}}))
    with pytest.raises(ValueError):
        PARENT_LOADER(parent)


def test_offline_report_tampering_is_detected(fixture):
    study.prepare(fixture.parent, fixture.out, settings=fixture.settings, retriever=Retriever("empty", []))
    study.report(fixture.out)
    (fixture.out / "operations.json").write_text("{}")
    with pytest.raises(ValueError, match="report changed"):
        study.verify(fixture.out)
