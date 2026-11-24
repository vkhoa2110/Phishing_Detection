"""Map formatting-equivalent quotes back to literal, bounded input spans.

No punctuation, accent, spelling or word changes are allowed. URL bytes and
redaction markers keep their case. This validates provenance, not semantics.
"""
import re

from app.domain.validation import REDACTION_PATTERN
from app.services.url.parsing import URL_PATTERN

VERSION = "evidence-span-alignment-1.0"


class SpanError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _index(text):
    protected = set()
    for pattern in (URL_PATTERN, REDACTION_PATTERN):
        for match in pattern.finditer(text):
            protected.update(range(match.start(), match.end()))
    characters, starts, ends, preserve_case = [], [], [], []
    for match in re.finditer(r"\s+|\S", text):
        value = match.group()
        if value.isspace():
            value = " "
        elif match.start() not in protected:
            lower = value.lower()
            # Avoid case expansions that could equate different spellings.
            if len(lower) == 1:
                value = lower
        characters.append(value)
        starts.append(match.start())
        ends.append(match.end())
        preserve_case.append(match.start() in protected)
    return "".join(characters), starts, ends, preserve_case


def align_quote(quote, text, *, max_length=240):
    if not quote.strip():
        raise SpanError("QUOTE_BLANK")
    start = text.find(quote)
    if start >= 0:
        end, kind = start + len(quote), "exact"
    else:
        normalized, starts, ends, preserve_case = _index(text)
        needle = _index(quote.strip())[0]
        spelling = re.sub(r"\s+", " ", quote.strip())
        location = normalized.find(needle)
        # A quote can begin inside a URL or marker, so detecting URLs in the
        # quote alone is insufficient. Check the source's protected positions.
        while location >= 0:
            if all(not preserve_case[location + i] or spelling[i] == normalized[location + i]
                   for i in range(len(needle))):
                break
            location = normalized.find(needle, location + 1)
        if location < 0:
            raise SpanError("QUOTE_NOT_FOUND")
        start, end = starts[location], ends[location + len(needle) - 1]
        kind = "format_equivalent"
    if end - start > max_length:
        raise SpanError("QUOTE_SPAN_TOO_LONG")
    return text[start:end], {"start": start, "end": end, "match": kind}
