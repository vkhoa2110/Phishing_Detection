"""Tiny fabricated reviewer fixtures test validation, never populate real gold."""
import csv
import math

import pytest

from evaluation.benchmark_pack import RELEVANCE_FIELDS, sheet
from evaluation.message_data import sha, write_json, write_jsonl
from evaluation.relevance_review import adjudicate, finalize, score
from evaluation.review import ReviewPending


@pytest.fixture
def review(tmp_path):
    path = tmp_path / "review"
    path.mkdir()
    queries = [{"id": "q1", "text": "Yêu cầu OTP", "split": "test"},
               {"id": "q2", "text": "Không có tài liệu", "split": "test"}]
    docs = [{"id": f"d{i}", "text": f"Nội dung minh họa {i}", "title": "Fixture", "publisher": "Fixture", "source_url": "https://example.org"} for i in range(1, 4)]
    pairs = [{"query_id": q["id"], "document_id": d["id"], "query": q["text"], "document_text": d["text"],
              "title": d["title"], "publisher": d["publisher"], "source_url": d["source_url"], "scope": "", "published_at": None}
             for q in queries for d in docs]
    write_jsonl(path / "queries.jsonl", queries)
    write_jsonl(path / "corpus.jsonl", docs)
    write_jsonl(path / "pairs.jsonl", pairs)
    write_json(path / "rubric.json", {"fixture": True})
    write_json(path / "manifest.json", {"files": {n: sha(path / n) for n in ("queries.jsonl", "corpus.jsonl", "pairs.jsonl", "rubric.json")}})
    for side in ("a", "b"):
        sheet(path / f"annotator_{side}.csv", pairs, RELEVANCE_FIELDS)
    return path, pairs


def fill(path, pairs, identity, override=None):
    rows = []
    for p in pairs:
        grade = "2" if (p["query_id"], p["document_id"]) == ("q1", "d1") else "1" if (p["query_id"], p["document_id"]) == ("q1", "d2") else "0"
        row = {**p, "grade": grade, "notes": "Fabricated unit-test review, not human annotation.",
               "rater_id": identity, "support_quote": p["document_text"] if grade == "2" else ""}
        if override:
            override(row)
        rows.append(row)
    sheet(path, rows, RELEVANCE_FIELDS)


def test_no_retrieval_metric_from_blank_or_ai_ratings(review, tmp_path):
    path, _ = review
    with pytest.raises(ReviewPending):
        finalize(path, tmp_path / "gold")
    assert not (tmp_path / "gold").exists()
    ai = tmp_path / "ai"
    ai.mkdir()
    write_json(ai / "manifest.json", {"status": "ai_reference_unverified", "rater_ids": []})
    with pytest.raises(ValueError, match="independent review"):
        score(ai, {}, "test")


def test_exhaustive_consensus_scoring_has_correct_denominators(review, tmp_path):
    path, pairs = review
    for side in ("a", "b"):
        fill(path / f"annotator_{side}.csv", pairs, "unit-test-" + side)
    gold = tmp_path / "gold"
    result = finalize(path, gold)
    assert result["pairs"] == 6 and result["unknown_pairs"] == 0
    result = score(gold, {"q1": ["d2", "d1"], "q2": []}, "test")
    m = result["metrics"]
    assert m["hit_at_3"] == {"value": 1, "n": 1}
    assert m["precision_at_3"]["value"] == pytest.approx(1 / 6)
    assert m["precision_returned"] == {"value": .5, "n": 1}
    assert m["recall_at_3"] == {"value": 1, "n": 1}
    assert m["mrr_at_3"] == {"value": .5, "n": 1}
    assert m["ndcg_at_3"]["value"] == pytest.approx((1 + 3 / math.log2(3)) / (3 + 1 / math.log2(3)))
    assert m["no_match_rejection"] == {"value": 1, "n": 1}
    with pytest.raises(ValueError, match="already exists"):
        finalize(path, gold)
    with pytest.raises(ValueError, match="exactly"):
        score(gold, {"q1": ["d1"]}, "test")
    with pytest.raises(ValueError, match="duplicate"):
        score(gold, {"q1": ["d1", "d1"], "q2": []}, "test")


def test_unknown_judgment_cannot_become_no_match_success(review, tmp_path):
    path, pairs = review
    def unknown(row):
        if row["query_id"] == "q2" and row["document_id"] == "d3":
            row["grade"] = "UNKNOWN"
    for side in ("a", "b"):
        fill(path / f"annotator_{side}.csv", pairs, "unit-test-" + side, unknown)
    gold = tmp_path / "gold"
    finalize(path, gold)
    result = score(gold, {"q1": ["d1"], "q2": []}, "test")
    assert result["unknown_judgment_queries"] == ["q2"]
    assert result["scored_queries"] == 1
    assert result["metrics"]["no_match_rejection"] == {"value": None, "n": 0}


def test_same_identity_bad_quote_and_changed_text_are_rejected(review, tmp_path):
    path, pairs = review
    for side in ("a", "b"):
        fill(path / f"annotator_{side}.csv", pairs, "same-fixture")
    with pytest.raises(ValueError, match="different"):
        finalize(path, tmp_path / "gold")
    fill(path / "annotator_b.csv", pairs, "other-fixture", lambda r: r.update(support_quote="invented") if r["grade"] == "2" else None)
    with pytest.raises(ValueError, match="not in"):
        finalize(path, tmp_path / "gold")
    fill(path / "annotator_b.csv", pairs, "other-fixture", lambda r: r.update(query="changed"))
    with pytest.raises(ValueError, match="must not change"):
        finalize(path, tmp_path / "gold")


def test_disagreement_requires_a_third_reviewer_and_frozen_hashes(review, tmp_path):
    path, pairs = review
    fill(path / "annotator_a.csv", pairs, "unit-test-a")
    fill(path / "annotator_b.csv", pairs, "unit-test-b", lambda r: r.update(grade="1") if r["grade"] == "2" else None)
    gold = tmp_path / "gold"
    with pytest.raises(ReviewPending, match="third"):
        finalize(path, gold)
    assert adjudicate(path)["disagreements"] == 1
    difference = [p for p in pairs if (p["query_id"], p["document_id"]) == ("q1", "d1")]
    fill(path / "adjudication.csv", difference, "unit-test-a")
    with pytest.raises(ValueError, match="differ"):
        finalize(path, gold)
    fill(path / "adjudication.csv", difference, "unit-test-third")
    finalize(path, gold)
    (gold / "judgments.json").write_text("[]")
    with pytest.raises(ValueError, match="changed"):
        score(gold, {"q1": [], "q2": []}, "test")
