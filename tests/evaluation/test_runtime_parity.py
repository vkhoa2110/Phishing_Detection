from dataclasses import replace
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.runtime import create_app
from app.core.settings import Settings
from evaluation.data.sms import sha, write_json, write_jsonl
from evaluation.messages.runtime_parity import (DEFAULT_CASES, RecordingModel, RecordingRetrieval,
    evaluate_cases, historical_intake, load_cases, preview_and_analyze, run)


class ContractModel:
    """Deterministic faults/bands for contracts only, not a learned URL model."""
    def load(self, reload=False): return self.status()
    def status(self):
        return {"ready": True, "kind": "contract_fixture", "feature_count": 0,
                "thresholds": {"warning_threshold": .5, "high_threshold": .8}}
    def predict(self, urls):
        rows = []
        for i, url in enumerate(urls, 1):
            score = .9 if "/orders" in url else .1 if "/reset" in url else .6
            rows.append({"id": f"URL-{i:02}", "url": url, "status": "ok", "score": score,
                "risk_level": "HIGH" if score >= .8 else "WARNING" if score >= .5 else "LOW",
                "warning_threshold": .5, "high_threshold": .8})
        return rows


@pytest.fixture(scope="module")
def matrix():
    return evaluate_cases(load_cases(DEFAULT_CASES), ContractModel())[0]


def test_contract_audit_exposes_existing_bugs_instead_of_calling_them_passed(matrix):
    failed = [r for r in matrix if not all(r["checks"].values())]
    assert len(matrix) == 64 and len(failed) == 6
    assert {r["case_id"] for r in failed} == {"PARITY-06", "PARITY-07"}
    for row in matrix:
        assert all(ok for name, ok in row["checks"].items() if name not in {
            "expected_approved_URL_metadata", "approved_text_preserves_required_fragments"})
    uppercase = next(r for r in failed if r["case_id"] == "PARITY-06")
    assert uppercase["metadata_sent"] == []
    assert "https://EXAMPLE.org/orders" in uppercase["approved_text"]
    otp = next(r for r in failed if r["case_id"] == "PARITY-07")
    assert "[SECRET]://example.org" in otp["approved_text"]


@pytest.mark.parametrize("case_id", ["PARITY-03", "PARITY-04", "PARITY-05", "PARITY-08", "PARITY-09", "PARITY-10"])
def test_original_scoring_and_approved_payload_are_separate(matrix, case_id):
    case = next(c for c in load_cases(DEFAULT_CASES) if c["id"] == case_id)
    for row in [r for r in matrix if r["case_id"] == case_id]:
        assert row["checks"]["model_scores_expected_original_urls"]
        serialized = json.dumps(row["actual_provider_payload"], ensure_ascii=False)
        assert all(value not in serialized for value in case.get("forbidden_payload_strings", []))
        sent = json.loads(row["actual_provider_payload"]["messages"][1]["content"])
        assert sent["text"] == row["approved_text"]
        if row["arm"] in {"llm_only", "llm_rag"}: assert "url_results" not in sent
        if case_id == "PARITY-03":
            assert "synthetic-secret" in row["model_calls"][0]["urls"][0]
            assert "synthetic-secret" not in serialized


def test_no_url_low_score_unknown_band_and_model_failure_stay_distinct(matrix):
    chosen = {r["case_id"]: r for r in matrix if r["arm"] == "llm_only"}
    assert chosen["PARITY-01"]["URL_status"] == "not_present"
    assert chosen["PARITY-03"]["URL_level"] == "LOW"
    assert chosen["PARITY-04"]["URL_status"] == "partial"  # valid score in abstention band
    assert chosen["PARITY-04"]["URL_level"] == "UNKNOWN"
    assert chosen["PARITY-15"]["URL_status"] == "unavailable"
    assert chosen["PARITY-02"]["URL_level"] == "HIGH" and chosen["PARITY-02"]["headline"] == "LOW"
    assert chosen["PARITY-16"]["llm_status"] == "ok" and chosen["PARITY-16"]["headline"] == "UNKNOWN"
    for case in ("PARITY-13", "PARITY-14"):
        assert chosen[case]["llm_status"] == "error" and chosen[case]["URL_level"] == "HIGH"


def test_changed_final_preview_requires_another_approval_before_any_processing():
    calls, approvals, events = [], [], []
    recorder = RecordingModel(ContractModel())
    app = create_app("focused", replace(Settings(), api_key="offline-fixture"),
        transport=httpx.MockTransport(lambda r: calls.append(r)), model_service=recorder,
        rag_service=RecordingRetrieval(events))
    def approve(text):
        approvals.append(text)
        return len(approvals) == 1
    with TestClient(app) as client:
        result = preview_and_analyze(client,
            {"text": "Tra cứu https://demo:synthetic-pass@example.org/path"},
            include_ml=True, use_rag=True, approve=approve)
    assert result["status_code"] == 428 and result["result"]["requires_confirmation"]
    assert len(approvals) == 2 and approvals[0] != approvals[1]
    assert not calls and not recorder.calls and not events


@pytest.mark.parametrize("change", [{"expected_metadata_urls": None}, {"provider_fixture": "invented"}, {"text": ""}])
def test_invalid_case_protocols_are_rejected(tmp_path, change):
    case = {**load_cases(DEFAULT_CASES)[0], **change}
    path = tmp_path / "cases.jsonl"; write_jsonl(path, [case])
    with pytest.raises(ValueError): load_cases(path)


def test_historical_intake_rejects_modified_dev_input(tmp_path):
    path = tmp_path / "sms.jsonl"
    write_jsonl(path, [{"id": f"dev-{i}", "text": "Thông báo lịch học."} for i in range(80)])
    write_json(tmp_path / "manifest.json", {"files": {"sms.jsonl": sha(path)}})
    assert len(historical_intake(tmp_path, ContractModel())) == 80
    path.write_text(path.read_text() + "\n")
    with pytest.raises(ValueError, match="changed"): historical_intake(tmp_path, ContractModel())


def test_saved_summary_never_calls_fixture_agreement_model_accuracy(tmp_path):
    cases = tmp_path / "cases.jsonl"; write_jsonl(cases, load_cases(DEFAULT_CASES)[:2])
    summary = run(tmp_path / "out", cases, model=ContractModel())
    assert summary["all_contracts_passed"] is True
    assert summary["model_is_real"] is False
    assert summary["classification_quality_metrics"] is None and summary["live_provider_calls"] == 0
    with pytest.raises(ValueError, match="new output"):
        run(tmp_path / "out", cases, model=ContractModel())
