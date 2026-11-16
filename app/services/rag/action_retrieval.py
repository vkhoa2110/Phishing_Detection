"""Experimental action-aware hybrid ranks over a frozen local E5 index."""
from collections import Counter
import math
import re
import time
import unicodedata

from app.services.rag.retrieval import E5Encoder, rank_chunks, sha_file

POLICY = "action-hybrid-1.0"


def tokens(text):
    text = unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.findall(r"[a-z0-9]{2,}", text)


def actions(text):
    words = set(tokens(text))
    normalized = " ".join(tokens(text))
    found = set()
    if any(v in normalized for v in ("otp", "mat khau", "ma xac thuc", "ma khoi phuc")):
        found.add("authentication")
    if any(v in normalized for v in ("dieu khien", "chia se man hinh", "ho tro tu xa", "cai phan mem")):
        found.add("remote_access")
    if words & {"phi", "nop", "tra", "chuyen"} and words & {"thuong", "rut", "hoan", "ngan", "viec"}:
        found.add("advance_payment")
    if "quyen" in words and words & {"email", "khoan", "nhap", "dung"}:
        found.add("account_permissions")
    if any(v in normalized for v in ("bao lanh", "khoi kien", "cic", "no xau")):
        found.add("debt")
    if any(v in normalized for v in ("hoan tien", "thu hoi", "chuyen nham")):
        found.add("refund")
    return found


def rerank(query, candidates, *, top_k=2):
    """Action overlap is an IR heuristic, never fraud or source-entailment proof."""
    query_actions = actions(query)
    documents = [tokens(c["title"] + " " + c["text"]) for c in candidates]
    lengths = [len(d) for d in documents]
    average = sum(lengths) / len(lengths) if lengths else 1
    frequencies = Counter(term for doc in documents for term in set(doc))
    scores = []
    for doc in documents:
        tf = Counter(doc)
        score = 0
        for word in set(tokens(query)):
            count = tf[word]
            if count:
                idf = math.log(1 + (len(documents) - frequencies[word] + .5) / (frequencies[word] + .5))
                score += idf * count * 2.2 / (count + 1.2 * (.25 + .75 * len(doc) / max(average, 1)))
        scores.append(score)
    sparse_order = sorted(range(len(candidates)), key=lambda i: (-scores[i], candidates[i]["document_id"]))
    sparse_rank = {i: rank for rank, i in enumerate(sparse_order, 1)}
    result = []
    for dense_rank, source in enumerate(candidates, 1):
        overlap = query_actions & actions(source["title"] + " " + source["text"] + " " + source.get("context_note", ""))
        if query_actions and not overlap:
            continue
        i = dense_rank - 1
        rrf = 1 / (60 + dense_rank) + (1 / (60 + sparse_rank[i]) if scores[i] > 0 else 0)
        result.append({**source, "rrf_score": round(rrf, 8), "action_overlap": sorted(overlap)})
    result.sort(key=lambda s: (-len(s["action_overlap"]), -s["rrf_score"], -s["score"], s["document_id"]))
    return result[:top_k]


class ActionAwareRAG:
    def __init__(self, base):
        self.base = base
        self.settings = base.settings

    def status(self):
        return {**self.base.status(), "retrieval_policy": POLICY, "operating_policy_calibrated": False}

    def search(self, text, mode="text"):
        if mode == "url": return self.base.search(text, mode)
        started = time.perf_counter()
        with self.base.lock:
            try:
                index, config = self.base.inspect()
                if self.base.encoder is None:
                    self.base.encoder = E5Encoder(self.base.path(self.settings.rag_model_dir))
                encoder = self.base.encoder
                windows = encoder.split(text, budget=300, overlap=40)
                if not windows:
                    return {"status": "empty", "sources": [], "reason": "Không có nội dung để truy xuất."}
                vectors = encoder.encode(windows, "query: ")
                candidates = rank_chunks(index.chunks, index.vectors, vectors, top_k=10, min_score=config["min_score"])
                selected = rerank(text, candidates)
                return {"status": "ok" if selected else "empty", "sources": selected,
                    "reason": "Nguồn tham khảo theo hành vi; cần kiểm tra hỗ trợ ngữ nghĩa." if selected else "Chưa có nguồn đạt bộ lọc hành vi.",
                    "retrieval_policy": POLICY, "operating_policy_calibrated": False,
                    "base_dense_min_score": config["min_score"], "dense_candidates": len(candidates),
                    "query_actions": sorted(actions(text)),
                    "index_manifest_sha256": sha_file(self.base.path(self.settings.rag_index_dir) / "manifest.json"),
                    "elapsed_ms": round(1000 * (time.perf_counter() - started), 1)}
            except (ImportError, OSError, ValueError, KeyError, TypeError, RuntimeError):
                return {"status": "unavailable", "sources": [], "reason": "Chưa truy xuất được nguồn theo hành vi."}
