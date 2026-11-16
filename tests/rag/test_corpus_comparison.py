import pytest

from evaluation.rag.corpus_comparison import score, validate_grid


def test_expansion_uses_the_same_relevance_denominator_for_both_corpora():
    rows = [{"direct_ids": ["old"], "selected_ids": ["old"]},
            {"direct_ids": ["new"], "selected_ids": ["old"]},
            {"direct_ids": [], "selected_ids": ["old"]}]
    before = score(rows, {"old"})
    assert before["answerable_in_this_corpus"] == 1
    assert before["hit_on_fixed_expanded_denominator"] == .5
    rows[1]["selected_ids"] = ["new"]
    after = score(rows, {"old", "new"})
    assert after["answerable_in_expanded_reference"] == before["answerable_in_expanded_reference"] == 2
    assert after["hit_on_fixed_expanded_denominator"] == 1
    assert after["no_match_queries"] == 1 and not after["abstention_policy_evaluated"]


def test_unjudged_pairs_and_changed_old_documents_are_rejected():
    queries = [{"id": "q"}]
    old = [{"id": "a", "text": "unchanged"}]
    new = old + [{"id": "b", "text": "new"}]
    grades = [{"query_id": "q", "document_id": "a", "grade": 2}]
    with pytest.raises(ValueError, match="every query/document"):
        validate_grid(queries, old, new, grades)
    grades.append({"query_id": "q", "document_id": "b", "grade": 0})
    assert len(validate_grid(queries, old, new, grades)) == 2
    new[0] = {"id": "a", "text": "quiet rewrite"}
    with pytest.raises(ValueError, match="unchanged"):
        validate_grid(queries, old, new, grades)
