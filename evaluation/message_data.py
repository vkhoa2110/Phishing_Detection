"""Prepare source-labelled Vietnamese SMS for blind human annotation.

No LLM, training, malicious-URL requests, or phishing-label inference occurs.
The upstream positive label combines spam and scams and is NOT our gold label.
"""
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import re
import unicodedata
from urllib.parse import urlsplit

from app.privacy import redact
from app.urls import extract_urls

REPOSITORY = "trannguyenthaituan/vietnamese_sms_dataset"
REVISION = "a90e2bd7e8df2376939658075ba8094dcee488ad"
SOURCE_URL = "https://huggingface.co/datasets/" + REPOSITORY
FIELDS = ["id", "text", "label", "category", "evidence_quote", "notes", "rater_id"]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_jsonl(path):
    return [json.loads(s) for s in Path(path).read_text(encoding="utf-8").splitlines() if s.strip()]


def write_jsonl(path, rows):
    Path(path).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def normal(text):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


def clean_message(text):
    text, fields = redact(normal(text))
    # Upstream OTP values are sometimes still literal. Mask short numeric
    # identifiers too; document this transformation rather than claim raw PII-free.
    text, count = re.subn(r"(?<!\w)\d{4,}(?!\w)", "[NUMBER]", text)
    if count:
        fields.append("Dãy số từ 4 chữ số (bổ sung cho dữ liệu SMS)")
    return text, sorted(set(fields))


def spreadsheet_cell(value):
    """Prevent formula execution when a public message is opened in a spreadsheet."""
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value


def annotation_sheet(path, items):
    with Path(path).open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for item in items:
            writer.writerow({"id": item["id"], "text": spreadsheet_cell(item["text"])})


def template(text):
    """Campaign hint, not a label: replace URL and variable tokens, retain words."""
    from app.urls import URL_PATTERN
    text = URL_PATTERN.sub(" URL ", text.casefold())
    text = re.sub(r"\[[^\]]+\]|\d+", " VALUE ", text)
    return re.findall(r"\w+", text)


def hints(text):
    ascii_text = "".join(c for c in unicodedata.normalize("NFD", text.casefold()) if unicodedata.category(c) != "Mn").replace("đ", "d")
    tags = []
    for name, terms in (("authentication", ("otp", "mat khau", "xac thuc", "dang nhap")),
                        ("money", ("chuyen khoan", "thanh toan", "vay", "so du", "nap tien", "phi")),
                        ("deadline", ("het han", "khoa", "ngay", "phut", "khan cap")),
                        ("promotion", ("khuyen mai", "uu dai", "tang", "trung thuong"))):
        if any(t in ascii_text for t in terms):
            tags.append(name)
    return tags or ["other"]


def group_candidates(items, near_threshold=.85):
    """Conservative connected components: same domain OR near-duplicate words.

    Whole registrable domains are grouped, even for legitimate services or
    shorteners. This can over-group unrelated campaigns; it avoids splitting
    them optimistically. Dates remain source dates, not verified attack times.
    """
    import tldextract
    suffixes = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)
    parent = list(range(len(items)))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    def union(a, b):
        a, b = find(a), find(b)
        if a != b:
            parent[max(a, b)] = min(a, b)
    domains, templates, words = {}, {}, []
    for i, item in enumerate(items):
        hosts = set()
        for url in item["urls"]:
            parsed = urlsplit(url if "://" in url else "https://" + url)
            host = (parsed.hostname or "").casefold()
            extracted = suffixes(host)
            domain = extracted.top_domain_under_public_suffix or host
            if domain:
                hosts.add(domain)
                if domain in domains:
                    union(i, domains[domain])
                domains[domain] = i
        item["domains"] = sorted(hosts)
        token_list = template(item["text"])
        signature = " ".join(token_list)
        if signature in templates:
            union(i, templates[signature])
        templates[signature] = i
        words.append(set(token_list))
    # ~2.6k messages: length pruning keeps an exact all-pairs comparison cheap.
    for i, left in enumerate(words):
        if not left:
            continue
        for j in range(i):
            right = words[j]
            if min(len(left), len(right)) < near_threshold * max(len(left), len(right)):
                continue
            if len(left & right) / len(left | right) >= near_threshold:
                union(i, j)
    members = defaultdict(list)
    for i, item in enumerate(items):
        members[find(i)].append(item)
    for cluster in members.values():
        fingerprint = hashlib.sha256("\n".join(sorted(c["id"] for c in cluster)).encode()).hexdigest()[:16]
        for item in cluster:
            item["group_id"] = "sms-group-" + fingerprint
    return {"groups": len(members), "largest_group": max(map(len, members.values()), default=0),
            "method": "connected components: identical template, token-set Jaccard >=0.85, or shared registrable domain; bundled PSL, no network"}


def source_candidates(raw):
    raw = Path(raw)
    provenance = json.loads((raw / "download.json").read_text())
    if provenance["repo"] != REPOSITORY or provenance["revision"] != REVISION:
        raise ValueError("Unexpected dataset revision.")
    required = {"README.md", "QUICKSTART_GUIDE.md", "full_dataset.csv", "train.csv", "test.csv"}
    if set(provenance["files"]) != required:
        raise ValueError("Incomplete raw source provenance.")
    for name, info in provenance["files"].items():
        if name not in {"README.md", "QUICKSTART_GUIDE.md", "full_dataset.csv", "train.csv", "test.csv"} or sha(raw / name) != info["sha256"]:
            raise ValueError("Raw source hash mismatch.")
    with (raw / "full_dataset.csv").open(encoding="utf-8-sig", newline="") as f:
        original = list(csv.DictReader(f))
    seen_ids, merged, excluded = set(), {}, Counter()
    for source in original:
        if source["message_id"] in seen_ids or source["label"] not in {"0", "1"}:
            raise ValueError("Invalid source ID/label.")
        seen_ids.add(source["message_id"])
        text, fields = clean_message(source["message"])
        try:
            urls, invalid = extract_urls(text, "text")
        except ValueError:
            excluded["over_url_limit"] += 1
            continue
        if not text or len(text) > 8000 or invalid:
            excluded["invalid_or_overlength"] += 1
            continue
        key = normal(text).casefold()
        if key in merged:
            item = merged[key]
            item["source_ids"].append(source["message_id"])
            item["source_labels"].add(int(source["label"]))
            item["source_dates"].add(source["date"])
            continue
        merged[key] = {"id": "VN-SMS-" + hashlib.sha256(key.encode()).hexdigest()[:16],
                       "text": text, "source_ids": [source["message_id"]], "source_labels": {int(source["label"])},
                       "source_dates": {source["date"]}, "urls": urls, "masked_fields": fields,
                       "sampling_hints": hints(text)}
    items = []
    for item in merged.values():
        if len(item["source_labels"]) != 1:
            excluded["conflicting_after_redaction"] += 1
            continue
        item["source_label"] = next(iter(item.pop("source_labels")))
        item["source_dates"] = sorted(item["source_dates"])
        items.append(item)
    originals = {}
    for split in ("train", "test"):
        with (raw / (split + ".csv")).open(encoding="utf-8-sig", newline="") as f:
            originals[split] = {r["message"] for r in csv.DictReader(f)}
    audit = {"raw_records": len(original), "unique_raw_texts": len({r['message'] for r in original}),
             "upstream_exact_train_test_overlap": len(originals["train"] & originals["test"]),
             "deduplicated_usable": len(items), "excluded": dict(excluded),
             "source_labels": dict(Counter(i["source_label"] for i in items)),
             "upstream_claim": "Authors describe real, contributor-consented, anonymized SMS; not independently verified here.",
             "source_label_semantics": "0=legitimate; 1=spam/scam combined, NOT a phishing gold label"}
    return sorted(items, key=lambda i: i["id"]), audit, provenance


def prepare(raw, out, seed=20261028):
    out = Path(out)
    if out.exists():
        raise ValueError("Choose a fresh annotation directory; existing selections are immutable.")
    items, audit, provenance = source_candidates(raw)
    audit["grouping"] = group_candidates(items)
    # Reserve entire components before selecting messages. No model predictions
    # or outcome-dependent 'hardness' filtering are used.
    groups = sorted({i["group_id"] for i in items})
    rng = random.Random(seed)
    rng.shuffle(groups)
    assignment = {g: "dev" if i < round(.4 * len(groups)) else "test" for i, g in enumerate(groups)}
    selected = []
    for split, quota in (("dev", 40), ("test", 60)):
        for label in (0, 1):
            pool = [i for i in items if assignment[i["group_id"]] == split and i["source_label"] == label]
            rng.shuffle(pool)
            # Round-robin coarse, observable strata. These are NOT truth labels.
            buckets = defaultdict(list)
            for item in pool:
                buckets[(bool(item["urls"]), item["sampling_hints"][0])].append(item)
            chosen, per_group = [], Counter()
            while len(chosen) < quota:
                progress = False
                for key in sorted(buckets):
                    while buckets[key] and per_group[buckets[key][-1]["group_id"]] >= 2:
                        buckets[key].pop()
                    if buckets[key] and len(chosen) < quota:
                        item = buckets[key].pop()
                        per_group[item["group_id"]] += 1
                        chosen.append({**item, "split": split})
                        progress = True
                if not progress:
                    raise ValueError(f"Insufficient independent groups for {split}, source label {label}; do not silently relax the grouping or cap.")
            selected.extend(chosen)
    selected.sort(key=lambda i: i["id"])
    dev_domains = {d for i in selected if i["split"] == "dev" for d in i["domains"]}
    test_domains = {d for i in selected if i["split"] == "test" for d in i["domains"]}
    assert not dev_domains & test_domains
    assert len(selected) == 200
    out.mkdir(parents=True)
    blind_items = [{k: v for k, v in item.items() if k != "source_label"} for item in selected]
    write_jsonl(out / "items.jsonl", blind_items)
    write_jsonl(out / "source_labels.jsonl", [{"id": i["id"], "source_label": i["source_label"]} for i in selected])
    annotation_sheet(out / "annotator_a.csv", blind_items)
    annotation_sheet(out / "annotator_b.csv", blind_items)
    audit.update(selected=200, dev=80, test=120, selected_with_url=sum(bool(i["urls"]) for i in selected),
                 selected_groups=len({i["group_id"] for i in selected}), cross_split_domains=0)
    write_json(out / "audit.json", audit)
    manifest = {"version": "vn-sms-review-2.0", "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "awaiting_two_independent_raters", "source_url": SOURCE_URL, "source_revision": REVISION,
        "source_license": "CC-BY-4.0", "upstream_files": provenance["files"], "seed": seed,
        "selection": "200 total; dev 80/test 120; balanced by UPSTREAM labels only; max two per component per source-label stratum",
        "grouping": audit["grouping"]["method"], "near_duplicate_threshold": .85,
        "date_policy": "retain author-provided dates; no claim of a chronological split or verified event timestamps",
        "transformations": "whitespace/NFC normalization, rule redaction plus digit runs >=4, exact dedup after redaction, conservative grouping, sampling; no generated message text or model-assigned labels",
        "source_labels_are_gold": False,
        "files": {name: sha(out / name) for name in ("items.jsonl", "source_labels.jsonl", "audit.json")}}
    write_json(out / "manifest.json", manifest)
    (out / "ATTRIBUTION.md").write_text(
        "# Nguồn và giấy phép\n\nVietnamese SMS Dataset with Quality Assurance — Tran Nguyen Thai Tuan, "
        "Le Hoang Khang, Nguyen Minh Tai, Nguyen Van Thang, Mai Hoang Dinh (2026).\n\n"
        f"Nguồn: {SOURCE_URL}\n\nRevision: `{REVISION}`. License: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).\n\n"
        "Bản thích nghi của PhishLens: chuẩn hóa, che bổ sung thông tin, khử trùng, nhóm và chọn 200 bản ghi để gán nhãn lại. "
        "Tin nhắn không do PhishLens sinh. Nhãn nguồn gộp spam/scam, chưa dùng làm nhãn phishing. "
        "Các tuyên bố về thu thập/đồng thuận là của tác giả bộ nguồn, chưa được dự án xác minh độc lập.\n", encoding="utf-8")
    return audit
