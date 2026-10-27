"""Independently check recorded metrics with scikit-learn, without API calls."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
from sklearn.metrics import accuracy_score, confusion_matrix, precision_recall_fscore_support


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    summary = json.loads((args.run / "summary.json").read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in (args.run / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == summary["n"]
    targets = [r["label"] for r in rows]
    checked = {}
    for system, metrics in summary["metrics"].items():
        predictions = [1 if r["levels"][system] in ("HIGH", "WARNING") else 0 if r["levels"][system] == "LOW" else -1 for r in rows]
        precision, recall, f1, _ = precision_recall_fscore_support(targets, predictions, labels=[1], zero_division=0)
        matrix = confusion_matrix(targets, predictions, labels=[0, 1, -1])
        values = {"accuracy": float(accuracy_score(targets, predictions)),
                  "precision": float(precision[0]) if 1 in predictions else None,
                  "recall": float(recall[0]), "f1": float(f1[0]),
                  "false_positive_rate": float(matrix[0, 1] / matrix[0].sum()),
                  "coverage": sum(p != -1 for p in predictions) / len(predictions)}
        for key, value in values.items():
            assert (value is None and metrics[key] is None) or np.isclose(value, metrics[key]), (system, key, value, metrics[key])
        assert (int(matrix[1, 1]), int(matrix[0, 1]), int(matrix[0, 0]), int(matrix[1, 0]), int(matrix[1, 2]), int(matrix[0, 2])) == tuple(metrics[key] for key in ("tp", "fp", "tn", "fn", "unknown_positive", "unknown_negative"))
        checked[system] = values
    cache = [json.loads(line) for line in (args.run / "checkpoints.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len({(c["case_id"], c["arm"]) for c in cache}) == 2 * len(rows)
    by_id = {r["id"]: r for r in rows}
    assert all(c["result"] == by_id[c["case_id"]][c["arm"]] for c in cache)
    result = {"verified_at": datetime.now(timezone.utc).isoformat(), "implementation": "scikit-learn",
              "summary_sha256": hashlib.sha256((args.run / "summary.json").read_bytes()).hexdigest(),
              "results_sha256": hashlib.sha256((args.run / "results.jsonl").read_bytes()).hexdigest(),
              "unique_completed_attempts": len(cache), "verified_metrics": checked}
    (args.run / "independent_metric_check.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Verified {len(checked)} configurations against scikit-learn and {len(cache)} unique checkpoints.")


if __name__ == "__main__":
    main()
