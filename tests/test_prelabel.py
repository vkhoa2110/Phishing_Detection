import asyncio
import csv
from dataclasses import replace
import json
from types import SimpleNamespace

import httpx
import pytest

from app.settings import Settings
from evaluation.message_data import annotation_sheet, read_jsonl, sha, write_json, write_jsonl
from evaluation.prelabel import generate, parse_annotations
from evaluation.review import validate_gold


@pytest.fixture
def options(tmp_path):
    w = tmp_path / "review"; w.mkdir()
    items = [{"id": str(i), "text": text, "split": "dev" if i < 2 else "test",
              "group_id": str(i), "domains": []} for i, text in enumerate(("Quảng cáo ưu đãi.", "Gửi OTP cho tôi.", "Lịch họp ngày mai.", "Tự mở ứng dụng."))]
    write_jsonl(w / "items.jsonl", items)
    write_jsonl(w / "source_labels.jsonl", [{"id": i["id"], "source_label": "DO_NOT_LEAK"} for i in items])
    write_json(w / "audit.json", {})
    write_json(w / "manifest.json", {"source_labels_are_gold": False,
               "files": {n: sha(w / n) for n in ("items.jsonl", "source_labels.jsonl", "audit.json")}})
    for name in ("annotator_a.csv", "annotator_b.csv"): annotation_sheet(w / name, items)
    return SimpleNamespace(workspace=w, out=tmp_path / "out", live=False, batch_size=2,
                           max_tokens=8192, timeout=30, max_new_calls=2, seed=42)


def annotations(messages):
    return {"annotations": [{"id": m["id"], "label": "1" if "OTP" in m["text"] else "0",
        "category": "credential_theft" if "OTP" in m["text"] else "routine", "confidence": "medium",
        "evidence_quote": "OTP" if "OTP" in m["text"] else "", "notes": "Lý do minh họa."} for m in messages]}


def test_parser_rejects_invalid_quote_missing_ids_and_extra_fields():
    messages = [{"id": "1", "text": "Gửi OTP cho tôi."}]
    data = annotations(messages)
    assert parse_annotations(json.dumps(data), messages)[0]["label"] == "1"
    data["annotations"][0]["evidence_quote"] = "bịa"
    with pytest.raises(ValueError, match="quote"): parse_annotations(json.dumps(data), messages)
    with pytest.raises(ValueError, match="IDs"): parse_annotations('{"annotations": []}', messages)
    data = annotations(messages); data["annotations"][0]["source_label"] = "1"
    with pytest.raises(ValueError, match="fields"): parse_annotations(json.dumps(data), messages)


def test_offline_never_calls_provider_or_modifies_blind_sheets(options):
    def fail(request): pytest.fail("Offline must not call the provider")
    result = asyncio.run(generate(options, replace(Settings(), api_key="fixture"), httpx.MockTransport(fail)))
    assert result["valid_annotations"] == 0 and result["counts"] == {"UNKNOWN": 4}
    with (options.workspace / "annotator_a.csv").open(encoding="utf-8-sig") as f:
        assert all(not r["label"] for r in csv.DictReader(f))
    with pytest.raises(ValueError, match="frozen"):
        validate_gold(options.out / "manifest.json", options.out / "labels.jsonl")


def test_live_budget_resume_blinding_and_ai_provenance(options):
    calls = []
    def handler(request):
        data = json.loads(request.content); calls.append(data)
        messages = json.loads(data["messages"][1]["content"])["messages"]
        assert all(set(m) == {"id", "text"} for m in messages)
        assert "DO_NOT_LEAK" not in request.content.decode()
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(annotations(messages))}}],
                                          "usage": {"total_tokens": 100}})
    options.live = True; options.max_new_calls = 1
    settings = replace(Settings(), api_key="fixture")
    first = asyncio.run(generate(options, settings, httpx.MockTransport(handler)))
    assert first["valid_annotations"] == 2 and len(calls) == 1
    options.max_new_calls = 2
    result = asyncio.run(generate(options, settings, httpx.MockTransport(handler)))
    assert result["valid_annotations"] == 4 and len(calls) == 2
    assert result["counts"] == {"0": 3, "1": 1} and result["known_usage"]["total_tokens"] == 200
    assert all(r["annotation_status"] == "ai_preliminary" and not r["independent_human_review"] for r in read_jsonl(options.out / "labels.jsonl"))
    asyncio.run(generate(options, settings, httpx.MockTransport(handler)))
    assert len(calls) == 2
    options.batch_size = 1
    with pytest.raises(ValueError, match="changed"):
        asyncio.run(generate(options, settings, httpx.MockTransport(handler)))


def test_provider_failure_is_not_retried_or_counted_as_valid_unknown(options):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=[])
    options.live = True
    settings = replace(Settings(), api_key="fixture")
    result = asyncio.run(generate(options, settings, httpx.MockTransport(handler)))
    assert result["valid_annotations"] == 0 and result["error_codes"] == {"RESPONSE_INVALID": 2}
    assert all(not r["annotation_available"] for r in read_jsonl(options.out / "labels.jsonl"))
    asyncio.run(generate(options, settings, httpx.MockTransport(handler)))
    assert len(calls) == 2


def test_repair_preserves_available_unknown_and_never_retries_by_label(options):
    from evaluation.prelabel_repair import repair
    calls = []
    def handler(request):
        payload = json.loads(request.content); calls.append(payload)
        messages = json.loads(payload["messages"][1]["content"])["messages"]
        data = annotations(messages)
        if len(calls) == 1:
            data["annotations"][0].update(label="UNKNOWN", category="insufficient_context", notes="Thiếu ngữ cảnh.")
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(data)}}]})
    options.live = True; options.max_new_calls = 1
    settings = replace(Settings(), api_key="fixture")
    asyncio.run(generate(options, settings, httpx.MockTransport(handler)))
    original = {r["id"]: r for r in read_jsonl(options.out / "labels.jsonl") if r["annotation_available"]}
    repair_options = SimpleNamespace(base=options.out, workspace=options.workspace,
        out=options.out.parent / "repair", live=True, max_new_calls=2)
    result = asyncio.run(repair(repair_options, settings, httpx.MockTransport(handler)))
    assert result["valid_annotations"] == 4 and len(calls) == 2
    assert calls[1]["max_tokens"] == 16384
    repaired_ids = {m["id"] for m in json.loads(calls[1]["messages"][1]["content"])["messages"]}
    assert not repaired_ids & original.keys()
    merged = {r["id"]: r for r in read_jsonl(repair_options.out / "merged/labels.jsonl")}
    assert all(merged[k] == r for k, r in original.items())
    with pytest.raises(ValueError, match="frozen"):
        validate_gold(repair_options.out / "merged/manifest.json", repair_options.out / "merged/labels.jsonl")


def test_repair_rejects_changed_base_before_provider(options):
    from evaluation.prelabel_repair import repair
    settings = replace(Settings(), api_key="fixture")
    asyncio.run(generate(options, settings))
    (options.out / "labels.jsonl").write_text("{}")
    args = SimpleNamespace(base=options.out, workspace=options.workspace, out=options.out.parent / "repair", live=True, max_new_calls=2)
    with pytest.raises(ValueError, match="changed"):
        asyncio.run(repair(args, settings, httpx.MockTransport(lambda r: pytest.fail("No request on changed input"))))


def test_truncated_annotation_keeps_reported_usage_but_no_labels(options):
    def handler(request):
        return httpx.Response(200, json={"choices": [{"finish_reason": "length", "message": {"content": "incomplete"}}],
                                          "usage": {"total_tokens": 8192}})
    options.live = True
    result = asyncio.run(generate(options, replace(Settings(), api_key="fixture"), httpx.MockTransport(handler)))
    assert result["valid_annotations"] == 0
    assert result["known_usage"]["total_tokens"] == 16384
    assert result["error_codes"] == {"OUTPUT_TRUNCATED": 2}


def test_repair_can_continue_from_a_merged_run_without_losing_prior_annotations(options):
    from evaluation.prelabel_repair import repair
    settings = replace(Settings(), api_key="fixture")
    asyncio.run(generate(options, settings))
    state = {"calls": 0}
    def handler(request):
        state["calls"] += 1
        payload = json.loads(request.content)
        messages = json.loads(payload["messages"][1]["content"])["messages"]
        if state["calls"] == 2: return httpx.Response(200, json=[])
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(annotations(messages))}}]})
    first = SimpleNamespace(base=options.out, workspace=options.workspace, out=options.out.parent / "repair1",
                            live=True, max_new_calls=2, batch_size=2)
    result = asyncio.run(repair(first, settings, httpx.MockTransport(handler)))
    assert result["valid_annotations"] == 2
    before = {r["id"]: r for r in read_jsonl(first.out / "merged/labels.jsonl") if r["annotation_available"]}
    second = SimpleNamespace(base=first.out / "merged", workspace=options.workspace, out=options.out.parent / "repair2",
                             live=True, max_new_calls=2, batch_size=1)
    final = asyncio.run(repair(second, settings, httpx.MockTransport(handler)))
    assert final["valid_annotations"] == 4
    after = {r["id"]: r for r in read_jsonl(second.out / "merged/labels.jsonl")}
    assert all(after[k] == r for k, r in before.items())
