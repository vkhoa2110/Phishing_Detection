"""Shared local authority validation; never resolves or fetches a URL."""
import ipaddress
from urllib.parse import urlsplit

import idna


IDNA_POLICY = "uts46-nontransitional-std3"


def ascii_host(host: str) -> str:
    """Preserve distinct IDNA2008 hosts, including sharp-s vs 'ss'."""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return idna.encode(host, uts46=True, transitional=False, std3_rules=True).decode("ascii").lower()
    return "[" + address.compressed + "]" if address.version == 6 else address.compressed


def inspect_authority(value: str):
    if (not value or len(value) > 4096 or "\\" in value
            or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError("Invalid or ambiguous URL spelling.")
    parsed = urlsplit(value if "://" in value else "http://" + value)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None):
        raise ValueError("Unsupported or ambiguous URL authority.")
    host = ascii_host(parsed.hostname)
    if "." not in host and ":" not in host:
        raise ValueError("A qualified hostname or IP address is required.")
    # Accessing port also rejects malformed / out-of-range values.
    _ = parsed.port
    return parsed, host
