from evaluation.data.cohort_audit import compare


def test_different_cohorts_are_not_fabricated_label_changes():
    result, rows = compare([{"id": "a", "text": "Một tin", "label": 1, "group_id": "g1"}],
                           [{"id": "b", "text": "Tin khác", "label": 0, "group_id": "g2"}])
    assert result["shared_IDs"] == result["label_changes_on_same_text"] == 0
    assert rows[0]["new_label"] == "N/A" and rows[1]["old_label"] == "N/A"


def test_label_change_requires_the_same_id_and_normalized_message():
    a = {"id": "a", "text": "Một   tin", "label": 1}
    result, rows = compare([a], [{"id": "a", "text": "một tin", "label": None}])
    assert result["label_changes_on_same_text"] == 1 and rows[0]["new_label"] == "UNKNOWN"
    result, rows = compare([a], [{"id": "a", "text": "Nội dung khác", "label": 0}])
    assert result["label_changes_on_same_text"] == 0
    assert result["same_ID_different_text_needs_review"] == 1
