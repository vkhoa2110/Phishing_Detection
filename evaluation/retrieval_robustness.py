"""Dev-only selection for accent robustness; previously seen test is regression only.

No application settings, corpus, old index, or old calibration is modified.
All fixed methods use identical augmented dev cases and the same >=90% hit rule.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import unicodedata

import numpy as np

from app.privacy import redact
from app.rag_service import E5Encoder, RetrievalIndex, read_jsonl, sha_file, write_json
from app.settings import ROOT
from .retrieval import metrics, select_threshold
from .retrieval_comparison import BM25, top_documents, validate_queries

METHODS = ("e5_original", "e5_dual_view", "bm25_original", "bm25_folded")


def fold_accents(text):
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn").replace("đ", "d").replace("Đ", "D")


def augment_dev(cases):
    result, seen = [], set()
    for c in cases:
        for view, text in (("original", c["text"]), ("folded", fold_accents(c["text"]))):
            normalized = " ".join(text.casefold().split())
            if normalized in seen: continue
            seen.add(normalized)
            result.append({**c, "id": c["id"] + "-" + view, "text": text,
                           "parent_id": c["id"], "view": view, "split": "dev"})
    return result


def dual_scores(original_query, folded_query, original_documents, folded_documents):
    # Align each query view to the matching document view, no translation or generated claims.
    return np.maximum((original_query @ original_documents.T).max(axis=0),
                      (folded_query @ folded_documents.T).max(axis=0))


def score(cases, index, encoder, folded_vectors, lexical, folded_lexical):
    result = {m: [] for m in METHODS}
    for c in cases:
        text = redact(c["text"])[0]
        folded = fold_accents(text)
        start = time.perf_counter()
        original_q = encoder.encode(encoder.split(text), "query: ")
        dense = (original_q @ index.vectors.T).max(axis=0)
        original_ms = 1000 * (time.perf_counter() - start)
        start = time.perf_counter()
        folded_q = encoder.encode(encoder.split(folded), "query: ")
        dual = dual_scores(original_q, folded_q, index.vectors, folded_vectors)
        dual_ms = original_ms + 1000 * (time.perf_counter() - start)
        start = time.perf_counter(); bm25 = lexical.score(text)
        bm25_ms = 1000 * (time.perf_counter() - start)
        start = time.perf_counter(); bm25_folded = folded_lexical.score(folded)
        folded_ms = 1000 * (time.perf_counter() - start)
        for method, scores, elapsed in (("e5_original", dense, original_ms), ("e5_dual_view", dual, dual_ms),
                                        ("bm25_original", bm25, bm25_ms), ("bm25_folded", bm25_folded, folded_ms)):
            result[method].append({"id": c["id"], "relevant_ids": c["relevant_ids"],
                "ranked": top_documents(scores, index.chunks), "elapsed_ms": round(elapsed, 3)})
    return result


def select_on_dev(predictions):
    calibrations = {}
    for method, rows in predictions.items():
        try:
            threshold, result = select_threshold(rows)
            calibrations[method] = {"status": "qualified", "min_score": threshold, "dev_metrics": result}
        except ValueError:
            calibrations[method] = {"status": "infeasible_dev_hit_below_90_percent", "min_score": None}
    qualified = [m for m in METHODS if calibrations[m]["status"] == "qualified"]
    selected = max(qualified, key=lambda m: (calibrations[m]["dev_metrics"]["balanced_query_accuracy"],
                   calibrations[m]["dev_metrics"]["precision_returned_sources"] or 0,
                   -METHODS.index(m))) if qualified else None
    return calibrations, selected


def evaluate(args):
    if args.out.exists(): raise ValueError("Choose a fresh output directory.")
    documents = read_jsonl(args.corpus)
    original_dev, regression = read_jsonl(args.dev), read_jsonl(args.regression)
    validate_queries(original_dev, regression, documents)
    dev = augment_dev(original_dev)
    if {" ".join(c["text"].casefold().split()) for c in dev} & {" ".join(c["text"].casefold().split()) for c in regression}:
        raise ValueError("Augmented dev overlaps regression text.")
    index = RetrievalIndex.load(args.index, args.corpus)
    encoder = E5Encoder(args.model_dir)
    start = time.perf_counter()
    folded_vectors = encoder.encode([fold_accents(c["text"]) for c in index.chunks], "passage: ")
    lexical = BM25([c["text"] for c in index.chunks])
    folded_lexical = BM25([fold_accents(c["text"]) for c in index.chunks])
    build_ms = 1000 * (time.perf_counter() - start)
    args.out.mkdir(parents=True)
    np.save(args.out / "folded_embeddings.npy", folded_vectors, allow_pickle=False)
    (args.out / "dev_augmented.jsonl").write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in dev))
    config = {"created_at": datetime.now(timezone.utc).isoformat(), "source_sha256": sha_file(__file__),
        "corpus_sha256": sha_file(args.corpus), "dev_sha256": sha_file(args.dev), "regression_sha256": sha_file(args.regression),
        "augmented_dev_sha256": sha_file(args.out / "dev_augmented.jsonl"),
        "index_manifest_sha256": sha_file(args.index / "manifest.json"),
        "folded_embeddings_sha256": sha_file(args.out / "folded_embeddings.npy"),
        "methods": list(METHODS), "transformation": "NFD remove Mn; map đ/Đ to d/D; no learned spelling correction",
        "dual_score": "max(original query/original passage cosine, folded query/folded passage cosine)",
        "threshold_objective": "dev balanced query accuracy subject to hit@3>=0.90; tie precision then higher threshold",
        "method_selection": "dev balanced query accuracy, then annotated-source precision, then predefined method order",
        "top_k": 3, "bm25_k1": 1.2, "bm25_b": .75, "new_passage_embedding_ms": round(build_ms, 2),
        "application_changed": False, "provider_calls": 0,
        "limitations": "Assistant-authored relevance, incomplete judgments. Augmented dev variants are correlated. Regression was seen before development; no new independent test or phishing F1 claim."}
    write_json(args.out / "protocol.json", config)
    dev_predictions = score(dev, index, encoder, folded_vectors, lexical, folded_lexical)
    calibrations, selected = select_on_dev(dev_predictions)
    write_json(args.out / "calibration.json", {"selected_on": "augmented_dev_only", "selected_method": selected, "methods": calibrations})
    regression_predictions = score(regression, index, encoder, folded_vectors, lexical, folded_lexical)
    result = {"protocol": config, "original_dev_cases": len(original_dev), "augmented_dev_cases": len(dev),
        "regression_cases": len(regression), "selected_method_on_dev": selected, "methods": {}}
    for method in METHODS:
        threshold = calibrations[method]["min_score"]
        result["methods"][method] = {"calibration": calibrations[method],
            "dev_raw": metrics(dev_predictions[method], -float("inf")),
            "regression_raw": metrics(regression_predictions[method], -float("inf")),
            "regression_filtered": metrics(regression_predictions[method], threshold) if threshold is not None else None}
    write_json(args.out / "predictions.json", {"dev": dev_predictions, "regression": regression_predictions})
    write_json(args.out / "summary.json", result)
    lines = ["# Thử nghiệm retrieval cho tiếng Việt không dấu", "", config["limitations"], "",
        f"Dev gốc {len(original_dev)}; sau thêm biến thể bỏ dấu {len(dev)}. Biến thể cùng câu không phải quan sát độc lập. "
        f"Regression {len(regression)} câu đã xem từ v2, KHÔNG phải test độc lập. Không đổi ứng dụng.", "",
        f"Phương pháp được chọn CHỈ trên dev: **{selected}**.", "",
        "| Phương pháp | Dev hit raw | Dev hit sau lọc | Dev từ chối | Regression hit | Regression từ chối | Ngưỡng dev |",
        "|---|---:|---:|---:|---:|---:|---:|"]
    for method in METHODS:
        r = result["methods"][method]; c = r["calibration"]; d = c.get("dev_metrics"); t = r["regression_filtered"]
        if d is None:
            lines.append(f"| {method} | {100*r['dev_raw']['hit_at_3']:.2f}% | Không đạt ≥90% | — | — | — | Không chọn |"); continue
        lines.append(f"| {method} | {100*r['dev_raw']['hit_at_3']:.2f}% | {100*d['hit_at_3']:.2f}% | "
                     f"{d['rejected_no_match']}/{d['no_match_queries']} | {100*t['hit_at_3']:.2f}% | "
                     f"{t['rejected_no_match']}/{t['no_match_queries']} | {c['min_score']} |")
    lines += ["", "Các phương pháp được hiệu chỉnh lại trên CÙNG dev tăng cường. Không đối chiếu ngưỡng mới với ngưỡng v2 như cùng điều kiện. "
        "Tối đa hai lượt encode query cho E5 dual; bộ vector đoạn bỏ dấu được lưu riêng. Không sinh thêm câu hoặc đổi nội dung gửi LLM.", "",
        "Bỏ dấu không khôi phục dấu đúng và có thể nhập nhằng nhiều từ. Chưa xử lý đầy đủ sai thực thể/thời gian hoặc bảo đảm nguồn hỗ trợ kết luận. "
        "Cần người rà relevance, nguồn hỗ trợ và một test mới trước khi triển khai."]
    (args.out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=ROOT / "data/knowledge/corpus_v2/documents.jsonl")
    parser.add_argument("--index", type=Path, default=ROOT / "artifacts/rag/e5-small-v2-r1")
    parser.add_argument("--dev", type=Path, default=ROOT / "data/evaluation/rag_retrieval_dev_v2.jsonl")
    parser.add_argument("--regression", type=Path, default=ROOT / "data/evaluation/rag_retrieval_test_v2.jsonl")
    parser.add_argument("--model-dir", type=Path, default=ROOT / "models/embeddings/multilingual-e5-small")
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts/rag-evaluation/accent_robustness_v1")
    args = parser.parse_args()
    result = evaluate(args)
    print(json.dumps({"selected_on_dev": result["selected_method_on_dev"], "out": str(args.out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
