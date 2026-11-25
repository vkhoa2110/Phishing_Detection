"""Multi-link emails: complete scoring, shared limits and approved metadata.

All providers/models here are fixtures; no network or personal database is used.
"""
from dataclasses import replace
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api import candidate, focused, interaction, legacy, stable, verifier_shadow
from app.api.workspace import create_app as create_workspace
from app.core.settings import Settings
from app.services.url.intake import inspect_url_intake
from app.services.url.parsing import MAX_URLS, extract_urls
from app.services.workspace import WorkspaceSettings
from tests.api.test_baseline import FakeML
from tests.api.test_candidate_app import OrderedRAG
from tests.api.test_focused_app import decision, packet
from tests.api.test_guest_access import EXT_HEADERS
from tests.api.test_workspace import headers


PROFILES = [legacy, stable, candidate, interaction, focused, verifier_shadow]


def links(count):
    return [f"https://example.org/item-{i:02d}" for i in range(count)]


class RecordingML(FakeML):
    def __init__(self):
        self.seen = []

    def predict(self, urls):
        self.seen.append(list(urls))
        return super().predict(urls)


@pytest.mark.parametrize("profile", PROFILES, ids=lambda module: module.__name__.split(".")[-1])
@pytest.mark.parametrize("count", [6, 50])
def test_every_profile_previews_and_scores_all_links_without_silent_truncation(tmp_path, profile, count):
    ml = RecordingML()
    expected = links(count)
    # Repeated navigation/footer links do not consume extra capacity.
    text = "Thông tin sản phẩm\n" + "\n".join(expected + expected[:8])
    def provider(request):
        pytest.fail("URL-only processing must not call a provider.")
    app = profile.create_app(replace(Settings(), root=tmp_path),
        httpx.MockTransport(provider), ml, OrderedRAG([]))
    with TestClient(app) as client:
        assert client.get("/api/status").json()["limits"]["urls"] == MAX_URLS == 50
        preview = client.post("/api/preview", json={"text": text})
        assert preview.status_code == 200, preview.text
        assert preview.json()["url_count"] == count
        assert not ml.seen
        result = client.post("/api/analyze", json={"text": text, "use_llm": False})
        assert result.status_code == 200, result.text
        assert [row["url"] for row in result.json()["urls"]] == expected
        assert ml.seen == [expected]
        assert all(row["status"] == "ok" for row in result.json()["urls"])


@pytest.mark.parametrize("profile", PROFILES, ids=lambda module: module.__name__.split(".")[-1])
def test_overflow_in_original_or_approved_text_stops_before_model_or_provider(tmp_path, profile):
    ml, calls = RecordingML(), []
    def provider(request):
        calls.append(request)
        pytest.fail("Overflow must be rejected before a provider call.")
    app = profile.create_app(replace(Settings(), root=tmp_path, api_key="offline-fixture"),
        httpx.MockTransport(provider), ml, OrderedRAG([]))
    overflow = " ".join(links(51))
    with TestClient(app) as client:
        for path, body in [
            ("/api/preview", {"text": overflow}),
            ("/api/analyze", {"text": overflow, "use_llm": False}),
            ("/api/analyze", {"text": "Thông báo", "llm_text": overflow, "consent": True}),
        ]:
            result = client.post(path, json=body)
            assert result.status_code == 422 and "50 URL" in result.json()["detail"]
        assert not ml.seen and not calls


def test_recovered_urls_share_capacity_and_ambiguous_prose_does_not_consume_it():
    clear = links(25)
    hidden = [f"site{i}[.]example.org/a" for i in range(25)]
    prose = [f"item{i}.unknownsuffix" for i in range(51)]
    result = inspect_url_intake(" ".join(clear + hidden + prose), "text")
    assert result["urls"] == clear + [url.replace("[.]", ".") for url in hidden]
    assert len(result["unscored_candidates"]) == 51
    with pytest.raises(ValueError, match="50 URL"):
        inspect_url_intake(" ".join(clear + hidden + ["extra[.]example.org"]), "text")


@pytest.mark.parametrize("extract", [extract_urls, lambda text, mode: (
    inspect_url_intake(text, mode)["urls"], inspect_url_intake(text, mode)["invalid_urls"])])
def test_invalid_urls_count_towards_limit_and_single_url_mode_stays_single(extract):
    text = " ".join(links(49) + ["https://example.org:invalid/a"])
    good, invalid = extract(text, "text")
    assert good == links(49) and invalid == ["https://example.org:invalid/a"]
    with pytest.raises(ValueError, match="50 URL"):
        extract(text + " https://extra.example.org/", "text")
    with pytest.raises(ValueError):
        extract(" ".join(links(2)), "url")


@pytest.mark.parametrize("surface", ["web", "extension"])
@pytest.mark.parametrize("count", [6, 50])
def test_guest_multi_link_email_only_sends_scores_for_urls_still_approved(tmp_path, surface, count):
    ml, calls = RecordingML(), []
    def provider(request):
        calls.append(json.loads(json.loads(request.content)["messages"][1]["content"]))
        return packet(decision())
    app = create_workspace("focused", replace(Settings(), root=tmp_path, api_key="offline-fixture"),
        transport=httpx.MockTransport(provider), model_service=ml, rag_service=OrderedRAG([]),
        workspace_settings=WorkspaceSettings(database=tmp_path / "test.sqlite3"))
    original = links(count)
    approved = "Hãy gửi mã OTP\n" + "\n".join(original[:-1] + ["https://new.example.org/"])
    with TestClient(app) as client:
        prefix = "/api/extension" if surface == "extension" else "/api"
        request_headers = EXT_HEADERS if surface == "extension" else headers(client)
        if surface == "extension":
            assert client.post(prefix + "/session", headers=request_headers, json={}).json()["limits"]["urls"] == 50
        preview = client.post(prefix + "/preview", headers=request_headers, json={"text": approved})
        assert preview.status_code == 200 and preview.json()["url_count"] == count
        result = client.post(prefix + "/analyze", headers=request_headers, json={
            "text": "Hãy gửi mã OTP\n" + "\n".join(original), "llm_text": preview.json()["text"],
            "consent": True, "use_llm": True, "include_ml": True,
        })
        assert result.status_code == 200, result.text
        data = result.json()
        assert len(data["urls"]) == count and ml.seen == [original]
        assert data["llm"]["status"] == "ok" and len(calls) == 1
        assert calls[0]["text"] == approved
        assert [row["url"] for row in calls[0]["url_results"]] == original[:-1]
        assert original[-1] not in json.dumps(calls)
        assert data["history"]["reason"] == "guest"
        with app.state.workspace.connection() as conn:
            assert conn.execute("SELECT COUNT(*) FROM history").fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
