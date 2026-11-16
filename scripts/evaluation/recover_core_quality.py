"""Explicit paced amendment after a successful health check; never resend a case."""
import argparse
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.services.llm.telemetry import ObservedTransport
from evaluation.common import registered
from evaluation.data.sms import sha, write_json, write_jsonl
from evaluation.messages.core_pilot import parse_response
from evaluation.messages.core_quality import report


class PacedTransport(ObservedTransport):
    def __init__(self, path, interval=4.0, inner=None):
        super().__init__(path, inner)
        self.interval = interval
        self.last_start = None
        self.gate = asyncio.Lock()

    async def handle_async_request(self, request):
        async with self.gate:
            if self.last_start is not None:
                await asyncio.sleep(max(0, self.interval - (time.monotonic() - self.last_start)))
            self.last_start = time.monotonic()
            response = await super().handle_async_request(request)
            if response.status_code != 200:
                # Persist only bounded metadata; bodies may echo private inputs.
                value = response.headers.get("retry-after", "")
                delay = int(value) if re.fullmatch(r"[0-9]{1,5}", value) else None
                with self.path.with_name("http_diagnostics.jsonl").open("a") as stream:
                    stream.write(json.dumps({"http_status": response.status_code,
                        "retry_after_seconds": delay, "automatic_retry": False}) + "\n")
            return response


def dependencies(config):
    return {**config["source_files_sha256"], str(Path(__file__).relative_to(ROOT)): sha(__file__)}


def prepare(parent, health, out):
    parent, health, out = Path(parent).resolve(), Path(health).resolve(), Path(out).resolve()
    registered.verify(parent, parse_response)
    config, requests = registered.load(parent)
    attempts, records = registered.checkpoints(parent, config)
    state = json.loads((parent / "summary.json").read_text())
    if (config["stage"] != "core_quality_dev" or state["state"] != "stopped_by_gate"
            or set(attempts) != set(records) or not records
            or not any(r.get("http_status") == 429 for r in records.values())
            or any(r.get("http_status") in registered.FATAL_HTTP - {429} for r in records.values())):
        raise ValueError("Requires an accounted-for core quality run stopped at HTTP 429.")
    probe = json.loads((health / "health_result.json").read_text())
    protocol = json.loads((health / "health_protocol.json").read_text())
    attempt = json.loads((health / "health_attempt.json").read_text())
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(probe["completed_at"])).total_seconds()
    if (probe.get("http_status") != 200 or probe.get("finish_reason") != "stop"
            or probe.get("transport_error") or not 0 <= age <= 900
            or protocol["endpoint"] != config["endpoint"]
            or protocol["payload"]["model"] != config["model"]
            or attempt["protocol_sha256"] != sha(health / "health_protocol.json")):
        raise ValueError("A recent successful same-provider health check is required.")
    probe_tokens = probe.get("usage", {}).get("total_tokens")
    if type(probe_tokens) is not int or probe_tokens < 0:
        raise ValueError("Health probe usage is unknown.")
    budget = config["recorded_token_stop_budget"] - state["usage"]["total_tokens"] - probe_tokens
    if budget <= 0: raise ValueError("Original recorded-token budget is exhausted.")
    pending = [{k: v for k, v in r.items() if k != "request_sha256"}
               for key, r in requests.items() if key not in attempts]
    if not pending: raise ValueError("No unattempted cases remain.")
    locks = [parent / n for n in (*registered.SEALED, "registration.sha256")]
    locks += [health / n for n in ("health_protocol.json", "health_attempt.json", "health_result.json")]
    metadata = {**deepcopy(config["metadata"]), "parent_run": str(parent),
        "amendment": "Recovered provider; one worker, at least four seconds between starts. "
            "Only unattempted keys. Keep all parent errors. This does not identify the original 429 cause.",
        "provider_limits_reference": "https://docs.fptcloud.com/docs/fpt-ai-factory/services/serverless-inference/faq/",
        "health_probe_usage": probe_tokens, "unknown_prior_error_usage": state["usage_missing"],
        "parent_attempts_retained": len(attempts), "pacing_seconds": 4.0}
    child = registered.register(out, pending, stage=config["stage"], metadata=metadata,
        locks=locks, max_tokens=config["max_tokens"], token_budget=budget)
    child.update(workers=1, timeout_seconds=config["timeout_seconds"], source_files_sha256=dependencies(config))
    write_json(out / "execution.json", child)
    (out / "registration.sha256").write_text(sha(out / "execution.json") + "\n")
    return {"prepared": len(pending), "parent_retained": len(records), "recorded_token_budget": budget,
            "pacing_seconds": 4, "API_calls": 0}


async def run(out, live=False, inner=None):
    out = Path(out)
    config, _ = registered.load(out)
    if config["workers"] != 1 or config["metadata"].get("pacing_seconds") != 4:
        raise ValueError("Use the paced amendment registered by this tool.")
    transport = PacedTransport(out / "telemetry.jsonl", inner=inner) if live else None
    return await registered.run(out, parse_response, live=live, transport=transport)


def merge(child_path, out):
    child_path, out = Path(child_path).resolve(), Path(out).resolve()
    if not registered.verify(child_path, parse_response)["complete"]:
        raise ValueError("Child is incomplete; retain the gate and all pending cases.")
    child, child_requests = registered.load(child_path)
    parent = Path(child["metadata"]["parent_run"])
    registered.verify(parent, parse_response)
    original, requests = registered.load(parent)
    pa, pr = registered.checkpoints(parent, original)
    ca, cr = registered.checkpoints(child_path, child)
    if set(pa) & set(ca) or set(child_requests) != set(requests) - set(pa):
        raise ValueError("Continuation omitted or resent a key.")
    if any(r != requests[k] for k, r in child_requests.items()):
        raise ValueError("Continuation payload changed.")
    rows = [{k: v for k, v in r.items() if k != "request_sha256"} for r in requests.values()]
    locks = [p / n for p in (parent, child_path) for n in (*registered.SEALED, "registration.sha256")]
    locks += [p / "telemetry.jsonl" for p in (parent, child_path)]
    meta = {**deepcopy(original["metadata"]), "parent_run": str(parent), "continuation_run": str(child_path),
        "merged_without_inference": True, "original_429_retained": True, "pacing_changed_between_phases": True,
        "health_probe_usage_separate": child["metadata"]["health_probe_usage"]}
    config = registered.register(out, rows, stage=original["stage"], metadata=meta, locks=locks,
        max_tokens=original["max_tokens"], token_budget=original["recorded_token_stop_budget"])
    config["source_files_sha256"] = dependencies(original)
    write_json(out / "execution.json", config)
    (out / "registration.sha256").write_text(sha(out / "execution.json") + "\n")
    records = {**pr, **cr}
    write_jsonl(out / "attempts.jsonl", list({**pa, **ca}.values()))
    write_jsonl(out / "responses.jsonl", list(records.values()))
    write_json(out / "summary.json", registered.summary(config, records, "complete"))
    (out / "telemetry.jsonl").write_bytes((parent / "telemetry.jsonl").read_bytes() + (child_path / "telemetry.jsonl").read_bytes())
    write_json(out / "result_hashes.json", {n: sha(out / n) for n in registered.SEALED})
    registered.verify(out, parse_response)
    result = report(out)
    with (out / "report.md").open("a") as stream:
        stream.write("\nLượt gộp giữ HTTP 429 ban đầu. Phần chưa gửi chạy sau probe thành công, một worker, "
            "cách tối thiểu bốn giây; đây là amendment vận hành có ghi nhận. Thời điểm/tốc độ giữa hai pha khác nhau.\n")
    return {"merged_attempts": len(records), "resent_keys": 0, "API_calls": 0, "arms": result["arms"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "run", "merge"])
    parser.add_argument("--parent", type=Path)
    parser.add_argument("--health", type=Path)
    parser.add_argument("--child", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if args.command == "prepare": value = prepare(args.parent, args.health, args.out)
    elif args.command == "run": value = asyncio.run(run(args.out, args.live))
    else: value = merge(args.child, args.out)
    print(json.dumps(value, ensure_ascii=False, indent=2))
