"""Compose immutable, hashed source snapshots; retain the original documents unchanged."""
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def assemble(snapshots, catalogs, out, catalog_out):
    if out.exists() or catalog_out.exists():
        raise ValueError("Choose fresh corpus and catalog paths.")
    if len(snapshots) != len(catalogs):
        raise ValueError("Each input snapshot needs its catalog.")
    docs, sources, parents = [], [], []
    for snapshot, catalog_path in zip(snapshots, catalogs):
        manifest = json.loads((snapshot / "manifest.json").read_text())
        for name, expected in manifest["files"].items():
            if sha(snapshot / name) != expected:
                raise ValueError("Input snapshot hash mismatch: " + name)
        if sha(catalog_path) != manifest["catalog_sha256"]:
            raise ValueError("Input catalog changed after collection.")
        batch = [json.loads(line) for line in (snapshot / "documents.jsonl").read_text().splitlines() if line]
        docs.extend(batch)
        accepted_ids = {d["id"] for d in batch}
        sources.extend(s for s in json.loads(catalog_path.read_text())["sources"] if s["id"] in accepted_ids)
        parents.append({"snapshot": str(snapshot), "manifest_sha256": sha(snapshot / "manifest.json"),
                        "documents_sha256": sha(snapshot / "documents.jsonl")})
    for field in ("id", "source_url", "source_text_sha256", "summary_sha256"):
        if len({d[field] for d in docs}) != len(docs):
            raise ValueError("Duplicate across input snapshots: " + field)
    if {d["id"] for d in docs} != {s["id"] for s in sources} or len(sources) != len(docs):
        raise ValueError("Catalog/source IDs do not agree.")
    # Inline canonical notes so the resulting catalog has no location-dependent references.
    by_id = {d["id"]: d for d in docs}
    for s in sources:
        s.pop("notes_ref", None)
        s.update(summary=by_id[s["id"]]["text"], context_note=by_id[s["id"]]["context_note"])
    version = out.name
    catalog = {"version": version, "language": "vi", "require_all_sources": True, "sources": sources}
    catalog_out.parent.mkdir(parents=True, exist_ok=True)
    write(catalog_out, catalog)
    out.mkdir(parents=True)
    (out / "documents.jsonl").write_text("".join(json.dumps(d, ensure_ascii=False) + "\n" for d in docs), encoding="utf-8")
    with (out / "sources.csv").open("w", encoding="utf-8-sig", newline="") as f:
        fields = ["id", "title", "publisher", "kind", "topics", "published_at", "date_status", "source_url", "resolved_url"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for d in docs:
            writer.writerow({k: ";".join(d[k]) if k == "topics" else d[k] for k in fields})
    write(out / "collection_report.json", {"snapshot": version, "documents": len(docs), "parents": parents,
        "inherited_without_refresh": len([json.loads(l) for l in (snapshots[0] / 'documents.jsonl').read_text().splitlines() if l]),
        "by_kind": dict(Counter(d["kind"] for d in docs)), "publishers": len({d["publisher"] for d in docs}),
        "review_status": "assistant_curated_not_independent_expert_review", "full_source_articles_redistributed": False})
    write(out / "manifest.json", {"snapshot": version, "catalog_sha256": sha(catalog_out),
        "expanded_catalog_sha256": hashlib.sha256(json.dumps(catalog, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
        "parents": parents, "assembler_sha256": sha(__file__), "collected_at": datetime.now(timezone.utc).isoformat(),
        "files": {n: sha(out / n) for n in ("documents.jsonl", "sources.csv", "collection_report.json")}})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, action="append", required=True)
    parser.add_argument("--catalog", type=Path, action="append", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--catalog-out", type=Path, required=True)
    args = parser.parse_args()
    assemble(args.snapshot, args.catalog, args.out, args.catalog_out)


if __name__ == "__main__":
    main()
