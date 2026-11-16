"""Approved URL metadata must retain both privacy and score provenance."""
from copy import deepcopy
import json

import pytest

from app.services.llm.client import LLMFailure, approved_ml_metadata


def scored(url, **overrides):
    return {"id": "URL-01", "url": url, "status": "ok", "score": .9,
            "risk_level": "HIGH", "warning_threshold": .2, "high_threshold": .8,
            **overrides}


@pytest.mark.parametrize("visible, original", [
    ("https://EXAMPLE.org/orders", "https://example.org/orders"),
    ("HTTPS://EXAMPLE.org/A?x=REDACTED#REDACTED", "https://example.org/A?x=private#private"),
    ("https://bücher.example/A", "https://xn--bcher-kva.example/A"),
    ("https://xn--bcher-kva.example/A", "https://bücher.example/A"),
    ("https://faß.de/A", "https://xn--fa-hia.de/A"),
    ("EXAMPLE.org/A", "example.org/A"),
    ("https://[2001:DB8::1]:443/A", "https://[2001:db8::1]:443/A"),
])
def test_authority_equivalence_preserves_the_approved_spelling_and_original_score(visible, original):
    row = scored(original)
    before = deepcopy(row)
    result = approved_ml_metadata("Kiểm tra " + visible, [row])
    assert len(result) == 1
    assert result[0] == {key: value for key, value in row.items() if key not in {"status", "url"}} | {"url": visible}
    assert row == before
    assert "private" not in json.dumps(result)


@pytest.mark.parametrize("visible", [
    "http://example.org/A?x=REDACTED#REDACTED",
    "example.org/A?x=REDACTED#REDACTED",
    "https://example.org:443/A?x=REDACTED#REDACTED",
    "https://example.org./A?x=REDACTED#REDACTED",
    "https://example.org/a?x=REDACTED#REDACTED",
    "https://example.org/%41?x=REDACTED#REDACTED",
    "https://example.org/A?y=REDACTED#REDACTED",
    "https://example.org/A?x=REDACTED",
    "https://example.org/A?x=REDACTED&y=REDACTED#REDACTED",
    "https://other.org/A?x=REDACTED#REDACTED",
    "https://example[.]org/A?x=REDACTED#REDACTED",
    "https://exam\u200bple.org/A?x=REDACTED#REDACTED",
])
def test_other_url_changes_cannot_reintroduce_an_existing_score(visible):
    assert approved_ml_metadata(visible, [scored("https://example.org/A?x=secret#private")]) == []


@pytest.mark.parametrize("visible, original", [
    ("https://example.org:443/A", "https://example.org:0443/A"),
    ("https://fass.de/A", "https://faß.de/A"),
    ("https://example.org/A/", "https://example.org/A"),
    ("https://example.org", "https://example.org/"),
])
def test_ports_distinct_idna_hosts_and_paths_are_not_broadened(visible, original):
    assert approved_ml_metadata(visible, [scored(original)]) == []


def test_deleted_or_replaced_url_is_not_sent_and_failed_rows_are_ignored():
    rows = [scored("https://private.example/A"), scored("https://example.org/A", status="error")]
    assert approved_ml_metadata("Không gửi đường dẫn", rows) == []
    assert approved_ml_metadata("https://other.example/A", rows) == []
    assert approved_ml_metadata("https://example.org/A", rows) == []


def test_redaction_collisions_cannot_attach_scores_for_different_original_urls():
    rows = [scored("https://example.org/?token=secret-a"),
            scored("https://example.org/?token=secret-b", id="URL-02", score=.1, risk_level="LOW")]
    assert approved_ml_metadata("https://EXAMPLE.org/?token=REDACTED", rows) == []


def test_an_exact_duplicate_is_deduplicated_but_conflicting_metadata_is_omitted():
    row = scored("https://example.org/A")
    assert len(approved_ml_metadata("https://EXAMPLE.org/A", [row, deepcopy(row)])) == 1
    assert approved_ml_metadata("https://EXAMPLE.org/A", [row, {**row, "score": .1}]) == []


def test_userinfo_and_hidden_authority_are_not_recovered_for_metadata():
    for url in ["https://user:private@example.org/A", "https://exam\u200bple.org/A"]:
        assert approved_ml_metadata("https://example.org/A", [scored(url)]) == []


@pytest.mark.parametrize("visible, original", [
    ("https://ｅxample.org/path", "https://example.org/path"),
    ("https://example.org/path", "https://ｅxample.org/path"),
    ("https://bu\u0308cher.example/A", "https://xn--bcher-kva.example/A"),
    ("https://xn--bcher-kva.example/A", "https://bu\u0308cher.example/A"),
])
def test_authority_nfkc_recovery_stays_local_only(visible, original):
    assert approved_ml_metadata(visible, [scored(original)]) == []


def test_metadata_retains_model_order_and_only_the_existing_contract_fields():
    rows = [scored("https://one.example/A", raw_url="private-raw-field"),
            scored("https://two.example/A", id="URL-02")]
    result = approved_ml_metadata("https://TWO.example/A https://ONE.example/A", rows)
    assert [row["id"] for row in result] == ["URL-01", "URL-02"]
    assert all(set(row) == {"id", "url", "score", "risk_level", "warning_threshold", "high_threshold"}
               for row in result)


def test_more_than_five_visible_urls_still_rejects_the_request():
    with pytest.raises(LLMFailure, match="5 URL"):
        approved_ml_metadata(" ".join(f"https://site{i}.example/" for i in range(6)), [])
