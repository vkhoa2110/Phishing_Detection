"""Fetch a pinned, CC BY source and prepare a fresh 200-message review batch."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from evaluation.message_data import REPOSITORY, REVISION, prepare


def download(directory):
    directory.mkdir(parents=True, exist_ok=True)
    names = ("README.md", "QUICKSTART_GUIDE.md", "full_dataset.csv", "train.csv", "test.csv")
    manifest_path = directory / "download.json"
    if manifest_path.exists():
        return  # prepare() verifies each recorded file; never overwrite a snapshot.
    if any(directory.iterdir()):
        raise ValueError("Partial raw snapshot without provenance; choose a fresh --raw directory.")
    files = {}
    with httpx.Client(timeout=45, follow_redirects=True, trust_env=False) as client:
        for name in names:
            url = f"https://huggingface.co/datasets/{REPOSITORY}/resolve/{REVISION}/{name}"
            with client.stream("GET", url) as response:
                response.raise_for_status()
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > 10_000_000:
                        raise ValueError("Source exceeds download limit.")
                    chunks.append(chunk)
            data = b"".join(chunks)
            (directory / name).write_bytes(data)
            files[name] = {"url": url, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    manifest_path.write_text(json.dumps({"repo": REPOSITORY, "revision": REVISION,
        "retrieved_at": datetime.now(timezone.utc).isoformat(), "files": files}, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=ROOT / "data/raw/vietnamese_sms_a90e2bd7")
    parser.add_argument("--out", type=Path, default=ROOT / "data/annotation/vn_sms_v2")
    args = parser.parse_args()
    try:
        download(args.raw)
        print(json.dumps(prepare(args.raw, args.out), ensure_ascii=False, indent=2))
    except (ValueError, OSError, httpx.HTTPError) as exc:
        parser.exit(2, f"Preparation stopped: {exc}\n")
