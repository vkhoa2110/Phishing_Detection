from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pytest

from evaluation.retrieval_comparison import BM25, reciprocal_rank_fusion, validate_queries
from app.rag_service import read_jsonl, sha_file

ROOT = Path(__file__).resolve().parents[1]


def test_bm25_unicode_and_rrf_agreement():
    bm25 = BM25(["Xác minh QR Zalo", "Cấp điện EVN", "Đặt vé trả sau"])
    scores = bm25.score("XA\u0301C MINH Zalo")
    assert scores[0] > 0 and scores[1] == scores[2] == 0
    chunks = [{"chunk_id": str(i)} for i in range(3)]
    fused = reciprocal_rank_fusion(np.array([.8, .9, .1]), np.array([2., 1., 0.]), chunks)
    assert fused[0] == fused[1] and fused[0] > fused[2]


def test_relevance_validation_rejects_leakage_and_false_support():
    doc = {"id": "d1", "text": "Nội dung hỗ trợ."}
    dev = [{"id": "d", "text": "Một câu", "relevant_ids": ["d1"], "support": [{"document_id": "d1", "quote": "hỗ trợ"}]},
           {"id": "dn", "text": "Không nguồn dev", "relevant_ids": []}]
    test = [{"id": "t", "text": "Câu khác", "relevant_ids": ["d1"]}, {"id": "tn", "text": "Không nguồn test", "relevant_ids": []}]
    validate_queries(dev, test, [doc])
    changed = deepcopy(test); changed[0]["text"] = "  MỘT CÂU "
    with pytest.raises(ValueError, match="overlap"):
        validate_queries(dev, changed, [doc])
    changed = deepcopy(dev); changed[0]["support"][0]["quote"] = "trích dẫn bịa"
    with pytest.raises(ValueError, match="substring"):
        validate_queries(changed, test, [doc])
    changed = deepcopy(test); changed[0]["relevant_ids"] = ["unknown"]
    with pytest.raises(ValueError, match="Unknown"):
        validate_queries(dev, changed, [doc])


def test_v2_snapshot_retains_original_sources_and_does_not_reuse_reserved_ids():
    old = read_jsonl(ROOT / "data/knowledge/corpus_v1/documents.jsonl")
    new = read_jsonl(ROOT / "data/knowledge/corpus_v2/documents.jsonl")
    assert new[:len(old)] == old
    reserved = {s["id"] for s in json.loads((ROOT / "data/knowledge/source_catalog.json").read_text())["sources"]}
    added = new[len(old):]
    assert len(added) == 12 and len(new) == 37
    assert not reserved & {d["id"] for d in added}
    assert len({d["scenario"] for d in added}) == 8
    assert sum(d["kind"] == "legitimate_workflow" for d in new) == 11
    manifest = json.loads((ROOT / "data/knowledge/corpus_v2/manifest.json").read_text())
    for name, expected in manifest["files"].items():
        assert sha_file(ROOT / "data/knowledge/corpus_v2" / name) == expected


def test_v2_queries_are_frozen_have_claim_support_and_are_separate_from_sms_gold():
    directory = ROOT / "data/evaluation"
    manifest = json.loads((directory / "rag_retrieval_v2_manifest.json").read_text())
    for name, expected in manifest["files"].items():
        assert sha_file(directory / name) == expected
    dev, test = [read_jsonl(directory / f"rag_retrieval_{split}_v2.jsonl") for split in ("dev", "test")]
    validate_queries(dev, test, read_jsonl(ROOT / "data/knowledge/corpus_v2/documents.jsonl"))
    assert len(dev) == 60 and len(test) == 40
    assert sum(bool(c["relevant_ids"]) for c in dev) == 40
    assert sum(bool(c["relevant_ids"]) for c in test) == 24
    assert all("label" not in c and c["annotation"] == "assistant_authored_not_human_verified" for c in dev + test)
    old = sum([read_jsonl(directory / f"rag_retrieval_{s}_v1.jsonl") for s in ("dev", "test")], [])
    assert not {c["text"] for c in old} & {c["text"] for c in dev + test}
    for kind in ("unsupported_entity", "unsupported_temporal", "specific_verification", "out_of_scope"):
        assert any(c["query_kind"] == kind and not c["relevant_ids"] for c in test)
