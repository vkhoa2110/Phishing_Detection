"""Compare fixed retrieval policies on already-seen AI dev references, offline."""
import argparse
import json
from pathlib import Path

from app.core.settings import Settings
from app.services.rag.action_retrieval import ActionAwareRAG
from app.services.rag.retrieval import RAGService
from evaluation.data.sms import read_jsonl, sha, write_json


def run(inputs, reference, out):
    inputs, reference, out = Path(inputs), Path(reference), Path(out)
    if out.exists(): raise ValueError("Choose a new comparison directory.")
    manifest = json.loads((reference / "manifest.json").read_text())
    for file, field in ((inputs / "queries.jsonl", "query_file_sha256"),
                        (inputs / "corpus.jsonl", "corpus_file_sha256"),
                        (reference / "judgments.jsonl", "judgments_sha256")):
        if sha(file) != manifest[field]: raise ValueError("AI reference changed.")
    queries, docs = read_jsonl(inputs / "queries.jsonl"), read_jsonl(inputs / "corpus.jsonl")
    settings = Settings()
    if read_jsonl(settings.root / settings.rag_corpus) != docs:
        raise ValueError("The current corpus differs from the exact reference inventory.")
    rows = read_jsonl(reference / "judgments.jsonl")
    grades = {(r["query_id"], r["document_id"]): r["grade"] for r in rows}
    inventory = {(q["id"], d["id"]) for q in queries for d in docs}
    if len(grades) != len(rows) or set(grades) != inventory: raise ValueError("Incomplete judgment inventory.")
    base = RAGService(settings, include_scope=True)
    if not base.status()["ready"]: raise ValueError("The frozen local index is not ready.")
    policies = {"e5_existing_filter": base, "action_hybrid_candidate": ActionAwareRAG(base)}
    result = {"reference_quality": "assistant_AI_not_human_gold", "already_seen_development_queries": True,
        "parameters_fitted_in_this_run": False, "heuristic_informed_by_previous_dev_errors": True,
        "new_external_test": False, "provider_calls": 0, "policies": {}}
    per_query = []
    for name, retriever in policies.items():
        counts = dict(queries=len(queries), relevant_queries=0, hits=0, no_match_queries=0,
                      rejected_no_match=0, returned=0, returned_direct=0)
        for query in queries:
            retrieved = retriever.search(query["text"])
            if retrieved["status"] == "unavailable": raise ValueError("Retrieval failure is not a successful rejection.")
            selected = [s["document_id"] for s in retrieved["sources"]]
            direct = {d["id"] for d in docs if grades[(query["id"], d["id"])] == 2}
            if direct:
                counts["relevant_queries"] += 1
                counts["hits"] += bool(direct & set(selected))
            else:
                counts["no_match_queries"] += 1
                counts["rejected_no_match"] += not selected
            counts["returned"] += len(selected)
            counts["returned_direct"] += len(direct & set(selected))
            per_query.append({"policy": name, "query_id": query["id"], "selected": selected,
                              "direct_reference": sorted(direct)})
        divide = lambda a, b: a / b if b else None
        result["policies"][name] = {**counts, "hit_at_return_limit": divide(counts["hits"], counts["relevant_queries"]),
            "precision_returned": divide(counts["returned_direct"], counts["returned"]),
            "no_match_rejection": divide(counts["rejected_no_match"], counts["no_match_queries"])}
    out.mkdir(parents=True)
    write_json(out / "metrics.json", result)
    write_json(out / "queries.json", per_query)
    write_json(out / "manifest.json", {"source_sha256": sha(__file__),
        "query_sha256": sha(inputs / "queries.jsonl"), "reference_sha256": sha(reference / "judgments.jsonl"),
        "retriever_sha256": sha(settings.root / "app/services/rag/action_retrieval.py"),
        "corpus_sha256": sha(settings.root / settings.rag_corpus),
        "index_sha256": sha(settings.root / settings.rag_index_dir / "manifest.json")})
    lines = ["# Truy xuất theo hành vi — diagnostic dev, reference AI", "",
        "Cùng corpus v1/index E5/ngưỡng dense gốc. Candidate thêm pool 10, BM25/RRF, bộ lọc hành vi và tối đa hai nguồn; "
        "chính sách mới chưa được calibration. Heuristic có tham khảo lỗi dev đã xem, không phải test độc lập.", "",
        "| Chính sách | Query có nguồn được tìm thấy | Nguồn trực tiếp / trả về | Từ chối query không có nguồn |",
        "|---|---:|---:|---:|"]
    for name, m in result["policies"].items():
        lines.append(f"| {name} | {m['hits']}/{m['relevant_queries']} | {m['returned_direct']}/{m['returned']} | "
                     f"{m['rejected_no_match']}/{m['no_match_queries']} |")
    lines += ["", "Đo truy xuất theo tóm lược được AI chấm; chưa xác minh lại bài gốc hoặc chứng minh hỗ trợ ngữ nghĩa. "
        "Không suy các tỷ lệ này thành Accuracy/F1 phishing. Không điều chỉnh thêm tham số để làm đẹp lượt này."]
    (out / "report.md").write_text("\n".join(lines) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.inputs, args.reference, args.out), ensure_ascii=False, indent=2))
