"""Bounded paired engineering comparison, not a semantic RAG quality benchmark.

Reuses all 16 source cases and frozen verdicts from the earlier development run.
Both arms are freshly generated. No classification, test inference, or retries.
"""
import argparse
import asyncio
from collections import Counter
import csv
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import statistics

import httpx

from app.llm_service import normalize_endpoint
from app.rag_explanation_v2 import build_explanation_payload, call_explanation_v2, parse_explanation_v2
from app.rag_evidence_v3 import build_evidence_payload, call_evidence, parse_evidence
from app.settings import ROOT, Settings
from .message_data import read_jsonl, sha, write_json, write_jsonl
from .url_context_run import append, canonical_sha

ARMS = ("free_text_v2", "span_selection_v3")
TOOLS = {ARMS[0]: (build_explanation_payload, call_explanation_v2, parse_explanation_v2),
         ARMS[1]: (build_evidence_payload, call_evidence, parse_evidence)}
FATAL = {"HTTP_400", "HTTP_401", "HTTP_402", "HTTP_403", "HTTP_404", "HTTP_429"}
ORIGIN = ROOT / "artifacts/evaluations/improvement_pilot_v1"


def now():
    return datetime.now(timezone.utc).isoformat()


def prepare(out, origin=ORIGIN):
    out, origin = Path(out), Path(origin)
    if out.exists():
        raise ValueError("Preserve previous runs; choose a new output directory.")
    prior = json.loads((origin / "execution.json").read_text())["configuration"]
    by_id = {row["id"]: row for row in read_jsonl(origin / "cases.jsonl")}
    verdicts = {row["id"]: row for row in read_jsonl(origin / "predictions.jsonl") if row["arm"] == "v5_plain"}
    prepared = json.loads((origin / "prepared.json").read_text())
    cases = []
    for identifier in prior["selections"]["rag_with_sources"]:
        item, verdict = by_id[identifier], verdicts[identifier]
        sources = prepared[identifier]["retrieval"]["sources"]
        if verdict["status"] != "ok" or not sources:
            raise ValueError("All preselected cases require a frozen successful verdict and sources.")
        cases.append({"id": identifier, "dataset": item["dataset"], "text": item["text"],
                      "verdict": verdict["verdict"], "sources": sources})
    if len(cases) != 16 or len({c["id"] for c in cases}) != 16:
        raise ValueError("Use all 16 previously selected cases, without selecting by outcome.")
    settings = Settings()
    files = [Path(__file__), ROOT / "app/rag_explanation.py", ROOT / "app/rag_explanation_v2.py",
             ROOT / "app/rag_evidence_v3.py", ROOT / "app/schemas.py", ROOT / "app/settings.py",
             ROOT / "app/llm_service.py", ROOT / "evaluation/message_data.py", ROOT / "evaluation/url_context_run.py"]
    files += [origin / name for name in ("execution.json", "cases.jsonl", "prepared.json", "predictions.jsonl")]
    schedule = [{"id": c["id"], "arm": arm} for c in cases for arm in ARMS]
    schedule.sort(key=lambda item: canonical_sha([20261107, item["id"], item["arm"]]))
    config = {"version": "rag-evidence-pilot-1.0", "model": settings.llm_model,
              "endpoint": normalize_endpoint(settings.endpoint, settings), "max_tokens": 8192,
              "timeout_seconds": 90, "workers": 2, "max_provider_attempts": 32,
              "recorded_token_stop_budget": 400000, "arms": list(ARMS), "schedule": schedule,
              "cases_sha256": canonical_sha(cases), "registered_before_inference": True,
              "selection": "All 16 old source-selected dev cases; no selection by earlier generation outcome.",
              "comparison": "Fresh paired requests, same frozen verdict/sources/provider/token cap; generation contract differs.",
              "primary": ["truncation_count", "error_count", "valid_response_count", "recorded_tokens"],
              "failure_policy": "Journal before call, never resend an attempted key. Stop on fatal HTTP, three consecutive errors or recorded token budget (in-flight batch may finish).",
              "claims": "Engineering diagnostic only. ID selection has no generated actions/claims; no semantic quality equivalence or improvement inferred.",
              "human_semantic_grades_available": False, "test_inference": False,
              "classification_calls": 0, "default_app_changed": False,
              "input_hashes": {str(p.resolve()): sha(p) for p in files}}
    out.mkdir(parents=True)
    write_jsonl(out / "cases.jsonl", cases)
    write_json(out / "execution.json", {"registered_at": now(), "configuration": config})
    return config, cases


def load(out):
    config = json.loads((out / "execution.json").read_text())["configuration"]
    for path, expected in config["input_hashes"].items():
        if sha(path) != expected:
            raise ValueError("Registered source/input changed: " + path)
    cases = read_jsonl(out / "cases.jsonl")
    if canonical_sha(cases) != config["cases_sha256"]:
        raise ValueError("Locked cases changed.")
    return config, cases


def payload(case, arm, config):
    return TOOLS[arm][0](approved_text=case["text"], verdict=case["verdict"], sources=case["sources"],
                         model=config["model"], max_tokens=config["max_tokens"])


def checkpoint(out, config):
    values = []
    allowed = {(x["id"], x["arm"]) for x in config["schedule"]}
    for name in ("attempts.jsonl", "predictions.jsonl"):
        rows = read_jsonl(out / name) if (out / name).exists() else []
        lookup = {(r["id"], r["arm"]): r for r in rows}
        if len(rows) != len(lookup) or not set(lookup) <= allowed:
            raise ValueError("Duplicate or unknown checkpoint key.")
        values.append(lookup)
    attempts, records = values
    if not set(records) <= set(attempts) or len(attempts) > config["max_provider_attempts"]:
        raise ValueError("Checkpoint exceeds attempted requests or budget.")
    return attempts, records


def seal(out):
    hashes = {name: sha(out / name) for name in ("execution.json", "cases.jsonl", "attempts.jsonl", "predictions.jsonl", "summary.json")}
    path = out / "result_hashes.json"
    if path.exists():
        if json.loads(path.read_text()) != hashes:
            raise ValueError("Completed result snapshot hash mismatch.")
    else:
        write_json(path, hashes)


def summarize(config, records, state):
    results = {}
    for arm in ARMS:
        rows = [r for r in records.values() if r["arm"] == arm]
        counts = Counter(r["status"] for r in rows)
        results[arm] = {"n": len(rows), "statuses": dict(counts),
                       "valid_responses": counts["ok"] + counts["no_support"],
                       "errors": dict(Counter(r.get("code") for r in rows if r["status"] == "error")),
                       "usage": {key: sum(r.get("usage", {}).get(key, 0) for r in rows)
                                 for key in ("prompt_tokens", "completion_tokens", "total_tokens")},
                       "usage_missing": sum(not r.get("usage") for r in rows),
                       "median_elapsed_ms": statistics.median([r["elapsed_ms"] for r in rows if "elapsed_ms" in r]) if any("elapsed_ms" in r for r in rows) else None,
                       "support_pairs": sum(len(r.get("explanation", {}).get("support", [])) for r in rows),
                       "visible_output_characters": sum(len(r.get("raw_content") or "") for r in rows)}
    return {"state": state, "completed": len(records), "expected": len(config["schedule"]),
            "provider_attempts": len(records), "arms": results, "semantic_support_verified": False,
            "classification_changed": False, "diagnostic_only": True,
            "note": "Structural validity and shorter output do not establish semantic relevance. No action generation in selection arm; not equivalent full explanation tasks."}


async def run(out, live=False, transport=None):
    out = Path(out)
    config, cases = load(out)
    if not live:
        return {"state": "prepared", "API_calls": 0}
    settings = Settings()
    if not settings.api_key.strip():
        raise ValueError("API credentials unavailable.")
    if config["model"] != settings.llm_model or config["endpoint"] != normalize_endpoint(settings.endpoint, settings):
        raise ValueError("Provider settings differ from registration.")
    with (out / ".run.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        attempts, records = checkpoint(out, config)
        for key, attempt in attempts.items():
            if key not in records:
                record = {**attempt, "status": "error", "code": "INTERRUPTED_REQUEST", "usage": {}}
                append(out / "predictions.jsonl", record)
                records[key] = record
        if (out / "summary.json").exists():
            prior_summary = json.loads((out / "summary.json").read_text())
            if prior_summary["state"] == "stopped_by_gate":
                return summarize(config, records, "stopped_by_gate")
        by_id = {c["id"]: c for c in cases}
        pending = [x for x in config["schedule"] if (x["id"], x["arm"]) not in attempts]
        failures = 0
        for record in records.values():
            failures = failures + 1 if record["status"] == "error" else 0
        state = "complete" if not pending else "running"
        async with httpx.AsyncClient(timeout=config["timeout_seconds"], transport=transport, trust_env=False) as client:
            async def request(item):
                identifier, arm = item["id"], item["arm"]
                case = by_id[identifier]
                body = payload(case, arm, config)
                attempt = {**item, "started_at": now(), "payload_sha256": canonical_sha(body),
                           "frozen_verdict_sha256": canonical_sha(case["verdict"])}
                append(out / "attempts.jsonl", attempt)
                attempts[(identifier, arm)] = attempt
                result = await TOOLS[arm][1](client, endpoint=config["endpoint"], api_key=settings.api_key,
                    payload=body, approved_text=case["text"], verdict=case["verdict"], sources=case["sources"],
                    timeout=config["timeout_seconds"], capture_raw=True)
                # The frozen V1 transport underlying the free-text parser did
                # not require finish=stop. Apply the same completion contract
                # to both arms here, without altering the old locked module.
                if "finish_reason" in result and result["finish_reason"] not in {"stop", "length"}:
                    result.update(status="error", code="RESPONSE_INCOMPLETE",
                                  explanation={"support": [], "actions": []})
                record = {**result, **attempt}
                append(out / "predictions.jsonl", record)
                records[(identifier, arm)] = record
                return record
            for start in range(0, len(pending), config["workers"]):
                previous = list(records.values())
                if (failures >= 3 or any(r.get("code") in FATAL for r in previous) or
                        sum(r.get("usage", {}).get("total_tokens", 0) for r in previous) >= config["recorded_token_stop_budget"]):
                    state = "stopped_by_gate"
                    break
                batch = await asyncio.gather(*(request(item) for item in pending[start:start + config["workers"]]))
                for record in batch:
                    failures = failures + 1 if record["status"] == "error" else 0
                if len(records) == len(config["schedule"]):
                    state = "complete"
                write_json(out / "summary.json", summarize(config, records, state))
        result = summarize(config, records, state)
        write_json(out / "summary.json", result)
        if state == "complete":
            seal(out)
        return result


def verify(out):
    out = Path(out)
    config, cases = load(out)
    attempts, records = checkpoint(out, config)
    if len(records) == len(config["schedule"]):
        if not (out / "result_hashes.json").exists():
            raise ValueError("Completed run is missing its sealed result snapshot.")
        seal(out)
    by_id = {c["id"]: c for c in cases}
    replayed = 0
    for key, attempt in attempts.items():
        case = by_id[key[0]]
        if attempt["payload_sha256"] != canonical_sha(payload(case, key[1], config)) or attempt["frozen_verdict_sha256"] != canonical_sha(case["verdict"]):
            raise ValueError("Attempt payload/verdict mismatch.")
        if key not in records:
            continue
        record = records[key]
        if any(record[k] != attempt[k] for k in ("payload_sha256", "frozen_verdict_sha256")):
            raise ValueError("Saved prediction mismatch.")
        if record.get("finish_reason") == "length":
            if record.get("code") != "OUTPUT_TRUNCATED" or record["status"] != "error":
                raise ValueError("Truncation was not retained.")
        elif record.get("finish_reason") == "stop":
            parsed = TOOLS[key[1]][2](record.get("raw_content"), approved_text=case["text"],
                                      verdict=case["verdict"], sources=case["sources"])
            for field in ("status", "code", "explanation"):
                if record.get(field) != parsed.get(field):
                    raise ValueError("Raw response parse differs: " + field)
            replayed += 1
        elif "finish_reason" in record:
            if record["status"] != "error" or record.get("code") != "RESPONSE_INCOMPLETE":
                raise ValueError("Incomplete generation was not retained as error.")
        elif record["status"] != "error":
            raise ValueError("Success requires a completed provider response.")
    if (out / "summary.json").exists():
        stored = json.loads((out / "summary.json").read_text())
        if summarize(config, records, stored["state"]) != stored:
            raise ValueError("Saved summary differs from records.")
    result = {"verified_at": now(), "attempts": len(attempts), "records": len(records),
              "raw_replay_count": replayed, "unresolved_attempts": len(set(attempts) - set(records)),
              "complete": len(records) == len(config["schedule"]), "API_calls": 0, "classification_changed": False,
              "source_hashes_checked": True, "semantic_support_verified": False}
    write_json(out / "verification.json", result)
    return result


def report(out):
    out = Path(out)
    config, cases = load(out)
    _, records = checkpoint(out, config)
    stored = json.loads((out / "summary.json").read_text())
    summary = summarize(config, records, stored["state"])
    if stored != summary:
        raise ValueError("Summary differs from saved records.")
    lines = ["# RAG: fresh paired engineering pilot", "", "16 previously viewed development inputs; same frozen verdict and sources. No semantic labels, new test, or classification gain claim.", "", "| Arm | Records | Valid JSON/quotes or no_support | Errors | Tokens recorded |", "|---|---:|---:|---:|---:|"]
    for arm, value in summary["arms"].items():
        lines.append(f"| {arm} | {value['n']} | {value['valid_responses']} | {sum(value['errors'].values())} | {value['usage']['total_tokens']} |")
    lines += ["", summary["note"], "", "One attempt per key. Failed/truncated generations remain failures; no repair requests. Usage is not a verified invoice. Human relevance review is still required.", ""]
    (out / "report.md").write_text("\n".join(lines))
    sheet = out / "relevance_blind.csv"
    if not sheet.exists():
        mapping = {}
        with sheet.open("w", newline="") as target:
            fields = ["review_id", "message", "output_status", "support_json", "relevance_0_2", "notes"]
            writer = csv.DictWriter(target, fieldnames=fields)
            writer.writeheader()
            by_id = {c["id"]: c for c in cases}
            for key in sorted(records, key=lambda k: canonical_sha(["blind-rag-evidence", *k])):
                record = records[key]
                identifier = "RE-" + canonical_sha(key)[:12]
                mapping[identifier] = {"id": key[0], "arm": key[1]}
                writer.writerow({"review_id": identifier, "message": by_id[key[0]]["text"],
                                 "output_status": record["status"],
                                 "support_json": json.dumps(record.get("explanation", {}).get("support", []), ensure_ascii=False)})
        write_json(out / "review_mapping.json", mapping)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "run", "verify", "report"])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--origin", type=Path, default=ORIGIN)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if args.command == "prepare":
        config, _ = prepare(args.out, args.origin)
        result = {"prepared": True, "requests_max": config["max_provider_attempts"], "API_calls": 0}
    elif args.command == "run":
        result = asyncio.run(run(args.out, live=args.live))
    else:
        result = globals()[args.command](args.out)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
