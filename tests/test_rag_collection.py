import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest


spec = importlib.util.spec_from_file_location("rag_collector", Path(__file__).parents[1] / "scripts/collect_rag_sources.py")
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


def source():
    return {"id": "VN-RAG-001", "publisher": "Fixture", "kind": "mixed_guidance", "topics": ["otp"],
            "url": "https://support.google.com/mail/answer/8253?hl=vi", "anchors": ["OTP"],
            "summary": "Bản tóm lược biên tập.", "context_note": "Kiểm tra ngữ cảnh."}


def extraction_fixture(monkeypatch):
    body = "OTP được dùng để xác thực trong thao tác do người dùng khởi tạo. " * 12
    monkeypatch.setattr(collector.trafilatura, "extract", lambda *a, **k: body)
    monkeypatch.setattr(collector.trafilatura, "extract_metadata", lambda *a, **k: SimpleNamespace(title="Fixture", date="2040-01-01"))


def test_rejects_unreviewed_hosts_http_and_embedded_credentials():
    for value in ("http://support.google.com/mail", "https://evil.test/a", "https://support.google.com.evil.test/a",
                  "https://user:password@support.google.com/a", "https://127.0.0.1/a"):
        with pytest.raises(ValueError):
            collector.validate_url(value)


def test_redirect_to_unreviewed_host_is_never_requested():
    calls = []
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://evil.test/private"})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ValueError, match="outside"):
                await collector.fetch_bytes(client, source()["url"])
    asyncio.run(run())
    assert len(calls) == 1 and "evil.test" not in calls[0]


def test_response_size_limit_is_enforced():
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"x" * 101))) as client:
            with pytest.raises(ValueError, match="byte limit"):
                await collector.fetch_bytes(client, source()["url"], limit=100)
    asyncio.run(run())


def test_publication_date_not_guessed_from_footer_or_library_inference(monkeypatch):
    extraction_fixture(monkeypatch)
    html = b"<html><h1>Security guidance</h1><article>OTP</article><footer>Updated 2025-01-01</footer></html>"
    result = collector.parse_source(html, source()["url"], source())
    assert result["published_at"] is None
    assert result["date_status"] == "not_available"


def test_verified_publication_hint_wins_over_unreliable_inferred_date(monkeypatch):
    extraction_fixture(monkeypatch)
    item = source() | {"date_hint": "09/10/2024", "published_at": "2024-10-09"}
    result = collector.parse_source(b"<h1>OTP</h1><time>09/10/2024</time>", item["url"], item)
    assert result["published_at"] == "2024-10-09"
    assert result["date_status"] == "visible_date_confirmed"


def test_publisher_date_selector_ignores_other_footer_dates(monkeypatch):
    extraction_fixture(monkeypatch)
    html = '<h1>Cảnh báo OTP</h1><p class="text-bca-gray-400">08/09/2025</p><footer><span>01/01/2026</span></footer>'
    item = source() | {"url": "https://bocongan.gov.vn/bai-viet/fixture"}
    result = collector.parse_source(html.encode(), item["url"], item)
    assert result["published_at"] == "2025-09-08"
    assert result["date_status"] == "publisher_article_date_selector"


def test_future_publication_metadata_is_not_published_as_fact(monkeypatch):
    extraction_fixture(monkeypatch)
    html = b'<h1>OTP</h1><meta property="article:published_time" content="2099-01-01T00:00:00Z">'
    result = collector.parse_source(html, source()["url"], source())
    assert result["published_at"] is None
    assert result["date_status"] == "future_date_rejected"


def test_wrong_topic_or_interstitial_is_rejected(monkeypatch):
    extraction_fixture(monkeypatch)
    with pytest.raises(ValueError, match="anchors"):
        collector.parse_source(b"<h1>OTP</h1>", source()["url"], source() | {"anchors": ["unrelated"]})
    with pytest.raises(ValueError, match="interstitial"):
        collector.parse_source(b"<h1>Access denied</h1>", source()["url"], source())


def test_catalog_resolves_single_canonical_note_and_rejects_duplicates(tmp_path):
    note = {"id": "VN-RAG-001", "text": "Ghi chú nguồn.", "context_note": "Bối cảnh."}
    (tmp_path / "documents.jsonl").write_text(json.dumps(note), encoding="utf-8")
    item = source()
    item.pop("summary"); item.pop("context_note")
    item["notes_ref"] = "documents.jsonl#VN-RAG-001"
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"sources": [item]}), encoding="utf-8")
    result = collector.load_catalog(catalog)
    assert result["sources"][0]["summary"] == note["text"]
    catalog.write_text(json.dumps({"sources": [item, item]}), encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate"):
        collector.load_catalog(catalog)


def test_delivered_corpus_has_unique_sources_provenance_and_short_notes():
    root = Path(__file__).parents[1]
    documents = [json.loads(line) for line in (root / "knowledge/corpus_v1/documents.jsonl").read_text(encoding="utf-8").splitlines()]
    assert 20 <= len(documents) <= 30
    for field in ("id", "source_text_sha256", "summary_sha256"):
        assert len({d[field] for d in documents}) == len(documents)
    assert sum(d["kind"] == "legitimate_workflow" for d in documents) >= 6
    for doc in documents:
        collector.validate_url(doc["source_url"])
        assert doc["http_status"] == 200 and doc["review_status"] == "assistant_curated"
        assert doc["content_kind"] == "editorial_summary_not_verbatim"
        assert len(doc["text"].split()) <= 150
        assert doc["source_text_sha256"] != doc["summary_sha256"]
        assert doc["published_at"] is None or re_date(doc["published_at"])
    manifest = json.loads((root / "knowledge/corpus_v1/manifest.json").read_text())
    assert manifest["catalog_sha256"] == collector.sha((root / "knowledge/source_catalog.json").read_bytes())
    for name, expected in manifest["files"].items():
        assert expected == collector.sha((root / "knowledge/corpus_v1" / name).read_bytes())


def re_date(value):
    from datetime import date
    return date.fromisoformat(value).isoformat() == value
