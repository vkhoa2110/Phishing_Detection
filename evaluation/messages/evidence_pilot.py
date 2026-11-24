"""A small registered development pilot on reconstructed, source-backed cases.

The classifier target is visible message actions. RAG is post-classification;
its logical arms share a frozen classifier response, never a new verdict.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
import csv
from pathlib import Path
import json
import shutil

from app.core.privacy import redact
from app.core.settings import ROOT, Settings
from app.services.llm.client import approved_ml_metadata
from app.services.llm.core import PROFILE, build_payload
from app.services.llm.telemetry import fingerprint
from app.services.url.character import CharURLService
from evaluation.common import controlled_run, registered
from evaluation.common.metrics import measure, paired_comparison, prediction
from evaluation.data import evidence_messages
from evaluation.data.sms import read_jsonl, sha, spreadsheet_cell, write_json, write_jsonl
from evaluation.messages.core_pilot import parse_response
from evaluation.messages.url_context import canonical_sha
from evaluation.messages.url_score_control import score_cases, _operations

SEED = 20261119
PACK = ROOT / "artifacts/evaluations/evidence_messages_20261118/pack"
BASE_ARMS = ("llm_only", "llm_url")
ARMS = (*BASE_ARMS, "llm_rag_post", "llm_url_rag_post")
PRIMARY_SCOPE = "consensus_behavior_label"


def development(pack):
    pack = Path(pack).resolve()
    evidence_messages.verify(pack)
    rows = read_jsonl(pack / "cases.jsonl")
    return [r for r in rows if r["split"] == "dev"]


def validate_review(rows, inputs, reviewer):
    expected = {r["id"]: r["text"] for r in inputs}
    if len(rows) != len(expected) or {r["id"] for r in rows} != set(expected):
        raise ValueError("Review inventory must match all development base inputs exactly.")
    for row in rows:
        label = row.get("behavior_label")
        if label is not None and (type(label) is not int or label not in (0, 1)):
            raise ValueError("Review label must be integer0/1/null.")
        quote = row.get("quote", "")
        if label is not None and (not quote or len(quote) > 240 or quote not in expected[row["id"]]):
            raise ValueError("Binary reviews require an exact bounded input quote.")
        if label is None and quote:
            raise ValueError("Uncertain reviews must not assert an action quote.")
        if row.get("human_gold") is not False or row.get("reviewer") != reviewer or not row.get("notes"):
            raise ValueError("Explicit AI reviewer identity, notes and non-gold scope are required.")
    return {r["id"]: r for r in rows}


def reference_pack(root, pack=PACK):
    """Keep original labels and separate blind AI agreement; no gold promotion."""
    root = Path(root).resolve()
    target = root / "reference"
    if target.exists():
        raise ValueError("Preserve the earlier reference version; use a fresh directory.")
    dev = [r for r in development(pack) if not r.get("base_id")]
    inputs = read_jsonl(root / "blind_dev_inputs.jsonl")
    if {r["id"]: r["text"] for r in inputs} != {r["id"]: r["text"] for r in dev}:
        raise ValueError("Blind review inputs differ from the frozen development scope.")
    a = validate_review(read_jsonl(root / "reviewer_a.jsonl"), inputs, "codex_ai_A")
    b = validate_review(read_jsonl(root / "reviewer_b.jsonl"), inputs, "codex_ai_B")
    references = []
    for row in dev:
        left, right = a[row["id"]], b[row["id"]]
        agreed = left["behavior_label"] if left["behavior_label"] == right["behavior_label"] else None
        references.append({"id": row["id"], "author_behavior_label": row["behavior_label"],
            "scenario_label": row["label"], "consensus_behavior_label": agreed,
            "reviewer_a": left, "reviewer_b": right,
            "reference_status": "blind_AI_agreement_not_human_gold", "human_gold": False})
    target.mkdir()
    write_jsonl(target / "labels.jsonl", references)
    with (target / "review_differences.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        fields = ("id", "text", "author_behavior", "reviewer_a", "reviewer_b", "agreed_behavior", "notes_a", "notes_b")
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader()
        texts = {r["id"]: r["text"] for r in inputs}
        for row in references:
            writer.writerow({"id": row["id"], "text": spreadsheet_cell(texts[row["id"]]),
                "author_behavior": row["author_behavior_label"], "reviewer_a": row["reviewer_a"]["behavior_label"],
                "reviewer_b": row["reviewer_b"]["behavior_label"], "agreed_behavior": row[PRIMARY_SCOPE],
                "notes_a": spreadsheet_cell(row["reviewer_a"]["notes"]), "notes_b": spreadsheet_cell(row["reviewer_b"]["notes"])})
    counts = lambda field: dict(Counter("UNKNOWN" if r[field] is None else str(r[field]) for r in references))
    locks = [root / name for name in ("blind_dev_inputs.jsonl", "reviewer_a.jsonl", "reviewer_b.jsonl", "label_review_protocol.json")]
    locks += [Path(pack) / "manifest.json", Path(pack) / "cases.jsonl"]
    manifest = {"status": "blind_AI_agreement_not_human_gold", "primary_scope": PRIMARY_SCOPE,
        "human_gold": False, "classifier_outputs_seen": False, "cases": len(references),
        "agreement": sum(a[r["id"]]["behavior_label"] == b[r["id"]]["behavior_label"] for r in dev),
        "author_counts": counts("author_behavior_label"), "consensus_counts": counts(PRIMARY_SCOPE),
        "different_from_author": sum(r[PRIMARY_SCOPE] != r["author_behavior_label"] for r in references),
        "policy": "Only matching AI binary labels form binary reference; disagreement or null remains UNKNOWN. Original design references remain available.",
        "limits": "Two assistant sessions share a model family. Agreement is not independent human truth or proof of correctness.",
        "input_files_sha256": {str(p.resolve()): sha(p) for p in locks},
        "files_sha256": {p.name: sha(p) for p in target.iterdir()}}
    write_json(target / "manifest.json", manifest)
    return manifest


def load_reference(path):
    path = Path(path)
    config = json.loads((path / "manifest.json").read_text())
    if config.get("human_gold") is not False or config.get("status") != "blind_AI_agreement_not_human_gold":
        raise ValueError("Only explicitly provisional blind AI references are supported.")
    for source, expected in config["input_files_sha256"].items():
        if sha(source) != expected: raise ValueError("Reference input changed: " + source)
    for name, expected in config["files_sha256"].items():
        if sha(path / name) != expected: raise ValueError("Reference output changed: " + name)
    return {r["id"]: r for r in read_jsonl(path / "labels.jsonl")}


def select_cases(rows, seed=SEED):
    """Six URL groups + six non-URL groups, selected without scores or labels."""
    if any(r.get("split") != "dev" for r in rows):
        raise ValueError("Holdout is excluded from pilot selection.")
    base = [r for r in rows if not r.get("base_id")]
    groups = defaultdict(list)
    for row in base: groups[row["group_id"]].append(row)
    by_url = {True: [], False: []}
    for group, members in groups.items():
        candidates = [r for r in members if r["urls"]] or members
        representative = min(candidates, key=lambda r: canonical_sha([seed, "representative", r["id"]]))
        by_url[bool(representative["urls"])].append(representative)
    chosen = []
    for has_url in (True, False):
        candidates = sorted(by_url[has_url], key=lambda r: canonical_sha([seed, "group", r["group_id"]]))
        chosen += candidates[:6]
    if len(chosen) != 12:
        raise ValueError("The pilot requires six independent URL and six non-URL development groups.")
    base_ids = {r["id"] for r in chosen}
    variants = sorted((r for r in rows if r.get("base_id") in base_ids),
                      key=lambda r: canonical_sha([seed, "injection", r["id"]]))[:4]
    return sorted(chosen + variants, key=lambda r: canonical_sha([seed, "case_order", r["id"]]))


def bind_requests(cases, prepared, model):
    requests, cells = {}, []
    for case in cases:
        item = prepared[case["id"]]
        common = None
        for arm in ARMS:
            ml = item["real_metadata"] if arm in {"llm_url", "llm_url_rag_post"} else []
            body, included = build_payload(text=case["text"], urls=[{**r, "status": "ok"} for r in ml],
                include_ml=bool(ml), model=model, max_tokens=2048, thinking="disabled")
            data = json.loads(body["messages"][1]["content"])
            actual = data.pop("url_results", [])
            if actual != ml or included != bool(ml):
                raise ValueError("Provider metadata differs from the registered treatment.")
            if common is None: common = data
            if data != common: raise ValueError("Only URL metadata may vary in classification.")
            key = case["id"] + "::" + fingerprint(body)[:16]
            requests.setdefault(key, {"key": key, "case_id": case["id"], "text": case["text"],
                                      "profile": "core", "payload": body})
            cells.append({"id": case["id"], "arm": arm, "request_key": key,
                "URL_context_available": bool(item["real_metadata"]), "injection": bool(case.get("base_id"))})
    ordered = sorted(requests.values(), key=lambda r: canonical_sha([SEED, "call_order", r["key"]]))
    return ordered, cells


def prepare(root, pack=PACK):
    root, pack = Path(root).resolve(), Path(pack).resolve()
    out, inputs = root / "classification", root / "classification_inputs"
    if out.exists() or inputs.exists(): raise ValueError("Preserve earlier pilot; choose a fresh directory.")
    references = load_reference(root / "reference")
    selected = select_cases(development(pack))
    if {r["base_id"] if r.get("base_id") else r["id"] for r in selected} - set(references):
        raise ValueError("Every selected case requires a pre-output development reference.")
    model = CharURLService()
    prepared = score_cases(selected, model)
    if not model.status()["ready"] or any(r.get("status") != "ok" for item in prepared.values() for r in item["raw_url_results"]):
        raise ValueError("Local URL preflight failed; no classifier run registered.")
    approved = []
    for row in selected:
        text, fields = redact(row["text"])
        item = prepared[row["id"]]
        item.update(original_text_sha256=canonical_sha(row["text"]), approved_text_sha256=canonical_sha(text),
                    privacy_redactions=fields, real_metadata=approved_ml_metadata(text, item["operating_url_results"]))
        approved.append({**row, "text": text})
    requests, cells = bind_requests(approved, prepared, Settings().llm_model)
    assets = [*model.path.rglob("*"), model.preprocessing_path]
    settings = Settings()
    for directory in (settings.root / settings.rag_index_dir, settings.root / settings.rag_model_dir,
                      settings.root / "app/services/url/resources"):
        assets += list(directory.rglob("*"))
    assets += [settings.root / settings.rag_corpus]
    assets = sorted({p.resolve() for p in assets if p.is_file()})
    inputs.mkdir()
    write_jsonl(inputs / "cases.jsonl", approved)
    write_jsonl(inputs / "references.jsonl", [{**references[r.get("base_id", r["id"])],
                "id": r["id"], "inherited_from": r.get("base_id")} for r in approved])
    write_json(inputs / "prepared.json", prepared)
    write_jsonl(inputs / "cells.jsonl", cells)
    write_json(inputs / "assets.json", {"URL_model": model.status(), "RAG_stage": "post_classification",
        "corpus": settings.rag_corpus, "index": settings.rag_index_dir,
        "files_sha256": {str(p): sha(p) for p in assets}})
    metadata = {"inputs": str(inputs), "pack": str(pack), "reference": str(root / "reference"), "seed": SEED,
        "arms": list(ARMS), "base_cases": sum(not r.get("base_id") for r in approved),
        "injection_variants": sum(bool(r.get("base_id")) for r in approved), "logical_cells": len(cells),
        "selection": "Six URL + six non-URL source components, hash-selected without labels/scores/outputs; up to4 existing paired injection variants",
        "primary_reference": PRIMARY_SCOPE, "sensitivity_reference": "author_behavior_label",
        "scenario_reference": "secondary descriptive only; not classifier behavior target",
        "human_gold": False, "holdout_inference": False, "old_120_reserve_inference": False,
        "familiar_author_exposed_reconstructions": True, "classification_profile": PROFILE,
        "same_prompt_schema_model_decoding_cap": True, "identical_payloads_share_response": True,
        "RAG_stage": "post_classification; logical RAG arms reuse their frozen classifier response",
        "runtime_scope": "Research core classifier adapter, not end-to-end HTTP/UI/shared deadline benchmark",
        "pilot_unique_requests": min(4, len(requests)), "pacing_seconds": 4, "cost": "unknown provider tariff",
        "metric_policy": "All binary references remain denominator; predictedUNKNOWN/technicalerrors count missed. UNKNOWN reference separate; injection pairs separate.",
        "no_auto_app_promotion": True}
    locks = list(inputs.iterdir()) + assets + list((root / "reference").iterdir())
    locks += [root / "label_review_protocol.json", pack / "manifest.json", pack / "cases.jsonl"]
    if (root / "protocol.json").is_file(): locks.append(root / "protocol.json")
    # Collection snapshot is independently verified and remains immutable.
    cfg = registered.register(out, requests, stage="evidence_development_pilot", metadata=metadata,
                              locks=locks, max_tokens=2048, token_budget=100000)
    cfg.update(workers=1, timeout_seconds=45)
    write_json(out / "execution.json", cfg)
    (out / "registration.sha256").write_text(sha(out / "execution.json") + "\n")
    snapshot = root / "source_snapshot"
    if snapshot.exists(): raise ValueError("Source snapshot already exists.")
    for relative in cfg["source_files_sha256"]:
        target = snapshot / relative; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    write_json(root / "source_snapshot_manifest.json", cfg["source_files_sha256"])
    return cfg


async def run(root, *, live=False, limit=None, inner=None):
    return await controlled_run.run(Path(root) / "classification", parse_response, live=live, limit=limit, inner=inner)


def report(root):
    root = Path(root).resolve(); out = root / "classification"
    verified = registered.verify(out, parse_response)
    cfg, _ = registered.load(out)
    _, records = registered.checkpoints(out, cfg)
    inputs = Path(cfg["metadata"]["inputs"])
    cases = {r["id"]: r for r in read_jsonl(inputs / "cases.jsonl")}
    refs = {r["id"]: r for r in read_jsonl(inputs / "references.jsonl")}
    cells = read_jsonl(inputs / "cells.jsonl")
    decisions = []
    for cell in cells:
        record = records.get((cfg["stage"], cell["request_key"]))
        parsed = record["parsed"] if record else {"status": "pending"}
        level = parsed["verdict"]["risk_level"] if parsed["status"] == "ok" else "UNKNOWN"
        decisions.append({**cell, "base_id": cases[cell["id"]].get("base_id"),
            "group_id": cases[cell["id"]]["group_id"], "level": level, "status": parsed["status"],
            "error": parsed.get("code"), "reference": refs[cell["id"]][PRIMARY_SCOPE],
            "author_reference": refs[cell["id"]]["author_behavior_label"],
            "semantic_UNKNOWN": parsed["status"] == "ok" and level == "UNKNOWN"})
    summary = {"complete": verified["complete"], "physical_run": _operations(records.values()),
        "logical_cells": len(cells), "physical_requests": cfg["max_attempts"],
        "reference_status": "AI-only, same-family blind agreement; not human gold",
        "primary_target": "visible requested behavior", "holdout_inference": False,
        "old_120_reserve_inference": False, "independent_accuracy": None, "arms": {}, "injection_pairs": [],
        "classification_RAG_invariance": True}
    if verified["complete"]:
        for scope, field in (("blind_AI_agreement", "reference"), ("original_author_sensitivity", "author_reference")):
            summary[scope] = {}
            for arm in ARMS:
                selected = [r for r in decisions if r["arm"] == arm and not r["injection"]]
                strata = {"all": selected, "URL_context": [r for r in selected if r["URL_context_available"]],
                          "no_URL_context": [r for r in selected if not r["URL_context_available"]]}
                result = {}
                for name, group in strata.items():
                    binary = [r for r in group if r[field] is not None]
                    result[name] = {**measure([r[field] for r in binary], [r["level"] for r in binary]),
                        "all_cases": len(group), "reference_UNKNOWN": len(group)-len(binary),
                        "source_components": len({r["group_id"] for r in group}),
                        "technical_errors": sum(r["status"] == "error" for r in group),
                        "semantic_UNKNOWN": sum(r["semantic_UNKNOWN"] for r in group),
                        "UNKNOWN_reference_predictions": dict(Counter(r["level"] for r in group if r[field] is None))}
                summary[scope][arm] = result
        lookup = {(r["id"], r["arm"]): r for r in decisions}
        for r in decisions:
            if r["arm"] in {"llm_rag_post", "llm_url_rag_post"}:
                parentarm = "llm_only" if r["arm"] == "llm_rag_post" else "llm_url"
                assert r["request_key"] == lookup[(r["id"], parentarm)]["request_key"]
            if r["injection"] and r["arm"] in BASE_ARMS:
                base = lookup[(r["base_id"], r["arm"])]
                summary["injection_pairs"].append({"base_id": r["base_id"], "variant_id": r["id"],
                    "arm": r["arm"], "base_level": base["level"], "variant_level": r["level"],
                    "base_status": base["status"], "variant_status": r["status"],
                    "valid_binary_flip": base["status"] == r["status"] == "ok" and
                        prediction(base["level"]) is not None and prediction(r["level"]) is not None and
                        prediction(base["level"]) != prediction(r["level"]),
                    "instruction_compliance_review": None, "attack_success_rate": None})
        original = [r for r in decisions if r["arm"] == "llm_only" and not r["injection"] and r["reference"] is not None]
        summary["paired_URL"] = paired_comparison([r["reference"] for r in original], [r["level"] for r in original],
            [lookup[(r["id"], "llm_url")]["level"] for r in original])
        labels = [r["reference"] for r in original]
        summary["baselines"] = {"always_HIGH": measure(labels, ["HIGH"]*len(labels)),
                                "always_LOW": measure(labels, ["LOW"]*len(labels))}
    write_jsonl(root / "decisions.jsonl", decisions)
    write_json(root / "metrics.json", summary)
    lines = ["# Pilot dev — tham chiếu AI, không phải gold", "",
        "Bộ tin dựng lại; chọn theo nhóm/URL trước khi xem output. Holdout và120SMSreserve không suy luận.",
        "RAG sau phân loại dùng chung verdict nên F1 giống arm tương ứng theo thiết kế; chất lượng nguồn chấm riêng.", "",
        f"Trạng thái hoàn tất: {verified['complete']}. {len(records)}/{cfg['max_attempts']} request vật lý.", ""]
    if verified["complete"]:
        lines += ["| Arm | n nhị phân | TP/FP/FN+UNKNOWN dương | Precision | Recall | F1 | Accuracy | Coverage | Lỗi / mọi ca |", "|---|---:|---|---:|---:|---:|---:|---:|---:|"]
        fmt = lambda value: "N/A" if value is None else f"{value*100:.2f}%"
        for arm in ARMS:
            m = summary["blind_AI_agreement"][arm]["all"]
            lines.append(f"| {arm} | {m['n']} | {m['tp']}/{m['fp']}/{m['fn']+m['unknown_positive']} | " +
                " | ".join(fmt(m[k]) for k in ("precision", "recall", "f1", "accuracy", "coverage")) +
                f" | {m['technical_errors']}/{m['all_cases']} |")
        lines += ["", "UNKNOWN reference báo riêng; predictedUNKNOWN/lỗi giữ trong Accuracy/Recall/F1 theo protocol. Xem metrics.json cho nhóm URL, nhãn tác giả đối chiếu và baseline luôn HIGH/LOW.",
            "Số mẫu và nguồn nhỏ; không chọn lại ngưỡng/prompt hoặc tuyên bố lợi ích URL từ bảng này. Injection có flip chưa tự chứng minh làm theo chỉ dẫn; ASR vẫn N/A nếu chưa chấm."]
    else:
        lines.append("Chưa công bố bảng chất lượng vì lượt chạy chưa hoàn tất; không bỏ các attempt lỗi hoặc pending.")
    (root / "report.md").write_text("\n".join(lines)+"\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("review", "prepare", "run", "verify", "report"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--pack", type=Path, default=PACK)
    parser.add_argument("--live", action="store_true"); parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.command == "review": result = reference_pack(args.root, args.pack)
    elif args.command == "prepare":
        cfg = prepare(args.root, args.pack); result = {"physical_requests": cfg["max_attempts"], **cfg["metadata"]}
    elif args.command == "run": result = asyncio.run(run(args.root, live=args.live, limit=args.limit))
    elif args.command == "verify": result = registered.verify(args.root/"classification", parse_response)
    else: result = report(args.root)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
