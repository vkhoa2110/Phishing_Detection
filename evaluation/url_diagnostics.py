"""Offline URL diagnostics from frozen predictions; no model/API calls or tuning.

Usage: python -m evaluation.url_diagnostics --run-dir artifacts/evaluations/phishvn_official_v1 \
    --out artifacts/evaluations/url_diagnostics_v1
"""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path


PREVALENCES = (.01, .05, .10, .50)
Z95 = 1.959963984540054


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def wilson95(successes, total):
    """Two-sided Wilson interval for a binomial rate, undefined at n=0."""
    if type(successes) is not int or type(total) is not int or not 0 <= successes <= total:
        raise ValueError("Wilson counts must be integers with 0 <= successes <= total.")
    if not total:
        return None
    p = successes / total
    z2 = Z95 * Z95
    denominator = 1 + z2 / total
    center = (p + z2 / (2 * total)) / denominator
    half = Z95 * math.sqrt(p * (1 - p) / total + z2 / (4 * total * total)) / denominator
    return {"lower": max(0.0, center - half), "upper": min(1.0, center + half), "n": total}


def projected_precision(recall, false_positive_rate, prevalence):
    """Scenario projection assuming conditional rates transfer unchanged."""
    if not math.isfinite(prevalence) or not 0 < prevalence < 1:
        raise ValueError("Scenario prevalence must be strictly between 0 and 1.")
    if recall is None or false_positive_rate is None:
        return None
    positive_mass = recall * prevalence
    return ratio(positive_mass, positive_mass + false_positive_rate * (1 - prevalence))


def measures(rows, threshold):
    tp = fp = tn = fn = 0
    for row in rows:
        positive = row["score"] >= threshold
        if row["label"] == 1:
            tp += positive
            fn += not positive
        else:
            fp += positive
            tn += not positive
    recall, fpr = ratio(tp, tp + fn), ratio(fp, fp + tn)
    return {"n": len(rows), "positives": tp + fn, "negatives": fp + tn,
            "domain_groups": len({r["domain_group"] for r in rows}),
            "tp": tp, "fp": fp, "tn": tn, "fn": fn,
            "precision": ratio(tp, tp + fp), "recall": recall, "false_positive_rate": fpr,
            "f1": ratio(2 * tp, 2 * tp + fp + fn), "accuracy": ratio(tp + tn, len(rows)),
            "recall_wilson95": wilson95(tp, tp + fn),
            "false_positive_rate_wilson95": wilson95(fp, fp + tn),
            "precision_at_assumed_prevalence": {
                str(p): projected_precision(recall, fpr, p) for p in PREVALENCES}}


def load_inputs(run_dir):
    """Read once, hash those bytes, and reject malformed/contradictory snapshots."""
    run_dir = Path(run_dir).resolve()
    names = ["test_predictions.csv", "url_model_metrics.json"]
    if (run_dir / "manifest.json").exists():
        names.append("manifest.json")
    raw = {name: (run_dir / name).read_bytes() for name in names}
    inputs = {name: {"path": str(run_dir / name), "sha256": hashlib.sha256(data).hexdigest()}
              for name, data in raw.items()}
    reader = csv.DictReader(io.StringIO(raw["test_predictions.csv"].decode("utf-8-sig")))
    required = {"id", "labels", "score", "source", "tier", "domain_group"}
    if not required <= set(reader.fieldnames or []):
        raise ValueError("Prediction CSV is missing required columns.")
    rows, seen = [], set()
    for row in reader:
        if (not row["id"] or row["id"] in seen or row["labels"] not in {"0", "1"}
                or any(not (row[k] or "").strip() for k in ("source", "tier", "domain_group"))):
            raise ValueError("Prediction CSV has invalid/duplicate IDs, labels or grouping fields.")
        score = float(row["score"])
        if not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError("Prediction scores must be finite and within [0, 1].")
        seen.add(row["id"])
        rows.append({"id": row["id"], "label": int(row["labels"]), "score": score,
                     **{k: row[k] for k in ("source", "tier", "domain_group")}})
    if not rows:
        raise ValueError("Prediction CSV is empty.")
    stored = json.loads(raw["url_model_metrics.json"])["test"]
    thresholds = {}
    for name in ("warning", "high", "fixed_0.5"):
        if name not in stored:
            continue
        threshold = stored[name]["threshold"]
        if (isinstance(threshold, bool) or not isinstance(threshold, (float, int))
                or not math.isfinite(threshold) or not 0 <= threshold <= 1):
            raise ValueError("Stored threshold is invalid.")
        thresholds[name] = float(threshold)
        recomputed = measures(rows, threshold)
        for key in ("n", "tp", "fp", "tn", "fn"):
            if recomputed[key] != stored[name][key]:
                raise ValueError(f"Stored metrics disagree with predictions: {name}/{key}.")
    if "warning" not in thresholds:
        raise ValueError("Missing frozen warning threshold.")
    return rows, thresholds, inputs


def pct(value):
    return "N/A" if value is None else f"{100 * value:.2f}%"


def interval(value):
    return "N/A" if value is None else f"[{pct(value['lower'])}; {pct(value['upper'])}]"


def markdown(summary):
    lines = ["# Chẩn đoán mô hình URL từ kết quả đã lưu", "",
             f"Tạo lúc (UTC): {summary['created_at']}", "",
             "Tính lại từ CSV dự đoán PhishVN; không huấn luyện, không gọi LLM, không chọn lại ngưỡng. "
             "Kết quả này phân tích cùng tập test đã xem, không phải đánh giá trên dữ liệu độc lập mới.", "",
             "Khoảng Wilson 95% cho Recall/FPR giả định các URL độc lập. URL trong cùng tên miền "
             "có thể phụ thuộc nhau; chưa bootstrap theo domain, nên khoảng này có thể quá hẹp. "
             "Khoảng thống kê không phản ánh sai nhãn, lệch nguồn hoặc thay đổi theo thời gian.", "",
             "Mẫu số bằng 0 được ghi N/A (JSON: null). Mỗi hàng nguồn/tier phải đọc cùng số mẫu "
             "dương và âm; nhiều nguồn chỉ chứa một lớp."]
    for name, group in summary["thresholds"].items():
        lines += ["", f"## Ngưỡng {name}: {group['threshold']:.12g}", "",
                  "| Nhóm | n (+ / −) | Số miền | TP / FP / TN / FN | Precision | Recall [Wilson 95%] | FPR [Wilson 95%] |",
                  "|---|---:|---:|---|---:|---|---|"]
        groups = ([("Toàn bộ", group["all"]), ("Gold + silver", group["gold_silver"])] +
                  [("Nguồn: " + k, v) for k, v in group["by_source"].items()] +
                  [("Tier: " + k, v) for k, v in group["by_tier"].items()])
        for label, m in groups:
            label = label.replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {label} | {m['n']} ({m['positives']} / {m['negatives']}) | {m['domain_groups']} | "
                         f"{m['tp']} / {m['fp']} / {m['tn']} / {m['fn']} | {pct(m['precision'])} | "
                         f"{pct(m['recall'])} {interval(m['recall_wilson95'])} | "
                         f"{pct(m['false_positive_rate'])} {interval(m['false_positive_rate_wilson95'])} |")
    lines += ["", "## Precision theo tỷ lệ phishing giả định", "",
              "Đây là các kịch bản tính toán, không phải tỷ lệ phishing thực tế của người dùng. "
              "Giả định Recall và FPR đo trên toàn bộ test giữ nguyên khi tỷ lệ lớp thay đổi; "
              "giả định này có thể không đúng khi nguồn URL thay đổi.", "",
              "`Precision(p) = Recall × p / (Recall × p + FPR × (1 − p))`", "",
              "| Ngưỡng | p = 1% | p = 5% | p = 10% | p = 50% |", "|---|---:|---:|---:|---:|"]
    for name, group in summary["thresholds"].items():
        projection = group["all"]["precision_at_assumed_prevalence"]
        lines.append("| " + name + " | " + " | ".join(pct(projection[str(p)]) for p in PREVALENCES) + " |")
    lines += ["", "## Quyết định và giới hạn", "",
              "- Ngưỡng triển khai giữ nguyên. Không dùng báo cáo test này để chọn ngưỡng mới rồi gọi là cải thiện độc lập.",
              "- Cần thiết kế mục tiêu Recall/FPR trên validation, kiểm tra nguồn/tier, rồi chốt trước một test mới.",
              "- Điểm mô hình chưa là xác suất đã hiệu chỉnh; Precision phụ thuộc tỷ lệ lớp và nguồn URL.",
              "- Số đo URL không thay cho hiệu quả phân loại nội dung tin nhắn hay chất lượng lời giải thích RAG.",
              "", "## Dấu vết đầu vào", ""]
    for name, meta in summary["inputs"].items():
        lines.append(f"- `{name}`: SHA-256 `{meta['sha256']}`.")
    lines.append(f"- Mã diagnostic: SHA-256 `{summary['code_sha256']}`.")
    return "\n".join(lines) + "\n"


def diagnose(run_dir, out):
    out = Path(out)
    if out.exists():
        raise ValueError("Output already exists; choose a new directory to preserve snapshots.")
    rows, thresholds, inputs = load_inputs(run_dir)
    summary = {"schema_version": "url-diagnostics-1.0", "created_at": datetime.now(timezone.utc).isoformat(),
               "inputs": inputs, "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "threshold_selection": "unchanged, read from the existing test metrics; no selection in this run",
               "interval_method": "two-sided Wilson 95%; assumes independent URLs; no domain bootstrap",
               "assumed_prevalences": list(PREVALENCES), "thresholds": {}}
    for name, threshold in thresholds.items():
        summary["thresholds"][name] = {
            "threshold": threshold, "all": measures(rows, threshold),
            "gold_silver": measures([r for r in rows if r["tier"] in {"gold", "silver"}], threshold),
            **{"by_" + key: {group: measures([r for r in rows if r[key] == group], threshold)
                            for group in sorted({r[key] for r in rows})} for key in ("source", "tier")}}
    report = markdown(summary)
    # All input validation and rendering precede the only output creation.
    out.mkdir(parents=True, exist_ok=False)
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (out / "report.md").write_text(report, encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        summary = diagnose(args.run_dir, args.out)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(2, f"Diagnostics stopped: {exc}\n")
    print(json.dumps({"report": str(args.out / "report.md"), "thresholds": {
        name: {"threshold": item["threshold"], **item["all"]}
        for name, item in summary["thresholds"].items()}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
