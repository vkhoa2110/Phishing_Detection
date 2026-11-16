import asyncio
from dataclasses import replace
import json

import httpx
import pytest

from app.core.settings import Settings
from evaluation.common import registered
from evaluation.data.sms import read_jsonl, sha
from evaluation.messages.claim_audit import audit
from evaluation.messages.core_pilot import parse_response


def test_audit_preserves_complete_inventory_errors_and_sealed_source(tmp_path, monkeypatch):
    settings = replace(Settings(), api_key="offline-fixture")
    monkeypatch.setattr(registered, "Settings", lambda: settings)
    study = tmp_path / "study"
    text = "Cập nhật địa chỉ giao hàng."
    rows = [{"key": str(i), "case_id": f"case-{i}", "profile": "core", "text": text,
             "payload": {"model": settings.llm_model, "max_tokens": 2048,
                         "messages": [{"role": "user", "content": str(i)}]}} for i in range(2)]
    registered.register(study, rows, stage="fixture", max_tokens=2048, token_budget=10000)
    def provider(request):
        cut = json.loads(request.content)["messages"][0]["content"] == "1"
        answer = {"risk_level": "HIGH", "context_kind": "scam_request", "reason_code": "payment_redirection",
                  "quotes": [text], "missing_context": []}
        return httpx.Response(200, json={"model": "fixture", "usage": {"total_tokens": 100},
            "choices": [{"finish_reason": "length" if cut else "stop", "message": {"content": json.dumps(answer)}}]})
    asyncio.run(registered.run(study, parse_response, live=True, transport=httpx.MockTransport(provider)))
    before = {p.name: sha(p) for p in study.iterdir() if p.is_file()}
    result = audit(study, tmp_path / "audit")
    assert result["requests"] == 2 and result["counts"] == {"needs_review": 1, "not_applied": 1}
    assert result["classification_changes"] == result["F1_change"] == result["API_calls"] == 0
    outputs = read_jsonl(tmp_path / "audit/per_request.jsonl")
    assert outputs[1]["error"] == "OUTPUT_TRUNCATED"
    assert before == {p.name: sha(p) for p in study.iterdir() if p.is_file()}
    with pytest.raises(ValueError, match="immutable"):
        audit(study, tmp_path / "audit")
    # The auditor must reject changed raw records rather than bless new metrics.
    response = study / "responses.jsonl"
    response.write_text(response.read_text() + "\n")
    with pytest.raises(ValueError, match="Sealed results changed"):
        audit(study, tmp_path / "changed_source_audit")
