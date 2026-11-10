"""Offline turn-rule replay and request-size audit, not a new LLM benchmark."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.services.llm.client import LLMFailure
from app.services.llm.compact import parse_turn_contract, payload_for
from evaluation.data.sms import read_jsonl, sha, write_json, write_jsonl
from evaluation.messages.interaction_pilot import verify


def audit(pilot: Path, out: Path):
    if out.exists():
        raise ValueError("Preserve prior audits; choose a fresh output directory.")
    verified = verify(pilot)
    if not verified["complete"]:
        raise ValueError("A complete, verified pilot is required.")
    request_rows = read_jsonl(pilot / "packs/conversation_paired/requests.jsonl")
    requests = {row["key"]: row for row in request_rows}
    old = [row for row in read_jsonl(pilot / "responses.jsonl")
           if row["pack"] == "conversation_paired" and row["key"].endswith("message-v6")]
    replayed, sizes, changed_valid = [], [], 0
    for row in old:
        request = requests[row["key"]]
        body, _, limit = payload_for(text=request["text"], urls=[], include_ml=False, sources=[],
            model=request["payload"]["model"], max_tokens=request["payload"]["max_tokens"])
        sizes.append({"key": row["key"], "old_request_chars": len(json.dumps(request["payload"]["messages"], ensure_ascii=False)),
                      "new_request_chars": len(json.dumps(body["messages"], ensure_ascii=False)),
                      "visible_turn_limit": limit})
        item = {"key": row["key"], "original_status": row["parsed"]["status"],
                "original_code": row["parsed"].get("code"), "finish_reason": row.get("finish_reason"),
                "replay_scope": "turn_rule_only; original schema length limits retained"}
        if row.get("http_status") != 200 or row.get("finish_reason") != "stop" or row.get("transport_error"):
            item["replay_status"] = "retained_transport_error"
        else:
            try:
                verdict, _, _ = parse_turn_contract(row["content"], request["text"], compact=False)
            except LLMFailure as exc:
                item.update(replay_status="error", replay_code=exc.code)
            else:
                item["replay_status"] = "accepted"
                if row["parsed"]["status"] == "ok":
                    changed_valid += verdict.model_dump() != row["parsed"]["verdict"]
        replayed.append(item)
    old_chars = sum(row["old_request_chars"] for row in sizes)
    new_chars = sum(row["new_request_chars"] for row in sizes)
    files = [Path(__file__), ROOT / "app/services/llm/compact.py", ROOT / "app/services/llm/policy_v6.py",
             ROOT / "app/api/interaction.py", pilot / "execution.json", pilot / "responses.jsonl",
             pilot / "packs/conversation_paired/requests.jsonl", pilot / "result_hashes.json"]
    result = {"scope": "offline diagnostic; no substitution into original pilot results", "API_calls": 0,
        "old_v6_records": len(old), "old_statuses": dict(Counter(row["parsed"]["status"] for row in old)),
        "turn_rule_replay": dict(Counter(row["replay_status"] for row in replayed)),
        "old_invalid_accepted_by_count_fix": sum(row["original_code"] == "OUTPUT_INVALID" and row["replay_status"] == "accepted" for row in replayed),
        "previously_valid_verdicts_changed": changed_valid,
        "request_characters": {"old_total": old_chars, "new_total": new_chars,
                               "reduction_fraction": 1 - new_chars / old_chars},
        "live_v61_success_rate": None, "truncation_improvement_measured": False,
        "notes": "Replay isolates the turn-count correction and retains the old output length limits. "
                 "The actual v6.1 app also imposes compact output bounds, which old responses were not asked to follow. "
                 "Characters are not tokens. A shorter request does not establish less reasoning or fewer truncations.",
        "input_hashes": {str(p.resolve()): sha(p) for p in files}}
    if changed_valid:
        raise ValueError("Turn-rule correction altered a previously valid verdict.")
    out.mkdir(parents=True)
    write_json(out / "summary.json", result)
    write_jsonl(out / "turn_rule_replay.jsonl", replayed)
    write_jsonl(out / "request_sizes.jsonl", sizes)
    (out / "report.md").write_text(
        "# v6.1 contract correction — offline only\n\n"
        f"Original v6 records: {len(old)}. Previously invalid completed outputs accepted by the isolated turn fix: "
        f"{result['old_invalid_accepted_by_count_fix']}. Previously valid verdicts changed: {changed_valid}.\n\n"
        f"Request characters across the same inputs: {old_chars} → {new_chars} "
        f"({result['request_characters']['reduction_fraction']:.1%} reduction). Not a token or latency measurement.\n\n"
        + result["notes"] + "\n\nNo provider requests, new phishing F1 or repaired old pilot score.\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot", type=Path, default=ROOT / "artifacts/evaluations/v6_pilot_live_20261109")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.pilot, args.out)
    print(json.dumps({key: value for key, value in result.items() if key != "input_hashes"}, ensure_ascii=False, indent=2))
