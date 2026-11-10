"""Bounded v4/v5 dev pilot and a separate pre/post-classification RAG diagnostic.

Uses the unchanged AI references and previously prepared retrieval. No test,
model replacement, default changes, retry-based score repair or human-gold claim.
"""
import argparse
import asyncio
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
import csv
import fcntl
import json
from pathlib import Path
import random

import httpx
from sklearn.metrics import confusion_matrix, f1_score, precision_score, recall_score

from app.services.llm.client import _parse_verdict_with_validation, normalize_endpoint
from app.services.llm.policy_v5 import call_message, payload_for
from app.services.rag.explanation import build_explanation_payload, call_explanation, parse_explanation
from app.core.settings import ROOT, Settings
from evaluation.data.sms import read_jsonl, sha, write_json, write_jsonl
from evaluation.common.metrics import measure, paired_comparison
from evaluation.messages.quality_pilot import select_cases
from evaluation.messages.url_context import append, canonical_sha

SEED = 20261106
BASE_ARMS = ("v4_plain", "v5_plain")
PREPARED_RUN = ROOT / "artifacts/evaluations/components_dev_live_v1"
FATAL = {"HTTP_400", "HTTP_401", "HTTP_403", "HTTP_404", "HTTP_429"}


def selections(cases, prepared):
    selected, empty, repeats = [], [], []
    for dataset in ("sms", "url_context"):
        rows = [c for c in cases if c["dataset"] == dataset]
        order = lambda c: canonical_sha([SEED, "rag-order", c["id"]])
        available = sorted([c for c in rows if prepared[c["id"]]["retrieval"]["sources"]], key=order)
        missing = sorted([c for c in rows if not prepared[c["id"]]["retrieval"]["sources"]], key=order)
        selected += [c["id"] for c in available[:8]]
        empty += [c["id"] for c in missing[:4]]
        repeats += [c["id"] for c in sorted(rows, key=lambda c: canonical_sha([SEED, "repeat", c["id"]]))[:4]]
    if (len(selected), len(empty), len(repeats)) != (16, 8, 8):
        raise ValueError("Expected 16 source cases, 8 empty controls and 8 repeats.")
    return {"rag_with_sources": selected, "rag_no_source_controls": empty, "repeat_cases": repeats}


def registration(settings):
    cases = select_cases()
    if sha(PREPARED_RUN / "prepared.json") != (PREPARED_RUN / "prepared.sha256").read_text().strip():
        raise ValueError("Previously prepared retrieval changed.")
    prepared_all = json.loads((PREPARED_RUN / "prepared.json").read_text())
    prepared = {c["id"]: {"retrieval": prepared_all[c["id"]]["retrieval"]} for c in cases}
    selected = selections(cases, prepared)
    paths = [ROOT / name for name in ("evaluation/messages/improvement_pilot.py", "evaluation/messages/quality_pilot.py",
        "evaluation/messages/components.py", "evaluation/common/metrics.py", "evaluation/data/sms.py",
        "app/services/llm/policy_v5.py", "app/services/llm/message.py", "app/services/rag/explanation.py", "app/domain/schemas.py",
        "app/services/llm/client.py", "app/domain/validation.py", "app/core/privacy.py", "app/services/url/parsing.py", "app/core/settings.py")]
    paths += [PREPARED_RUN / "execution.json", PREPARED_RUN / "prepared.json",
              ROOT / settings.rag_corpus]
    config = {"version": "improvement-pilot-1.0", "model": settings.llm_model,
        "endpoint": normalize_endpoint(settings.endpoint, settings), "max_tokens": 8192, "timeout": 90,
        "workers": 2, "seed": SEED, "base_arms": list(BASE_ARMS), "selections": selected,
        "max_provider_attempts": 280, "recorded_token_stop_budget": 1500000,
        "cases_sha256": canonical_sha(cases), "prepared_sha256": canonical_sha(prepared),
        "source_hashes": {str(p.resolve()): sha(p) for p in paths},
        "primary_comparison": "120 identical dev inputs, v4/v5 only system prompt differs; same MessageVerdict and validator, no ML/RAG in primary arms",
        "rag_comparison": "16 predeclared source cases: v5 with references before classification versus same-source explanation after frozen v5_plain; post risk fixed by design, evaluate explanations separately",
        "no_op_controls": "8 empty-retrieval pre-RAG inputs reuse the exact v5_plain result; separate 8 repeated v5_plain requests quantify generation disagreement",
        "references": "AI-labelled SMS and authored URL contexts; previously viewed dev, not human gold",
        "test_inference": False, "model_fits": 0, "app_defaults_changed": False,
        "gates": {"context_education_min_fp_reduction": 2, "context_min_recall": .9375,
            "sms_min_recall": 8/9, "sms_max_additional_false_positives": 2,
            "min_coverage": .90, "max_coverage_drop": .05},
        "failure_policy": "One attempt per logical request; journal before sending; interrupted attempts become errors, never resent. Stop on fatal HTTP, three consecutive errors or recorded token budget. Errors retained; no model/prompt revisions inside run.",
        "statistics": "One generation/arm plus eight extra repeats. Small dev diagnostic; no independent generalization or human semantic-support claim. Post-classification label invariance is architectural, not measured classification gain."}
    return config, cases, prepared


def expected_keys(cases, config):
    keys = {(c["id"], arm) for c in cases for arm in BASE_ARMS}
    selection = config["selections"]
    for identifier in selection["rag_with_sources"] + selection["rag_no_source_controls"]:
        keys.update({(identifier, "v5_pre_rag"), (identifier, "v5_post_rag")})
    keys.update((identifier, "v5_repeat") for identifier in selection["repeat_cases"])
    return keys


def message_payload(case, arm, prepared, config):
    profile = "message-v4" if arm == "v4_plain" else "message-v5"
    sources = prepared[case["id"]]["retrieval"]["sources"] if arm == "v5_pre_rag" else []
    payload, _ = payload_for(text=case["text"], urls=[], include_ml=False, sources=sources,
        model=config["model"], max_tokens=config["max_tokens"], profile=profile)
    return payload, sources


def level(record):
    return record["verdict"]["risk_level"] if record["status"] == "ok" and "verdict" in record else "UNKNOWN"


def measurements(cases, lookup, arm):
    binary = [c for c in cases if c["targets"]["message_behavior"] is not None]
    unknown = [c for c in cases if c["targets"]["message_behavior"] is None]
    return {**measure([c["targets"]["message_behavior"] for c in binary], [level(lookup[(c["id"], arm)]) for c in binary]),
        "reference_unknown": dict(Counter(level(lookup[(c["id"], arm)]) for c in unknown)),
        "technical_errors_all_references": sum(lookup[(c["id"], arm)]["status"] == "error" for c in cases)}


def summarize(cases, config, records, attempts, state):
    lookup = {(r["id"], r["arm"]): r for r in records}
    expected = expected_keys(cases, config)
    if len(lookup) != len(records) or not set(lookup) <= expected:
        raise ValueError("Duplicate/unexpected checkpoint.")
    main_ready = all((c["id"], a) in lookup for c in cases for a in BASE_ARMS)
    result = {"all_tasks_complete": set(lookup) == expected, "main_metrics_ready": main_ready,
        "records": len(records), "expected_records": len(expected), "provider_attempts": len(attempts),
        "state": state, "metrics": None, "paired": None, "gates": None,
        "usage": {k: sum(r.get("usage", {}).get(k, 0) for r in records if not r.get("reused_from"))
                  for k in ["prompt_tokens", "completion_tokens", "total_tokens"]},
        "errors": dict(Counter(r.get("code") for r in records if r["status"] == "error"))}
    if not main_ready:
        return result
    result["metrics"], result["paired"] = {}, {}
    for dataset in ("sms", "url_context"):
        group = [c for c in cases if c["dataset"] == dataset]
        result["metrics"][dataset] = {a: measurements(group, lookup, a) for a in BASE_ARMS}
        binary = [c for c in group if c["targets"]["message_behavior"] is not None]
        result["paired"][dataset] = paired_comparison([c["targets"]["message_behavior"] for c in binary],
            *[[level(lookup[(c["id"], a)]) for c in binary] for a in BASE_ARMS])
    education = [c for c in cases if c["dataset"] == "url_context" and c["variant"].startswith("education")]
    fp = {a: sum(level(lookup[(c["id"], a)]) in {"HIGH", "WARNING"} for c in education) for a in BASE_ARMS}
    s4, s5 = (result["metrics"]["sms"][a] for a in BASE_ARMS)
    c4, c5 = (result["metrics"]["url_context"][a] for a in BASE_ARMS)
    gates = config["gates"]
    checks = {"education_false_alarms_reduced": fp["v4_plain"] - fp["v5_plain"] >= gates["context_education_min_fp_reduction"],
        "context_recall_preserved": c5["recall"] >= gates["context_min_recall"],
        "sms_recall_preserved": s5["recall"] >= gates["sms_min_recall"],
        "sms_false_alarms_controlled": s5["fp"] <= s4["fp"] + gates["sms_max_additional_false_positives"],
        "coverage_preserved": all(new["coverage"] >= gates["min_coverage"] and old["coverage"] - new["coverage"] <= gates["max_coverage_drop"] + 1e-12
                                  for old, new in [(s4, s5), (c4, c5)])}
    result["gates"] = {"checks": checks, "passed": all(checks.values()), "education_fp": fp,
                       "scope": "Predeclared dev acceptance only, not independent test evidence"}
    repeats = [c for c in cases if (c["id"], "v5_repeat") in lookup]
    result["repeats"] = {"n": len(repeats), "different_levels": sum(level(lookup[(c["id"], "v5_plain")]) != level(lookup[(c["id"], "v5_repeat")]) for c in repeats)}
    source_ids = set(config["selections"]["rag_with_sources"])
    rag_cases = [c for c in cases if c["id"] in source_ids]
    if all((c["id"], "v5_pre_rag") in lookup for c in rag_cases):
        result["rag_classification"] = {d: {a: measurements([c for c in rag_cases if c["dataset"] == d], lookup, a)
                                                   for a in ["v5_plain", "v5_pre_rag"]} for d in ["sms", "url_context"]}
    post = [r for r in records if r["arm"] == "v5_post_rag"]
    result["post_explanation"] = {"statuses": dict(Counter(r["status"] for r in post)),
        "valid_support_records": sum(bool(r.get("explanation", {}).get("support")) for r in post),
        "source_cases": len(source_ids), "classification_recomputed": False, "semantic_support_verified": False}
    return result


async def execute(out, live=False):
    settings = replace(Settings(), max_tokens=8192, timeout_seconds=90)
    config, cases, prepared = registration(settings)
    if live and not settings.api_key.strip():
        raise ValueError("API credentials unavailable.")
    if out.exists() and (not (out / "execution.json").exists() or json.loads((out / "execution.json").read_text())["configuration"] != config):
        raise ValueError("Registration changed; use a new output directory.")
    out.mkdir(parents=True, exist_ok=True)
    with (out / ".run.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not (out / "execution.json").exists():
            write_json(out / "execution.json", {"registered_at": datetime.now(timezone.utc).isoformat(), "configuration": config})
            write_jsonl(out / "cases.jsonl", cases)
            write_json(out / "prepared.json", prepared)
        if read_jsonl(out / "cases.jsonl") != cases or json.loads((out / "prepared.json").read_text()) != prepared:
            raise ValueError("Locked inputs changed.")
        rp, ap = out / "predictions.jsonl", out / "attempts.jsonl"
        records, attempts = (read_jsonl(p) if p.exists() else [] for p in [rp, ap])
        lookup = {(r["id"], r["arm"]): r for r in records}
        journal = {(r["id"], r["arm"]): r for r in attempts}
        expected = expected_keys(cases, config)
        if len(lookup) != len(records) or len(journal) != len(attempts) or not set(journal) <= expected or not set(lookup) <= expected:
            raise ValueError("Invalid checkpoint/journal.")
        for key, attempt in journal.items():
            if key not in lookup:
                record = {"id": key[0], "arm": key[1], "status": "error", "code": "INTERRUPTED_REQUEST", "usage": {}, "payload_sha256": attempt["payload_sha256"]}
                if "frozen_verdict_sha256" in attempt:
                    record["frozen_verdict_sha256"] = attempt["frozen_verdict_sha256"]
                append(rp, record); records.append(record); lookup[key] = record
        state = {"live": live, "new_calls": 0, "stop_reason": None if live else "offline_prepared"}
        def export():
            write_json(out / "summary.json", summarize(cases, config, records, attempts, state))
        export()
        if not live:
            print(json.dumps({"out": str(out), "max_calls": config["max_provider_attempts"], "API_calls": 0}), flush=True)
            return
        failures = 0
        by_id = {c["id"]: c for c in cases}
        def save(record):
            key = record["id"], record["arm"]
            if key in lookup:
                raise ValueError("Attempted to replace a saved prediction.")
            append(rp, record); records.append(record); lookup[key] = record
        async with httpx.AsyncClient(timeout=90, trust_env=False) as client:
            async def request(case, arm):
                nonlocal failures
                key = case["id"], arm
                if key in lookup or state["stop_reason"]:
                    return
                sources = prepared[case["id"]]["retrieval"]["sources"]
                if arm == "v5_pre_rag" and not sources:
                    base = lookup[(case["id"], "v5_plain")]
                    payload, _ = message_payload(case, arm, prepared, config)
                    if canonical_sha(payload) != base["payload_sha256"]:
                        raise ValueError("No-op payload differs from plain input.")
                    save({**base, "arm": arm, "reused_from": "v5_plain"})
                    return
                if arm == "v5_post_rag":
                    base = lookup[(case["id"], "v5_plain")]
                    if not sources or base["status"] != "ok":
                        save({"id": case["id"], "arm": arm, "status": "skipped", "code": "NO_SOURCES" if not sources else "CLASSIFICATION_FAILED", "usage": {}, "base_status": base["status"]})
                        return
                    payload = build_explanation_payload(approved_text=case["text"], verdict=base["verdict"], sources=sources,
                        model=config["model"], max_tokens=config["max_tokens"])
                else:
                    payload, sources = message_payload(case, arm, prepared, config)
                if len(attempts) >= config["max_provider_attempts"]:
                    state["stop_reason"] = "provider_attempt_budget"
                    return
                attempt = {"id": case["id"], "arm": arm, "payload_sha256": canonical_sha(payload), "started_at": datetime.now(timezone.utc).isoformat()}
                if arm == "v5_post_rag":
                    attempt["frozen_verdict_sha256"] = canonical_sha(base["verdict"])
                append(ap, attempt); attempts.append(attempt); state["new_calls"] += 1
                if arm == "v5_post_rag":
                    record = await call_explanation(client, endpoint=config["endpoint"], api_key=settings.api_key.strip(), payload=payload,
                        approved_text=case["text"], verdict=base["verdict"], sources=sources, timeout=90, capture_raw=True)
                    record["frozen_verdict_sha256"] = canonical_sha(base["verdict"])
                else:
                    record = await call_message(client, endpoint=config["endpoint"], api_key=settings.api_key.strip(), payload=payload,
                        text=case["text"], sources=sources, timeout=90)
                record.update(id=case["id"], arm=arm, payload_sha256=attempt["payload_sha256"])
                save(record)
                failures = failures + 1 if record["status"] == "error" else 0
                usage = sum(r.get("usage", {}).get("total_tokens", 0) for r in records if not r.get("reused_from"))
                if record.get("code") in FATAL or failures >= 3 or usage >= config["recorded_token_stop_budget"]:
                    state["stop_reason"] = record.get("code") if record.get("code") in FATAL else "three_consecutive_errors" if failures >= 3 else "recorded_token_budget"
                if len(attempts) % 10 == 0 or state["stop_reason"]:
                    export(); print(json.dumps({"attempted": len(attempts), "records": len(records), "max_calls": config["max_provider_attempts"], "errors": sum(r["status"] == "error" for r in records), "recorded_tokens": usage}), flush=True)
            async def phase(tasks):
                queue = asyncio.Queue()
                for identifier, arm in tasks:
                    if (identifier, arm) not in lookup:
                        queue.put_nowait((identifier, arm))
                async def worker():
                    while not queue.empty() and state["stop_reason"] is None:
                        identifier, arm = queue.get_nowait()
                        await request(by_id[identifier], arm)
                await asyncio.gather(*(worker() for _ in range(2)))
            ordered = list(cases)
            random.Random(SEED).shuffle(ordered)
            main_tasks = [(c["id"], a) for i, c in enumerate(ordered) for a in (BASE_ARMS if i % 2 else BASE_ARMS[::-1])]
            rag_ids = config["selections"]["rag_with_sources"] + config["selections"]["rag_no_source_controls"]
            secondary = [(identifier, arm) for i, identifier in enumerate(rag_ids) for arm in (("v5_pre_rag", "v5_post_rag") if i % 2 else ("v5_post_rag", "v5_pre_rag"))]
            secondary += [(identifier, "v5_repeat") for identifier in config["selections"]["repeat_cases"]]
            try:
                await phase(main_tasks)
                if all((c["id"], a) in lookup for c in cases for a in BASE_ARMS):
                    await phase(secondary)
            finally:
                state["stop_reason"] = state["stop_reason"] or ("all_tasks_completed" if set(lookup) == expected else "interrupted")
                export()
        print(json.dumps({"out": str(out), "state": state}), flush=True)


def verify(out):
    config = json.loads((out / "execution.json").read_text())["configuration"]
    for path, digest in config["source_hashes"].items():
        if sha(path) != digest:
            raise ValueError("Registered source/input changed: " + path)
    cases, records, attempts = (read_jsonl(out / name) for name in ["cases.jsonl", "predictions.jsonl", "attempts.jsonl"])
    prepared = json.loads((out / "prepared.json").read_text())
    if canonical_sha(cases) != config["cases_sha256"] or canonical_sha(prepared) != config["prepared_sha256"]:
        raise ValueError("Locked case/retrieval inputs changed.")
    lookup = {(r["id"], r["arm"]): r for r in records}
    journal = {(r["id"], r["arm"]): r for r in attempts}
    if len(lookup) != len(records) or len(journal) != len(attempts) or set(lookup) != expected_keys(cases, config):
        raise ValueError("Incomplete or duplicate pilot.")
    by_id = {c["id"]: c for c in cases}
    for key, record in lookup.items():
        case, arm = by_id[key[0]], key[1]
        sources = prepared[key[0]]["retrieval"]["sources"]
        if record.get("reused_from"):
            base = lookup[(key[0], "v5_plain")]
            if arm != "v5_pre_rag" or sources or {k:v for k,v in record.items() if k not in {"arm", "reused_from"}} != {k:v for k,v in base.items() if k != "arm"} or key in journal:
                raise ValueError("Invalid no-op reuse.")
        elif record["status"] == "skipped":
            if arm != "v5_post_rag" or sources and lookup[(key[0], "v5_plain")]["status"] == "ok" or key in journal:
                raise ValueError("Unexpected skipped request.")
        else:
            if key not in journal:
                raise ValueError("Provider result without journal.")
            if arm == "v5_post_rag":
                base = lookup[(key[0], "v5_plain")]
                payload = build_explanation_payload(approved_text=case["text"], verdict=base["verdict"], sources=sources, model=config["model"], max_tokens=config["max_tokens"])
                if record.get("frozen_verdict_sha256") != canonical_sha(base["verdict"]):
                    raise ValueError("Frozen classification changed.")
                if record["status"] in {"ok", "no_support"}:
                    parsed = parse_explanation(record["raw_content"], approved_text=case["text"], verdict=base["verdict"], sources=sources)
                    if parsed["explanation"] != record["explanation"] or parsed["status"] != record["status"]:
                        raise ValueError("Post-explanation parsing mismatch.")
            else:
                payload, sources = message_payload(case, arm, prepared, config)
                if record["status"] == "ok":
                    verdict, warnings, validation = _parse_verdict_with_validation(record["raw_content"], case["text"], sources or None, "message-v3")
                    if verdict.model_dump() != record["verdict"] or warnings != record["warnings"] or validation != record["validation"]:
                        raise ValueError("Message parsing mismatch.")
            if journal[key]["payload_sha256"] != canonical_sha(payload) or record["payload_sha256"] != canonical_sha(payload):
                raise ValueError("Payload hash mismatch.")
    saved = json.loads((out / "summary.json").read_text())
    recalculated = summarize(cases, config, records, attempts, saved["state"])
    if saved != recalculated:
        raise ValueError("Saved metrics disagree with checkpoints.")
    for dataset, arms in saved["metrics"].items():
        group = [c for c in cases if c["dataset"] == dataset and c["targets"]["message_behavior"] is not None]
        y = [c["targets"]["message_behavior"] for c in group]
        for arm, m in arms.items():
            levels = [level(lookup[(c["id"], arm)]) for c in group]
            # UNKNOWN negatives do not count as true negatives; adjust separately.
            p = [value in {"HIGH", "WARNING"} for value in levels]
            tn, fp, fn, tp = confusion_matrix(y, p, labels=[0,1]).ravel()
            if int(tp) != m["tp"] or int(fp) != m["fp"] or int(fn) != m["fn"] + m["unknown_positive"]:
                raise ValueError("Independent confusion check failed.")
            for name, function in [("precision", precision_score), ("recall", recall_score), ("f1", f1_score)]:
                if abs(function(y, p, zero_division=0) - m[name]) > 1e-12:
                    raise ValueError("Independent metric check failed.")
    write_json(out / "verification.json", {"verified": True, "provider_attempts": len(attempts), "records": len(records),
        "new_calls_during_verification": 0, "human_gold": False, "semantic_support_verified": False,
        "checks": "locked source/data hashes; raw responses, payloads and journal; source/input quotes; no-op reuse; fixed verdict; sklearn P/R/F1",
        "files": {n: sha(out / n) for n in ["execution.json", "cases.jsonl", "prepared.json", "predictions.jsonl", "attempts.jsonl", "summary.json"]}})
    return config, cases, records, saved


def report(out):
    config, cases, records, result = verify(out)
    fmt = lambda value: "N/A" if value is None else f"{100*value:.2f}%"
    lines = ["# v5 / character-URL / post-classification RAG: message pilot", "",
        "**Previously viewed DEV, AI SMS labels and authored contexts. Not human gold or a new test.** "
        "The URL experiment is separate; no URL scores are supplied to this pilot. One fresh generation/profile, errors retained. "
        "Only v4/v5 system rules change in the primary comparison; same schema/validator/model and input text.", "",
        f"Provider attempts: {result['provider_attempts']}/{config['max_provider_attempts']}; logical records: {result['records']}/{result['expected_records']}.", ""]
    for dataset, arms in result["metrics"].items():
        lines += ["## " + dataset, "", "| Policy | n | TP | FP | UNKNOWN +/− | P | R | F1 | FPR | Coverage |", "|---|---:|---:|---:|---|---:|---:|---:|---:|---:|"]
        for arm, m in arms.items():
            lines.append(f"| {arm} | {m['n']} | {m['tp']} | {m['fp']} | {m['unknown_positive']}/{m['unknown_negative']} | {fmt(m['precision'])} | {fmt(m['recall'])} | {fmt(m['f1'])} | {fmt(m['false_positive_rate'])} | {fmt(m['coverage'])} |")
        lines += ["", "Paired outcomes: " + json.dumps(result["paired"][dataset]), ""]
    lines += ["## Predeclared dev gates", "", json.dumps(result["gates"], ensure_ascii=False), "",
        "## RAG ordering diagnostic", "",
        "16 source-bearing cases were selected by hash before inference; 8 no-source controls reuse the exact plain response. "
        "Post-RAG cannot change the base classification by architecture. This is not evidence of improved classification. "
        "Citation exact-match checks do not establish relevance or semantic support. Manual grades remain empty.", "",
        "Pre-RAG classification: " + json.dumps(result.get("rag_classification"), ensure_ascii=False), "",
        "Post-RAG structural results: " + json.dumps(result.get("post_explanation"), ensure_ascii=False), "",
        "Independent repeat control: " + json.dumps(result.get("repeats")), "",
        "Errors: " + json.dumps(result["errors"]), "", "Recorded token usage: " + json.dumps(result["usage"]), "",
        "Usage excludes unreported tokens and is not a verified invoice. No retries, prompt revisions or test inference occurred in this run."]
    (out / "report.md").write_text("\n".join(lines) + "\n")
    by_case, lookup = {c["id"]:c for c in cases}, {(r["id"],r["arm"]):r for r in records}
    fields = ["review_id", "text", "output_status", "classification_summary", "explanation", "signal_score", "source_relevance_score", "claim_support_score", "actions_score", "notes", "rater_id"]
    mapping = {}
    with (out / "explanation_blind.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader()
        entries = [(identifier, arm) for identifier in config["selections"]["rag_with_sources"] for arm in ["v5_pre_rag", "v5_post_rag"]]
        entries.sort(key=lambda item: canonical_sha([SEED,"blind",*item]))
        for i, (identifier, arm) in enumerate(entries, 1):
            record = lookup[(identifier,arm)]; review_id=f"EX-{i:03d}"
            base = lookup[(identifier,"v5_plain")]
            writer.writerow({"review_id":review_id,"text":by_case[identifier]["text"],"output_status":record["status"],
                "classification_summary":base.get("verdict",{}).get("summary",""),
                "explanation":json.dumps(record.get("explanation", record.get("verdict",{})),ensure_ascii=False)})
            mapping[review_id]={"id":identifier,"arm":arm}
    write_json(out / "explanation_review_mapping.json",mapping)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "run", "report", "verify"])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command in {"prepare", "run"}:
            asyncio.run(execute(args.out, live=args.command == "run"))
        elif args.command == "report":
            report(args.out)
        else:
            verify(args.out)
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(2, f"Improvement pilot stopped: {exc}\n")


if __name__ == "__main__":
    main()
