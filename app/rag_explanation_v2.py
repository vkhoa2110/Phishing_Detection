"""Parser correction for distinct claims citing the same retrieved document.

The v1 prompt, JSON schema, transport and payload builder stay byte-identical.
V1 incorrectly imposed one claim per document despite no such prompt/schema
constraint. V2 checks every quote, permits distinct claims per document, and
rejects exact duplicate claim objects. This is not semantic-support validation.
"""
from .rag_explanation import (Explanation, PROFILE, SYSTEM_PROMPT, SOURCE_FIELDS,
                              _checked_inputs, _empty_result, _load_strict_json,
                              build_explanation_payload, build_retrieval_query,
                              call_explanation as _call_v1)


PARSER_VERSION = "rag-explanation-parser-v2"


def _result(status, code=None):
    result = _empty_result(status, code)
    result["validation"].update(parser_version=PARSER_VERSION, parser_applied=True)
    return result


def parse_explanation_v2(raw, *, approved_text, verdict, sources):
    """Validate each claim rather than using document ID as claim identity."""
    try:
        _, normalized = _checked_inputs(approved_text, verdict, sources)
    except (ValueError, TypeError):
        return _result("error", "INPUT_INVALID")
    if not isinstance(raw, str) or len(raw) > 100000:
        return _result("error", "OUTPUT_INVALID")
    try:
        explanation = Explanation.model_validate(_load_strict_json(raw), strict=True)
    except (ValueError, TypeError):
        return _result("error", "OUTPUT_INVALID")
    allowed = {source["document_id"]: source for source in normalized}
    used_documents, used_claims = set(), set()
    for claim in explanation.support:
        source = allowed.get(claim.document_id)
        if not source or claim.source_quote not in source["text"]:
            return _result("error", "SOURCE_NOT_GROUNDED")
        if claim.input_quote not in approved_text:
            return _result("error", "INPUT_QUOTE_NOT_GROUNDED")
        identity = (claim.document_id, claim.source_quote, claim.input_quote,
                    claim.claim, claim.relation, claim.scope_note)
        if identity in used_claims:
            return _result("error", "DUPLICATE_CLAIM")
        used_claims.add(identity)
        used_documents.add(claim.document_id)
    for action in explanation.actions:
        identifiers = action.supporting_document_ids
        if len(identifiers) != len(set(identifiers)) or not set(identifiers) <= used_documents:
            return _result("error", "ACTION_SOURCE_NOT_GROUNDED")
    if not explanation.support:
        return _result("no_support")
    result = _result("ok")
    result["explanation"] = explanation.model_dump()
    result["validation"].update(exact_source_quotes_checked=True, exact_input_quotes_checked=True,
                                 allowed_document_ids_checked=True)
    return result


async def call_explanation_v2(client, *, endpoint, api_key, payload, approved_text, verdict, sources, timeout,
                              capture_raw=False):
    """Reuse V1 network behavior and correct only eligible completed parsing.

    HTTP/connection/timeout/truncation/schema errors are preserved. The caller
    still validates endpoint and consent. Default app returns omit raw content.
    """
    result = await _call_v1(client, endpoint=endpoint, api_key=api_key, payload=payload,
        approved_text=approved_text, verdict=verdict, sources=sources, timeout=timeout, capture_raw=True)
    eligible = (result.get("finish_reason") == "stop" and (
        result["status"] in {"ok", "no_support"} or result.get("code") == "SOURCE_NOT_GROUNDED"))
    if eligible:
        parsed = parse_explanation_v2(result.get("raw_content"), approved_text=approved_text,
                                     verdict=verdict, sources=sources)
        result.update(parsed)
        if parsed["status"] != "error":
            result.pop("code", None)
    else:
        result["validation"].update(parser_version=PARSER_VERSION, parser_applied=False)
    if not capture_raw:
        result.pop("raw_content", None)
    return result
