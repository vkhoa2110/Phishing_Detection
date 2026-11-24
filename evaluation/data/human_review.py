"""Validate two external human-review sheets against a separately frozen inventory.

This CLI only prepares blank packets and reports pending/agreement/disagreement.
It does not infer labels, authenticate people, adjudicate, or export gold data.
Keep the printed manifest SHA-256 separately from the reviewer CSV copies.

Examples::

    python -m evaluation.data.human_review freeze --kind classification \\
      --source trusted_blank.csv --source-sha256 <sha256> --out packet_v1
    python -m evaluation.data.human_review reconcile --inventory packet_v1 \\
      --manifest-sha256 <printed_sha256> --a returned_a.csv --b returned_b.csv \\
      --out review_status_v1

The older SMS/retrieval finalization protocols remain unchanged. Reviewer IDs
are declarations only; different IDs do not establish human independence.
"""
import argparse
from collections import Counter
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import random
import re
import unicodedata

from evaluation.data.sms import spreadsheet_cell


@dataclass(frozen=True)
class ReviewSpec:
    keys: tuple[str, ...]
    decisions: tuple[str, ...]
    allowed: frozenset[str]
    basis: str
    reviewer: str
    extra_mutable: tuple[str, ...] = ()

    @property
    def mutable(self):
        return self.decisions + (self.basis, self.reviewer) + self.extra_mutable


SPECS = {
    "classification": ReviewSpec(("sample_id",), ("human_label",),
        frozenset({"PHISHING", "BENIGN", "INSUFFICIENT"}), "evidence_basis", "reviewer_id", ("notes",)),
    "rag": ReviewSpec(("pair_id",), ("human_relevance_0_2", "human_support_0_2"),
        frozenset({"0", "1", "2"}), "human_rationale", "human_rater_id"),
    "injection": ReviewSpec(("pair_id", "arm"), ("human_instruction_followed",),
        frozenset({"YES", "NO", "UNDETERMINED"}), "human_reason", "human_reviewer", ("human_evidence_quote",)),
}
INPUT_COLUMNS = {
    "classification": ("sample_id", "text_redacted"),
    "rag": ("pair_id", "approved_message", "input_quote", "source_summary_quote", "source_url",
        "source_title", "publisher", "published_at", "source_text_kind", "declared_relation",
        "rendered_claim", "claim_origin", "source_scope_note"),
    # Injection is an output-comparison review, not blinded phishing annotation.
    "injection": ("pair_id", "arm", "base_id", "variant_id", "original_text", "variant_text",
        "inserted_instruction", "forced_literal_risk_level", "base_level", "variant_level", "base_status",
        "variant_status", "base_error", "variant_error", "base_finish_reason", "variant_finish_reason",
        "base_raw_output", "variant_raw_output", "base_parsed_verdict",
        "variant_parsed_verdict", "base_request_key", "variant_request_key"),
}
STATES = ("PENDING_BOTH", "A_ONLY", "B_ONLY", "AGREEMENT", "DISAGREEMENT")
VERSION = "human-review-inventory-1.0"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def text_digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _snapshot(path, expected, what):
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError(f"A lowercase SHA-256 anchor is required for {what}.")
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError(f"Frozen {what} changed (SHA-256 mismatch).")
    return raw


def _csv_bytes(raw):
    with io.StringIO(raw.decode("utf-8-sig"), newline="") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames or []
        if not fields or any(not name for name in fields) or len(set(fields)) != len(fields):
            raise ValueError("CSV headers are empty or duplicate.")
        rows = list(reader)
    if not rows:
        raise ValueError("An empty inventory cannot establish review agreement.")
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ValueError("CSV row has missing or excess cells.")
    return fields, rows


def _csv(path):
    return _csv_bytes(Path(path).read_bytes())


def _key(row, spec):
    values = tuple(row[field] for field in spec.keys)
    if any(not value.strip() or value != value.strip() or value.startswith(("=", "+", "-", "@")) for value in values):
        raise ValueError("Missing, whitespace-altered, or spreadsheet-unsafe review ID.")
    return values


def _index(rows, spec):
    result = {}
    for row in rows:
        key = _key(row, spec)
        if key in result:
            raise ValueError("Duplicate review ID: " + repr(key))
        result[key] = row
    return result


def _write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_csv(path, fields, rows):
    with Path(path).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: spreadsheet_cell(str(row.get(key, ""))) for key in fields})


def freeze(kind, source, out, source_sha256, registration=None):
    """Freeze trusted blank inputs; never derive the inventory from returned A/B."""
    if kind not in SPECS:
        raise ValueError("Unknown review kind.")
    source, out = Path(source), Path(out)
    registration = Path(registration) if registration is not None else None
    if registration is not None and (registration.exists() or registration.resolve().is_relative_to(out.resolve())):
        raise ValueError("Keep a new operator registration outside the reviewer packet.")
    if out.exists():
        raise ValueError("Preserve existing review packets; choose a new output directory.")
    source_snapshot = _snapshot(source, source_sha256, "source")
    spec = SPECS[kind]
    fields, rows = _csv_bytes(source_snapshot)
    required = set(spec.keys + spec.mutable)
    expected_columns = required | set(INPUT_COLUMNS[kind])
    allowed_source_columns = [expected_columns]
    if kind == "injection":
        allowed_source_columns.append(expected_columns | {"literal_verdict_command_result"})
    if set(fields) not in allowed_source_columns:
        raise ValueError("Trusted input has missing or unexpected columns; AI labels/predictions are not permitted in classification or RAG packets.")
    _index(rows, spec)
    if any(row[column].strip() for row in rows for column in spec.mutable):
        raise ValueError("Freeze only blank human-review inputs, never existing labels.")
    omitted = ["literal_verdict_command_result"] if kind == "injection" and "literal_verdict_command_result" in fields else []
    fields = [column for column in fields if column not in omitted]
    rows = [{column: row[column] for column in fields} for row in rows]
    immutable = [column for column in fields if column not in spec.mutable]
    inputs = [{"input": {column: row[column] for column in immutable},
               "sha256": {column: text_digest(row[column]) for column in immutable}} for row in rows]
    out.mkdir(parents=True)
    (out / "trusted_source.snapshot.csv").write_bytes(source_snapshot)
    inventory = out / "inventory.jsonl"
    inventory.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in inputs), encoding="utf-8")
    manifest = {"version": VERSION, "kind": kind, "rows": len(rows), "columns": fields,
                "immutable_columns": immutable, "source_sha256": source_sha256, "omitted_columns": omitted,
                "inventory_file": "inventory.jsonl", "inventory_sha256": digest(inventory),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "human_labels_generated": 0, "identity_verification": "Declared reviewer IDs only; no authentication."}
    _write_json(out / "manifest.json", manifest)
    # Different deterministic orders prevent accidental row-position matching.
    for reviewer in ("a", "b"):
        ordered = list(rows)
        random.Random(f"{manifest['inventory_sha256']}:{reviewer}").shuffle(ordered)
        _write_csv(out / f"annotator_{reviewer}.csv", fields, ordered)
    result = {"inventory": str(out), "rows_per_sheet": len(rows), "kind": kind,
              "manifest_sha256": digest(out / "manifest.json"), "human_labels_generated": 0}
    if registration is not None:
        registration.parent.mkdir(parents=True, exist_ok=True)
        _write_json(registration, {"version": "human-review-registration-1.0",
            "inventory": os.path.relpath(out.resolve(), registration.parent.resolve()),
            "manifest_sha256": result["manifest_sha256"]})
        result["operator_registration"] = str(registration)
    return result


def load_inventory(path, manifest_sha256):
    path = Path(path)
    manifest_snapshot = _snapshot(path / "manifest.json", manifest_sha256, "manifest")
    manifest = json.loads(manifest_snapshot.decode("utf-8"))
    if manifest.get("version") != VERSION or manifest.get("kind") not in SPECS:
        raise ValueError("Unsupported frozen inventory version/kind.")
    spec = SPECS[manifest["kind"]]
    fields = manifest.get("columns", [])
    immutable = manifest.get("immutable_columns", [])
    if (not isinstance(fields, list) or len(set(fields)) != len(fields)
            or set(fields) != set(INPUT_COLUMNS[manifest["kind"]] + spec.mutable)
            or manifest.get("omitted_columns") not in ([[], ["literal_verdict_command_result"]] if manifest["kind"] == "injection" else [[]])
            or immutable != [column for column in fields if column not in spec.mutable]
            or manifest.get("inventory_file") != "inventory.jsonl"):
        raise ValueError("Invalid frozen inventory schema.")
    inventory_snapshot = _snapshot(path / "inventory.jsonl", manifest.get("inventory_sha256"), "inventory")
    data = [json.loads(line) for line in inventory_snapshot.decode("utf-8").splitlines() if line.strip()]
    if not data or len(data) != manifest.get("rows"):
        raise ValueError("Frozen inventory count changed.")
    rows = []
    for row in data:
        if set(row) != {"input", "sha256"} or set(row["input"]) != set(immutable) or set(row["sha256"]) != set(immutable):
            raise ValueError("Malformed frozen inventory row.")
        if any(not isinstance(row["input"][column], str) or text_digest(row["input"][column]) != row["sha256"][column] for column in immutable):
            raise ValueError("Frozen input text digest changed.")
        rows.append(row["input"])
    return manifest, spec, _index(rows, spec)


def _identity(value):
    return unicodedata.normalize("NFKC", value).strip().casefold()


def read_returned(path, manifest, spec, inputs):
    snapshot = Path(path).read_bytes()
    fields, rows = _csv_bytes(snapshot)
    if set(fields) != set(manifest["columns"]):
        raise ValueError("Returned CSV columns differ from the frozen packet.")
    indexed = _index(rows, spec)
    if indexed.keys() != inputs.keys():
        raise ValueError("Returned IDs are missing or unexpected; retain the exact frozen inventory.")
    declared = {}
    results = {}
    for key, row in indexed.items():
        for column, expected in inputs[key].items():
            if row[column] not in {expected, spreadsheet_cell(expected)}:
                raise ValueError(f"Frozen input changed: {key!r}, {column}.")
        decisions = {field: row[field].strip() for field in spec.decisions}
        if any(value and value not in spec.allowed for value in decisions.values()):
            raise ValueError("Invalid human label/grade: " + repr(key))
        reviewer, basis = row[spec.reviewer].strip(), row[spec.basis].strip()
        if reviewer:
            declared[_identity(reviewer)] = reviewer
        filled = sum(bool(value) for value in decisions.values())
        if filled and (not reviewer or not basis):
            raise ValueError("Any entered judgment requires a declared reviewer and evidence basis: " + repr(key))
        complete = filled == len(spec.decisions)
        results[key] = {"decisions": decisions, "reviewer": reviewer, "basis": basis,
                        "extra": {column: row[column] for column in spec.extra_mutable},
                        "complete": complete, "progress": "COMPLETE" if complete else "IN_PROGRESS" if filled else "EMPTY"}
    if len(declared) > 1:
        raise ValueError("Each returned sheet must declare one consistent reviewer ID.")
    return results, next(iter(declared.values()), ""), snapshot


def reconcile(inventory, a, b, out, manifest_sha256):
    """Validate external copies and emit unresolved decisions, never gold labels."""
    out = Path(out)
    if out.exists():
        raise ValueError("Preserve prior review results; choose a new output directory.")
    manifest, spec, inputs = load_inventory(inventory, manifest_sha256)
    left, reviewer_a, snapshot_a = read_returned(a, manifest, spec, inputs)
    right, reviewer_b, snapshot_b = read_returned(b, manifest, spec, inputs)
    if reviewer_a and reviewer_b and _identity(reviewer_a) == _identity(reviewer_b):
        raise ValueError("Independent sheets require two distinct declared reviewer IDs.")
    counts, output = Counter({state: 0 for state in STATES}), []
    agreement_axes = {field: 0 for field in spec.decisions}
    for key in sorted(inputs):
        lrow, rrow = left[key], right[key]
        if lrow["complete"] and rrow["complete"]:
            equal = lrow["decisions"] == rrow["decisions"]
            state = "AGREEMENT" if equal else "DISAGREEMENT"
            for field in spec.decisions:
                agreement_axes[field] += int(lrow["decisions"][field] == rrow["decisions"][field])
        else:
            state = "A_ONLY" if lrow["complete"] else "B_ONLY" if rrow["complete"] else "PENDING_BOTH"
        counts[state] += 1
        record = {**inputs[key], "status": state, "progress_a": lrow["progress"], "progress_b": rrow["progress"],
                  "reviewer_a": lrow["reviewer"], "reviewer_b": rrow["reviewer"],
                  "basis_a": lrow["basis"], "basis_b": rrow["basis"]}
        for field in spec.decisions:
            record.update({field + "_a": lrow["decisions"][field], field + "_b": rrow["decisions"][field],
                           "adjudicated_" + field: ""})
        for field in spec.extra_mutable:
            record.update({field + "_a": lrow["extra"][field], field + "_b": rrow["extra"][field]})
        record.update({"adjudicator_id": "", "adjudication_basis": ""})
        output.append(record)
    paired = counts["AGREEMENT"] + counts["DISAGREEMENT"]
    summary = {"kind": manifest["kind"], "rows": len(inputs), "states": dict(counts),
        "completed_a": sum(row["complete"] for row in left.values()),
        "completed_b": sum(row["complete"] for row in right.values()), "paired_completed": paired,
        "agreement_fraction": counts["AGREEMENT"] / paired if paired else None,
        "agreement_by_axis": {field: {"agreed": count, "paired_denominator": paired,
            "fraction": count / paired if paired else None} for field, count in agreement_axes.items()},
        "reviewer_a": reviewer_a or None, "reviewer_b": reviewer_b or None,
        "identity_verification": "Declared IDs only; identities and human independence are not authenticated.",
        "human_labels_generated": 0, "adjudications_generated": 0, "gold_exported": False,
        "unresolved_disagreements": counts["DISAGREEMENT"],
        "status": "awaiting_human_review" if paired < len(inputs) else "awaiting_human_adjudication" if counts["DISAGREEMENT"] else "two_declared_reviewer_agreement_not_frozen_gold",
        "provenance": {"manifest_sha256": manifest_sha256, "inventory_sha256": manifest["inventory_sha256"],
            "returned_a_sha256": hashlib.sha256(snapshot_a).hexdigest(), "returned_b_sha256": hashlib.sha256(snapshot_b).hexdigest()}}
    out.mkdir(parents=True)
    (out / "returned_a.snapshot.csv").write_bytes(snapshot_a)
    (out / "returned_b.snapshot.csv").write_bytes(snapshot_b)
    _write_csv(out / "review_status.csv", list(output[0]), output)
    _write_csv(out / "adjudication.csv", list(output[0]), [row for row in output if row["status"] == "DISAGREEMENT"])
    _write_json(out / "summary.json", summary)
    return summary


def registered_inventory(path):
    """Read the operator-owned SHA anchor, stored apart from returned CSVs."""
    path = Path(path)
    record = json.loads(path.read_text(encoding="utf-8"))
    if set(record) != {"version", "inventory", "manifest_sha256"} or record["version"] != "human-review-registration-1.0":
        raise ValueError("Invalid operator registration.")
    if not isinstance(record["inventory"], str) or not record["inventory"]:
        raise ValueError("Invalid registered inventory path.")
    return (path.parent / record["inventory"]).resolve(), record["manifest_sha256"]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="action", required=True)
    prepare = commands.add_parser("freeze", help="Freeze trusted blank inputs before collecting returned reviews.")
    prepare.add_argument("--kind", choices=tuple(SPECS), required=True)
    prepare.add_argument("--source", type=Path, required=True)
    prepare.add_argument("--source-sha256", required=True)
    prepare.add_argument("--out", type=Path, required=True)
    prepare.add_argument("--registration", type=Path, help="New operator-owned SHA registration, outside the reviewer packet.")
    merge = commands.add_parser("reconcile", help="Report pending and conflicting human reviews without adjudicating.")
    merge.add_argument("--registration", type=Path, help="Operator-owned registration; do not accept a reviewer-supplied file.")
    merge.add_argument("--inventory", type=Path)
    merge.add_argument("--manifest-sha256")
    merge.add_argument("--a", type=Path, required=True)
    merge.add_argument("--b", type=Path, required=True)
    merge.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.action == "freeze":
            result = freeze(args.kind, args.source, args.out, args.source_sha256, args.registration)
        else:
            if args.registration:
                if args.inventory is not None or args.manifest_sha256 is not None:
                    raise ValueError("Use an operator registration or explicit inventory/hash, not both.")
                inventory, anchor = registered_inventory(args.registration)
            else:
                if args.inventory is None or args.manifest_sha256 is None:
                    raise ValueError("Provide --registration or both --inventory and --manifest-sha256.")
                inventory, anchor = args.inventory, args.manifest_sha256
            result = reconcile(inventory, args.a, args.b, args.out, anchor)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        parser.exit(2, f"Human review stopped: {exc}\n")


if __name__ == "__main__":
    main()
