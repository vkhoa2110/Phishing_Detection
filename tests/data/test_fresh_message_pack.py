from collections import Counter

import pytest

from evaluation.data.fresh_messages import authored, select


def item(identifier, group, label, url=False):
    return {"id": identifier, "group_id": group, "source_label": label,
            "text": "Tin nhắn minh họa " + identifier, "urls": ["https://example.org/"] if url else []}


def test_selection_blocks_entire_old_groups_and_never_samples_by_predictions():
    values = [item("old", "old-group", 0), item("new-but-related", "old-group", 1)]
    values += [item(f"sample-{label}-{i}", f"group-{label}-{i}", label, bool(i % 2))
               for label in (0, 1) for i in range(10)]
    selected, blocked = select(values, {"old"}, quota_per_label=5)
    assert len(selected) == len({row["group_id"] for row in selected}) == 10
    assert not {row["group_id"] for row in selected} & blocked
    assert Counter(row["source_label"] for row in selected) == {0: 5, 1: 5}
    assert Counter(row["split"] for row in selected) == {"development_review": 4, "reserve_review": 6}
    with pytest.raises(ValueError, match="Insufficient"):
        select(values, {"old"}, quota_per_label=11)


def test_authored_stress_keeps_design_labels_separate_and_urls_identical_per_family():
    rows, references = authored()
    assert len(rows) == len(references) == 40
    assert sum("injected" in row["id"] for row in rows) == 16
    assert all("risk_reference" not in row for row in rows)
    assert all(row["independent_gold"] is False and row["url_risk_reference"] is None for row in references)
    for family in {row["family"] for row in rows}:
        messages = [row["text"] for row in rows if row["family"] == family]
        assert len(messages) == 5 and len({text.rsplit("\n", 1)[-1] for text in messages}) == 1
