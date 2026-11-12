"""Register only unattempted requests after a stopped connection-only pilot.

The parent stays immutable. A combined report retains all parent errors and
checks that the child never sends a key already attempted in the parent.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evaluation.data.sms import read_jsonl, sha, write_json, write_jsonl
from evaluation.messages import compact_pilot as pilot


def prepare(parent, out):
    parent, out = Path(parent).resolve(), Path(out).resolve()
    if out.exists():
        raise ValueError("Choose a fresh continuation directory.")
    pilot.verify(parent)
    config, requests = pilot.load(parent)
    attempts, records = pilot.checkpoints(parent, config)
    summary = json.loads((parent / "summary.json").read_text())
    if (summary["state"] != "stopped_by_gate" or not records or set(attempts) != set(records)
            or any(r.get("http_status") is not None or r.get("transport_error") != "CONNECTION_ERROR" for r in records.values())):
        raise ValueError("Continuation requires a stopped connection-only run, with every attempt accounted for.")
    pending = [row for key, row in requests.items() if key not in attempts]
    if not pending:
        raise ValueError("There are no unattempted requests.")
    out.mkdir(parents=True)
    write_jsonl(out / "requests.jsonl", pending)
    child = deepcopy(config)
    child.update(registered_at=pilot.now(), max_attempts=len(pending),
        threads=len({r["case_id"] for r in pending}), unique_inputs=len({r["text"] for r in pending}),
        requests_sha256=sha(out / "requests.jsonl"),
        schedule=[item for item in config["schedule"] if (item["pack"], item["key"]) not in attempts],
        selection="All unattempted parent requests after a connection-only stop; never replace prior errors.",
        parent_run={"path": str(parent), "attempts_retained_as_errors": len(attempts),
            "files_sha256": {name: sha(parent / name) for name in pilot.SEALED}},
        limitations=config["limitations"] + " This is the unattempted subset only; use the combined report for the full registered denominator.")
    child["source_files_sha256"][str(Path(__file__).relative_to(ROOT))] = sha(Path(__file__))
    write_json(out / "execution.json", child)
    return {"requests_prepared": len(pending), "prior_errors_retained": len(attempts), "total_original_budget": config["max_attempts"], "API_calls": 0}


def report(out):
    out = Path(out).resolve()
    pilot.verify(out)
    child, child_requests = pilot.load(out)
    parent = Path(child["parent_run"]["path"])
    for name, expected in child["parent_run"]["files_sha256"].items():
        if sha(parent / name) != expected:
            raise ValueError("Parent run changed.")
    pilot.verify(parent)
    original, original_requests = pilot.load(parent)
    prior_attempts, prior_records = pilot.checkpoints(parent, original)
    child_attempts, child_records = pilot.checkpoints(out, child)
    expected_pending = set(original_requests) - set(prior_attempts)
    if set(child_requests) != expected_pending or set(child_attempts) & set(prior_attempts):
        raise ValueError("Continuation resends or omits original requests.")
    if any(row != original_requests[key] for key, row in child_requests.items()):
        raise ValueError("A continued request differs from its original registration.")
    combined = {**prior_records, **child_records}
    state = "complete" if len(combined) == original["max_attempts"] else "incomplete"
    summary = pilot.summarize(original, original_requests, combined, state)
    summary["continuation"] = {"parent_attempts": len(prior_attempts), "new_attempts": len(child_attempts),
        "prior_errors_retained": len(prior_records), "resent_keys": 0}
    write_json(out / "combined_summary.json", summary)
    lines = ["# Pilot v5/v6.1 — kết quả gộp, giữ nguyên lỗi kết nối", "",
        f"Tổng {len(combined)}/{original['max_attempts']} attempt: {len(prior_records)} lỗi kết nối ở lượt đầu, "
        f"{len(child_records)} kết quả ở phần chưa thử. Không gửi lại hoặc thay kết quả cũ.", "",
        "| Profile | Hợp lệ / toàn bộ | Lỗi kết nối | Bị cắt | Token provider ghi nhận |",
        "|---|---:|---:|---:|---:|"]
    for profile, values in summary["profiles"].items():
        lines.append(f"| {profile} | {values['valid']}/{values['expected']} | {values['errors'].get('CONNECTION_ERROR', 0)} | "
            f"{values['errors'].get('OUTPUT_TRUNCATED', 0)} | {values['usage']['total_tokens']} |")
    lines += ["", f"Cặp hợp lệ cả hai: {summary['both_valid_pairs']}; khác nhãn: {summary['different_label_pairs']}.",
        "Latency gộp chứa attempt lỗi rất nhanh; xem summary riêng của continuation khi đọc thời gian phản hồi có kết nối.",
        "Không có nhãn độc lập; không tính Accuracy/F1. Usage của lỗi kết nối chưa biết, không xem là token được provider xác nhận bằng 0.",
        original["limitations"]]
    (out / "combined_report.md").write_text("\n".join(lines) + "\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "report"])
    parser.add_argument("--parent", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare" and args.parent is None:
        parser.error("prepare requires --parent")
    result = prepare(args.parent, args.out) if args.command == "prepare" else report(args.out)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
