"""Fetch reviewed source URLs and build a provenance-backed Vietnamese summary corpus.

The deliverable contains editorial summaries, never scraped full articles.
An optional temporary review directory holds source text for checking summaries.
"""
import argparse
import asyncio
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import unicodedata
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup
import trafilatura

AGENT = "PhishLensResearch/0.1"
TRUSTED_HOSTS = {
    "bocongan.gov.vn", "www.bocongan.gov.vn", "congan.tuyenquang.gov.vn",
    "chongluadao.vn", "www.chongluadao.vn", "cybersafe.vnu.edu.vn", "uet.vnu.edu.vn",
    "student.ulis.vnu.edu.vn", "vnpost.vn", "www.vnpost.vn", "vietcombank.com.vn",
    "www.vietcombank.com.vn", "bidv.com.vn", "www.bidv.com.vn",
    "support.google.com", "support.microsoft.com",
}


def normal(value):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", value)).strip()


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode("utf-8")).hexdigest()


def validate_url(url):
    p = urlsplit(url)
    if p.scheme != "https" or p.hostname not in TRUSTED_HOSTS or p.port not in (None, 443) or p.username or p.password:
        raise ValueError("Source URL or redirect is outside the reviewed HTTPS host list.")
    return url


def load_catalog(path):
    catalog = json.loads(path.read_text(encoding="utf-8"))
    seen_ids, seen_urls = set(), set()
    for item in catalog["sources"]:
        if "notes_ref" in item:
            relative, source_id = item.pop("notes_ref").rsplit("#", 1)
            note_path = (path.parent / relative).resolve()
            if not note_path.is_relative_to(path.parent.resolve()):
                raise ValueError("Notes reference must remain within the knowledge directory.")
            notes = [json.loads(line) for line in note_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            note = next((d for d in notes if d["id"] == source_id), None)
            if note is None:
                raise ValueError("Referenced editorial note is missing.")
            item.update(summary=note["text"], context_note=note["context_note"])
        validate_url(item["url"])
        if not re.fullmatch(r"VN-RAG-\d{3}", item["id"]) or item["id"] in seen_ids or item["url"] in seen_urls:
            raise ValueError("Duplicate/invalid source ID or URL.")
        if len(item["summary"].split()) > 150 or not item["topics"] or not item["anchors"]:
            raise ValueError("A source needs a short summary, topics and verification anchors.")
        if item["kind"] not in {"scam_warning", "legitimate_workflow", "incident_response", "mixed_guidance"}:
            raise ValueError("Unknown document kind.")
        seen_ids.add(item["id"])
        seen_urls.add(item["url"])
    return catalog


async def fetch_bytes(client, url, limit=4_000_000):
    for _ in range(6):
        validate_url(url)
        async with client.stream("GET", url, follow_redirects=False) as response:
            if response.status_code in {301, 302, 303, 307, 308}:
                url = urljoin(str(response.url), response.headers["location"])
                validate_url(url)
                continue
            chunks, size = [], 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > limit:
                    raise ValueError("Source response exceeds byte limit.")
                chunks.append(chunk)
            return response.status_code, str(response.url), dict(response.headers), b"".join(chunks)
    raise ValueError("Too many redirects.")


def parse_source(data, resolved_url, source):
    soup = BeautifulSoup(data, "html.parser")
    html = str(soup)
    body = trafilatura.extract(html, url=resolved_url, include_comments=False, include_tables=True,
                               include_links=False, favor_precision=True) or ""
    if len(body) < 250:
        raise ValueError("Missing or too little article text; needs manual review.")
    folded = normal(body).casefold()
    if not all(normal(a).casefold() in folded for a in source["anchors"]):
        raise ValueError("Expected topic anchors absent from extracted source text.")
    h1 = soup.find("h1")
    metadata = trafilatura.extract_metadata(html, default_url=resolved_url, extensive=False)
    title = normal(h1.get_text(" ", strip=True) if h1 else metadata.title or "")
    if not title or any(x in title.casefold() for x in ("access denied", "just a moment", "page not found", "404 not found")):
        raise ValueError("Source title indicates an error/interstitial.")
    published, date_status = None, "not_available"
    # Avoid inferred dates: extraction libraries can mistake navigation/footer dates for publication.
    if source.get("date_hint") and source["date_hint"] in normal(soup.get_text(" ", strip=True)):
        published, date_status = source["published_at"], "visible_date_confirmed"
    else:
        tag = soup.find("meta", attrs={"property": "article:published_time"}) or soup.find("meta", attrs={"itemprop": "datePublished"})
        if tag and re.match(r"^\d{4}-\d{2}-\d{2}", tag.get("content", "")):
            published, date_status = tag["content"][:10], "explicit_publication_metadata"
        elif urlsplit(resolved_url).hostname in {"bocongan.gov.vn", "www.bocongan.gov.vn"}:
            tag = soup.select_one("p.text-bca-gray-400")
            if tag and re.fullmatch(r"\d{2}/\d{2}/\d{4}", tag.get_text(strip=True)):
                published = datetime.strptime(tag.get_text(strip=True), "%d/%m/%Y").date().isoformat()
                date_status = "publisher_article_date_selector"
        elif urlsplit(resolved_url).hostname in {"vietcombank.com.vn", "www.vietcombank.com.vn"} and h1:
            tag = h1.find_next("span", class_="date")
            if tag and re.fullmatch(r"\d{2}/\d{2}/\d{4}", tag.get_text(strip=True)):
                published = datetime.strptime(tag.get_text(strip=True), "%d/%m/%Y").date().isoformat()
                date_status = "publisher_article_date_selector"
    today = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Ho_Chi_Minh")).date().isoformat()
    if published and published > today:
        published, date_status = None, "future_date_rejected"
    modified = soup.find("meta", attrs={"property": "article:modified_time"})
    return {"title": title, "text": body, "published_at": published, "date_status": date_status,
            "last_modified_at": modified.get("content") if modified else None,
            "source_text_sha256": sha(normal(body)), "source_text_characters": len(body)}


async def collect(args):
    catalog = load_catalog(args.catalog)
    args.out.mkdir(parents=True, exist_ok=True)
    if (args.out / "manifest.json").exists():
        raise ValueError("Snapshot already exists. Choose another --out directory to retain provenance.")
    if args.review_dir:
        args.review_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    collected_at = datetime.now(timezone.utc).isoformat()
    robots, host_locks = {}, {}
    gate = asyncio.Semaphore(4)
    rejected, accepted = [], []
    async with httpx.AsyncClient(timeout=25, headers={"User-Agent": AGENT, "Accept-Language": "vi,en;q=0.5"}) as client:
        async def one(source):
            host = urlsplit(source["url"]).netloc
            lock = host_locks.setdefault(host, asyncio.Lock())
            async with gate, lock:
                try:
                    if host not in robots:
                        robots_url = f"https://{host}/robots.txt"
                        code, _, _, data = await fetch_bytes(client, robots_url, limit=500_000)
                        robot = RobotFileParser()
                        if code == 200:
                            robot.parse(data.decode("utf-8", errors="replace").splitlines())
                            robots[host] = (robot, "fetched")
                        elif code in (404, 410):
                            robots[host] = (None, "not_published")
                        else:
                            raise ValueError(f"robots.txt returned HTTP {code}; collection deferred.")
                    robot, robot_status = robots[host]
                    if robot and not robot.can_fetch(AGENT, source["url"]):
                        raise ValueError("robots.txt disallows automated collection.")
                    async with asyncio.timeout(40):
                        code, final_url, headers, data = await fetch_bytes(client, source["url"])
                    if code != 200:
                        raise ValueError(f"Source returned HTTP {code}.")
                    if "html" not in headers.get("content-type", "").lower():
                        raise ValueError("Source is not an HTML article/support page.")
                    parsed = await asyncio.to_thread(parse_source, data, final_url, source)
                    source_text = parsed.pop("text")
                    document = {"id": source["id"], "title": parsed.pop("title"), "publisher": source["publisher"],
                        "source_url": source["url"], "resolved_url": final_url, "language": "vi", "kind": source["kind"],
                        "topics": source["topics"], "text": source["summary"], "context_note": source["context_note"],
                        "content_kind": "editorial_summary_not_verbatim", "review_status": "assistant_curated",
                        "review_note": "Source checked for reachability and topic; not independent expert annotation.",
                        "retrieved_at": datetime.now(timezone.utc).isoformat(), "robots_status": robot_status,
                        "http_status": code, "html_sha256": sha(data), "summary_sha256": sha(source["summary"]),
                        "source_rights": "Original publisher retains source rights; no full article redistributed.", **parsed}
                    accepted.append(document)
                    if args.review_dir:
                        p = args.review_dir / (source["id"] + ".txt")
                        p.write_text(source_text, encoding="utf-8")
                        p.chmod(0o600)
                    print(source["id"], "OK", document["title"][:95], flush=True)
                except (httpx.HTTPError, ValueError, TimeoutError) as exc:
                    reason = str(exc) or type(exc).__name__
                    rejected.append({"id": source["id"], "url": source["url"], "reason": reason, "error_type": type(exc).__name__, "retrieved_at": datetime.now(timezone.utc).isoformat()})
                    print(source["id"], "DEFERRED", reason, flush=True)
        await asyncio.gather(*(one(source) for source in catalog["sources"]))
    # Exact duplicates are not silently counted as independent knowledge.
    seen, unique = {}, []
    for document in sorted(accepted, key=lambda d: d["id"]):
        identity = document["source_text_sha256"]
        if identity in seen:
            rejected.append({"id": document["id"], "url": document["source_url"], "reason": "Duplicate source text of " + seen[identity]})
        else:
            seen[identity] = document["id"]
            unique.append(document)
    report = {"snapshot": catalog["version"], "started_at": collected_at, "completed_at": datetime.now(timezone.utc).isoformat(),
              "candidates": len(catalog["sources"]), "documents": len(unique), "deferred": len(rejected),
              "by_kind": dict(Counter(d["kind"] for d in unique)), "by_publisher": dict(Counter(d["publisher"] for d in unique)),
              "by_topic": dict(Counter(topic for d in unique for topic in d["topics"])),
              "verified_publication_dates": sum(d["published_at"] is not None for d in unique),
              "unknown_publication_dates": sum(d["published_at"] is None for d in unique),
              "full_source_articles_redistributed": False, "indexed": False}
    def dump(path, value):
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.out / "documents.jsonl").write_text("".join(json.dumps(d, ensure_ascii=False) + "\n" for d in unique), encoding="utf-8")
    (args.out / "deferred_sources.jsonl").write_text("".join(json.dumps(d, ensure_ascii=False) + "\n" for d in rejected), encoding="utf-8")
    dump(args.out / "collection_report.json", report)
    with (args.out / "sources.csv").open("w", encoding="utf-8-sig", newline="") as file:
        fields = ["id", "title", "publisher", "kind", "topics", "published_at", "date_status", "source_url", "resolved_url"]
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for document in unique:
            writer.writerow({key: ";".join(document[key]) if key == "topics" else document[key] for key in fields})
    dump(args.out / "manifest.json", {"snapshot": catalog["version"], "catalog_sha256": sha(args.catalog.read_bytes()),
         "expanded_catalog_sha256": sha(json.dumps(catalog, ensure_ascii=False, sort_keys=True)),
         "collector_sha256": sha(Path(__file__).read_bytes()), "collected_at": collected_at,
         "files": {name: sha((args.out / name).read_bytes()) for name in ("documents.jsonl", "sources.csv", "collection_report.json", "deferred_sources.jsonl")},
         "packages": {p: importlib.metadata.version(p) for p in ("httpx", "beautifulsoup4", "trafilatura")}})
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=Path("knowledge/source_catalog.json"))
    parser.add_argument("--out", type=Path, default=Path("knowledge/corpus_v1"))
    parser.add_argument("--review-dir", type=Path)
    args = parser.parse_args()
    asyncio.run(collect(args))


if __name__ == "__main__":
    main()
