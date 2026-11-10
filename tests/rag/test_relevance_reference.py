import csv
import json

import pytest

from evaluation.data.sms import sha
from evaluation.rag.relevance_reference import prepare
from evaluation.rag.review import score
from tests.data.test_benchmark_pack import prepared


def test_ai_relevance_is_complete_inspectable_and_never_human_gold(prepared, tmp_path):
    pack, _ = prepared
    out = tmp_path / "ai-relevance"
    result = prepare(pack, out)
    assert result["pairs"] == 600
    assert result["queries_with_direct_source"] == 10
    assert result["queries_without_direct_source"] == 14
    m = json.loads((out / "manifest.json").read_text())
    assert m["status"] == "ai_reference_unverified" and m["rater_ids"] == []
    assert m["corpus_sha256"] == sha(pack / "retrieval/corpus.jsonl")
    rows = json.loads((out / "judgments.json").read_text())
    assert all(r["notes"] and not r["rater_id"] for r in rows)
    assert all(r["support_quote"] in r["document_text"] and r["support_quote"].strip() for r in rows if r["grade"] == 2)
    with (out / "review.csv").open(encoding="utf-8-sig") as f:
        exported = list(csv.DictReader(f))
    assert sum(r["grade"] == "0" for r in exported) > 0
    with pytest.raises(ValueError, match="independent review"):
        score(out, {}, "test")
    before = {p.name: sha(p) for p in out.iterdir()}
    with pytest.raises(ValueError, match="already exists"):
        prepare(pack, out)
    assert before == {p.name: sha(p) for p in out.iterdir()}
