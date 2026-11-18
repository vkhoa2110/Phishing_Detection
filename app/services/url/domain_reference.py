"""Pinned offline root-TLD cue for interpreting bare domains in prose.

Membership says only that a terminal label appears in this IANA snapshot. It
does not resolve the host, establish registrability, or assess reputation.
"""
from functools import lru_cache
import hashlib
import ipaddress
from pathlib import Path
import re


POLICY = "iana-root-tld-cue-1.0"
SOURCE_URL = "https://data.iana.org/TLD/tlds-alpha-by-domain.txt"
REGISTRY_URL = "https://www.iana.org/domains/root/db"
IANA_VERSION = "2026111600"
SNAPSHOT_SHA256 = "0e880d2f2a359fa5e404dac1551c4cf9d68dbc5acd62d7c697e956140119f1f6"
SNAPSHOT_HEADER = "# Version 2026111600, Last Updated Mon Nov 16 07:07:02 2026 UTC"
SNAPSHOT_ENTRIES = 1436
SNAPSHOT_PATH = Path(__file__).with_name("resources") / "iana_tlds.txt"
_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", re.ASCII)


def _parse_snapshot(payload: bytes) -> frozenset[str]:
    """Validate both the byte pin and the list format before caching it."""
    if hashlib.sha256(payload).hexdigest() != SNAPSHOT_SHA256:
        raise RuntimeError("Pinned IANA TLD reference checksum does not match.")
    try:
        lines = payload.decode("ascii").splitlines()
    except UnicodeDecodeError as exc:
        raise RuntimeError("Pinned IANA TLD reference must be ASCII.") from exc
    if not lines or lines[0] != SNAPSHOT_HEADER:
        raise RuntimeError("Pinned IANA TLD reference header does not match.")
    labels = lines[1:]
    if (len(labels) != SNAPSHOT_ENTRIES or labels != sorted(set(labels))
            or any(label != label.upper() or not _LABEL.fullmatch(label) for label in labels)):
        raise RuntimeError("Pinned IANA TLD reference entries are invalid.")
    return frozenset(label.lower() for label in labels)


@lru_cache(maxsize=1)
def _delegated_tlds() -> frozenset[str]:
    try:
        payload = SNAPSHOT_PATH.read_bytes()
    except OSError as exc:
        raise RuntimeError("Pinned IANA TLD reference is unavailable.") from exc
    return _parse_snapshot(payload)


def has_delegated_tld(ascii_host: str) -> bool:
    """Check a qualified, already IDNA-validated ASCII host against the pin.

    A single terminal root dot is accepted. Unicode hosts, IP addresses, URL
    strings, userinfo, ports, and single-label names are outside this contract.
    A false result can mean an undelegated, private, reserved, or newer suffix;
    it must not be interpreted as a phishing verdict.
    """
    if not isinstance(ascii_host, str) or not ascii_host.isascii():
        return False
    host = ascii_host[:-1] if ascii_host.endswith(".") else ascii_host
    if not host or len(host) > 253:
        return False
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return False
    labels = host.split(".")
    if len(labels) < 2 or any(not _LABEL.fullmatch(label) for label in labels):
        return False
    return labels[-1].lower() in _delegated_tlds()


def reference_manifest() -> dict:
    """Expose the checked resource identity without making network requests."""
    labels = _delegated_tlds()
    return {
        "policy": POLICY, "version": IANA_VERSION,
        "source_url": SOURCE_URL, "registry_url": REGISTRY_URL,
        "sha256": SNAPSHOT_SHA256, "header": SNAPSHOT_HEADER,
        "entries": len(labels),
        "resource": "app/services/url/resources/iana_tlds.txt",
        "runtime_network": False, "role": "bare_domain_extraction_cue_only",
    }
