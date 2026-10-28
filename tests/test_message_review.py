import asyncio
import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from evaluation.message_data import (annotation_sheet, clean_message, group_candidates, read_jsonl,
                                      sha, spreadsheet_cell, write_json, write_jsonl)
from evaluation.review import (ReviewPending, assert_split_isolation, finalize, load_reviews,
                                prepare_adjudication, validate_gold, workspace_items)


@pytest.fixture
def workspace(tmp_path):
    w = tmp_path / "review"
    w.mkdir()
    texts = ("Họp nhóm lúc 14 giờ.", "Gửi mật khẩu cho tôi.", "Đọc OTP qua cuộc gọi.",
             "Bạn tự mở ứng dụng đã cài.", "Kiểm tra ngay giúp tôi.")
    items = [{"id": str(i), "text": text, "split": "dev" if i < 2 else "test", "source_ids": [str(i)],
              "group_id": "group-" + str(i), "domains": [], "urls": [], "source_dates": []}
             for i, text in enumerate(texts)]
    write_jsonl(w / "items.jsonl", items)
    write_jsonl(w / "source_labels.jsonl", [{"id": i["id"], "source_label": 1} for i in items])
    write_json(w / "audit.json", {"selected": len(items)})
    write_json(w / "manifest.json", {"source_labels_are_gold": False, "source_url": "https://example.org/dataset",
        "source_revision": "fixture", "source_license": "CC-BY-4.0", "grouping": "fixture groups",
        "files": {name: sha(w / name) for name in ("items.jsonl", "source_labels.jsonl", "audit.json")}})
    for side in ("a", "b"):
        annotation_sheet(w / f"annotator_{side}.csv", items)
    return w


def fill(path, identity, change=None):
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields, rows = reader.fieldnames, list(reader)
    for r in rows:
        r.update(label="1" if r["id"] in {"1", "2"} else "UNKNOWN" if r["id"] == "4" else "0",
                 category="credential_theft" if r["id"] in {"1", "2"} else "insufficient_context" if r["id"] == "4" else "routine",
                 evidence_quote="mật khẩu" if r["id"] == "1" else "OTP" if r["id"] == "2" else "",
                 notes="Review fixture rationale; not real human annotations.", rater_id=identity)
        if change:
            change(r)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader();writer.writerows(rows)


def test_pending_review_blocks_gold_and_does_not_create_outputs(workspace, tmp_path):
    with pytest.raises(ReviewPending, match="chưa hoàn tất"):
        finalize(workspace, tmp_path / "gold")
    assert not (tmp_path / "gold").exists()


def test_consensus_freezes_actual_reviews_not_upstream_labels_and_preserves_unknown(workspace, tmp_path):
    fill(workspace / "annotator_a.csv", "fixture-a")
    fill(workspace / "annotator_b.csv", "fixture-b")
    out = tmp_path / "gold"
    m = finalize(workspace, out)
    assert m["counts"] == {"dev": {"0": 1, "1": 1}, "test": {"1": 1, "0": 1, "UNKNOWN": 1}}
    assert read_jsonl(out / "dev.jsonl")[0]["label"] == 0  # Upstream fixture labels are all 1.
    assert read_jsonl(out / "test_unknown.jsonl")[0]["label"] is None
    assert validate_gold(out / "manifest.json", out / "test.jsonl")["status"] == "reviewed_frozen"
    with pytest.raises(ValueError, match="already exists"):
        finalize(workspace, out)
    data = (out / "test.jsonl").read_text()
    (out / "test.jsonl").write_text(data + "\n")
    with pytest.raises(ValueError, match="modified"):
        validate_gold(out / "manifest.json", out / "test.jsonl")


def test_one_identity_cannot_count_as_two_raters(workspace):
    for side in ("a", "b"):
        fill(workspace / f"annotator_{side}.csv", "same-fixture-rater")
    with pytest.raises(ValueError, match="distinct"):
        load_reviews(workspace)


def test_label_disagreement_needs_third_review_and_does_not_get_auto_resolved(workspace, tmp_path):
    fill(workspace / "annotator_a.csv", "fixture-a")
    fill(workspace / "annotator_b.csv", "fixture-b", lambda r: r.update(label="0") if r["id"] == "2" else None)
    status = prepare_adjudication(workspace)
    assert status["label_disagreements"] == 1 and status["label_agreements"] == 4
    with pytest.raises(ReviewPending):
        finalize(workspace, tmp_path / "gold")
    fill(workspace / "adjudication.csv", "fixture-a")
    with pytest.raises(ValueError, match="third"):
        finalize(workspace, tmp_path / "gold")
    fill(workspace / "adjudication.csv", "fixture-third")
    finalize(workspace, tmp_path / "gold")
    row = read_jsonl(tmp_path / "gold/test.jsonl")[0]
    assert row["label"] == 1 and row["annotation_status"] == "adjudicated"
    assert row["rater_ids"] == ["fixture-a", "fixture-b", "fixture-third"]


def test_fake_evidence_quote_and_changed_message_are_rejected(workspace):
    fill(workspace / "annotator_a.csv", "fixture-a", lambda r: r.update(evidence_quote="invented") if r["id"] == "1" else None)
    with pytest.raises(ValueError, match="quote"):
        load_reviews(workspace)
    fill(workspace / "annotator_a.csv", "fixture-a", lambda r: r.update(text="Edited input") if r["id"] == "0" else None)
    with pytest.raises(ValueError, match="edit message"):
        load_reviews(workspace)


def test_domains_and_groups_cannot_cross_review_splits():
    items = [{"id": "a", "text": "One", "split": "dev", "domains": ["example.org"], "group_id": "a"},
             {"id": "b", "text": "Two", "split": "test", "domains": ["example.org"], "group_id": "b"}]
    with pytest.raises(ValueError, match="domains"):
        assert_split_isolation(items)
    items[1].update(domains=[], group_id="a")
    with pytest.raises(ValueError, match="group_id"):
        assert_split_isolation(items)


def test_campaign_grouping_joins_subdomains_and_variable_templates():
    items = [{"id": "a", "text": "Lịch họp tuần mới xem tài liệu", "urls": ["https://a.example.org/schedule"]},
             {"id": "b", "text": "Đóng phí hoàn hàng vào tài khoản này", "urls": ["https://b.example.org/fee"]},
             {"id": "c", "text": "Giao dịch số 123456 xác nhận trong ứng dụng", "urls": []},
             {"id": "d", "text": "Giao dịch số 987654 xác nhận trong ứng dụng", "urls": []}]
    info = group_candidates(items)
    assert info["groups"] == 2
    assert items[0]["group_id"] == items[1]["group_id"]
    assert items[2]["group_id"] == items[3]["group_id"]


def test_additional_source_redaction_and_spreadsheet_export():
    text, fields = clean_message("Ma OTP xac thuc GD la 066595; liên hệ user@example.org")
    assert "066595" not in text and "user@" not in text and fields
    assert spreadsheet_cell("=IMPORTXML(\"https://example.org\")").startswith("'=")
    assert spreadsheet_cell("Tin nhắn") == "Tin nhắn"


def test_unreviewed_v2_evaluation_is_blocked_before_model_load_or_paid_calls(monkeypatch, tmp_path):
    import evaluation.ablation as module
    monkeypatch.setattr(module, "ModelService", lambda *_: pytest.fail("Must fail before model loading"))
    args = SimpleNamespace(dataset=tmp_path / "not-reviewed.jsonl", prompt_profile="message-v2", fusion_policy="separate")
    with pytest.raises(ValueError, match="reviewed-manifest"):
        asyncio.run(module.evaluate(args))


def test_delivered_selection_has_200_unique_group_isolated_items_without_gold_labels():
    workspace = Path(__file__).resolve().parents[1] / "data/annotation/vn_sms_v2"
    items, manifest = workspace_items(workspace)
    assert len(items) == 200
    assert sum(i["split"] == "dev" for i in items) == 80
    assert sum(i["split"] == "test" for i in items) == 120
    assert sum(bool(i["urls"]) for i in items) == 103
    assert all("label" not in i and "source_label" not in i for i in items)
    assert manifest["status"] == "awaiting_two_independent_raters"
    assert_split_isolation(items)
