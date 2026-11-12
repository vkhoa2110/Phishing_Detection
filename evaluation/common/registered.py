"""Once-only registered provider runs, preserving raw responses and failed attempts."""
import asyncio
from collections import Counter
import fcntl
import json
from pathlib import Path

import httpx

from app.core.settings import ROOT, Settings
from app.services.llm.client import normalize_endpoint
from evaluation.data.sms import read_jsonl, sha, write_json, write_jsonl
from evaluation.messages.interaction_pilot import FATAL_HTTP, checkpoints, collect, now
from evaluation.messages.url_context import append, canonical_sha

SEALED = ("execution.json", "requests.jsonl", "attempts.jsonl", "responses.jsonl", "summary.json")


def register(out, rows, *, stage, metadata=None, locks=(), max_tokens=8192, token_budget=1500000):
    out = Path(out)
    if out.exists():
        raise ValueError("Choose a fresh output directory.")
    if not rows or len({r["key"] for r in rows}) != len(rows):
        raise ValueError("Nonempty unique requests are required.")
    settings = Settings()
    for row in rows:
        if row["payload"]["model"] != settings.llm_model or row["payload"]["max_tokens"] != max_tokens:
            raise ValueError("Payload differs from registered model/budget.")
    rows = [{**r, "request_sha256": canonical_sha(r)} for r in rows]
    sources = sorted((ROOT / "app").rglob("*.py")) + sorted((ROOT / "evaluation").rglob("*.py"))
    inputs = sorted({Path(p).resolve() for p in locks})
    config = {"schema": "registered-provider-1.0", "stage": stage, "registered_at": now(),
        "model": settings.llm_model, "endpoint": normalize_endpoint(settings.endpoint, settings),
        "max_tokens": max_tokens, "workers": 2, "timeout_seconds": 90,
        "max_attempts": len(rows), "recorded_token_stop_budget": token_budget,
        "schedule": [{"pack": stage, "key": r["key"], "request_sha256": r["request_sha256"]} for r in rows],
        "source_files_sha256": {str(p.relative_to(ROOT)): sha(p) for p in sources},
        "input_files_sha256": {str(p): sha(p) for p in inputs}, "metadata": metadata or {},
        "policy": "Raw response retained; journal before send; no retries/JSON repair; failures and interrupted requests stay in denominator."}
    out.mkdir(parents=True)
    write_jsonl(out / "requests.jsonl", rows)
    config["requests_sha256"] = sha(out / "requests.jsonl")
    write_json(out / "execution.json", config)
    (out / "registration.sha256").write_text(sha(out / "execution.json") + "\n")
    return config


def load(out):
    out = Path(out)
    if sha(out / "execution.json") != (out / "registration.sha256").read_text().strip():
        raise ValueError("Registration changed.")
    config = json.loads((out / "execution.json").read_text())
    if config["schema"] != "registered-provider-1.0" or sha(out / "requests.jsonl") != config["requests_sha256"]:
        raise ValueError("Registered requests changed.")
    for name, expected in config["source_files_sha256"].items():
        if not (ROOT / name).is_file() or sha(ROOT / name) != expected:
            raise ValueError("Registered source changed: " + name)
    for name, expected in config["input_files_sha256"].items():
        if sha(name) != expected:
            raise ValueError("Registered input changed: " + name)
    rows = read_jsonl(out / "requests.jsonl")
    if any(canonical_sha({k: v for k, v in r.items() if k != "request_sha256"}) != r["request_sha256"] for r in rows):
        raise ValueError("Request identity changed.")
    requests = {(config["stage"], r["key"]): r for r in rows}
    schedule = [{"pack": config["stage"], "key": r["key"], "request_sha256": r["request_sha256"]} for r in rows]
    if len(requests) != len(rows) or len(rows) != config["max_attempts"] or schedule != config["schedule"]:
        raise ValueError("Request inventory differs from schedule.")
    return config, requests


def parsed(raw, request, parser):
    if raw.get("transport_error"):
        return {"status": "error", "code": raw["transport_error"]}
    if raw.get("http_status") != 200:
        return {"status": "error", "code": f"HTTP_{raw.get('http_status')}"}
    if raw.get("finish_reason") != "stop":
        return {"status": "error", "code": "OUTPUT_TRUNCATED" if raw.get("finish_reason") == "length" else "RESPONSE_INCOMPLETE"}
    if not raw.get("provider_model") or not isinstance(raw.get("content"), str):
        return {"status": "error", "code": "RESPONSE_INVALID"}
    try:
        return parser(raw["content"], request)
    except (ValueError, TypeError, KeyError, AttributeError):
        return {"status": "error", "code": "OUTPUT_INVALID"}


def summary(config, records, state):
    return {"state": state, "expected": config["max_attempts"], "completed": len(records),
        "valid": sum(r["parsed"]["status"] == "ok" for r in records.values()),
        "errors": dict(Counter(r["parsed"]["code"] for r in records.values() if r["parsed"]["status"] != "ok")),
        "usage": {field: sum(r.get("usage", {}).get(field, 0) for r in records.values())
                  for field in ("prompt_tokens", "completion_tokens", "total_tokens")},
        "usage_missing": sum("total_tokens" not in r.get("usage", {}) for r in records.values())}


def verify(out, parser):
    out = Path(out)
    config, requests = load(out)
    attempts, records = checkpoints(out, config)
    for key, row in records.items():
        if row["started_at"] != attempts[key]["started_at"] or parsed(row, requests[key], parser) != row["parsed"]:
            raise ValueError("Response replay differs from checkpoint.")
    seal = out / "result_hashes.json"
    if seal.exists():
        hashes = json.loads(seal.read_text())
        if set(hashes) != set(SEALED) or any(sha(out / n) != expected for n, expected in hashes.items()):
            raise ValueError("Sealed results changed.")
    elif len(records) == len(requests):
        raise ValueError("Complete run has no seal.")
    if (out / "summary.json").exists():
        stored = json.loads((out / "summary.json").read_text())
        if stored != summary(config, records, stored["state"]):
            raise ValueError("Summary differs from raw responses.")
    return {"verified": True, "complete": len(records) == len(requests), "attempts": len(attempts), "API_calls": 0}


async def run(out, parser, *, live=False, transport=None):
    out = Path(out)
    config, requests = load(out)
    if not live:
        return {"prepared": True, "requests": len(requests), "API_calls": 0}
    settings = Settings()
    if not settings.api_key.strip() or any(c in settings.api_key for c in "\r\n"):
        raise ValueError("Valid API key required.")
    if normalize_endpoint(settings.endpoint, settings) != config["endpoint"] or settings.llm_model != config["model"]:
        raise ValueError("Provider setting differs from registration.")
    with (out / ".run.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        verify(out, parser)
        attempts, records = checkpoints(out, config)
        if (out / "result_hashes.json").exists():
            return summary(config, records, "complete")
        for key, attempt in attempts.items():
            if key not in records:
                row = {**attempt, "content": None, "http_status": None, "finish_reason": None,
                       "provider_model": None, "usage": {}, "elapsed_ms": 0, "transport_error": "INTERRUPTED_REQUEST"}
                row["parsed"] = parsed(row, requests[key], parser)
                append(out / "responses.jsonl", row)
                records[key] = row
        previous = json.loads((out / "summary.json").read_text()) if (out / "summary.json").exists() else {}
        if previous.get("state") == "stopped_by_gate":
            return summary(config, records, "stopped_by_gate")
        pending = [r for r in config["schedule"] if (r["pack"], r["key"]) not in attempts]
        state, consecutive = "complete" if not pending else "running", 0
        for record in records.values():
            consecutive = consecutive + 1 if record.get("transport_error") else 0
        async with httpx.AsyncClient(timeout=config["timeout_seconds"], transport=transport, trust_env=False) as client:
            async def send(item):
                key = item["pack"], item["key"]
                attempt = {**item, "started_at": now()}
                append(out / "attempts.jsonl", attempt)
                attempts[key] = attempt
                raw = await collect(client, config=config, key=settings.api_key.strip(), payload=requests[key]["payload"])
                row = {**attempt, **raw, "parsed": parsed(raw, requests[key], parser)}
                append(out / "responses.jsonl", row)
                records[key] = row
                return row
            for start in range(0, len(pending), config["workers"]):
                if (any(r.get("http_status") in FATAL_HTTP for r in records.values()) or consecutive >= 3
                        or sum(r["usage"].get("total_tokens", 0) for r in records.values()) >= config["recorded_token_stop_budget"]):
                    state = "stopped_by_gate"
                    break
                results = await asyncio.gather(*(send(item) for item in pending[start:start + config["workers"]]))
                for row in results:
                    consecutive = consecutive + 1 if row.get("transport_error") else 0
                state = "complete" if len(records) == len(requests) else "running"
                info = summary(config, records, state)
                write_json(out / "summary.json", info)
                print(json.dumps({"stage": config["stage"], **info}), flush=True)
        info = summary(config, records, state)
        write_json(out / "summary.json", info)
        if state == "complete":
            write_json(out / "result_hashes.json", {n: sha(out / n) for n in SEALED})
        return info
