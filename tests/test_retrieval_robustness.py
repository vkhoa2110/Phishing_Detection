import numpy as np

from evaluation.retrieval_robustness import augment_dev, dual_scores, fold_accents, select_on_dev


def test_folding_handles_decomposed_vietnamese_and_preserves_numbers_and_urls():
    assert fold_accents("Điện lực 2026 https://EVN.vn/a?x=1") == "Dien luc 2026 https://EVN.vn/a?x=1"
    assert fold_accents("OTP BIDV") == "OTP BIDV"


def test_augmented_dev_retains_parent_labels_and_deduplicates_existing_ascii():
    cases = [{"id": "a", "text": "Mã xác minh", "relevant_ids": ["doc"]},
             {"id": "b", "text": "OTP", "relevant_ids": []}]
    rows = augment_dev(cases)
    assert len(rows) == 3
    assert {r["text"] for r in rows} == {"Mã xác minh", "Ma xac minh", "OTP"}
    assert all(r["relevant_ids"] == cases[0]["relevant_ids"] for r in rows if r["parent_id"] == "a")
    assert all(r["split"] == "dev" for r in rows)


def test_dual_views_do_not_cross_compare_incompatible_spaces():
    original_q, folded_q = np.array([[0., 1.]]), np.array([[1., 0.]])
    original_docs, folded_docs = np.array([[1., 0.]]), np.array([[0., 1.]])
    assert dual_scores(original_q, folded_q, original_docs, folded_docs).tolist() == [0.]


def test_method_selection_never_relaxes_dev_hit_constraint():
    def row(label, doc, score):
        return {"relevant_ids": label, "ranked": [{"document_id": doc, "score": score}], "elapsed_ms": 1}
    predictions = {
        "e5_original": [row(["a"], "wrong", .95), row([], "a", .1)],
        "e5_dual_view": [row(["a"], "wrong", .95), row([], "a", .1)],
        "bm25_original": [row(["a"], "a", .9), row([], "a", .95)],
        "bm25_folded": [row(["a"], "a", .9), row([], "a", .1)]}
    calibrations, selected = select_on_dev(predictions)
    assert selected == "bm25_folded"
    assert calibrations["e5_original"]["min_score"] is None
    assert calibrations["bm25_folded"]["min_score"] == .9
