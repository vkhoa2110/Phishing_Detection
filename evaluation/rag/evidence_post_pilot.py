"""Frozen-verdict, post-classification source selection on the evidence dev pilot.

This staged research helper measures source-selection operations and prepares
semantic review. It cannot change a classifier verdict, establish semantic
support, or benchmark the application's shared 45-second deadline.
"""
import argparse
import asyncio
from collections import Counter
import csv
import json
from pathlib import Path

from app.core.settings import ROOT, Settings
from app.services.rag.evidence import build_evidence_payload, evidence_catalog, parse_evidence
from app.services.rag.explanation import build_retrieval_query
from app.services.rag.retrieval import RAGService
from evaluation.common import controlled_run, registered
from evaluation.data.sms import read_jsonl, sha, write_json, write_jsonl
from evaluation.messages.core_pilot import parse_response as parse_classifier
from evaluation.messages.url_context import canonical_sha

ARMS = ("llm_rag_post", "llm_url_rag_post")
BASE_ARMS = {"llm_rag_post": "llm_only", "llm_url_rag_post": "llm_url"}
STAGE = "evidence_dev_post_rag"
INPUT_FILES = ("cases.jsonl", "cells.jsonl", "prepared.json", "retrieval_trace.jsonl", "study.json")


def _json(path):
    return json.loads(Path(path).read_text())


def _asset_paths(settings):
    """Pin existing local assets, including weights; never fetch or build them."""
    files = []
    for name in (settings.rag_corpus, settings.rag_index_dir, settings.rag_model_dir):
        path = settings.root / name
        if path.is_file():
            files.append(path.resolve())
        elif path.is_dir():
            files.extend(p.resolve() for p in path.rglob("*") if p.is_file())
    return sorted(set(files))


def _parent(parent):
    parent = Path(parent).resolve()
    if not registered.verify(parent, parse_classifier)["complete"]:
        raise ValueError("Complete the frozen classifier run before post-classification RAG.")
    config, requests = registered.load(parent)
    _, records = registered.checkpoints(parent, config)
    inputs = Path(config["metadata"]["inputs"])
    if not inputs.is_absolute():
        inputs = parent.parent / inputs
    inputs = inputs.resolve()
    cases = read_jsonl(inputs / "cases.jsonl")
    cells = read_jsonl(inputs / "cells.jsonl")
    prepared = _json(inputs / "prepared.json")
    by_id = {row["id"]: row for row in cases}
    by_cell = {(row["id"], row["arm"]): row for row in cells}
    if len(by_id) != len(cases) or len(by_cell) != len(cells):
        raise ValueError("Parent cases/cells must be unique.")
    expected = {(identifier, arm) for identifier in by_id for arm in (*BASE_ARMS.values(), *ARMS)}
    if set(by_cell) != expected:
        raise ValueError("Parent must contain exactly the four declared logical arms per case.")
    frozen = []
    for identifier in sorted(by_id):
        for arm in ARMS:
            cell = by_cell[identifier, arm]
            base = by_cell[identifier, BASE_ARMS[arm]]
            if cell["request_key"] != base["request_key"]:
                raise ValueError("Post arm must alias its corresponding classifier request.")
            key = config["stage"], cell["request_key"]
            if key not in requests or key not in records:
                raise ValueError("Missing parent classifier request/response.")
            request = requests[key]
            if request.get("profile") != "core" or request.get("text") != by_id[identifier]["text"]:
                raise ValueError("Parent classifier request does not match the frozen message.")
            frozen.append({"id": identifier, "arm": arm, "classification_request_key": cell["request_key"],
                           "classification": records[key]["parsed"]})
    return parent, inputs, cases, prepared, frozen


def parse_response(raw, request):
    parsed = parse_evidence(raw, approved_text=request["text"], verdict=request["verdict"], sources=request["sources"])
    # Empty selection is a successful technical completion, not semantic proof.
    return {**parsed, "explanation_status": parsed["status"],
            "status": "ok" if parsed["status"] in {"ok", "no_support"} else "error"}


def prepare(parent, out, *, settings=None, retriever=None):
    out = Path(out).resolve()
    inputs = out.parent / (out.name + "_inputs")
    if out.exists() or inputs.exists():
        raise ValueError("Preserve previous runs; choose fresh run and input directories.")
    parent, parent_inputs, cases, parent_prepared, frozen = _parent(parent)
    settings = settings or Settings()
    retriever = retriever or RAGService(settings, include_scope=True)
    case_map = {row["id"]: row for row in cases}
    traces, cells, prepared, requests = [], [], {}, {}
    retrieval_cache = {}
    for cell in frozen:
        identifier, arm = cell["id"], cell["arm"]
        text = case_map[identifier]["text"]
        parsed = cell["classification"]
        row = {**cell, "frozen_classification_sha256": canonical_sha(parsed), "request_key": None}
        if parsed.get("status") != "ok" or not isinstance(parsed.get("verdict"), dict):
            row.update(status="classifier_error", code=parsed.get("code", "CLASSIFIER_INVALID"))
            cells.append(row)
            continue
        verdict = parsed["verdict"]
        query = build_retrieval_query(text, verdict)
        query_key = canonical_sha(query)
        if query_key not in retrieval_cache:
            try:
                retrieval_cache[query_key] = retriever.search(query, mode="text")
            except (ImportError, OSError, ValueError, KeyError, TypeError, RuntimeError):
                retrieval_cache[query_key] = {"status": "unavailable", "sources": [], "reason": "LOCAL_RETRIEVAL_ERROR"}
        retrieval = retrieval_cache[query_key]
        trace = {"id": identifier, "arm": arm, "query": query, "query_sha256": query_key,
                 "classification_request_key": cell["classification_request_key"],
                 "frozen_verdict_sha256": canonical_sha(verdict), "retrieval": retrieval,
                 "retrieved_after_classifier_completed": True}
        traces.append(trace)
        prepared_key = identifier + "::" + arm
        prepared[prepared_key] = {"text": text, "verdict": verdict, "retrieval": retrieval}
        row["frozen_verdict_sha256"] = canonical_sha(verdict)
        if retrieval.get("status") not in {"ok", "empty"}:
            row.update(status="retrieval_unavailable", code="RETRIEVAL_UNAVAILABLE")
        elif not retrieval.get("sources"):
            row.update(status="no_sources", explanation_status="not_requested_no_sources")
        elif retrieval.get("status") != "ok":
            raise ValueError("Nonempty sources require an ok retrieval status.")
        else:
            sources = retrieval["sources"]
            payload = build_evidence_payload(approved_text=text, verdict=verdict, sources=sources,
                                            model=settings.llm_model, max_tokens=2048)
            payload["thinking"] = {"type": "disabled"}
            key = "post-" + canonical_sha(payload)
            request = {"key": key, "text": text, "verdict": verdict, "sources": sources,
                       "catalog": evidence_catalog(approved_text=text, verdict=verdict, sources=sources),
                       "profile": "post_evidence_selection", "payload": payload}
            if key in requests and requests[key] != request:
                raise ValueError("Payload alias failed exact request comparison.")
            requests[key] = request
            prepared[prepared_key]["catalog"] = request["catalog"]
            row.update(status="registered", request_key=key)
        cells.append(row)
    inputs.mkdir(parents=True)
    write_jsonl(inputs / "cases.jsonl", cases)
    write_jsonl(inputs / "cells.jsonl", cells)
    write_json(inputs / "prepared.json", prepared)
    write_jsonl(inputs / "retrieval_trace.jsonl", traces)
    parent_pins = [parent / name for name in (*registered.SEALED, "result_hashes.json", "registration.sha256")]
    parent_pins += sorted(p for p in parent_inputs.rglob("*") if p.is_file())
    assets = _asset_paths(settings)
    study = {"schema": "evidence-post-pilot-1.0", "parent": str(parent), "parent_inputs": str(parent_inputs),
             "arms": list(ARMS), "case_count": len(cases), "logical_cells": len(cells),
             "physical_requests": len(requests), "classifier_results_sha256": canonical_sha(frozen),
             "frozen_verdicts_sha256": canonical_sha([{k: r[k] for k in ("id", "arm", "frozen_verdict_sha256")}
                  for r in cells if "frozen_verdict_sha256" in r]),
             "assets_sha256": {str(p): sha(p) for p in assets},
             "parent_sha256": {str(p): sha(p) for p in parent_pins},
             "RAG_position": "after_frozen_verdict", "include_scope": True, "classification_changed": False,
             "independent_gold": False, "semantic_support_verified": False, "reserve_inference": False,
             "application_deadline_benchmark": False,
             "notes": "Source selection only; authored dev references do not establish semantic relevance or F1 improvement."}
    write_json(inputs / "study.json", study)
    locks = [inputs / name for name in INPUT_FILES] + parent_pins + assets
    if requests:
        rows = sorted(requests.values(), key=lambda r: canonical_sha([20261119, r["key"]]))
        config = registered.register(out, rows, stage=STAGE, max_tokens=2048, token_budget=80000,
            locks=locks, metadata={"inputs": str(inputs), "parent": str(parent), "pacing_seconds": 4,
                "pilot_unique_requests": min(4, len(rows)), "post_classification": True,
                "classification_changed": False, "semantic_support_verified": False,
                "application_shared_deadline_benchmark": False, "independent_gold": False})
        config.update(workers=1, timeout_seconds=45)
        write_json(out / "execution.json", config)
        (out / "registration.sha256").write_text(sha(out / "execution.json") + "\n")
    else:
        out.mkdir(parents=True)
        write_json(out / "offline_registration.json", {"schema": "evidence-post-empty-1.0", "inputs": str(inputs),
            "input_files_sha256": {str(p): sha(p) for p in locks}, "physical_requests": 0})
        write_json(out / "offline_seal.json", {"offline_registration.json": sha(out / "offline_registration.json")})
    return {"prepared": True, "logical_cells": len(cells), "requests": len(requests), "API_calls": 0,
            "inputs": str(inputs)}


def _load(out):
    out = Path(out).resolve()
    if (out / "offline_registration.json").exists():
        offline = _json(out / "offline_registration.json")
        seal = _json(out / "offline_seal.json")
        if seal != {"offline_registration.json": sha(out / "offline_registration.json")}:
            raise ValueError("Empty registration seal changed.")
        for name, expected in offline["input_files_sha256"].items():
            if sha(name) != expected:
                raise ValueError("Frozen empty-study input changed: " + name)
        return Path(offline["inputs"]), None, {}, {}
    config, requests = registered.load(out)
    _, records = registered.checkpoints(out, config)
    return Path(config["metadata"]["inputs"]), config, requests, records


def verify(out):
    out = Path(out)
    inputs, config, _, _ = _load(out)
    study = _json(inputs / "study.json")
    for field in ("assets_sha256", "parent_sha256"):
        for name, expected in study[field].items():
            if sha(name) != expected:
                raise ValueError("Frozen post-study asset or parent changed: " + name)
    frozen = read_jsonl(inputs / "cells.jsonl")
    checksum = canonical_sha([{k: r[k] for k in ("id", "arm", "frozen_verdict_sha256")}
                               for r in frozen if "frozen_verdict_sha256" in r])
    if checksum != study["frozen_verdicts_sha256"]:
        raise ValueError("Frozen verdict checksum changed.")
    if (out / "report_hashes.json").exists():
        for name, expected in _json(out / "report_hashes.json").items():
            if sha(out / name) != expected:
                raise ValueError("Frozen post-stage report changed: " + name)
    result = registered.verify(out, parse_response) if config else {"verified": True, "complete": True, "attempts": 0, "API_calls": 0}
    return {**result, "classification_changed": False, "semantic_support_verified": False}


async def run(out, *, live=False, limit=None, inner=None):
    verify(out)
    _, config, _, _ = _load(out)
    if config is None:
        return {"state": "complete_offline_no_requests", "requests": 0, "API_calls": 0}
    return await controlled_run.run(out, parse_response, live=live, limit=limit, inner=inner)


def _csv(value):
    value = str(value)
    return "'" + value if value.startswith(("=", "+", "-", "@", "\t", "\r")) else value


def report(out):
    out = Path(out)
    verified = verify(out)
    if not verified["complete"]:
        raise ValueError("Complete the registered post-classification stage before reporting.")
    inputs, config, _, records = _load(out)
    cases = {r["id"]: r for r in read_jsonl(inputs / "cases.jsonl")}
    cells = read_jsonl(inputs / "cells.jsonl")
    prepared = _json(inputs / "prepared.json")
    selections, semantic_rows = [], []
    for cell in cells:
        row = {**cell, "explanation": {"support": [], "actions": []}}
        if cell["request_key"] is not None:
            record = records[config["stage"], cell["request_key"]]
            row.update(explanation_status=record["parsed"].get("explanation_status", "technical_error"),
                       status=record["parsed"]["status"], code=record["parsed"].get("code"),
                       explanation=record["parsed"].get("explanation", {"support": [], "actions": []}))
        selections.append(row)
        support = row["explanation"]["support"]
        retrieved = {s["document_id"]: s for s in prepared.get(cell["id"] + "::" + cell["arm"], {})
                     .get("retrieval", {}).get("sources", [])}
        for index, pair in enumerate(support or [{}]):
            metadata = pair.get("source_metadata", {})
            semantic_rows.append({"review_id": "ER-" + canonical_sha([cell["id"], cell["arm"], index])[:12],
                "id": cell["id"], "text": cases[cell["id"]]["text"], "input_quote": pair.get("input_quote", ""),
                "source_quote": pair.get("source_quote", ""),
                "source_url": retrieved.get(pair.get("document_id"), {}).get("source_url", metadata.get("source_url", "")),
                "output_status": row.get("explanation_status", row["status"]),
                "relevance_0_2": "", "entails_0_2": "", "notes": ""})
    write_jsonl(out / "selections.jsonl", selections)
    physical = list(records.values())
    operations = {"physical_requests": len(physical), "logical_cells": len(cells),
        "logical_statuses": dict(Counter(r["status"] for r in selections)),
        "logical_explanation_statuses": dict(Counter(r.get("explanation_status", r["status"]) for r in selections)),
        "physical_valid": sum(r["parsed"]["status"] == "ok" for r in physical),
        "physical_errors": dict(Counter(r["parsed"].get("code") for r in physical if r["parsed"]["status"] != "ok")),
        "recorded_tokens": sum(r.get("usage", {}).get("total_tokens", 0) for r in physical),
        "usage_missing": sum("total_tokens" not in r.get("usage", {}) for r in physical),
        "classification_changed": False, "F1_improvement": None, "semantic_support_verified": False,
        "application_shared_deadline_benchmark": False, "independent_gold": False,
        "frozen_verdicts_sha256": _json(inputs / "study.json")["frozen_verdicts_sha256"]}
    write_json(out / "operations.json", operations)
    sheet = out / "semantic_review.csv"
    if not sheet.exists():
        fields = ["review_id", "id", "text", "input_quote", "source_quote", "source_url", "output_status", "relevance_0_2", "entails_0_2", "notes"]
        with sheet.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows({k: _csv(v) for k, v in row.items()} for row in semantic_rows)
    (out / "README.md").write_text("# RAG sau phân loại — pilot dev\n\n"
        f"{len(cells)} ô logic; {len(physical)} yêu cầu API riêng; {operations['recorded_tokens']} token được ghi nhận.\n\n"
        "Kết luận phân loại được khóa từ lượt cha. RAG chỉ chọn cặp đoạn tham khảo sau phân loại; "
        "không có điểm F1 cải thiện. Nguồn không khả dụng được giữ là lỗi kỹ thuật truy xuất, "
        "khác trường hợp kho không có nguồn đạt ngưỡng. Phản hồi chọn nguồn rỗng hợp lệ được ghi no_support.\n\n"
        "Phiếu semantic_review.csv chưa có điểm người chấm. Trích đoạn khớp chuỗi không xác nhận nguồn hỗ trợ đúng "
        "về ngữ nghĩa. Đây là nghiên cứu theo giai đoạn, không đo deadline 45 giây dùng chung của ứng dụng.\n")
    write_json(out / "report_hashes.json", {name: sha(out / name) for name in
               ("operations.json", "selections.jsonl", "README.md")})
    return operations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "run", "verify", "report"])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--parent", type=Path)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare(args.parent, args.out)
    elif args.command == "run":
        result = asyncio.run(run(args.out, live=args.live, limit=args.limit))
    else:
        result = globals()[args.command](args.out)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
