"""Bounded v5/v6.1 engineering pilot on twelve previously authored inputs.

No phishing gold, new SMS inference, URL inference, or RAG is involved. Every
attempt is journaled before sending and is never retried, including on restart.
"""
import argparse
import asyncio
from collections import Counter
import csv
import fcntl
import importlib.metadata
import json
from pathlib import Path
import statistics

import httpx

from app.core.settings import ROOT, Settings
from app.services.llm.client import LLMFailure, normalize_endpoint
from app.services.llm.compact import parse_v61, payload_for as compact_payload
from app.services.llm.policy_v5 import payload_for as control_payload
from evaluation.data.sms import read_jsonl, sha, spreadsheet_cell, write_json, write_jsonl
from evaluation.messages.conversation import CASES
from evaluation.messages.interaction_pilot import (
    FATAL_HTTP, PACKS, checkpoints, collect, now, parse as parse_control,
)
from evaluation.messages.url_context import append, canonical_sha


SCHEMA = "compact-paired-pilot-1.0"
PROFILES = ("message-v5", "message-v6.1")
SEALED = ("execution.json", "requests.jsonl", "attempts.jsonl", "responses.jsonl", "summary.json")


def prepare(out: Path, *, max_tokens=2048):
    if out.exists():
        raise ValueError("Choose a fresh directory; never overwrite registered runs.")
    if type(max_tokens) is not int or not 1 <= max_tokens <= 8192:
        raise ValueError("Invalid token cap.")
    settings = Settings()
    rows = []
    pairs = [(case, history) for case in CASES for history in ("full_history", "last_turn_only")]
    pairs.sort(key=lambda pair: canonical_sha([20261111, pair[0]["id"], pair[1]]))
    for index, (case, history) in enumerate(pairs):
        text = case["text"] if history == "full_history" else case["text"].splitlines()[-1]
        profiles = PROFILES if index % 2 == 0 else tuple(reversed(PROFILES))
        for profile in profiles:
            builder = compact_payload if profile == PROFILES[1] else control_payload
            payload = builder(text=text, urls=[], include_ml=False, sources=[],
                              model=settings.llm_model, max_tokens=max_tokens)[0]
            row = {"key": f"{case['id']}::{history}::{profile}", "case_id": case["id"],
                   "history": history, "profile": profile, "text": text, "payload": payload}
            rows.append({**row, "request_sha256": canonical_sha(row)})
    out.mkdir(parents=True)
    write_jsonl(out / "requests.jsonl", rows)
    # Lock transitive local code as well as the directly used prompt/parser.
    sources = sorted((ROOT / "app").rglob("*.py")) + sorted((ROOT / "evaluation").rglob("*.py"))
    config = {"schema": SCHEMA, "registered_at": now(), "model": settings.llm_model,
        "endpoint": normalize_endpoint(settings.endpoint, settings), "max_tokens": max_tokens,
        "profiles": list(PROFILES), "threads": len(CASES), "unique_inputs": len({r["text"] for r in rows}),
        "max_attempts": len(rows), "workers": 2, "timeout_seconds": 90,
        "recorded_token_stop_budget": 200000, "requests_sha256": sha(out / "requests.jsonl"),
        "schedule": [{"pack": "compact", "key": r["key"], "request_sha256": r["request_sha256"]} for r in rows],
        "source_files_sha256": {str(p.relative_to(ROOT)): sha(p) for p in sources},
        "versions": {name: importlib.metadata.version(name) for name in ("httpx", "pydantic")},
        "selection": "All six existing authored threads; final full history and final last turn. No selection by predictions.",
        "primary_endpoints": ["valid_completed_outputs", "truncations", "schema_and_turn_errors", "recorded_tokens", "latency"],
        "failure_policy": "One attempt per key, durable journal, no retries/JSON repair. Stop on fatal HTTP, three transport errors or recorded token budget.",
        "limitations": "Engineering pilot, six familiar authored threads, twelve unique inputs, no independent semantic gold. "
            "v6.1 emits interaction fields while v5 does not; same cap is not matched output work. "
            "No URL/RAG or fresh/reserve SMS inference. No accuracy/F1 claim."}
    write_json(out / "execution.json", config)
    return config


def load(out):
    config = json.loads((out / "execution.json").read_text())
    if config["schema"] != SCHEMA or config["profiles"] != list(PROFILES):
        raise ValueError("Unsupported protocol.")
    if sha(out / "requests.jsonl") != config["requests_sha256"]:
        raise ValueError("Registered requests changed.")
    for name, expected in config["source_files_sha256"].items():
        if not (ROOT / name).is_file() or sha(ROOT / name) != expected:
            raise ValueError("Registered source changed: " + name)
    rows = read_jsonl(out / "requests.jsonl")
    requests = {}
    for row in rows:
        identity = {k: v for k, v in row.items() if k != "request_sha256"}
        if canonical_sha(identity) != row["request_sha256"] or row["profile"] not in PROFILES:
            raise ValueError("Request identity changed.")
        requests[("compact", row["key"])] = row
    inventory = [{"pack": "compact", "key": r["key"], "request_sha256": r["request_sha256"]} for r in rows]
    if len(requests) != len(rows) or len(rows) != config["max_attempts"] or inventory != config["schedule"]:
        raise ValueError("Schedule differs from registered request inventory.")
    return config, requests


def parse(raw, request):
    if request["profile"] == PROFILES[0]:
        return parse_control(raw, request, PACKS[1])
    if raw.get("transport_error"):
        return {"status": "error", "code": raw["transport_error"]}
    if raw.get("http_status") != 200:
        return {"status": "error", "code": f"HTTP_{raw.get('http_status')}"}
    if raw.get("finish_reason") != "stop":
        return {"status": "error", "code": "OUTPUT_TRUNCATED" if raw.get("finish_reason") == "length" else "RESPONSE_INCOMPLETE"}
    if not raw.get("provider_model"):
        return {"status": "error", "code": "RESPONSE_INVALID"}
    try:
        verdict, warnings, validation = parse_v61(raw.get("content"), request["text"])
        return {"status": "ok", "verdict": verdict.model_dump(), "warnings": warnings, "validation": validation}
    except LLMFailure as exc:
        return {"status": "error", "code": exc.code,
                "diagnostic": "TURN_COUNT" if "vượt phần nội dung" in exc.message else "SCHEMA_OR_CONTENT"}


def summarize(config, requests, records, state):
    groups = {}
    for profile in PROFILES:
        rows = [r for key, r in records.items() if requests[key]["profile"] == profile]
        groups[profile] = {
            "expected": sum(r["profile"] == profile for r in requests.values()), "completed": len(rows),
            "valid": sum(r["parsed"]["status"] == "ok" for r in rows),
            "errors": dict(Counter(r["parsed"]["code"] for r in rows if r["parsed"]["status"] != "ok")),
            "finish_reasons": dict(Counter(r.get("finish_reason") or "missing" for r in rows)),
            "risk_levels": dict(Counter(r["parsed"]["verdict"]["risk_level"] for r in rows if r["parsed"]["status"] == "ok")),
            "usage": {field: sum(r.get("usage", {}).get(field, 0) for r in rows)
                      for field in ("prompt_tokens", "completion_tokens", "total_tokens")},
            "usage_missing": sum("total_tokens" not in r.get("usage", {}) for r in rows),
            "median_elapsed_ms": statistics.median(r["elapsed_ms"] for r in rows) if rows else None,
        }
    pairs = []
    for case_id, history in sorted({(r["case_id"], r["history"]) for r in requests.values()}):
        keys = [("compact", f"{case_id}::{history}::{p}") for p in PROFILES]
        if all(k in records and records[k]["parsed"]["status"] == "ok" for k in keys):
            levels = [records[k]["parsed"]["verdict"]["risk_level"] for k in keys]
            pairs.append({"case_id": case_id, "history": history, "levels": levels, "same_label": levels[0] == levels[1]})
    return {"state": state, "expected": config["max_attempts"], "completed": len(records), "profiles": groups,
        "both_valid_pairs": len(pairs), "different_label_pairs": sum(not p["same_label"] for p in pairs),
        "paired_labels": pairs, "accuracy": None, "F1": None,
        "recorded_total_tokens": sum(r.get("usage", {}).get("total_tokens", 0) for r in records.values()),
        "limitations": config["limitations"]}


def verify(out):
    config, requests = load(out)
    attempts, records = checkpoints(out, config)
    for key, record in records.items():
        if record["started_at"] != attempts[key]["started_at"] or parse(record, requests[key]) != record["parsed"]:
            raise ValueError("Raw response replay or attempt identity differs.")
    seal = out / "result_hashes.json"
    if seal.exists():
        hashes = json.loads(seal.read_text())
        if set(hashes) != set(SEALED) or any(sha(out / name) != value for name, value in hashes.items()):
            raise ValueError("Sealed results changed.")
    elif len(records) == len(requests):
        raise ValueError("Complete results have no seal.")
    if (out / "summary.json").exists():
        stored = json.loads((out / "summary.json").read_text())
        if stored != summarize(config, requests, records, stored["state"]):
            raise ValueError("Summary differs from raw records.")
    return {"verified": True, "attempts": len(attempts), "records": len(records),
            "complete": len(records) == len(requests), "API_calls": 0, "semantic_gold": False}


async def run(out, *, live=False, transport=None):
    config, requests = load(out)
    if not live:
        return {"prepared": True, "max_attempts": config["max_attempts"], "API_calls": 0}
    settings = Settings()
    if not settings.api_key.strip() or any(c in settings.api_key for c in "\r\n"):
        raise ValueError("A valid API key is required.")
    if (normalize_endpoint(settings.endpoint, settings) != config["endpoint"] or settings.llm_model != config["model"]):
        raise ValueError("Provider configuration differs from registration.")
    with (out / ".run.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        verify(out)
        attempts, records = checkpoints(out, config)
        if (out / "result_hashes.json").exists():
            return summarize(config, requests, records, "complete")
        for key, attempt in attempts.items():
            if key not in records:
                row = {**attempt, "content": None, "usage": {}, "elapsed_ms": 0, "transport_error": "INTERRUPTED_REQUEST",
                       "http_status": None, "finish_reason": None, "provider_model": None}
                row["parsed"] = parse(row, requests[key])
                append(out / "responses.jsonl", row)
                records[key] = row
        prior = json.loads((out / "summary.json").read_text()) if (out / "summary.json").exists() else {}
        if prior.get("state") == "stopped_by_gate":
            return summarize(config, requests, records, "stopped_by_gate")
        pending = [r for r in config["schedule"] if (r["pack"], r["key"]) not in attempts]
        state, consecutive_errors = "complete" if not pending else "running", 0
        for record in records.values():
            consecutive_errors = consecutive_errors + 1 if record.get("transport_error") else 0
        async with httpx.AsyncClient(timeout=config["timeout_seconds"], transport=transport, trust_env=False) as client:
            async def request(item):
                key = item["pack"], item["key"]
                attempt = {**item, "started_at": now()}
                append(out / "attempts.jsonl", attempt)
                attempts[key] = attempt
                raw = await collect(client, config=config, key=settings.api_key.strip(), payload=requests[key]["payload"])
                row = {**attempt, **raw, "parsed": parse(raw, requests[key])}
                append(out / "responses.jsonl", row)
                records[key] = row
                return row
            for start in range(0, len(pending), config["workers"]):
                if (any(r.get("http_status") in FATAL_HTTP for r in records.values()) or consecutive_errors >= 3
                        or sum(r["usage"].get("total_tokens", 0) for r in records.values()) >= config["recorded_token_stop_budget"]):
                    state = "stopped_by_gate"
                    break
                batch = await asyncio.gather(*(request(item) for item in pending[start:start + config["workers"]]))
                for row in batch:
                    consecutive_errors = consecutive_errors + 1 if row.get("transport_error") else 0
                state = "complete" if len(records) == len(requests) else "running"
                summary = summarize(config, requests, records, state)
                write_json(out / "summary.json", summary)
                print(json.dumps({"completed": len(records), "expected": len(requests),
                    "errors": sum(r["parsed"]["status"] != "ok" for r in records.values()),
                    "recorded_tokens": summary["recorded_total_tokens"]}), flush=True)
        summary = summarize(config, requests, records, state)
        write_json(out / "summary.json", summary)
        if state == "complete":
            write_json(out / "result_hashes.json", {name: sha(out / name) for name in SEALED})
        return summary


def report(out):
    verified = verify(out)
    config, requests = load(out)
    _, records = checkpoints(out, config)
    summary = json.loads((out / "summary.json").read_text())
    lines = ["# Pilot v5 / v6.1 — kiểm tra kỹ thuật", "", config["limitations"], "",
        "| Profile | Hoàn tất | Hợp lệ | Bị cắt | Token ghi nhận | Trung vị (ms) |",
        "|---|---:|---:|---:|---:|---:|"]
    for profile, values in summary["profiles"].items():
        lines.append(f"| {profile} | {values['completed']}/{values['expected']} | {values['valid']} | "
            f"{values['errors'].get('OUTPUT_TRUNCATED', 0)} | {values['usage']['total_tokens']} | {values['median_elapsed_ms']} |")
    lines += ["", f"Cặp có output hợp lệ ở cả hai: {summary['both_valid_pairs']}; khác nhãn: {summary['different_label_pairs']}.",
        "Không có nhãn ngữ nghĩa độc lập; không tính Accuracy/F1. RAG/URL không nằm trong lượt này.",
        "Mọi lỗi được giữ, không retry hoặc thay JSON. Usage thiếu được báo riêng trong summary."]
    (out / "report.md").write_text("\n".join(lines) + "\n")
    sheet = out / "output_review.csv"
    if not sheet.exists():
        fields = ["blind_id", "input_text", "output_status", "output_json", "risk_reference", "unsupported_claims", "reviewer_id", "notes"]
        with sheet.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for key, record in sorted(records.items(), key=lambda item: canonical_sha(item[0])):
                cells = {"blind_id": "CP-" + canonical_sha(key)[:12], "input_text": requests[key]["text"],
                         "output_status": record["parsed"]["status"], "output_json": record.get("content") or ""}
                writer.writerow({name: spreadsheet_cell(value) for name, value in cells.items()})
    return verified


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "run", "verify", "report"])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if args.command == "prepare":
        config = prepare(args.out, max_tokens=args.max_tokens)
        result = {"prepared": True, "requests": config["max_attempts"], "API_calls": 0}
    elif args.command == "run":
        result = asyncio.run(run(args.out, live=args.live))
    elif args.command == "verify":
        result = verify(args.out)
    else:
        result = report(args.out)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
