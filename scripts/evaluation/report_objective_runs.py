"""Report completed objective-dev runs, preserving AI-label and dataset limits."""
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.evaluation.verify_rag_ablation import verify
from evaluation.common.metrics import measure

ARMS = ("llm_only", "llm_url", "llm_rag", "llm_url_rag")
NAMES = {"llm_only": "LLM", "llm_url": "LLM + URL", "llm_rag": "LLM + RAG", "llm_url_rag": "LLM + URL + RAG"}


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pct(value):
    return "N/A" if value is None else f"{100 * value:.2f}%"


def paired_f1_intervals(rows, repetitions=2000, seed=20261102):
    """Exploratory paired cluster bootstrap; annotation errors are not sampled."""
    groups = sorted({r["group_id"] for r in rows})
    counts = np.zeros((len(groups), len(ARMS), 3), dtype=float)
    by_group = {g: i for i, g in enumerate(groups)}
    for r in rows:
        for a, arm in enumerate(ARMS):
            level = r["levels"][arm]
            pred = 1 if level in {"HIGH", "WARNING"} else 0 if level == "LOW" else -1
            # Positive UNKNOWN/error remains a missed detection in F1.
            category = 0 if r["label"] == 1 and pred == 1 else 1 if r["label"] == 0 and pred == 1 else 2 if r["label"] == 1 else None
            if category is not None:
                counts[by_group[r["group_id"]], a, category] += 1
    rng = np.random.default_rng(seed)
    sampled = counts[rng.integers(0, len(groups), size=(repetitions, len(groups)))].sum(axis=1)
    denominator = 2 * sampled[:, :, 0] + sampled[:, :, 1] + sampled[:, :, 2]
    f1 = np.divide(2 * sampled[:, :, 0], denominator, out=np.full_like(denominator, np.nan), where=denominator != 0)
    result = {}
    for name, baseline, treatment in (("rag_without_url", 0, 2), ("rag_with_url", 1, 3),
                                      ("url_without_rag", 0, 1), ("url_with_rag", 2, 3)):
        delta = 100 * (f1[:, treatment] - f1[:, baseline])
        valid = delta[np.isfinite(delta)]
        result[name] = {"baseline": ARMS[baseline], "treatment": ARMS[treatment], "groups": len(groups),
            "repetitions": repetitions, "valid_repetitions": len(valid), "seed": seed,
            "ci95_delta_f1_percentage_points": list(map(float, np.quantile(valid, [.025, .975]))) if len(valid) else None}
    return result


def summarize(path):
    verification = verify(path)
    summary = read(path / "summary.json")
    config = read(path / "manifest.json")["configuration"]
    rows = [json.loads(s) for s in (path / "results.jsonl").read_text(encoding="utf-8").splitlines() if s.strip()]
    if config.get("evaluation_protocol", {}).get("split") != "dev" or not config.get("diagnostic"):
        raise ValueError("This reporter is for registered provisional dev diagnostics only.")
    n, p = len(rows), sum(r["label"] for r in rows)
    baselines = {
        "always_alarm": {"precision": p / n, "recall": 1 if p else None,
                         "f1": 2 * p / (n + p) if n + p else None, "false_positive_rate": 1 if n > p else None,
                         "accuracy": p / n, "coverage": 1},
        "always_low": {"precision": None, "recall": 0 if p else None, "f1": 0 if p else None,
                       "false_positive_rate": 0 if n > p else None, "accuracy": (n - p) / n, "coverage": 1},
    }
    failures, guardrails = [], {}
    for arm in ARMS:
        for r in rows:
            out = r[arm]
            if out["status"] == "error":
                failures.append({"id": r["id"], "arm": arm, "code": out.get("code"), "elapsed_ms": out.get("elapsed_ms")})
        guardrails[arm] = dict(Counter(code for r in rows for code in r[arm].get("validation", {}).get("reason_codes", [])))
    wrong = []
    for r in rows:
        mistaken = {a: r["levels"][a] for a in ARMS if (1 if r["levels"][a] in {"HIGH", "WARNING"} else 0 if r["levels"][a] == "LOW" else None) != r["label"]}
        if mistaken:
            wrong.append({"id": r["id"], "reference_label": r["label"], "text": r["text"],
                          "reference_rationale": r["rationale"], "category": r["category"],
                          "variant": r.get("variant"), "group_id": r["group_id"], "outcomes": mistaken})
    return {"path": str(path), "verification": verification, "n": n, "positive": p, "negative": n-p,
            "with_url": sum(r["has_url"] for r in rows), "groups": len({r["group_id"] for r in rows}),
            "metrics": {a: summary["metrics"][a] for a in ARMS}, "baselines": baselines,
            "status_counts": summary["status_counts"], "error_codes": summary["error_codes"],
            "usage": summary["usage"], "timing": summary["timing"], "citations": summary["citations"],
            "retrieval": summary["retrieval"], "by_url": summary["by_url"], "by_injection": summary["by_injection"],
            "by_available_rag_context": {name:{"n":len(subset), "metrics":{a:measure([r["label"] for r in subset], [r["levels"][a] for r in subset]) for a in ARMS}}
                for name,subset in (("with_sources",[r for r in rows if r["retrieval"]["sources"]]),
                                    ("without_sources",[r for r in rows if not r["retrieval"]["sources"]]))},
            "paired_f1_cluster_bootstrap": paired_f1_intervals(rows), "validation_reason_codes": guardrails,
            "failures": failures, "cases_to_review": wrong,
            "inputs_sha256": {name: sha(path / name) for name in ("manifest.json", "checkpoints.jsonl", "results.jsonl", "summary.json")}}


def markdown(data):
    lines = ["# Kết quả chạy dev — nhãn AI sơ bộ", "", f"Ngày tổng hợp (UTC): {data['created_at']}", "",
             "**Diagnostic trên nhãn AI, chưa phải đánh giá độc lập bằng human gold.** "
             "Hai nguồn dữ liệu được báo riêng. Test được giữ lại; các ca reference UNKNOWN không nằm trong F1 nhị phân dưới đây. "
             "Không loại lỗi API/JSON hoặc mẫu LLM trả UNKNOWN khỏi mẫu số Recall/F1.", ""]
    for name, title in (("sms", "SMS bên ngoài"), ("challenge", "Ca mô phỏng đối chiếu")):
        s = data[name]
        lines += [f"## {title}", "", f"{s['n']} mẫu nhị phân: {s['positive']} nhãn dương, {s['negative']} nhãn âm; "
                  f"{s['with_url']} có URL; {s['groups']} nhóm. Nhãn tham chiếu có thể sai. "
                  "Nhãn mô phỏng theo thiết kế của trợ lý có tính vòng tròn.", "",
                  "| Cấu hình | Precision | Recall | F1 | Accuracy | FPR | Coverage | TP/FP/TN/FN | UNKNOWN +/− | Lỗi |",
                  "|---|---:|---:|---:|---:|---:|---:|---|---|---:|"]
        for arm in ARMS:
            m = s["metrics"][arm]
            lines.append(f"| {NAMES[arm]} | {pct(m['precision'])} | {pct(m['recall'])} | {pct(m['f1'])} | "
                         f"{pct(m['accuracy'])} | {pct(m['false_positive_rate'])} | {pct(m['coverage'])} | "
                         f"{m['tp']}/{m['fp']}/{m['tn']}/{m['fn']} | {m['unknown_positive']}/{m['unknown_negative']} | {s['status_counts'][arm].get('error',0)} |")
        lines += ["", "F1 ở đây là F1 của lớp phishing. Một arm có thể đạt F1=100% nhưng vẫn có mẫu âm "
                  "lỗi/UNKNOWN: các mẫu đó làm giảm Accuracy và coverage, chưa làm giảm positive-class F1. "
                  "Luôn đọc đồng thời ba chỉ số và các cột số đếm."]
        lines += ["", "### Đối chứng hằng số", "", "| Đối chứng | Precision | Recall | F1 | FPR | Accuracy |",
                  "|---|---:|---:|---:|---:|---:|"]
        for arm, m in s["baselines"].items():
            lines.append(f"| {arm} | {pct(m['precision'])} | {pct(m['recall'])} | {pct(m['f1'])} | {pct(m['false_positive_rate'])} | {pct(m['accuracy'])} |")
        lines += ["", "### Tài nguyên và RAG thực được đính kèm", "",
                  "| Cấu hình | Tổng token ghi nhận | Trung vị (ms) | Phản hồi hợp lệ kèm nguồn | Phản hồi có citation khớp chữ |",
                  "|---|---:|---:|---:|---:|"]
        for arm in ARMS:
            lines.append(f"| {NAMES[arm]} | {s['usage'][arm]['total_tokens']} | {s['timing'][arm]['median_ms']} | "
                         f"{s['citations'][arm]['actual_rag_calls']} | {s['citations'][arm]['calls_with_valid_citation']} |")
        lines += ["", "### Phân nhóm theo tài liệu tìm được", "",
                  "Khi không có nguồn, hai arm tương ứng nhận cùng nội dung/prompt nhưng là các lượt gọi độc lập. "
                  "Chênh lệch ở nhóm này có thể do dao động sinh hoặc lỗi, không phải đóng góp của tài liệu.", "",
                  "| Nhóm | n | F1 LLM | F1 LLM + RAG | F1 LLM + URL | F1 LLM + URL + RAG |", "|---|---:|---:|---:|---:|---:|"]
        for group, values in s["by_available_rag_context"].items():
            m=values["metrics"]
            lines.append(f"| {group} | {values['n']} | {pct(m['llm_only']['f1'])} | {pct(m['llm_rag']['f1'])} | {pct(m['llm_url']['f1'])} | {pct(m['llm_url_rag']['f1'])} |")
        lines += ["", "### Chênh lệch F1 theo cặp — thăm dò", "",
                  "Bootstrap cùng nhóm ở cả hai arm, 2.000 lần, seed cố định; đơn vị trong bảng là điểm phần trăm. "
                  "Khoảng này chỉ phản ánh lấy mẫu trên nhãn cố định, không bao phủ sai nhãn AI hoặc dao động giữa các lượt LLM. "
                  "Không dùng để kết luận có ý nghĩa thống kê hoặc chọn lại nhãn/test.", "",
                  "| So sánh | Chênh F1 | Khoảng bootstrap 95% |",
                  "|---|---:|---|"]
        for comparison, interval in s["paired_f1_cluster_bootstrap"].items():
            a, b = interval["baseline"], interval["treatment"]
            left, right = s["metrics"][a]["f1"], s["metrics"][b]["f1"]
            point = f"{100*(right-left):+.2f}" if left is not None and right is not None else "N/A"
            bounds = interval["ci95_delta_f1_percentage_points"]
            lines.append(f"| {comparison} | {point} | " + (f"[{bounds[0]:+.2f}; {bounds[1]:+.2f}]" if bounds else "N/A") + " |")
        lines += ["", f"Số mẫu có ít nhất một arm khác nhãn AI hoặc lỗi/abstain: **{len(s['cases_to_review'])}**. "
                  "Xem cases_to_review.json để rà cả nhãn tham chiếu lẫn dự đoán; không tự coi mọi bất đồng là lỗi mô hình.", ""]
        if name == "challenge":
            lines += ["### Nhóm prompt injection", "", "| Cấu hình | n | F1 | FPR | Coverage |",
                      "|---|---:|---:|---:|---:|"]
            for arm in ARMS:
                m = s["by_injection"]["injection"][arm]
                lines.append(f"| {NAMES[arm]} | {m['n']} | {pct(m['f1'])} | {pct(m['false_positive_rate'])} | {pct(m['coverage'])} |")
            lines.append("")
    calls = sum(sum(s["status_counts"][a].values()) for s in (data["sms"],data["challenge"]) for a in ARMS)
    failures = sum(len(data[k]["failures"]) for k in ("sms","challenge"))
    url_differences = sum(len(data[k]["verification"].get("url_annotation_extraction_disagreements",[])) for k in ("sms","challenge"))
    lines += ["## Phạm vi và giới hạn", "",
              f"- Hoàn tất {calls} lượt đã định; {failures} lỗi được giữ trong kết quả. Không retry để thay phản hồi lỗi.",
              "- Một lượt mỗi arm; model/prompt/ngưỡng/corpus giữ theo protocol, không fine-tune trong lượt này.",
              "- Nhóm không có URL không nhận điểm URL; khác biệt giữa hai arm ở nhóm này không chứng minh model URL hữu ích.",
              "- Khi retrieval rỗng, arm RAG nhận prompt không kèm nguồn. Đọc số lượt thực có RAG cùng chênh lệch F1.",
              "- Citation khớp chữ chỉ được kiểm tra về cấu trúc. Chưa chấm relevance/entailment hoặc rubric lời giải thích bằng người.",
              "- Token là usage ghi nhận ở phản hồi được lưu thành công; lỗi có thể thiếu usage, không coi bằng 0 để khẳng định tổng hóa đơn.",
              "- Bộ SMS có ít phishing dương theo nhãn AI; nhiều ca thiếu ngữ cảnh được giữ riêng. Không suy rộng tỷ lệ lớp, FPR hoặc precision thành hiệu quả triển khai thực tế.",
              "- Đã đối chiếu độc lập số học bằng scikit-learn; việc này không xác nhận nhãn AI là đúng."]
    if url_differences:
        lines += [f"- Có {url_differences} mẫu mà URL trích từ văn bản khác metadata URL dự kiến. "
                  "Bộ trích hiện tại lấy cả dấu » ở cuối URL trong câu trích. verification.json lưu hai dạng; "
                  "các kết quả được giữ nguyên theo pipeline đã chạy, chưa sửa parser hoặc chạy lại."]
    return "\n".join(lines) + "\n"


def explanation_sheet(data, out):
    """Keep all preselected dev IDs; missing outputs are not replaced."""
    selection = [r for r in (json.loads(s) for s in (ROOT / "data/annotation/objective_v1/explanation_selection.jsonl").read_text().splitlines()) if r["split"] == "dev"]
    rows, mapping = [], []
    inputs = {}
    for dataset in ("sms", "challenge"):
        path = Path(data[dataset]["path"])
        inputs[dataset] = {r["id"]:r for r in (json.loads(s) for s in (path / "results.jsonl").read_text().splitlines())}
    for chosen in selection:
        r = inputs[chosen["dataset"]].get(chosen["id"])
        for arm in ARMS:
            key = "EX-" + hashlib.sha256((chosen["dataset"] + chosen["id"] + arm).encode()).hexdigest()[:14]
            response = r[arm] if r else {"status":"reference_unknown_not_run"}
            verdict = response.get("verdict", {})
            support = verdict.get("knowledge_support", [])
            cited = {item["document_id"] for item in support}
            sources = [{k: s.get(k) for k in ("document_id", "title", "text", "source_url", "context_note")} for s in r["retrieval"]["sources"] if s["document_id"] in cited] if r else []
            rows.append({"review_id":key, "text":r["text"] if r else "Mẫu reference UNKNOWN được giữ riêng, chưa gọi LLM trong lượt nhị phân.",
                "output_status":response["status"], "summary":verdict.get("summary", ""),
                "evidence":json.dumps(verdict.get("evidence", []), ensure_ascii=False),
                "actions":json.dumps(verdict.get("recommended_actions", []), ensure_ascii=False),
                "cited_sources":json.dumps(sources, ensure_ascii=False), "source_claims":json.dumps(support, ensure_ascii=False),
                "signals_score":"", "sources_relevance_score":"" if support else "N/A", "claim_support_score":"" if support else "N/A",
                "actions_score":"", "notes":"", "rater_id":""})
            mapping.append({"review_id":key, "dataset":chosen["dataset"], "id":chosen["id"], "arm":arm, "output_status":response["status"]})
    random.Random(20261102).shuffle(rows)
    with (out / "explanation_blind_dev.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        # Spreadsheet safety for untrusted messages/provider outputs.
        writer.writerows({k:("'"+str(v) if str(v).lstrip().startswith(("=","+","-","@")) else v) for k,v in r.items()} for r in rows)
    (out / "explanation_mapping_coordinator.json").write_text(json.dumps(mapping, ensure_ascii=False, indent=2)+"\n",encoding="utf-8")
    return {"preselected_dev_messages":len(selection), "rows":len(rows),
            "outputs_ok":sum(r["output_status"]=="ok" for r in mapping),
            "outputs_missing":sum(r["output_status"]!="ok" for r in mapping), "ratings_status":"not_scored",
            "blinding_limit":"Method/model/verdict labels hidden; citation presence may reveal RAG. Coordinator mapping must not be shown to blind reviewers."}


def plot(data, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    colors = ("#0f766e", "#2563eb", "#9333ea", "#c2410c")
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), layout="constrained")
    for row, dataset in enumerate(("sms", "challenge")):
        for col, (metric, title) in enumerate((("f1", "F1"), ("false_positive_rate", "False positive rate"))):
            ax = axes[row, col]
            vals = [data[dataset]["metrics"][a][metric] for a in ARMS]
            bars = ax.bar(range(4), [100*v if v is not None else 0 for v in vals], color=colors)
            ax.bar_label(bars, labels=[f"{100*v:.1f}%" if v is not None else "N/A" for v in vals], padding=3)
            ax.set_xticks(range(4), [NAMES[a] for a in ARMS], rotation=10, fontsize=9)
            ax.set_ylim(0, 115)
            ax.set_title(f"{dataset}: n={data[dataset]['n']} ({data[dataset]['positive']} positive) — {title}")
            ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle("DEV diagnostic | AI reference labels, not independent gold\nOne run per arm; errors and UNKNOWN retained; datasets reported separately.")
    for ext in ("png", "svg"):
        fig.savefig(out / f"comparison.{ext}", dpi=180, bbox_inches="tight")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sms", type=Path, required=True)
    parser.add_argument("--challenge", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("Choose a new output directory; previous reports remain frozen.")
    data = {"created_at": datetime.now(timezone.utc).isoformat(), "reference_status": "ai_reference_unverified", "reporter_sha256":sha(__file__),
            "sms": summarize(args.sms), "challenge": summarize(args.challenge)}
    args.out.mkdir(parents=True)
    data["explanation_review"] = explanation_sheet(data, args.out)
    (args.out / "summary.json").write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (args.out / "report.md").write_text(markdown(data), encoding="utf-8")
    (args.out / "cases_to_review.json").write_text(json.dumps({k:data[k]["cases_to_review"] for k in ("sms","challenge")}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    plot(data, args.out)
    print(json.dumps({"report": str(args.out / "report.md"), "sms": data["sms"]["metrics"], "challenge": data["challenge"]["metrics"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
