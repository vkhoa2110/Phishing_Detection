"""Experimental exact-URL reputation routing, with no network or model writes.

Evidence is separate from predictions. A lookup never establishes the safety
of a message, follows redirects, or inherits trust across paths/subdomains.
This component is not enabled in the production analysis pipeline.
"""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import ipaddress
import re
from urllib.parse import urlsplit, urlunsplit


VERSION = "exact-url-reputation-1.0"


def utc(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if not isinstance(parsed, datetime) or parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Evidence timestamps must include a timezone.")
    return parsed.astimezone(timezone.utc)


def canonical_url(value):
    """Conservative local key; preserve scheme, path, query and percent encoding.

    Bare URLs use a distinct scheme-less namespace, not an assumed HTTP/HTTPS
    alias. Preserve fragments too: browser applications may interpret them.
    Missing paths become '/'; no substring, wildcard or parent-domain matching.
    """
    if (not isinstance(value, str) or not value or len(value) > 4096 or "\\" in value
            or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError("Invalid reputation URL.")
    explicit_scheme = "://" in value
    parsed = urlsplit(value if explicit_scheme else "//" + value)
    if (parsed.scheme not in {"", "http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None):
        raise ValueError("Unsupported URL scheme/authority.")
    host = parsed.hostname.encode("idna").decode("ascii").lower().removesuffix(".")
    try:
        address = ipaddress.ip_address(host)
        host = "[" + address.compressed + "]" if address.version == 6 else address.compressed
    except ValueError:
        if len(host) > 253 or not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                                     for label in host.split(".")):
            raise ValueError("Invalid hostname.")
    port = parsed.port
    if port is not None and port not in ({80} if parsed.scheme == "http" else {443} if parsed.scheme == "https" else set()):
        host += ":" + str(port)
    return urlunsplit((parsed.scheme, host, parsed.path or "/", parsed.query, parsed.fragment))


@dataclass(frozen=True)
class Evidence:
    id: str
    url: str
    verdict: str
    source: str
    source_id: str
    source_url: str
    source_tier: str
    evidence_kind: str
    observed_at: str
    expires_at: str

    def __post_init__(self):
        if any(not isinstance(v, str) or not v.strip() for v in asdict(self).values()):
            raise ValueError("Evidence fields must be nonempty strings.")
        expected = {"trusted": "source_registry", "malicious": "source_threat_list"}
        if self.verdict not in expected or self.evidence_kind != expected[self.verdict]:
            raise ValueError("Only source evidence may establish reputation; predictions/popularity cannot.")
        canonical_url(self.url)
        if utc(self.expires_at) <= utc(self.observed_at):
            raise ValueError("Evidence expiry must follow its observation.")


class ReputationStore:
    def __init__(self, records):
        self._index = {}
        seen = set()
        for record in records:
            item = record if isinstance(record, Evidence) else Evidence(**record)
            if item.id in seen:
                raise ValueError("Duplicate evidence ID.")
            seen.add(item.id)
            self._index.setdefault(canonical_url(item.url), []).append(item)
        self.size = len(seen)

    def lookup(self, url, *, as_of):
        now = utc(as_of)
        result = {"state": "miss", "verdict": "unknown", "risk_level": "UNKNOWN", "evidence": []}
        try:
            key = canonical_url(url)
        except (ValueError, UnicodeError):
            return {**result, "state": "invalid_url"}
        matches = self._index.get(key, [])
        active = [r for r in matches if utc(r.observed_at) <= now < utc(r.expires_at)]
        if not active:
            if matches:
                result["state"] = "expired" if any(utc(r.observed_at) <= now for r in matches) else "not_yet_valid"
            return result
        result["evidence"] = [asdict(r) for r in sorted(active, key=lambda r: r.id)]
        if len({r.verdict for r in active}) != 1:
            return {**result, "state": "conflict"}
        verdict = active[0].verdict
        return {**result, "state": "known", "verdict": verdict,
                "risk_level": "HIGH" if verdict == "malicious" else "LOW"}


def route_urls(urls, store, predict, *, as_of):
    """Call the supplied URL model only on unresolved inputs; keep input order.

    Invalid, expired, conflicting or missing evidence all fall back to ML.
    The caller must still analyze message behavior independently.
    """
    lookups = [store.lookup(url, as_of=as_of) for url in urls]
    unresolved = [i for i, lookup in enumerate(lookups) if lookup["state"] != "known"]
    outputs = list(predict([urls[i] for i in unresolved])) if unresolved else []
    if len(outputs) != len(unresolved):
        raise ValueError("URL model returned a different number of records.")
    fallback = {}
    for i, output in zip(unresolved, outputs):
        if output.get("url") != urls[i]:
            raise ValueError("URL model output order/URL mismatch.")
        if output.get("status") == "ok" and output.get("risk_level") not in {"HIGH", "WARNING", "LOW"}:
            raise ValueError("Invalid model risk level.")
        fallback[i] = output
    rows = []
    for i, (url, lookup) in enumerate(zip(urls, lookups)):
        called = i in fallback
        model = fallback.get(i)
        risk = (model["risk_level"] if model.get("status") == "ok" else "UNKNOWN") if called else lookup["risk_level"]
        rows.append({"url": url, "reputation": lookup, "model_called": called,
                     "decision_source": "url_model" if called else "reputation",
                     "risk_level": risk, "model": model})
    return rows
