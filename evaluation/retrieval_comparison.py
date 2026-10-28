"""Compare BM25, E5, and reciprocal-rank fusion locally; no provider calls.

Parameters are fixed. Optional rejection thresholds use dev only, with the
same >=90% dev hit@3 requirement as the deployed retriever. No runtime changes.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import time
import unicodedata

import numpy as np

from app.privacy import redact
from app.rag_service import E5Encoder, RetrievalIndex, read_json, read_jsonl, sha_file, write_json
from app.settings import ROOT
from .retrieval import metrics, select_threshold


def tokens(text):
    return re.findall(r"\w+", unicodedata.normalize("NFC", text).casefold())


class BM25:
    def __init__(self, texts, k1=1.2, b=.75):
        self.docs = [Counter(tokens(t)) for t in texts]
        self.lengths = np.array([sum(d.values()) for d in self.docs])
        self.average = float(self.lengths.mean())
        if self.average <= 0:
            raise ValueError("Empty BM25 corpus.")
        self.k1, self.b = k1, b
        df = Counter(term for d in self.docs for term in d)
        self.idf = {t: math.log(1 + (len(texts) - n + .5) / (n + .5)) for t, n in df.items()}

    def score(self, text):
        result = np.zeros(len(self.docs))
        for term in set(tokens(text)):
            tf = np.array([d[term] for d in self.docs], dtype=float)
            denominator = tf + self.k1 * (1 - self.b + self.b * self.lengths / self.average)
            result += self.idf.get(term, 0) * tf * (self.k1 + 1) / denominator
        return result


def order(scores, chunks):
    return sorted(range(len(scores)), key=lambda i: (-float(scores[i]), chunks[i]["chunk_id"]))


def reciprocal_rank_fusion(dense, lexical, chunks, k=60):
    scores = np.zeros(len(chunks))
    for raw in (dense, lexical):
        for rank, i in enumerate(order(raw, chunks), 1):
            if raw[i] > 0:
                scores[i] += 1 / (k + rank)
    return scores


def top_documents(scores, chunks):
    selected, seen = [], set()
    for i in order(scores, chunks):
        doc = chunks[i]["document_id"]
        if doc not in seen:
            selected.append({"document_id": doc, "score": round(float(scores[i]), 6)})
            seen.add(doc)
        if len(selected) == 3:
            break
    return selected


def score_cases(cases, index, encoder, lexical):
    result = {method: [] for method in ("bm25", "e5", "hybrid_rrf")}
    for c in cases:
        start = time.perf_counter()
        text = redact(c["text"])[0]
        bm25 = lexical.score(text)
        lexical_ms = 1000 * (time.perf_counter() - start)
        dense_start = time.perf_counter()
        vectors = encoder.encode(encoder.split(text), "query: ")
        dense = (vectors @ index.vectors.T).max(axis=0)
        dense_ms = 1000 * (time.perf_counter() - dense_start)
        rrf_start = time.perf_counter()
        rrf = reciprocal_rank_fusion(dense, bm25, index.chunks)
        rrf_ms = 1000 * (time.perf_counter() - rrf_start)
        for method, scores, elapsed in (("bm25", bm25, lexical_ms), ("e5", dense, dense_ms),
                                        ("hybrid_rrf", rrf, lexical_ms + dense_ms + rrf_ms)):
            result[method].append({"id": c["id"], "relevant_ids": c["relevant_ids"],
                                   "ranked": top_documents(scores, index.chunks), "elapsed_ms": round(elapsed, 3)})
    return result


def validate_queries(dev, test, documents):
    """Reject repeated inputs, missing relevance targets and unsupported annotated quotes."""
    known = {d["id"]: d for d in documents}
    all_cases = dev + test
    normalized = lambda text: " ".join(unicodedata.normalize("NFC", redact(text)[0]).casefold().split())
    if len({c["id"] for c in all_cases}) != len(all_cases):
        raise ValueError("Dev/test IDs overlap.")
    if len({normalized(c["text"]) for c in all_cases}) != len(all_cases):
        raise ValueError("Dev/test inputs overlap after redaction/normalization.")
    for split, cases in (("dev", dev), ("test", test)):
        if not any(c["relevant_ids"] for c in cases) or not any(not c["relevant_ids"] for c in cases):
            raise ValueError("Each split needs relevant and no-match queries.")
        for c in cases:
            if c.get("split", split) != split or not c["text"].strip():
                raise ValueError("Invalid split or empty query.")
            if len(c["relevant_ids"]) != len(set(c["relevant_ids"])) or not set(c["relevant_ids"]) <= known.keys():
                raise ValueError("Unknown/duplicate relevance ID.")
            if "support" in c:
                if {s["document_id"] for s in c["support"]} != set(c["relevant_ids"]):
                    raise ValueError("Support must cover every annotated relevant document.")
                for s in c["support"]:
                    if not s["quote"].strip() or s["quote"] not in known[s["document_id"]]["text"]:
                        raise ValueError("Relevance evidence is not an exact summary substring.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts/rag-evaluation/retrieval_comparison_v1")
    parser.add_argument("--corpus", type=Path, default=ROOT / "data/knowledge/corpus_v1/documents.jsonl")
    parser.add_argument("--index", type=Path, default=ROOT / "artifacts/rag/e5-small-v1")
    parser.add_argument("--dev", type=Path, default=ROOT / "data/evaluation/rag_retrieval_dev_v1.jsonl")
    parser.add_argument("--test", type=Path, default=ROOT / "data/evaluation/rag_retrieval_test_v1.jsonl")
    parser.add_argument("--model-dir", type=Path, default=ROOT / "models/embeddings/multilingual-e5-small")
    args = parser.parse_args()
    if args.out.exists():
        parser.error("Choose a fresh output directory; comparisons are immutable snapshots.")
    corpus, index_dir, dev_path, test_path = args.corpus, args.index, args.dev, args.test
    dev_cases, test_cases = read_jsonl(dev_path), read_jsonl(test_path)
    validate_queries(dev_cases, test_cases, read_jsonl(corpus))
    index = RetrievalIndex.load(index_dir, corpus)
    encoder = E5Encoder(args.model_dir)
    lexical = BM25([c["text"] for c in index.chunks])
    # Warm encoder so timing excludes checkpoint loading / one-time kernel setup.
    encoder.encode(["Kiểm tra khởi động bộ truy xuất."], "query: ")
    dev = score_cases(dev_cases, index, encoder, lexical)
    calibrations = {}
    for method, rows in dev.items():
        try:
            threshold, _ = select_threshold(rows)
            calibrations[method] = {"status": "qualified", "min_score": threshold, "selected_on": "dev"}
        except ValueError:
            calibrations[method] = {"status": "infeasible_dev_hit_at_3_below_90_percent", "min_score": None}
    if (index_dir / "calibration.json").exists():
        frozen = read_json(index_dir / "calibration.json")
        if frozen["dev_sha256"] == sha_file(dev_path):
            if calibrations["e5"]["min_score"] != frozen["min_score"]:
                raise ValueError("E5 calibration disagrees with the frozen dev run.")
    args.out.mkdir(parents=True)
    write_json(args.out / "calibration.json", calibrations)
    # No threshold is selected or modified after generating test predictions.
    test = score_cases(test_cases, index, encoder, lexical)
    summary = {"created_at": datetime.now(timezone.utc).isoformat(), "calibration": calibrations,
        "configuration": {"corpus_sha256": sha_file(corpus), "dev_sha256": sha_file(dev_path),
            "test_sha256": sha_file(test_path), "index_manifest_sha256": sha_file(index_dir / "manifest.json"),
            "source_sha256": sha_file(__file__), "bm25_k1": 1.2, "bm25_b": .75, "rrf_k": 60,
            "lexical_tokenizer": "NFC Unicode word tokens, casefold, no stopwords or Vietnamese word segmentation",
            "same_indexed_fields": "chunk text only", "top_k": 3},
        "limitations": "Assistant-authored source-relevance probes, not human-reviewed gold or phishing classification. Dev/test use different wording but share source topics. Relevance may be incomplete. Fixed methods and dev-only threshold selection; no application threshold changed.",
        "methods": {}}
    for method in dev:
        threshold = calibrations[method]["min_score"]
        summary["methods"][method] = {"dev_raw_top3": metrics(dev[method], -float("inf")),
            "test_raw_top3": metrics(test[method], -float("inf")),
            "dev_filtered": metrics(dev[method], threshold) if threshold is not None else None,
            "test_filtered": metrics(test[method], threshold) if threshold is not None else None}
    write_json(args.out / "predictions.json", {"dev": dev, "test": test})
    slices = {}
    for method, rows in test.items():
        slices[method] = {}
        for kind in sorted({c.get("query_kind", "unspecified") for c in test_cases}):
            ids = {c["id"] for c in test_cases if c.get("query_kind", "unspecified") == kind}
            selected = [r for r in rows if r["id"] in ids]
            threshold = calibrations[method]["min_score"]
            slices[method][kind] = {"raw_top3": metrics(selected, -float("inf")),
                                   "filtered": metrics(selected, threshold) if threshold is not None else None}
    write_json(args.out / "test_slices.json", slices)
    write_json(args.out / "summary.json", summary)
    lines = ["# So sánh truy xuất BM25, E5 và Hybrid RRF", "", summary["limitations"], "",
        f"Cùng {len(index.chunks)} chunk, top-3, text-only. Dev: {len(dev_cases)}; test: {len(test_cases)}. "
        "BM25 k1=1.2, b=0.75; RRF k=60. Ngưỡng chọn trên dev với hit@3 >=90%; nếu không đạt thì ghi không khả thi, không hạ điều kiện. Không thay cấu hình ứng dụng.", "",
        "| Phương pháp | Chế độ | Test hit@3 | Test precision nguồn | Từ chối không nguồn | Dev hit@3 | Ngưỡng |",
        "|---|---|---:|---:|---:|---:|---:|"]
    for method, result in summary["methods"].items():
        for mode in ("raw_top3", "filtered"):
            t, d = result["test_" + mode], result["dev_" + mode]
            if t is None:
                lines.append(f"| {method} | {mode} | Không đạt điều kiện dev | | | | |"); continue
            precision = "N/A" if t["precision_returned_sources"] is None else f"{100*t['precision_returned_sources']:.2f}%"
            lines.append(f"| {method} | {mode} | {100*t['hit_at_3']:.2f}% | {precision} | "
                         f"{t['rejected_no_match']}/{t['no_match_queries']} | {100*d['hit_at_3']:.2f}% | "
                         f"{calibrations[method]['min_score'] if mode == 'filtered' else 'không lọc'} |")
    lines += ["", "Hit@3 chỉ cần có ít nhất một nguồn đúng, còn precision đếm tỷ lệ từng nguồn đúng. "
        "Raw top-3 luôn trả 3 tài liệu, kể cả truy vấn không liên quan. Không được so trực tiếp raw top-3 với filtered để quy lợi ích cho embedding.",
        "", "Các số đo truy xuất không phải Precision/Recall/F1 phân loại lừa đảo. Nhãn relevance còn hẹp và cần được thẩm định độc lập."]
    (args.out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
