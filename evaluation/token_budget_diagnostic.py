"""Revisit truncated calls with more tokens; never replace the primary run.

This is a failure-selected diagnostic, not another population-level benchmark.
"""
import argparse
import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import time

import httpx

from app.llm_service import LLMFailure, LLMService
from app.settings import ROOT, Settings
from .ablation import ARMS, call_arm
from .metrics import prediction
from .run import FATAL_CODES, digest, level, load_checkpoints, prepare_manifest, write_json


async def evaluate(args):
    original = Path(args.run)
    original_manifest = json.loads((original / "manifest.json").read_text())
    original_summary = json.loads((original / "summary.json").read_text())
    if original_summary["run_state"]["stop_reason"] != "all_calls_completed":
        raise ValueError("Complete the primary run before selecting diagnostic cases.")
    config = original_manifest["configuration"]
    settings = replace(Settings(), max_tokens=args.max_tokens, timeout_seconds=90)
    if (settings.llm_model != config["llm"]["model"] or settings.endpoint != config["llm"]["endpoint"]
            or args.max_tokens <= config["llm"]["max_tokens"]):
        raise ValueError("Keep model/endpoint unchanged and increase the token budget.")
    for path, expected in config["source_sha256"].items():
        if digest(ROOT / path) != expected:
            raise ValueError("Primary source code has changed: " + path)
    rows = [json.loads(s) for s in (original / "results.jsonl").read_text().splitlines()]
    selected = [(r, a) for r in rows for a in ARMS if r[a].get("code") == "OUTPUT_TRUNCATED"]
    if len(selected) > args.max_new_calls:
        raise ValueError("Diagnostic call budget is smaller than selected calls.")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    prepare_manifest(out, {"primary_manifest_sha256": digest(original / "manifest.json"),
        "primary_checkpoints_sha256": digest(original / "checkpoints.jsonl"),
        "diagnostic_source_sha256": digest(__file__), "max_tokens": args.max_tokens,
        "timeout_seconds": 90, "selection": [{"case_id": r["id"], "arm": a} for r, a in selected],
        "purpose": "failure-selected token-budget diagnostic; primary metrics remain unchanged"})
    cache = load_checkpoints(out / "checkpoints.jsonl")
    keys = {(r["id"], a) for r, a in selected}
    if not cache.keys() <= keys:
        raise ValueError("Unknown diagnostic checkpoint.")
    if args.live:
        async with httpx.AsyncClient(timeout=settings.timeout_seconds, trust_env=False) as client:
            service = LLMService(settings, client)
            # Small, sequential diagnostic; no automatic retry.
            for r, a in selected:
                key = (r["id"], a)
                if key in cache:
                    continue
                started = time.perf_counter()
                try:
                    result = await call_arm(service, r, r, a, config.get("prompt_profile", "legacy"))
                except LLMFailure as exc:
                    result = {"status": "error", "code": exc.code, "message": exc.message,
                              "elapsed_ms": round(1000 * (time.perf_counter() - started), 1)}
                except Exception as exc:
                    result = {"status": "error", "code": "UNEXPECTED_" + type(exc).__name__,
                              "elapsed_ms": round(1000 * (time.perf_counter() - started), 1)}
                cache[key] = result
                with (out / "checkpoints.jsonl").open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"case_id": r["id"], "arm": a, "result": result}, ensure_ascii=False) + "\n")
                    f.flush()
                    os.fsync(f.fileno())
                print(f"{r['id']} {a}: {result['status']} {level(result)}", flush=True)
                if result.get("code") in FATAL_CODES:
                    break
    result_rows = [{"case_id": r["id"], "label": r["label"], "arm": a,
                    "original": r[a], "diagnostic": cache.get((r["id"], a), {"status": "pending"})}
                   for r, a in selected]
    summary = {"selected_calls": len(selected), "attempted": len(cache), "max_tokens": args.max_tokens,
        "recovered": sum(r["diagnostic"]["status"] == "ok" for r in result_rows),
        "correct_in_selected_cases": sum(prediction(level(r["diagnostic"])) == r["label"] for r in result_rows),
        "usage": {k: sum(v.get("usage", {}).get(k, 0) for v in cache.values())
                  for k in ("prompt_tokens", "completion_tokens", "total_tokens")},
        "limitations": "Only primary-run truncation failures selected after observing outcomes. Not an estimate of accuracy at the larger budget; do not merge into primary metrics."}
    write_json(out / "results.json", result_rows)
    write_json(out / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, default=ROOT / "artifacts/evaluations/rag_ablation_v1")
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts/evaluations/rag_budget_diagnostic_v1")
    parser.add_argument("--max-tokens", type=int, default=8192)
    parser.add_argument("--max-new-calls", type=int, default=10)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    try:
        summary = asyncio.run(evaluate(args))
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Diagnostic stopped: {exc}\n")
    if args.live and summary["attempted"] != summary["selected_calls"]:
        parser.exit(1, "Diagnostic incomplete; inspect summary and resume unchanged.\n")
