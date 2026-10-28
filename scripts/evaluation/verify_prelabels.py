"""Verify AI prelabel delivery without accepting it as independently reviewed gold."""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from app.privacy import redact
from evaluation.message_data import read_jsonl, spreadsheet_cell
from evaluation.review import CATEGORIES, validate_gold, workspace_items


def verify(directory, workspace):
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest.get("status") != "ai_preliminary" or manifest.get("human_reviewed") is not False:
        raise ValueError("Expected explicit provisional AI status.")
    for name, expected in manifest["files"].items():
        if Path(name).name != name or hashlib.sha256((directory / name).read_bytes()).hexdigest() != expected:
            raise ValueError("Invalid file fingerprint: " + name)
    items, _ = workspace_items(workspace)
    source = {i["id"]: redact(i["text"])[0] for i in items}
    annotations = read_jsonl(directory / "labels.jsonl")
    if len(annotations) != len(items) or {r["id"] for r in annotations} != set(source):
        raise ValueError("IDs are duplicated or incomplete.")
    for r in annotations:
        if r["text"] != source[r["id"]] or r["annotation_status"] != "ai_preliminary" or r["independent_human_review"] is not False:
            raise ValueError("Input or annotation provenance mismatch.")
        if r["label"] is not None and (type(r["label"]) is not int or r["label"] not in {0, 1}):
            raise ValueError("Invalid AI label.")
        if not r["annotation_available"]:
            raise ValueError("Unavailable responses remain; finish the repair run.")
        if r["category"] not in CATEGORIES or r["confidence"] not in {"high", "medium", "low"} or not r["notes"].strip():
            raise ValueError("Invalid category, confidence or rationale.")
        if r["label"] == 1 and not r["evidence_quote"].strip():
            raise ValueError("Positive annotation lacks an action quote.")
        if r["evidence_quote"] and r["evidence_quote"] not in r["text"]:
            raise ValueError("Evidence is not in input.")
    summary = json.loads((directory / "summary.json").read_text())
    counts = dict(Counter("UNKNOWN" if r["label"] is None else str(r["label"]) for r in annotations))
    if counts != summary["counts"] or summary["valid_annotations"] != len(items):
        raise ValueError("Summary does not match annotation counts.")
    priority_ids = {r["id"] for r in annotations if r["label"] in (None, 1) or r["confidence"] != "high"}
    for filename, expected in (("review_all.csv", set(source)), ("priority_review.csv", priority_ids)):
        with (directory / filename).open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        if len(rows) != len(expected) or {r["id"] for r in rows} != expected:
            raise ValueError("CSV selection is incomplete or duplicated.")
        if any(r["text"] != spreadsheet_cell(source[r["id"]]) for r in rows):
            raise ValueError("CSV message text or formula escaping changed.")
    for name, expected in manifest["configuration"]["human_sheet_sha256"].items():
        if hashlib.sha256((workspace / name).read_bytes()).hexdigest() != expected:
            raise ValueError("Blind human sheet changed since the AI run began.")
    try:
        validate_gold(directory / "manifest.json", directory / "labels.jsonl")
    except ValueError:
        pass
    else:
        raise ValueError("AI annotations must never pass the human-gold gate.")
    return {"status": "passed", "items": len(items), "all_provider_annotations_available": True,
        "counts": counts, "priority_items": len(priority_ids), "input_text_and_evidence_verified": True,
        "blind_human_sheet_hashes_unchanged": True, "rejected_as_human_gold": True,
        "scope": "Structural provenance, quotes, file hashes, counts, CSV and gold gate only. Not independent semantic label validation."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--workspace", type=Path, default=ROOT / "data/annotation/vn_sms_v2")
    args = parser.parse_args()
    result = verify(args.directory, args.workspace)
    path = args.directory / "verification.json"
    if path.exists(): parser.error("Verification already exists; retain the earlier record.")
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
