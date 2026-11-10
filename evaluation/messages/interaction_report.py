"""Report frozen pilot outputs without inventing human semantic labels."""
import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import shutil
import statistics

from app.services.llm.client import LLMFailure
from app.services.llm.policy_v6 import conversation_turns, parse_v6
import evaluation.rag.controlled as controlled
from evaluation.data.sms import read_jsonl, sha, write_json, write_jsonl
from evaluation.messages.url_context import canonical_sha
from evaluation.messages.interaction_pilot import PACKS, checkpoints, load, verify


def conversation_summary(records, requests):
    rows = [row for (kind, _), row in records.items() if kind == PACKS[1]]
    groups = {}
    for profile in ("message-v5", "message-v6"):
        selected = [row for row in rows if row["key"].endswith(profile)]
        groups[profile] = {"n": len(selected), "valid": sum(row["parsed"]["status"] == "ok" for row in selected),
            "errors": dict(Counter(row["parsed"].get("code") for row in selected if row["parsed"]["status"] == "error")),
            "usage": {key: sum(row["usage"].get(key, 0) for row in selected) for key in
                      ("prompt_tokens", "completion_tokens", "total_tokens")},
            "median_elapsed_ms": statistics.median(row["elapsed_ms"] for row in selected) if selected else None}
    def decision(row):
        return row["parsed"]["verdict"]["risk_level"] if row["parsed"]["status"] == "ok" else "ERROR:" + row["parsed"]["code"]
    profiles = defaultdict(dict)
    for row in rows:
        prefix, profile = row["key"].rsplit("::", 1)
        profiles[prefix][profile] = row
    agreement = Counter()
    for pair in profiles.values():
        if len(pair) != 2:
            agreement["missing_record"] += 1
        elif all(row["parsed"]["status"] == "ok" for row in pair.values()):
            agreement["valid_agree" if len({decision(row) for row in pair.values()}) == 1 else "valid_disagree"] += 1
        else:
            agreement["at_least_one_error"] += 1
    trajectories = []
    for thread in sorted({row["key"].split("::")[0] for row in rows}):
        for profile in groups:
            visible = []
            for prefix in (1, 2, 3):
                row = records.get((PACKS[1], f"{thread}::p{prefix}::full_history::{profile}"))
                visible.append(decision(row) if row else "MISSING")
            trajectories.append({"thread": thread, "profile": profile, "decisions": visible,
                "first_alert_prefix": next((i + 1 for i, risk in enumerate(visible) if risk in {"HIGH", "WARNING"}), None),
                "supported_warning_time_verified": False})
    # The p1 history arms are identical payloads, not additional context.
    identical = Counter()
    for profile in groups:
        for thread in sorted({row["key"].split("::")[0] for row in rows}):
            keys = [(PACKS[1], f"{thread}::p1::{history}::{profile}") for history in ("full_history", "last_turn_only")]
            if all(key in records for key in keys):
                if canonical_sha(requests[keys[0]]["payload"]) != canonical_sha(requests[keys[1]]["payload"]):
                    raise ValueError("A registered p1 duplicate pair differs.")
                pair = [records[key] for key in keys]
                identical["pairs"] += 1
                if all(row["parsed"]["status"] == "ok" for row in pair):
                    identical["valid_agree" if decision(pair[0]) == decision(pair[1]) else "valid_disagree"] += 1
                else:
                    identical["at_least_one_error"] += 1
    return {"profiles": groups, "paired_risk_agreement": dict(agreement),
            "identical_payload_pairs": dict(identical), "full_history_trajectories": trajectories,
            "accuracy": None, "F1": None, "thread_units": 6,
            "semantic_labels": "blank; no supported early-warning or false-alarm rate inferred"}


def report(out: Path):
    checked = verify(out)
    config, requests = load(out)
    _, records = checkpoints(out, config)
    if not checked["complete"]:
        raise ValueError("Retain and report the stopped run before attempting a new protocol.")
    scored = out / "rag_scored"
    if not scored.exists():
        shutil.copytree(out / "packs" / PACKS[0], scored)
        responses = out / "rag_responses.jsonl"
        write_jsonl(responses, [{key: value for key, value in row.items() if key not in {"pack", "parsed"}}
                              for (kind, _), row in records.items() if kind == PACKS[0]])
        rag = controlled.score(scored, responses)
        write_json(out / "rag_score_hashes.json", {name: sha(out / name) for name in (
            "rag_scored/summary.json", "rag_scored/parsed_responses.jsonl", "rag_responses.jsonl")})
    else:
        hashes = json.loads((out / "rag_score_hashes.json").read_text())
        if any(sha(out / name) != expected for name, expected in hashes.items()):
            raise ValueError("Derived RAG score changed.")
        rag = json.loads((scored / "summary.json").read_text())
    conversation = conversation_summary(records, requests)
    write_json(out / "conversation_summary.json", conversation)
    diagnostics = []
    for key, row in records.items():
        if row["parsed"]["status"] != "error":
            continue
        detail = {"pack": key[0], "key": key[1], "code": row["parsed"]["code"],
                  "finish_reason": row.get("finish_reason"), "usage": row["usage"]}
        if key[0] == PACKS[1] and key[1].endswith("message-v6") and row.get("finish_reason") == "stop":
            try:
                parse_v6(row.get("content") or "", requests[key]["text"])
            except LLMFailure as exc:
                detail["validator_message"] = exc.message
            try:
                raw = json.loads(row.get("content") or "")
                detail["declared_turns"] = raw.get("interaction", {}).get("conversation_turns_used")
                detail["parsed_turn_limit"] = len(conversation_turns(requests[key]["text"]))
                detail["single_turn_contract_conflict"] = detail["declared_turns"] == 1 and detail["parsed_turn_limit"] == 0
            except (ValueError, TypeError, AttributeError):
                detail["valid_json"] = False
        diagnostics.append(detail)
    write_jsonl(out / "error_diagnostics.jsonl", diagnostics)
    single_conflicts = sum(row.get("single_turn_contract_conflict", False) for row in diagnostics)
    retrieved_source_counts = {request["case_id"]: len(request["sources"])
                              for (kind, key), request in requests.items()
                              if kind == PACKS[0] and key.endswith("::retrieved")}
    sheet = out / "conversation_output_review.csv"
    if not sheet.exists():
        fields = ["blind_output_id", "input_text", "output_status", "risk_prediction", "output_json",
                  "risk_reference", "evidence_support_0_2", "role_correct_0_2", "reviewer_id", "notes"]
        with sheet.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader()
            for key, row in sorted(records.items(), key=lambda item: canonical_sha(item[0])):
                if key[0] != PACKS[1]:
                    continue
                writer.writerow({"blind_output_id": "CVOUT-" + canonical_sha(key)[:12],
                    "input_text": requests[key]["text"], "output_status": row["parsed"]["status"],
                    "risk_prediction": row["parsed"].get("verdict", {}).get("risk_level", "UNKNOWN"),
                    "output_json": json.dumps(row["parsed"].get("verdict", {}), ensure_ascii=False)})
    lines = ["# Pilot v6 — 09/11/2026", "", "102 actual one-shot provider requests on authored development inputs. "
        "Raw responses and attempts are sealed and replayed offline. No independent phishing labels or human semantic grades.",
        "", "## Conversation profiles", "", "| Profile | Requests | Valid | Errors | Recorded tokens | Median seconds |",
        "|---|---:|---:|---:|---:|---:|"]
    for profile, values in conversation["profiles"].items():
        lines.append(f"| {profile} | {values['n']} | {values['valid']} | {values['n'] - values['valid']} | "
                     f"{values['usage']['total_tokens']} | {values['median_elapsed_ms'] / 1000:.2f} |")
    lines += ["", "72 requests represent only six threads, three prefixes, two history conditions and two profiles. "
        "Thirty distinct displayed inputs; repeated p1 payloads expose stochastic/format failures, not a history benefit. "
        "The max output cap is 2,048 in both profiles; v6 must emit additional interaction fields.",
        "", "Errors by profile: `" + json.dumps({p: v["errors"] for p, v in conversation["profiles"].items()}) + "`.",
        "", f"Single-turn contract conflicts in v6: {single_conflicts}. The frozen parser returns no conversation "
        "for a single labelled line, while the model reports one turn. These remain original errors; no repaired prediction is substituted.",
        "", "Paired risk agreement, not correctness: `" + json.dumps(conversation["paired_risk_agreement"]) + "`.",
        "", "## Controlled RAG", "", "| Condition | Requests | Support selected | No support | Error | Target control span selected |",
        "|---|---:|---:|---:|---:|---:|"]
    for condition, values in rag["structural_results"].items():
        lines.append(f"| {condition} | {values['n']} | {values['ok']} | {values['no_support']} | {values['error']} | {values['selected_control_target']} |")
    lines += ["", "Support selection is structural, not verified relevance. A target-span selection is an attack diagnostic, "
        "not a fully evaluated attack-success rate. Inputs are not token-budget-matched. Removing the design sentence "
        "does not prove remaining context is insufficient. Classification was frozen before RAG.",
        "", "Number of retrieved source documents per case: `" + json.dumps(retrieved_source_counts) + "`. "
        "Component collection still sends empty-source requests; the application may skip explanation when sources are empty, "
        "so this is not an end-to-end app latency/cost benchmark.",
        "", "## Full-history warning trajectories", "", "| Thread | Profile | Prefix 1 | Prefix 2 | Prefix 3 |",
        "|---|---|---|---|---|"]
    for row in conversation["full_history_trajectories"]:
        lines.append("| " + " | ".join([row["thread"], row["profile"], *row["decisions"]]) + " |")
    lines += ["", "These are predictions only. Prefix risk and the first supported warning still need semantic labels. "
        "Do not label every early prefix with the final thread's risk.",
        "", "## Resource use and limits", "", f"RAG recorded tokens: {rag['usage']['total_tokens']}. "
        f"Conversation recorded tokens: {sum(v['usage']['total_tokens'] for v in conversation['profiles'].values())}. "
        "Usage is provider telemetry, not a verified bill; monetary cost is unavailable without a price contract. "
        "Every truncation, malformed output and validation failure remains in the denominator. No retries or JSON repair.",
        "", "Human review sheets: `rag_scored/semantic_review.csv`, `conversation_output_review.csv`, "
        "and `packs/conversation_paired/input_review.csv`. Output schemas can reveal the profile, so masking identifiers "
        "does not make the output review fully blind.", ""]
    (out / "report.md").write_text("\n".join(lines))
    write_json(out / "verification.json", checked)
    return {"verified": checked, "conversation": conversation["profiles"], "rag": rag["structural_results"],
            "classification_accuracy_available": False, "independent_semantic_labels": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(report(args.out), ensure_ascii=False, indent=2))
