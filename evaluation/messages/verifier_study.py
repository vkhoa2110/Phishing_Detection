"""Conditional, input-blinded verifier study on the frozen eighty dev messages.

The original core run is immutable. This module prepares and reports a separate
experimental projection; agreement with provisional AI labels is not real-world
accuracy or independent ground truth. No application setting is changed.
"""
import argparse
import asyncio
from collections import Counter
import json
from pathlib import Path

from app.core.settings import ROOT
from evaluation.common import controlled_run, registered
from evaluation.common.metrics import measure
from evaluation.data.sms import read_jsonl, sha, write_json, write_jsonl
from evaluation.messages.interaction_pilot import now
from evaluation.messages.semantic_verifier import ALARM_LEVELS, MAX_TOKENS, build_payload, parse_response, revision
from evaluation.messages import url_score_control as control
from evaluation.messages.url_context import canonical_sha

STAGE = "conditional_semantic_verifier_dev"
ZERO_SCHEMA = "zero-verifier-study-1.0"


def gate_cells(control_run, cfg, requests, records, cells, sms, references):
    """Bind each logical arm to its untouched request/response and alarm gate."""
    refs = {row["id"]: row["label"] for row in references}
    by_id = {row["id"]: row for row in sms}
    expected = {(case_id, arm) for case_id in by_id for arm in control.ARMS}
    if (len(sms) != 80 or len(by_id) != 80 or len(references) != 80 or set(refs) != set(by_id)
            or Counter(refs.values()) != Counter({0: 54, 1: 4, None: 22})
            or any(value is not None and type(value) is not int for value in refs.values())
            or len(cells) != len(expected) or {(r["id"], r["arm"]) for r in cells} != expected):
        raise ValueError("Exactly three complete arms over the frozen 80 cases and 4/54/22 labels are required.")
    gates, unique = [], {}
    for cell in cells:
        key = (cfg["stage"], cell["request_key"])
        request, record = requests[key], records[key]
        text = request["text"]
        if text != by_id[cell["id"]]["text"]:
            raise ValueError("The control request must use the exact frozen approved text.")
        parsed = record["parsed"]
        level = parsed["verdict"]["risk_level"] if parsed["status"] == "ok" else "UNKNOWN"
        if level not in {"HIGH", "WARNING", "LOW", "UNKNOWN"}:
            raise ValueError("Invalid completed control level.")
        eligible = parsed["status"] == "ok" and level in ALARM_LEVELS
        verifier_key = None
        if eligible:
            payload = build_payload(text, cfg["model"])
            verifier_key = "verify-" + canonical_sha(payload)
            unique.setdefault(verifier_key, {"key": verifier_key, "text": text, "payload": payload})
        gates.append({**cell, "reference": refs[cell["id"]], "text": text,
            "approved_text_sha256": canonical_sha(text), "eligible": eligible, "verifier_key": verifier_key,
            "original_level": level, "original_status": parsed["status"], "original_error": parsed.get("code"),
            "original_record": record, "original_record_sha256": canonical_sha(record),
            "original_response_path": str(Path(control_run).resolve() / "responses.jsonl"),
            "original_request": request, "original_request_sha256": canonical_sha(request),
            "original_request_path": str(Path(control_run).resolve() / "requests.jsonl")})
    if {cell["request_key"] for cell in cells} != {key[1] for key in requests} or set(requests) != set(records):
        raise ValueError("Every completed control request must be accounted for by the logical cells.")
    return gates, sorted(unique.values(), key=lambda row: row["key"])


def _control_snapshot(control_run):
    control_run = Path(control_run).resolve()
    if not registered.verify(control_run, control.parse_response)["complete"]:
        raise ValueError("Complete and seal the control run before selecting alarms.")
    cfg, requests = registered.load(control_run)
    if tuple(cfg["metadata"].get("arms", ())) != control.ARMS:
        raise ValueError("The preregistered three-arm control is required.")
    _, records = registered.checkpoints(control_run, cfg)
    meta = cfg["metadata"]
    sms, refs, _ = control.load_scope(meta["pack"], meta["labels"])
    cells_path = Path(meta["inputs"]) / "cells.jsonl"
    gates, rows = gate_cells(control_run, cfg, requests, records, read_jsonl(cells_path), sms, refs)
    summary = json.loads((control_run / "summary.json").read_text())
    used = summary["usage"]["total_tokens"]
    health = meta.get("healthprobe_tokens", 0)
    if any(type(value) is not int or value < 0 for value in (used, health)):
        raise ValueError("Recorded token counts must be nonnegative integers.")
    locks = [control_run / name for name in (*registered.SEALED, "result_hashes.json", "registration.sha256")]
    locks += [cells_path, Path(meta["labels"]) / "labels.jsonl", Path(meta["labels"]) / "labels_manifest.json"]
    return cfg, gates, rows, used, health, locks


def prepare(control_run, out, total_budget=300000):
    """Register one blind request per distinct alarm text, reusing it across arms."""
    control_run, out = Path(control_run).resolve(), Path(out).resolve()
    inputs = out.with_name(out.name + "_inputs")
    if out.exists() or inputs.exists():
        raise ValueError("Choose fresh verifier output and input directories.")
    if type(total_budget) is not int or total_budget <= 0:
        raise ValueError("A positive total recorded token budget is required.")
    cfg, gates, rows, used, health, locks = _control_snapshot(control_run)
    remaining = total_budget - used - health
    if rows and remaining <= 0:
        raise ValueError("The combined recorded token budget is exhausted.")
    inputs.mkdir(parents=True)
    write_jsonl(inputs / "gate_cells.jsonl", gates)
    aliases = [{"verifier_key": row["key"], "approved_text_sha256": canonical_sha(row["text"]),
        "cells": [{"id": gate["id"], "arm": gate["arm"], "control_request_key": gate["request_key"]}
                  for gate in gates if gate["verifier_key"] == row["key"]]} for row in rows]
    write_jsonl(inputs / "aliases.jsonl", aliases)
    locks += [inputs / "gate_cells.jsonl", inputs / "aliases.jsonl"]
    metadata = {"control_run": str(control_run), "inputs": str(inputs), "labels": cfg["metadata"]["labels"],
        "arms": list(control.ARMS), "messages": 80, "logical_cells": len(gates),
        "eligible_alarm_cells": sum(g["eligible"] for g in gates), "unique_verifier_requests": len(rows),
        "aliased_alarm_cells": sum(g["eligible"] for g in gates) - len(rows),
        "reference_counts": {"positive": 4, "negative": 54, "UNKNOWN": 22},
        "reference_status": "ai_preliminary_not_gold", "independent_accuracy": None,
        "reference_judge": cfg["metadata"].get("reference_judge", "provider_ai"),
        "same_provider_second_opinion_not_independent_gold": True,
        "conditional_selection": "Only completed valid HIGH/WARNING per arm; union by identical approved text",
        "payload_blinding": "Only approved text and output schema; no original verdict, reason, URL score, arm or reference",
        "original_records_preserved": True, "promote_application": False, "reserve_inference": False,
        "pacing_seconds": 4, "pilot_unique_requests": min(4, len(rows)),
        "total_recorded_token_budget": total_budget, "control_recorded_tokens": used,
        "healthprobe_recorded_tokens": health, "remaining_recorded_token_budget": remaining,
        "token_usage_missing_control": json.loads((control_run / "summary.json").read_text()).get("usage_missing", 0),
        "cost": None, "cost_status": "unknown; no provider price assumed",
        "quality_scope": "Conditional development agreement with frozen provisional AI behavior labels; no real-world accuracy claim"}
    if not rows:
        out.mkdir(parents=True)
        sources = sorted((ROOT / "app").rglob("*.py")) + sorted((ROOT / "evaluation").rglob("*.py"))
        zero = {"schema": ZERO_SCHEMA, "registered_at": now(), "metadata": metadata, "max_attempts": 0,
            "input_files_sha256": {str(path.resolve()): sha(path) for path in locks},
            "source_files_sha256": {str(path.resolve()): sha(path) for path in sources}}
        write_json(out / "zero_verifier.json", zero)
        (out / "zero_verifier.sha256").write_text(sha(out / "zero_verifier.json") + "\n")
        report(out)
        return zero
    config = registered.register(out, rows, stage=STAGE, metadata=metadata, locks=locks,
                                 max_tokens=MAX_TOKENS, token_budget=remaining)
    config.update(workers=1, timeout_seconds=45)
    write_json(out / "execution.json", config)
    (out / "registration.sha256").write_text(sha(out / "execution.json") + "\n")
    return config


def verify(out):
    out = Path(out)
    if not (out / "zero_verifier.json").exists():
        return registered.verify(out, parse_response)
    if sha(out / "zero_verifier.json") != (out / "zero_verifier.sha256").read_text().strip():
        raise ValueError("Zero-verifier manifest changed.")
    cfg = json.loads((out / "zero_verifier.json").read_text())
    if cfg["schema"] != ZERO_SCHEMA or cfg["max_attempts"] != 0:
        raise ValueError("Invalid zero-verifier artifact.")
    for group in ("input_files_sha256", "source_files_sha256"):
        if any(not Path(path).is_file() or sha(path) != expected for path, expected in cfg[group].items()):
            raise ValueError("A locked zero-verifier input or source changed.")
    return {"verified": True, "complete": True, "attempts": 0, "API_calls": 0}


async def run(out, *, live=False, limit=None, inner=None):
    if (Path(out) / "zero_verifier.json").exists():
        return {**verify(out), "state": "complete", "requests": 0}
    return await controlled_run.run(out, parse_response, live=live, limit=limit, inner=inner)


def summarize(gates, decisions):
    """Compute paired projections while retaining errors and unknown references."""
    rows = []
    for gate in gates:
        changed = revision(gate["original_level"], decisions[gate["verifier_key"]]) if gate["eligible"] else {
            "original_level": gate["original_level"], "level": gate["original_level"],
            "status": "not_eligible", "needs_review": gate["original_status"] != "ok"}
        rows.append({**gate, "revision": changed,
            "verifier_parsed": decisions[gate["verifier_key"]] if gate["eligible"] else None})
    result = {"reference_status": "ai_preliminary_not_gold", "independent_accuracy": None,
        "quality_scope": "Conditional development agreement with provisional AI behavior references; not whole-message safety or real-world accuracy",
        "policy": "Original technical errors remain errors; verifier insufficient/error preserves the original alarm and requires review",
        "messages": 80, "logical_cells": len(rows), "arms": {},
        "eligible_alarm_cells": sum(row["eligible"] for row in rows), "unique_verifier_requests": len(decisions),
        "aliased_alarm_cells": sum(row["eligible"] for row in rows) - len(decisions)}
    for arm in control.ARMS:
        selected = [row for row in rows if row["arm"] == arm]
        binary = [row for row in selected if row["reference"] is not None]
        gated = [row for row in selected if row["eligible"]]
        gated_binary = [row for row in gated if row["reference"] is not None]
        def metrics(items, after):
            return measure([row["reference"] for row in items],
                [row["revision"]["level"] if after else row["original_level"] for row in items])
        result["arms"][arm] = {"all_58_binary": {"before": metrics(binary, False), "after": metrics(binary, True)},
            "gated_binary_subset": {"n": len(gated_binary), "before": metrics(gated_binary, False), "after": metrics(gated_binary, True)},
            "all_80": {"n": len(selected), "original_technical_errors": sum(row["original_status"] != "ok" for row in selected),
                "original_error_codes": dict(Counter(row["original_error"] for row in selected if row["original_status"] != "ok")),
                "gated_alarm_cells": len(gated), "revision_statuses": dict(Counter(row["revision"]["status"] for row in gated)),
                "needs_review": sum(row["revision"]["needs_review"] for row in selected)},
            "unknown_22_reference": {"n": sum(row["reference"] is None for row in selected),
                "before": dict(Counter(row["original_level"] for row in selected if row["reference"] is None)),
                "after": dict(Counter(row["revision"]["level"] for row in selected if row["reference"] is None))},
            "alarm_transitions": {"FP_to_LOW": sum(row["reference"] == 0 and row["revision"]["level"] == "LOW" for row in gated),
                "TP_to_LOW": sum(row["reference"] == 1 and row["revision"]["level"] == "LOW" for row in gated),
                "unknown_reference_to_LOW": sum(row["reference"] is None and row["revision"]["level"] == "LOW" for row in gated),
                "kept_supported": sum(row["revision"]["status"] == "supported_alarm" for row in gated),
                "kept_insufficient": sum(row["revision"]["status"] == "insufficient" for row in gated),
                "kept_technical_error": sum(row["revision"]["status"] == "technical_error" for row in gated),
                "alarm_to_UNKNOWN": sum(row["revision"]["level"] == "UNKNOWN" for row in gated)}}
    positives = []
    for case_id in sorted({row["id"] for row in rows if row["reference"] == 1}):
        case_rows = [row for row in rows if row["id"] == case_id]
        positives.append({"id": case_id, "text": case_rows[0]["text"], "reference": 1,
            "arms": {row["arm"]: {"before_level": row["original_level"], "original_status": row["original_status"],
                "original_error": row["original_error"], "eligible": row["eligible"], "verifier_key": row["verifier_key"],
                "after_level": row["revision"]["level"], "revision_status": row["revision"]["status"],
                "needs_review": row["revision"]["needs_review"], "verifier_parsed": row["verifier_parsed"]} for row in case_rows}})
    result["all_four_positive_cases"] = positives
    return result, rows


def report(out):
    out = Path(out)
    if not verify(out)["complete"]:
        raise ValueError("Complete and seal every verifier attempt before reporting quality.")
    zero = (out / "zero_verifier.json").exists()
    if zero:
        cfg = json.loads((out / "zero_verifier.json").read_text())
        records, actual_requests = {}, {}
    else:
        cfg, actual_requests = registered.load(out)
        _, records = registered.checkpoints(out, cfg)
    meta = cfg["metadata"]
    # Replaying the original control verifies full records, source/input locks,
    # and the gate selection rather than trusting the saved projection alone.
    _, expected_gates, expected_requests, _, _, _ = _control_snapshot(meta["control_run"])
    gates = read_jsonl(Path(meta["inputs"]) / "gate_cells.jsonl")
    if gates != expected_gates or len(expected_requests) != len(records):
        raise ValueError("Verifier gates or request inventory differ from the original sealed control.")
    actual_payloads = {key[1]: {field: value for field, value in request.items() if field != "request_sha256"}
                       for key, request in actual_requests.items()}
    if actual_payloads != {request["key"]: request for request in expected_requests}:
        raise ValueError("Registered verifier payloads differ from the exact blinded gated union.")
    decisions = {key[1]: row["parsed"] for key, row in records.items()}
    if set(decisions) != {row["key"] for row in expected_requests}:
        raise ValueError("Verifier response aliases differ from the gated union.")
    result, rows = summarize(gates, decisions)
    result["operations"] = {"verifier_requests": len(records),
        "valid": sum(row["parsed"]["status"] == "ok" for row in records.values()),
        "errors": dict(Counter(row["parsed"].get("code") for row in records.values() if row["parsed"]["status"] != "ok")),
        "verifier_recorded_tokens": sum(row.get("usage", {}).get("total_tokens", 0) for row in records.values()),
        "usage_missing": sum("total_tokens" not in row.get("usage", {}) for row in records.values()),
        "control_recorded_tokens": meta["control_recorded_tokens"], "healthprobe_recorded_tokens": meta["healthprobe_recorded_tokens"],
        "total_recorded_token_budget": meta["total_recorded_token_budget"], "cost": None, "cost_status": "unknown"}
    result["operations"]["combined_recorded_tokens"] = (result["operations"]["verifier_recorded_tokens"]
        + meta["control_recorded_tokens"] + meta["healthprobe_recorded_tokens"])
    result["application_promoted"] = False
    write_jsonl(out / "gate_results.jsonl", rows)
    write_json(out / "verifier_report.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run", "verify", "report"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--control-run", type=Path)
    parser.add_argument("--total-budget", type=int, default=300000)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.command == "prepare":
        if args.control_run is None: parser.error("prepare requires --control-run")
        cfg = prepare(args.control_run, args.out, args.total_budget)
        value = {"requests": cfg["max_attempts"], "API_calls": 0, "metadata": cfg["metadata"]}
    elif args.command == "run": value = asyncio.run(run(args.out, live=args.live, limit=args.limit))
    elif args.command == "verify": value = verify(args.out)
    else: value = report(args.out)
    print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
