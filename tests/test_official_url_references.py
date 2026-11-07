import hashlib
import json
from pathlib import Path

import pytest

from evaluation import official_url_references as references


def test_fetch_boundary_rejects_credentials_ports_and_other_hosts():
    hosts = ["github.com"]
    assert references.checked_url("https://github.com/login", hosts).endswith("/login")
    for value in ("http://github.com/login", "https://evil.test/login", "https://github.com@evil.test/", "https://user@github.com/login", "https://github.com:444/login"):
        with pytest.raises(ValueError):
            references.checked_url(value, hosts)


def test_publication_requires_exact_route_or_explicit_self_document():
    fetched = {"status": 200, "content_type": "text/html", "encoding": "utf-8", "url": "https://github.com/guide",
               "body": b'<title>Account support</title><a href="/password_reset">Reset password</a>'}
    row = {"url": "https://github.com/password_reset", "source_url": "https://github.com/guide"}
    publication = references.publication(row, fetched)
    assert publication["relation"] == "published_link"
    assert publication["href"] == row["url"]
    row["url"] = "https://github.com/login"
    with pytest.raises(ValueError, match="not linked"):
        references.publication(row, fetched)
    row["source_url"] = row["url"]
    assert references.publication(row, fetched)["relation"] == "self_served_document"


def test_overlap_separates_regression_without_promoting_unseen_origin():
    index = {"urls": ["https://github.com/login"], "domains": ["github.com"], "campaigns": []}
    assert references.overlap("https://github.com/new-route", index)["assigned_pool"] == "regression"
    unseen = references.overlap("https://stanford.edu/", index)
    assert unseen["assigned_pool"] == "new_origin_reference_review_only"
    assert unseen["prospective_eligible"] is False
    assert unseen["campaign_overlap"] is None


def plan():
    return {"version": references.VERSION, "label_policy": "official_origin_reference_not_benign_gold",
            "allowed_hosts": [f"official{i}.edu" for i in range(8)],
            "minimum_success_coverage": {"records": 24, "domains": 8, "tags": ["article"]},
            "selections": [{"id": f"ref{i}", "url": f"https://official{i % 8}.edu/article/{i}",
                            "source_url": f"https://official{i % 8}.edu/article/{i}",
                            "publisher": f"Official {i % 8}", "region": "international", "tags": ["article"]} for i in range(24)]}


def test_plan_rejects_score_dependent_fields_and_insufficient_diversity():
    candidate = plan()
    assert references.validate_selection(candidate) is candidate
    candidate["selections"][0]["score"] = .95
    with pytest.raises(ValueError, match="predictions"):
        references.validate_selection(candidate)
    candidate = plan()
    candidate["selections"] = candidate["selections"][:23]
    with pytest.raises(ValueError, match="24"):
        references.validate_selection(candidate)


def test_lock_collection_failure_is_preserved_and_no_risk_labels(tmp_path):
    registration = tmp_path / "registration.json"
    registration.write_text(json.dumps({"exclusion_index": {"urls": [], "domains": ["official0.edu"], "campaigns": []}}))
    out = tmp_path / "references"
    references.lock_selection(out, plan(), registration)
    raw = tmp_path / "raw.html"
    raw.write_bytes(b"<html><title>Official information</title></html>")
    digest = hashlib.sha256(raw.read_bytes()).hexdigest()

    class Fake:
        def fetch(self, url):
            if url.endswith("/0"):
                raise ValueError("Mock unavailable, retained rather than replaced")
            return {"status": 200, "url": url, "body": raw.read_bytes(), "encoding": "utf-8", "content_type": "text/html",
                    "retrieved_at": references.stamp(), "snapshot_path": str(raw), "snapshot_sha256": digest,
                    "redirect_chain": [{"url": url, "status": 200}], "robots": {"snapshot_path": str(raw), "snapshot_sha256": digest}}

    summary = references.collect(out, tmp_path / "unused", fetcher=Fake())
    assert (summary["selected"], summary["collected"], summary["failed"], summary["risk_labels"], summary["model_calls"]) == (24, 23, 1, 0, 0)
    assert summary["coverage_met"] is False
    assert references.verify(out) == {"verified": True, "records": 23, "attempts": 24, "API_calls": 0}
    rows = references.read_jsonl(out / "records.jsonl")
    assert all(r["label"] is None and r["reviewer_ids"] == [] for r in rows)
    assert "Mock unavailable" in (out / "attempts.jsonl").read_text()
    with pytest.raises(ValueError, match="already collected"):
        references.collect(out, tmp_path / "unused", fetcher=Fake())
    raw.write_text("altered evidence")
    with pytest.raises(ValueError, match="snapshot"):
        references.verify(out)


def test_plan_tamper_invalidates_hash(tmp_path):
    registration = tmp_path / "registration.json"
    registration.write_text(json.dumps({"exclusion_index": {"urls": [], "domains": [], "campaigns": []}}))
    out = tmp_path / "references"
    references.lock_selection(out, plan(), registration)
    with (out / "selection.json").open("a") as handle:
        handle.write(" ")
    with pytest.raises(ValueError, match="selection changed"):
        references.read_selection(out)
