import asyncio
from collections import Counter
from dataclasses import replace
import json

import httpx
import pytest

from app.llm_service import LLMService, RAG_PROMPT_VERSION, PROMPT_VERSION
from app.settings import Settings
from app.urls import extract_urls
from evaluation.ablation import ARMS, DATASET, assemble_rows, call_arm, load_cases, summarize
from evaluation.run import load_checkpoints, prepare_manifest


def test_frozen_dataset_balanced_and_has_url_and_no_url_strata():
    cases = load_cases(DATASET)
    assert len(cases) == 100
    assert Counter(c["label"] for c in cases) == {0: 50, 1: 50}
    for has_url, n in ((True, 60), (False, 40)):
        subset = [c for c in cases if bool(extract_urls(c["text"], "text")[0]) == has_url]
        assert len(subset) == n
        assert sum(c["label"] for c in subset) == n // 2
    assert all(c["annotation"] == "assistant_label_not_independently_verified" for c in cases)


def test_four_arms_identical_input_and_isolated_ml_and_rag_without_label_leakage():
    payloads = []
    def handler(request):
        payloads.append(json.loads(request.content))
        content = {"risk_level": "LOW", "summary": "Chưa có dấu hiệu", "evidence": [],
                   "recommended_actions": [], "knowledge_support": []}
        # baseline schema forbids extra RAG fields.
        if "reference_documents" not in json.loads(payloads[-1]["messages"][1]["content"]):
            del content["knowledge_support"]
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(content)}}]})
    case = {"text": "Đọc https://example.org/?token=private", "label": 1,
            "rationale": "MUST_NOT_LEAK", "id": "LABEL_SECRET"}
    prepared = {"urls": [{"id": "URL-01", "url": "https://example.org/?token=private", "status": "ok",
                         "risk_level": "HIGH", "score": .9, "warning_threshold": .1, "high_threshold": .5}],
                "retrieval": {"sources": [{"document_id": "VN-RAG-001", "text": "Bảo vệ tài khoản cá nhân.",
                    "title": "Tài liệu", "context_note": "Tóm lược", "publisher": "Nguồn", "published_at": None}]}}
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            service = LLMService(replace(Settings(), api_key="test-fixture"), client)
            results = [await call_arm(service, case, prepared, a) for a in ARMS]
            assert [r["prompt_version"] for r in results] == [PROMPT_VERSION, PROMPT_VERSION, RAG_PROMPT_VERSION, RAG_PROMPT_VERSION]
    asyncio.run(exercise())
    bodies = [json.loads(p["messages"][1]["content"]) for p in payloads]
    assert len({b["text"] for b in bodies}) == 1
    assert ["url_results" in b for b in bodies] == [False, True, False, True]
    assert ["reference_documents" in b for b in bodies] == [False, False, True, True]
    assert bodies[2]["reference_documents"] == bodies[3]["reference_documents"]
    assert "MUST_NOT_LEAK" not in json.dumps(payloads)
    assert "LABEL_SECRET" not in json.dumps(payloads)
    assert "private" not in bodies[0]["text"]


def test_no_url_unknown_ml_and_completed_llm_not_affected_by_pending_arms():
    cases = [{"id": "X", "label": 0, "category": "context", "text": "Họp nhóm lúc 14 giờ."}]
    prepared = {"X": {"urls": [], "invalid_urls": [], "ml_ms": 0,
                      "retrieval": {"status": "empty", "sources": []}}}
    low = {"status": "ok", "verdict": {"risk_level": "LOW"}, "elapsed_ms": 10}
    rows = assemble_rows(cases, prepared, {("X", "llm_only"): low})
    assert rows[0]["levels"]["url_model_only"] == "UNKNOWN"
    assert rows[0]["levels"]["llm_only"] == "LOW"
    assert rows[0]["levels"]["fusion_llm_only"] == "LOW"
    assert rows[0]["levels"]["fusion_llm_rag"] == "UNKNOWN"
    summary = summarize(rows)
    assert summary["complete_cases"] == 0
    assert summary["metrics"]["llm_only"]["accuracy"] == 1
    assert summary["by_url"]["with_url"]["llm_only"]["n"] == 0
    assert summary["metrics"]["url_model_only"]["unknown_negative"] == 1


def test_error_and_high_ml_preserved_and_not_counted_as_successful_pair():
    cases = [{"id": "X", "label": 0, "category": "context", "text": "Tài liệu https://example.org"}]
    prepared = {"X": {"urls": [{"status": "ok", "risk_level": "HIGH"}], "invalid_urls": [],
                      "retrieval": {"status": "ok", "sources": [{"document_id": "VN-RAG-001"}]}}}
    cache = {("X", a): {"status": "error", "code": "TIMEOUT"} for a in ARMS}
    rows = assemble_rows(cases, prepared, cache)
    assert all(rows[0]["levels"][a] == "UNKNOWN" for a in ARMS)
    assert all(rows[0]["levels"]["fusion_" + a] == "HIGH" for a in ARMS)
    s = summarize(rows)
    assert s["metrics"]["fusion_llm_url_rag"]["fp"] == 1
    assert s["error_codes"]["llm_rag"] == {"TIMEOUT": 1}
    assert s["comparisons"]["rag_without_url"]["both_successful"]["n"] == 0


def test_resume_manifest_rejects_changed_source_or_corpus_and_keeps_error_checkpoint(tmp_path):
    config = {"arms": list(ARMS), "corpus_sha256": "original", "source_sha256": "original"}
    prepare_manifest(tmp_path, config)
    for change in ("corpus_sha256", "source_sha256"):
        with pytest.raises(ValueError, match="different"):
            prepare_manifest(tmp_path, {**config, change: "changed"})
    line = {"case_id": "X", "arm": "llm_rag", "result": {"status": "error", "code": "TIMEOUT"}}
    path = tmp_path / "checkpoints.jsonl"
    path.write_text(json.dumps(line) + "\n")
    assert load_checkpoints(path)[("X", "llm_rag")]["code"] == "TIMEOUT"


def test_live_budget_and_resume_never_repeat_paid_calls(monkeypatch, tmp_path):
    from types import SimpleNamespace
    import evaluation.ablation as module
    model_dir, index_dir, embedding_dir = (tmp_path / n for n in ("model", "index", "embedding"))
    for directory in (model_dir, index_dir, embedding_dir):
        directory.mkdir()
    (model_dir / "model.json").write_text("{}")
    (index_dir / "manifest.json").write_text("{}")
    (embedding_dir / "phishlens_model.json").write_text("{}")
    (tmp_path / "corpus.jsonl").write_text("{}\n")
    settings = replace(Settings(), root=tmp_path, api_key="test-fixture", rag_index_dir="index",
                       rag_model_dir="embedding", rag_corpus="corpus.jsonl")
    class FakeML:
        path = model_dir
        def load(self):
            return {"ready": True}
        def predict(self, urls):
            assert not urls
            return []
    prepared_calls, paid_calls = [], []
    class FakeRAG:
        def status(self):
            return {"ready": True}
        def search(self, text):
            prepared_calls.append(text)
            return {"status": "empty", "sources": []}
    class FakeService:
        async def analyze(self, **kwargs):
            paid_calls.append(kwargs)
            await asyncio.sleep(0)
            return {"status": "ok", "verdict": {"risk_level": "LOW"}, "elapsed_ms": 1,
                    "rag": False, "included_ml": False}
    monkeypatch.setattr(module, "Settings", lambda: settings)
    monkeypatch.setattr(module, "ModelService", lambda _: FakeML())
    monkeypatch.setattr(module, "RAGService", lambda _: FakeRAG())
    monkeypatch.setattr(module, "LLMService", lambda *_: FakeService())
    dataset = tmp_path / "cases.jsonl"
    dataset.write_text("".join(json.dumps({"id": str(i), "text": text, "label": i,
        "category": "test", "rationale": "fixture"}) + "\n" for i, text in enumerate(("Họp nhóm.", "Gửi mật khẩu."))))
    args = SimpleNamespace(dataset=dataset, out=tmp_path / "out", max_tokens=4096, timeout=90,
                           live=True, max_new_calls=3, seed=42, workers=2)
    first = asyncio.run(module.evaluate(args))
    assert len(paid_calls) == 3
    assert first["run_state"]["stop_reason"] == "call_budget_reached"
    args.max_new_calls = 8
    second = asyncio.run(module.evaluate(args))
    assert len(paid_calls) == 8  # Five new requests, not eight more.
    assert len(prepared_calls) == 2  # Same retrieval snapshot reused for all arms and resume.
    assert second["complete_cases"] == 2
    assert second["run_state"]["new_api_calls"] == 5
    assert second["run_state"]["stop_reason"] == "all_calls_completed"
    assert len(load_checkpoints(args.out / "checkpoints.jsonl")) == 8
