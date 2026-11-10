"""Execute the frozen v6 RAG/conversation packs once, with durable attempts.

The pilot has no independent semantic labels. Transport, schema, warning
trajectories and resource usage are diagnostics, never phishing accuracy.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import shutil
import statistics
import time

import httpx

from app.llm_service import LLMFailure, _parse_verdict_with_validation, normalize_endpoint
from app.message_policy_v6 import parse_v6
from app.rag_evidence_v3 import parse_evidence
from app.settings import ROOT, Settings
from evaluation.message_data import read_jsonl, sha, write_json
from evaluation.url_context_run import append, canonical_sha


SEED = 20261109
PACKS = ("rag_controlled", "conversation_paired")
FATAL_HTTP = {400, 401, 402, 403, 404, 429}


def now():
    return datetime.now(timezone.utc).isoformat()


def check_pack(pack: Path, kind: str):
    protocol = json.loads((pack / "protocol.json").read_text())
    expected_schema = {PACKS[0]: "rag-controlled-v1-1.2", PACKS[1]: "conversation-prefix-paired-1.0"}[kind]
    if protocol["schema"] != expected_schema or sha(pack / "requests.jsonl") != protocol["requests_sha256"]:
        raise ValueError("Unsupported or modified pack: " + kind)
    manifest = protocol.get("execution_manifest", protocol)
    for name, expected in manifest["source_files_sha256"].items():
        if sha(ROOT / name) != expected:
            raise ValueError("Pack source changed: " + name)
    if kind == PACKS[0]:
        if sha(ROOT / manifest["corpus"]) != protocol["corpus_sha256"]:
            raise ValueError("Corpus changed.")
        for name, expected in manifest["index_files_sha256"].items():
            if sha(ROOT / manifest["index_dir"] / name) != expected:
                raise ValueError("Retrieval index changed.")
        private_name, private_hash = "private_map.jsonl", protocol["private_map_sha256"]
    else:
        private_name, private_hash = "private_design_map.jsonl", protocol["private_map_sha256"]
    if sha(pack / private_name) != private_hash:
        raise ValueError("Private design map changed.")
    rows = read_jsonl(pack / "requests.jsonl")
    if len(rows) != protocol["requests"] or len({row["key"] for row in rows}) != len(rows):
        raise ValueError("Unexpected request inventory.")
    for row in rows:
        identity = {key: value for key, value in row.items() if key != "request_sha256"}
        if kind == PACKS[0]:
            encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        else:
            encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True)
        if hashlib.sha256(encoded.encode()).hexdigest() != row["request_sha256"]:
            raise ValueError("Request hash differs.")
    return protocol, rows


def prepare(origin: Path, out: Path):
    if out.exists():
        raise ValueError("Preserve existing runs; choose a fresh output directory.")
    settings = Settings()
    requests = []
    for kind in PACKS:
        _, rows = check_pack(origin / kind, kind)
        for row in rows:
            if row["payload"]["model"] != settings.llm_model:
                raise ValueError("Registered model differs from provider setting.")
            requests.append({"pack": kind, "key": row["key"], "request_sha256": row["request_sha256"]})
    requests.sort(key=lambda row: canonical_sha([SEED, row["pack"], row["key"]]))
    out.mkdir(parents=True)
    for kind in PACKS:
        shutil.copytree(origin / kind, out / "packs" / kind)
    files = [Path(__file__), ROOT / "app/llm_service.py", ROOT / "app/verdict_validation.py",
             ROOT / "app/schemas.py", ROOT / "evaluation/url_context_run.py", ROOT / "evaluation/message_data.py"]
    pack_hashes = {str(p.relative_to(out)): sha(p) for p in sorted((out / "packs").rglob("*")) if p.is_file()}
    config = {"version": "v6-pilot-1.0", "registered_at": now(), "schedule": requests,
              "model": settings.llm_model, "endpoint": normalize_endpoint(settings.endpoint, settings),
              "workers": 2, "timeout_seconds": 90, "max_attempts": len(requests),
              "recorded_token_stop_budget": 1500000, "pack_files_sha256": pack_hashes,
              "source_files_sha256": {str(p.resolve()): sha(p) for p in files},
              "failure_policy": "One attempt per key; journal before send. Never repair or retry outputs. "
                  "Stop on fatal HTTP, three consecutive transport errors or recorded token budget.",
              "independent_semantic_labels": False, "classification_accuracy_available": False,
              "test_inference": False, "selection": "All frozen 30 RAG and 72 conversation requests."}
    write_json(out / "execution.json", config)
    return config


def load(out: Path):
    config = json.loads((out / "execution.json").read_text())
    for name, expected in config["source_files_sha256"].items():
        if sha(name) != expected:
            raise ValueError("Runner source changed after registration: " + name)
    for name, expected in config["pack_files_sha256"].items():
        if sha(out / name) != expected:
            raise ValueError("Locked pack changed: " + name)
    requests = {}
    for kind in PACKS:
        _, rows = check_pack(out / "packs" / kind, kind)
        requests.update({(kind, row["key"]): row for row in rows})
    expected = {(row["pack"], row["key"]) for row in config["schedule"]}
    if len(expected) != len(config["schedule"]) or expected != set(requests) or len(expected) != config["max_attempts"]:
        raise ValueError("Execution inventory differs from frozen packs.")
    return config, requests


def parse(row, request, kind):
    """Replay the raw response with the runtime's completion requirement."""
    if row.get("transport_error"):
        return {"status": "error", "code": row["transport_error"]}
    if row.get("http_status") != 200:
        return {"status": "error", "code": f"HTTP_{row.get('http_status')}"}
    if row.get("finish_reason") != "stop":
        return {"status": "error", "code": "OUTPUT_TRUNCATED" if row.get("finish_reason") == "length" else "RESPONSE_INCOMPLETE"}
    if not row.get("provider_model"):
        return {"status": "error", "code": "RESPONSE_INVALID"}
    if kind == PACKS[0]:
        return parse_evidence(row.get("content"), approved_text=request["text"],
                              verdict=request["frozen_verdict"], sources=request["sources"])
    try:
        if request["key"].endswith("message-v6"):
            verdict, warnings, validation = parse_v6(row.get("content") or "", request["text"])
        else:
            verdict, warnings, validation = _parse_verdict_with_validation(
                row.get("content") or "", request["text"], None, "message-v3")
        return {"status": "ok", "verdict": verdict.model_dump(), "warnings": warnings, "validation": validation}
    except LLMFailure as exc:
        return {"status": "error", "code": exc.code}


async def collect(client, *, config, key, payload):
    started = time.perf_counter()
    row = {"content": None, "http_status": None, "finish_reason": None, "provider_model": None, "usage": {}}
    try:
        async with asyncio.timeout(config["timeout_seconds"]):
            async with client.stream("POST", config["endpoint"], headers={"Authorization": "Bearer " + key},
                                     json=payload, follow_redirects=False) as response:
                row["http_status"] = response.status_code
                if response.status_code != 200:
                    return row
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > 256000:
                        row["transport_error"] = "OUTPUT_TOO_LARGE"
                        return row
                    chunks.append(chunk)
        data = json.loads(b"".join(chunks))
        body = data if "choices" in data else data.get("data", {})
        usage = body.get("usage", data.get("usage", {}))
        if isinstance(usage, dict):
            row["usage"] = {k: v for k, v in usage.items() if k in {
                "prompt_tokens", "completion_tokens", "total_tokens"} and type(v) is int and v >= 0}
        choice = body["choices"][0]
        row.update(content=choice["message"].get("content"), finish_reason=choice.get("finish_reason"),
                   provider_model=body.get("model"))
    except (httpx.TimeoutException, TimeoutError):
        row["transport_error"] = "TIMEOUT"
    except httpx.HTTPError:
        row["transport_error"] = "CONNECTION_ERROR"
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        row["transport_error"] = "RESPONSE_INVALID"
    finally:
        row["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
    return row


def checkpoints(out, config):
    allowed = {(row["pack"], row["key"]): row for row in config["schedule"]}
    values = []
    for name in ("attempts.jsonl", "responses.jsonl"):
        rows = read_jsonl(out / name) if (out / name).exists() else []
        lookup = {(row["pack"], row["key"]): row for row in rows}
        if len(lookup) != len(rows) or not set(lookup) <= set(allowed):
            raise ValueError("Duplicate or unknown checkpoint key.")
        for key, row in lookup.items():
            if row["request_sha256"] != allowed[key]["request_sha256"]:
                raise ValueError("Checkpoint request hash mismatch.")
        values.append(lookup)
    attempts, records = values
    if not set(records) <= set(attempts):
        raise ValueError("Response has no preceding attempt.")
    return attempts, records


def summarize(config, records, state):
    grouped = defaultdict(list)
    for (kind, key), row in records.items():
        condition = key.split("::", 1)[1] if kind == PACKS[0] else "::".join(key.split("::")[2:])
        grouped[kind + "::" + condition].append(row)
    groups = {}
    for name, rows in grouped.items():
        groups[name] = {"n": len(rows), "statuses": dict(Counter(r["parsed"]["status"] for r in rows)),
            "errors": dict(Counter(r["parsed"].get("code") for r in rows if r["parsed"]["status"] == "error")),
            "risk_levels": dict(Counter(r["parsed"]["verdict"]["risk_level"] for r in rows if r["parsed"]["status"] == "ok" and "verdict" in r["parsed"])),
            "usage": {key: sum(r["usage"].get(key, 0) for r in rows) for key in ("prompt_tokens", "completion_tokens", "total_tokens")},
            "usage_missing": sum(not r["usage"] for r in rows),
            "median_elapsed_ms": statistics.median(r["elapsed_ms"] for r in rows)}
    return {"state": state, "expected": config["max_attempts"], "completed": len(records), "groups": groups,
            "recorded_total_tokens": sum(r["usage"].get("total_tokens", 0) for r in records.values()),
            "independent_semantic_labels": False, "accuracy": None, "F1": None,
            "limitations": "Authored diagnostic inputs. Seventy-two requests are six threads, not 72 independent cases. "
                "v5/v6 emit different schemas. RAG verdicts are frozen; no classification improvement measured."}


async def run(out: Path, *, live=False, transport=None):
    config, requests = load(out)
    if not live:
        return {"state": "prepared", "API_calls": 0, "requests": len(requests)}
    settings = Settings()
    if not settings.api_key.strip() or any(c in settings.api_key for c in "\r\n"):
        raise ValueError("API credentials unavailable or invalid.")
    if settings.llm_model != config["model"] or normalize_endpoint(settings.endpoint, settings) != config["endpoint"]:
        raise ValueError("Provider configuration changed.")
    with (out / ".run.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        attempts, records = checkpoints(out, config)
        if (out / "result_hashes.json").exists():
            verify(out)
            return summarize(config, records, "complete")
        for key, attempt in attempts.items():
            if key not in records:
                row = {**attempt, "content": None, "usage": {}, "elapsed_ms": 0,
                       "transport_error": "INTERRUPTED_REQUEST", "http_status": None,
                       "finish_reason": None, "provider_model": None}
                row["parsed"] = parse(row, requests[key], key[0])
                append(out / "responses.jsonl", row)
                records[key] = row
        prior = json.loads((out / "summary.json").read_text()) if (out / "summary.json").exists() else {}
        if prior.get("state") == "stopped_by_gate":
            return summarize(config, records, "stopped_by_gate")
        pending = [row for row in config["schedule"] if (row["pack"], row["key"]) not in attempts]
        state = "complete" if not pending else "running"
        transport_errors = 0
        for row in records.values():
            transport_errors = transport_errors + 1 if row.get("transport_error") else 0
        async with httpx.AsyncClient(timeout=config["timeout_seconds"], transport=transport, trust_env=False) as client:
            async def request(item):
                key = item["pack"], item["key"]
                attempt = {**item, "started_at": now()}
                append(out / "attempts.jsonl", attempt)
                attempts[key] = attempt
                row = await collect(client, config=config, key=settings.api_key.strip(), payload=requests[key]["payload"])
                row = {**attempt, **row}
                row["parsed"] = parse(row, requests[key], key[0])
                append(out / "responses.jsonl", row)
                records[key] = row
                return row
            for start in range(0, len(pending), config["workers"]):
                if (any(r.get("http_status") in FATAL_HTTP for r in records.values()) or transport_errors >= 3
                        or sum(r["usage"].get("total_tokens", 0) for r in records.values()) >= config["recorded_token_stop_budget"]):
                    state = "stopped_by_gate"
                    break
                batch = await asyncio.gather(*(request(item) for item in pending[start:start + config["workers"]]))
                for row in batch:
                    transport_errors = transport_errors + 1 if row.get("transport_error") else 0
                if len(records) == len(requests):
                    state = "complete"
                summary = summarize(config, records, state)
                write_json(out / "summary.json", summary)
                print(json.dumps({"completed": len(records), "expected": len(requests),
                    "errors": sum(row["parsed"]["status"] == "error" for row in records.values()),
                    "recorded_tokens": summary["recorded_total_tokens"], "state": state}), flush=True)
        summary = summarize(config, records, state)
        write_json(out / "summary.json", summary)
        if state == "complete":
            write_json(out / "result_hashes.json", {name: sha(out / name) for name in
                ("execution.json", "attempts.jsonl", "responses.jsonl", "summary.json")})
        return summary


def verify(out: Path):
    config, requests = load(out)
    attempts, records = checkpoints(out, config)
    for key, row in records.items():
        if parse(row, requests[key], key[0]) != row["parsed"]:
            raise ValueError("Raw response replay differs: " + str(key))
    if (out / "result_hashes.json").exists():
        hashes = json.loads((out / "result_hashes.json").read_text())
        if any(sha(out / name) != expected for name, expected in hashes.items()):
            raise ValueError("Sealed results changed.")
    elif len(records) == len(requests):
        raise ValueError("Complete run has no result seal.")
    stored = json.loads((out / "summary.json").read_text())
    if stored != summarize(config, records, stored["state"]):
        raise ValueError("Summary differs from response records.")
    return {"verified": True, "attempts": len(attempts), "records": len(records),
            "complete": len(records) == len(requests), "API_calls": 0, "semantic_labels_available": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "run", "verify"])
    parser.add_argument("--origin", type=Path, default=ROOT / "artifacts/evaluations/v6_hardening_20261109")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if args.command == "prepare":
        config = prepare(args.origin, args.out)
        result = {"prepared": True, "requests": config["max_attempts"], "API_calls": 0}
    elif args.command == "run":
        result = asyncio.run(run(args.out, live=args.live))
    else:
        result = verify(args.out)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
