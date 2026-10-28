"""Small, local E5 retriever. Imports ML extras only when RAG is actually requested."""
from dataclasses import dataclass
import hashlib
import importlib.util
import json
from pathlib import Path
import re
from threading import RLock
import time
from urllib.parse import urlsplit

import numpy as np

MODEL_ID = "intfloat/multilingual-e5-small"
MODEL_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
INDEX_VERSION = "e5-summary-v1"
DIMENSION = 384
MAX_TOKENS = 512


def sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class E5Encoder:
    def __init__(self, directory, threads=4):
        import torch
        from transformers import AutoModel, AutoTokenizer

        directory = Path(directory)
        provenance = read_json(directory / "phishlens_model.json")
        if provenance["model_id"] != MODEL_ID or provenance["revision"] != MODEL_REVISION:
            raise ValueError("Embedding model revision does not match the approved E5 export.")
        if not {"config.json", "model.safetensors", "tokenizer.json", "tokenizer_config.json"} <= provenance["files"].keys():
            raise ValueError("Embedding model provenance is incomplete.")
        for name, expected in provenance["files"].items():
            if name not in {"config.json", "model.safetensors", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json", "sentencepiece.bpe.model"}:
                raise ValueError("Unexpected model file.")
            if sha_file(directory / name) != expected:
                raise ValueError("Embedding model file hash mismatch: " + name)
        torch.set_num_threads(max(1, min(threads, 8)))
        self.torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(str(directory), local_files_only=True, trust_remote_code=False)
        self.model = AutoModel.from_pretrained(str(directory), local_files_only=True, trust_remote_code=False,
                                               use_safetensors=True).to("cpu").eval()

    def split(self, text, budget=300, overlap=40):
        """Split by tokenizer offsets so every citation remains an exact source substring."""
        if not 0 <= overlap < budget <= 450:
            raise ValueError("Invalid chunk token budget.")
        text = text.strip()
        encoded = self.tokenizer(text, add_special_tokens=False, return_offsets_mapping=True)
        offsets = encoded["offset_mapping"]
        if not offsets:
            return []
        result, start = [], 0
        while start < len(offsets):
            end = min(start + budget, len(offsets))
            piece = text[offsets[start][0]:offsets[end - 1][1]].strip()
            if piece:
                result.append(piece)
            if end == len(offsets):
                break
            start = end - overlap
        return result

    def encode(self, texts, prefix, batch_size=8):
        if prefix not in {"query: ", "passage: "} or not texts:
            raise ValueError("E5 requires a query/passsage prefix and nonempty input.")
        torch = self.torch
        vectors = []
        with torch.inference_mode():
            for start in range(0, len(texts), batch_size):
                batch = self.tokenizer([prefix + t for t in texts[start:start + batch_size]],
                                       padding=True, truncation=False, return_tensors="pt")
                if batch["input_ids"].shape[1] > MAX_TOKENS:
                    raise ValueError("Embedding input exceeds 512 tokens; split it first.")
                outputs = self.model(**batch).last_hidden_state
                masked = outputs.masked_fill(~batch["attention_mask"][..., None].bool(), 0.0)
                pooled = masked.sum(dim=1) / batch["attention_mask"].sum(dim=1)[..., None]
                vectors.append(torch.nn.functional.normalize(pooled, p=2, dim=1).cpu().numpy())
        return np.concatenate(vectors).astype(np.float32)


def make_chunks(documents, encoder):
    chunks, seen = [], set()
    for doc in documents:
        if doc["id"] in seen or not re.fullmatch(r"VN-RAG-\d{3}", doc["id"]):
            raise ValueError("Duplicate or invalid document ID.")
        seen.add(doc["id"])
        p = urlsplit(doc["source_url"])
        if p.scheme != "https" or not p.hostname or p.username or p.password:
            raise ValueError("Source must be a public HTTPS URL without credentials.")
        if doc["content_kind"] != "editorial_summary_not_verbatim":
            raise ValueError("Corpus content kind is not supported.")
        if hashlib.sha256(doc["text"].encode()).hexdigest() != doc["summary_sha256"]:
            raise ValueError("Corpus summary hash mismatch.")
        for i, text in enumerate(encoder.split(doc["text"]), 1):
            chunks.append({"chunk_id": f"{doc['id']}-{i:02}", "document_id": doc["id"], "text": text,
                           **{k: doc[k] for k in ("title", "publisher", "source_url", "published_at", "context_note", "kind")}})
    if not chunks:
        raise ValueError("Corpus is empty.")
    return chunks


def validate_vectors(vectors, count):
    if vectors.shape != (count, DIMENSION) or not np.isfinite(vectors).all():
        raise ValueError("Embedding matrix has invalid shape or values.")
    if not np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-4):
        raise ValueError("Embedding vectors must be normalized.")


def build_index(corpus, directory, encoder):
    directory = Path(directory)
    if directory.exists() and any(directory.iterdir()):
        raise ValueError("Index output already contains files; choose a fresh directory.")
    chunks = make_chunks(read_jsonl(corpus), encoder)
    vectors = encoder.encode([c["text"] for c in chunks], "passage: ")
    validate_vectors(vectors, len(chunks))
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "chunks.jsonl").write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in chunks), encoding="utf-8")
    np.save(directory / "embeddings.npy", vectors, allow_pickle=False)
    manifest = {"version": INDEX_VERSION, "model_id": MODEL_ID, "revision": MODEL_REVISION,
                "dimension": DIMENSION, "normalized": True, "corpus_sha256": sha_file(corpus),
                "documents": len({c["document_id"] for c in chunks}), "chunks": len(chunks),
                "chunk_tokens": 300, "overlap_tokens": 40, "passage_prefix": "passage: ",
                "query_prefix": "query: ", "retrieval": "exact_cosine_numpy",
                "files": {name: sha_file(directory / name) for name in ("chunks.jsonl", "embeddings.npy")}}
    write_json(directory / "manifest.json", manifest)
    return manifest


def rank_chunks(chunks, vectors, query_vectors, top_k=3, min_score=-1):
    """Max score over query windows, one chunk per document; no ML scores involved."""
    scores = (query_vectors @ vectors.T).max(axis=0)
    order = sorted(range(len(chunks)), key=lambda i: (-float(scores[i]), chunks[i]["chunk_id"]))
    selected, documents = [], set()
    for i in order:
        chunk = chunks[i]
        if float(scores[i]) < min_score or chunk["document_id"] in documents:
            continue
        selected.append({**chunk, "score": round(float(scores[i]), 6)})
        documents.add(chunk["document_id"])
        if len(selected) >= top_k:
            break
    return selected


@dataclass
class RetrievalIndex:
    chunks: list
    vectors: np.ndarray
    manifest: dict

    @classmethod
    def load(cls, directory, corpus):
        directory = Path(directory)
        m = read_json(directory / "manifest.json")
        if m["version"] != INDEX_VERSION or m["model_id"] != MODEL_ID or m["revision"] != MODEL_REVISION:
            raise ValueError("Index version/model does not match.")
        if m["corpus_sha256"] != sha_file(corpus):
            raise ValueError("Corpus changed; rebuild and recalibrate the RAG index.")
        for name in ("chunks.jsonl", "embeddings.npy"):
            if sha_file(directory / name) != m["files"][name]:
                raise ValueError("RAG index file hash mismatch.")
        chunks = read_jsonl(directory / "chunks.jsonl")
        vectors = np.load(directory / "embeddings.npy", allow_pickle=False)
        validate_vectors(vectors, len(chunks))
        if len(chunks) != m["chunks"] or len({c["chunk_id"] for c in chunks}) != len(chunks):
            raise ValueError("RAG chunk IDs/count do not match.")
        return cls(chunks, vectors, m)


class RAGService:
    def __init__(self, settings):
        self.settings = settings
        self.lock = RLock()
        self.index = self.encoder = self.calibration = None

    def path(self, name):
        return self.settings.root / name

    def inspect(self):
        """Validate small metadata/index without importing torch, downloading, or loading weights."""
        try:
            directory = self.path(self.settings.rag_index_dir)
            index = RetrievalIndex.load(directory, self.path(self.settings.rag_corpus))
            config = read_json(directory / "calibration.json")
            if config["index_manifest_sha256"] != sha_file(directory / "manifest.json"):
                raise ValueError("Calibration belongs to a different index.")
            if not 0 <= config["min_score"] <= 1 or config["top_k"] != 3:
                raise ValueError("Invalid calibration parameters.")
            model_dir = self.path(self.settings.rag_model_dir)
            model_info = read_json(model_dir / "phishlens_model.json")
            if model_info["model_id"] != MODEL_ID or model_info["revision"] != MODEL_REVISION:
                raise ValueError("Embedding revision differs from index.")
            for name in ("config.json", "model.safetensors", "tokenizer.json", "tokenizer_config.json"):
                if name not in model_info["files"] or not (model_dir / name).is_file():
                    raise FileNotFoundError("Embedding files missing.")
            if not all(importlib.util.find_spec(name) for name in ("torch", "transformers")):
                raise ValueError("RAG dependencies not installed.")
            return index, config
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ValueError("RAG chưa sẵn sàng. Cần chuẩn bị model, chỉ mục và ngưỡng truy xuất cùng phiên bản.") from exc

    def status(self):
        try:
            index, config = self.inspect()
            return {"ready": True, "model": MODEL_ID, "revision": MODEL_REVISION,
                    "documents": index.manifest["documents"], "chunks": len(index.chunks),
                    "min_score": config["min_score"], "top_k": config["top_k"],
                    "message": "Kho tham khảo cục bộ đã sẵn sàng; mức tương tự không phải xác suất."}
        except ValueError as exc:
            return {"ready": False, "model": MODEL_ID, "message": str(exc)}

    def search(self, text, mode="text"):
        start = time.perf_counter()
        # General scam guidance cannot establish reputation for a bare URL.
        if mode == "url":
            return {"status": "empty", "sources": [], "reason": "Đầu vào chỉ có URL; kho này không xác minh danh tiếng tên miền."}
        with self.lock:
            try:
                # Recheck fingerprints on every request, so edited corpus/index never silently uses an old cache.
                index, config = self.inspect()
                if self.encoder is None:
                    self.encoder = E5Encoder(self.path(self.settings.rag_model_dir))
                self.index, self.calibration = index, config
                windows = self.encoder.split(text, budget=300, overlap=40)
                if not windows:
                    return {"status": "empty", "sources": [], "reason": "Không có nội dung để truy xuất."}
                query_vectors = self.encoder.encode(windows, "query: ")
                sources = rank_chunks(index.chunks, index.vectors, query_vectors, config["top_k"], config["min_score"])
                return {"status": "ok" if sources else "empty", "sources": sources,
                        "model": MODEL_ID, "revision": MODEL_REVISION,
                        "index_manifest_sha256": sha_file(self.path(self.settings.rag_index_dir) / "manifest.json"),
                        "min_score": config["min_score"], "top_k": config["top_k"],
                        "reason": "Tóm lược nguồn tham khảo; không xác nhận danh tiếng URL." if sources else "Chưa tìm được tài liệu đạt ngưỡng phù hợp.",
                        "elapsed_ms": round((time.perf_counter() - start) * 1000, 1)}
            except (ImportError, OSError, ValueError, KeyError, TypeError, RuntimeError):
                return {"status": "unavailable", "sources": [],
                        "reason": "Không truy xuất được kho cục bộ. Kết quả LLM sẽ không có nguồn RAG; xem hướng dẫn thiết lập."}
