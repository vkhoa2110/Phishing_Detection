"""Verify a completed four-arm run independently with scikit-learn."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np
from sklearn.metrics import accuracy_score, confusion_matrix, precision_recall_fscore_support

ROOT = Path(__file__).resolve().parents[2]
ARMS = ("llm_only", "llm_url", "llm_rag", "llm_url_rag")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_lines(path):
    return [json.loads(s) for s in path.read_text(encoding="utf-8").splitlines() if s.strip()]


def predict(level):
    assert level in {"HIGH", "WARNING", "LOW", "UNKNOWN"}
    return 1 if level in {"HIGH", "WARNING"} else 0 if level == "LOW" else -1


def verify_metrics(rows, saved):
    for system, expected in saved.items():
        assert expected["n"] == len(rows)
        if not rows:
            continue
        y = np.array([r["label"] for r in rows])
        levels = [r["levels"][system] for r in rows]
        p = np.array([predict(l) for l in levels])
        matrix = confusion_matrix(y, p, labels=[1, 0, -1])
        tp, fn, up = map(int, matrix[0])
        fp, tn, un = map(int, matrix[1])
        values = dict(tp=tp, fp=fp, tn=tn, fn=fn, unknown_positive=up, unknown_negative=un)
        pr, re, f1, _ = precision_recall_fscore_support(y, p, labels=[1], zero_division=np.nan)
        covered = int(sum(p != -1))
        values.update(precision=pr[0], recall=re[0], f1=f1[0], accuracy=accuracy_score(y, p),
                      coverage=covered / len(rows), false_positive_rate=fp / sum(y == 0) if sum(y == 0) else np.nan,
                      selective_accuracy=sum(y == p) / covered if covered else np.nan)
        for key, value in values.items():
            assert ((expected[key] is None and math.isnan(value)) or
                    (expected[key] is not None and abs(expected[key] - value) < 1e-12)), (system, key, expected[key], value)
        assert expected["risk_counts"] == dict(Counter(levels))


def verify(out):
    config = read_json(out / "manifest.json")["configuration"]
    summary = read_json(out / "summary.json")
    rows = read_lines(out / "results.jsonl")
    checkpoints = read_lines(out / "checkpoints.jsonl")
    assert config["arms"] == list(ARMS)
    assert summary["run_state"]["stop_reason"] == "all_calls_completed"
    assert len(rows) == summary["n"] == config["dataset_cases"]
    dataset = Path(config["dataset_path"]) if config.get("dataset_path") else ROOT / "data/evaluation" / config["dataset_name"]
    assert sha(dataset) == config["dataset_sha256"]
    originals = {c["id"]: c for c in read_lines(dataset)}
    assert len(originals) == len(rows)
    assert sha(out / "prepared_cases.json") == (out / "prepared_cases.sha256").read_text().strip()
    prepared = read_json(out / "prepared_cases.json")
    expected_keys = {(r["id"], a) for r in rows for a in ARMS}
    assert len(checkpoints) == len(expected_keys)
    assert {(c["case_id"], c["arm"]) for c in checkpoints} == expected_keys
    cache = {(c["case_id"], c["arm"]): c["result"] for c in checkpoints}
    for path, fingerprint in config["source_sha256"].items():
        assert sha(ROOT / path) == fingerprint, path
    valid_citations = 0
    for r in rows:
        assert all(r[k] == v for k, v in originals[r["id"]].items())
        assert all(r[k] == v for k, v in prepared[r["id"]].items())
        assert r["has_url"] == bool(r["urls"])
        ml = [u["risk_level"] for u in r["urls"] if u["status"] == "ok"]
        ml_level = "HIGH" if "HIGH" in ml else "WARNING" if "WARNING" in ml else "LOW" if ml else "UNKNOWN"
        assert r["levels"]["url_model_only"] == ml_level
        sources = {s["document_id"]: s for s in r["retrieval"]["sources"]}
        for arm in ARMS:
            result = r[arm]
            assert result == cache[(r["id"], arm)]
            assert result["status"] in {"ok", "error"}
            expected = result.get("verdict", {}).get("risk_level", "UNKNOWN") if result["status"] == "ok" else "UNKNOWN"
            assert r["levels"][arm] == expected
            severity = {"HIGH": 2, "WARNING": 1, "LOW": 0, "UNKNOWN": -1}
            alarm = max([ml_level, expected], key=severity.get)
            fused = alarm if severity[alarm] >= 1 else "UNKNOWN" if r["invalid_urls"] else "LOW" if expected == "LOW" else "UNKNOWN"
            if config.get("fusion_policy") == "separate":
                fused = expected
            assert r["levels"]["fusion_" + arm] == fused
            if result["status"] != "ok":
                continue
            assert result["rag"] == bool(sources and arm in {"llm_rag", "llm_url_rag"})
            assert result["included_ml"] == bool(r["urls"] and arm in {"llm_url", "llm_url_rag"})
            assert all(e["quote"] in result["input_used"] for e in result["verdict"]["evidence"])
            for support in result["verdict"].get("knowledge_support", []):
                assert result["rag"]
                assert support["document_id"] in sources
                assert support["source_quote"] in sources[support["document_id"]]["text"]
                valid_citations += 1
    verify_metrics(rows, summary["metrics"])
    for group, flag in (("with_url", True), ("without_url", False)):
        verify_metrics([r for r in rows if r["has_url"] == flag], summary["by_url"][group])
    for category, values in summary["by_category"].items():
        verify_metrics([r for r in rows if r["category"] == category], values)
    for group, flag in (("injection", True), ("other", False)):
        verify_metrics([r for r in rows if bool(r.get("prompt_injection")) == flag], summary["by_injection"][group])
    result = {"verified": True, "cases": len(rows), "checkpoints": len(checkpoints),
              "systems": len(summary["metrics"]), "valid_exact_source_quotes": valid_citations,
              "independent_metric_library": "scikit-learn", "semantic_citation_quality": "not_verified"}
    (out / "verification.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.out), ensure_ascii=False))
    except (AssertionError, ValueError, KeyError, OSError) as exc:
        sys.exit(f"Verification failed: {exc}")
