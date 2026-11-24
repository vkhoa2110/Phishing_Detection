"""Seal externally completed classification reviews without creating human labels.

This additive tool requires the operator-owned frozen registration, two returned
reviewer sheets, an explicit operator attestation, and manual resolutions for
every disagreement. Declared IDs and attestations do not authenticate people.
It does not read case/design labels, model predictions, or the review ID key.

``init`` creates blank operator templates and a readiness report; it never
finalizes pending reviews. Keep the printed reference-manifest SHA-256 outside
the reference directory, just as for the original review registration.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import unicodedata

from evaluation.data import human_review as review

VERSION = "adjudicated-human-reference-1.0"
STATUS = "declared_human_adjudicated_reference_not_independently_authenticated"
SCOPE = "visible_message_actions"
ATTESTATION_VERSION = "human-review-operator-attestation-1.0"
ATTESTATION_FIELDS = {"version", "human_origin_confirmed", "reviewer_independence_attested",
                      "operator_id", "reviewer_a_id", "reviewer_b_id", "scope"}
DECISION_FIELDS = ("sample_id", "human_label_a", "human_label_b", "final_label",
                   "adjudication_basis", "adjudicator_id")
SEALED_FILES = ("registration.snapshot.json", "inventory/manifest.json", "inventory/inventory.jsonl",
                "returned_a.snapshot.csv", "returned_b.snapshot.csv", "attestation.snapshot.json",
                "adjudication.snapshot.csv", "reference.jsonl")
HELPERS = ("human_review.py", "adjudicated_reference.py")
IDENTITY_LIMIT = "Declared IDs and operator attestations only; people and independence are not authenticated."


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _identity(value):
    return unicodedata.normalize("NFKC", value).strip().casefold()


def _json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON field: " + key)
            result[key] = value
        return result
    try:
        return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Invalid JSON input.") from exc


def _write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _csv_bytes(raw):
    with io.StringIO(raw.decode("utf-8-sig"), newline="") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames or []
        if len(fields) != len(set(fields)) or set(fields) != set(DECISION_FIELDS):
            raise ValueError("Manual adjudication requires the exact template columns; no AI/design/source fields.")
        rows = list(reader)
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ValueError("Malformed manual adjudication CSV row.")
    return rows


def _registration(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    data = _json(raw)
    if (not isinstance(data, dict) or set(data) != {"version", "inventory", "manifest_sha256"}
            or data["version"] != "human-review-registration-1.0"
            or not isinstance(data["inventory"], str) or not data["inventory"]):
        raise ValueError("Invalid operator registration.")
    # The existing inventory loader validates the external manifest SHA anchor.
    return path, raw, (path.parent / data["inventory"]).resolve(), data["manifest_sha256"]


def _reviews(registration, a, b):
    reg_path, reg_raw, inventory, anchor = _registration(registration)
    manifest, spec, inputs = review.load_inventory(inventory, anchor)
    if manifest["kind"] != "classification":
        raise ValueError("Finalized phishing references require classification review packets.")
    left, who_a, raw_a = review.read_returned(a, manifest, spec, inputs)
    right, who_b, raw_b = review.read_returned(b, manifest, spec, inputs)
    if who_a and who_b and _identity(who_a) == _identity(who_b):
        raise ValueError("Two distinct declared reviewer IDs are required.")
    # Capture only bytes that still match the SHA anchors validated above.
    frozen_manifest = review._snapshot(inventory / "manifest.json", anchor, "manifest")
    frozen_inventory = review._snapshot(inventory / "inventory.jsonl", manifest["inventory_sha256"], "inventory")
    states = Counter({name: 0 for name in review.STATES})
    disagreements = []
    for key in sorted(inputs):
        lrow, rrow = left[key], right[key]
        if lrow["complete"] and rrow["complete"]:
            if lrow["decisions"] == rrow["decisions"]:
                state = "AGREEMENT"
            else:
                state = "DISAGREEMENT"
                disagreements.append({"sample_id": key[0], "human_label_a": lrow["decisions"]["human_label"],
                                      "human_label_b": rrow["decisions"]["human_label"], "final_label": "",
                                      "adjudication_basis": "", "adjudicator_id": ""})
        else:
            state = "A_ONLY" if lrow["complete"] else "B_ONLY" if rrow["complete"] else "PENDING_BOTH"
        states[state] += 1
    paired = states["AGREEMENT"] + states["DISAGREEMENT"]
    readiness = {"status": "awaiting_human_review" if paired < len(inputs) else
                    "awaiting_manual_adjudication_and_operator_attestation" if disagreements else
                    "awaiting_operator_attestation",
                 "rows": len(inputs), "completed_a": sum(r["complete"] for r in left.values()),
                 "completed_b": sum(r["complete"] for r in right.values()), "paired_completed": paired,
                 "states": dict(states), "agreement_fraction": states["AGREEMENT"] / paired if paired else None,
                 "finalized_reference_ready": False, "human_labels_generated": 0,
                 "independent_human_authentication": False, "identity_verification": IDENTITY_LIMIT,
                 "quality_metrics": "not measured; review readiness is not classification accuracy"}
    return {"registration_path": reg_path, "registration_raw": reg_raw, "inventory": inventory,
            "anchor": anchor, "manifest": manifest, "inputs": inputs, "left": left, "right": right,
            "who_a": who_a, "who_b": who_b, "raw_a": raw_a, "raw_b": raw_b,
            "frozen_manifest": frozen_manifest, "frozen_inventory": frozen_inventory,
            "readiness": readiness, "disagreements": disagreements}


def init_review(registration, a, b, out):
    """Inspect actual returns and prepare unfilled attestation/adjudication templates."""
    out = Path(out)
    if out.exists():
        raise ValueError("Choose new output; preserve prior review/finalization results.")
    context = _reviews(registration, a, b)
    out.mkdir(parents=True)
    _write_json(out / "readiness.json", context["readiness"])
    _write_json(out / "attestation.json", {"version": ATTESTATION_VERSION,
        "human_origin_confirmed": False, "reviewer_independence_attested": False,
        "operator_id": "", "reviewer_a_id": "", "reviewer_b_id": "", "scope": SCOPE})
    review._write_csv(out / "adjudication.csv", DECISION_FIELDS, context["disagreements"])
    return context["readiness"]


def _attestation(raw, context):
    data = _json(raw)
    if (not isinstance(data, dict) or set(data) != ATTESTATION_FIELDS
            or data["version"] != ATTESTATION_VERSION or data["scope"] != SCOPE):
        raise ValueError("Invalid attestation schema or evaluation scope.")
    if data["human_origin_confirmed"] is not True or data["reviewer_independence_attested"] is not True:
        raise ValueError("An operator must explicitly attest human origin and independent review.")
    for key in ("operator_id", "reviewer_a_id", "reviewer_b_id"):
        if not isinstance(data[key], str) or not data[key].strip():
            raise ValueError("Attestation must name the operator and both declared reviewer IDs.")
    if (_identity(data["reviewer_a_id"]) != _identity(context["who_a"])
            or _identity(data["reviewer_b_id"]) != _identity(context["who_b"])
            or _identity(data["reviewer_a_id"]) == _identity(data["reviewer_b_id"])):
        raise ValueError("Attested reviewer IDs must match the two distinct returned sheets.")
    return data


def _reference(context, attestation_raw, adjudication_raw):
    if context["readiness"]["paired_completed"] != context["readiness"]["rows"]:
        raise ValueError("Every frozen sample requires two completed human reviews before finalization.")
    _attestation(attestation_raw, context)
    expected = {row["sample_id"]: row for row in context["disagreements"]}
    decisions = {}
    for row in _csv_bytes(adjudication_raw):
        sample_id = row["sample_id"]
        if sample_id not in expected or sample_id in decisions:
            raise ValueError("Manual decisions contain unknown, agreeing, or duplicate sample IDs.")
        if any(row[field] != expected[sample_id][field] for field in ("human_label_a", "human_label_b")):
            raise ValueError("Manual decision A/B labels differ from the returned human reviews.")
        if row["final_label"] not in review.SPECS["classification"].allowed:
            raise ValueError("Manual final_label must be PHISHING, BENIGN, or INSUFFICIENT.")
        if not row["adjudication_basis"].strip() or not row["adjudicator_id"].strip():
            raise ValueError("Every manual decision requires case evidence and an adjudicator ID.")
        decisions[sample_id] = row
    if decisions.keys() != expected.keys():
        raise ValueError("Every human disagreement requires explicit manual adjudication.")
    rows = []
    for key in sorted(context["inputs"]):
        sample_id = key[0]
        rows.append({"sample_id": sample_id,
            "label": decisions[sample_id]["final_label"] if sample_id in decisions else
                     context["left"][key]["decisions"]["human_label"],
            "text_sha256": review.text_digest(context["inputs"][key]["text_redacted"]),
            "resolution": "manual_adjudication" if sample_id in decisions else "agreement"})
    return rows


def _helpers():
    return {"evaluation/data/" + name: review.digest(Path(__file__).parent / name) for name in HELPERS}


def _provenance(context, attestation_raw, adjudication_raw):
    return {"registration_path": str(context["registration_path"]),
        "registration_sha256": _sha(context["registration_raw"]), "registered_inventory": str(context["inventory"]),
        "inventory_manifest_sha256": context["anchor"], "inventory_sha256": context["manifest"]["inventory_sha256"],
        "returned_a_sha256": _sha(context["raw_a"]), "returned_b_sha256": _sha(context["raw_b"]),
        "attestation_sha256": _sha(attestation_raw), "adjudication_sha256": _sha(adjudication_raw)}


def finalize(registration, a, b, attestation, adjudication, out):
    """Seal complete externally supplied human judgments, without automatic adjudication."""
    out = Path(out)
    if out.exists():
        raise ValueError("Choose new output; preserve prior review/finalization results.")
    context = _reviews(registration, a, b)
    attestation_raw, adjudication_raw = Path(attestation).read_bytes(), Path(adjudication).read_bytes()
    rows = _reference(context, attestation_raw, adjudication_raw)
    out.mkdir(parents=True)
    (out / "inventory").mkdir()
    snapshots = {"registration.snapshot.json": context["registration_raw"],
        "inventory/manifest.json": context["frozen_manifest"], "inventory/inventory.jsonl": context["frozen_inventory"],
        "returned_a.snapshot.csv": context["raw_a"], "returned_b.snapshot.csv": context["raw_b"],
        "attestation.snapshot.json": attestation_raw, "adjudication.snapshot.csv": adjudication_raw}
    for name, raw in snapshots.items():
        (out / name).write_bytes(raw)
    (out / "reference.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    counts = Counter(row["label"] for row in rows)
    manifest = {"version": VERSION, "status": STATUS, "scope": SCOPE,
        "created_at": datetime.now(timezone.utc).isoformat(), "rows": len(rows),
        "label_counts": {label: counts[label] for label in sorted(review.SPECS["classification"].allowed)},
        "agreements": context["readiness"]["states"]["AGREEMENT"], "manual_adjudications": len(context["disagreements"]),
        "human_labels_generated": 0, "independently_authenticated": False,
        "identity_verification": IDENTITY_LIMIT, "provenance": _provenance(context, attestation_raw, adjudication_raw),
        "helpers_sha256": _helpers(), "files_sha256": {name: review.digest(out / name) for name in SEALED_FILES}}
    _write_json(out / "manifest.json", manifest)
    return manifest


def verify(out, manifest_sha256):
    """Verify an externally anchored seal and replay its human review provenance.

    The separately trusted original registration and inventory must remain
    available. A self-reported hash from inside a modified seal is insufficient.
    This checks integrity and declarations, never a person's identity.
    """
    out = Path(out)
    manifest = _json(review._snapshot(out / "manifest.json", manifest_sha256, "reference manifest"))
    expected_fields = {"version", "status", "scope", "created_at", "rows", "label_counts", "agreements",
        "manual_adjudications", "human_labels_generated", "independently_authenticated", "identity_verification",
        "provenance", "helpers_sha256", "files_sha256"}
    if (not isinstance(manifest, dict) or set(manifest) != expected_fields or manifest["version"] != VERSION
            or manifest["status"] != STATUS or manifest["scope"] != SCOPE
            or type(manifest["human_labels_generated"]) is not int or manifest["human_labels_generated"] != 0
            or manifest["independently_authenticated"] is not False or manifest["identity_verification"] != IDENTITY_LIMIT):
        raise ValueError("Invalid finalized reference manifest or unsupported gold/identity claim.")
    labels = review.SPECS["classification"].allowed
    if (not isinstance(manifest["label_counts"], dict) or set(manifest["label_counts"]) != labels
            or any(type(value) is not int or value < 0 for value in manifest["label_counts"].values())
            or any(type(manifest[key]) is not int or manifest[key] < 0
                   for key in ("rows", "agreements", "manual_adjudications"))):
        raise ValueError("Reference counts must be nonnegative integers with the exact human label classes.")
    if manifest["helpers_sha256"] != _helpers():
        raise ValueError("Registered finalization helpers changed; preserve the version used to seal the reference.")
    if not isinstance(manifest["files_sha256"], dict) or set(manifest["files_sha256"]) != set(SEALED_FILES):
        raise ValueError("Invalid sealed reference file list.")
    raw = {name: review._snapshot(out / name, manifest["files_sha256"][name], "sealed " + name) for name in SEALED_FILES}
    provenance = manifest["provenance"]
    expected_provenance = {"registration_path", "registration_sha256", "registered_inventory", "inventory_manifest_sha256",
                           "inventory_sha256", "returned_a_sha256", "returned_b_sha256", "attestation_sha256", "adjudication_sha256"}
    if not isinstance(provenance, dict) or set(provenance) != expected_provenance:
        raise ValueError("Invalid sealed reference provenance.")
    registration = provenance["registration_path"]
    if not isinstance(registration, str) or not Path(registration).is_absolute():
        raise ValueError("A separately trusted original registration path is required.")
    if review._snapshot(registration, provenance["registration_sha256"], "original registration") != raw["registration.snapshot.json"]:
        raise ValueError("Registration snapshot differs from its original trust anchor.")
    context = _reviews(registration, out / "returned_a.snapshot.csv", out / "returned_b.snapshot.csv")
    if (_provenance(context, raw["attestation.snapshot.json"], raw["adjudication.snapshot.csv"]) != provenance
            or context["frozen_manifest"] != raw["inventory/manifest.json"]
            or context["frozen_inventory"] != raw["inventory/inventory.jsonl"]):
        raise ValueError("Frozen registration/inventory or human-review provenance changed.")
    rows = _reference(context, raw["attestation.snapshot.json"], raw["adjudication.snapshot.csv"])
    stored = [_json(line.encode("utf-8")) for line in raw["reference.jsonl"].decode("utf-8").splitlines() if line.strip()]
    counts = Counter(row["label"] for row in rows)
    if (stored != rows or type(manifest["rows"]) is not int or manifest["rows"] != len(rows)
            or manifest["label_counts"] != {label: counts[label] for label in sorted(review.SPECS["classification"].allowed)}
            or type(manifest["agreements"]) is not int or manifest["agreements"] != context["readiness"]["states"]["AGREEMENT"]
            or type(manifest["manual_adjudications"]) is not int or manifest["manual_adjudications"] != len(context["disagreements"])):
        raise ValueError("Reference labels, mappings, counts, or resolutions do not match the sealed human evidence.")
    return {"verified": True, "status": STATUS, "scope": SCOPE, "rows": len(rows), "labels": rows,
            "label_counts": manifest["label_counts"], "provenance": provenance,
            "inventory_manifest_sha256": provenance["inventory_manifest_sha256"],
            "registration_sha256": provenance["registration_sha256"],
            "inventory_sha256": provenance["inventory_sha256"],
            "identity_verification": IDENTITY_LIMIT, "independently_authenticated": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="action", required=True)
    for action in ("init", "finalize"):
        command = commands.add_parser(action)
        command.add_argument("--registration", type=Path, required=True)
        command.add_argument("--a", type=Path, required=True)
        command.add_argument("--b", type=Path, required=True)
        command.add_argument("--out", type=Path, required=True)
        if action == "finalize":
            command.add_argument("--attestation", type=Path, required=True)
            command.add_argument("--adjudication", type=Path, required=True)
    command = commands.add_parser("verify")
    command.add_argument("--out", type=Path, required=True)
    command.add_argument("--manifest-sha256", required=True)
    args = parser.parse_args()
    try:
        if args.action == "init":
            result = init_review(args.registration, args.a, args.b, args.out)
        elif args.action == "finalize":
            result = finalize(args.registration, args.a, args.b, args.attestation, args.adjudication, args.out)
            result = {**result, "manifest_sha256": review.digest(args.out / "manifest.json")}
        else:
            result = verify(args.out, args.manifest_sha256)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError, TypeError, UnicodeError) as exc:
        parser.exit(2, f"Human reference stopped: {exc}\n")


if __name__ == "__main__":
    main()
