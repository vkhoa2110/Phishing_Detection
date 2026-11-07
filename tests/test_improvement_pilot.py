import asyncio
import copy
from dataclasses import replace
import json

import httpx
import pytest

import evaluation.improvement_pilot as pilot
from app.settings import Settings
from evaluation.url_context_run import canonical_sha


def inputs():
    cases, prepared = [], {}
    labels = {"sms": [1]*9 + [0]*42 + [None]*29,
              "url_context": [1]*16 + [0]*16 + [None]*8}
    for dataset, values in labels.items():
        for i, label in enumerate(values):
            identifier = f"{dataset}-{i}"
            cases.append({"id": identifier, "dataset": dataset, "text": "Hãy gửi OTP cho tôi." if label else "Thông báo lịch học.",
                "targets": {"message_behavior": label}, "variant": "education_injection" if label == 0 else "request",
                "group_id": identifier})
            prepared[identifier] = {"retrieval": {"sources": [{"document_id": "VN-RAG-001", "text": "Không gửi OTP cho người khác.",
                                                              "title": "Bảo vệ mã xác thực"}] if i < 20 else []}}
    selection = pilot.selections(cases, prepared)
    config = {"selections": selection, "max_provider_attempts": 280, "recorded_token_stop_budget": 1500000,
        "model": "fixture", "max_tokens": 8192, "timeout": 90, "endpoint": "https://provider.example/v1/chat/completions",
        "source_hashes": {}, "cases_sha256": canonical_sha(cases), "prepared_sha256": canonical_sha(prepared),
        "gates": {"context_education_min_fp_reduction": 2, "context_min_recall": .9375,
                  "sms_min_recall": 8/9, "sms_max_additional_false_positives": 2, "min_coverage": .9, "max_coverage_drop": .05}}
    return config, cases, prepared


def test_selection_and_attempt_budget_are_fixed_without_reading_predictions():
    cfg, cases, prepared = inputs()
    selected = pilot.selections(cases, prepared)
    changed = copy.deepcopy(cases)
    for case in changed:
        case["targets"]["message_behavior"] = 1
    assert pilot.selections(changed, prepared) == selected
    assert len(pilot.expected_keys(cases, cfg)) == 296
    max_calls = len(cases)*2 + len(selected["rag_with_sources"])*2 + len(selected["repeat_cases"])
    assert max_calls == cfg["max_provider_attempts"] == 280


def test_no_source_payload_is_an_exact_no_op_and_labels_never_reach_provider():
    cfg, cases, prepared = inputs()
    by_id = {c["id"]:c for c in cases}
    for identifier in cfg["selections"]["rag_no_source_controls"]:
        case = by_id[identifier]
        plain, _ = pilot.message_payload(case, "v5_plain", prepared, cfg)
        rag, sources = pilot.message_payload(case, "v5_pre_rag", prepared, cfg)
        assert plain == rag and not sources
        user = json.loads(plain["messages"][1]["content"])
        assert not {"id", "dataset", "targets", "label", "reference_kind"} & set(user)


def test_gates_cannot_be_passed_by_abstaining_on_everything():
    cfg, cases, _ = inputs()
    records = []
    for case in cases:
        label = case["targets"]["message_behavior"]
        for arm in pilot.BASE_ARMS:
            records.append({"id":case["id"],"arm":arm,"status":"ok","verdict":{"risk_level":"UNKNOWN" if arm == "v5_plain" or label is None else "HIGH" if label else "LOW"}})
    summary = pilot.summarize(cases,cfg,records,[],{})
    assert summary["main_metrics_ready"]
    assert not summary["gates"]["passed"]
    assert not summary["gates"]["checks"]["coverage_preserved"]
    assert not summary["gates"]["checks"]["sms_recall_preserved"]
    assert pilot.summarize(cases,cfg,records[:-1],[],{})["metrics"] is None
    with pytest.raises(ValueError, match="Duplicate"):
        pilot.summarize(cases,cfg,records+[records[0]],[],{})


def test_mocked_end_to_end_keeps_no_op_reuse_and_does_not_repeat_paid_requests(tmp_path, monkeypatch):
    cfg, cases, prepared = inputs()
    monkeypatch.setattr(pilot, "registration", lambda _: (cfg, cases, prepared))
    monkeypatch.setattr(pilot, "Settings", lambda: replace(Settings(), api_key="unit-test-key"))
    requests = []
    real_client = httpx.AsyncClient
    def respond(request):
        payload = json.loads(request.content); requests.append(payload)
        data = json.loads(payload["messages"][1]["content"])
        if "classification_locked" in data:
            content = {"support":[],"actions":[]}
        else:
            dangerous = "gửi OTP" in data["text"]
            content = {"risk_level":"HIGH" if dangerous else "LOW", "summary":"Đánh giá theo hành vi.",
                "context_kind":"scam_request" if dangerous else "routine",
                "evidence":[{"quote":"gửi OTP","reason":"Yêu cầu gửi bí mật cho người khác."}] if dangerous else [],
                "recommended_actions":["Xác minh qua kênh đã biết."]}
            if "reference_documents" in data: content["knowledge_support"] = []
        return httpx.Response(200,json={"choices":[{"finish_reason":"stop","message":{"content":json.dumps(content,ensure_ascii=False)}}],
                                       "usage":{"prompt_tokens":10,"completion_tokens":10,"total_tokens":20}})
    monkeypatch.setattr(pilot.httpx, "AsyncClient", lambda **kwargs:real_client(transport=httpx.MockTransport(respond),**kwargs))
    out=tmp_path/"run"
    asyncio.run(pilot.execute(out,live=True))
    assert len(requests)==280
    _, _, records, summary=pilot.verify(out)
    assert summary["all_tasks_complete"] and summary["provider_attempts"]==280
    assert summary["usage"]["total_tokens"]==5600  # Reused records are not billed again.
    assert sum(bool(r.get("reused_from")) for r in records)==8
    assert summary["post_explanation"]["classification_recomputed"] is False
    asyncio.run(pilot.execute(out,live=True))
    assert len(requests)==280
    pilot.report(out)
    assert (out/"explanation_blind.csv").is_file()
