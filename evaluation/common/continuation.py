"""Continue unattempted payloads after a transport gate; preserve prior results."""
import argparse
from copy import deepcopy
import json
from pathlib import Path

from app.core.settings import ROOT
from evaluation.common import registered
from evaluation.data.sms import sha, write_json, write_jsonl


def dependencies(config):
    # Inherit the exact parent dependency set, plus this continuation code.
    # Files added later for unrelated experiments do not reinterpret old data.
    return {**config["source_files_sha256"], str(Path(__file__).relative_to(ROOT)): sha(__file__)}


def prepare(parent, out, parser, *, timeout=180):
    parent, out = Path(parent).resolve(), Path(out).resolve()
    registered.verify(parent, parser)
    config, requests = registered.load(parent)
    attempts, records = registered.checkpoints(parent, config)
    previous = json.loads((parent / "summary.json").read_text())
    if previous["usage"]["total_tokens"] >= config["recorded_token_stop_budget"]:
        raise ValueError("The registered token budget is exhausted.")
    if (previous["state"] != "stopped_by_gate" or set(attempts) != set(records) or not records
            or not any(r.get("transport_error") for r in records.values())
            or any(r.get("http_status") in registered.FATAL_HTTP for r in records.values())):
        raise ValueError("Continuation requires an accounted-for transport stop; never bypass HTTP permission/budget gates.")
    pending = [{k: v for k, v in row.items() if k != "request_sha256"} for key, row in requests.items() if key not in attempts]
    if not pending: raise ValueError("No unattempted payloads remain.")
    locks = [parent / name for name in (*registered.SEALED, "registration.sha256")]
    meta = {**deepcopy(config["metadata"]), "parent_run": str(parent), "parent_attempts_retained": len(attempts)}
    child = registered.register(out, pending, stage=config["stage"], metadata=meta, locks=locks,
        max_tokens=config["max_tokens"], token_budget=max(1, config["recorded_token_stop_budget"] - previous["usage"]["total_tokens"]))
    child["source_files_sha256"] = dependencies(config)
    child["timeout_seconds"] = timeout
    child["continuation_note"] = "New timeout applies only to unattempted keys; prior successes and failures remain unchanged."
    write_json(out / "execution.json", child)
    (out / "registration.sha256").write_text(sha(out / "execution.json") + "\n")
    return {"prepared": len(pending), "prior_attempts_retained": len(attempts), "new_timeout_seconds": timeout, "API_calls": 0}


def merge(child_path, out, parser):
    child_path, out = Path(child_path).resolve(), Path(out).resolve()
    child, child_requests = registered.load(child_path)
    if not registered.verify(child_path, parser)["complete"]:
        raise ValueError("Child is incomplete; do not manufacture unattempted results.")
    parent = Path(child["metadata"]["parent_run"])
    registered.verify(parent, parser)
    original, requests = registered.load(parent)
    pa, pr = registered.checkpoints(parent, original)
    ca, cr = registered.checkpoints(child_path, child)
    if set(pa) & set(ca) or set(child_requests) != set(requests) - set(pa):
        raise ValueError("Continuation inventory resends or omits keys.")
    if any(row != requests[key] for key, row in child_requests.items()):
        raise ValueError("Continued payload differs from original request.")
    rows = [{k: v for k, v in row.items() if k != "request_sha256"} for row in requests.values()]
    meta = {**deepcopy(original["metadata"]), "merged_without_new_inference": True,
            "parent_run": str(parent), "continuation_run": str(child_path), "timeouts": [original["timeout_seconds"], child["timeout_seconds"]]}
    locks = [folder / name for folder in (parent, child_path) for name in (*registered.SEALED, "registration.sha256")]
    config = registered.register(out, rows, stage=original["stage"], metadata=meta, locks=locks,
        max_tokens=original["max_tokens"], token_budget=original["recorded_token_stop_budget"])
    config["source_files_sha256"] = dependencies(original)
    write_json(out / "execution.json", config)
    (out / "registration.sha256").write_text(sha(out / "execution.json") + "\n")
    attempts, records = {**pa, **ca}, {**pr, **cr}
    write_jsonl(out / "attempts.jsonl", list(attempts.values()))
    write_jsonl(out / "responses.jsonl", list(records.values()))
    write_json(out / "summary.json", registered.summary(config, records, "complete"))
    write_json(out / "result_hashes.json", {name: sha(out / name) for name in registered.SEALED})
    registered.verify(out, parser)
    return {"merged_attempts": len(attempts), "resent_keys": 0, "API_calls": 0}


def main():
    from evaluation.data.fresh_dev import parse_labels
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare-labels", "merge-labels"])
    parser.add_argument("--parent", type=Path)
    parser.add_argument("--child", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.parent, args.out, parse_labels) if args.command == "prepare-labels" else merge(args.child, args.out, parse_labels)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
