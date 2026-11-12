"""Fixed-prompt four-arm development study; AI references are diagnostic only."""
import argparse
import asyncio
from collections import Counter
import csv
import io
import json
from pathlib import Path
from urllib.parse import urlsplit
import zipfile

import tldextract

from app.core.settings import ROOT, Settings
from app.domain.schemas import MessageRAGVerdict
from app.domain.validation import validate_message_verdict
from app.services.llm.client import MESSAGE_V3_RAG_SYSTEM_PROMPT, SOURCE_SCOPE_FIELDS
from app.services.llm.message import FRAUD_RULES
from app.services.llm.policy_v5 import INJECTION_FRAUD_RULES
from app.services.rag.explanation import _load_strict_json
from app.services.rag.retrieval import RAGService
from app.services.url.character import CharURLService
from app.services.url.parsing import extract_urls
from app.services.url.policy import ConservativeURLModel
from evaluation.common import registered
from evaluation.common.metrics import measure, paired_comparison, prediction
from evaluation.data.fresh_dev import cases
from evaluation.data.sms import read_jsonl, sha, spreadsheet_cell, write_json, write_jsonl
from evaluation.messages.url_context import canonical_sha

ARMS = ("llm_only", "llm_url", "llm_rag", "llm_url_rag")
SYSTEM = MESSAGE_V3_RAG_SYSTEM_PROMPT + FRAUD_RULES + INJECTION_FRAUD_RULES + """
THÍ NGHIỆM CÙNG HỢP ĐỒNG: Mọi cấu hình trả cùng output_schema, kể cả khi không có nguồn.
reference_documents và url_results có thể rỗng. Không có nguồn thì knowledge_support=[].
Điểm URL chỉ là score chuỗi chưa hiệu chỉnh, không xác nhận trang đích và không tự chứng minh lừa đảo nội dung.
Chỉ đánh giá hành vi người nhận được yêu cầu. Giải thích ngắn; không lặp hướng dẫn.
"""


def payload(case, prepared, arm, model, max_tokens=4096):
    sources = prepared["sources"] if arm in {"llm_rag", "llm_url_rag"} else []
    urls = prepared["url_context"] if arm in {"llm_url", "llm_url_rag"} else []
    data = {"text": case["text"], "assessment_target": "message_actions_not_url_reputation",
            "url_results": urls, "reference_documents": sources,
            "output_schema": MessageRAGVerdict.model_json_schema()}
    return {"model": model, "messages": [{"role": "system", "content": SYSTEM},
        {"role": "user", "content": json.dumps(data, ensure_ascii=False)}], "temperature": .1,
        "top_p": 1, "top_k": 40, "max_tokens": max_tokens, "stream": False}


def bind_requests(all_cases, prepared, model):
    requests, cells = {}, []
    for case in all_cases:
        for arm in ARMS:
            body = payload(case, prepared[case["id"]], arm, model)
            key = case["id"] + "::" + canonical_sha(body)[:16]
            sources = prepared[case["id"]]["sources"] if arm in {"llm_rag", "llm_url_rag"} else []
            requests.setdefault(key, {"key": key, "case_id": case["id"], "text": case["text"],
                                      "sources": sources, "payload": body})
            cells.append({"id": case["id"], "dataset": case["dataset"], "arm": arm, "request_key": key})
    rows = sorted(requests.values(), key=lambda r: canonical_sha([20261111, r["key"]]))
    return rows, cells


def domain(url, extractor):
    try:
        host = urlsplit(url if "://" in url else "https://" + url).hostname or ""
        return extractor(host).top_domain_under_public_suffix or host
    except ValueError:
        return ""


def training_domains(archive):
    extractor = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)
    with zipfile.ZipFile(archive) as bundle:
        rows = csv.DictReader(io.StringIO(bundle.read("data/splits/url_train.csv").decode()))
        return {domain(r["url"], extractor) for r in rows}


def prepare(pack, labels, out):
    pack, labels, out = Path(pack).resolve(), Path(labels).resolve(), Path(out).resolve()
    if out.exists(): raise ValueError("Choose a fresh study directory.")
    sms, authored = cases(pack)
    label_manifest = json.loads((labels / "labels_manifest.json").read_text())
    if label_manifest["status"] != "ai_preliminary_not_gold" or sha(labels / "labels.jsonl") != label_manifest["label_file_sha256"]:
        raise ValueError("AI references must be frozen and explicitly provisional.")
    references = read_jsonl(labels / "labels.jsonl")
    if {r["id"] for r in references} != {r["id"] for r in sms}:
        raise ValueError("Reference inventory differs from the exact dev inputs.")
    settings = Settings()
    model, rag = CharURLService(), RAGService(settings, include_scope=True)
    if not model.load()["ready"] or not rag.status()["ready"]:
        raise ValueError("The frozen character model and retrieval index must be ready.")
    wrapper = ConservativeURLModel(model)
    archive = ROOT / "data/raw/PhishVN_v3.1.0_open.zip"
    seen = training_domains(archive)
    extractor = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)
    prepared = {}
    fields = ("document_id", "title", "text", "context_note", "publisher", "published_at", *SOURCE_SCOPE_FIELDS)
    for case in sms + authored:
        invalid = []
        try: urls, invalid = extract_urls(case["text"], "text")
        except ValueError: urls = []; invalid = ["extraction_limit"]
        outputs = wrapper.predict(urls) if case["dataset"] == "sms" else []
        context = [{"url": r["url"], "score": r["score"], "risk_level": r["risk_level"],
                    "low_threshold": r["raw_warning_threshold"], "high_threshold": r["high_threshold"],
                    "score_is_calibrated_probability": False} for r in outputs if r["status"] == "ok"]
        retrieved = rag.search(case["text"])
        if retrieved["status"] == "unavailable":
            raise ValueError("Retrieval failed; do not register this as an empty-source control.")
        prepared[case["id"]] = {"url_results": outputs, "url_context": context,
            "invalid_url_count": len(invalid), "url_train_domain_overlap": any(domain(u, extractor) in seen for u in urls),
            "sources": [{k: s[k] for k in fields if k in s} for s in retrieved["sources"]],
            "retrieval_status": retrieved["status"], "illustrative_urls_not_scored": case["dataset"] == "authored"}
    rows, cells = bind_requests(sms + authored, prepared, settings.llm_model)
    # Files adjacent to the run remain immutable inputs and are locked before registration.
    input_dir = out.with_name(out.name + "_inputs")
    if input_dir.exists(): raise ValueError("Prepared inputs already exist; preserve the earlier registration.")
    input_dir.mkdir(parents=True)
    write_json(input_dir / "prepared.json", prepared)
    write_jsonl(input_dir / "cells.jsonl", cells)
    locks = [pack / n for n in ("manifest.json", "sms.jsonl", "authored.jsonl", "authored_design.jsonl")]
    locks += [labels / "labels_manifest.json", labels / "labels.jsonl", archive,
              input_dir / "prepared.json", input_dir / "cells.jsonl", model.preprocessing_path]
    locks += list(model.path.glob("*")) + list((settings.root / settings.rag_index_dir).glob("*"))
    locks += [settings.root / settings.rag_corpus, settings.root / settings.rag_model_dir / "phishlens_model.json"]
    return registered.register(out, rows, stage="fresh_four_arm", max_tokens=4096, locks=[p for p in locks if p.is_file()],
        metadata={"pack": str(pack), "labels": str(labels), "inputs": str(input_dir), "arms": list(ARMS),
            "logical_cells": len(cells), "unique_requests": len(rows), "reserve_inference": False,
            "corpus": settings.rag_corpus, "index": settings.rag_index_dir,
            "model_kind": "char_tfidf_logreg_candidate", "rag_stage": "before_classification_research_only",
            "same_prompt_schema_decoding": True, "identical_payloads_share_response": True,
            "reference_quality": label_manifest.get("limitations", "AI preliminary labels; not independent human gold"),
            "reference_judge": label_manifest.get("reference_judge", "provider_ai"),
            "reference_same_provider": label_manifest.get("same_provider_as_classifier", True)})


def parse_response(raw, request):
    data = _load_strict_json(raw)
    verdict = MessageRAGVerdict.model_validate(data, strict=True)
    verdict, warnings, validation = validate_message_verdict(verdict, request["text"], request["sources"],
                                                           context_explicit="context_kind" in data)
    return {"status": "ok", "verdict": verdict.model_dump(), "warnings": warnings, "validation": validation}


def results(out):
    out = Path(out)
    verified = registered.verify(out, parse_response)
    if not verified["complete"]: raise ValueError("Finish or report the incomplete run without comparative metrics.")
    config, _ = registered.load(out)
    _, records = registered.checkpoints(out, config)
    meta = config["metadata"]
    sms, authored = cases(meta["pack"])
    by_id = {r["id"]: r for r in sms + authored}
    refs = {r["id"]: r["label"] for r in read_jsonl(Path(meta["labels"]) / "labels.jsonl")}
    design = read_jsonl(Path(meta["pack"]) / "authored_design.jsonl")
    refs.update({r["id"]: prediction(r["risk_reference"]) for r in design})
    prepared = json.loads((Path(meta["inputs"]) / "prepared.json").read_text())
    cells = read_jsonl(Path(meta["inputs"]) / "cells.jsonl")
    rows = []
    for cell in cells:
        record = records[(config["stage"], cell["request_key"])]
        parsed = record["parsed"]
        rows.append({**cell, "group_id": by_id[cell["id"]]["group_id"], "label": refs[cell["id"]],
            "status": parsed["status"], "error": parsed.get("code"),
            "level": parsed["verdict"]["risk_level"] if parsed["status"] == "ok" else "UNKNOWN"})
    summary = {"reference_quality": meta["reference_quality"], "sms_reference_counts": dict(Counter(
        "UNKNOWN" if refs[r["id"]] is None else str(refs[r["id"]]) for r in sms)), "groups": {},
        "physical_run": json.loads((out / "summary.json").read_text()), "logical_cells": len(cells),
        "identical_payloads_reused": len(cells) - len(records), "paired_sms": {}, "independent_accuracy": None}
    for name, condition in {
        "sms": lambda r: r["dataset"] == "sms",
        "sms_url_context_available": lambda r: r["dataset"] == "sms" and bool(prepared[r["id"]]["url_context"]),
        "sms_rag_available": lambda r: r["dataset"] == "sms" and bool(prepared[r["id"]]["sources"]),
        "sms_seen_url_domain": lambda r: r["dataset"] == "sms" and prepared[r["id"]]["url_train_domain_overlap"],
        "authored": lambda r: r["dataset"] == "authored",
        "authored_injection": lambda r: r["dataset"] == "authored" and r["id"].endswith("injected"),
    }.items():
        group = {}
        for arm in ARMS:
            selected = [r for r in rows if r["arm"] == arm and condition(r)]
            binary = [r for r in selected if r["label"] is not None]
            group[arm] = {**measure([r["label"] for r in binary], [r["level"] for r in binary]),
                "all_cases": len(selected), "reference_unknown": len(selected) - len(binary),
                "technical_errors": sum(r["status"] != "ok" for r in selected)}
        summary["groups"][name] = group
    for arm in ARMS[1:]:
        selected = [r for r in rows if r["dataset"] == "sms" and r["arm"] == "llm_only" and r["label"] is not None]
        lookup = {(r["id"], r["arm"]): r["level"] for r in rows}
        summary["paired_sms"][arm] = paired_comparison([r["label"] for r in selected], [r["level"] for r in selected],
                                                      [lookup[(r["id"], arm)] for r in selected])
    binary_labels = [refs[r["id"]] for r in sms if refs[r["id"]] is not None]
    summary["baselines_sms"] = {"always_high": measure(binary_labels, ["HIGH"] * len(binary_labels)),
                               "always_low": measure(binary_labels, ["LOW"] * len(binary_labels))}
    write_json(out / "metrics.json", summary)
    write_jsonl(out / "decisions.jsonl", rows)
    lines = ["# Bốn cấu hình trên development — nhãn AI sơ bộ", "", meta["reference_quality"],
        "Không phải đánh giá độc lập bằng nhãn người. Các tỷ lệ dưới đây là mức khớp nhãn AI tạm.", "",
        "| Nhóm | Cấu hình | n nhị phân | TP/FP/FN | Precision | Recall | F1 | FPR | Coverage | Lỗi / mọi mẫu |",
        "|---|---|---:|---|---:|---:|---:|---:|---:|---:|"]
    fmt = lambda v: "N/A" if v is None else f"{100*v:.2f}%"
    for name in ("sms", "authored", "authored_injection"):
        for arm, m in summary["groups"][name].items():
            lines.append(f"| {name} | {arm} | {m['n']} | {m['tp']}/{m['fp']}/{m['fn'] + m['unknown_positive']} | "
                + " | ".join(fmt(m[k]) for k in ("precision", "recall", "f1", "false_positive_rate", "coverage"))
                + f" | {m['technical_errors']}/{m['all_cases']} |")
    lines += ["", f"Nhãn SMS: {summary['sms_reference_counts']}. UNKNOWN giữ riêng; lỗi và predicted UNKNOWN không bị loại khỏi mẫu số.",
        f"{len(cells)} ô logic, {len(records)} request khác nhau; {summary['identical_payloads_reused']} ô dùng chung response vì payload giống hệt.",
        "Xem metrics.json để tách nhóm thật sự có thông tin URL/RAG, overlap miền và baseline luôn HIGH/LOW.",
        "Không chọn prompt/ngưỡng theo kết quả này, không khẳng định LLM+URL phải thắng. RAG ở đây trước phân loại, khác candidate giải thích sau verdict.",
        "120 reserve không được suy luận; URL minh họa trong stress không được chấm model hoặc dùng làm nhãn URL."]
    (out / "report.md").write_text("\n".join(lines) + "\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "run", "report", "verify"])
    parser.add_argument("--pack", type=Path)
    parser.add_argument("--labels", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if args.command == "prepare":
        config = prepare(args.pack, args.labels, args.out)
        result = {"requests": config["max_attempts"], "logical_cells": config["metadata"]["logical_cells"], "API_calls": 0}
    elif args.command == "run": result = asyncio.run(registered.run(args.out, parse_response, live=args.live))
    elif args.command == "verify": result = registered.verify(args.out, parse_response)
    else:
        value = results(args.out)
        result = {"sms_reference_counts": value["sms_reference_counts"], "physical_run": value["physical_run"]}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
