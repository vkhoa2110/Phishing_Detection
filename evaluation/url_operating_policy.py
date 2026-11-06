"""Compare unchanged URL scores under legacy alarms and abstention bands."""
import argparse
import csv
from datetime import datetime, timezone
import io
import json
from pathlib import Path

from app.settings import ROOT
from app.url_policy import operating_prediction
from .message_data import read_jsonl, sha, write_json
from .metrics import measure
from scripts.evaluation.report_url_context import check_metrics


def compare(rows, thresholds):
    cases, levels, lookup = [], {"legacy": [], "conservative": []}, {}
    transitions = {"negative_alarm_to_unknown": 0, "positive_alarm_to_unknown": 0, "alarm_to_low": 0}
    for i, row in enumerate(rows):
        score = float(row["score"])
        low, high = thresholds["warning_threshold"], thresholds["high_threshold"]
        old = "HIGH" if high is not None and score >= high else "WARNING" if score >= low else "LOW"
        raw = {"id": str(i), "url": row["url"], "score": score, "risk_level": old, "status": "ok",
               "warning_threshold": low, "high_threshold": high}
        new = operating_prediction(raw)
        if new["status"] != "ok":
            raise ValueError("Invalid input URL score/cutoffs.")
        label = int(row["label"])
        c = {"id": str(i), "targets": {"url_risk": label}}
        cases.append(c)
        for name, level in (("legacy", old), ("conservative", new["risk_level"])):
            levels[name].append(level)
            lookup[(c["id"], name, 0)] = {"status": "ok", "outputs": {"url_risk": level}}
        if old in {"HIGH", "WARNING"} and new["risk_level"] == "UNKNOWN":
            transitions["positive_alarm_to_unknown" if label else "negative_alarm_to_unknown"] += 1
        if old in {"HIGH", "WARNING"} and new["risk_level"] == "LOW":
            transitions["alarm_to_low"] += 1
    metrics = {name: measure([c["targets"]["url_risk"] for c in cases], values) for name, values in levels.items()}
    for name, m in metrics.items():
        check_metrics(cases, lookup, name, 0, "url_risk", {**m, "reference_unknown_count": 0,
                      "reference_unknown_predictions": {}, "technical_errors": 0})
    if transitions["alarm_to_low"]:
        raise ValueError("Unsafe alarm-to-LOW transition.")
    return {"metrics": metrics, "transitions": transitions,
            "domains": len({r["domain_group"] for r in rows})}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out
    if out.exists():
        parser.error("Choose a new output directory.")
    source = ROOT / "artifacts/evaluations/phishvn_official_v1/val_predictions.csv"
    dev_run = ROOT / "artifacts/evaluations/url_context_dev_live_v1"
    config = ROOT / "models/inference_XGBoost_d6_s42/config.json"
    thresholds = json.loads(config.read_text())["thresholds"]
    prepared = json.loads((dev_run / "prepared_urls.json").read_text())
    if sha(dev_run / "prepared_urls.json") != (dev_run / "prepared_urls.sha256").read_text().strip():
        parser.error("Prepared dev scores changed.")
    validation = [{**r, "label": int(r["labels"]), "score": float(r["score"])}
                  for r in csv.DictReader(io.StringIO(source.read_text(encoding="utf-8-sig")))]
    dev = [{**r, "label": r["url_label"], "score": prepared[r["id"]]["score"]}
           for r in read_jsonl(ROOT / "data/annotation/url_context_v1/urls.jsonl") if r["split"] == "dev"]
    if len(dev) != 40 or len(validation) != len({r["id"] for r in validation}):
        parser.error("Unexpected/duplicate input rows.")
    out.mkdir(parents=True)
    write_json(out / "execution.json", {"created_at": datetime.now(timezone.utc).isoformat(),
        "method": "Keep the original low/high cutoffs; intermediate WARNING becomes UNKNOWN, never LOW. No fitting or numeric threshold selection.",
        "thresholds": thresholds, "source_hashes": {str(p): sha(p) for p in
            (source, config, dev_run / "prepared_urls.json", Path(__file__), ROOT / "app/url_policy.py")},
        "API_calls": 0, "test_inference": False, "independent_test": False})
    groups = {"dev_40_unique_urls": dev, "full_reused_validation": validation,
              "validation_gold_silver": [r for r in validation if r["tier"] in {"gold", "silver"}]}
    result = {name: compare(rows, thresholds) for name, rows in groups.items()}
    write_json(out / "summary.json", result)
    pct = lambda value: "N/A" if value is None else f"{100*value:.2f}%"
    lines = ["# URL operating policy: abstention, not a new model", "",
        "Same raw scores and original cutoffs. WARNING becomes UNKNOWN; HIGH and LOW stay unchanged. "
        "References are historical. Validation/dev were previously viewed; this is not independent improvement evidence.", "",
        "| Group | Policy | n | F1 | Recall | FPR | Accuracy | Coverage | UNKNOWN +/− |", "|---|---|---:|---:|---:|---:|---:|---:|---|"]
    for name, entry in result.items():
        for policy, m in entry["metrics"].items():
            lines.append(f"| {name} | {policy} | {m['n']} | {pct(m['f1'])} | {pct(m['recall'])} | {pct(m['false_positive_rate'])} | "
                         f"{pct(m['accuracy'])} | {pct(m['coverage'])} | {m['unknown_positive']}/{m['unknown_negative']} |")
        lines += ["", f"{name}: transitions={entry['transitions']}", ""]
    lines += ["The policy reduces alarm frequency by abstaining. UNKNOWN-positive still lowers full-set Recall/F1. "
              "No new LOW conclusions are created. These results do not establish that the URL model learned better features."]
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(out / "report.md"), "API_calls": 0}))


if __name__ == "__main__":
    main()
