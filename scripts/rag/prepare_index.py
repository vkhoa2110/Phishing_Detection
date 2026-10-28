"""Download the pinned E5 safetensors export explicitly, then build a local index."""
import argparse
import importlib.metadata
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from app.rag_service import MODEL_ID, MODEL_REVISION, E5Encoder, build_index, sha_file, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", help="Explicitly permit downloading public model weights from Hugging Face.")
    parser.add_argument("--model-dir", type=Path, default=ROOT / "models/embeddings/multilingual-e5-small")
    parser.add_argument("--corpus", type=Path, default=ROOT / "data/knowledge/corpus_v1/documents.jsonl")
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts/rag/e5-small-v1")
    args = parser.parse_args()
    if args.download:
        from huggingface_hub import snapshot_download
        names = ["config.json", "model.safetensors", "tokenizer.json", "tokenizer_config.json",
                 "special_tokens_map.json", "sentencepiece.bpe.model"]
        snapshot_download(MODEL_ID, revision=MODEL_REVISION, local_dir=args.model_dir, allow_patterns=names, max_workers=2)
        write_json(args.model_dir / "phishlens_model.json", {"model_id": MODEL_ID, "revision": MODEL_REVISION,
                   "files": {n: sha_file(args.model_dir / n) for n in names},
                   "packages": {n: importlib.metadata.version(n) for n in ("torch", "transformers", "huggingface-hub")}})
    manifest = build_index(args.corpus, args.out, E5Encoder(args.model_dir))
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    print("Next: calibrate using python -m evaluation.retrieval; no threshold is guessed during building.")


if __name__ == "__main__":
    main()
