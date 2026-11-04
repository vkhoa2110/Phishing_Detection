import pytest

from scripts.evaluation.verify_rag_ablation import verify_original_fields


def fixture():
    original = {"id":"fixture", "label":0, "text":"Thông báo https://example.org", "urls":["https://example.org"]}
    prepared = {"urls":[{"url":"https://example.org", "score":.8, "status":"ok"}], "retrieval":{"sources":[]}}
    result = {**original, **prepared}
    return original, prepared, result


def test_url_annotation_and_scored_url_records_have_verified_correspondence():
    original, prepared, result = fixture()
    verify_original_fields(original, result, prepared)
    original.pop("urls")  # Historical message inputs did not carry this field.
    verify_original_fields(original, result, prepared)


def test_changed_reference_label_or_url_target_cannot_pass_verification():
    original, prepared, result = fixture()
    result["label"] = 1
    with pytest.raises(AssertionError, match="Reference field changed"):
        verify_original_fields(original, result, prepared)
    original, prepared, result = fixture()
    prepared["urls"][0]["url"] = "https://different.example"
    with pytest.raises(AssertionError, match="URL targets changed"):
        verify_original_fields(original, result, prepared)


def test_saved_result_cannot_silently_drop_a_scored_url():
    original, prepared, result = fixture()
    result["urls"] = []
    with pytest.raises(AssertionError, match="Prepared inputs changed"):
        verify_original_fields(original, result, prepared)


def test_actual_parser_disagreement_is_exposed_without_mutating_frozen_run():
    original, prepared, result = fixture()
    original["text"] = "Câu trích: «https://example.org»"
    result["text"] = original["text"]
    prepared["urls"][0]["url"] = "https://example.org»"
    difference = verify_original_fields(original, result, prepared)
    assert difference == {"id":"fixture", "annotated_urls":["https://example.org"], "extracted_urls":["https://example.org»"]}
    assert original["urls"] == ["https://example.org"]
