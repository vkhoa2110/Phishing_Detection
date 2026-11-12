"""Derive development-only inputs and provisional AI labels; never infer reserve."""
import argparse
import asyncio
from collections import Counter
import csv
import json
from pathlib import Path

from app.core.privacy import redact
from app.core.settings import ROOT, Settings
from app.services.rag.explanation import _load_strict_json
from evaluation.common import registered
from evaluation.data.prelabel import PROMPT, parse_annotations
from evaluation.data.sms import FIELDS, read_jsonl, sha, spreadsheet_cell, write_json, write_jsonl
from evaluation.messages.url_context import canonical_sha


def prepare(source, out):
    source, out = Path(source).resolve(), Path(out).resolve()
    manifest = json.loads((source / "manifest.json").read_text())
    for name, expected in manifest["files_sha256"].items():
        if sha(source / name) != expected:
            raise ValueError("Frozen fresh source changed: " + name)
    if out.exists():
        raise ValueError("Choose a fresh development pack.")
    items = read_jsonl(source / "items.jsonl")
    dev = [r for r in items if r["split"] == "development_review"]
    reserve = [r for r in items if r["split"] == "reserve_review"]
    if len(dev) != 80 or len(reserve) != 120:
        raise ValueError("Expected the frozen 80/120 split.")
    for key in ("group_id", "domains"):
        values = lambda rows: {v for r in rows for v in (r[key] if key == "domains" else [r[key]])}
        if values(dev) & values(reserve):
            raise ValueError("Development and reserve overlap.")
    cases = [{"id": r["id"], "text": redact(r["text"])[0], "group_id": r["group_id"],
              "dataset": "sms", "split": "dev"} for r in dev]
    stress = [{"id": r["id"], "text": redact(r["text"])[0], "group_id": r["family"],
               "dataset": "authored", "split": "dev", "url_is_illustrative": True}
              for r in read_jsonl(source / "authored_stress.jsonl")]
    if len(stress) != 40 or len({r["id"] for r in cases + stress}) != 120:
        raise ValueError("Unexpected authored inventory.")
    out.mkdir(parents=True)
    write_jsonl(out / "sms.jsonl", cases)
    write_jsonl(out / "authored.jsonl", stress)
    write_jsonl(out / "authored_design.jsonl", read_jsonl(source / "authored_design_references.jsonl"))
    for side in ("a", "b"):
        with (out / f"human_{side}.csv").open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            for row in sorted(cases, key=lambda r: canonical_sha([side, r["id"]])):
                writer.writerow({"id": row["id"], "text": spreadsheet_cell(row["text"])})
    write_json(out / "manifest.json", {"status": "development_only_not_gold", "source": str(source),
        "source_manifest_sha256": sha(source / "manifest.json"), "source_items_sha256": sha(source / "items.jsonl"),
        "reserve_ids_sha256": canonical_sha(sorted(r["id"] for r in reserve)), "reserve_count": len(reserve),
        "reserve_inference": False, "source_sampling_labels_used_for_phishing": False,
        "files": {name: sha(out / name) for name in ("sms.jsonl", "authored.jsonl", "authored_design.jsonl")}})
    return {"sms": len(cases), "authored": len(stress), "reserve_inference": 0}


def cases(pack):
    pack = Path(pack)
    manifest = json.loads((pack / "manifest.json").read_text())
    for name, expected in manifest["files"].items():
        if sha(pack / name) != expected:
            raise ValueError("Development pack changed.")
    return read_jsonl(pack / "sms.jsonl"), read_jsonl(pack / "authored.jsonl")


def prepare_labels(pack, out):
    sms, _ = cases(pack)
    ordered = sorted(sms, key=lambda r: canonical_sha([20261111, r["id"]]))
    rows = []
    for i in range(0, len(ordered), 4):
        messages = [{"id": r["id"], "text": r["text"]} for r in ordered[i:i + 4]]
        rows.append({"key": f"labels-{i // 4:03}", "messages": messages, "payload": {
            "model": Settings().llm_model, "messages": [{"role": "system", "content": PROMPT},
            {"role": "user", "content": json.dumps({"messages": messages}, ensure_ascii=False)}],
            "temperature": .1, "top_p": 1, "top_k": 40, "max_tokens": 8192, "stream": False}})
    return registered.register(out, rows, stage="fresh_ai_labels", locks=[Path(pack) / "manifest.json", Path(pack) / "sms.jsonl"],
        metadata={"pack": str(Path(pack).resolve()), "independent_gold": False,
                  "judge_same_provider_as_classifier": True, "reserve_inference": False}, token_budget=300000)


def parse_labels(raw, request):
    data = _load_strict_json(raw)
    labels = parse_annotations(json.dumps(data, ensure_ascii=False), request["messages"])
    return {"status": "ok", "annotations": labels}


def export_labels(out):
    out = Path(out)
    verified = registered.verify(out, parse_labels)
    if not verified["complete"]:
        raise ValueError("Finish the registered annotation inventory before freezing labels.")
    config, _ = registered.load(out)
    _, records = registered.checkpoints(out, config)
    labels = {r["id"]: r for row in records.values() if row["parsed"]["status"] == "ok"
              for r in row["parsed"]["annotations"]}
    sms, _ = cases(config["metadata"]["pack"])
    output = []
    for row in sms:
        a = labels.get(row["id"])
        output.append({"id": row["id"], "label": None if a is None or a["label"] == "UNKNOWN" else int(a["label"]),
            "annotation_available": a is not None, "annotation_status": "ai_preliminary", "human_reviewed": False,
            "judge_model": config["model"], "evidence_quote": a["evidence_quote"] if a else "",
            "notes": a["notes"] if a else "Không có phản hồi gán nhãn hợp lệ.",
            "category": a["category"] if a else "insufficient_context"})
    write_jsonl(out / "labels.jsonl", output)
    fields = ["id", "text", "label", "category", "evidence_quote", "notes", "annotation_status"]
    by_id = {r["id"]: r for r in sms}
    review = out / "ai_review.csv"
    if not review.exists():
        with review.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader()
            for row in output:
                values = {k: row.get(k, "") for k in fields}
                values.update(text=by_id[row["id"]]["text"], label="UNKNOWN" if row["label"] is None else row["label"])
                writer.writerow({k: spreadsheet_cell(v) if isinstance(v, str) else v for k, v in values.items()})
    write_json(out / "labels_manifest.json", {"status": "ai_preliminary_not_gold", "human_reviewed": False,
        "label_file_sha256": sha(out / "labels.jsonl"), "execution_sha256": sha(out / "execution.json"),
        "counts": dict(Counter("UNKNOWN" if r["label"] is None else str(r["label"]) for r in output)),
        "annotation_unavailable": sum(not r["annotation_available"] for r in output),
        "limitations": "Same-provider AI reference, not independent truth; never equate agreement with real-world accuracy."})
    return json.loads((out / "labels_manifest.json").read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "prepare-labels", "label", "export-labels"])
    parser.add_argument("--source", type=Path, default=ROOT / "data/annotation/fresh_messages_v1")
    parser.add_argument("--pack", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if args.command == "prepare": result = prepare(args.source, args.out)
    elif args.command == "prepare-labels": result = prepare_labels(args.pack, args.out)
    elif args.command == "label": result = asyncio.run(registered.run(args.out, parse_labels, live=args.live))
    else: result = export_labels(args.out)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
