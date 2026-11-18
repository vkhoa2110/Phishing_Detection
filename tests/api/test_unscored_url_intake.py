"""Offline API boundaries for the candidate-only bare-domain interpretation."""
from dataclasses import replace
import hashlib
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api import focused, interaction, legacy, stable
from app.core.settings import ROOT, Settings
from app.services.url import intake as intake_module
from app.services.url.domain_reference import reference_manifest
from tests.api.test_baseline import FakeML, api_response
from tests.api.test_candidate_app import OrderedRAG


FACTORIES = {"candidate": interaction.create_app, "focused": focused.create_app}
UNSCORED = ["tu.tu", "di.doi", "nhac.lich", "ghi.chu", "ban.nhan", "hen.ngay", "toi.gui"]


class RecordingML(FakeML):
    def __init__(self):
        self.seen = []

    def predict(self, urls):
        self.seen.append(list(urls))
        return super().predict(urls)


def low_decision(profile):
    if profile == "focused":
        return {"risk_level": "LOW", "context_kind": "routine",
                "reason_code": "no_fraud_evidence", "quotes": [], "missing_context": []}
    return {
        "risk_level": "LOW", "context_kind": "routine",
        "summary": "Chưa thấy yêu cầu lừa đảo trong thông điệp.", "evidence": [],
        "recommended_actions": ["Đối chiếu thông tin qua kênh liên hệ đã biết."],
        "interaction": {"requester": None, "recipient": None, "requested_action": "unknown",
                        "asset_or_access": None, "beneficiary": None, "stage": "single_message",
                        "persuasion": [], "conversation_turns_used": 1},
    }


def offline_app(profile, tmp_path, calls, ml=None):
    def provider(request):
        payload = json.loads(request.content)
        calls.append(json.loads(payload["messages"][1]["content"]))
        body = api_response(low_decision(profile))
        body["model"] = "offline-fixture"
        return httpx.Response(200, json=body)

    settings = replace(Settings(), root=tmp_path, api_key="offline-fixture")
    return FACTORIES[profile](settings, httpx.MockTransport(provider),
                              ml or RecordingML(), OrderedRAG([]))


@pytest.mark.parametrize("profile", FACTORIES)
def test_reference_and_code_provenance_survive_both_manifests(tmp_path, profile):
    calls, ml = [], RecordingML()
    with TestClient(offline_app(profile, tmp_path, calls, ml)) as client:
        status_manifest = client.get("/api/status").json()["runtime_manifest"]
        response = client.post("/api/analyze", json={"text": "tu.tu example.com", "use_llm": False})
        assert response.status_code == 200, response.text
        result = response.json()
        reference = reference_manifest()
        assert result["url_intake"]["bare_domain_reference"] == reference
        assert result["execution"]["url"]["bare_domain_reference"] == reference
        assert result["execution"]["url"]["unscored_candidates"] == 1
        for manifest in (status_manifest, result["execution"]["runtime_manifest"]):
            assert manifest["url_intake_version"] == intake_module.VERSION
            assert manifest["bare_domain_reference"] == reference
            assert reference["sha256"] == hashlib.sha256((ROOT / reference["resource"]).read_bytes()).hexdigest()
            for name in ("app/services/url/intake.py", "app/services/url/domain_reference.py"):
                assert manifest["source_files_sha256"][name] == hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        assert result["url_intake"]["unscored_candidates"] == [{
            "original": "tu.tu", "analysis_url": "tu.tu",
            "reason": "bare_suffix_not_in_pinned_iana_root", "requires_user_review": True, "opened": False,
        }]
        assert result["invalid_urls"] == [] and ml.seen == [["example.com"]] and not calls


@pytest.mark.parametrize("profile", FACTORIES)
def test_only_known_root_is_scored_and_metadata_while_unscored_text_reaches_ai(tmp_path, profile):
    calls, ml = [], RecordingML()
    text = "Hẹn gặp vào ngày mai. tu.tu di.doi example.com"
    with TestClient(offline_app(profile, tmp_path, calls, ml)) as client:
        response = client.post("/api/analyze", json={"text": text, "consent": True, "include_ml": True})
        assert response.status_code == 200, response.text
        result = response.json()
        assert ml.seen == [["example.com"]]
        assert [item["url"] for item in result["urls"]] == ["example.com"]
        assert calls[0]["text"] == text
        assert [item["url"] for item in calls[0]["url_results"]] == ["example.com"]
        assert [item["original"] for item in result["url_intake"]["unscored_candidates"]] == ["tu.tu", "di.doi"]
        assert result["llm"]["verdict"]["risk_level"] == result["final"]["risk_level"] == "LOW"
        assert result["assessments"]["url"]["risk_level"] == "HIGH"
        assert result["final"]["requires_review"] and result["invalid_urls"] == []


@pytest.mark.parametrize("profile", FACTORIES)
def test_unscored_candidates_only_add_review_flag_and_leave_assessments_unchanged(tmp_path, profile):
    calls = []
    with TestClient(offline_app(profile, tmp_path, calls)) as client:
        base = client.post("/api/analyze", json={"text": "Hẹn gặp vào ngày mai.", "consent": True}).json()
        result = client.post("/api/analyze", json={"text": "Hẹn gặp vào ngày mai. tu.tu", "consent": True}).json()
        assert base["final"]["requires_review"] is False
        assert result["final"]["requires_review"] is True
        assert {**result["final"], "requires_review": False} == base["final"]
        assert result["assessments"] == base["assessments"]
        assert result["llm"]["verdict"] == base["llm"]["verdict"]
        assert result["urls"] == result["invalid_urls"] == []
        assert "chưa được chấm URL" in result["notice"]


@pytest.mark.parametrize("profile", FACTORIES)
def test_more_than_five_unscored_candidates_pass_preview_and_approved_analysis(tmp_path, profile):
    calls, ml = [], RecordingML()
    text = "Nhắc lịch " + " ".join(UNSCORED) + " example.com"
    with TestClient(offline_app(profile, tmp_path, calls, ml)) as client:
        preview = client.post("/api/preview", json={"text": text})
        assert preview.status_code == 200, preview.text
        assert preview.json()["text"] == text
        assert preview.json()["url_count"] == 1 and preview.json()["invalid_count"] == 0
        assert preview.json()["unscored_candidate_count"] == len(UNSCORED)
        assert not calls and not ml.seen
        response = client.post("/api/analyze", json={
            "text": text, "llm_text": preview.json()["text"], "consent": True, "include_ml": True,
        })
        assert response.status_code == 200, response.text
        result = response.json()
        assert len(result["url_intake"]["unscored_candidates"]) == len(UNSCORED)
        assert calls[0]["text"] == text
        assert [row["url"] for row in calls[0]["url_results"]] == ["example.com"]
        assert result["llm"]["status"] == "ok" and ml.seen == [["example.com"]]
        scored_overflow = " ".join(f"site{i}.com" for i in range(6))
        assert client.post("/api/preview", json={"text": scored_overflow}).status_code == 422
        assert client.post("/api/analyze", json={"text": scored_overflow, "consent": True}).status_code == 422
        assert len(calls) == 1


@pytest.mark.parametrize("profile", FACTORIES)
def test_consent_precedes_analysis_intake_and_edited_preview_stays_private(tmp_path, monkeypatch, profile):
    calls, inspected, ml = [], [], RecordingML()
    original_inspect = intake_module.inspect_url_intake

    def inspect(text, mode):
        inspected.append((text, mode))
        return original_inspect(text, mode)

    monkeypatch.setattr(intake_module, "inspect_url_intake", inspect)
    monkeypatch.setattr(interaction, "inspect_url_intake", inspect)
    original = "Nhắc lịch tu.tu https://private.example/?token=intake-private-value khoa@example.org 0912345678"
    with TestClient(offline_app(profile, tmp_path, calls, ml)) as client:
        assert client.post("/api/analyze", json={"text": original, "include_ml": True}).status_code == 422
        assert not inspected and not ml.seen and not calls
        preview = client.post("/api/preview", json={"text": original}).json()
        assert preview["url_count"] == 1 and preview["unscored_candidate_count"] == 1
        assert "intake-private-value" not in preview["text"] and "khoa@" not in preview["text"]
        assert "0912345678" not in preview["text"] and not ml.seen and not calls
        approved = "Nhắc lịch " + " ".join(UNSCORED)
        edited_preview = client.post("/api/preview", json={"text": approved}).json()
        body = {"text": original, "llm_text": edited_preview["text"], "include_ml": True}
        inspected.clear()
        assert client.post("/api/analyze", json=body).status_code == 422
        assert not inspected and not ml.seen and not calls
        response = client.post("/api/analyze", json={**body, "consent": True})
        assert response.status_code == 200, response.text
        result = response.json()
        assert calls[0]["text"] == approved and calls[0]["url_results"] == []
        assert "private.example" not in json.dumps(calls) and "intake-private-value" not in json.dumps(calls)
        assert result["llm"]["input_modified"] is True
        assert ml.seen == [["https://private.example/?token=intake-private-value"]]


@pytest.mark.parametrize("factory", [stable.create_app, legacy.create_app], ids=["stable", "legacy"])
def test_historical_profiles_keep_their_existing_bare_candidate_rules(tmp_path, factory):
    calls, ml = [], RecordingML()

    def provider(request):
        calls.append(request)
        pytest.fail("Disabled AI must not call a provider.")

    app = factory(replace(Settings(), root=tmp_path), httpx.MockTransport(provider), ml, OrderedRAG([]))
    with TestClient(app) as client:
        assert client.post("/api/preview", json={"text": " ".join(UNSCORED)}).status_code == 422
        assert client.post("/api/analyze", json={"text": " ".join(UNSCORED), "use_llm": False}).status_code == 422
        result = client.post("/api/analyze", json={"text": "tu.tu", "use_llm": False}).json()
        assert [row["url"] for row in result["urls"]] == ["tu.tu"]
        assert "url_intake" not in result and not calls
