"""Explicitly repair unavailable AI annotations with smaller batches in a new run.

The original run is read-only. Valid annotations (including genuine UNKNOWN)
are never retried or selected by label. Human review CSVs are never populated.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

from app.privacy import redact
from app.settings import ROOT, Settings
from .message_data import annotation_sheet, read_jsonl, sha, write_json, write_jsonl
from .prelabel import PROMPT, export, generate
from .review import workspace_items


async def repair(args, settings=None, transport=None):
    settings = settings or Settings()
    items, _ = workspace_items(args.workspace)
    base_manifest = json.loads((args.base / "manifest.json").read_text())
    if base_manifest.get("status") != "ai_preliminary":
        raise ValueError("Only a completed AI prelabel export can be repaired.")
    for name, expected in base_manifest["files"].items():
        if sha(args.base / name) != expected: raise ValueError("Base run was changed.")
    original_config = base_manifest["configuration"]
    if (settings.llm_model != original_config["model"]
            or hashlib.sha256(PROMPT.encode()).hexdigest() != original_config["prompt_sha256"]):
        raise ValueError("Repair must use the same annotator model/prompt.")
    if original_config["selection_sha256"] != sha(args.workspace / "items.jsonl"):
        raise ValueError("Base and workspace selections differ.")
    base_rows = read_jsonl(args.base / "labels.jsonl")
    missing = {r["id"] for r in base_rows if not r["annotation_available"]}
    if len(base_rows) != len(items) or {r["id"] for r in base_rows} != {i["id"] for i in items}:
        raise ValueError("Base labels do not cover source selection.")
    if not missing: raise ValueError("All annotations are already available; nothing to retry.")
    selected = [i for i in items if i["id"] in missing]
    args.out.mkdir(parents=True, exist_ok=True)
    local_workspace = args.out / "repair_workspace"
    provenance = {"base_manifest_sha256": sha(args.base / "manifest.json"),
        "original_workspace_manifest_sha256": sha(args.workspace / "manifest.json"),
        "repair_ids": sorted(missing), "selection_reason": "Missing/invalid provider response only; never based on predicted label."}
    if local_workspace.exists():
        if json.loads((local_workspace / "audit.json").read_text()) != provenance:
            raise ValueError("Repair provenance changed; choose a new output.")
    else:
        local_workspace.mkdir()
        write_jsonl(local_workspace / "items.jsonl", selected)
        write_jsonl(local_workspace / "source_labels.jsonl", [])
        write_json(local_workspace / "audit.json", provenance)
        write_json(local_workspace / "manifest.json", {"source_labels_are_gold": False,
            "status": "ai_repair_selection_not_human_gold",
            "files": {n: sha(local_workspace / n) for n in ("items.jsonl", "source_labels.jsonl", "audit.json")}})
        for name in ("annotator_a.csv", "annotator_b.csv"):
            annotation_sheet(local_workspace / name, selected)
    options = SimpleNamespace(workspace=local_workspace, out=args.out / "repair_run", live=args.live,
        batch_size=getattr(args, "batch_size", 4), max_tokens=16384, timeout=120, max_new_calls=args.max_new_calls, seed=20261028)
    result = await generate(options, settings, transport)
    # Keep successful original records exactly, including low confidence and UNKNOWN.
    repair_config = json.loads((options.out / "configuration.json").read_text())
    if repair_config["model"] != original_config["model"] or repair_config["prompt_sha256"] != original_config["prompt_sha256"]:
        raise ValueError("Repair must use the same annotator model/prompt.")
    checkpoints, source_files = {}, {}
    for prefix, directory in (("base", args.base / "batches"), ("repair", options.out / "batches")):
        for p in sorted(directory.glob("*.json")):
            key = prefix + "_" + p.stem
            checkpoints[key] = json.loads(p.read_text())
            source_files[key] = p
    config = {**original_config, "derivation": provenance, "repair_runner_sha256": sha(__file__),
        "repair_manifest_sha256": sha(options.out / "manifest.json"),
        "repair_max_tokens": 16384, "repair_batch_size": options.batch_size,
        "request_budget_note": "Original and repair calls recorded separately; base failures remain in audit."}
    merged = args.out / "merged"; merged.mkdir(exist_ok=True)
    archive = merged / "batches"; archive.mkdir(exist_ok=True)
    for key, source in source_files.items():
        shutil.copyfile(source, archive / (key + ".json"))
    messages = [{"id": i["id"], "text": redact(i["text"])[0]} for i in items]
    final = export(merged, items, messages, checkpoints, config)
    merged_rows = {r["id"]: r for r in read_jsonl(merged / "labels.jsonl")}
    for old in base_rows:
        if old["annotation_available"] and merged_rows[old["id"]] != old:
            raise ValueError("Repair unexpectedly changed an available annotation.")
    write_json(merged / "repair_verification.json", {"base_available_records_preserved": True,
        "retried_unavailable_items": len(missing), "total_items": len(items),
        "valid_annotations": final["valid_annotations"], "human_gold": False})
    return final


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=ROOT / "artifacts/annotations/vn_sms_ai_v1")
    parser.add_argument("--workspace", type=Path, default=ROOT / "data/annotation/vn_sms_v2")
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts/annotations/vn_sms_ai_repair_v1")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--max-new-calls", type=int, default=50)
    parser.add_argument("--batch-size", type=int, choices=(1, 2, 4), default=4)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(repair(args)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
