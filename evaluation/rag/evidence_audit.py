"""Offline visible-output audit, not a new LLM/RAG effectiveness experiment.

Completed old responses can be projected into ID pairs for contract testing.
Projection is deterministic software transformation, never a model generation;
truncated responses without content are retained as unavailable, not repaired.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics

from app.services.rag.evidence import PROFILE, evidence_catalog, parse_evidence
from app.services.rag.explanation_v2 import parse_explanation_v2


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bytes(value):
    return len(value.encode("utf-8"))


def _lines(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def audit(source_run, out):
    source_run, out = Path(source_run), Path(out)
    if source_run.resolve() == out.resolve():
        raise ValueError("Audit output must be separate from the frozen run.")
    names = ["execution.json", "cases.jsonl", "prepared.json", "predictions.jsonl", "attempts.jsonl", "summary.json"]
    hashes = {str(source_run / name): _sha(source_run / name) for name in names}
    cases = {row["id"]: row for row in _lines(source_run / "cases.jsonl")}
    prepared = json.loads((source_run / "prepared.json").read_text())
    rows = _lines(source_run / "predictions.jsonl")
    lookup = {(row["id"], row["arm"]): row for row in rows}
    records = []
    for row in rows:
        if row["arm"] != "v5_post_rag" or row["status"] == "skipped":
            continue
        text = cases[row["id"]]["text"]
        verdict = lookup[(row["id"], "v5_plain")]["verdict"]
        sources = prepared[row["id"]]["retrieval"]["sources"]
        args = dict(approved_text=text, verdict=verdict, sources=sources)
        catalog = evidence_catalog(**args)
        raw = row.get("raw_content")
        item = {"id": row["id"], "finish_reason": row.get("finish_reason"),
                "original_status": row["status"], "original_code": row.get("code"),
                "completion_tokens_recorded": row.get("usage", {}).get("completion_tokens"),
                "original_visible_utf8_bytes": _bytes(raw) if isinstance(raw, str) else None,
                "catalog_sha256": catalog["catalog_sha256"], "source_metadata_unchanged": True,
                "projection_is_model_generation": False}
        if row.get("finish_reason") != "stop" or not isinstance(raw, str):
            item.update(projection_status="unavailable_original_output", projected_raw=None)
            records.append(item)
            continue
        parsed = parse_explanation_v2(raw, **args)
        item["v2_status"] = parsed["status"]
        if parsed["status"] == "error":
            item.update(projection_status="invalid_original_output", projected_raw=None)
            records.append(item)
            continue
        selected, skipped, seen = [], 0, set()
        for claim in parsed["explanation"]["support"]:
            document = next(source for source in catalog["reference_documents"]
                            if source["document_id"] == claim["document_id"])
            source_span = next((span for span in document["spans"] if claim["source_quote"] in span["text"]), None)
            input_span = next((span for span in catalog["input_spans"] if claim["input_quote"] in span["text"]), None)
            if source_span is None or input_span is None:
                skipped += 1
                continue
            selection = {"source_span_id": source_span["id"], "input_span_id": input_span["id"],
                         "relation": claim["relation"]}
            key = tuple(selection.values())
            if key in seen:
                skipped += 1
                continue
            seen.add(key)
            if len(selected) < 2:
                selected.append(selection)
            else:
                skipped += 1
        projected_raw = json.dumps({"selections": selected}, ensure_ascii=False, separators=(",", ":"))
        replayed = parse_evidence(projected_raw, **args)
        if replayed["status"] == "error":
            raise ValueError("Projected contract replay failed.")
        item.update(projection_status="offline_contract_passed", projected_raw=projected_raw,
                    projected_utf8_bytes=_bytes(projected_raw), projected_selection_count=len(selected),
                    dropped_or_collapsed_claims=skipped, replay_status=replayed["status"],
                    original_claim_count=len(parsed["explanation"]["support"]))
        records.append(item)
    if any(_sha(Path(path)) != expected for path, expected in hashes.items()):
        raise ValueError("Frozen source files changed during audit.")
    available = [row for row in records if row["projection_status"] == "offline_contract_passed"]
    result = {"version": "rag-evidence-visible-output-audit-1", "profile": PROFILE,
              "created_at": datetime.now(timezone.utc).isoformat(), "provider_calls": 0,
              "classification_changed": False, "semantic_support_verified": False,
              "original_outputs_rewritten": False, "truncated_outputs_repaired": False,
              "projection_is_model_generation": False, "input_sha256": hashes,
              "implementation_sha256": {name: _sha(Path(name)) for name in [
                  "app/services/rag/evidence.py", "evaluation/rag/evidence_audit.py"]},
              "source_response_count": len(records),
              "projection_counts": dict(Counter(row["projection_status"] for row in records)),
              "completed_pairs": len(available),
              "median_old_visible_utf8_bytes": statistics.median(row["original_visible_utf8_bytes"] for row in available) if available else None,
              "median_projected_utf8_bytes": statistics.median(row["projected_utf8_bytes"] for row in available) if available else None,
              "note": "Old completed responses are deterministically projected, at most 2 ID pairs; "
                      "claims can collapse or be omitted. This does not establish fresh generation success, "
                      "lower reasoning tokens, less truncation, equal information content, relevance or phishing F1.",
              "records": records}
    out.mkdir(parents=True, exist_ok=True)
    (out / "audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    lines = ["# Selection-only RAG: offline contract audit", "",
             "**No provider requests, no semantic ground truth, no repaired or replaced old response.**", "",
             f"Source responses: {len(records)}; completed contract projections: {len(available)}.",
             f"Projection counts: {json.dumps(result['projection_counts'])}.",
             f"Median visible UTF-8 bytes in completed pairs: {result['median_old_visible_utf8_bytes']} "
             f"→ {result['median_projected_utf8_bytes']}.", "", result["note"], "",
             "A paired fresh comparison must retain all failures, use the same model/token budget/inputs, "
             "and assess relevance separately. The three truncated outputs have no visible content to replay."]
    (out / "report.md").write_text("\n".join(lines) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", type=Path, default=Path("artifacts/evaluations/improvement_pilot_v1"))
    parser.add_argument("--out", type=Path, default=Path("artifacts/evaluations/rag_evidence_contract_v3"))
    args = parser.parse_args()
    result = audit(args.source_run, args.out)
    print(json.dumps({key: result[key] for key in ["provider_calls", "source_response_count", "projection_counts",
          "median_old_visible_utf8_bytes", "median_projected_utf8_bytes"]}))


if __name__ == "__main__":
    main()
