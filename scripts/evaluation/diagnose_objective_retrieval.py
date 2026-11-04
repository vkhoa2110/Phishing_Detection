"""DEV-only retrieval diagnostic against explicitly provisional AI relevance."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from app.privacy import redact
from app.rag_service import RAGService
from app.settings import Settings
from evaluation.benchmark_pack import verify
from evaluation.message_data import read_jsonl
from evaluation.retrieval import metrics as independent_metrics


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def average(rows, key):
    values = [r[key] for r in rows if r[key] is not None]
    return {"value": sum(values) / len(values) if values else None, "n": len(values)}


def run(pack, reference, out):
    pack, reference, out = Path(pack), Path(reference), Path(out)
    if out.exists():
        raise ValueError("Choose a new output directory; preserve earlier diagnostics.")
    verify(pack)
    manifest = json.loads((reference / "manifest.json").read_text())
    if manifest.get("status") != "ai_reference_unverified" or manifest.get("rater_ids") != []:
        raise ValueError("This diagnostic only accepts declared AI references; human-gold uses relevance_review.")
    for name, digest in manifest["files"].items():
        if name not in {"judgments.json", "review.csv"} or sha(reference / name) != digest:
            raise ValueError("AI relevance reference changed.")
    path = pack / "retrieval"
    if manifest["corpus_sha256"] != sha(path / "corpus.jsonl") or manifest["queries_sha256"] != sha(path / "queries.jsonl"):
        raise ValueError("Relevance reference does not match the frozen corpus/queries.")
    docs = {d["id"] for d in read_jsonl(path / "corpus.jsonl")}
    queries = [q for q in read_jsonl(path / "queries.jsonl") if q["split"] == "dev"]
    judgments = json.loads((reference / "judgments.json").read_text())
    service = RAGService(Settings(), include_scope=True)
    results, independent = [], []
    for q in queries:
        chosen = [r for r in judgments if r["query_id"] == q["id"]]
        grades = {r["document_id"]: r["grade"] for r in chosen}
        if len(chosen) != len(docs) or set(grades) != docs or any(type(g) is not int or g not in (0, 1, 2) for g in grades.values()):
            raise ValueError("Reference must judge all documents for each query.")
        started = time.perf_counter()
        retrieval = service.search(redact(q["text"])[0], "text")
        elapsed = round(1000 * (time.perf_counter() - started), 2)
        valid = retrieval["status"] in {"ok", "empty"}
        sources = retrieval["sources"] if valid else []
        returned = [s["document_id"] for s in sources]
        relevant = {d for d, g in grades.items() if g == 2}
        hits = len(set(returned) & relevant)
        dcg = sum((2**grades[d] - 1) / math.log2(i+2) for i, d in enumerate(returned))
        ideal = sum((2**g - 1) / math.log2(i+2) for i, g in enumerate(sorted(grades.values(), reverse=True)[:3]))
        results.append({"id": q["id"], "text": q["text"], "retrieval_status": retrieval["status"],
            "technical_success": valid, "relevant_ids_ai": sorted(relevant), "returned": returned,
            "scores": [s["score"] for s in sources], "returned_grades_ai": [grades[d] for d in returned],
            "elapsed_ms": elapsed, "hit_at_3": int(hits > 0) if relevant else None,
            "precision_at_3": hits / 3, "precision_returned": hits / len(returned) if returned else None,
            "recall_at_3": hits / len(relevant) if relevant else None,
            "mrr_at_3": next((1 / (i+1) for i, d in enumerate(returned) if d in relevant), 0) if relevant else None,
            "ndcg_at_3": dcg / ideal if ideal else None,
            "no_match_rejection": int(valid and not returned) if not relevant else None})
        independent.append({"id": q["id"], "relevant_ids": sorted(relevant), "ranked": sources, "elapsed_ms": elapsed})
    keys = ("hit_at_3", "precision_at_3", "precision_returned", "recall_at_3", "mrr_at_3", "ndcg_at_3", "no_match_rejection")
    metrics = {key: average(results, key) for key in keys}
    # Independent count check, not a check that AI relevance is semantically right.
    if all(r["technical_success"] for r in results):
        check = independent_metrics(independent, -1)
        assert abs(check["hit_at_3"] - metrics["hit_at_3"]["value"]) < 1e-12
        assert abs(check["no_match_rejection_rate"] - metrics["no_match_rejection"]["value"]) < 1e-12
    summary = {"created_at": datetime.now(timezone.utc).isoformat(), "split": "dev",
        "reference_status": "ai_reference_unverified", "queries": len(results),
        "queries_with_direct_source_ai": sum(bool(r["relevant_ids_ai"]) for r in results),
        "queries_without_direct_source_ai": sum(not r["relevant_ids_ai"] for r in results),
        "technical_errors": sum(not r["technical_success"] for r in results), "provider_requests": 0,
        "metrics": metrics, "rows": results,
        "hashes": {"protocol": sha(pack / "protocol.json"), "reference_manifest": sha(reference / "manifest.json"),
                   "corpus": sha(path / "corpus.jsonl"), "code": sha(__file__)},
        "limitations": "DEV diagnostic using single-assistant provisional relevance, not independent human gold. No test queries run, no threshold tuning. Technical errors never counted as correct no-match rejection; relevance is not phishing accuracy."}
    lines = ["# Truy xuất RAG trên dev — đối chiếu nhãn AI sơ bộ", "",
             "**Chưa phải relevance gold do người chấm độc lập.** Không chọn lại ngưỡng trong lượt này.", "",
             f"{summary['queries']} truy vấn: {summary['queries_with_direct_source_ai']} có nguồn trực tiếp theo AI, "
             f"{summary['queries_without_direct_source_ai']} chưa có. {summary['technical_errors']} lỗi kỹ thuật. 0 lượt provider.", "",
             "| Chỉ số | Giá trị | Số truy vấn có mẫu số xác định |", "|---|---:|---:|"]
    for name, metric in metrics.items():
        value = "N/A" if metric["value"] is None else f"{100*metric['value']:.2f}%"
        lines.append(f"| {name} | {value} | {metric['n']} |")
    lines += ["", "Grade 2 là hỗ trợ trực tiếp; grade 1 chỉ liên quan chủ đề. Precision@3 dùng mẫu số 3, "
              "Precision_returned chỉ tính tài liệu đã trả. NDCG dùng cả mức 1 và 2. Các giá trị này phụ thuộc "
              "nhãn AI và thang relevance, không đo độ chính xác phát hiện phishing.", "",
              "| ID | Nguồn trực tiếp theo AI | Tài liệu trả về | Grade AI của tài liệu trả |", "|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r['id']} | {', '.join(r['relevant_ids_ai']) or 'Không có'} | {', '.join(r['returned']) or 'Không trả'} | {r['returned_grades_ai']} |")
    out.mkdir(parents=True)
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, default=ROOT / "data/annotation/objective_v1")
    parser.add_argument("--reference", type=Path, default=ROOT / "artifacts/annotations/objective_retrieval_ai_v1")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run(args.pack, args.reference, args.out)
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(2, f"Retrieval diagnostic stopped: {exc}\n")
    print(json.dumps({k:result[k] for k in ("queries", "technical_errors", "provider_requests", "metrics")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
