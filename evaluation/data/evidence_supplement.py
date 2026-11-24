"""Freeze a source-backed supplement without inference or human-gold claims.

This additive builder leaves the older challenge protocol unchanged. Public
warning excerpts are partial documented examples, never received specimens.
Only the short, attributed excerpt is quoted; source briefs also contain an
assistant paraphrase. Reviewers receive opaque IDs and blank human columns.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import json
from pathlib import Path

from app.core.settings import ROOT
from evaluation.data import evidence_messages as legacy
from evaluation.data import human_review
from evaluation.data.sms import normal, read_jsonl, sha, write_json, write_jsonl

VERSION = "evidence-supplement-pack-2.0"
PROTOCOL_VERSION = "evidence-supplement-collection-2.0"
SEED = 20261121
CHANNELS = {"SMS", "EMAIL", "UNKNOWN"}
ORIGINS = {"documented_excerpt", "documented_template", "reconstructed", "paraphrased", "self_authored"}
PUBLIC_ORIGINS = {"documented_excerpt", "documented_template"}
LABEL_NAMES = {1: "PHISHING", 0: "BENIGN", None: "INSUFFICIENT"}
REVIEW_FIELDS = ("sample_id", "text_redacted", "human_label", "evidence_basis", "reviewer_id", "notes")
FROZEN_HELPERS = (
    "evaluation/data/evidence_supplement.py", "evaluation/data/evidence_messages.py",
    "evaluation/data/human_review.py", "evaluation/data/sms.py", "app/core/privacy.py",
    "app/services/url/intake.py", "app/services/url/parsing.py", "app/services/url/authority.py",
    "app/services/url/domain_reference.py", "app/services/url/resources/iana_tlds.txt",
)


def load_protocol(path):
    """Accept the pre-existing collection plan; never infer targets from cases."""
    protocol = json.loads(Path(path).read_text(encoding="utf-8"))
    if (protocol.get("version") != PROTOCOL_VERSION or protocol.get("seed") != SEED
            or protocol.get("dev_fraction") != .6):
        raise ValueError("Unexpected registered supplement version, seed, or split fraction.")
    targets = protocol.get("base_targets", {})
    if set(targets) != set(LABEL_NAMES.values()):
        raise ValueError("Register targets for PHISHING, BENIGN, and INSUFFICIENT.")
    for target in targets.values():
        if set(target) != {"with_URL", "without_URL"} or any(type(v) is not int or v < 0 for v in target.values()):
            raise ValueError("Base targets must be nonnegative integer URL-stratum counts.")
    channels = protocol.get("channel_target", {})
    if set(channels) != {"SMS", "EMAIL"} or any(type(v) is not int or v < 0 for v in channels.values()):
        raise ValueError("Register nonnegative SMS and EMAIL collection targets.")
    for key in ("paired_injection_target", "public_specimen_or_template_target"):
        if type(protocol.get(key)) is not int or protocol[key] < 0:
            raise ValueError("Register nonnegative integer supplemental targets.")
    for key in ("new_sources_to_RAG", "old_holdout_or_reserve_inference", "model_training"):
        if protocol.get(key) is not False:
            raise ValueError("This builder does not add RAG documents, run holdout, or train.")
    for key in ("provider_calls", "human_labels_generated"):
        if type(protocol.get(key)) is not int or protocol[key] != 0:
            raise ValueError("The collection protocol must declare zero inference and human-label generation.")
    return protocol


def validate_sources(rows, *, base=ROOT):
    sources = legacy.validate_sources(rows, base=base)
    for source in sources.values():
        if source.get("snapshot_kind") != "short_excerpt_and_paraphrase" or source.get("verification_agent") != "assistant":
            raise ValueError("Explicit assistant-verified short-excerpt source briefs are required.")
        channels = source.get("documented_channels")
        if (not isinstance(channels, list) or len(set(channels)) != len(channels)
                or any(channel not in {"SMS", "EMAIL"} for channel in channels)):
            raise ValueError("Source documented_channels must explicitly list SMS/EMAIL or be empty.")
    return sources


def validate_cases(rows, sources):
    """Add explicit channel/excerpt gates, then reuse the frozen URL provenance checks."""
    prepared, originals = [], {}
    for original in rows:
        row = dict(original)
        key = row.get("id")
        if not isinstance(key, str) or not key or key in originals:
            raise ValueError("Unique nonempty case IDs are required.")
        origin = row.get("text_origin")
        if origin not in ORIGINS:
            raise ValueError("Public examples must be documented excerpts/templates, not claimed received specimens.")
        channel, basis = row.get("channel"), row.get("channel_basis_kind")
        if channel not in CHANNELS:
            raise ValueError("Every case must declare SMS, EMAIL, or UNKNOWN channel.")
        if channel == "UNKNOWN":
            if basis != "unknown":
                raise ValueError("UNKNOWN channel requires an unknown channel basis.")
        elif basis == "source_explicit":
            if not any(channel in sources.get(s, {}).get("documented_channels", []) for s in row.get("source_ids", [])):
                raise ValueError("A source-explicit channel must be documented by a cited source.")
        elif basis != "author_assigned" or origin in PUBLIC_ORIGINS:
            raise ValueError("Authored channel assignment cannot establish the channel of a public excerpt/template.")
        if origin in PUBLIC_ORIGINS:
            quote = row.get("source_message_quote", "")
            # All copied message text must be inside the one <=25-word source
            # excerpt, so multiple cases cannot silently multiply quote budgets.
            if not quote or not any(normal(quote) in normal(sources[s]["evidence_excerpt"])
                                    for s in row.get("source_ids", []) if s in sources):
                raise ValueError("A public message quote must be inside its source's short attributed excerpt.")
            if origin == "documented_excerpt" and row.get("message_completeness") != "excerpt":
                raise ValueError("A documented excerpt must explicitly declare partial message completeness.")
        if origin == "documented_excerpt":
            row["text_origin"] = "documented_template"
        originals[key] = original
        prepared.append(row)
    validated = legacy.validate_cases(prepared, sources)
    by_id = {row["id"]: row for row in validated}
    for row in validated:
        row["text_origin"] = originals[row["id"]]["text_origin"]
        if row.get("base_id") and (row["base_id"] == row["id"] or by_id[row["base_id"]].get("base_id")):
            raise ValueError("An injection variant must reference a different, non-variant base case.")
    return validated


def counts(rows, protocol):
    base = [row for row in rows if not row.get("base_id")]
    variants = [row for row in rows if row.get("base_id")]
    strata = Counter((row["channel"], LABEL_NAMES[row["label"]], bool(row["urls"]), row["text_origin"])
                     for row in rows)
    base_strata = {label: {url: sum(LABEL_NAMES[row["label"]] == label and bool(row["urls"]) == (url == "with_URL")
                                   for row in base) for url in ("with_URL", "without_URL")}
                   for label in LABEL_NAMES.values()}
    quotas = []
    for label, targets in protocol["base_targets"].items():
        for url, target in targets.items():
            actual = base_strata[label][url]
            quotas.append({"kind": "base", "label": label, "URL_group": url, "target": target,
                           "actual": actual, "shortfall": max(0, target - actual)})
    for channel, target in protocol["channel_target"].items():
        actual = sum(row["channel"] == channel for row in base)
        quotas.append({"kind": "base_channel", "channel": channel, "target": target,
                       "actual": actual, "shortfall": max(0, target - actual)})
    public = sum(row["text_origin"] in PUBLIC_ORIGINS for row in base)
    for kind, actual, target in (("paired_injection", len(variants), protocol["paired_injection_target"]),
                                  ("public_excerpt_or_template", public, protocol["public_specimen_or_template_target"])):
        quotas.append({"kind": kind, "target": target, "actual": actual, "shortfall": max(0, target - actual)})
    return {"total_cases": len(rows), "base_cases": len(base), "injection_variants": len(variants),
            "base_label_URL_counts": base_strata,
            "by_channel_label_URL_origin": [{"channel": channel, "label": label, "has_URL": url,
                    "text_origin": origin, "count": value}
                for (channel, label, url, origin), value in sorted(strata.items())],
            "quotas": quotas, "human_confirmed_cases": 0, "received_original_messages": 0,
            "reference_status": legacy.REFERENCE_STATUS,
            "note": "Quotas concern purposive scenario-design references, not human phishing labels or population prevalence."}


def _materialize(sources_path, cases_path, protocol_path, corpus_paths):
    # Persist one path identity in overlap observations both at creation and
    # verification, which reloads resolved paths from the manifest.
    corpus_paths = tuple(Path(path).resolve() for path in corpus_paths)
    protocol = load_protocol(protocol_path)
    sources = validate_sources(read_jsonl(sources_path))
    cases = validate_cases(read_jsonl(cases_path), sources)
    assigned, edges = legacy.assign_splits(cases, seed=protocol["seed"])
    rows = sorted(({**row, "split": "holdout" if row["split"] == "test" else "dev"} for row in assigned),
                  key=lambda row: legacy.digest([SEED, "supplement_input_order", row["id"]]))
    return protocol, sources, rows, edges, legacy.corpus_overlap(sources, corpus_paths)


def _readiness(rows):
    return {"independent_gold_ready": False, "human_reviewed": False, "human_labels_generated": 0,
            "provider_calls": 0, "model_training": False, "old_holdout_or_reserve_read": False,
            "heldout_model_inference": False, "sources_added_to_RAG": False,
            "test_status": "locked_author_exposed_holdout_not_independent_blind",
            "splits": {split: {"cases": len(selected := [r for r in rows if r["split"] == split]),
                                "base_cases": sum(not r.get("base_id") for r in selected),
                                "components": len({r["group_id"] for r in selected}),
                                "scenario_labels": dict(Counter(LABEL_NAMES[r["label"]] for r in selected)),
                                "behavior_references": dict(Counter(LABEL_NAMES[r["behavior_label"]] for r in selected))}
                       for split in ("dev", "holdout")},
            "limits": ["Assistant design references are not human gold.",
                       "Public excerpts can omit decisive context; keep INSUFFICIENT when needed.",
                       "No current destination-site safety or received-message authenticity is verified.",
                       "This builder does not read old message reserves; a separate privacy-preserving overlap audit is required.",
                       "No automatic selection of examples, prompts, or models by prediction outcomes."]}


def prepare(sources_path, cases_path, protocol_path, out, *, corpus_paths=()):
    out = Path(out)
    if out.exists():
        raise ValueError("Choose fresh output; preserve existing sources, splits, and human sheets.")
    protocol, sources, rows, edges, overlap = _materialize(sources_path, cases_path, protocol_path, corpus_paths)
    out.mkdir(parents=True)
    write_jsonl(out / "cases.jsonl", rows)
    write_jsonl(out / "leakage_edges.jsonl", edges)
    write_json(out / "counts.json", counts(rows, protocol))
    write_json(out / "readiness.json", _readiness(rows))
    write_json(out / "corpus_overlap.json", overlap)
    for split in ("dev", "holdout"):
        write_jsonl(out / (split + "_inputs.jsonl"), [{"id": r["id"], "text": r["text"]} for r in rows if r["split"] == split])
    review_source = out / "review_inputs_blank.csv"
    mapping = []
    with review_source.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        for row in rows:
            blind_id = "RV-" + legacy.digest([SEED, "supplement_blind_review", row["id"]])[:24]
            writer.writerow({"sample_id": blind_id, "text_redacted": row["text"]})
            mapping.append({"sample_id": blind_id, "case_id": row["id"]})
    write_jsonl(out / "review_ID_key_OPERATOR_ONLY.jsonl", mapping)
    review = human_review.freeze("classification", review_source, out / "human_review", sha(review_source),
                                registration=out / "human_review.registration.json")
    locks = [Path(sources_path), Path(cases_path), Path(protocol_path), *map(Path, corpus_paths)]
    locks += [ROOT / helper for helper in FROZEN_HELPERS]
    locks += [Path(source["snapshot_path"]) for source in sources.values()]
    manifest = {"version": VERSION, "created_at": datetime.now(timezone.utc).isoformat(),
                "sources_path": str(Path(sources_path).resolve()), "cases_path": str(Path(cases_path).resolve()),
                "protocol_path": str(Path(protocol_path).resolve()), "corpus_paths": [str(Path(p).resolve()) for p in corpus_paths],
                "source_count": len(sources), "case_count": len(rows), "components": len({r["group_id"] for r in rows}),
                "seed": SEED, "dev_fraction": .6, "human_reviewed": False,
                "reference_status": legacy.REFERENCE_STATUS, "human_labels_generated": 0, "provider_calls": 0,
                "review_packet": review, "quote_budget_words_per_source": {key: len(source["evidence_excerpt"].split()) for key, source in sources.items()},
                "input_files_sha256": {str(p.resolve()): sha(p) for p in locks},
                "files_sha256": {str(p.relative_to(out)): sha(p) for p in sorted(out.rglob("*")) if p.is_file()},
                "split_method": "Fixed-seed connected source/alias/domain/campaign/template/Jaccard>=.75/lineage components; dev<.6; no reroll",
                "old_holdout_or_reserve_read": False, "sources_added_to_RAG": False,
                "manifest_anchor_note": "Keep this manifest SHA-256 independently to detect replacement of the whole pack."}
    write_json(out / "manifest.json", manifest)
    return manifest


def verify(out, *, manifest_sha256=None):
    out = Path(out)
    if manifest_sha256 is not None and sha(out / "manifest.json") != manifest_sha256:
        raise ValueError("Frozen supplement manifest differs from its external SHA-256 anchor.")
    config = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    if (config.get("version") != VERSION or config.get("human_reviewed") is not False
            or config.get("reference_status") != legacy.REFERENCE_STATUS
            or type(config.get("human_labels_generated")) is not int or config["human_labels_generated"] != 0
            or type(config.get("provider_calls")) is not int or config["provider_calls"] != 0
            or config.get("seed") != SEED or config.get("dev_fraction") != .6
            or config.get("old_holdout_or_reserve_read") is not False or config.get("sources_added_to_RAG") is not False):
        raise ValueError("Unexpected supplement pack or gold claim.")
    for path, expected in config["input_files_sha256"].items():
        if sha(path) != expected:
            raise ValueError("Frozen source/case/protocol/helper changed: " + path)
    for name, expected in config["files_sha256"].items():
        if sha(out / name) != expected:
            raise ValueError("Frozen supplement output changed: " + name)
    protocol, sources, rows, edges, overlap = _materialize(config["sources_path"], config["cases_path"], config["protocol_path"], config["corpus_paths"])
    if (config.get("case_count") != len(rows) or config.get("source_count") != len(sources)
            or config.get("components") != len({row["group_id"] for row in rows})
            or config.get("quote_budget_words_per_source") != {key: len(source["evidence_excerpt"].split()) for key, source in sources.items()}):
        raise ValueError("Frozen inventory sizes or per-source quote budgets differ.")
    expected = {"cases.jsonl": rows, "leakage_edges.jsonl": edges, "counts.json": counts(rows, protocol),
                "readiness.json": _readiness(rows), "corpus_overlap.json": overlap}
    for name, value in expected.items():
        actual = read_jsonl(out / name) if name.endswith(".jsonl") else json.loads((out / name).read_text(encoding="utf-8"))
        if actual != value:
            raise ValueError("Recomputed supplement provenance, grouping, or counts differ: " + name)
    registration = human_review.registered_inventory(out / "human_review.registration.json")
    human_review.load_inventory(*registration)
    return {"verified": True, "cases": len(rows), "sources": len(sources),
            "human_gold": False, "human_labels_generated": 0, "provider_calls": 0,
            "manifest_sha256": sha(out / "manifest.json"), "externally_anchored": manifest_sha256 is not None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "verify"))
    parser.add_argument("--sources", type=Path)
    parser.add_argument("--cases", type=Path)
    parser.add_argument("--protocol", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, action="append", default=[])
    parser.add_argument("--manifest-sha256")
    args = parser.parse_args()
    if args.command == "prepare":
        if any(path is None for path in (args.sources, args.cases, args.protocol)):
            parser.error("prepare requires --sources, --cases, and the pre-existing --protocol")
        result = prepare(args.sources, args.cases, args.protocol, args.out, corpus_paths=args.corpus)
    else:
        result = verify(args.out, manifest_sha256=args.manifest_sha256)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
