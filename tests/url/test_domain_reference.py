import hashlib

import pytest

from app.services.url import domain_reference as reference


def test_snapshot_identity_and_offline_manifest():
    manifest = reference.reference_manifest()
    assert manifest["version"] == "2026111600"
    assert manifest["sha256"] == "0e880d2f2a359fa5e404dac1551c4cf9d68dbc5acd62d7c697e956140119f1f6"
    assert manifest["entries"] == 1436
    assert manifest["source_url"] == "https://data.iana.org/TLD/tlds-alpha-by-domain.txt"
    assert manifest["runtime_network"] is False
    assert hashlib.sha256(reference.SNAPSHOT_PATH.read_bytes()).hexdigest() == manifest["sha256"]


@pytest.mark.parametrize("host", [
    "example.com", "EXAMPLE.ORG", "a.b.co.uk", "example.vn", "example.com.",
    "xn--bcher-kva.de", "xn--fa-hia.de", "example.xn--p1ai", "example.xn--fiqs8s",
])
def test_recognizes_qualified_ascii_hosts_and_real_idn_root_labels(host):
    assert reference.has_delegated_tld(host) is True


@pytest.mark.parametrize("host", [
    "QK.Tu", "P.Hiep", "Q.Tan", "vay.Tu", "9b.Moi.SSD", "example.onion",
    "example.example", "example.test", "example.invalid", "example.localhost",
    "xn--ti-jia.xn--chnh-wpa", "xn--vn-jla.xn--bn-l5s", "example.not-a-root-tld",
    "com", ".com", "example.com..", "a..com", "-bad.com", "bad-.com",
    "under_score.com", "example.com:443", "https://example.com", "user@example.com",
    "example.com/path", "bücher.de", "192.0.2.1", "2001:db8::1", "[2001:db8::1]",
    " example.com", "example.com\n", "a" * 64 + ".com", "",
])
def test_omits_ambiguous_suffixes_and_inputs_outside_the_host_contract(host):
    assert reference.has_delegated_tld(host) is False


def test_reference_does_not_claim_registrability_or_reputation():
    # IANA suffix membership intentionally does not impose PSL depth or check
    # registration: both these names have the real terminal label "uk".
    assert reference.has_delegated_tld("co.uk") is True
    assert reference.has_delegated_tld("an-unverified-name.co.uk") is True
    assert reference.reference_manifest()["role"] == "bare_domain_extraction_cue_only"


def test_modified_bytes_fail_the_pin_instead_of_changing_policy():
    payload = reference.SNAPSHOT_PATH.read_bytes()
    with pytest.raises(RuntimeError, match="checksum"):
        reference._parse_snapshot(payload + b"FAKEROOT\n")


@pytest.mark.parametrize(("body", "error"), [
    (b"# Version 1999010100, Last Updated unknown\nCOM\nORG\n", "header"),
    ((reference.SNAPSHOT_HEADER + "\nCOM\nCOM\n").encode(), "entries"),
    ((reference.SNAPSHOT_HEADER + "\nORG\nCOM\n").encode(), "entries"),
    ((reference.SNAPSHOT_HEADER + "\nCOM\nNOT_A_TLD\n").encode(), "entries"),
    ((reference.SNAPSHOT_HEADER + "\nCOM\norg\n").encode(), "entries"),
    ((reference.SNAPSHOT_HEADER + "\nCOM\n").encode(), "entries"),
    ((reference.SNAPSHOT_HEADER + "\nCOM\n").encode() + b"\xff\n", "ASCII"),
])
def test_updated_pin_still_requires_valid_header_and_entry_format(monkeypatch, body, error):
    # Updating a checksum alone must not bypass the structural checks required
    # when a maintainer intentionally replaces the pinned resource.
    monkeypatch.setattr(reference, "SNAPSHOT_SHA256", hashlib.sha256(body).hexdigest())
    monkeypatch.setattr(reference, "SNAPSHOT_ENTRIES", 2)
    with pytest.raises(RuntimeError, match=error):
        reference._parse_snapshot(body)


def test_missing_snapshot_fails_closed(monkeypatch, tmp_path):
    reference._delegated_tlds.cache_clear()
    monkeypatch.setattr(reference, "SNAPSHOT_PATH", tmp_path / "missing.txt")
    try:
        with pytest.raises(RuntimeError, match="unavailable"):
            reference.has_delegated_tld("example.org")
    finally:
        reference._delegated_tlds.cache_clear()


def test_successful_snapshot_is_cached_until_restart_or_explicit_clear(monkeypatch, tmp_path):
    snapshot = tmp_path / "iana_tlds.txt"
    snapshot.write_bytes(reference.SNAPSHOT_PATH.read_bytes())
    reference._delegated_tlds.cache_clear()
    monkeypatch.setattr(reference, "SNAPSHOT_PATH", snapshot)
    try:
        assert reference.has_delegated_tld("example.org") is True
        snapshot.unlink()
        assert reference.has_delegated_tld("example.vn") is True
        reference._delegated_tlds.cache_clear()
        with pytest.raises(RuntimeError, match="unavailable"):
            reference.reference_manifest()
    finally:
        reference._delegated_tlds.cache_clear()
