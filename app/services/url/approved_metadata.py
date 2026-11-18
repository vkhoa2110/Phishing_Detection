"""Attach existing local URL scores only to URLs in the approved text.

This is an identity check, not URL intake: it never restores defanged dots,
removes hidden characters, changes a path or opens a destination.  The only
equivalences are scheme case and the shared HTTP authority/IDNA policy.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping

from app.services.url.authority import inspect_authority
from app.services.url.domain_reference import has_delegated_tld
from app.services.url.parsing import URL_PATTERN, extract_urls, trim_url, valid_url


FIELDS = ("id", "score", "risk_level", "warning_threshold", "high_threshold")


def _literal_visible_candidates(text: str) -> list[str]:
    candidates = []
    for match in URL_PATTERN.finditer(text):
        value = trim_url(match.group())
        start, end = match.start(), match.start() + len(value)
        neighbors = text[start - 1:start] + text[end:end + 1]
        # A bare ASCII regex match can be only a prefix of a hidden/Unicode
        # authority. Do not turn local normalization into metadata approval.
        if any(unicodedata.category(c) == "Cf" or unicodedata.category(c).startswith("M") or c.isalnum() or c == "_"
               for c in neighbors):
            continue
        if value not in candidates:
            candidates.append(value)
    return candidates


def approved_visible_urls(text: str) -> list[str]:
    """Keep literal matching while dotted prose cannot consume the URL limit.

    The normal strict extractor remains the source of visible spellings. Only
    its legacy five-candidate overflow needs the bare-domain policy; this is
    not the recovery intake and never restores an obfuscated URL.
    """
    literal = _literal_visible_candidates(text)
    try:
        visible = extract_urls(text, "text")[0]
        return [value for value in visible if value in literal]
    except ValueError:
        countable = []
        for value in literal:
            identity = _identity(value)
            if (re.match(r"(?i)^(?:https?://|www\.)", value)
                    or identity is not None and has_delegated_tld(identity[1])):
                countable.append(value)
        if len(countable) > 5:
            raise ValueError("More than five URL candidates remain after bare-domain filtering.")
        return [value for value in countable if valid_url(value)]


def _identity(value: str) -> tuple[str | None, str, str, str] | None:
    """Keep scheme presence, port spelling and everything after authority exact."""
    if not isinstance(value, str):
        return None
    try:
        parsed, host = inspect_authority(value)
        scheme_end = value.find("://")
        start = scheme_end + 3 if scheme_end >= 0 else 0
        boundary = re.search(r"[/?#]", value[start:])
        end = start + boundary.start() if boundary else len(value)
        authority = value[start:end]
        # UTS46 can discard formatting characters and fold width/composition.
        # These transformations belong to local intake/review, not metadata
        # approval. Ordinary already-normalized Unicode IDNA remains eligible.
        if (unicodedata.normalize("NFKC", authority) != authority
                or any(unicodedata.category(character) == "Cf" for character in authority)):
            return None
        if authority.startswith("["):
            port = authority[authority.index("]") + 1:]
        else:
            port = ":" + authority.rsplit(":", 1)[1] if ":" in authority else ""
        return (parsed.scheme if scheme_end >= 0 else None, host, port, value[end:])
    except (UnicodeError, ValueError):
        return None


def select_approved_metadata(
    visible_urls: Iterable[str],
    scored_urls: Iterable[Mapping],
    *,
    redact_url: Callable[[str], tuple[str, list[str]]],
) -> list[dict]:
    """Match approved spellings without disclosing an original private URL.

    Two distinct originals can collapse to one URL after query/PII redaction.
    Such groups, and duplicate scores that disagree, are omitted rather than
    attributing an uncertain local score to a visible URL.
    """
    visible = {}
    for url in visible_urls:
        key = _identity(url)
        if key is not None:
            visible.setdefault(key, url)

    groups = defaultdict(list)
    for row in scored_urls:
        if row.get("status") != "ok" or any(field not in row for field in FIELDS):
            continue
        original = row.get("url")
        original_key = _identity(original)
        if original_key is None:
            continue
        redacted = redact_url(original)[0]
        key = _identity(redacted)
        if key in visible:
            groups[key].append((original_key, {field: row[field] for field in FIELDS}))

    result = []
    for key, records in groups.items():
        original_key, metadata = records[0]
        if any(other_key != original_key or other_metadata != metadata
               for other_key, other_metadata in records[1:]):
            continue
        result.append({"id": metadata["id"], "url": visible[key],
                       **{field: metadata[field] for field in FIELDS if field != "id"}})
    return result
