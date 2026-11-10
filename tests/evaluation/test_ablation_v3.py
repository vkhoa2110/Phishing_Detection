"""Versioned v3 ablation uses the existing gold gate and immutable offline snapshots."""
import asyncio
from dataclasses import replace
import json
from types import SimpleNamespace

import httpx
import pytest

from app.services.llm.client import LLMService, MESSAGE_V3_PROMPT_VERSION, MESSAGE_V3_RAG_PROMPT_VERSION
from app.core.settings import Settings
import evaluation.messages.ablation as ablation
from evaluation.messages.baseline import digest


@pytest.mark.parametrize("profile", ["message-v2", "message-v3"])
def test_message_benchmark_requires_double_review_before_preparation(tmp_path, profile):
    args = SimpleNamespace(prompt_profile=profile, fusion_policy="separate", diagnostic=False,
                           reviewed_manifest=None, dataset=tmp_path / "missing.jsonl", out=tmp_path / "out")
    with pytest.raises(ValueError, match="requires --reviewed-manifest"):
        asyncio.run(ablation.evaluate(args))
    assert not args.out.exists()


@pytest.mark.parametrize("diagnostic", [False, True])
def test_v3_never_accepts_provisional_labels_as_reviewed_gold(tmp_path, diagnostic):
    manifest = tmp_path / "ai_manifest.json"
    manifest.write_text(json.dumps({"status": "ai_provisional", "rater_ids": ["same-model"]}))
    args = SimpleNamespace(prompt_profile="message-v3", fusion_policy="separate", diagnostic=diagnostic,
                           reviewed_manifest=manifest, dataset=tmp_path / "test.jsonl", out=tmp_path / "out")
    with pytest.raises(ValueError, match="double-reviewed"):
        asyncio.run(ablation.evaluate(args))
    assert not args.out.exists()


def offline_environment(monkeypatch, tmp_path):
    model_dir, index_dir, embedding_dir = (tmp_path / name for name in ("model", "index", "embedding"))
    for directory in (model_dir, index_dir, embedding_dir):
        directory.mkdir()
    (model_dir / "model.json").write_text("{}")
    (index_dir / "manifest.json").write_text("{}")
    (embedding_dir / "phishlens_model.json").write_text("{}")
    (tmp_path / "corpus.jsonl").write_text("{}\n")
    settings = replace(Settings(), root=tmp_path, api_key="", rag_index_dir="index",
                       rag_model_dir="embedding", rag_corpus="corpus.jsonl")
    scope_flags, searches = [], []

    class FakeML:
        path = model_dir

        def load(self):
            return {"ready": True}

        def predict(self, urls):
            assert urls == []
            return []

    class FakeRAG:
        def __init__(self, settings, include_scope=False):
            scope_flags.append(include_scope)

        def status(self):
            return {"ready": True}

        def search(self, text):
            searches.append(text)
            return {"status": "ok", "sources": [{"document_id": "VN-RAG-001",
                    "scope": "Thông tin chung; chưa xác minh người gửi."}]}

    def forbidden_service(*args, **kwargs):
        pytest.fail("Offline preparation must not initialize the provider service.")

    monkeypatch.setattr(ablation, "Settings", lambda: settings)
    monkeypatch.setattr(ablation, "ModelService", lambda _: FakeML())
    monkeypatch.setattr(ablation, "RAGService", FakeRAG)
    monkeypatch.setattr(ablation, "LLMService", forbidden_service)
    monkeypatch.setattr(ablation.importlib.metadata, "version", lambda name: "offline-fixture")
    dataset = tmp_path / "cases.jsonl"
    dataset.write_text("".join(json.dumps({"id": str(i), "text": text, "label": i,
        "category": "test", "rationale": "Synthetic test fixture, not reviewed gold."}) + "\n"
        for i, text in enumerate(("Họp nhóm.", "Gửi mật khẩu cho tôi."))), encoding="utf-8")
    args = SimpleNamespace(dataset=dataset, out=tmp_path / "out", max_tokens=4096, timeout=90,
                           live=False, max_new_calls=0, seed=42, workers=1, diagnostic=True,
                           reviewed_manifest=None, prompt_profile="message-v3", fusion_policy="separate")
    return args, scope_flags, searches


def test_v3_offline_manifest_records_profiles_scope_and_non_gold_status(monkeypatch, tmp_path):
    args, scope_flags, searches = offline_environment(monkeypatch, tmp_path)
    result = asyncio.run(ablation.evaluate(args))
    configuration = json.loads((args.out / "manifest.json").read_text())["configuration"]
    assert configuration["llm"]["prompt_versions"] == [MESSAGE_V3_PROMPT_VERSION, MESSAGE_V3_RAG_PROMPT_VERSION]
    assert configuration["rag_scope_metadata"] is True
    assert configuration["retrieval_score_contract"] == "rounded_cosine_6_decimals"
    assert configuration["reviewed_gold"] is None and configuration["diagnostic"] is True
    assert configuration["dataset_sha256"] == digest(args.dataset)
    assert configuration["source_sha256"]["evaluation/messages/ablation.py"] == digest(ablation.__file__)
    assert scope_flags == [True] and len(searches) == 2
    assert "không phải gold" in (args.out / "report.md").read_text(encoding="utf-8")
    assert result["run_state"]["new_api_calls"] == 0
    assert result["complete_cases"] == 0
    assert not (args.out / "checkpoints.jsonl").exists()


def test_v3_profile_change_cannot_overwrite_or_reuse_old_results(monkeypatch, tmp_path):
    args, _, searches = offline_environment(monkeypatch, tmp_path)
    asyncio.run(ablation.evaluate(args))
    original = {path.name: digest(path) for path in args.out.iterdir()}
    args.prompt_profile = "message-v2"
    with pytest.raises(ValueError, match="different dataset/model/prompt/configuration"):
        asyncio.run(ablation.evaluate(args))
    assert {path.name: digest(path) for path in args.out.iterdir()} == original
    assert len(searches) == 2


def test_v3_resume_refuses_changed_prepared_scope(monkeypatch, tmp_path):
    args, _, searches = offline_environment(monkeypatch, tmp_path)
    asyncio.run(ablation.evaluate(args))
    snapshot = args.out / "prepared_cases.json"
    prepared = json.loads(snapshot.read_text())
    prepared["0"]["retrieval"]["sources"][0]["scope"] = "Modified source scope"
    snapshot.write_text(json.dumps(prepared))
    with pytest.raises(ValueError, match="Prepared snapshot was modified"):
        asyncio.run(ablation.evaluate(args))
    assert len(searches) == 2


def test_v3_four_arms_share_inputs_and_scope_without_label_leakage():
    payloads = []

    def handler(request):
        body = json.loads(request.content)
        payloads.append(body)
        data = json.loads(body["messages"][1]["content"])
        verdict = {"context_kind": "routine", "risk_level": "LOW", "summary": "Thông báo họp nhóm.",
                   "evidence": [], "recommended_actions": []}
        if "reference_documents" in data:
            verdict["knowledge_support"] = []
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(verdict)}}]})

    case = {"id": "LABEL_SECRET", "label": 0, "rationale": "NEVER_SEND_ANNOTATIONS", "text": "Họp nhóm lúc 14 giờ."}
    prepared = {"urls": [], "retrieval": {"sources": [{
        "document_id": "VN-RAG-001", "title": "Nguồn minh họa", "text": "Xác minh yêu cầu qua kênh đã biết.",
        "publisher": "Đơn vị minh họa", "published_at": None, "context_note": "Chưa xác minh người gửi.",
        "scope": "Hướng dẫn chung", "document_role": "mixed_guidance", "valid_from": None,
    }]}}

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            service = LLMService(replace(Settings(), api_key="test-fixture"), client)
            return [await ablation.call_arm(service, case, prepared, arm, "message-v3") for arm in ablation.ARMS]

    results = asyncio.run(exercise())
    assert [result["prompt_version"] for result in results] == [MESSAGE_V3_PROMPT_VERSION] * 2 + [MESSAGE_V3_RAG_PROMPT_VERSION] * 2
    bodies = [json.loads(payload["messages"][1]["content"]) for payload in payloads]
    assert len({body["text"] for body in bodies}) == 1
    assert ["url_results" in body for body in bodies] == [False, True, False, True]
    assert ["reference_documents" in body for body in bodies] == [False, False, True, True]
    assert bodies[2]["reference_documents"] == bodies[3]["reference_documents"]
    assert bodies[2]["reference_documents"][0]["scope"] == "Hướng dẫn chung"
    assert "LABEL_SECRET" not in json.dumps(payloads)
    assert "NEVER_SEND_ANNOTATIONS" not in json.dumps(payloads)
