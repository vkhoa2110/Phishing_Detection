"""Compare corpus coverage and raw E5 top-3 using a locked, complete relevance grid."""
import argparse
import json
from pathlib import Path

from app.services.rag.retrieval import E5Encoder, RetrievalIndex, rank_chunks
from evaluation.data.sms import read_jsonl, sha, write_json, write_jsonl


def validate_grid(queries, old_docs, new_docs, judgments):
    qids = {q["id"] for q in queries}
    old = {d["id"]: d for d in old_docs}
    new = {d["id"]: d for d in new_docs}
    if len(qids) != len(queries) or len(old) != len(old_docs) or len(new) != len(new_docs):
        raise ValueError("Duplicate query or document ID.")
    if not old or not set(old) < set(new) or any(new.get(k) != v for k, v in old.items()):
        raise ValueError("Expansion must preserve all old documents unchanged.")
    grades = {(r["query_id"], r["document_id"]): r["grade"] for r in judgments}
    if (len(grades) != len(judgments) or set(grades) != {(q, d) for q in qids for d in new}
            or any(type(v) is not int or v not in {0, 1, 2} for v in grades.values())):
        raise ValueError("Require exactly one 0–2 grade for every query/document pair.")
    return grades


def score(rows, doc_ids):
    answerable = [r for r in rows if r["direct_ids"]]
    possible = [r for r in answerable if set(r["direct_ids"]) & doc_ids]
    hits = sum(bool(set(r["direct_ids"]) & set(r["selected_ids"])) for r in rows)
    relevant_returned = sum(len(set(r["direct_ids"]) & set(r["selected_ids"])) for r in rows)
    returned = sum(len(r["selected_ids"]) for r in rows)
    return {"queries": len(rows), "answerable_in_expanded_reference": len(answerable),
        "answerable_in_this_corpus": len(possible), "hits": hits,
        "hit_on_fixed_expanded_denominator": hits / len(answerable) if answerable else None,
        "hit_on_corpus_answerable_queries": hits / len(possible) if possible else None,
        "direct_returned": relevant_returned, "returned": returned,
        "precision_returned": relevant_returned / returned if returned else None,
        "no_match_queries": len(rows) - len(answerable), "abstention_policy_evaluated": False}


def run(registration, old_index, new_index, model_dir, out):
    registration, out = Path(registration), Path(out)
    if out.exists(): raise ValueError("Choose a new output directory.")
    if sha(registration) != registration.with_suffix(".sha256").read_text().strip():
        raise ValueError("Registration changed.")
    config = json.loads(registration.read_text())
    for name, expected in config["locks"].items():
        if sha(name) != expected: raise ValueError("Registered input changed: " + name)
    paths = config["inputs"]
    queries = read_jsonl(paths["queries"])
    old_docs, new_docs = read_jsonl(paths["old_corpus"]), read_jsonl(paths["new_corpus"])
    grades = validate_grid(queries, old_docs, new_docs, read_jsonl(paths["judgments"]))
    indexes = {"original_25": RetrievalIndex.load(old_index, paths["old_corpus"]),
               "expanded_29": RetrievalIndex.load(new_index, paths["new_corpus"])}
    encoder = E5Encoder(model_dir)
    rows = {name: [] for name in indexes}
    for query in queries:
        vectors = encoder.encode(encoder.split(query["text"]), "query: ")
        direct = sorted(d["id"] for d in new_docs if grades[(query["id"], d["id"])] == 2)
        for name, index in indexes.items():
            selected = rank_chunks(index.chunks, index.vectors, vectors, top_k=3)
            rows[name].append({"id": query["id"], "direct_ids": direct,
                "selected_ids": [s["document_id"] for s in selected],
                "ranked": [{"id": s["document_id"], "score": s["score"]} for s in selected]})
    metrics = {name: score(items, {c["document_id"] for c in indexes[name].chunks}) for name, items in rows.items()}
    out.mkdir(parents=True)
    write_json(out / "metrics.json", {"corpora": metrics, "reference": "assistant_AI_preliminary",
        "source_selection_used_seen_dev_gaps": True, "threshold_selected": False,
        "independent_test": False, "provider_calls": 0, "default_runtime_changed": False})
    for name, items in rows.items(): write_jsonl(out / (name + ".jsonl"), items)
    write_json(out / "manifest.json", {"registration_sha256": sha(registration), "scorer_sha256": sha(__file__),
        "indexes": {name: sha(Path(folder) / "manifest.json") for name, folder in
                    (("original_25", old_index), ("expanded_29", new_index))},
        "files": {p.name: sha(p) for p in out.iterdir() if p.is_file()}})
    lines = ["# Mở rộng corpus: chẩn đoán dev có nhãn relevance AI", "",
        "Cùng 12 query đã xem, E5 cố định, raw top-3 luôn trả nguồn. Giữ nguyên 25 tài liệu cũ, thêm bốn tài liệu. "
        "Nguồn mới được chọn để xử lý lỗi dev; reference cho mọi cặp được khóa trước suy luận retrieval mới. "
        "Không phải test độc lập, không đánh giá ngưỡng từ chối hoặc F1 phishing.", "",
        "| Corpus | Query có nguồn trực tiếp trong corpus | Hit / query có nguồn ở corpus mở rộng | Nguồn trực tiếp / trả về |",
        "|---|---:|---:|---:|"]
    for name, m in metrics.items():
        lines.append(f"| {name} | {m['answerable_in_this_corpus']} | {m['hits']}/{m['answerable_in_expanded_reference']} | "
                     f"{m['direct_returned']}/{m['returned']} |")
    lines += ["", "Mẫu số chính dùng chung tập query có nguồn theo reference mở rộng; không so hai tỷ lệ với mẫu số âm thầm thay đổi. "
        "Bản mở rộng chưa có calibration hoặc nhãn người, chưa được thay vào app mặc định. "
        "Hai phiếu review giữ trống; không suy thành chất lượng nguồn do người chấm."]
    (out / "report.md").write_text("\n".join(lines) + "\n")
    return metrics


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("registration", "old-index", "new-index", "model-dir", "out"):
        p.add_argument("--" + name, type=Path, required=True)
    args = p.parse_args()
    print(json.dumps(run(args.registration, args.old_index, args.new_index, args.model_dir, args.out), indent=2))
