"""Offline projection preserves failures; projected data is never a generation."""
import json

import pytest

from evaluation.rag.evidence_audit import audit


def test_completed_projection_never_salvages_or_rewrites_truncated_response(tmp_path):
    source_run, out = tmp_path / "source", tmp_path / "audit"
    source_run.mkdir()
    text = "Gửi mã OTP cho tôi."
    source = {"document_id": "VN-RAG-001", "text": "Không gửi mã OTP cho người khác.", "title": "Fixture"}
    verdict = {"risk_level": "HIGH", "context_kind": "scam_request", "summary": "Có yêu cầu gửi mã.",
               "evidence": [{"quote": "mã OTP", "reason": "Yêu cầu bí mật."}], "recommended_actions": []}
    claim = {"document_id": source["document_id"], "source_quote": source["text"], "input_quote": "mã OTP",
             "claim": "Nguồn cảnh báo không gửi mã cho người khác.", "relation": "mechanism_match",
             "scope_note": "Không xác minh người gửi cụ thể."}
    cases = [{"id": identifier, "text": text} for identifier in ["one", "empty", "cut"]]
    prepared = {case["id"]: {"retrieval": {"sources": [source]}} for case in cases}
    rows = [{"id": case["id"], "arm": "v5_plain", "verdict": verdict} for case in cases]
    rows += [
        {"id": "one", "arm": "v5_post_rag", "status": "ok", "finish_reason": "stop",
         "raw_content": json.dumps({"support": [claim], "actions": []}), "usage": {"completion_tokens": 500}},
        {"id": "empty", "arm": "v5_post_rag", "status": "no_support", "finish_reason": "stop",
         "raw_content": '{"support":[],"actions":[]}', "usage": {"completion_tokens": 80}},
        {"id": "cut", "arm": "v5_post_rag", "status": "error", "code": "OUTPUT_TRUNCATED",
         "finish_reason": "length", "raw_content": None, "usage": {"completion_tokens": 8192}},
    ]
    for name, content in [("execution.json", {}), ("prepared.json", prepared), ("summary.json", {})]:
        (source_run / name).write_text(json.dumps(content))
    for name, content in [("cases.jsonl", cases), ("predictions.jsonl", rows), ("attempts.jsonl", [])]:
        (source_run / name).write_text("".join(json.dumps(row) + "\n" for row in content))
    before = {path.name: path.read_bytes() for path in source_run.iterdir()}
    result = audit(source_run, out)
    assert result["projection_counts"] == {"offline_contract_passed": 2, "unavailable_original_output": 1}
    assert result["provider_calls"] == 0 and result["semantic_support_verified"] is False
    assert result["projection_is_model_generation"] is False
    cut = next(record for record in result["records"] if record["id"] == "cut")
    assert cut["original_code"] == "OUTPUT_TRUNCATED" and cut["projected_raw"] is None
    assert before == {path.name: path.read_bytes() for path in source_run.iterdir()}
    assert (out / "audit.json").is_file() and (out / "report.md").is_file()
    with pytest.raises(ValueError, match="separate"):
        audit(source_run, source_run)
