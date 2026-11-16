"""Distinguish a cohort change from relabeling the same message; no inference."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import re
import unicodedata

from evaluation.data.sms import read_jsonl, sha, write_json


def normalized(text):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip().casefold()


def compare(old, new):
    left, right = {r["id"]: r for r in old}, {r["id"]: r for r in new}
    if len(left) != len(old) or len(right) != len(new): raise ValueError("Duplicate case IDs.")
    for row in old + new:
        label = row["label"]
        if label is not None and (type(label) is not int or label not in {0, 1}):
            raise ValueError("Expected binary or UNKNOWN reference.")
    rows = []
    for key in sorted(set(left) | set(right)):
        a, b = left.get(key), right.get(key)
        relation = "new_cohort_only" if a is None else "old_cohort_only" if b is None else (
            "same_message" if normalized(a["text"]) == normalized(b["text"]) else "same_id_text_differs")
        label_text = lambda row: "N/A" if row is None else "UNKNOWN" if row["label"] is None else str(row["label"])
        rows.append({"id": key, "old_label": label_text(a), "new_label": label_text(b),
            "relation": relation, "label_changed_on_same_text": relation == "same_message" and a["label"] != b["label"],
            "review_notes": ""})
    counts = lambda records: dict(Counter("UNKNOWN" if r["label"] is None else str(r["label"]) for r in records))
    groups = lambda records: {r["group_id"] for r in records if r.get("group_id")}
    summary = {"old_cases": len(old), "new_cases": len(new), "old_labels": counts(old), "new_labels": counts(new),
        "shared_IDs": len(set(left) & set(right)),
        "shared_normalized_texts": len({normalized(r["text"]) for r in old} & {normalized(r["text"]) for r in new}),
        "shared_group_IDs": len(groups(old) & groups(new)),
        "label_changes_on_same_text": sum(r["label_changed_on_same_text"] for r in rows),
        "same_ID_different_text_needs_review": sum(r["relation"] == "same_id_text_differs" for r in rows),
        "provider_calls": 0, "reserve_inference": False}
    return summary, rows


def run(old_binary, old_unknown, new_cases, new_labels, out):
    out = Path(out)
    if out.exists(): raise ValueError("Preserve prior audits and manual notes.")
    old = read_jsonl(old_binary) + read_jsonl(old_unknown)
    cases, labels = read_jsonl(new_cases), read_jsonl(new_labels)
    by_id = {r["id"]: r for r in labels}
    if len(by_id) != len(labels) or set(by_id) != {r["id"] for r in cases}:
        raise ValueError("New cohort and label inventories differ.")
    new = [{**r, "label": by_id[r["id"]]["label"]} for r in cases]
    summary, rows = compare(old, new)
    out.mkdir(parents=True)
    write_json(out / "summary.json", summary)
    with (out / "by_id_review.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    write_json(out / "manifest.json", {"inputs": {str(Path(p).resolve()): sha(p) for p in
        (old_binary, old_unknown, new_cases, new_labels)}, "audit_source_sha256": sha(__file__)})
    (out / "report.md").write_text(
        "# Đối chiếu cohort và nhãn theo ID\n\n"
        f"Hai nhóm có {summary['old_cases']} và {summary['new_cases']} mẫu; "
        f"trùng {summary['shared_IDs']} ID, {summary['shared_normalized_texts']} nội dung chuẩn hóa và "
        f"{summary['shared_group_IDs']} group ID. Số đổi nhãn trên cùng ID/nội dung: {summary['label_changes_on_same_text']}.\n\n"
        "`by_id_review.csv` giữ cả ID chỉ có ở một cohort; nhãn không tồn tại để N/A, không bịa lý do đổi nhãn. "
        "Cột review_notes để người rà soát bổ sung. Nhãn AI không chứng nhận rủi ro toàn thông điệp hay URL. "
        "Các cohort vẫn có thể cùng nguồn công khai; ID/group khác không tự chứng minh khác campaign hoặc nguồn độc lập. "
        "Không gọi provider hoặc đọc mẫu reserve trong phép đối chiếu này.\n")
    return summary


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("old-binary", "old-unknown", "new-cases", "new-labels", "out"):
        p.add_argument("--" + name, type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(run(a.old_binary, a.old_unknown, a.new_cases, a.new_labels, a.out), indent=2))
