"""Conservative URL intake for the opt-in v6 candidate.

The original text is never replaced.  A separate analysis view recognizes a
small, documented set of obfuscations and records every transformation.  The
result is suitable for local scoring only; it does not authenticate or open a
destination.
"""
from __future__ import annotations

import re
import unicodedata

from .urls import extract_urls, trim_url
from .url_authority import IDNA_POLICY, inspect_authority


VERSION = "url-intake-2.1"
ZERO_WIDTH = "\u200b\u200c\u200d\u2060\ufeff"
DEFANGED_DOT = re.compile(r"(?i)(?:\[\s*\.\s*\]|\(\s*\.\s*\)|\{\s*\.\s*\})")
TOKEN = re.compile(r"[^\s<>\"']{4,4096}")


def _strip_outer(value: str) -> str:
    value = value.strip().strip("'\"<>")
    value = value.rstrip(".,;!?:。。，；！")
    for left, right in (("(", ")"), ("[", "]"), ("{", "}")):
        while value.startswith(left) and value.endswith(right):
            value = value[1:-1]
    return value


def _idna_view(value: str) -> str:
    """Validate all authorities, preserving the original path/query spelling."""
    parsed, host = inspect_authority(value)
    port = f":{parsed.port}" if parsed.port is not None else ""
    # Rebuild authority only. urlunsplit would lose an empty '?' or '#'.
    scheme_end = value.find("://")
    start = scheme_end + 3 if scheme_end >= 0 else 0
    boundary = re.search(r"[/?#]", value[start:])
    end = start + boundary.start() if boundary else len(value)
    return value[:start] + host + port + value[end:]


def _normalize_authority(value: str) -> tuple[str, list[str]]:
    """Normalize only scheme/authority; path, query and fragment stay exact."""
    scheme_end = value.find("://")
    authority_start = scheme_end + 3 if scheme_end >= 0 else 0
    boundary = re.search(r"[/?#]", value[authority_start:])
    authority_end = authority_start + boundary.start() if boundary else len(value)
    head, tail = value[:authority_end], value[authority_end:]
    changes: list[str] = []
    normalized = unicodedata.normalize("NFKC", head)
    if normalized != head:
        head = normalized
        changes.append("unicode_nfkc")
    without_hidden = head.translate({ord(character): None for character in ZERO_WIDTH})
    if without_hidden != head:
        head = without_hidden
        changes.append("removed_format_character")
    restored = DEFANGED_DOT.sub(".", head)
    if restored != head:
        head = restored
        changes.append("restored_defanged_dot")
    return head + tail, changes


def inspect_url_intake(text: str, mode: str) -> dict:
    strict_failure = None
    try:
        strict, invalid = extract_urls(text, mode)
    except ValueError as exc:
        if mode != "url":
            raise
        strict, invalid, strict_failure = [], [], exc
    accepted, recovered, findings, rejected = [], [], [], []
    candidates = [text.strip()] if mode == "url" else [match.group() for match in TOKEN.finditer(text)]
    strict_set = set(strict)
    for raw in candidates:
        original = trim_url(_strip_outer(raw))
        if not original or ("@" in original and "://" not in original):
            continue
        value, changes = _normalize_authority(original)
        # Ignore ordinary prose tokens. Treat a transformed whole token as the
        # candidate; never score a spurious ASCII suffix of a Unicode hostname.
        recognizable = original in strict_set or original in invalid or "://" in value or bool(changes)
        try:
            normalized = _idna_view(value)
        except (UnicodeError, ValueError):
            if recognizable and original not in rejected:
                rejected.append(original)
            continue
        if normalized != value:
            changes.append("idna_ascii_host")
        value = normalized
        if not recognizable and not changes:
            continue
        if changes:
            if value not in recovered:
                recovered.append(value)
            if not any(item["original"] == original for item in findings):
                findings.append({"original": original, "analysis_url": value,
                                 "transformations": changes, "requires_user_review": True,
                                 "opened": False})
        elif value not in accepted:
            accepted.append(value)
    urls = list(dict.fromkeys([*accepted, *recovered]))
    if mode == "url" and (not urls or rejected):
        raise strict_failure or ValueError("Nhập một URL HTTP/HTTPS hợp lệ, ví dụ https://example.org/.")
    if len(urls) + len(rejected) > 5:
        raise ValueError("Mỗi lần kiểm tra hỗ trợ tối đa 5 URL khác nhau, kể cả URL được viết che dấu.")
    return {
        "version": VERSION, "idna_policy": IDNA_POLICY,
        "urls": urls, "strict_urls": accepted, "recovered_urls": recovered,
        "invalid_urls": rejected, "findings": findings, "interpretation_only": True,
        "notice": "URL khôi phục chỉ là cách đọc phục vụ chấm cục bộ; ứng dụng không mở URL và không xác nhận đích đến.",
    }


def extract_urls_v2(text: str, mode: str) -> tuple[list[str], list[str]]:
    result = inspect_url_intake(text, mode)
    return result["urls"], result["invalid_urls"]
