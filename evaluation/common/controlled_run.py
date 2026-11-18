"""Paced, once-only registered runs with an explicit operational pilot pause."""
import asyncio
import fcntl
import json
from pathlib import Path
import time

import httpx

from app.core.settings import Settings
from app.services.llm.client import normalize_endpoint
from app.services.llm.telemetry import ObservedTransport
from evaluation.common import registered
from evaluation.data.sms import write_json
from evaluation.messages.interaction_pilot import collect, now
from evaluation.messages.url_context import append


async def run(out, parser, *, live=False, limit=None, inner=None):
    """Pause after ``limit`` new attempts; resuming never resends an old key.

    Pace, timeout and token budget belong to the initial registration. A pilot
    pause is not a failure gate; only pending, never-attempted requests may run
    afterwards. Fatal HTTP/transport/token gates cannot be bypassed by resume.
    """
    out = Path(out)
    config, requests = registered.load(out)
    interval = config["metadata"].get("pacing_seconds")
    if config["workers"] != 1 or not isinstance(interval, (int, float)) or interval < 0:
        raise ValueError("Register one worker and nonnegative pacing before running.")
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError("A positive attempt limit is required.")
    if not live:
        return {"prepared": True, "requests": len(requests), "API_calls": 0}
    settings = Settings()
    if not settings.api_key.strip() or any(c in settings.api_key for c in "\r\n"):
        raise ValueError("A valid server API key is required.")
    if normalize_endpoint(settings.endpoint, settings) != config["endpoint"] or settings.llm_model != config["model"]:
        raise ValueError("Provider differs from registration.")
    with (out / ".run.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        registered.verify(out, parser)
        attempts, records = registered.checkpoints(out, config)
        if (out / "result_hashes.json").exists():
            return registered.summary(config, records, "complete")
        for key, attempt in attempts.items():
            if key not in records:
                row = {**attempt, "content": None, "http_status": None, "finish_reason": None,
                       "provider_model": None, "usage": {}, "elapsed_ms": 0,
                       "transport_error": "INTERRUPTED_REQUEST"}
                row["parsed"] = registered.parsed(row, requests[key], parser)
                append(out / "responses.jsonl", row)
                records[key] = row
        previous = json.loads((out / "summary.json").read_text()) if (out / "summary.json").exists() else {}
        if previous.get("state") == "stopped_by_gate":
            return registered.summary(config, records, "stopped_by_gate")
        pilot = config["metadata"].get("pilot_unique_requests")
        if not attempts and pilot and limit != pilot:
            raise ValueError("The first live segment must use the registered pilot size.")
        pending = [row for row in config["schedule"] if (row["pack"], row["key"]) not in attempts]
        consecutive = 0
        for row in records.values():
            consecutive = consecutive + 1 if row.get("transport_error") else 0
        state, sent, last_start = "complete" if not pending else "running", 0, None
        transport = ObservedTransport(out / "telemetry.jsonl", inner=inner)
        async with httpx.AsyncClient(timeout=config["timeout_seconds"], transport=transport, trust_env=False) as client:
            for item in pending:
                if (any(row.get("http_status") in registered.FATAL_HTTP for row in records.values())
                        or consecutive >= 3
                        or sum(row["usage"].get("total_tokens", 0) for row in records.values()) >= config["recorded_token_stop_budget"]):
                    state = "stopped_by_gate"
                    break
                if limit is not None and sent >= limit:
                    state = "pilot_paused"
                    break
                if last_start is not None:
                    await asyncio.sleep(max(0, interval - (time.monotonic() - last_start)))
                elif records and interval:
                    # Avoid a burst across two adjacent process invocations.
                    await asyncio.sleep(interval)
                last_start = time.monotonic()
                key = item["pack"], item["key"]
                attempt = {**item, "started_at": now()}
                append(out / "attempts.jsonl", attempt)
                attempts[key] = attempt
                raw = await collect(client, config=config, key=settings.api_key.strip(), payload=requests[key]["payload"])
                row = {**attempt, **raw, "parsed": registered.parsed(raw, requests[key], parser)}
                append(out / "responses.jsonl", row)
                records[key] = row
                consecutive = consecutive + 1 if row.get("transport_error") else 0
                sent += 1
                state = "complete" if len(records) == len(requests) else "running"
                info = registered.summary(config, records, state)
                write_json(out / "summary.json", info)
                print(json.dumps({"stage": config["stage"], **info}), flush=True)
        info = registered.summary(config, records, state)
        write_json(out / "summary.json", info)
        if state == "complete":
            write_json(out / "result_hashes.json", {name: registered.sha(out / name) for name in registered.SEALED})
        return info
