"""Prepare and validate a claim-level audit of editorial RAG summaries."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import unicodedata


ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "data/knowledge/corpus_v2/documents.jsonl"
RAW_DIRS = [ROOT / "data/raw/rag_v2_final_review", ROOT / "data/raw/rag_v2_source_review_checked"]
JUDGMENTS = {"supported", "overgeneralized", "contradicted", "source_unavailable"}
FIELDS = ["claim_id", "document_id", "source_url", "summary_claim", "source_file",
          "source_excerpt", "judgment", "reviewer_id", "reviewed_at", "notes"]
SCHEMA = "rag-summary-audit-v1-1.1"


def normalized(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_text_sha(path: Path) -> str:
    """Use the same normalized-text identity as the corpus collector."""
    text = normalized(path.read_text())
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def documents() -> list[dict]:
    rows = [json.loads(line) for line in CORPUS.read_text().splitlines() if line.strip()]
    if len(rows) != 37 or len({row["id"] for row in rows}) != len(rows):
        raise ValueError("Expected the locked 37-document corpus v2.")
    return rows


def source_file(document_id: str) -> Path | None:
    for folder in RAW_DIRS:
        candidate = folder / f"{document_id}.txt"
        if candidate.exists():
            return candidate
    return None


def claims(text: str) -> list[str]:
    values = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part.strip()]
    return values or [text.strip()]


def prepare(out: Path) -> dict:
    if out.exists():
        raise ValueError("Choose a new output directory; review sheets are versioned.")
    out.mkdir(parents=True)
    rows, inventory = [], []
    for document in documents():
        path = source_file(document["id"])
        if path is not None and source_text_sha(path) != document["source_text_sha256"]:
            raise ValueError("Raw source hash differs: " + document["id"])
        inventory.append({"document_id": document["id"], "raw_source_available": path is not None,
                          "source_file": str(path.relative_to(ROOT)) if path else "",
                          "source_text_sha256": document["source_text_sha256"]})
        for index, claim in enumerate(claims(document["text"]), 1):
            rows.append({"claim_id": f"{document['id']}-C{index:02d}", "document_id": document["id"],
                         "source_url": document["source_url"], "summary_claim": claim,
                         "source_file": str(path.relative_to(ROOT)) if path else "",
                         "source_excerpt": "", "judgment": "", "reviewer_id": "",
                         "reviewed_at": "", "notes": ""})
    with (out / "claims.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader(); writer.writerows(rows)
    protocol = {
        "schema": SCHEMA, "created_at": datetime.now(timezone.utc).isoformat(),
        "corpus": str(CORPUS.relative_to(ROOT)), "corpus_sha256": sha(CORPUS),
        "documents": len(inventory), "claims": len(rows),
        "raw_source_available": sum(item["raw_source_available"] for item in inventory),
        "inventory": inventory, "allowed_judgments": sorted(JUDGMENTS),
        "completion_rule": "Every claim needs a judgment, reviewer_id and rationale/excerpt; source_unavailable needs notes.",
        "review_status": "blank_human_review_sheet; no AI or source labels are promoted to gold",
    }
    (out / "protocol.json").write_text(json.dumps(protocol, ensure_ascii=False, indent=2) + "\n")
    (out / "README.md").write_text(
        "# Claim-level RAG summary audit\n\n"
        "Review each editorial claim against the saved publisher text. Fill `source_excerpt`, `judgment`, "
        "`reviewer_id`, `reviewed_at` and `notes`. A matching quote supports only the claim and scope it states. "
        "Do not infer that a publisher article authenticates a message, sender or URL. Documents without local "
        "source text remain `source_unavailable` until evidence is collected; do not copy the summary as evidence.\n"
    )
    return protocol


def validate(sheet: Path) -> dict:
    protocol = json.loads((sheet.parent / "protocol.json").read_text())
    if protocol.get("schema") != SCHEMA or protocol.get("corpus_sha256") != sha(CORPUS):
        raise ValueError("Review must bind the current corpus and audit protocol; regenerate legacy packs.")
    docs = {doc["id"]: doc for doc in documents()}
    inventory = protocol["inventory"]
    if (len(inventory) != len(docs)
            or {item["document_id"] for item in inventory} != set(docs)):
        raise ValueError("Source inventory differs from the locked corpus.")
    source_texts, locked_paths = {}, {}
    for item in inventory:
        identifier = item["document_id"]
        if item["source_text_sha256"] != docs[identifier]["source_text_sha256"]:
            raise ValueError("Source identity differs from corpus.")
        path = item["source_file"]
        if bool(path) != item["raw_source_available"]:
            raise ValueError("Inconsistent source availability.")
        locked_paths[identifier] = path
        if path:
            absolute = (ROOT / path).resolve()
            if not absolute.is_relative_to(ROOT.resolve()):
                raise ValueError("Source snapshot must be inside the project.")
            if source_text_sha(absolute) != item["source_text_sha256"]:
                raise ValueError("Source snapshot differs from locked hash.")
            source_texts[identifier] = normalized(absolute.read_text())
    expected = {}
    for identifier, doc in docs.items():
        for index, claim in enumerate(claims(doc["text"]), 1):
            expected[f"{identifier}-C{index:02d}"] = {
                "document_id": identifier, "source_url": doc["source_url"],
                "summary_claim": claim, "source_file": locked_paths[identifier],
            }
    with sheet.open(newline="") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        fields = reader.fieldnames
    if not rows or fields != FIELDS:
        raise ValueError("Unexpected review schema.")
    if len(rows) != len(expected) or {row["claim_id"] for row in rows} != set(expected):
        raise ValueError("Review must contain every locked claim exactly once, with no unknown IDs.")
    counts = {key: 0 for key in sorted(JUDGMENTS)}
    incomplete = 0
    for row in rows:
        if any(row[key] != value for key, value in expected[row["claim_id"]].items()):
            raise ValueError("Immutable claim/source fields were changed.")
        judgment = row["judgment"].strip()
        if not judgment:
            incomplete += 1
            if any(row[field].strip() for field in ("reviewer_id", "source_excerpt", "reviewed_at")):
                raise ValueError("Incomplete rows cannot carry reviewer attribution or excerpts.")
            continue
        if judgment not in JUDGMENTS or not row["reviewer_id"].strip() or not row["reviewed_at"].strip():
            raise ValueError("Completed review rows require a valid judgment, reviewer and time.")
        try:
            reviewed = datetime.fromisoformat(row["reviewed_at"].replace("Z", "+00:00"))
            if reviewed.tzinfo is None or reviewed.utcoffset() is None:
                raise ValueError("Missing timezone.")
        except ValueError as exc:
            raise ValueError("Review time must be an ISO datetime with timezone.") from exc
        if judgment == "source_unavailable":
            if not row["notes"].strip() or row["source_excerpt"].strip():
                raise ValueError("source_unavailable requires notes and no fabricated excerpt.")
            if row["document_id"] in source_texts:
                raise ValueError("A locked source snapshot is available for this claim.")
        elif not row["source_excerpt"].strip():
            raise ValueError("Semantic judgments require a source excerpt.")
        elif (row["document_id"] not in source_texts
              or normalized(row["source_excerpt"]) not in source_texts[row["document_id"]]):
            raise ValueError("Excerpt must occur in the bound publisher snapshot.")
        counts[judgment] += 1
    return {"rows": len(rows), "completed": len(rows) - incomplete, "incomplete": incomplete,
            "counts": counts, "human_review_complete": incomplete == 0,
            "review_form_complete": incomplete == 0,
            "source_evidence_complete": incomplete == 0 and counts["source_unavailable"] == 0,
            "reviewer_identity_verified": False, "semantic_support_verified_by_code": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["prepare", "validate"])
    parser.add_argument("--out", type=Path)
    parser.add_argument("--sheet", type=Path)
    args = parser.parse_args()
    result = prepare(args.out) if args.command == "prepare" else validate(args.sheet)
    print(json.dumps(result, ensure_ascii=False, indent=2))
