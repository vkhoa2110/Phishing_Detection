"""Verify completed URL/context executions and render a separate result artifact."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys

import numpy as np
from sklearn.metrics import accuracy_score, confusion_matrix, precision_recall_fscore_support

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from evaluation.message_data import read_jsonl, sha, write_json
from evaluation.url_context_pack import TARGETS, verify as verify_pack
from evaluation.url_context_run import canonical_sha, parse_content, payload_for
from evaluation.url_context_score import expected_keys, level, validate_records

NAMES = {"url_model": "Model URL", "llm_only": "LLM", "llm_url": "LLM + URL"}


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def predict(value):
    return 1 if value in {"HIGH", "WARNING"} else 0 if value == "LOW" else -1


def check_metrics(cases, lookup, arm, rep, target, saved):
    binary = [c for c in cases if c["targets"][target] is not None]
    y = np.array([c["targets"][target] for c in binary], dtype=int)
    levels = [level(lookup[(c["id"], arm, rep)], target) for c in binary]
    p = np.array([predict(v) for v in levels], dtype=int)
    assert saved["n"] == len(binary)
    unknown = [c for c in cases if c["targets"][target] is None]
    assert saved["reference_unknown_count"] == len(unknown)
    assert saved["reference_unknown_predictions"] == dict(Counter(level(lookup[(c["id"], arm, rep)], target) for c in unknown))
    assert saved["technical_errors"] == sum(lookup[(c["id"], arm, rep)]["status"] == "error" for c in cases)
    if not binary:
        return
    matrix = confusion_matrix(y, p, labels=[1, 0, -1])
    tp, fn, up = map(int, matrix[0]); fp, tn, un = map(int, matrix[1])
    precision, recall, f1, _ = precision_recall_fscore_support(y, p, labels=[1], zero_division=np.nan)
    covered = int(sum(p != -1))
    values = {"tp": tp, "fn": fn, "fp": fp, "tn": tn, "unknown_positive": up, "unknown_negative": un,
        "precision": precision[0], "recall": recall[0], "f1": f1[0], "accuracy": accuracy_score(y, p),
        "coverage": covered / len(y), "selective_accuracy": sum(y == p) / covered if covered else np.nan,
        "false_positive_rate": fp / sum(y == 0) if sum(y == 0) else np.nan}
    for name, value in values.items():
        assert (saved[name] is None and math.isnan(value)) or (saved[name] is not None and abs(saved[name] - value) < 1e-12), (arm, rep, target, name)
    assert saved["risk_counts"] == dict(Counter(levels))


def paired_bootstrap(cases, lookup, repetitions, target, baseline="llm_only", draws=2000):
    """Resample domains jointly for all arms/repeats; no independent-row claim."""
    binary = [c for c in cases if c["targets"][target] is not None]
    groups = sorted({c["group_id"] for c in binary})
    if not groups:
        return None
    positions = {g: i for i, g in enumerate(groups)}
    counts = np.zeros((len(groups), repetitions, 2, 3))
    for c in binary:
        for repeat in range(1, repetitions + 1):
            for a, arm in enumerate((baseline, "llm_url")):
                rep = 0 if arm == "url_model" else repeat
                p = predict(level(lookup[(c["id"], arm, rep)], target))
                category = 0 if c["targets"][target] == 1 and p == 1 else 1 if c["targets"][target] == 0 and p == 1 else 2 if c["targets"][target] == 1 else None
                if category is not None:
                    counts[positions[c["group_id"]], repeat - 1, a, category] += 1
    rng = np.random.default_rng(20261103)
    totals = counts[rng.integers(0, len(groups), size=(draws, len(groups)))].sum(axis=1)
    denominator = 2 * totals[..., 0] + totals[..., 1] + totals[..., 2]
    f1 = np.divide(2 * totals[..., 0], denominator, out=np.full_like(denominator, np.nan), where=denominator != 0)
    deltas = 100 * (f1[:, :, 1] - f1[:, :, 0]).mean(axis=1)
    valid = deltas[np.isfinite(deltas)]
    return {"baseline": baseline, "treatment": "llm_url", "target": target, "domain_groups": len(groups),
            "draws": draws, "valid_draws": len(valid), "seed": 20261103,
            "ci95_mean_delta_f1_pp": list(map(float, np.quantile(valid, [.025, .975]))) if len(valid) else None,
            "interpretation": "Exploratory domain bootstrap over observed repeats with references fixed. Does not quantify source-label error, shared-template dependence or population shift."}


def verify(run):
    config = read(run / "execution.json")["configuration"]
    pack = Path(config["pack"])
    verify_pack(pack)
    assert sha(pack / "manifest.json") == config["pack_manifest_sha256"]
    assert sha(pack / f"{config['split']}.jsonl") == config["dataset_sha256"]
    assert sha(pack / "system_prompt.txt") == config["prompt_sha256"]
    for file, digest in {**config["source_sha256"], **config["model_files_sha256"]}.items():
        assert sha(ROOT / file) == digest, file
    assert sha(run / "prepared_urls.json") == (run / "prepared_urls.sha256").read_text().strip()
    prepared = read(run / "prepared_urls.json")
    cases = read_jsonl(pack / f"{config['split']}.jsonl")
    urls = {r["id"]: r for r in read_jsonl(pack / "urls.jsonl")}
    records = read_jsonl(run / "predictions.jsonl")
    lookup, missing = validate_records(cases, records, config["repetitions"])
    assert not missing and len(records) == len(expected_keys(cases, config["repetitions"]))
    attempts = read_jsonl(run / "attempts.jsonl")
    attempts_by_key = {(a["id"], a["arm"], a["repeat"]): a for a in attempts}
    assert len(attempts) == len(attempts_by_key) == config["max_total_provider_attempts"]
    prompt = (pack / "system_prompt.txt").read_text()
    for c in cases:
        ml = prepared[c["url_id"]]
        assert ml["url"] == urls[c["url_id"]]["url"] and ml["status"] == "ok"
        warning = config["thresholds"]["warning_threshold"]
        high = config["thresholds"]["high_threshold"]
        assert ml["warning_threshold"] == warning and ml["high_threshold"] == high
        expected = "HIGH" if high is not None and ml["score"] >= high else "WARNING" if ml["score"] >= warning else "LOW"
        assert ml["risk_level"] == expected == lookup[(c["id"], "url_model", 0)]["outputs"]["url_risk"]
        for arm in ("llm_only", "llm_url"):
            payload = payload_for(c, arm, ml, prompt, config)
            for rep in range(1, config["repetitions"] + 1):
                key = (c["id"], arm, rep)
                r, a = lookup[key], attempts_by_key[key]
                assert a["payload_sha256"] == canonical_sha(payload)
                if r.get("error_code") != "INTERRUPTED_REQUEST":
                    assert r["payload_sha256"] == a["payload_sha256"]
                if r["status"] == "ok":
                    parsed = parse_content(r["raw_content"], c)
                    assert r["outputs"] == {t: parsed[t] for t in TARGETS}
                    assert all(r[k] == parsed[k] for k in ("url_role", "explanation", "evidence_quotes"))
                elif r.get("error_code") == "OUTPUT_INVALID":
                    try:
                        parse_content(r.get("raw_content"), c)
                    except (ValueError, TypeError, KeyError):
                        pass
                    else:
                        raise AssertionError("Valid content incorrectly recorded as OUTPUT_INVALID")
                elif r.get("error_code") == "OUTPUT_TRUNCATED":
                    assert r["finish_reason"] == "length"
    summary = read(run / "summary.json")
    assert summary["metrics_ready"] and summary["run_state"]["stop_reason"] == "all_calls_completed"
    assert summary["provider_requests"] == len(attempts)
    for task, targets in summary["metrics"].items():
        subset = [c for c in cases if c["task"] == task]
        for target, values in targets.items():
            for arm, reps in values["by_repeat"].items():
                for rep, saved in reps.items():
                    check_metrics(subset, lookup, arm, int(rep), target, saved)
                for name, moments in values["repeat_summary"][arm].items():
                    observations = [r[name] for r in reps.values() if r[name] is not None]
                    assert moments["defined_repeats"] == len(observations)
                    assert moments["mean"] is None if not observations else abs(moments["mean"] - np.mean(observations)) < 1e-12
                    assert moments["std_across_repeats"] is None if len(observations) < 2 else abs(moments["std_across_repeats"] - np.std(observations, ddof=1)) < 1e-12
            for stratum, arms in values["by_source_tier"].items():
                rows = [c for c in subset if urls[c["url_id"]]["source"] + "/" + urls[c["url_id"]]["tier"] == stratum]
                for arm, reps in arms.items():
                    for rep, saved in reps.items():
                        check_metrics(rows, lookup, arm, int(rep), target, saved)
            for name, reps in values["paired"].items():
                baseline = name.removesuffix("_to_llm_url")
                binary = [c for c in subset if c["targets"][target] is not None]
                for rep_string, saved in reps.items():
                    rep = int(rep_string)
                    a = [predict(level(lookup[(c["id"], baseline, 0 if baseline == "url_model" else rep)], target)) == c["targets"][target] for c in binary]
                    b = [predict(level(lookup[(c["id"], "llm_url", rep)], target)) == c["targets"][target] for c in binary]
                    assert saved["improved"] == sum(not x and y for x, y in zip(a, b))
                    assert saved["regressed"] == sum(x and not y for x, y in zip(a, b))
                    assert saved["both_correct"] == sum(x and y for x, y in zip(a, b))
                    assert saved["both_wrong"] == sum(not x and not y for x, y in zip(a, b))
    for arm in ("llm_only", "llm_url", "url_model"):
        rows = [r for r in records if r["arm"] == arm]
        assert summary["status_counts"][arm] == dict(Counter(r["status"] for r in rows))
        if arm != "url_model":
            assert summary["error_codes"][arm] == dict(Counter(r["error_code"] for r in rows if r["status"] == "error"))
            for k, total in summary["usage"][arm].items():
                assert total == sum(r.get("usage", {}).get(k, 0) for r in rows)
    checks = {"neutral_link": lambda c: c["variant"] == "neutral_link",
        "benign_url_secret_request": lambda c: c["targets"]["url_risk"] == 0 and c["targets"]["message_behavior"] == 1,
        "risky_url_educational_quote": lambda c: c["targets"]["url_risk"] == 1 and c["url_role"] == "quoted",
        "injection": lambda c: c["variant"].endswith("injection")}
    for name, predicate in checks.items():
        subset = [c for c in cases if c["task"] == "message_context" and predicate(c)]
        assert summary["context_checks"][name]["n"] == len(subset)
        for arm, reps in summary["context_checks"][name]["by_repeat"].items():
            for rep, saved in reps.items():
                check_metrics(subset, lookup, arm, int(rep), "action_risk", saved)
    return config, cases, records, lookup, summary


def pct(value):
    return "N/A" if value is None else f"{100 * value:.2f}%"


def report(config, cases, records, lookup, summary, out):
    lines = ["# Đánh giá URL và ngữ cảnh — dev", "", "**Nhãn URL lịch sử và ngữ cảnh tự soạn; không phải nhãn SMS thực độc lập.**",
        "", f"{len(cases)} đầu vào, {config['repetitions']} lượt mỗi cấu hình LLM, {summary['provider_requests']} lượt API đã định. "
        "Model URL được tính cục bộ và dùng lại. Test chưa chạy trong lượt này. Các ca ngữ cảnh dùng lại URL nên không độc lập thống kê.",
        "", f"Model: {config['model']}; temperature={config['temperature']}; max_tokens={config['max_tokens']}; "
        f"WARNING={config['thresholds']['warning_threshold']:.6f}, HIGH={config['thresholds']['high_threshold']:.6f}. "
        "Hai cấu hình LLM dùng cùng prompt/schema/URL; chỉ khác có hay không có điểm ML. Prompt nghiên cứu khác message-v3 của ứng dụng.", ""]
    bootstrap = {}
    for task, targets in summary["metrics"].items():
        subset = [c for c in cases if c["task"] == task]
        lines += [f"## {task}: {len(subset)} mẫu", ""]
        for target, values in targets.items():
            lines += [f"### {target}", "", "| Cấu hình | Lượt | n nhị phân | Precision | Recall | F1 | Accuracy | FPR | Coverage | UNKNOWN +/− | Lỗi* |",
                      "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|"]
            for arm in ("url_model", "llm_only", "llm_url"):
                for rep, m in values["by_repeat"].get(arm, {}).items():
                    lines.append(f"| {NAMES[arm]} | {rep} | {m['n']} | {pct(m['precision'])} | {pct(m['recall'])} | {pct(m['f1'])} | {pct(m['accuracy'])} | {pct(m['false_positive_rate'])} | {pct(m['coverage'])} | {m['unknown_positive']}/{m['unknown_negative']} | {m['technical_errors']} |")
            unknown = next(iter(next(iter(values["by_repeat"].values())).values()))["reference_unknown_count"]
            lines += ["", f"Reference UNKNOWN/không áp dụng: {unknown} mẫu, báo riêng trong summary.json. "
                      "*Lỗi tính trên toàn nhóm task, kể cả reference UNKNOWN; không cộng các cột lỗi giữa ba mục tiêu.",
                      "", "| Cấu hình | F1 trung bình ± SD giữa các lượt | FPR trung bình | Coverage trung bình |",
                      "|---|---|---:|---:|"]
            for arm, moments in values["repeat_summary"].items():
                m = moments["f1"]
                sd = "N/A" if m["std_across_repeats"] is None else f"{100*m['std_across_repeats']:.2f} điểm %"
                lines.append(f"| {NAMES[arm]} | {pct(m['mean'])} ± {sd} | {pct(moments['false_positive_rate']['mean'])} | {pct(moments['coverage']['mean'])} |")
            lines += ["", "| So sánh sang LLM + URL | Lượt | Sửa đúng | Làm sai thêm | Chênh accuracy (điểm %) |",
                      "|---|---:|---:|---:|---:|"]
            for name, reps in values["paired"].items():
                for rep, m in reps.items():
                    delta = "N/A" if m["accuracy_delta"] is None else f"{100*m['accuracy_delta']:+.2f}"
                    lines.append(f"| {name} | {rep} | {m['improved']} | {m['regressed']} | {delta} |")
            bootstrap[task + "/" + target] = paired_bootstrap(subset, lookup, config["repetitions"], target)
            ci = bootstrap[task + "/" + target]
            if ci and ci["ci95_mean_delta_f1_pp"]:
                a, b = ci["ci95_mean_delta_f1_pp"]
                lines += ["", f"Khoảng bootstrap miền 95% của chênh F1 trung bình (LLM + URL − LLM): [{a:+.2f}; {b:+.2f}] điểm %. "
                          "Đây là thăm dò trên nhãn cố định; không bao phủ sai nhãn nguồn, sự phụ thuộc giữa câu mẫu và độ lệch khi triển khai.", ""]
    lines += ["## Đối chứng hằng số", "", "| Task / mục tiêu | n (+/−) | F1 luôn cảnh báo | FPR luôn cảnh báo | Accuracy luôn LOW |",
              "|---|---|---:|---:|---:|"]
    for task, target in (("url_only", "url_risk"), ("message_context", "message_behavior"), ("message_context", "action_risk")):
        binary = [c for c in cases if c["task"] == task and c["targets"][target] is not None]
        n, positives = len(binary), sum(c["targets"][target] for c in binary)
        lines.append(f"| {task}/{target} | {n} ({positives}/{n-positives}) | {pct(2*positives/(n+positives) if n+positives else None)} | {pct(1 if n>positives else None)} | {pct((n-positives)/n if n else None)} |")
    lines += ["", "Luôn LOW có Recall=0 và F1=0 khi có mẫu dương. Đối chứng hằng số có coverage=100%; tỷ lệ lớp cân bằng không đại diện triển khai thực tế.", "",
              "## Nhóm đối chứng: action_risk", "", "| Nhóm | n | Cấu hình | Lượt | F1 | FPR | Accuracy | Coverage |", "|---|---:|---|---:|---:|---:|---:|---:|"]
    for name, group in summary["context_checks"].items():
        for arm, reps in group["by_repeat"].items():
            for rep, m in reps.items():
                lines.append(f"| {name} | {group['n']} | {NAMES[arm]} | {rep} | {pct(m['f1'])} | {pct(m['false_positive_rate'])} | {pct(m['accuracy'])} | {pct(m['coverage'])} |")
    lines += ["", "Nhóm chỉ có một lớp có chỉ số không xác định; không đọc F1=0 ở nhóm toàn âm thành 0% chính xác. Dùng FPR/Accuracy/Coverage cùng số đếm.", "",
              "## Nguồn/tier của phần URL-only", "", "| Nguồn/tier | Cấu hình | Lượt | n | TP/FP/TN/FN | UNKNOWN +/− | FPR | Recall |", "|---|---|---:|---:|---|---|---:|---:|"]
    for name, arms in summary["metrics"]["url_only"]["url_risk"]["by_source_tier"].items():
        for arm, reps in arms.items():
            for rep, m in reps.items():
                lines.append(f"| {name} | {NAMES[arm]} | {rep} | {m['n']} | {m['tp']}/{m['fp']}/{m['tn']}/{m['fn']} | {m['unknown_positive']}/{m['unknown_negative']} | {pct(m['false_positive_rate'])} | {pct(m['recall'])} |")
    lines += ["", "## Lỗi, tài nguyên và giới hạn", "", "| Cấu hình | Phản hồi ok | Lỗi | Token ghi nhận | Trung vị (giây) |", "|---|---:|---:|---:|---:|"]
    for arm in ("llm_only", "llm_url"):
        elapsed = [r["elapsed_ms"] / 1000 for r in records if r["arm"] == arm and "elapsed_ms" in r]
        counts = summary["status_counts"][arm]
        lines.append(f"| {NAMES[arm]} | {counts.get('ok',0)} | {counts.get('error',0)} | {summary['usage'][arm]['total_tokens']} | {np.median(elapsed):.2f} |")
    lines += ["", "Mã lỗi: `" + json.dumps(summary["error_codes"], ensure_ascii=False) + "`.", "",
        "- Toàn bộ lỗi được giữ; không gọi lại để thay kết quả. Token là usage ghi nhận, chưa đối chiếu hóa đơn.",
        "- F1 lớp dương có thể cao dù lỗi/UNKNOWN ở lớp âm. Luôn đọc cùng accuracy, FPR và coverage.",
        "- Đã kiểm tra số học bằng scikit-learn, hash dữ liệu/model/prompt, payload và checkpoint. Kiểm tra trích nguyên văn không xác nhận lập luận đúng.",
        "- Nguồn URL là PhishVN gold/silver lịch sử, đã từng đánh giá ML; nhóm dev dương đều silver. Cân bằng lớp không đại diện tỷ lệ lừa đảo thực tế.",
        "- Ngữ cảnh ghép và action_risk được định nghĩa theo thiết kế. Không phải bằng chứng các URL từng xuất hiện trong thông điệp đó.",
        "- Không thay prompt, ngưỡng hay nhãn giữa các lượt. Số đo không phải kết quả ứng dụng message-v3 và không so trực tiếp với 51 SMS cũ."]
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_json(out / "bootstrap.json", bootstrap)
    review = []
    for c in cases:
        targets = ("url_risk",) if c["task"] == "url_only" else TARGETS
        outcomes = {str(rep): {arm: lookup[(c["id"], arm, rep)].get("outputs", {}) for arm in ("llm_only", "llm_url")}
                    for rep in range(1, config["repetitions"] + 1)}
        if any(c["targets"][t] is not None and (predict(level(lookup[(c["id"], a, rep)], t)) != c["targets"][t])
               for t in targets for a in ("llm_only", "llm_url") for rep in range(1, config["repetitions"] + 1)):
            review.append({**c, "outcomes": outcomes})
    write_json(out / "cases_to_review.json", review)
    return bootstrap


def plot(summary, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 2, figsize=(11, 7), layout="constrained")
    for row, (task, target, title) in enumerate((("url_only", "url_risk", "URL-only: 40 historical URLs"),
                                               ("message_context", "action_risk", "Action risk: 80 authored contexts"))):
        s = summary["metrics"][task][target]["repeat_summary"]
        arms = [a for a in ("url_model", "llm_only", "llm_url") if a in s]
        for col, metric in enumerate(("f1", "false_positive_rate")):
            values = [100 * s[a][metric]["mean"] for a in arms]
            errors = [100 * (s[a][metric]["std_across_repeats"] or 0) for a in arms]
            ax = axes[row, col]
            bars = ax.bar(range(len(arms)), values, yerr=errors, capsize=5, color=[{"url_model": "#64748b", "llm_only": "#0f766e", "llm_url": "#2563eb"}[a] for a in arms])
            ax.bar_label(bars, labels=[f"{v:.1f}%" for v in values], padding=8)
            ax.set_xticks(range(len(arms)), [NAMES[a] for a in arms]); ax.set_ylim(0, 115)
            ax.set_title(title + "\n" + ("F1" if metric == "f1" else "False positive rate"))
            ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle("DEV diagnostic | mean across 3 LLM runs; error bars: repeat SD\nHistorical source labels + authored contexts; errors/UNKNOWN retained.")
    for extension in ("png", "svg"):
        fig.savefig(out / ("comparison." + extension), dpi=180)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("Choose a new report directory")
    config, cases, records, lookup, summary = verify(args.run)
    # This report's captions are deliberately scoped to this preregistered dev run.
    assert config["split"] == "dev" and config["repetitions"] == 3 and len(cases) == 120
    args.out.mkdir(parents=True)
    bootstrap = report(config, cases, records, lookup, summary, args.out)
    plot(summary, args.out)
    write_json(args.out / "verification.json", {"verified": True, "created_at": datetime.now(timezone.utc).isoformat(),
        "cases": len(cases), "provider_attempts": summary["provider_requests"], "metric_library": "scikit-learn",
        "semantic_explanation_quality": "not_verified", "reporter_sha256": sha(__file__),
        "input_hashes": {p.name: sha(p) for p in args.run.iterdir() if p.is_file() and p.name != ".run.lock"}})
    write_json(args.out / "summary.json", {"configuration": config, "results": summary, "bootstrap": bootstrap})
    print(json.dumps({"report": str(args.out / "report.md"), "verified": True, "provider_attempts": summary["provider_requests"]}))


if __name__ == "__main__":
    main()
