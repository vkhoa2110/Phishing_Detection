"""Paired production-schema v3/v4 dev pilot; no test or label changes."""
import argparse
import asyncio
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import random

import httpx

from app.message_service import call_message, payload_for
from app.settings import ROOT, Settings
from app.llm_service import normalize_endpoint
from .component_ablation import load_cases
from .message_data import read_jsonl, sha, write_json, write_jsonl
from .metrics import measure, paired_comparison
from .url_context_run import FATAL, append, canonical_sha

ARMS = ("message-v3", "message-v4")
SEED = 20261104


def select_cases():
    rows = load_cases(ROOT / "data/annotation/objective_v1", ROOT / "data/annotation/url_context_v1")
    sms = [r for r in rows if r["dataset"] == "sms"]
    context = [r for r in rows if r["dataset"] == "url_context"]
    chosen = set()
    for label in (0, 1):
        pool = {r["url_id"] for r in context if r["targets"]["url_risk"] == label}
        chosen.update(sorted(pool, key=lambda value: canonical_sha([SEED, "quality-regression", value]))[:4])
    cases = sms + [c for c in context if c["url_id"] in chosen]
    if len(cases) != 120:
        raise ValueError("Expected 80 SMS + five contexts of eight domains.")
    return cases


def configuration(settings, cases):
    files = [ROOT / name for name in ("evaluation/quality_pilot.py", "app/message_service.py", "app/llm_service.py",
        "app/verdict_validation.py", "app/schemas.py", "app/settings.py", "app/urls.py", "app/privacy.py", "evaluation/metrics.py",
        "evaluation/component_ablation.py", "evaluation/message_data.py", "evaluation/url_context_run.py")]
    return {"version": "quality-pilot-1.0", "model": settings.llm_model,
        "endpoint": normalize_endpoint(settings.endpoint, settings), "cases": len(cases), "arms": list(ARMS),
        "max_calls": len(cases) * 2, "max_tokens": 8192, "timeout": 90, "workers": 2, "seed": SEED,
        "cases_sha256": canonical_sha(cases), "source_hashes": {str(p): sha(p) for p in files},
        "intervention": "Only system fraud-decision rules change. Same production MessageVerdict schema, structural validator, text, model and decoding. No ML/RAG supplied to either arm.",
        "selection": "All 80 dev SMS; four domains per source label drawn by hash before inference, all five context variants retained. No prediction-based selection.",
        "gates": {"sms_fpr_reduction_pp": 10, "sms_fpr_alternative_max": .15,
            "sms_min_recall": 8/9, "sms_max_additional_missed_positives": 1,
            "min_coverage": .90, "max_coverage_drop_pp": 5, "context_max_f1_drop_pp": 5,
            "context_min_recall": .9375, "educational_max_additional_false_alarms": 0},
        "limits": "Dev-selected candidate, single generation, AI SMS references and authored contexts; not independent gold or proof of generalization.",
        "failure_policy": "One attempt; errors retained. Interrupted journal entries are errors, not resent. Stop on fatal HTTP or three consecutive errors.",
        "test_inference": False}


def level(record):
    return record["verdict"]["risk_level"] if record["status"] == "ok" else "UNKNOWN"


def score(cases, records):
    lookup = {(r["id"], r["arm"]): r for r in records}
    expected = {(c["id"], a) for c in cases for a in ARMS}
    if len(lookup) != len(records) or not lookup.keys() <= expected:
        raise ValueError("Duplicate/unexpected predictions.")
    result = {"metrics_ready": set(lookup) == expected, "completed": len(records), "expected": len(expected),
        "metrics": None, "paired": None, "gates": None,
        "errors": {a: dict(Counter(r.get("code") for r in records if r["arm"] == a and r["status"] == "error")) for a in ARMS},
        "status_counts": {a: dict(Counter(r["status"] for r in records if r["arm"] == a)) for a in ARMS},
        "usage": {a: {k: sum(r.get("usage", {}).get(k, 0) for r in records if r["arm"] == a)
                      for k in ("prompt_tokens", "completion_tokens", "total_tokens")} for a in ARMS}}
    if not result["metrics_ready"]:
        return result
    result["metrics"], result["paired"] = {}, {}
    for dataset in ("sms", "url_context"):
        rows = [c for c in cases if c["dataset"] == dataset]
        binary = [c for c in rows if c["targets"]["message_behavior"] is not None]
        unknown = [c for c in rows if c["targets"]["message_behavior"] is None]
        labels = [c["targets"]["message_behavior"] for c in binary]
        result["metrics"][dataset] = {a: {**measure(labels, [level(lookup[(c["id"], a)]) for c in binary]),
            "reference_unknown": dict(Counter(level(lookup[(c["id"], a)]) for c in unknown))} for a in ARMS}
        result["paired"][dataset] = paired_comparison(labels, *[[level(lookup[(c["id"], a)]) for c in binary] for a in ARMS])
    educational = [c for c in cases if c["dataset"] == "url_context" and c["variant"].startswith("education")]
    edu_fp = {a: sum(level(lookup[(c["id"], a)]) in {"HIGH", "WARNING"} for c in educational) for a in ARMS}
    s3, s4 = (result["metrics"]["sms"][a] for a in ARMS)
    c3, c4 = (result["metrics"]["url_context"][a] for a in ARMS)
    checks = {"sms_false_alarm_improved": s3["false_positive_rate"] - s4["false_positive_rate"] >= .10 - 1e-12 or s4["false_positive_rate"] <= .15,
        "sms_recall_preserved": s4["recall"] >= 8/9 - 1e-12 and s3["tp"] - s4["tp"] <= 1,
        "sms_coverage_preserved": s4["coverage"] >= .9 and s3["coverage"] - s4["coverage"] <= .05 + 1e-12,
        "context_f1_preserved": c4["f1"] >= c3["f1"] - .05 - 1e-12,
        "context_recall_preserved": c4["recall"] >= .9375,
        "context_coverage_preserved": c4["coverage"] >= .9 and c3["coverage"] - c4["coverage"] <= .05 + 1e-12,
        "educational_false_alarms_not_increased": edu_fp[ARMS[1]] <= edu_fp[ARMS[0]]}
    result["gates"] = {"checks": checks, "passed": all(checks.values()), "educational_fp": edu_fp,
        "meaning": "Development acceptance only, conditional on provisional references; not independent-test certification."}
    return result


async def evaluate(args):
    settings = replace(Settings(), max_tokens=8192, timeout_seconds=90)
    cases = select_cases()
    config = configuration(settings, cases)
    out = args.out
    if args.live and (not settings.api_key.strip() or any(c in settings.api_key for c in "\r\n")):
        raise ValueError("API credentials unavailable.")
    if out.exists():
        if not (out / "execution.json").exists() or json.loads((out / "execution.json").read_text())["configuration"] != config:
            raise ValueError("Registration changed; use a new directory.")
    else:
        out.mkdir(parents=True)
    with (out / ".run.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not (out / "execution.json").exists():
            write_json(out / "execution.json", {"registered_at": datetime.now(timezone.utc).isoformat(), "configuration": config})
            write_jsonl(out / "cases.jsonl", cases)
        if read_jsonl(out / "cases.jsonl") != cases:
            raise ValueError("Cases modified.")
        rp, ap = out / "predictions.jsonl", out / "attempts.jsonl"
        records = read_jsonl(rp) if rp.exists() else []
        attempts = read_jsonl(ap) if ap.exists() else []
        expected = {(c["id"], a) for c in cases for a in ARMS}
        seen = {(r["id"], r["arm"]) for r in records}
        journal = {(a["id"], a["arm"]) for a in attempts}
        if len(seen) != len(records) or len(journal) != len(attempts) or not seen <= journal <= expected:
            raise ValueError("Invalid checkpoint/journal.")
        for a in attempts:
            key = a["id"], a["arm"]
            if key not in seen:
                r = {"id": a["id"], "arm": a["arm"], "status": "error", "code": "INTERRUPTED_REQUEST", "usage": {}}
                append(rp, r); records.append(r); seen.add(key)
        state = {"live": args.live, "new_calls": 0, "stop_reason": None if args.live else "offline_prepared"}
        def export():
            write_json(out / "summary.json", {**score(cases, records), "state": state})
        export()
        if not args.live:
            print(json.dumps({"cases": len(cases), "planned_calls": len(expected), "API_calls": 0}), flush=True)
            return
        ordered = list(cases)
        random.Random(SEED).shuffle(ordered)
        queue = asyncio.Queue()
        for i, c in enumerate(ordered):
            for arm in ARMS if i % 2 else tuple(reversed(ARMS)):
                if (c["id"], arm) not in seen:
                    queue.put_nowait((c, arm))
        errors = 0
        async with httpx.AsyncClient(timeout=90, trust_env=False) as client:
            async def worker():
                nonlocal errors
                while not queue.empty() and state["stop_reason"] is None:
                    c, arm = queue.get_nowait()
                    payload, _ = payload_for(text=c["text"], urls=[], include_ml=False, sources=[], model=config["model"], max_tokens=8192, profile=arm)
                    a = {"id": c["id"], "arm": arm, "payload_sha256": canonical_sha(payload), "started_at": datetime.now(timezone.utc).isoformat()}
                    append(ap, a); attempts.append(a); state["new_calls"] += 1
                    result = await call_message(client, endpoint=config["endpoint"], api_key=settings.api_key.strip(), payload=payload,
                                                text=c["text"], sources=[], timeout=90)
                    result.update(id=c["id"], arm=arm, payload_sha256=a["payload_sha256"])
                    append(rp, result); records.append(result); seen.add((c["id"], arm))
                    errors = errors + 1 if result["status"] == "error" else 0
                    if result.get("code") in FATAL or errors >= 3:
                        state["stop_reason"] = result.get("code") if result.get("code") in FATAL else "three_consecutive_errors"
                    if len(records) % 10 == 0 or state["stop_reason"]:
                        export(); print(json.dumps({"completed": len(records), "planned": len(expected), "errors": sum(r["status"] == "error" for r in records)}), flush=True)
            try:
                await asyncio.gather(*(worker() for _ in range(2)))
            finally:
                state["stop_reason"] = state["stop_reason"] or ("all_calls_completed" if len(records) == len(expected) else "interrupted")
                export()
        print(json.dumps({"out": str(out), "state": state}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    try:
        asyncio.run(evaluate(args))
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(2, f"Quality pilot stopped: {exc}\n")


if __name__ == "__main__":
    main()
