"""Exercise the deployed HTTP workflow offline; fixtures do not measure quality.

This is also an evaluation entry for future callers: use preview_and_analyze
instead of maintaining a second redactor/intake/feature pipeline. Approved edits
require an explicit second preview before the final consent request.
"""
import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app.api.runtime import create_app
from app.core.privacy import redact
from app.core.settings import ROOT, Settings
from app.services.llm.client import approved_ml_metadata
from app.services.url.character import CharURLService
from app.services.url.intake import extract_urls_v2
from app.services.url.parsing import extract_urls
from app.services.url.policy import operating_prediction
from evaluation.data.sms import read_jsonl, sha, write_json, write_jsonl

DEFAULT_CASES = ROOT / "data/evaluation/runtime_parity_v1.jsonl"
ARMS = {"llm_only": (False, False), "llm_url": (True, False),
        "llm_rag": (False, True), "llm_url_rag": (True, True)}


def preview_and_analyze(client, case, *, include_ml, use_rag, approve):
    """Approve every displayed draft, including changes at final revalidation.

    ``approve(text)`` must be explicit. Offline fixtures can approve all drafts;
    interactive callers must ask again when normalization changes the text.
    """
    preview = client.post("/api/preview", json={"mode": "text", "text": case["text"]})
    if preview.status_code != 200:
        return {"preview": None, "status_code": preview.status_code, "result": preview.json()}
    draft, review_steps = case.get("approved_edit", preview.json()["text"]), []
    for _ in range(4):
        accepted = approve(draft)
        review_steps.append({"text": draft, "approved": accepted is True})
        if accepted is not True:
            return {"preview": None, "status_code": 428, "result": {"requires_confirmation": True}, "review_steps": review_steps}
        checked = client.post("/api/preview", json={"mode": "text", "text": draft})
        if checked.status_code != 200:
            return {"preview": None, "status_code": checked.status_code, "result": checked.json()}
        approved = checked.json()
        if approved["text"] == draft: break
        draft = approved["text"]
    else:
        return {"preview": None, "status_code": 409, "result": {"normalization_unstable": True}, "review_steps": review_steps}
    response = client.post("/api/analyze", json={"mode": "text", "text": case["text"],
        "llm_text": approved["text"], "consent": True, "include_ml": include_ml, "use_rag": use_rag})
    return {"preview": approved, "status_code": response.status_code, "result": response.json(), "review_steps": review_steps}


class RecordingModel:
    def __init__(self, model):
        self.model, self.calls, self.fault = model, [], None

    def load(self, reload=False): return self.model.load(reload=reload)
    def status(self): return self.model.status()

    def features(self, url):
        if not isinstance(self.model, CharURLService): return {"fixture_model": True}
        value = self.model.preprocessing.format_url(url)
        x = self.model.vectorizer.transform([value])
        digest = hashlib.sha256(x.indptr.tobytes() + x.indices.tobytes() + x.data.tobytes()).hexdigest()
        return {"model_input": value, "nonzero_features": int(x.nnz), "features_sha256": digest}

    def predict(self, urls):
        if self.fault == "unavailable":
            outputs = [{"id": f"URL-{i:02}", "url": u, "status": "unavailable", "message": "Deliberate offline fault fixture"}
                       for i, u in enumerate(urls, 1)]
        else:
            outputs = self.model.predict(urls)
        self.calls.append({"urls": list(urls), "outputs": outputs,
                           "features": [] if self.fault else [self.features(u) for u in urls]})
        return outputs


class RecordingRetrieval:
    """Controlled empty-source fixture: observe query/stage without loading E5."""
    def __init__(self, events): self.events, self.calls = events, []
    def status(self): return {"ready": True, "documents": 0, "chunks": 0, "fixture": True}
    def search(self, text, mode="text"):
        self.calls.append({"text": text, "mode": mode}); self.events.append("retrieval")
        return {"status": "empty", "sources": [], "reason": "Offline empty-source fixture; not retrieval quality"}


def load_cases(path):
    cases = read_jsonl(path)
    if not cases or len({c["id"] for c in cases}) != len(cases): raise ValueError("Unique nonempty case inventory required.")
    for c in cases:
        if not isinstance(c.get("text"), str) or not c["text"].strip(): raise ValueError("Case text required.")
        for key in ("expected_urls", "expected_metadata_urls"):
            if not isinstance(c.get(key), list) or any(not isinstance(u, str) for u in c[key]):
                raise ValueError("Explicit expected URL inventories required.")
        if c.get("expected_status") not in {200, 422}: raise ValueError("Explicit HTTP contract required.")
        if c.get("model_fixture") not in {None, "unavailable"}: raise ValueError("Unknown model fixture.")
        if c.get("provider_fixture") not in {None, "truncated", "invalid_json", "semantic_unknown"}:
            raise ValueError("Unknown provider fixture.")
    return cases


def evaluate_cases(cases, model):
    events, captures, active = [], [], {}
    recording = RecordingModel(model); rag = RecordingRetrieval(events)
    settings = replace(Settings(), api_key="offline-parity-fixture", endpoint="https://mkp-api.fptcloud.com/v1/chat/completions",
                       allowed_hosts=("mkp-api.fptcloud.com",), llm_model="offline-parity-response", max_tokens=2048)
    def provider(request):
        payload = json.loads(request.content); captures.append(payload); events.append("classification")
        scenario = active.get("provider_fixture")
        answer = {"risk_level": "UNKNOWN" if scenario == "semantic_unknown" else "LOW",
                  "context_kind": "insufficient" if scenario == "semantic_unknown" else "routine",
                  "reason_code": "missing_context" if scenario == "semantic_unknown" else "no_fraud_evidence",
                  "quotes": [], "missing_context": []}
        return httpx.Response(200, json={"model": "offline-fixture", "usage": {"total_tokens": 1},
            "choices": [{"finish_reason": "length" if scenario == "truncated" else "stop",
                         "message": {"content": "not-json" if scenario == "invalid_json" else json.dumps(answer)}}]})
    if not recording.load()["ready"]: raise ValueError("The requested local model is not ready.")
    app = create_app("focused", settings, transport=httpx.MockTransport(provider), model_service=recording, rag_service=rag)
    rows = []
    with TestClient(app) as client:
        status = client.get("/api/status").json()
        for case in cases:
            active.clear(); active.update(case); recording.fault = case.get("model_fixture")
            # Missing consent must stop before both local model and provider.
            recording.calls.clear(); captures.clear(); events.clear(); rag.calls.clear()
            denied = client.post("/api/analyze", json={"text": case["text"], "consent": False})
            consent_ok = denied.status_code == 422 and not recording.calls and not captures and not rag.calls
            for arm, (include_ml, use_rag) in ARMS.items():
                recording.calls.clear(); captures.clear(); events.clear(); rag.calls.clear()
                response = preview_and_analyze(client, case, include_ml=include_ml, use_rag=use_rag, approve=lambda _: True)
                checks = {"consent_precedes_processing": consent_ok,
                          "http_status": response["status_code"] == case["expected_status"]}
                row = {"case_id": case["id"], "arm": arm, "checks": checks, "known_issue": case.get("known_issue"),
                       "synthetic_input": True, "live_provider_calls": 0, "status_code": response["status_code"]}
                if response["status_code"] != 200:
                    checks["rejected_before_processing"] = not recording.calls and not captures and not rag.calls
                    rows.append(row); continue
                result, approved = response["result"], response["preview"]["text"]
                actual_urls = [u for call in recording.calls for u in call["urls"]]
                checks["model_scores_expected_original_urls"] = actual_urls == case["expected_urls"]
                checks["one_local_prediction_batch"] = len(recording.calls) == bool(actual_urls)
                checks["one_mock_classification_call"] = len(captures) == 1
                data = json.loads(captures[0]["messages"][1]["content"]) if captures else {}
                checks["approved_text_equals_provider_text"] = data.get("text") == approved
                checks["no_sources_in_classifier"] = "reference_documents" not in data
                checks["URL_component_isolation"] = ("url_results" in data) == include_ml
                actual_metadata = data.get("url_results", [])
                checks["expected_approved_URL_metadata"] = [u["url"] for u in actual_metadata] == (case["expected_metadata_urls"] if include_ml else [])
                serialized = json.dumps(captures, ensure_ascii=False)
                checks["removed_or_private_values_not_sent"] = all(v not in serialized for v in case.get("forbidden_payload_strings", []))
                checks["approved_text_preserves_required_fragments"] = all(v in approved for v in case.get("approved_must_contain", []))
                expected_outputs = [operating_prediction(u) for u in (recording.calls[0]["outputs"] if recording.calls else [])]
                checks["app_outputs_match_local_model_and_policy"] = result["urls"] == expected_outputs
                if not recording.fault:
                    direct = model.predict(case["expected_urls"]) if case["expected_urls"] else []
                    checks["direct_model_scores_match_runtime"] = result["urls"] == [operating_prediction(u) for u in direct]
                expected_error = case.get("expected_error")
                checks["technical_status_preserved"] = (result["llm"].get("code") == expected_error and
                    result["llm"]["status"] == ("error" if expected_error else "ok"))
                level = "UNKNOWN" if expected_error or case.get("provider_fixture") == "semantic_unknown" else "LOW"
                checks["headline_does_not_count_URL_again"] = result["final"]["risk_level"] == level
                should_retrieve = use_rag and not expected_error
                checks["retrieval_only_after_successful_verdict"] = events == (["classification", "retrieval"] if should_retrieve else ["classification"])
                checks["retrieval_uses_only_approved_text"] = all(c["text"] == approved for c in rag.calls)
                row.update(approved_text=approved, model_calls=list(recording.calls), metadata_sent=actual_metadata,
                           review_steps=response["review_steps"],
                           actual_provider_payload=captures[0] if captures else None, events=list(events),
                           llm_status=result["llm"]["status"], error=result["llm"].get("code"),
                           URL_status=result["assessments"]["url"]["status"], URL_level=result["assessments"]["url"]["risk_level"],
                           headline=result["final"]["risk_level"])
                rows.append(row)
    return rows, status


def historical_intake(pack, model):
    pack = Path(pack)
    manifest = json.loads((pack / "manifest.json").read_text())
    if sha(pack / "sms.jsonl") != manifest["files"]["sms.jsonl"]: raise ValueError("Saved dev input changed.")
    cases = read_jsonl(pack / "sms.jsonl")
    if len(cases) != 80 or len({c["id"] for c in cases}) != 80: raise ValueError("Expected the exact eighty dev SMS.")
    rows = []
    for c in cases:
        old, old_invalid = extract_urls(c["text"], "text")
        new, new_invalid = extract_urls_v2(c["text"], "text")
        scores = [operating_prediction(r) for r in model.predict(new)] if new else []
        approved = redact(c["text"])[0]
        metadata = approved_ml_metadata(approved, scores)
        rows.append({"id": c["id"], "legacy_urls": old, "legacy_invalid": old_invalid,
                     "runtime_urls": new, "runtime_invalid": new_invalid,
                     "different_intake": (old, old_invalid) != (new, new_invalid),
                     "second_redaction_changed_text": approved != c["text"],
                     "approved_metadata_urls": [r["url"] for r in metadata],
                     "model_scores_not_added_to_old_study": True})
    return rows


def run(out, cases_path=DEFAULT_CASES, *, pack=None, model=None):
    out = Path(out)
    if out.exists(): raise ValueError("Choose a new output directory; retain old results.")
    cases = load_cases(cases_path); model = model if model is not None else CharURLService()
    rows, status = evaluate_cases(cases, model)
    historical = historical_intake(pack, model) if pack else []
    failures = [{"case_id": r["case_id"], "arm": r["arm"], "failed_checks": [n for n, ok in r["checks"].items() if not ok],
                 "known_issue": r["known_issue"]} for r in rows if not all(r["checks"].values())]
    summary = {"cases": len(cases), "logical_runs": len(rows), "failed_runs": len(failures),
        "all_contracts_passed": not failures, "unresolved_cases": sorted({r["case_id"] for r in failures}),
        "failures": failures, "model_is_real": isinstance(model, CharURLService), "model": status["ml"],
        "classification_and_retrieval_are_fixtures": True, "classification_quality_metrics": None,
        "live_provider_calls": 0, "human_gold_created": 0, "reserve_inference": False}
    if historical:
        summary["historical_dev"] = {"n": len(historical), "legacy_URL_cases": sum(bool(r["legacy_urls"]) for r in historical),
            "runtime_URL_cases": sum(bool(r["runtime_urls"]) for r in historical),
            "runtime_metadata_cases": sum(bool(r["approved_metadata_urls"]) for r in historical),
            "different_intake_cases": sum(r["different_intake"] for r in historical),
            "second_redaction_changes": sum(r["second_redaction_changed_text"] for r in historical)}
    out.mkdir(parents=True)
    write_json(out / "summary.json", summary); write_jsonl(out / "per_run.jsonl", rows)
    write_jsonl(out / "historical_dev_intake.jsonl", historical)
    sources = ["evaluation/messages/runtime_parity.py", "app/api/runtime.py", "app/core/privacy.py",
               "app/services/interaction_analysis.py", "app/services/llm/core.py", "app/services/llm/client.py",
               "app/services/url/intake.py", "app/services/url/character.py", "app/services/url/policy.py"]
    manifest = {"source_sha256": {n: sha(ROOT / n) for n in sources}, "cases_sha256": sha(cases_path),
        "runtime": status["runtime"], "model_files_sha256": {p.name: sha(p) for p in model.path.iterdir() if p.is_file()} if isinstance(model, CharURLService) else {},
        "data_scope": f"{len(cases)} authored contract cases; optional exact eighty known dev SMS. No reserve or gold labels.",
        "artifacts_sha256": {p.name: sha(p) for p in out.iterdir() if p.is_file()}}
    if pack: manifest["dev_pack_sha256"] = {n: sha(Path(pack) / n) for n in ("manifest.json", "sms.jsonl")}
    write_json(out / "manifest.json", manifest)
    (out / "report.md").write_text(f"""# Kiểm tra app và đường chạy đánh giá

{len(cases)} ca tự soạn × bốn cấu hình = {len(rows)} lượt. Model URL {'thật' if summary['model_is_real'] else 'fixture'}; phản hồi LLM và retriever đều là fixture kiểm soát. Không gọi provider, không đo Accuracy/F1 hoặc chất lượng E5. Adapter gọi đúng `/api/preview` rồi `/api/analyze`, không chép lại pipeline xử lý input.

**Còn {len(failures)} lượt có điều kiện không đạt**, thuộc {len(summary['unresolved_cases'])} ca. Xem `summary.json` và từng check trong `per_run.jsonl`; không gọi các lỗi đã biết là đạt. Tách điều kiện an toàn (không gửi bí mật/URL bị xóa) khỏi việc thiếu metadata hay làm hỏng URL khi che dữ liệu. Các ca fixture lỗi model/API vẫn giữ trong inventory.

`model_calls` ghi URL thực đã chấm và hash đặc trưng sparse/model input; `metadata_sent` và `actual_provider_payload` cho biết bản gửi AI. Giá trị trong ca tự soạn là giả lập, không chứa dữ liệu người dùng thật. Cấu hình LLM-only vẫn nhìn URL vốn nằm trong text, nhưng không nhận thêm score; RAG của focused ở sau verdict nên không làm thay headline.

Chẩn đoán 80 SMS dev cũ chỉ đối chiếu intake và khả năng cấp metadata hiện tại, không sửa score/input/journal tuần 4, không tính F1 lại và không mở 120 reserve. Khác hoa/thường, URL sát ký tự trang trí hoặc cách đọc IDN có thể làm khác inventory. Những khác biệt này cần review; không coi tất cả là lợi ích của intake mới.

Các lỗi runtime được tái hiện và ghi lại để sửa ở bước riêng có snapshot/replay phù hợp; lượt này không sửa module đã khóa hash. Pilot provider với đầu vào dài và RAG vẫn chưa được thực hiện.
""", encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--dev-pack", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    a = parser.parse_args()
    print(json.dumps(run(a.out, a.cases, pack=a.dev_pack), ensure_ascii=False, indent=2))
