"""Blind double annotation, adjudication, and immutable benchmark export.

Rater identities are declarations supplied by the reviewers, not independently
authenticated by this CLI. Never synthesize human reviews or infer gold labels
from upstream spam labels or model predictions.
"""
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import json
from pathlib import Path

from app.settings import ROOT
from .message_data import FIELDS, read_jsonl, sha, spreadsheet_cell, write_json, write_jsonl

LABELS = {"0", "1", "UNKNOWN"}
CATEGORIES = {"credential_theft", "payment_scam", "impersonation", "unsolicited_advertising",
              "legitimate_workflow", "educational_quote", "routine", "insufficient_context", "other"}


class ReviewPending(ValueError):
    pass


def workspace_items(workspace):
    workspace = Path(workspace)
    manifest = json.loads((workspace / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("source_labels_are_gold") is not False:
        raise ValueError("Upstream labels must not be treated as phishing gold.")
    for name, expected in manifest["files"].items():
        if name not in {"items.jsonl", "source_labels.jsonl", "audit.json"} or sha(workspace / name) != expected:
            raise ValueError("Annotation selection was modified.")
    items = read_jsonl(workspace / "items.jsonl")
    if len({i["id"] for i in items}) != len(items):
        raise ValueError("Duplicate review IDs.")
    assert_split_isolation(items)
    return items, manifest


def assert_split_isolation(items):
    if any(i["split"] not in {"dev", "test"} for i in items):
        raise ValueError("Unknown split.")
    if len({i["text"].casefold() for i in items}) != len(items):
        raise ValueError("Duplicate text across review items.")
    for key in ("group_id", "domains"):
        def members(split):
            return {v for i in items if i["split"] == split
                    for v in (i[key] if key == "domains" else [i[key]])}
        if members("dev") & members("test"):
            raise ValueError("Cross-split " + key + " leakage.")


def read_sheet(path, items):
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not set(FIELDS) <= set(reader.fieldnames or []):
            raise ValueError("Review sheet has missing columns.")
        rows = list(reader)
    by_id = {r["id"]: r for r in rows}
    if len(by_id) != len(rows) or set(by_id) != {i["id"] for i in items}:
        raise ValueError("Review IDs are duplicate, missing, or unexpected.")
    pending, identities = [], set()
    for item in items:
        r = by_id[item["id"]]
        if r["text"] not in {item["text"], spreadsheet_cell(item["text"])}:
            raise ValueError("Reviewers must not edit message text: " + item["id"])
        r.update({k: (v or "").strip() for k, v in r.items() if k != "text"})
        if not r["label"] or not r["rater_id"] or not r["notes"] or not r["category"]:
            pending.append(item["id"])
            continue
        if r["label"] not in LABELS or r["category"] not in CATEGORIES:
            raise ValueError("Invalid label/category: " + item["id"])
        if r["label"] == "1" and not r["evidence_quote"]:
            raise ValueError("Positive label requires a verbatim action quote: " + item["id"])
        if r["evidence_quote"] and r["evidence_quote"] not in item["text"]:
            raise ValueError("Evidence quote is not in the message: " + item["id"])
        identities.add(r["rater_id"])
    if pending:
        raise ReviewPending(f"{Path(path).name}: {len(pending)} bản ghi chưa hoàn tất; ví dụ {', '.join(pending[:3])}.")
    if len(identities) != 1:
        raise ValueError("Each sheet requires one consistent rater_id.")
    return by_id, next(iter(identities))


def agreement(a, b):
    n = len(a)
    same = sum(a[k]["label"] == b[k]["label"] for k in a)
    ca, cb = Counter(r["label"] for r in a.values()), Counter(r["label"] for r in b.values())
    expected = sum(ca[label] * cb[label] for label in LABELS) / n**2 if n else 0
    observed = same / n if n else 0
    return {"n": n, "label_agreements": same, "label_disagreements": n - same,
            "raw_agreement": observed, "cohen_kappa_three_labels": (observed - expected) / (1 - expected) if expected < 1 else None,
            "labels": sorted(LABELS), "rater_a_counts": dict(ca), "rater_b_counts": dict(cb)}


def load_reviews(workspace):
    workspace = Path(workspace)
    items, manifest = workspace_items(workspace)
    a, rater_a = read_sheet(workspace / "annotator_a.csv", items)
    b, rater_b = read_sheet(workspace / "annotator_b.csv", items)
    if rater_a == rater_b:
        raise ValueError("Independent sheets require two distinct declared rater IDs.")
    return items, manifest, a, b, [rater_a, rater_b]


def prepare_adjudication(workspace):
    items, _, a, b, raters = load_reviews(workspace)
    path = Path(workspace) / "adjudication.csv"
    if path.exists():
        raise ValueError("Adjudication sheet already exists; never overwrite a review.")
    fields = FIELDS + ["rater_a_label", "rater_b_label", "rater_a_notes", "rater_b_notes"]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for i in items:
            key = i["id"]
            if a[key]["label"] != b[key]["label"]:
                writer.writerow({"id": key, "text": spreadsheet_cell(i["text"]),
                    "rater_a_label": a[key]["label"], "rater_b_label": b[key]["label"],
                    "rater_a_notes": spreadsheet_cell(a[key]["notes"]), "rater_b_notes": spreadsheet_cell(b[key]["notes"])})
    return {**agreement(a, b), "rater_ids": raters, "adjudication_sheet": str(path)}


def finalize(workspace, out):
    workspace, out = Path(workspace), Path(out)
    if out.exists():
        raise ValueError("Gold output already exists; use a new version to preserve locked test data.")
    items, selection, a, b, raters = load_reviews(workspace)
    differences = [i for i in items if a[i["id"]]["label"] != b[i["id"]]["label"]]
    resolutions, adjudicator = {}, None
    if differences:
        if not (workspace / "adjudication.csv").exists():
            raise ReviewPending("Label disagreements need an adjudication sheet and reviewer.")
        resolutions, adjudicator = read_sheet(workspace / "adjudication.csv", differences)
        if adjudicator in raters:
            raise ValueError("Adjudication must be performed by a third declared reviewer.")
    gold = []
    for i in items:
        key = i["id"]
        resolved = resolutions.get(key)
        decision = resolved or a[key]
        label = None if decision["label"] == "UNKNOWN" else int(decision["label"])
        category = decision["category"] if resolved or a[key]["category"] == b[key]["category"] else "mixed_annotation"
        gold.append({**i, "label": label, "reference_level": "UNKNOWN" if label is None else "ALARM" if label else "LOW",
            "category": category, "rationale": decision["notes"] if resolved else a[key]["notes"] + " / " + b[key]["notes"],
            "annotation_status": "adjudicated" if resolved else "two_rater_consensus",
            "rater_ids": raters + ([adjudicator] if resolved else []),
            "evidence_quotes": [decision["evidence_quote"]] if resolved else [a[key]["evidence_quote"], b[key]["evidence_quote"]],
            "source_url": selection["source_url"], "source_revision": selection["source_revision"],
            "source_kind": "external_sms_authors_report_real_not_independently_verified"})
    assert_split_isolation(gold)
    out.mkdir(parents=True)
    for split in ("dev", "test"):
        write_jsonl(out / (split + ".jsonl"), [i for i in gold if i["split"] == split and i["label"] is not None])
        write_jsonl(out / (split + "_unknown.jsonl"), [i for i in gold if i["split"] == split and i["label"] is None])
    agreement_data = {**agreement(a, b), "rater_ids": raters, "adjudicator_id": adjudicator,
                      "identity_verification": "declared IDs only; CLI does not authenticate human identity"}
    write_json(out / "agreement.json", agreement_data)
    files = {p.name: sha(p) for p in sorted(out.iterdir()) if p.is_file()}
    manifest = {"version": "vn-sms-gold-2.0", "status": "reviewed_frozen",
        "created_at": datetime.now(timezone.utc).isoformat(), "rater_ids": raters,
        "selection_manifest_sha256": sha(workspace / "manifest.json"), "source_revision": selection["source_revision"],
        "upstream_labels_used_as_gold": False, "split_policy": selection["grouping"],
        "source_url": selection["source_url"], "source_license": selection["source_license"],
        "annotation_sha256": {name: sha(workspace / name) for name in ("annotator_a.csv", "annotator_b.csv", "adjudication.csv") if (workspace / name).exists()},
        "identity_verification": agreement_data["identity_verification"],
        "counts": {split: dict(Counter("UNKNOWN" if i["label"] is None else str(i["label"]) for i in gold if i["split"] == split)) for split in ("dev", "test")},
        "files": files, "unknown_policy": "Retain in separate challenge files; never convert UNKNOWN to benign or include as binary gold."}
    write_json(out / "manifest.json", manifest)
    return manifest


def validate_gold(manifest_path, dataset):
    """Fail before API calls if labels are unreviewed, changed, or leaking splits."""
    manifest_path, dataset = Path(manifest_path).resolve(), Path(dataset).resolve()
    config = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (config.get("status") != "reviewed_frozen" or config.get("upstream_labels_used_as_gold") is not False
            or len(set(config.get("rater_ids", []))) < 2):
        raise ValueError("A frozen, double-reviewed phishing gold manifest is required.")
    if dataset.parent != manifest_path.parent or dataset.name not in {"dev.jsonl", "test.jsonl"}:
        raise ValueError("Select dev.jsonl or test.jsonl beside the gold manifest.")
    allowed = {"dev.jsonl", "test.jsonl", "dev_unknown.jsonl", "test_unknown.jsonl", "agreement.json"}
    if set(config["files"]) != allowed:
        raise ValueError("Unexpected gold files.")
    for name, expected in config["files"].items():
        if sha(manifest_path.parent / name) != expected:
            raise ValueError("Frozen benchmark file was modified: " + name)
    all_rows = [i for name in allowed if name.endswith(".jsonl") for i in read_jsonl(manifest_path.parent / name)]
    assert_split_isolation(all_rows)
    if len({i["id"] for i in all_rows}) != len(all_rows):
        raise ValueError("Duplicate benchmark IDs.")
    for i in all_rows:
        if i.get("annotation_status") not in {"adjudicated", "two_rater_consensus"} or set(config["rater_ids"]) - set(i.get("rater_ids", [])):
            raise ValueError("Incomplete annotation provenance.")
    chosen = read_jsonl(dataset)
    if any(type(i.get("label")) is not int or i["label"] not in (0, 1) for i in chosen):
        raise ValueError("Binary benchmark contains non-binary gold labels.")
    if {i["label"] for i in chosen} != {0, 1}:
        raise ValueError("Both classes are needed for the binary comparison.")
    return {"manifest_sha256": sha(manifest_path), "dataset_sha256": sha(dataset), "split": dataset.stem,
            "rater_ids": config["rater_ids"], "status": config["status"], "counts": config["counts"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "adjudicate", "finalize"))
    parser.add_argument("--workspace", type=Path, default=ROOT / "data/annotation/vn_sms_v2")
    parser.add_argument("--out", type=Path, default=ROOT / "data/evaluation/vn_sms_v2")
    args = parser.parse_args()
    try:
        if args.action == "status":
            items, _, a, b, raters = load_reviews(args.workspace)
            result = {**agreement(a, b), "rater_ids": raters}
        elif args.action == "adjudicate":
            result = prepare_adjudication(args.workspace)
        else:
            result = finalize(args.workspace, args.out)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except ReviewPending as exc:
        print(json.dumps({"status": "awaiting_human_review", "message": str(exc)}, ensure_ascii=False))
        parser.exit(2)
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(2, f"Review stopped: {exc}\n")


if __name__ == "__main__":
    main()
