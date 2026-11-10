"""Registered URL/context evaluation with durable attempts and no automatic retry."""
import argparse
import asyncio
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import random
import re
import time

import httpx

from app.services.llm.client import normalize_endpoint
from app.services.url.features import ModelService
from app.core.settings import ROOT, Settings
from evaluation.data.sms import read_jsonl, sha
from evaluation.messages.baseline import write_json
from evaluation.data.url_context import TARGETS, provider_input, verify
from evaluation.messages.url_context_score import LEVELS, expected_keys, score, validate_records

FATAL = {"HTTP_400", "HTTP_401", "HTTP_402", "HTTP_403", "HTTP_404", "HTTP_429"}
LLM_ARMS = ("llm_only", "llm_url")


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def append(path, value):
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def key(record):
    return record["id"], record["arm"], record["repeat"]


def parse_content(content, case):
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Empty response")
    text = content.strip()
    if text.startswith("```"):
        match = re.fullmatch(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if not match:
            raise ValueError("Invalid code fence")
        text = match.group(1)
    value = json.loads(text)
    fields = {*TARGETS, "url_role", "explanation", "evidence_quotes"}
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("Wrong schema")
    if any(not isinstance(value[t], str) or value[t] not in LEVELS for t in TARGETS):
        raise ValueError("Wrong risk level")
    if value["url_role"] not in {"requested", "quoted", "none", "UNKNOWN"}:
        raise ValueError("Wrong URL role")
    if not isinstance(value["explanation"], str) or not value["explanation"].strip():
        raise ValueError("Missing explanation")
    quotes = value["evidence_quotes"]
    if not isinstance(quotes, list) or any(not isinstance(q, str) or not q.strip() or q not in case["text"] for q in quotes):
        raise ValueError("Quote is not present in input")
    if case["task"] == "url_only" and (value["url_role"] != "none" or any(value[t] != "UNKNOWN" for t in ("message_behavior", "action_risk"))):
        raise ValueError("URL-only scope violation")
    return value


def ml_context(prediction, case):
    # No ID, reference, source, tier, or task label can enter the provider input.
    if prediction["status"] != "ok" or prediction["url"] not in case["text"]:
        raise ValueError("Missing/mismatched URL prediction")
    return [{k: prediction[k] for k in ("url", "score", "risk_level", "warning_threshold", "high_threshold")}]


def payload_for(case, arm, prediction, system_prompt, config):
    if arm not in LLM_ARMS:
        raise ValueError("Unexpected LLM arm")
    data = provider_input(case, ml_context(prediction, case) if arm == "llm_url" else [])
    return {"model": config["model"], "messages": [{"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(data, ensure_ascii=False)}],
        "temperature": config["temperature"], "top_p": config["top_p"], "top_k": config["top_k"],
        "max_tokens": config["max_tokens"], "stream": False}


async def call_provider(client, endpoint, api_key, payload, case, timeout):
    started = time.perf_counter()
    result = {"status": "error", "error_code": "RESPONSE_INVALID", "usage": {}}
    try:
        async with asyncio.timeout(timeout):
            async with client.stream("POST", endpoint, headers={"Authorization": "Bearer " + api_key},
                                     json=payload, follow_redirects=False) as response:
                result["http_status"] = response.status_code
                if response.status_code != 200:
                    result["error_code"] = f"HTTP_{response.status_code}"
                    return result
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > 1_000_000:
                        result["error_code"] = "OUTPUT_TOO_LARGE"
                        return result
                    chunks.append(chunk)
        data = json.loads(b"".join(chunks))
        body = data if "choices" in data else data.get("data", {})
        usage = body.get("usage", data.get("usage", {}))
        result["usage"] = {k: v for k, v in usage.items() if k in {"prompt_tokens", "completion_tokens", "total_tokens"}
                           and type(v) is int and v >= 0} if isinstance(usage, dict) else {}
        choice = body["choices"][0]
        content = choice["message"].get("content")
        result.update(raw_content=content if isinstance(content, str) else None,
                      finish_reason=choice.get("finish_reason"), provider_model=body.get("model"),
                      provider_response_id=body.get("id"))
        if choice.get("finish_reason") == "length":
            result["error_code"] = "OUTPUT_TRUNCATED"
            return result
        try:
            parsed = parse_content(content, case)
        except (ValueError, TypeError, KeyError):
            result["error_code"] = "OUTPUT_INVALID"
            return result
        result.pop("error_code")
        result.update(status="ok", outputs={t: parsed[t] for t in TARGETS}, explanation=parsed["explanation"],
                      url_role=parsed["url_role"], evidence_quotes=parsed["evidence_quotes"])
        return result
    except (TimeoutError, httpx.TimeoutException):
        result["error_code"] = "TIMEOUT"
    except httpx.HTTPError:
        result["error_code"] = "CONNECTION_ERROR"
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        result["error_code"] = "RESPONSE_INVALID"
    finally:
        result["elapsed_ms"] = round(1000 * (time.perf_counter() - started), 2)
    return result


def configuration(pack, split, repetitions, settings):
    verify(pack)
    protocol = json.loads((pack / "protocol.json").read_text())
    for name, digest in protocol["artifact_hashes"].items():
        if sha(ROOT / name) != digest:
            raise ValueError(f"Registered pack artifact changed: {name}")
    model_dir = Path(settings.model_dir)
    model_dir = model_dir if model_dir.is_absolute() else ROOT / model_dir
    if sha(model_dir / "model.ubj") != protocol["artifact_hashes"]["models/inference_XGBoost_d6_s42/model.ubj"]:
        raise ValueError("Configured model differs from the pack model")
    model = json.loads((model_dir / "config.json").read_text())
    cases = read_jsonl(pack / f"{split}.jsonl")
    expected_keys(cases, repetitions)
    files = ["evaluation/messages/url_context.py", "evaluation/messages/url_context_score.py", "evaluation/data/url_context.py",
             "evaluation/common/metrics.py", "evaluation/data/sms.py", "evaluation/messages/baseline.py", "evaluation/url/phishvn.py",
             "app/services/url/features.py", "app/core/settings.py", "app/services/llm/client.py", "app/services/url/parsing.py"]
    config = {"version": "url-context-execution-1.0", "pack": str(pack.resolve()), "split": split,
        "pack_manifest_sha256": sha(pack / "manifest.json"), "dataset_sha256": sha(pack / f"{split}.jsonl"),
        "prompt_sha256": sha(pack / "system_prompt.txt"), "cases": len(cases), "repetitions": repetitions,
        "llm_arms": list(LLM_ARMS), "max_total_provider_attempts": len(cases) * 2 * repetitions,
        "model": settings.llm_model, "endpoint": normalize_endpoint(settings.endpoint, settings),
        "max_tokens": settings.max_tokens, "timeout_seconds": settings.timeout_seconds,
        "temperature": .1, "top_p": 1, "top_k": 40, "workers": 2, "order_seed": 20261103,
        "api_seed": None, "thresholds": model["thresholds"],
        "model_files_sha256": {str(p.relative_to(ROOT) if p.is_relative_to(ROOT) else p): sha(p)
            for p in sorted(model_dir.iterdir()) if p.is_file()},
        "source_sha256": {name: sha(ROOT / name) for name in files},
        "failure_policy": "No retries. Errors remain UNKNOWN. Journal before request; interrupted attempts become INTERRUPTED_REQUEST on resume and are never reissued. Stop on fatal HTTP or three consecutive errors.",
        "validation": "Same exact JSON schema, levels, nonempty explanation and literal evidence quotes for both arms. URL-only requires other axes UNKNOWN. No semantic relabeling. Whole invalid response counts as error.",
        "input_policy": "Only task, unmodified public/synthetic text, and whitelisted model URL scores. No source labels, tier, IDs or reference sent.",
        "inference_scope": "Research prompt from frozen pack, not production message-v3; source labels historical, contexts authored.",
        "repetition_policy": "All registered repetitions retained, no best run or response selection; seeds shuffle order only."}
    return config, cases, model_dir


def export(out, config, cases, urls, records, attempts, state):
    result = score(cases, urls, records, config["repetitions"])
    result.update(run_state=state, execution_manifest_sha256=sha(out / "execution.json"),
        provider_requests=len(attempts), provenance="Live runner checkpoints and durable attempt journal; API errors retained. Numerical verification is separate.")
    result["status_counts"] = {arm: dict(Counter(r["status"] for r in records if r["arm"] == arm)) for arm in (*LLM_ARMS, "url_model")}
    result["error_codes"] = {arm: dict(Counter(r["error_code"] for r in records if r["arm"] == arm and r["status"] == "error")) for arm in LLM_ARMS}
    result["usage"] = {arm: {k: sum(r.get("usage", {}).get(k, 0) for r in records if r["arm"] == arm)
                            for k in ("prompt_tokens", "completion_tokens", "total_tokens")} for arm in LLM_ARMS}
    result["usage_note"] = "Recorded usage includes errors if returned by provider. Transport failures/interrupted calls may lack usage; not a verified bill."
    write_json(out / "summary.json", result)
    return result


async def evaluate(args):
    settings = replace(Settings(), max_tokens=8192, timeout_seconds=90)
    pack, out = Path(args.pack), Path(args.out)
    config, cases, model_dir = configuration(pack, args.split, args.repetitions, settings)
    if args.live and (not settings.api_key.strip() or any(x in settings.api_key for x in ("\r", "\n"))):
        raise ValueError("API credentials unavailable/invalid; no provider requests made")
    if out.exists():
        if not (out / "execution.json").exists() or json.loads((out / "execution.json").read_text())["configuration"] != config:
            raise ValueError("Output has different or missing execution registration; choose a new directory")
    else:
        out.mkdir(parents=True)
    with (out / ".run.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("Another process is running this evaluation") from exc
        if not (out / "execution.json").exists():
            write_json(out / "execution.json", {"registered_at": datetime.now(timezone.utc).isoformat(), "configuration": config})
        urls = read_jsonl(pack / "urls.jsonl")
        used_ids = {c["url_id"] for c in cases}
        selected = [u for u in urls if u["id"] in used_ids]
        prepared_path = out / "prepared_urls.json"
        if prepared_path.exists():
            if sha(prepared_path) != (out / "prepared_urls.sha256").read_text().strip():
                raise ValueError("Prepared URL predictions changed")
            prepared = json.loads(prepared_path.read_text())
        else:
            model = ModelService(settings)
            if not model.load()["ready"]:
                raise ValueError("URL model could not be loaded")
            if model.path.resolve() != model_dir.resolve():
                raise ValueError("ModelService resolved a different model directory")
            outputs = model.predict([u["url"] for u in selected])
            if any(p["status"] != "ok" for p in outputs):
                raise ValueError("URL prediction failed; stopped before provider calls")
            prepared = {u["id"]: p for u, p in zip(selected, outputs)}
            write_json(prepared_path, prepared)
            (out / "prepared_urls.sha256").write_text(sha(prepared_path) + "\n")
        if set(prepared) != used_ids or any(prepared[u["id"]]["url"] != u["url"] for u in selected):
            raise ValueError("Prepared URL targets differ")
        records_path, attempts_path = out / "predictions.jsonl", out / "attempts.jsonl"
        records = read_jsonl(records_path) if records_path.exists() else []
        lookup, _ = validate_records(cases, records, args.repetitions)
        attempts = read_jsonl(attempts_path) if attempts_path.exists() else []
        attempt_keys = {key(a) for a in attempts}
        valid_llm_keys = {k for k in expected_keys(cases, args.repetitions) if k[1] in LLM_ARMS}
        if len(attempts) != len(attempt_keys) or not attempt_keys <= valid_llm_keys:
            raise ValueError("Duplicate/unexpected attempt journal entries")
        if any(key(r) not in attempt_keys for r in records if r["arm"] in LLM_ARMS):
            raise ValueError("LLM checkpoint has no attempt journal entry")
        for a in attempts:
            if key(a) not in lookup:
                r = {k: a[k] for k in ("id", "arm", "repeat")}
                r.update(status="error", error_code="INTERRUPTED_REQUEST", usage={})
                append(records_path, r); records.append(r); lookup[key(r)] = r
        for c in cases:
            k = (c["id"], "url_model", 0)
            if k not in lookup:
                r = {"id": c["id"], "arm": "url_model", "repeat": 0, "status": "ok",
                     "outputs": {"url_risk": prepared[c["url_id"]]["risk_level"], "message_behavior": "UNKNOWN", "action_risk": "UNKNOWN"}}
                append(records_path, r); records.append(r); lookup[k] = r
        state = {"live": args.live, "new_provider_attempts": 0, "stop_reason": "offline_prepared" if not args.live else None}
        export(out, config, cases, urls, records, attempts, state)
        if not args.live:
            print(json.dumps({"prepared_cases": len(cases), "unique_urls": len(selected), "planned_calls": config["max_total_provider_attempts"], "new_provider_attempts": 0}), flush=True)
            return
        system_prompt = (pack / "system_prompt.txt").read_text(encoding="utf-8")
        queue = asyncio.Queue()
        for rep in range(1, args.repetitions + 1):
            ordered = sorted(cases, key=lambda c: c["id"])
            random.Random(config["order_seed"] + rep).shuffle(ordered)
            for i, c in enumerate(ordered):
                arms = LLM_ARMS if (i + rep) % 2 else tuple(reversed(LLM_ARMS))
                for arm in arms:
                    if (c["id"], arm, rep) not in lookup:
                        queue.put_nowait((c, arm, rep))
        errors = 0
        async with httpx.AsyncClient(timeout=settings.timeout_seconds, trust_env=False,
                                     limits=httpx.Limits(max_connections=2, max_keepalive_connections=2)) as client:
            async def worker():
                nonlocal errors
                while not queue.empty() and state["stop_reason"] is None:
                    c, arm, rep = queue.get_nowait()
                    payload = payload_for(c, arm, prepared[c["url_id"]], system_prompt, config)
                    attempt = {"id": c["id"], "arm": arm, "repeat": rep,
                        "started_at": datetime.now(timezone.utc).isoformat(), "payload_sha256": canonical_sha(payload)}
                    append(attempts_path, attempt); attempts.append(attempt)
                    state["new_provider_attempts"] += 1
                    result = await call_provider(client, config["endpoint"], settings.api_key.strip(), payload, c, settings.timeout_seconds)
                    result.update(id=c["id"], arm=arm, repeat=rep, payload_sha256=attempt["payload_sha256"])
                    append(records_path, result); records.append(result); lookup[key(result)] = result
                    errors = errors + 1 if result["status"] == "error" else 0
                    if result.get("error_code") in FATAL or errors >= 3:
                        state["stop_reason"] = result.get("error_code") if result.get("error_code") in FATAL else "three_consecutive_errors"
                    completed = sum(r["arm"] in LLM_ARMS for r in records)
                    if completed % 10 == 0 or state["stop_reason"]:
                        export(out, config, cases, urls, records, attempts, state)
                        print(json.dumps({"completed": completed, "planned": config["max_total_provider_attempts"],
                            "errors": sum(r["status"] == "error" for r in records), "stop_reason": state["stop_reason"]}), flush=True)
            try:
                await asyncio.gather(*(worker() for _ in range(config["workers"])))
            finally:
                state["stop_reason"] = state["stop_reason"] or ("all_calls_completed" if len(records) == len(expected_keys(cases, args.repetitions)) else "interrupted")
                export(out, config, cases, urls, records, attempts, state)
        print(json.dumps({"out": str(out), "stop_reason": state["stop_reason"], "provider_attempts": len(attempts)}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, default=ROOT / "data/annotation/url_context_v1")
    parser.add_argument("--split", choices=("dev", "test"), default="dev")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    try:
        asyncio.run(evaluate(args))
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(2, f"Evaluation stopped: {exc}\n")


if __name__ == "__main__":
    main()
