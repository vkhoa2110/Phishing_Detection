"""Verify and report completed four-arm component runs; no API/model calls."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from evaluation.messages.components import ARMS, TARGETS, canonical_sha, expected_keys, load_cases, lookup_records, metric, parse_content, payload_for
from evaluation.data.sms import read_jsonl, sha, write_json
from evaluation.common.metrics import measure, paired_comparison, prediction
from scripts.evaluation.report_url_context import check_metrics

NAMES = {"llm_only": "LLM", "llm_url": "LLM + URL", "llm_rag": "LLM + RAG", "llm_url_rag": "LLM + URL + RAG"}
COMPARISONS = (("URL, không RAG", "llm_only", "llm_url"), ("RAG, không URL", "llm_only", "llm_rag"),
               ("RAG, có URL", "llm_url", "llm_url_rag"), ("URL, có RAG", "llm_rag", "llm_url_rag"))


def read(path):
    return json.loads(Path(path).read_text())


def verify(run):
    config = read(run / "execution.json")["configuration"]
    for path, digest in config["source_hashes"].items():
        assert sha(path) == digest, path
    cases = read_jsonl(run / "cases.jsonl")
    assert canonical_sha(cases) == config["cases_sha256"]
    prepared = read(run / "prepared.json")
    assert sha(run / "prepared.json") == (run / "prepared.sha256").read_text().strip()
    assert set(prepared) == {c["id"] for c in cases}
    records = read_jsonl(run / "predictions.jsonl")
    lookup = lookup_records(cases, records)
    assert set(lookup) == expected_keys(cases), "Run incomplete"
    attempts = read_jsonl(run / "attempts.jsonl")
    by_attempt = {(a["id"], a["arm"]): a for a in attempts}
    assert len(by_attempt) == len(attempts) == config["provider_call_budget"]
    for c in cases:
        for output in prepared[c["id"]]["urls"]:
            assert output["status"] == "ok" and output["url"] in c["text"]
            warning, high = config["thresholds"]["warning_threshold"], config["thresholds"]["high_threshold"]
            assert output["warning_threshold"] == warning and output["high_threshold"] == high
            expected = "HIGH" if high is not None and output["score"] >= high else "WARNING" if output["score"] >= warning else "LOW"
            assert output["risk_level"] == expected
        for arm in ARMS:
            r, attempt = lookup[(c["id"], arm)], by_attempt[(c["id"], arm)]
            payload = payload_for(c, prepared[c["id"]], arm, config)
            digest = canonical_sha(payload)
            assert attempt["payload_sha256"] == digest
            assert r.get("payload_sha256", digest if r.get("error_code") == "INTERRUPTED_REQUEST" else None) == digest
            if r["status"] == "ok":
                parsed = parse_content(r["raw_content"], c, json.loads(payload["messages"][1]["content"])["reference_documents"])
                assert r["outputs"] == {t: parsed[t] for t in TARGETS}
                assert all(r[k] == parsed[k] for k in ("knowledge_support", "explanation", "evidence_quotes", "url_role"))
            elif r["error_code"] == "OUTPUT_TRUNCATED":
                assert r["finish_reason"] == "length"
            elif r["error_code"] == "OUTPUT_INVALID":
                try:
                    parse_content(r.get("raw_content"), c, json.loads(payload["messages"][1]["content"])["reference_documents"])
                except (ValueError, TypeError, KeyError):
                    pass
                else:
                    raise AssertionError("Invalid-output checkpoint contains a valid response")
    summary = read(run / "summary.json")
    assert summary["metrics_ready"] and summary["run_state"]["stop_reason"] == "all_calls_completed"
    assert summary["completed_calls"] == summary["provider_attempts"] == config["provider_call_budget"]
    assert summary["execution_sha256"] == sha(run / "execution.json")
    assert summary["prepared_sha256"] == sha(run / "prepared.json")
    three_keys = {(case_id, arm, 1): r for (case_id, arm), r in lookup.items()}
    for dataset in ("sms", "url_context"):
        selected = [c for c in cases if c["dataset"] == dataset]
        for target, arms in summary["metrics"][dataset].items():
            for arm, saved in arms.items():
                check_metrics(selected, three_keys, arm, 1, target, saved)
        for group, targets in summary["by_retrieval"][dataset].items():
            subset = [c for c in selected if bool(prepared[c["id"]]["retrieval"]["sources"]) == (group == "with_sources")]
            for target, arms in targets.items():
                for arm, saved in arms.items():
                    check_metrics(subset, three_keys, arm, 1, target, saved)
    for arm in ARMS:
        assert summary["status_counts"][arm] == dict(Counter(r["status"] for r in records if r["arm"] == arm))
        assert summary["error_codes"][arm] == dict(Counter(r["error_code"] for r in records if r["arm"] == arm and r["status"] == "error"))
        for k, v in summary["usage"][arm].items():
            assert v == sum(r.get("usage", {}).get(k, 0) for r in records if r["arm"] == arm)
    return config, cases, prepared, records, lookup, summary


def level(record, target):
    return record["outputs"][target] if record["status"] == "ok" else "UNKNOWN"


def paired_bootstrap(cases, lookup, target, left, right, draws=2000):
    binary = [c for c in cases if c["targets"][target] is not None]
    groups = sorted({c["group_id"] for c in binary})
    if not groups:
        return None
    positions = {g: i for i, g in enumerate(groups)}
    counts = np.zeros((len(groups), 2, 3))
    for c in binary:
        for i, arm in enumerate((left, right)):
            p = prediction(level(lookup[(c["id"], arm)], target))
            category = 0 if c["targets"][target] == 1 and p == 1 else 1 if c["targets"][target] == 0 and p == 1 else 2 if c["targets"][target] == 1 else None
            if category is not None:
                counts[positions[c["group_id"]], i, category] += 1
    rng = np.random.default_rng(20261104)
    totals = counts[rng.integers(0, len(groups), size=(draws, len(groups)))].sum(axis=1)
    denominator = 2 * totals[..., 0] + totals[..., 1] + totals[..., 2]
    f1 = np.divide(2 * totals[..., 0], denominator, out=np.full_like(denominator, np.nan), where=denominator != 0)
    deltas = 100 * (f1[:, 1] - f1[:, 0])
    valid = deltas[np.isfinite(deltas)]
    return {"groups": len(groups), "draws": draws, "valid_draws": len(valid), "seed": 20261104,
            "ci95_delta_f1_pp": list(map(float, np.quantile(valid, [.025, .975]))) if len(valid) else None,
            "scope": "One generation, fixed references, resampled groups; not repeat variability or source-label uncertainty."}


def augment(cases, prepared, lookup, summary, config=None):
    result = {"paired": {}, "context_checks": {}, "url_model": {}, "constant_baselines": {},
              "citation_by_dataset": {}, "identical_input_pairs": {}, "validation_errors": []}
    for dataset, targets in summary["metrics"].items():
        selected = [c for c in cases if c["dataset"] == dataset]
        result["citation_by_dataset"][dataset] = {arm: {
            "eligible_with_sources": sum(bool(prepared[c["id"]]["retrieval"]["sources"]) for c in selected) if arm in {"llm_rag", "llm_url_rag"} else 0,
            "responses_with_literal_support": sum(bool(lookup[(c["id"], arm)].get("knowledge_support")) for c in selected),
            "semantic_relevance_or_support_verified": False} for arm in ARMS}
        result["paired"][dataset], result["constant_baselines"][dataset] = {}, {}
        if config is not None:
            result["identical_input_pairs"][dataset] = {}
            for name, left, right in COMPARISONS:
                identical = [c for c in selected if canonical_sha(payload_for(c, prepared[c["id"]], left, config)) ==
                             canonical_sha(payload_for(c, prepared[c["id"]], right, config))]
                result["identical_input_pairs"][dataset][name] = {"cases": len(identical),
                    "different_risk_outputs": sum(any(level(lookup[(c["id"], left)], t) != level(lookup[(c["id"], right)], t)
                                                      for t in targets) for c in identical),
                    "interpretation": "Identical provider inputs called independently; output differences do not establish added-information effects."}
        for target in targets:
            binary = [c for c in selected if c["targets"][target] is not None]
            labels = [c["targets"][target] for c in binary]
            result["constant_baselines"][dataset][target] = {name: measure(labels, [value] * len(labels))
                for name, value in (("always_alarm", "HIGH"), ("always_low", "LOW"))}
            result["paired"][dataset][target] = {name: {
                "left": left, "right": right,
                "counts": paired_comparison(labels, [level(lookup[(c["id"], left)], target) for c in binary],
                                             [level(lookup[(c["id"], right)], target) for c in binary]),
                "bootstrap": paired_bootstrap(binary, lookup, target, left, right)} for name, left, right in COMPARISONS}
        if dataset == "url_context":
            levels = [max((p["risk_level"] for p in prepared[c["id"]]["urls"]),
                          key={"LOW": 0, "WARNING": 1, "HIGH": 2}.get, default="UNKNOWN") for c in selected]
            result["url_model"][dataset] = measure([c["targets"]["url_risk"] for c in selected], levels)
            # Independent sklearn checker used for the ML target too.
            fake_lookup = {(c["id"], "url_model", 0): {"status": "ok", "outputs": {"url_risk": v}}
                           for c, v in zip(selected, levels)}
            model = {**result["url_model"][dataset], "reference_unknown_count": 0,
                     "reference_unknown_predictions": {}, "technical_errors": 0}
            check_metrics(selected, fake_lookup, "url_model", 0, "url_risk", model)
            variants = {c["variant"] for c in selected}
            result["context_checks"] = {variant: {t: {a: metric([c for c in selected if c["variant"] == variant], lookup, a, t)
                for a in ARMS} for t in targets} for variant in sorted(variants)}
    if config is not None:
        for c in cases:
            for arm in ARMS:
                r = lookup[(c["id"], arm)]
                if r["status"] != "error":
                    continue
                reason = r["error_code"]
                if reason == "OUTPUT_INVALID":
                    sources = json.loads(payload_for(c, prepared[c["id"]], arm, config)["messages"][1]["content"])["reference_documents"]
                    try:
                        parse_content(r.get("raw_content"), c, sources)
                    except (ValueError, TypeError, KeyError) as exc:
                        reason = str(exc)
                result["validation_errors"].append({"id": c["id"], "dataset": c["dataset"], "arm": arm,
                                                     "error_code": r["error_code"], "reason": reason})
    return result


def pct(value):
    return "N/A" if value is None else f"{100 * value:.2f}%"


def table(lines, arms):
    lines += ["| Cấu hình | n | Precision | Recall | F1 | Accuracy | FPR | Coverage | UNKNOWN +/− | Lỗi* |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---|---:|"]
    for arm, m in arms.items():
        lines.append(f"| {NAMES.get(arm, arm)} | {m['n']} | {pct(m['precision'])} | {pct(m['recall'])} | {pct(m['f1'])} | "
                     f"{pct(m['accuracy'])} | {pct(m['false_positive_rate'])} | {pct(m['coverage'])} | "
                     f"{m['unknown_positive']}/{m['unknown_negative']} | {m.get('technical_errors', 0)} |")


def markdown(config, summary, extra):
    lines = ["# So sánh LLM, model URL và RAG — component dev v1", "",
        "**Nhãn SMS là nhãn AI chưa xác minh; ngữ cảnh URL do trợ lý soạn. Không phải đánh giá độc lập bằng nhãn người.**", "",
        f"{config['cases']} đầu vào dev, {config['provider_call_budget']} lần thử API, một lần mỗi cấu hình. "
        "Không gộp SMS và ngữ cảnh thành một điểm chung, chưa chạy test.", "",
        f"{config['model']}; temperature=0.1; max_tokens={config['max_tokens']}; timeout={config['timeout_seconds']} giây; workers={config['workers']}. "
        "Cùng prompt/schema/văn bản/validator; chỉ thay điểm URL và tài liệu được cấp. Prompt nghiên cứu khác message-v3 và khác lượt URL/context trước."]
    for dataset, targets in summary["metrics"].items():
        lines += ["", f"## {dataset}", "", f"Truy xuất: {summary['retrieval'][dataset]}"]
        for target, arms in targets.items():
            lines += ["", f"### {target}", ""]
            if target == "url_risk":
                model = extra["url_model"][dataset]
                table(lines, {"Model URL (chỉ chiều URL)": model})
                lines += [""]
            table(lines, arms)
            unknown = next(iter(arms.values()))["reference_unknown_count"]
            lines += ["", f"Reference UNKNOWN/không áp dụng: {unknown}. *Lỗi là tổng lỗi kỹ thuật của nhóm dataset, "
                      "có thể nằm ngoài các mẫu nhị phân của mục tiêu; không cộng lỗi giữa các bảng mục tiêu."]
            lines += ["", "| So sánh | Sửa đúng | Làm sai thêm | Chênh accuracy (điểm %) | Khoảng bootstrap 95% chênh F1 (điểm %) |",
                      "|---|---:|---:|---:|---|"]
            for name, entry in extra["paired"][dataset][target].items():
                c, ci = entry["counts"], entry["bootstrap"]["ci95_delta_f1_pp"]
                interval = "N/A" if ci is None else f"[{ci[0]:+.2f}; {ci[1]:+.2f}]"
                lines.append(f"| {name} | {c['improved']} | {c['regressed']} | {100 * c['accuracy_delta']:+.2f} | {interval} |")
        lines += ["", "### Phân biệt có/không có tài liệu", ""]
        for group, targets in summary["by_retrieval"][dataset].items():
            for target, arms in targets.items():
                lines += [f"**{group} / {target}**", ""]
                table(lines, arms)
                lines += [""]
    lines += ["", "## Reference UNKNOWN của SMS", "",
        "Không chấm đúng/sai trên nhãn UNKNOWN. Bảng dưới là phân bố quyết định, không phải độ chính xác từ chối.", "",
        "| Cấu hình | Mức đầu ra (lỗi được giữ là UNKNOWN) |", "|---|---|"]
    for arm, m in summary["metrics"]["sms"]["message_behavior"].items():
        lines.append(f"| {NAMES[arm]} | {m['reference_unknown_predictions']} |")
    lines += ["", "## Nguồn dẫn và tài nguyên", "",
              "| Cấu hình | Phản hồi ok/lỗi | Token ghi nhận | Trung vị (giây) | Phản hồi có nguồn dẫn khớp chữ |",
              "|---|---|---:|---:|---:|"]
    for arm in ARMS:
        lines.append(f"| {NAMES[arm]} | {summary['status_counts'][arm]} | {summary['usage'][arm]['total_tokens']} | "
                     f"{summary['timing'][arm]['median_ms'] / 1000:.2f} | {summary['citations'][arm]['responses_with_support']} |")
    lines += ["", "Nguồn dẫn theo dataset (số lượt có nguồn được cấp, số phản hồi trích nguồn khớp chữ):", "",
              "| Dataset | Cấu hình | Có nguồn được cấp | Phản hồi có trích nguồn |", "|---|---|---:|---:|"]
    for dataset, arms in extra["citation_by_dataset"].items():
        for arm in ("llm_rag", "llm_url_rag"):
            item = arms[arm]
            lines.append(f"| {dataset} | {NAMES[arm]} | {item['eligible_with_sources']} | {item['responses_with_literal_support']} |")
    lines += ["", "## Cặp có cùng payload", "",
              "Đầu vào giống nhau vẫn được gọi độc lập. Chênh đầu ra của các cặp này không chứng minh lợi ích/tác hại của thông tin URL hoặc RAG.", "",
              "| Dataset | So sánh | Cặp cùng payload | Khác ít nhất một chiều được chấm |", "|---|---|---:|---:|"]
    for dataset, comparisons in extra["identical_input_pairs"].items():
        for name, item in comparisons.items():
            lines.append(f"| {dataset} | {name} | {item['cases']} | {item['different_risk_outputs']} |")
    lines += ["", "Mã lỗi: `" + json.dumps(summary["error_codes"], ensure_ascii=False) + "`.", "",
        "## Giới hạn", "",
        "- Chỉ LLM và các cấu hình kết hợp có nhiệm vụ hành vi; model URL riêng chỉ chấm chiều URL có nhãn nguồn, không đem F1 URL so với F1 hành vi SMS.",
        "- Một lượt mỗi cấu hình; bootstrap nhóm không đo dao động sinh lại, sai nhãn AI hoặc lệch phân phối. Ngữ cảnh dùng chung URL và câu mẫu.",
        "- RAG rỗng thì payload của hai arm tương ứng giống nhau. Không URL thì thêm URL cũng không cung cấp thông tin mới; chênh lệch khi đó có thể do sinh ngẫu nhiên.",
        "- Dẫn nguồn khớp ID/đoạn chữ chưa chứng minh tài liệu liên quan hoặc hỗ trợ claim đúng. Chưa có relevance/rubric do người chấm độc lập cho lượt này.",
        "- Reference UNKNOWN báo riêng, không ép thành lành. Lỗi/UNKNOWN dương giảm Recall/F1; UNKNOWN âm vẫn làm giảm accuracy/coverage dù không tăng FP.",
        "- Không retry hoặc chọn phản hồi tốt nhất; token là usage được trả về, chưa đối chiếu hóa đơn. Thời gian là độ trễ gọi API, không phải ứng dụng đầu cuối.",
        "- Kho reputation là snapshot train cũ, chỉ kiểm tra lookup ở mốc 04/11. Không gửi nhãn nguồn của kho vào LLM hoặc coi chúng là điểm ML. "
        f"Trạng thái trên các URL xuất hiện trong tin: {summary['reputation_states']}; các URL lặp ở nhiều ngữ cảnh được đếm nhiều lần.",
        "- Không học hoặc chọn lại model/ngưỡng/tài liệu theo kết quả; chưa triển khai kết quả của prompt nghiên cứu vào ứng dụng.", "",
        "Số đếm nhóm đối chứng, baseline hằng số, bootstrap và toàn bộ summary có trong `summary.json`. Các ca bất đồng có trong `cases_to_review.json`."]
    return "\n".join(lines) + "\n"


def chart(summary, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    groups = [(d, t) for d, targets in summary["metrics"].items() for t in targets]
    labels = ["SMS\nmessage behavior", "URL contexts\nURL risk", "URL contexts\nmessage behavior", "URL contexts\naction risk"]
    fig, axes = plt.subplots(1, 3, figsize=(17, 5), constrained_layout=True)
    colors = ("#0f766e", "#2563eb", "#d97706", "#7c3aed")
    x = np.arange(len(groups))
    for axis, key, title in zip(axes, ("f1", "false_positive_rate", "coverage"), ("Positive-class F1", "False positive rate", "Coverage")):
        for i, (arm, color) in enumerate(zip(ARMS, colors)):
            values = [100 * summary["metrics"][d][t][arm][key] for d, t in groups]
            axis.bar(x + (i - 1.5) * .2, values, width=.19, label=NAMES[arm], color=color)
        axis.set_ylim(0, 105); axis.set_xticks(x, labels, fontsize=8); axis.set_title(title); axis.set_ylabel("%")
        axis.grid(axis="y", alpha=.2); axis.set_axisbelow(True)
    axes[0].legend(fontsize=8, loc="lower left")
    fig.suptitle("DEV diagnostic | one generation per arm | AI SMS labels + authored contexts\nErrors/UNKNOWN retained; datasets and targets scored separately", fontsize=13)
    fig.savefig(out / "comparison.png", dpi=160); fig.savefig(out / "comparison.svg"); plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("Choose a new report directory; preserve previous outputs.")
    config, cases, prepared, records, lookup, summary = verify(args.run)
    extra = augment(cases, prepared, lookup, summary, config=config)
    args.out.mkdir(parents=True)
    write_json(args.out / "summary.json", {"configuration": config, "results": summary, **extra})
    review = []
    for c in cases:
        levels = {a: {t: level(lookup[(c["id"], a)], t) for t in TARGETS} for a in ARMS}
        if any(c["targets"][t] is not None and prediction(values[t]) != c["targets"][t] for values in levels.values() for t in TARGETS):
            review.append({**c, "outcomes": levels})
    write_json(args.out / "cases_to_review.json", review)
    (args.out / "report.md").write_text(markdown(config, summary, extra), encoding="utf-8")
    chart(summary, args.out)
    write_json(args.out / "verification.json", {"verified": True, "created_at": datetime.now(timezone.utc).isoformat(),
        "provider_attempts": len(records), "cases": len(cases), "metrics": "independent scikit-learn confusion matrix and P/R/F1",
        "reporter_sha256": sha(__file__), "metric_checker_sha256": sha(ROOT / "scripts/evaluation/report_url_context.py"),
        "input_hashes": {n: sha(args.run / n) for n in ("execution.json", "cases.jsonl", "prepared.json", "predictions.jsonl", "attempts.jsonl", "summary.json")},
        "semantic_source_support_verified": False, "human_gold": False})
    print(json.dumps({"report": str(args.out / "report.md"), "verified": True, "provider_attempts": len(records)}))


if __name__ == "__main__":
    main()
