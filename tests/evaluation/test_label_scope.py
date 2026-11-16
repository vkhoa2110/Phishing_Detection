from evaluation.messages.label_scope import review_rows


def test_review_sheet_has_no_predictions_or_ai_labels_and_makes_no_safety_claim():
    cases = [{"id": "b", "text": "Cập nhật giao hàng https://example.org", "label": 0, "score": .99},
             {"id": "a", "text": "Thông báo", "prediction": "HIGH"}]
    rows = review_rows(cases)
    assert [r["id"] for r in rows] == ["a", "b"]
    for row in rows:
        assert not {"label", "score", "prediction"} & set(row)
        assert row["behavior_label"] == row["whole_message_label"] == row["url_evidence_status"] == ""
        assert row["evidence_source_url"] == row["reviewer"] == ""
