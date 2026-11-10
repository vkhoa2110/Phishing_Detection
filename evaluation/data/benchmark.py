"""Prepare a preregistered evaluation/review pack without calling any provider.

The external SMS, authored challenges and retrieval judgments remain separate.
AI references are explicitly provisional and never satisfy the human-gold gate.
"""
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import re
import zipfile

from app.core.settings import ROOT, Settings
from evaluation.data.challenges import candidates
from evaluation.data.sms import annotation_sheet, read_jsonl, sha, spreadsheet_cell, write_json, write_jsonl
from evaluation.data.review import assert_split_isolation, workspace_items

SEED = 20261102
RELEVANCE_FIELDS = ["query_id", "document_id", "query", "document_text", "title", "publisher",
                    "source_url", "scope", "published_at", "grade", "support_quote", "notes", "rater_id"]
RUBRIC = {
    "label_1": "Có căn cứ cụ thể cho hành vi lừa dối nhằm lấy bí mật, tiền hoặc quyền điều khiển. Phải trích nguyên văn. Tự xưng thương hiệu hoặc đuôi tên miền lạ riêng lẻ chưa đủ.",
    "label_0": "Không thấy yêu cầu lừa dối trong phạm vi thông điệp: thông báo, quảng cáo, quy trình được mô tả, cảnh báo giáo dục. Không xác nhận danh tính hoặc URL an toàn.",
    "label_UNKNOWN": "Thiếu thông tin quyết định; người nhận không biết có tự khởi tạo yêu cầu hay chưa; thông tin quan trọng bị che; không thể kết luận chỉ từ danh tính tự xưng hoặc URL.",
    "injection": "Câu ra lệnh cho AI là dữ liệu không đáng tin; đánh giá hành vi được yêu cầu ở nội dung thực. Không tự coi mọi mẫu chứa injection là phishing.",
    "forbidden_shortcuts": ["spam = phishing", "có OTP = phishing", "có URL = phishing", "nhãn nguồn = gold", "đồng thuận AI = đồng thuận người"],
    "evidence": "Nhãn 1 cần quote hành vi đúng nguyên văn; mọi nhãn cần lý do. Cho phép UNKNOWN; không ép số lượng hai lớp cân bằng.",
}
RELEVANCE_RUBRIC = {
    "0": "Không giúp phân tích hoặc hướng dẫn xác minh cho nội dung được hỏi.",
    "1": "Cùng chủ đề hoặc có hướng dẫn chung nhưng không trực tiếp hỗ trợ dấu hiệu/claim trong ngữ cảnh cụ thể.",
    "2": "Trực tiếp hỗ trợ ít nhất một dấu hiệu hoặc bước xác minh phù hợp ngữ cảnh; không vượt đơn vị, thời điểm hay phạm vi nguồn. Cần quote nguồn và lý do.",
    "UNKNOWN": "Người chấm chưa đủ căn cứ; không đổi thành không liên quan.",
    "query_task": "Tài liệu này có hỗ trợ phân tích dấu hiệu và bước xác minh của tin nhắn không? Không yêu cầu tài liệu chứng minh người gửi thật/giả.",
    "no_match": "Chỉ kết luận không có nguồn trực tiếp khi toàn bộ corpus được chấm và không có grade 2 hoặc UNKNOWN.",
}


def sheet(path, rows, fields):
    with Path(path).open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows({k: spreadsheet_cell("" if row.get(k) is None else str(row.get(k, ""))) for k in fields} for row in rows)


def shuffled(rows, salt):
    rows = list(rows)
    random.Random(SEED + salt).shuffle(rows)
    return rows


def selection_workspace(out, items, source, kind):
    out.mkdir(parents=True)
    assert_split_isolation(items)
    write_jsonl(out / "items.jsonl", items)
    # No model/source labels are copied into the new workspace.
    write_json(out / "audit.json", {"count": len(items), "splits": dict(Counter(i["split"] for i in items)),
        "with_url": sum(bool(i["urls"]) for i in items), "groups": len({i["group_id"] for i in items}),
        "source_kind": kind, "labels_present": False})
    write_json(out / "manifest.json", {**source, "version": "objective-review-1.0",
        "status": "awaiting_two_independent_raters", "source_labels_are_gold": False, "source_kind": kind,
        "grouping": "Inherited SMS domain/template components or disjoint authored scenario families; no re-split based on outcomes.",
        "files": {name: sha(out / name) for name in ("items.jsonl", "audit.json")}})
    for side, salt in (("a", 11), ("b", 29)):
        annotation_sheet(out / f"annotator_{side}.csv", shuffled(items, salt))


def ai_reference(out, sms, challenge, notes_path):
    """Export a declared single-assistant reference, never two invented raters."""
    notes = json.loads(Path(notes_path).read_text(encoding="utf-8"))
    if notes["status"] != "ai_reference_unverified" or len(notes["annotations"]) != len(sms):
        raise ValueError("Incomplete provisional reference annotations.")
    reference = {row[0]: row[1:] for row in notes["annotations"]}
    if set(reference) != set(range(1, len(sms) + 1)):
        raise ValueError("Duplicate or missing reference indices.")
    if sha(ROOT / "data/annotation/vn_sms_v2/items.jsonl") != notes["selection_sha256"]:
        raise ValueError("Reference notes target a different frozen SMS selection.")
    original = read_jsonl(ROOT / "data/annotation/vn_sms_v2/items.jsonl")
    if [i["id"] for i in sms] != [i["id"] for i in original]:
        raise ValueError("Reference indices do not match SMS IDs/order.")
    for dataset, rows in (("sms", sms), ("challenge", challenge)):
        exported = []
        for number, item in enumerate(rows, 1):
            if dataset == "sms":
                label, category, reason = reference[number]
            else:
                variant = item["variant"]
                label = None if variant == "unclear" else 1 if variant in {"request", "request_injection"} else 0
                category = "insufficient_context" if label is None else "impersonation" if label else "educational_quote" if variant == "educational_quote" else "legitimate_workflow"
                reason = ("Tình huống do trợ lý soạn; ngữ cảnh cố ý thiếu thông tin quyết định." if label is None else
                          "Tình huống do trợ lý soạn có yêu cầu lấy bí mật/tiền/quyền truy cập hoặc ngăn xác minh; câu injection không được dùng làm chỉ dẫn." if label else
                          "Tình huống do trợ lý soạn mô tả quy trình tự khởi tạo/thận trọng hoặc trích dẫn giáo dục; không làm theo lệnh injection.")
            label = None if label == "UNKNOWN" else label
            if label not in (None, 0, 1) or not str(reason).strip():
                raise ValueError("Invalid reference label/rationale.")
            exported.append({**item, "label": label, "category": category, "rationale": reason,
                "evidence_quotes": [item["text"]] if label == 1 else [],
                "annotation_status": "ai_reference_unverified", "rater_ids": [],
                "reference_level": "UNKNOWN" if label is None else "ALARM" if label else "LOW"})
        target = out / "provisional_reference" / dataset
        target.mkdir(parents=True)
        for split in ("dev", "test"):
            write_jsonl(target / f"{split}.jsonl", [i for i in exported if i["split"] == split and i["label"] is not None])
            write_jsonl(target / f"{split}_unknown.jsonl", [i for i in exported if i["split"] == split and i["label"] is None])
        sheet(target / "review.csv", [{"id": i["id"], "split": i["split"],
            "label": "UNKNOWN" if i["label"] is None else i["label"], "text": i["text"],
            "category": i["category"], "rationale": i["rationale"],
            "evidence_quote": " | ".join(i["evidence_quotes"]), "annotation_status": i["annotation_status"]} for i in exported],
            ["id", "split", "label", "text", "category", "rationale", "evidence_quote", "annotation_status"])
        write_json(target / "manifest.json", {"status": "ai_reference_unverified", "rater_ids": [],
            "version": "objective-ai-reference-1.0", "upstream_labels_used_as_gold": False,
            "method": notes["method"] if dataset == "sms" else "Labels follow assistant-authored design roles; circular by construction, challenge only, not independent accuracy.",
            "notes_sha256": sha(notes_path), "source_kind": rows[0]["source_kind"],
            "counts": {split: dict(Counter("UNKNOWN" if i["label"] is None else str(i["label"]) for i in exported if i["split"] == split)) for split in ("dev", "test")},
            "files": {p.name: sha(p) for p in sorted(target.iterdir()) if p.is_file()},
            "limitations": "AI annotations have errors and bias; cannot prove model accuracy. Binary subsets may contain very few phishing positives. No identity verification or adjudication occurred."})


def prepare(out, sms_workspace=ROOT / "data/annotation/vn_sms_v2", corpus=ROOT / "data/knowledge/corpus_v1/documents.jsonl"):
    out, corpus = Path(out), Path(corpus)
    if out.exists():
        raise ValueError("Choose a fresh pack directory; never overwrite an evaluation protocol.")
    sms, source = workspace_items(sms_workspace)
    if len(sms) != 200:
        raise ValueError("Expected the frozen 200-SMS selection.")
    # Keep the original selection immutable, repair a literal level-2 password
    # in this derived version before any future provider call.
    sms = [{**i, "text": re.sub(r"(?i)(\bMKC2\)?\s*(?:là|la|:|=)\s*)[a-z0-9]{4,}", r"\1[SECRET]", i["text"]),
            "source_kind": "external_sms_authors_report_real_not_independently_verified"} for i in sms]
    challenge = candidates()
    groups = shuffled(sorted({i["group_id"] for i in challenge}), 7)
    dev_groups = set(groups[:8])
    challenge = [{**i, "split": "dev" if i["group_id"] in dev_groups else "test"} for i in challenge]
    assert_split_isolation(sms)
    assert_split_isolation(challenge)
    if {d for i in sms for d in i["domains"]} & {d for i in challenge for d in i["domains"]}:
        raise ValueError("Authored domains overlap external SMS domains.")
    documents = read_jsonl(corpus)
    if len({d["id"] for d in documents}) != len(documents):
        raise ValueError("Duplicate corpus document IDs.")
    queries = []
    for split in ("dev", "test"):
        # Sample by observable source/split only, before any relevance/model outcome.
        for name, rows, count in (("sms", sms, 8), ("challenge", challenge, 4)):
            pool = sorted((i for i in rows if i["split"] == split), key=lambda i: i["id"])
            chosen = shuffled(pool, 43 if split == "dev" else 47)[:count]
            queries.extend({"id": i["id"], "text": i["text"], "split": split,
                            "group_id": i["group_id"], "source_kind": name} for i in chosen)
    if {i["group_id"] for i in queries if i["split"] == "dev"} & {i["group_id"] for i in queries if i["split"] == "test"}:
        raise ValueError("Retrieval query groups overlap.")
    settings = Settings()
    files_to_lock = sorted((ROOT / "app").rglob("*.py")) + [ROOT / "evaluation" / name for name in
        ("messages/ablation.py", "common/metrics.py", "data/review.py", "data/sms.py", "data/benchmark.py", "data/challenges.py", "rag/review.py", "messages/objective.py")]
    protocol = {
        "version": "objective-evaluation-1.0", "created_at": datetime.now(timezone.utc).isoformat(), "seed": SEED,
        "status": "inputs_frozen_reference_labels_not_gold",
        "primary_dataset": {"source": source["source_url"], "revision": source["source_revision"],
                            "count": 200, "dev": 80, "test": 120, "source_manifest_sha256": sha(Path(sms_workspace) / "manifest.json")},
        "secondary_dataset": {"kind": "assistant_authored_challenge", "count": len(challenge),
                              "families": len(groups), "split_by": "family", "pooled_with_primary": False},
        "arms": ["llm_only", "llm_url", "llm_rag", "llm_url_rag"],
        "prompt_profile": "message-v3", "fusion_policy": "separate", "model": settings.llm_model,
        "endpoint": settings.endpoint, "max_tokens": 8192, "timeout_seconds": 90,
        "temperature": .1, "top_p": 1, "top_k": 40, "workers": 2,
        "primary_repetitions": 1, "optional_repetitions": "Register a new protocol before additional runs; report all repeats, never pick the best.",
        "max_primary_test_calls": 576,
        "primary_metrics": ["precision", "recall", "f1", "false_positive_rate", "coverage", "error_rate"],
        "unknown_policy": "Gold UNKNOWN is a separate set; predicted UNKNOWN on binary gold stays in recall/F1 denominator for positive cases. API errors are technical failures, not correct abstentions.",
        "baseline": ["always_alarm", "always_low"],
        "comparison": "Same messages, model, prompt profile, budget and redaction; no labels/source/tier/annotation passed to LLM. Report main SMS and authored challenge separately.",
        "statistics": "Report counts and paired differences; cluster-bootstrap by group_id for exploratory CIs; do not treat near-duplicates as independent or claim significance from best run.",
        "test_policy": "Dev only for prompt/threshold decisions. Test once after freeze. Never append test answers to RAG or drop difficult/failed cases.",
        "explanation": {"selection_before_outputs": True, "samples_per_split_per_dataset": 8,
                        "dimensions": ["correct_signals", "relevant_sources", "claim_supported", "appropriate_actions"],
                        "scale": [0, 1, 2], "source_dimensions_without_citation": None,
                        "blinding": "Hide arm, model and verdict label; disclose missing source information can partially reveal arm."},
        "retrieval": {"queries": len(queries), "corpus_documents": len(documents), "pairs_per_rater": len(queries) * len(documents),
                      "top_k": 3, "relevance_scale": [0, 1, 2, "UNKNOWN"], "strict_relevance": 2,
                      "metrics": ["hit_at_3", "precision_at_3", "precision_returned", "recall_at_3", "mrr_at_3", "ndcg_at_3", "no_match_rejection"],
                      "exhaustive": "All corpus documents per query, not only top hits from a favored retriever."},
        "human_review": "Two independent blinded raters; disagreements require a third declared adjudicator. No invented human identities.",
        "prior_exposure": "200 SMS previously received AI preliminary labels; selection was not based on classifier correctness. New AI reference judgments remain unverified; this is not a pristine external gold test.",
        "additional_redaction": "Mask literal MKC2/password-level-2 values in derived SMS text; original selection stays unchanged. Rule redaction does not guarantee complete PII removal.",
        "ai_reference_policy": "May be used for explicitly provisional diagnostic only. Not accepted by validate_gold. Do not call AI agreement objective accuracy.",
        "corpus_sha256": sha(corpus), "corpus_path": str(corpus.relative_to(ROOT) if corpus.is_relative_to(ROOT) else corpus),
        "runtime_files_sha256": {str(p.relative_to(ROOT)): sha(p) for p in files_to_lock},
        "frozen_artifacts": {},
    }
    for name, value in (("model_config", Path(settings.model_dir) / "config.json"),
                        ("url_model", Path(settings.model_dir) / "model.ubj"),
                        ("rag_manifest", Path(settings.rag_index_dir) / "manifest.json"),
                        ("rag_calibration", Path(settings.rag_index_dir) / "calibration.json")):
        path = value if value.is_absolute() else ROOT / value
        if not path.is_file():
            raise ValueError(f"Missing frozen artifact: {name}")
        protocol["frozen_artifacts"][name] = {"path": str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path), "sha256": sha(path)}
    index_dir = Path(settings.rag_index_dir)
    index_dir = index_dir if index_dir.is_absolute() else ROOT / index_dir
    index_manifest = json.loads((index_dir / "manifest.json").read_text(encoding="utf-8"))
    calibration = json.loads((index_dir / "calibration.json").read_text(encoding="utf-8"))
    if index_manifest.get("corpus_sha256") != sha(corpus) or calibration.get("index_manifest_sha256") != sha(index_dir / "manifest.json"):
        raise ValueError("Corpus, index and calibration must be the same frozen configuration.")

    out.mkdir(parents=True)
    selection_workspace(out / "classification/sms", sms, source, sms[0]["source_kind"])
    selection_workspace(out / "classification/challenge", challenge,
        {"source_url": "local:assistant-authored-challenges", "source_revision": "objective-challenge-1.0",
         "source_license": "Project-authored text; example domains only"}, challenge[0]["source_kind"])
    write_json(out / "protocol.json", protocol)
    write_json(out / "classification_rubric.json", RUBRIC)
    retrieval = out / "retrieval"
    retrieval.mkdir()
    write_jsonl(retrieval / "queries.jsonl", queries)
    write_jsonl(retrieval / "corpus.jsonl", documents)
    write_json(retrieval / "rubric.json", RELEVANCE_RUBRIC)
    pairs = [{"query_id": q["id"], "document_id": d["id"], "query": q["text"],
              "document_text": d["text"], "title": d["title"], "publisher": d["publisher"],
              "source_url": d["source_url"], "scope": d.get("scope") or d.get("context_note", ""),
              "published_at": d.get("published_at")} for q in queries for d in documents]
    write_jsonl(retrieval / "pairs.jsonl", pairs)
    for side, salt in (("a", 53), ("b", 59)):
        sheet(retrieval / f"annotator_{side}.csv", shuffled(pairs, salt), RELEVANCE_FIELDS)
    write_json(retrieval / "manifest.json", {"version": "retrieval-review-1.0", "status": "awaiting_independent_review",
        "files": {name: sha(retrieval / name) for name in ("queries.jsonl", "corpus.jsonl", "pairs.jsonl", "rubric.json")}})
    explain = []
    for name, rows in (("sms", sms), ("challenge", challenge)):
        for split in ("dev", "test"):
            explain.extend({"id": i["id"], "dataset": name, "split": split} for i in
                           shuffled(sorted((r for r in rows if r["split"] == split), key=lambda r: r["id"]), 61)[:8])
    write_jsonl(out / "explanation_selection.jsonl", explain)
    write_json(out / "explanation_rubric.json", {
        "status": "awaiting_predictions_not_scored", "dimensions": protocol["explanation"]["dimensions"],
        "0": "Sai, bịa đặt, vượt nguồn hoặc hành động nguy hiểm.", "1": "Đúng một phần hoặc còn chung chung.",
        "2": "Đúng, cụ thể và phù hợp ngữ cảnh/phạm vi nguồn.", "source_dimensions_without_citation": None,
        "policy": "Blind arm/model/risk label; same preselected sample IDs across arms; errors are missing outputs, not score zero or successful abstention. Report each dimension and denominator, no arbitrary total score."})
    ai_reference(out, sms, challenge, ROOT / "data/evaluation/objective_sms_reference_notes_v1.json")
    (out / "README.md").write_text(PACK_README, encoding="utf-8")
    for side in ("a", "b"):
        with zipfile.ZipFile(out / f"reviewer_{side}.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, path in (("sms.csv", out / f"classification/sms/annotator_{side}.csv"),
                               ("challenge.csv", out / f"classification/challenge/annotator_{side}.csv"),
                               ("retrieval.csv", retrieval / f"annotator_{side}.csv")):
                archive.write(path, name)
            archive.writestr("README.md", REVIEWER_README)
            archive.writestr("classification_rubric.json", json.dumps(RUBRIC, ensure_ascii=False, indent=2))
            archive.writestr("retrieval_rubric.json", json.dumps(RELEVANCE_RUBRIC, ensure_ascii=False, indent=2))
    # ZIPs are local distribution conveniences, not required source artifacts.
    immutable = [p for p in out.rglob("*") if p.is_file() and not p.name.startswith("annotator_") and p.suffix != ".zip"]
    write_json(out / "manifest.json", {"version": "objective-pack-1.0", "status": "awaiting_reference_or_human_review",
        "files": {str(p.relative_to(out)): sha(p) for p in sorted(immutable)}})
    return verify(out)


def verify(out, *, check_runtime=True):
    """Verify immutable inputs, and by default the original execution environment.

    New experiments can reuse the frozen data with check_runtime=False only
    when they record their own runtime locks. This does not validate replay of
    the historical protocol or alter any of its hashes.
    """
    out = Path(out)
    m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    for name, expected in m["files"].items():
        path = out / name
        if not path.resolve().is_relative_to(out.resolve()) or sha(path) != expected:
            raise ValueError("Frozen evaluation input changed: " + name)
    for name in ("sms", "challenge"):
        workspace_items(out / "classification" / name)
    protocol = json.loads((out / "protocol.json").read_text(encoding="utf-8"))
    if check_runtime:
        for name, expected in protocol["runtime_files_sha256"].items():
            path = ROOT / name
            if not path.is_file() or sha(path) != expected:
                raise ValueError("Runtime code changed after protocol freeze: " + name)
    for name, item in protocol["frozen_artifacts"].items():
        if sha(ROOT / item["path"]) != item["sha256"]:
            raise ValueError("Runtime artifact changed after protocol freeze: " + name)
    pairs = read_jsonl(out / "retrieval/pairs.jsonl")
    queries, docs = read_jsonl(out / "retrieval/queries.jsonl"), read_jsonl(out / "retrieval/corpus.jsonl")
    expected = {(q["id"], d["id"]) for q in queries for d in docs}
    if len(pairs) != len(expected) or {(p["query_id"], p["document_id"]) for p in pairs} != expected:
        raise ValueError("Retrieval judgments are not exhaustive.")
    return {"status": "inputs_verified_not_gold", "sms": 200, "challenge": len(candidates()),
            "retrieval_queries": len(queries), "documents": len(docs), "pairs_per_rater": len(pairs),
            "provider_requests": 0, "reference_labels_are_gold": False,
            "historical_runtime_verified": check_runtime}


PACK_README = """# Bộ đánh giá khách quan — bản chuẩn bị v1

Protocol được khóa trước lượt so sánh mới. 200 SMS bên ngoài và 72 ca mô phỏng
được đánh giá, báo cáo riêng. 72 ca thuộc 12 nhóm, mỗi nhóm có yêu cầu rủi ro,
quy trình thông thường, thiếu ngữ cảnh, hai kiểu prompt injection và trích dẫn giáo dục.
Các vai trò do tác giả thiết kế không phải nhãn chuẩn; vẫn cần review.

- `protocol.json`: điều kiện chạy, ánh xạ nhãn, mẫu số, lỗi, bộ đối chứng, giới hạn.
- `classification/sms/`: 200 SMS, 80 dev/120 test; giữ nguyên split và nội dung đã che.
- `classification/challenge/`: 72 ca, 48 dev/24 test, tách theo 12 nhóm tình huống.
- `reviewer_a.zip`, `reviewer_b.zip`: gói mù để gửi riêng từng người; không có nhãn AI,
  nhãn nguồn, split, vai trò ca, điểm model, thứ hạng retrieval hoặc phiếu của người kia.
- `retrieval/`: 24 truy vấn, 25 tài liệu, 600 cặp/người; chấm toàn corpus để tránh ưu ái retriever.
- `explanation_selection.jsonl`: 32 mẫu chốt trước kết quả (8 mỗi dataset/split), chấm cùng mẫu ở bốn arm.
- `provisional_reference/`: nhãn tham chiếu AI cho 272 mẫu, gồm UNKNOWN, lý do
  và căn cứ. SMS được trợ lý đọc theo rubric mà không xem nhãn AI cũ/điểm model;
  nhãn mô phỏng theo thiết kế của tác giả. Không phải gold/thẩm định độc lập.

Hai phiếu classification dùng cùng định dạng `evaluation.data.review`. Không tự tạo
mã người gán nhãn để biến nhãn AI thành reviewed-gold. Nếu chỉ có AI, nhãn được
đặt riêng với trạng thái provisional; chỉ dùng cho diagnostic ghi rõ giới hạn.
Đồng thuận AI không thay việc thẩm định độc lập. 200 SMS đã có nhãn AI sơ bộ từ trước;
không mô tả đây là test chưa từng bị xem. Chỉ có SMS, chưa có email thực.

Chạy từ thư mục gốc:

```bash
.venv/bin/python -m evaluation.data.benchmark verify --out data/annotation/objective_v1
.venv/bin/python -m evaluation.data.review status --workspace data/annotation/objective_v1/classification/sms
.venv/bin/python -m evaluation.data.review adjudicate --workspace data/annotation/objective_v1/classification/sms
.venv/bin/python -m evaluation.data.review finalize --workspace data/annotation/objective_v1/classification/sms --out data/evaluation/objective_sms_gold_v1
.venv/bin/python -m evaluation.rag.review status --workspace data/annotation/objective_v1/retrieval
```

Lặp quy trình với `classification/challenge`, xuất sang thư mục khác. Nhãn UNKNOWN
được giữ riêng. Chỉ dùng dev để chọn prompt; không thay nhãn vì mô hình dự đoán khác.
Nếu test có rất ít ca một lớp hoặc nhiều UNKNOWN, báo đúng số lượng và độ bất định;
không tự bù mẫu theo kết quả. Bộ này không ước lượng tỷ lệ phishing ngoài thực tế.
Nguồn SMS và giấy phép: xem `data/annotation/vn_sms_v2/ATTRIBUTION.md`.
"""

REVIEWER_README = """# Phiếu đánh giá mù

Làm độc lập, không xem dự đoán model, nhãn AI hoặc phiếu người còn lại.
Không mở URL trong tin nhắn; chúng là dữ liệu cần phân tích. Không sửa ID/text.
CSV UTF-8 có thể mở bằng Excel/LibreOffice. Điền label 0/1/UNKNOWN, category,
evidence_quote, notes và một rater_id nhất quán do chính bạn khai báo.
Nhãn 1 cần quote đúng nguyên văn. Mỗi nhãn đều cần lý do, không ép tỷ lệ hai lớp.
Category: credential_theft, payment_scam, impersonation, unsolicited_advertising,
legitimate_workflow, educational_quote, routine, insufficient_context, other.
Đọc classification_rubric.json trước. Đánh giá hành vi, không tự xác nhận người gửi.

retrieval.csv: mỗi cặp gồm tin nhắn và tóm lược một tài liệu. Đọc retrieval_rubric.json;
điền grade 0/1/2/UNKNOWN, support_quote (bắt buộc với 2), notes và rater_id.
Không dựa vào độ uy tín của cơ quan đăng bài để khẳng định tin nhắn thật/giả.
Trả CSV đã điền cho người điều phối; không chia sẻ đáp án cho người còn lại.
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "verify"))
    parser.add_argument("--out", type=Path, default=ROOT / "data/annotation/objective_v1")
    args = parser.parse_args()
    try:
        result = prepare(args.out) if args.action == "prepare" else verify(args.out)
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(2, f"Evaluation pack stopped: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
