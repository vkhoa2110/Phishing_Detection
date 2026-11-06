from datetime import datetime, timezone

import pytest

from app.url_reputation import Evidence, ReputationStore, canonical_url, route_urls


NOW = "2026-07-17T00:00:00+00:00"


def record(**values):
    return {"id": "registry-1", "url": "https://bank.example/", "verdict": "trusted",
            "source": "test_registry", "source_id": "source-1", "source_url": "https://source.example/",
            "source_tier": "gold", "evidence_kind": "source_registry",
            "observed_at": "2026-07-16T00:00:00+00:00", "expires_at": "2026-07-18T00:00:00+00:00", **values}


def fake_model(seen, *, status="ok"):
    def predict(urls):
        seen.extend(urls)
        return [{"url": u, "status": status, "risk_level": "WARNING"} for u in urls]
    return predict


def test_exact_matching_does_not_trust_lookalikes_subdomains_paths_or_redirect_queries():
    store = ReputationStore([record()])
    assert store.lookup("https://BANK.example:443/", as_of=NOW)["state"] == "known"
    for url in ["https://bank.example.evil.test/", "https://login.bank.example/", "https://bank.example/login",
                "https://bank.example/?redirect=https://evil.test", "http://bank.example/",
                "bank.example", "https://bank.example/#/login", "https://bank.example:8443/",
                "https://bank.example@evil.test/", "https://evil.test/?next=https://bank.example/"]:
        assert store.lookup(url, as_of=NOW)["verdict"] == "unknown", url


def test_keys_preserve_query_order_case_and_percent_encoding_and_schemeless_namespace():
    assert canonical_url("HTTPS://BANK.example:443") == "https://bank.example/"
    assert canonical_url("bank.example") == "//bank.example/"
    keys = ["https://a.example/A", "https://a.example/a", "https://a.example/%61",
            "https://a.example/?a=1&b=2", "https://a.example/?b=2&a=1"]
    assert len({canonical_url(u) for u in keys}) == len(keys)
    assert canonical_url("https://bücher.example/") == "https://xn--bcher-kva.example/"


@pytest.mark.parametrize("url", ["https://bank.example\\@evil.test", "https://bank.example/\n",
                                 "https://user:pass@bank.example", "file:///etc/passwd",
                                 "https://bank.example:99999", "https://bank.example.."])
def test_ambiguous_or_invalid_authorities_never_hit(url):
    assert ReputationStore([record()]).lookup(url, as_of=NOW)["state"] == "invalid_url"


def test_evidence_validity_includes_start_but_excludes_expiry_and_future():
    store = ReputationStore([record()])
    url = "https://bank.example/"
    assert store.lookup(url, as_of="2026-07-16T00:00:00Z")["state"] == "known"
    assert store.lookup(url, as_of="2026-07-18T00:00:00Z")["state"] == "expired"
    assert store.lookup(url, as_of="2026-07-15T00:00:00Z")["state"] == "not_yet_valid"
    with pytest.raises(ValueError, match="timezone"):
        store.lookup(url, as_of=datetime(2026, 7, 17))


def test_conflicts_fall_back_and_expired_conflicting_record_does_not_override_active_evidence():
    bad = record(id="threat-1", verdict="malicious", evidence_kind="source_threat_list")
    store = ReputationStore([record(), bad])
    seen = []
    result = route_urls([bad["url"]], store, fake_model(seen), as_of=NOW)[0]
    assert result["reputation"]["state"] == "conflict"
    assert result["model_called"] and seen == [bad["url"]]
    bad["expires_at"] = "2026-07-16T12:00:00Z"
    assert ReputationStore([record(), bad]).lookup(bad["url"], as_of=NOW)["verdict"] == "trusted"


def test_routing_skips_only_active_known_urls_and_preserves_order_and_duplicates():
    malicious = record(id="threat-1", url="https://bad.example/", verdict="malicious", evidence_kind="source_threat_list")
    expired = record(id="old-1", url="https://old.example/", expires_at="2026-07-16T12:00:00Z")
    store = ReputationStore([record(), malicious, expired])
    urls = [malicious["url"], expired["url"], record()["url"], "https://new.example/", malicious["url"]]
    seen = []
    result = route_urls(urls, store, fake_model(seen), as_of=NOW)
    assert seen == [expired["url"], "https://new.example/"]
    assert [r["url"] for r in result] == urls
    assert [r["risk_level"] for r in result] == ["HIGH", "WARNING", "LOW", "WARNING", "HIGH"]
    assert [r["model_called"] for r in result] == [False, True, False, True, False]
    assert store.size == 3  # no write-back from model predictions


def test_all_known_inputs_do_not_even_call_model():
    def forbidden(urls):
        raise AssertionError("Model must not be called")
    result = route_urls([record()["url"]], ReputationStore([record()]), forbidden, as_of=NOW)
    assert result[0]["decision_source"] == "reputation" and result[0]["model"] is None


def test_model_failure_stays_unknown_and_wrong_joins_are_rejected():
    store = ReputationStore([])
    result = route_urls(["https://a.example"], store, fake_model([], status="unavailable"), as_of=NOW)
    assert result[0]["risk_level"] == "UNKNOWN"
    with pytest.raises(ValueError, match="number"):
        route_urls(["https://a.example"], store, lambda _: [], as_of=NOW)
    with pytest.raises(ValueError, match="mismatch"):
        route_urls(["https://a.example"], store, lambda _: [{"url": "https://other.example"}], as_of=NOW)


def test_prediction_or_popularity_cannot_be_promoted_to_trusted_and_evidence_requires_valid_dates():
    for kind in ["model_prediction", "popularity", "llm_opinion"]:
        with pytest.raises(ValueError, match="source evidence"):
            Evidence(**record(evidence_kind=kind))
    with pytest.raises(ValueError, match="expiry"):
        Evidence(**record(expires_at=record()["observed_at"]))
    with pytest.raises(ValueError, match="timezone"):
        Evidence(**record(observed_at="2026-07-16T00:00:00"))
    with pytest.raises(ValueError, match="Duplicate"):
        ReputationStore([record(), record()])
