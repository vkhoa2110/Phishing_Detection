import asyncio
import copy
import json
from types import SimpleNamespace

import httpx
import pytest

from evaluation import component_ablation as run


def case(**values):
    return {"id": "fixture-1", "dataset": "sms", "task": "message_context", "text": "Hãy gửi mã OTP cho tôi.",
            "group_id": "fixture-group", "targets": {"url_risk": None, "message_behavior": 1, "action_risk": None}, **values}


def content(**values):
    return {"url_risk": "UNKNOWN", "message_behavior": "HIGH", "action_risk": "HIGH", "url_role": "none",
            "explanation": "Yêu cầu cung cấp mã xác thực.", "evidence_quotes": ["gửi mã OTP"], "knowledge_support": [], **values}


def config():
    return {"model": "fixture", "prompt": run.SYSTEM_PROMPT, "temperature": .1, "top_p": 1, "top_k": 40,
            "max_tokens": 8192, "endpoint": "https://provider.example/v1/chat/completions", "timeout_seconds": 2,
            "provider_call_budget": 4, "scope": "unit_test_only"}


def prepared():
    return {"urls": [{"id": "hidden", "url": "https://example.org", "score": .8, "risk_level": "HIGH",
                       "warning_threshold": .1, "high_threshold": .5, "label": "do not send"}],
            "retrieval": {"sources": [{"document_id": "D1", "title": "Hướng dẫn", "text": "Giữ kín mã OTP.",
                                        "label": "do not send", "rationale": "hidden"}]}, "reputation": []}


def test_four_arms_share_prompt_schema_and_text_and_hide_reference_fields():
    c = case(text=case()["text"] + " https://example.org", label=1, rationale="hidden", source="hidden")
    payloads = {a: run.payload_for(c, prepared(), a, config()) for a in run.ARMS}
    inputs = {a: json.loads(p["messages"][1]["content"]) for a, p in payloads.items()}
    assert len({p["messages"][0]["content"] for p in payloads.values()}) == 1
    assert all(set(p) == {"task", "text", "url_model", "reference_documents"} for p in inputs.values())
    assert not inputs["llm_only"]["url_model"] and not inputs["llm_rag"]["url_model"]
    assert inputs["llm_url"]["url_model"] == inputs["llm_url_rag"]["url_model"]
    assert not inputs["llm_url"]["reference_documents"]
    assert inputs["llm_rag"]["reference_documents"] == inputs["llm_url_rag"]["reference_documents"]
    assert all("label" not in p and "rationale" not in p and "id" not in p for x in inputs.values() for p in x["url_model"] + x["reference_documents"])
    assert not run.payload_for(case(), prepared(), "llm_url", config())["messages"][1]["content"].find('"url_model": []') == -1


def test_citations_need_a_supplied_document_literal_quote_and_nonblank_claim():
    support = [{"document_id": "D1", "source_quote": "Giữ kín mã OTP.", "claim": "Không chia sẻ mã."}]
    value = content(knowledge_support=support)
    assert run.parse_content(json.dumps(value), case(), prepared()["retrieval"]["sources"])["knowledge_support"] == support
    for sources, altered in [([], value), (prepared()["retrieval"]["sources"], content(knowledge_support=[{**support[0], "source_quote": "không có"}])),
                              (prepared()["retrieval"]["sources"], content(knowledge_support=[{**support[0], "claim": " "}]))]:
        with pytest.raises(ValueError):
            run.parse_content(json.dumps(altered), case(), sources)


def test_evidence_scope_and_target_text_cannot_be_replaced_by_rag_text():
    with pytest.raises(ValueError, match="Quote"):
        run.parse_content(json.dumps(content(evidence_quotes=["Giữ kín mã OTP."])), case(), prepared()["retrieval"]["sources"])
    with pytest.raises(ValueError, match="No-URL"):
        run.parse_content(json.dumps(content(url_risk="LOW")), case(), [])
    assert run.parse_content("```json\n" + json.dumps(content()) + "\n```", case(), [])["message_behavior"] == "HIGH"


def test_complete_keys_unknown_reference_and_errors_keep_correct_denominators():
    cases = [case(), case(id="fixture-2", targets={t: None for t in run.TARGETS})]
    records = [{"id": c["id"], "arm": a, "status": "ok", "outputs": {t: "HIGH" for t in run.TARGETS}} for c in cases for a in run.ARMS]
    records[0] = {"id": cases[0]["id"], "arm": "llm_only", "status": "error", "error_code": "FIXTURE_ERROR"}
    lookup = run.lookup_records(cases, records)
    m = run.metric(cases, lookup, "llm_only", "message_behavior")
    assert m["n"] == 1 and m["unknown_positive"] == 1 and m["recall"] == 0
    assert m["reference_unknown_count"] == 1 and m["reference_unknown_predictions"] == {"HIGH": 1}
    with pytest.raises(ValueError, match="Duplicate"):
        run.lookup_records(cases, records + [records[0]])


def test_interrupted_journal_entry_is_kept_as_error_without_a_new_call(tmp_path, monkeypatch):
    c, cfg = case(), config()
    monkeypatch.setattr(run, "configuration", lambda *args: (cfg, [c]))
    run.write_json(tmp_path / "execution.json", {"configuration": cfg})
    run.write_jsonl(tmp_path / "cases.jsonl", [c])
    run.write_json(tmp_path / "prepared.json", {c["id"]: prepared()})
    (tmp_path / "prepared.sha256").write_text(run.sha(tmp_path / "prepared.json"))
    run.write_jsonl(tmp_path / "attempts.jsonl", [{"id": c["id"], "arm": "llm_only"}])
    args = SimpleNamespace(out=tmp_path, sms_pack=tmp_path, url_pack=tmp_path, reputation_run=tmp_path, live=False)
    asyncio.run(run.evaluate(args))
    records = run.read_jsonl(tmp_path / "predictions.jsonl")
    assert len(records) == 1 and records[0]["error_code"] == "INTERRUPTED_REQUEST"
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["metrics_ready"] is False and summary["metrics"] is None and summary["provider_attempts"] == 1


def test_provider_truncation_keeps_returned_token_usage_and_is_not_usable_prediction():
    body = {"choices": [{"finish_reason": "length", "message": {"content": "incomplete"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 8192, "total_tokens": 8202}}
    async def execute():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))) as client:
            return await run.call_provider(client, "fake-test-key", {}, case(), [], config())
    result = asyncio.run(execute())
    assert result["status"] == "error" and result["error_code"] == "OUTPUT_TRUNCATED"
    assert result["usage"]["total_tokens"] == 8202 and "outputs" not in result


def test_dev_selection_retains_all_29_unknown_sms_and_excludes_url_only_and_test():
    cases = run.load_cases(run.ROOT / "data/annotation/objective_v1", run.ROOT / "data/annotation/url_context_v1")
    sms = [c for c in cases if c["dataset"] == "sms"]
    assert len(cases) == 160 and len(sms) == 80
    assert sum(c["targets"]["message_behavior"] is None for c in sms) == 29
    assert all(c["task"] == "message_context" for c in cases)
    assert all(c["targets"]["url_risk"] is None and c["targets"]["action_risk"] is None for c in sms)
