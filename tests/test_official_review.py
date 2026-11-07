import json

import pytest

from scripts.data import render_official_review as review


def record():
    return {"id": "reference-1", "url": "https://official.edu/login", "publisher": "Official University", "region": "international", "tags": ["login"],
            "label": 1, "risk_score": .99, "model": "secret-model-arm", "source_risk_label": "private-silver-label",
            "evidence": {"source_url": "https://official.edu/guide", "final_url": "https://official.edu/guide", "retrieved_at": "2026-11-07T12:00:00Z",
                         "route_publication": {"relation": "published_link", "href": "https://official.edu/login", "title": "</script><script>window.injected=true</script>", "anchor": "Sign in", "model": "secret-model-arm"}}}


def test_blind_projection_omits_predictions_and_reference_risk_labels():
    result = review.blind_records([record()])[0]
    assert result["separate_source"] is True
    assert not {"label", "risk_score", "model", "source_risk_label"}.intersection(result)
    assert "secret-model-arm" not in json.dumps(result)
    assert "private-silver-label" not in json.dumps(result)


def test_render_verifies_before_reading_and_escapes_embedded_evidence(tmp_path, monkeypatch):
    records = tmp_path / "records"
    records.mkdir()
    (records / "records.jsonl").write_text(json.dumps(record()) + "\n")
    verified = []
    monkeypatch.setattr(review, "verify", lambda path: verified.append(path) or {"verified": True})
    out = tmp_path / "review" / "index.html"
    result = review.render_review(records, out)
    html = out.read_text()
    assert verified == [records]
    assert result["records"] == 1 and result["API_calls"] == result["external_requests"] == 0
    assert "</script><script>window.injected" not in html
    assert "\\u003c/script\\u003e" in html
    assert "secret-model-arm" not in html and "private-silver-label" not in html
    assert "connect-src 'none'" in html
    with pytest.raises(ValueError, match="never overwrite"):
        review.render_review(records, out)


def test_bad_locked_reference_prevents_output(tmp_path, monkeypatch):
    def invalid(_):
        raise ValueError("Reference hash mismatch")
    monkeypatch.setattr(review, "verify", invalid)
    out = tmp_path / "review.html"
    with pytest.raises(ValueError, match="hash mismatch"):
        review.render_review(tmp_path / "missing-records", out)
    assert not out.exists()
