"""Validate and freeze an editorially reviewed source collection, without network access."""
import argparse
from collections import Counter
import csv
from datetime import date, datetime, timezone
import importlib.util
import json
from pathlib import Path
import re

spec = importlib.util.spec_from_file_location("rag_collector", Path(__file__).with_name("collect_rag_sources.py"))
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)
ROOT = Path(__file__).resolve().parents[2]


def validate(corpus, catalog_path):
    catalog = collector.load_catalog(catalog_path)
    sources = {s["id"]: s for s in catalog["sources"]}
    documents = [json.loads(line) for line in (corpus / "documents.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    if not 20 <= len(documents) <= 100:
        raise ValueError("Small reviewed corpus must contain 20–100 documents.")
    if catalog.get("require_all_sources") and {d["id"] for d in documents} != set(sources):
        raise ValueError("Catalog and snapshot must contain exactly the same source IDs.")
    manifest_path = corpus / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for name, expected in manifest["files"].items():
        if collector.sha((corpus / name).read_bytes()) != expected:
            raise ValueError("Snapshot file hash mismatch: " + name)
    for field in ("id", "source_text_sha256", "summary_sha256"):
        if len({d[field] for d in documents}) != len(documents):
            raise ValueError("Duplicate " + field)
    for d in documents:
        collector.validate_url(d["source_url"])
        collector.validate_url(d["resolved_url"])
        source = sources[d["id"]]
        if d["source_url"] != source["url"] or d["text"] != source["summary"] or d["context_note"] != source["context_note"]:
            raise ValueError("Catalog and reviewed note disagree: " + d["id"])
        if not d["text"].strip() or len(d["text"].split()) > 150:
            raise ValueError("Empty or excessive summary.")
        if collector.sha(d["text"]) != d["summary_sha256"] or not all(re.fullmatch(r"[a-f0-9]{64}", d[f]) for f in ("html_sha256", "source_text_sha256")):
            raise ValueError("Source/summary hash invalid: " + d["id"])
        if d["http_status"] != 200 or d["content_kind"] != "editorial_summary_not_verbatim":
            raise ValueError("Unverified source or incorrectly declared content type.")
        if d["published_at"] is not None:
            date.fromisoformat(d["published_at"])
            if d["date_status"] in ("not_available", "future_date_rejected"):
                raise ValueError("Publication-date provenance is inconsistent.")
    if sum(d["kind"] == "legitimate_workflow" for d in documents) < 6:
        raise ValueError("Include guidance for legitimate workflows, not only scam warnings.")
    # Freeze the final curator-reviewed content separately from the original HTTP collection phase.
    manifest.setdefault("collection_phase", {k: manifest[k] for k in ("catalog_sha256", "expanded_catalog_sha256", "files")})
    manifest["catalog_sha256"] = collector.sha(catalog_path.read_bytes())
    manifest["expanded_catalog_sha256"] = collector.sha(json.dumps(catalog, ensure_ascii=False, sort_keys=True))
    manifest.setdefault("curation_completed_at", datetime.now(timezone.utc).isoformat())
    manifest["curation_validator_sha256"] = collector.sha(Path(__file__).read_bytes())
    manifest["curation_scope"] = "Source relevance, note fidelity, duplicate control and metadata; not independent expert approval."
    manifest["files"] = {name: collector.sha((corpus / name).read_bytes()) for name in manifest["files"]}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = {"documents": len(documents), "by_kind": dict(Counter(d["kind"] for d in documents)),
              "publishers": len({d["publisher"] for d in documents}),
              "known_publication_dates": sum(d["published_at"] is not None for d in documents),
              "unknown_publication_dates": [d["id"] for d in documents if d["published_at"] is None],
              "all_source_ids_unique": True, "all_source_text_hashes_unique": True,
              "catalog_notes_consistent": True, "snapshot_files_hash_verified": True,
              "content_kind": "editorial_summary_not_verbatim", "indexed": False}
    (corpus / "validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path, nargs="?", default=ROOT / "data/knowledge/corpus_v1")
    parser.add_argument("--catalog", type=Path, default=ROOT / "data/knowledge/source_catalog.json")
    args = parser.parse_args()
    validate(args.corpus, args.catalog)


if __name__ == "__main__":
    main()
