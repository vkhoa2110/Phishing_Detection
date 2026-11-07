from pathlib import Path

import pytest

from evaluation.openphish_candidates_v1 import LIMIT, candidate_rows, fetch_official, prepare


def test_offline_selection_excludes_history_deduplicates_domains_and_keeps_provisional():
    raw = b"https://old.test/a\nhttps://new.test/b\nhttps://new.test/a\nhttps://new.test/a#frag\nhttps://second.test/\nnot-a-url\n"
    rows, counts = candidate_rows(raw, {"domains": ["old.test"]}, "2026-11-07T10:00:00+00:00")
    assert len(rows) == 2
    assert {r["domain"] for r in rows} == {"new.test", "second.test"}
    assert counts["duplicate_normalized_urls"] == 1
    assert counts["historical_domain_urls"] == counts["invalid_urls"] == 1
    assert all(r["label_status"] == "external_source_provisional" and not r["prospective_eligible"] for r in rows)
    assert all(r["campaign"] is None and r["source_first_seen_at"] is None and not r["human_verified"] for r in rows)
    assert all("score" not in r and r["reviewer_ids"] == [] for r in rows)


def test_cap_and_selection_depend_only_on_hash_not_feed_order_or_model_score():
    lines = [f"https://new-{i}.test/path?q={i}" for i in range(250)]
    first, counts = candidate_rows("\n".join(lines).encode(), {"domains": []}, "2026-11-07T10:00:00Z")
    second, _ = candidate_rows("\n".join(reversed(lines)).encode(), {"domains": []}, "2026-11-07T10:00:00Z")
    assert len(first) == LIMIT == 200
    assert [r["url"] for r in first] == [r["url"] for r in second]
    assert counts["eligible_unique_domains"] == 250
    assert all(r["snapshot_line"] > 0 for r in first)


def test_private_suffix_isolation_and_campaign_remain_explicit_unknown():
    raw = b"https://old.github.io/a\nhttps://new.github.io/a\nhttps://new.github.io/b\n"
    rows, _ = candidate_rows(raw, {"domains": ["old.github.io"]}, "2026-11-07T10:00:00Z")
    assert len(rows) == 1 and rows[0]["domain"] == "new.github.io"
    assert "unknown_campaign" in rows[0]["eligibility_blockers"]


def test_suspect_url_cannot_be_fetched_and_existing_outputs_are_preserved(tmp_path):
    with pytest.raises(ValueError, match="Only the three official"):
        fetch_official("https://suspect.test/")
    out = tmp_path / "old"
    out.mkdir()
    with pytest.raises(ValueError, match="new output"):
        prepare(out, Path("unused"))


def test_mocked_fetch_only_official_endpoints_and_blind_fields_are_blank(tmp_path, monkeypatch):
    import csv
    import hashlib
    import json
    import evaluation.openphish_candidates_v1 as module
    monkeypatch.setattr(module, "check_lock", lambda _: {})
    monkeypatch.setattr(module, "verify", lambda _: None)
    (tmp_path / "protocol.json").write_text("{}")
    (tmp_path / "exclusions.json").write_text('{"domains":[]}')
    seen = []
    def mocked(url):
        seen.append(url)
        body = b"https://fixture.test/\n" if url == module.FEED else b"Official source fixture"
        return body, {"url": url, "retrieved_at": "2026-11-07T10:00:00Z", "sha256": hashlib.sha256(body).hexdigest()}
    monkeypatch.setattr(module, "fetch_official", mocked)
    result = module.fetch(tmp_path)
    assert seen == list(module.SOURCES.values())
    assert result["counts"]["selected"] == 1
    with (tmp_path / "blind_review.csv").open(encoding="utf-8-sig") as stream:
        row = next(csv.DictReader(stream))
    assert row["campaign"] == row["label"] == row["rationale"] == row["reviewer_id"] == ""
    assert json.loads((tmp_path / "summary.json").read_text())["listed_URL_requests"] == 0
    with pytest.raises(ValueError, match="already started"):
        module.fetch(tmp_path)
