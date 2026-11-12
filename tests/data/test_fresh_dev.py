import asyncio
from dataclasses import replace
import json

import httpx
import pytest

from app.core.settings import ROOT, Settings
from evaluation.common import registered
from evaluation.data import fresh_dev
from evaluation.data.sms import read_jsonl, sha


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.setattr(registered, "Settings", lambda: replace(Settings(), api_key="unit-only-secret"))
    pack = tmp_path / "pack"
    fresh_dev.prepare(ROOT / "data/annotation/fresh_messages_v1", pack)
    out = tmp_path / "labels"
    fresh_dev.prepare_labels(pack, out)
    return pack, out


def transport(calls, finish="stop"):
    def handle(request):
        body = json.loads(request.content)
        calls.append(body)
        messages = json.loads(body["messages"][1]["content"])["messages"]
        answer = {"annotations": [{"id": m["id"], "label": "0", "category": "routine",
            "confidence": "low", "evidence_quote": "", "notes": "Offline fixture, not a real assessment."} for m in messages]}
        return httpx.Response(200, json={"model": body["model"], "usage": {"total_tokens": 21},
            "choices": [{"finish_reason": finish if len(calls) == 1 else "stop", "message": {"content": json.dumps(answer)}}]})
    return httpx.MockTransport(handle)


def test_dev_subset_never_exposes_reserve_or_sampling_labels(prepared):
    pack, out = prepared
    sms, stress = fresh_dev.cases(pack)
    assert len(sms) == 80 and len(stress) == 40
    source = read_jsonl(ROOT / "data/annotation/fresh_messages_v1/items.jsonl")
    reserve = {r["id"] for r in source if r["split"] == "reserve_review"}
    _, requests = registered.load(out)
    sent_ids = set()
    for row in requests.values():
        data = json.loads(row["payload"]["messages"][1]["content"])
        assert set(data) == {"messages"}
        assert all(set(m) == {"id", "text"} for m in data["messages"])
        sent_ids.update(m["id"] for m in data["messages"])
    assert len(sent_ids) == 80 and not sent_ids & reserve


def test_annotation_raw_replay_and_missing_labels_stay_provisional(prepared):
    pack, out = prepared
    before = {side: sha(pack / f"human_{side}.csv") for side in ("a", "b")}
    calls = []
    mock = transport(calls, "length")
    assert asyncio.run(registered.run(out, fresh_dev.parse_labels))["API_calls"] == 0
    result = asyncio.run(registered.run(out, fresh_dev.parse_labels, live=True, transport=mock))
    assert result["completed"] == 20 and result["errors"]["OUTPUT_TRUNCATED"] == 1
    labels = fresh_dev.export_labels(out)
    assert labels["counts"] == {"0": 76, "UNKNOWN": 4}
    assert labels["human_reviewed"] is False
    assert registered.verify(out, fresh_dev.parse_labels)["complete"]
    asyncio.run(registered.run(out, fresh_dev.parse_labels, live=True, transport=mock))
    assert len(calls) == 20
    assert before == {side: sha(pack / f"human_{side}.csv") for side in before}
    assert "unit-only-secret" not in (out / "responses.jsonl").read_text()


def test_http_gate_and_registration_changes_refuse_more_requests(prepared):
    _, out = prepared
    calls = []
    def fail(request):
        calls.append(request)
        return httpx.Response(429)
    mock = httpx.MockTransport(fail)
    assert asyncio.run(registered.run(out, fresh_dev.parse_labels, live=True, transport=mock))["state"] == "stopped_by_gate"
    asyncio.run(registered.run(out, fresh_dev.parse_labels, live=True, transport=mock))
    assert len(calls) == 2
    with (out / "execution.json").open("a") as stream:
        stream.write("\n")
    with pytest.raises(ValueError, match="Registration changed"):
        asyncio.run(registered.run(out, fresh_dev.parse_labels, live=True, transport=mock))
    assert len(calls) == 2


def test_transport_continuation_preserves_errors_and_never_resends(prepared, tmp_path):
    from evaluation.common.continuation import prepare, merge
    _, out = prepared
    def fail(request): raise httpx.ConnectError("Offline fixture", request=request)
    first = asyncio.run(registered.run(out, fresh_dev.parse_labels, live=True, transport=httpx.MockTransport(fail)))
    assert first["completed"] == 4 and first["state"] == "stopped_by_gate"
    child, combined = tmp_path / "child", tmp_path / "combined"
    prepare(out, child, fresh_dev.parse_labels)
    calls = []
    asyncio.run(registered.run(child, fresh_dev.parse_labels, live=True, transport=transport(calls)))
    result = merge(child, combined, fresh_dev.parse_labels)
    assert len(calls) == 16 and result["merged_attempts"] == 20
    value = fresh_dev.export_labels(combined)
    assert value["counts"] == {"0": 64, "UNKNOWN": 16}
