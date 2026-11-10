import asyncio
from dataclasses import replace
import json
from pathlib import Path

import httpx
import pytest

import evaluation.messages.url_context as run


CASE = {"id": "fixture", "task": "url_only", "text": "https://example.org/",
        "targets": {"url_risk": 0, "message_behavior": None, "action_risk": None},
        "split": "dev", "group_id": "example.org", "url_id": "u1", "variant": "url_only"}
VERDICT = {"url_risk": "LOW", "message_behavior": "UNKNOWN", "action_risk": "UNKNOWN",
           "url_role": "none", "explanation": "Test fixture only", "evidence_quotes": [CASE["text"]]}
ML = {"url": CASE["text"], "status": "ok", "score": .1, "risk_level": "LOW",
      "warning_threshold": .2, "high_threshold": .8, "source": "never send", "label": 0}
CONFIG = {"model": "fixture", "endpoint": "https://example.org/v1/chat/completions", "temperature": .1,
          "top_p": 1, "top_k": 40, "max_tokens": 8192, "repetitions": 1,
          "max_total_provider_attempts": 2, "order_seed": 33, "workers": 2}


def test_only_model_metadata_changes_between_arms():
    left = run.payload_for(CASE, "llm_only", ML, "frozen", CONFIG)
    right = run.payload_for(CASE, "llm_url", ML, "frozen", CONFIG)
    assert left["messages"][0] == right["messages"][0]
    a = json.loads(left["messages"][1]["content"])
    b = json.loads(right["messages"][1]["content"])
    assert a.pop("url_model") == []
    context = b.pop("url_model")
    assert a == b == {"task": CASE["task"], "text": CASE["text"]}
    assert set(context[0]) == {"url", "score", "risk_level", "warning_threshold", "high_threshold"}


@pytest.mark.parametrize("change", ["foreign_quote", "wrong_scope", "extra_field", "blank_reason"])
def test_invalid_responses_are_rejected_not_relabelled(change):
    value = {**VERDICT}
    if change == "foreign_quote": value["evidence_quotes"] = ["not in the input"]
    elif change == "wrong_scope": value["message_behavior"] = "LOW"
    elif change == "extra_field": value["source_label"] = 0
    else: value["explanation"] = " "
    with pytest.raises(ValueError):
        run.parse_content(json.dumps(value), CASE)
    assert run.parse_content("```json\n" + json.dumps(VERDICT) + "\n```", CASE) == VERDICT


@pytest.mark.parametrize("kind", ["ok", "truncated", "invalid", "fatal"])
def test_provider_adapter_preserves_error_usage_and_does_not_retry(kind):
    requests = []
    async def handler(request):
        requests.append(request)
        if kind == "fatal": return httpx.Response(429, json={"error": "do not serialize provider error details"})
        return httpx.Response(200, json={"model": "fixture", "id": "response-fixture",
            "usage": {"total_tokens": 11}, "choices": [{"finish_reason": "length" if kind == "truncated" else "stop",
                "message": {"content": "bad json" if kind == "invalid" else json.dumps(VERDICT)}}]})
    async def call():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await run.call_provider(client, CONFIG["endpoint"], "fixture-secret", {}, CASE, 1)
    result = asyncio.run(call())
    assert len(requests) == 1 and "elapsed_ms" in result
    if kind == "ok": assert result["outputs"]["url_risk"] == "LOW"
    else:
        assert result["status"] == "error" and "outputs" not in result
        assert result["error_code"] == {"truncated": "OUTPUT_TRUNCATED", "invalid": "OUTPUT_INVALID", "fatal": "HTTP_429"}[kind]
    if kind != "fatal": assert result["usage"]["total_tokens"] == 11
    assert "fixture-secret" not in json.dumps(result)


@pytest.fixture
def fixture_run(tmp_path, monkeypatch):
    pack, model, out = tmp_path / "pack", tmp_path / "model", tmp_path / "out"
    pack.mkdir(); model.mkdir()
    (pack / "system_prompt.txt").write_text("frozen")
    (pack / "urls.jsonl").write_text(json.dumps({"id": "u1", "url": CASE["text"], "source": "fixture", "tier": "silver"}) + "\n")
    config = dict(CONFIG)
    monkeypatch.setattr(run, "configuration", lambda *a: (config, [CASE], model))
    settings = replace(run.Settings(), api_key="fixture-secret")
    monkeypatch.setattr(run, "Settings", lambda: settings)
    calls = []
    class Model:
        path = model
        def __init__(self, *args): pass
        def load(self): return {"ready": True}
        def predict(self, urls): return [ML]
    monkeypatch.setattr(run, "ModelService", Model)
    async def provider(*args):
        calls.append(args[3])
        return {"status": "ok", "outputs": {k: VERDICT[k] for k in run.TARGETS}, "usage": {"total_tokens": 1}}
    monkeypatch.setattr(run, "call_provider", provider)
    args = argparse_namespace(pack=pack, out=out, split="dev", repetitions=1, live=False)
    return args, calls, config


def argparse_namespace(**kwargs):
    from argparse import Namespace
    return Namespace(**kwargs)


def test_offline_pending_live_completion_and_resume_without_paid_repeats(fixture_run):
    args, calls, _ = fixture_run
    asyncio.run(run.evaluate(args))
    summary = json.loads((args.out / "summary.json").read_text())
    assert summary["metrics_ready"] is False and summary["metrics"] is None and not calls
    args.live = True
    asyncio.run(run.evaluate(args))
    summary = json.loads((args.out / "summary.json").read_text())
    assert summary["metrics_ready"] is True and summary["provider_requests"] == 2
    assert len(calls) == 2
    asyncio.run(run.evaluate(args))
    assert len(calls) == 2


def test_changed_registration_does_not_rewrite_existing_results(fixture_run):
    args, _, config = fixture_run
    asyncio.run(run.evaluate(args))
    before = {p.name: p.read_bytes() for p in args.out.iterdir() if p.is_file()}
    config["temperature"] = .8
    with pytest.raises(ValueError, match="different"):
        asyncio.run(run.evaluate(args))
    assert before == {p.name: p.read_bytes() for p in args.out.iterdir() if p.is_file()}


def test_interrupted_attempt_is_kept_as_error_and_never_reissued(fixture_run):
    args, calls, _ = fixture_run
    asyncio.run(run.evaluate(args))
    run.append(args.out / "attempts.jsonl", {"id": CASE["id"], "arm": "llm_only", "repeat": 1})
    args.live = True
    asyncio.run(run.evaluate(args))
    rows = run.read_jsonl(args.out / "predictions.jsonl")
    only = next(r for r in rows if r["arm"] == "llm_only")
    assert only["error_code"] == "INTERRUPTED_REQUEST" and len(calls) == 1
