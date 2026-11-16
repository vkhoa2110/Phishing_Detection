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


FIELDS = ("id", "score", "risk_level", "warning_threshold", "high_threshold")


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
