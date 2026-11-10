import csv
import json
import pytest

import evaluation.rag.summary_audit as audit
from evaluation.rag.summary_audit import FIELDS, validate


def test_summary_audit_creates_blank_review_without_promoting_labels(tmp_path, monkeypatch):
    # Raw publisher snapshots are intentionally not versioned. The audit must
    # remain usable on a fresh checkout and report their absence honestly.
    monkeypatch.setattr(audit, "RAW_DIRS", [tmp_path / "no-raw-sources"])
    out = tmp_path / "audit"
    protocol = audit.prepare(out)
    assert protocol["documents"] == 37 and protocol["claims"] > 37
    assert protocol["raw_source_available"] == 0
    rows = list(csv.DictReader((out / "claims.csv").open()))
    assert list(rows[0]) == FIELDS
    assert all(not row["judgment"] and not row["reviewer_id"] and not row["source_excerpt"] for row in rows)
    result = validate(out / "claims.csv")
    assert result["completed"] == 0 and result["human_review_complete"] is False


def write_rows(path, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader(); writer.writerows(rows)


@pytest.mark.parametrize("failure", ["unknown", "missing", "duplicate", "claim_changed", "bad_date", "fake_excerpt"])
def test_review_cannot_complete_from_unrelated_or_fabricated_rows(tmp_path, monkeypatch, failure):
    monkeypatch.setattr(audit, "RAW_DIRS", [tmp_path / "missing"])
    out = tmp_path / "audit"
    audit.prepare(out)
    path = out / "claims.csv"
    rows = list(csv.DictReader(path.open()))
    if failure == "unknown":
        rows = [{**rows[0], "claim_id": "NOT-A-CORPUS-CLAIM", "document_id": "MISSING"}]
    elif failure == "missing":
        rows.pop()
    elif failure == "duplicate":
        rows[-1] = rows[0]
    elif failure == "claim_changed":
        rows[0]["summary_claim"] = "Tampered claim."
    else:
        rows[0].update(judgment="source_unavailable", reviewer_id="reviewer-a",
                       reviewed_at="2026-11-09T12:00:00+07:00", notes="Snapshot missing.")
        if failure == "bad_date":
            rows[0]["reviewed_at"] = "not-a-date"
        else:
            rows[0].update(judgment="supported", source_excerpt="Fabricated source quotation.")
    write_rows(path, rows)
    with pytest.raises(ValueError):
        validate(path)


def test_review_checks_excerpt_membership_and_snapshot_hash(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    raw.mkdir()
    source = raw / "VN-RAG-001.txt"
    source.write_text("Không cung cấp mã OTP cho người gọi.\nHãy tự xác minh.")
    doc = {"id": "VN-RAG-001", "source_url": "https://example.org/source",
           "text": "Không cung cấp mã OTP cho người gọi.", "source_text_sha256": audit.source_text_sha(source)}
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    corpus = tmp_path / "documents.jsonl"
    corpus.write_text(json.dumps(doc) + "\n")
    monkeypatch.setattr(audit, "CORPUS", corpus)
    monkeypatch.setattr(audit, "RAW_DIRS", [raw])
    monkeypatch.setattr(audit, "documents", lambda: [doc])
    out = tmp_path / "audit"
    audit.prepare(out)
    path = out / "claims.csv"
    rows = list(csv.DictReader(path.open()))
    rows[0].update(judgment="supported", reviewer_id="reviewer-a", reviewed_at="2026-11-09T12:00:00Z",
                   source_excerpt="Không cung cấp mã OTP cho người gọi.")
    write_rows(path, rows)
    assert validate(path)["source_evidence_complete"] is True
    rows[0]["source_excerpt"] = "A fabricated quotation."
    write_rows(path, rows)
    with pytest.raises(ValueError, match="Excerpt"):
        validate(path)
    rows[0]["source_excerpt"] = doc["text"]
    write_rows(path, rows)
    source.write_text("Changed publisher snapshot.")
    with pytest.raises(ValueError, match="snapshot"):
        validate(path)
