"""Copy a character model into the current layout after exact score verification.

Requires a pre-refactor snapshot: baseline.json, char_export_before.json,
validation_urls.json and char_validation_scores.npy. Never fits a model, reads
test data, overwrites a package, or edits historical experiment manifests.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import numpy as np

from app.services.url.character import (
    CharURLService, DEFAULT_DEPLOYMENT, DEFAULT_PREPROCESSING, _json, _sha,
)


def repackage(source, baseline_dir, out=DEFAULT_DEPLOYMENT, *, preprocessing=DEFAULT_PREPROCESSING):
    source, baseline_dir, out = (Path(p).resolve() for p in (source, baseline_dir, out))
    if out.exists():
        raise ValueError("Destination exists; use a fresh model directory.")
    original_bytes = (source / "export.json").read_bytes()
    if original_bytes != (baseline_dir / "char_export_before.json").read_bytes():
        raise ValueError("Original manifest differs from the pre-refactor snapshot.")
    original = json.loads(original_bytes)
    baseline = json.loads((baseline_dir / "baseline.json").read_text())
    urls = json.loads((baseline_dir / "validation_urls.json").read_text())
    expected = np.load(baseline_dir / "char_validation_scores.npy", allow_pickle=False)
    if (not urls or len(urls) != baseline["character_validation_rows"]
            or expected.shape != (len(urls),) or not np.isfinite(expected).all()):
        raise ValueError("Incomplete validation snapshot.")
    if set(original["files"]) != {"vocabulary.json", "weights.npz"}:
        raise ValueError("Unexpected model files.")
    for name, digest in original["files"].items():
        if _sha(source / name) != digest:
            raise ValueError("Original model hash mismatch: " + name)
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".repackage-", dir=out.parent))
    try:
        for name in original["files"]:
            shutil.copyfile(source / name, temporary / name)
        manifest = deepcopy(original)
        manifest["source_runner_sha256"] = _sha(ROOT / "evaluation/url/character_baseline.py")
        manifest["serving_source_sha256"] = _sha(ROOT / "app/services/url/character.py")
        manifest["packaging_migration"] = {
            "from_git_commit": baseline["git_commit"],
            "original_manifest_sha256": _sha(source / "export.json"),
            "original_source_runner_sha256": original["source_runner_sha256"],
            "original_serving_source_sha256": original["serving_source_sha256"],
            "historical_equivalence": "inherited from original export; not a new test run",
            "validation_rows": len(urls), "validation_scores_bitwise_match": True,
            "snapshot_sha256": {name: _sha(baseline_dir / name) for name in (
                "baseline.json", "char_export_before.json", "validation_urls.json", "char_validation_scores.npy")},
            "repackage_source_sha256": _sha(Path(__file__)),
            "weights_copied_unchanged": True, "fits": 0, "API_calls": 0,
        }
        _json(temporary / "export.json", manifest)
        runtime = CharURLService(temporary, preprocessing)
        if not runtime.load()["ready"]:
            raise ValueError(runtime.error)
        if not np.array_equal(runtime._scores(urls), expected):
            raise ValueError("Scores changed; package refused.")
        for name, digest in original["files"].items():
            if _sha(temporary / name) != digest:
                raise ValueError("Copied model bytes changed: " + name)
        temporary.rename(out)
        return manifest["packaging_migration"]
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--baseline-dir", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=DEFAULT_DEPLOYMENT)
    args = parser.parse_args()
    result = repackage(args.source, args.baseline_dir, args.out)
    print(json.dumps({"out": str(args.out), **result}, ensure_ascii=False))


if __name__ == "__main__":
    main()
