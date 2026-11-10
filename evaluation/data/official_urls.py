"""Collect preselected official-origin references, never benign risk labels.

No models, LLMs, training, arbitrary crawl or form submissions are involved.
Selection is locked before collection. All failed selections remain in the log.
"""
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import time
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import requests

from evaluation.data.sms import read_jsonl, sha, spreadsheet_cell, write_json, write_jsonl
from evaluation.data.prospective_urls import normalize_url

VERSION = "official-url-reference-1.0"
USER_AGENT = "PhishLens-Academic-Reference/1.0"
REVIEW_FIELDS = ["id", "url", "publisher", "tags", "origin_assessment", "risk_label", "rationale", "reviewer_id"]
TAGS = {"login", "password_reset", "payment", "query", "long_path", "article", "homepage", "university", "government", "bank", "utility", "support"}


def stamp():
    return datetime.now(timezone.utc).isoformat()


class Document(HTMLParser):
    def __init__(self, html, base):
        super().__init__(convert_charrefs=True)
        self.base, self.links, self.title, self._title, self._anchor = base, [], "", False, None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "title":
            self._title = True
        if tag == "a" and attrs.get("href"):
            self._anchor = [urljoin(self.base, attrs["href"]), ""]

    def handle_data(self, data):
        if self._title:
            self.title += data
        if self._anchor is not None:
            self._anchor[1] += data

    def handle_endtag(self, tag):
        if tag == "title":
            self._title = False
        if tag == "a" and self._anchor is not None:
            self.links.append(tuple(self._anchor))
            self._anchor = None


def checked_url(url, hosts):
    normalized, _ = normalize_url(url)
    parts = urlsplit(normalized)
    if parts.scheme != "https" or parts.username is not None or parts.password is not None or parts.port is not None or parts.hostname not in hosts:
        raise ValueError("Only predeclared HTTPS hosts without credentials or custom ports may be fetched.")
    return normalized


def validate_selection(plan):
    if plan.get("version") != VERSION or plan.get("label_policy") != "official_origin_reference_not_benign_gold":
        raise ValueError("Unexpected reference plan or label policy.")
    selections = plan["selections"]
    if len(selections) < 24 or len({r["id"] for r in selections}) != len(selections):
        raise ValueError("Lock at least 24 distinct reference IDs.")
    urls, domains = set(), set()
    for row in selections:
        if set(row) != {"id", "url", "source_url", "publisher", "region", "tags"}:
            raise ValueError("Selection fields must not include labels, predictions or scores.")
        checked_url(row["url"], plan["allowed_hosts"])
        checked_url(row["source_url"], plan["allowed_hosts"])
        key, domain = normalize_url(row["url"])
        if key in urls or not row["publisher"] or row["region"] not in {"VN", "international"}:
            raise ValueError("Repeated URL or invalid selection metadata.")
        if not row["tags"] or set(row["tags"]) - TAGS:
            raise ValueError("Unknown route tags.")
        urls.add(key)
        domains.add(domain)
    if len(domains) < 8:
        raise ValueError("Lock at least eight registrable domains.")
    if set(plan["minimum_success_coverage"]) != {"records", "domains", "tags"}:
        raise ValueError("Declare success coverage before collection.")
    return plan


def lock_selection(out, plan, registration):
    out = Path(out)
    if out.exists():
        raise ValueError("Never replace an existing reference selection.")
    plan = validate_selection(dict(plan))
    registration = Path(registration).resolve(strict=True)
    protocol = json.loads(registration.read_text())
    if not all(k in protocol["exclusion_index"] for k in ("urls", "domains", "campaigns")):
        raise ValueError("Registration lacks overlap exclusions.")
    plan["locked_at"] = stamp()
    plan["collector_sha256"] = sha(__file__)
    plan["registration"] = {"path": str(registration), "sha256": sha(registration)}
    out.mkdir(parents=True)
    write_json(out / "selection.json", plan)
    (out / "selection.json.sha256").write_text(sha(out / "selection.json") + "\n")
    return plan


def read_selection(out):
    out = Path(out)
    if sha(out / "selection.json") != (out / "selection.json.sha256").read_text().strip():
        raise ValueError("Locked selection changed.")
    plan = validate_selection(json.loads((out / "selection.json").read_text()))
    if plan["collector_sha256"] != sha(__file__):
        raise ValueError("Collector changed after selection lock.")
    if sha(plan["registration"]["path"]) != plan["registration"]["sha256"]:
        raise ValueError("Locked registration changed.")
    return plan


def overlap(url, index):
    normalized, domain = normalize_url(url)
    hit_url, hit_domain = normalized in index["urls"], domain in index["domains"]
    return {"url_overlap": hit_url, "domain_overlap": hit_domain, "campaign_overlap": None,
            "campaign": None, "assigned_pool": "regression" if hit_url or hit_domain else "new_origin_reference_review_only",
            "prospective_eligible": False,
            "reason": "Official-origin references have no URL-risk label; unknown campaign does not establish isolation."}


class Fetcher:
    """A small allowlisted GET collector; robots errors fail closed except 404/410."""
    def __init__(self, hosts, raw_dir, *, delay=1.0, timeout=12):
        self.hosts, self.raw_dir, self.delay, self.timeout = hosts, Path(raw_dir), delay, timeout
        self.robots, self.cache, self.last = {}, {}, {}
        self.raw_dir.mkdir(parents=True, exist_ok=False)

    def _get(self, url, max_bytes):
        chain = []
        for _ in range(5):
            url = checked_url(url, self.hosts)
            host = urlsplit(url).hostname
            time.sleep(max(0, self.delay - (time.monotonic() - self.last.get(host, 0))))
            self.last[host] = time.monotonic()
            with requests.get(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain;q=0.9,*/*;q=0.1"}, timeout=self.timeout,
                              allow_redirects=False, stream=True) as response:
                chain.append({"url": url, "status": response.status_code})
                if response.status_code in {301, 302, 303, 307, 308}:
                    url = checked_url(urljoin(url, response.headers.get("Location", "")), self.hosts)
                    continue
                body = b""
                for chunk in response.iter_content(65536):
                    body += chunk
                    if len(body) > max_bytes:
                        raise ValueError("Response exceeds the locked size limit.")
                return {"url": url, "status": response.status_code, "body": body,
                        "content_type": response.headers.get("Content-Type", ""), "encoding": response.encoding or "utf-8",
                        "retrieved_at": stamp(), "redirect_chain": chain}
        raise ValueError("Too many redirects.")

    def fetch(self, source_url):
        source_url = checked_url(source_url, self.hosts)
        if source_url in self.cache:
            return self.cache[source_url]
        origin = "https://" + urlsplit(source_url).hostname
        if origin not in self.robots:
            robot_url = origin + "/robots.txt"
            robot = self._get(robot_url, 262144)
            path = self.raw_dir / (hashlib.sha256(robot_url.encode()).hexdigest()[:20] + ".robots.txt")
            path.write_bytes(robot["body"])
            metadata = {k: v for k, v in robot.items() if k not in {"body", "encoding"}}
            metadata.update({"snapshot_path": str(path.resolve()), "snapshot_sha256": sha(path)})
            parser = RobotFileParser()
            if robot["status"] in {404, 410}:
                parser.parse([])
            elif robot["status"] == 200:
                parser.parse(robot["body"].decode("utf-8", errors="replace").splitlines())
            else:
                raise ValueError("Robots unavailable; collector fails closed: " + str(robot["status"]))
            self.robots[origin] = (parser, metadata)
        parser, robot_metadata = self.robots[origin]
        if not parser.can_fetch(USER_AGENT, source_url):
            raise ValueError("Robots disallows this source URL.")
        result = self._get(source_url, 2097152)
        result["robots"] = robot_metadata
        path = self.raw_dir / (hashlib.sha256(source_url.encode()).hexdigest()[:20] + ".html")
        path.write_bytes(result["body"])
        result.update({"snapshot_path": str(path.resolve()), "snapshot_sha256": sha(path)})
        self.cache[source_url] = result
        return result


def publication(selection, fetched):
    """A served official document is weak origin evidence, not a risk verdict."""
    if fetched["status"] != 200 or "html" not in fetched["content_type"].lower():
        raise ValueError("Source did not return an HTML document with status 200.")
    document = Document(fetched["body"].decode(fetched["encoding"], errors="replace"), fetched["url"])
    target = normalize_url(selection["url"])[0]
    for href, anchor in document.links:
        try:
            if normalize_url(href)[0] == target:
                return {"relation": "published_link", "href": href, "anchor": " ".join(anchor.split()[:8]),
                        "title": " ".join(document.title.split()[:12])}
        except ValueError:
            pass
    if normalize_url(selection["source_url"])[0] == target:
        return {"relation": "self_served_document", "href": selection["url"], "anchor": "",
                "title": " ".join(document.title.split()[:12])}
    raise ValueError("Selected route is not linked from the declared source document.")


def collect(out, raw_dir, *, fetcher=None):
    out = Path(out)
    if (out / "attempts.jsonl").exists():
        raise ValueError("This selection was already collected; never retry or replace failures in place.")
    plan = read_selection(out)
    index = json.loads(Path(plan["registration"]["path"]).read_text())["exclusion_index"]
    fetcher = fetcher or Fetcher(plan["allowed_hosts"], raw_dir)
    records, attempts = [], []
    for order, row in enumerate(plan["selections"]):
        attempt = {"id": row["id"], "source_url": row["source_url"], "started_at": stamp()}
        try:
            result = fetcher.fetch(row["source_url"])
            route = publication(row, result)
            normalized, domain = normalize_url(row["url"])
            evidence = {"source_url": row["source_url"], "publisher": row["publisher"], "retrieved_at": result["retrieved_at"],
                        "final_url": result["url"], "status_code": result["status"], "snapshot_path": result["snapshot_path"],
                        "snapshot_sha256": result["snapshot_sha256"], "route_publication": route,
                        "redirect_chain": result["redirect_chain"], "robots": result["robots"]}
            records.append({**row, "normalized_url": normalized, "domain": domain, "selection_order": order,
                            "label_scope": "official_origin_reference", "label": None, "label_status": "assistant_curated",
                            "reviewer_ids": [], "evidence": evidence, "exposure": overlap(row["url"], index)})
            attempt.update({"status": "collected", "snapshot_sha256": result["snapshot_sha256"]})
        except (requests.RequestException, ValueError, UnicodeError) as exc:
            attempt.update({"status": "failed", "error": str(exc)[:500]})
        attempts.append(attempt)
        write_jsonl(out / "attempts.jsonl", attempts)
        write_jsonl(out / "records.jsonl", records)
        print(row["id"], attempt["status"], attempt.get("error", ""), flush=True)
    with (out / "review.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        for row in records:
            writer.writerow({"id": row["id"], "url": spreadsheet_cell(row["url"]), "publisher": row["publisher"], "tags": "|".join(row["tags"])})
    tags = Counter(tag for row in records for tag in row["tags"])
    domains = {r["domain"] for r in records}
    required = plan["minimum_success_coverage"]
    summary = {"version": VERSION, "locked_selection_sha256": sha(out / "selection.json"), "finished_at": stamp(),
               "selected": len(plan["selections"]), "collected": len(records), "failed": len(attempts) - len(records),
               "domains": len(domains), "regions": dict(Counter(r["region"] for r in records)), "tags": dict(tags),
               "domain_list": sorted(domains), "pools": dict(Counter(r["exposure"]["assigned_pool"] for r in records)),
               "missing_route_tags": sorted(set(required["tags"]) - tags.keys()),
               "coverage_met": len(records) >= required["records"] and len(domains) >= required["domains"] and not (set(required["tags"]) - tags.keys()),
               "risk_labels": 0, "model_calls": 0, "LLM_calls": 0,
               "limitation": "Assistant-curated official-origin references, not independently benign gold or a prospective test. Source identity is curated; a served page/link does not establish current website safety or URL content legitimacy."}
    write_json(out / "collection.json", summary)
    write_json(out / "collection_locks.json", {name: sha(out / name) for name in ("records.jsonl", "attempts.jsonl", "collection.json")})
    return summary


def verify(out):
    out = Path(out)
    plan = read_selection(out)
    for name, digest in json.loads((out / "collection_locks.json").read_text()).items():
        if sha(out / name) != digest:
            raise ValueError("Collected records/attempts/summary changed: " + name)
    selected = {r["id"]: r for r in plan["selections"]}
    index = json.loads(Path(plan["registration"]["path"]).read_text())["exclusion_index"]
    records, attempts = read_jsonl(out / "records.jsonl"), read_jsonl(out / "attempts.jsonl")
    if [r["id"] for r in attempts] != list(selected):
        raise ValueError("Collection attempts do not cover the locked selections in order.")
    for row in records:
        if row["label"] is not None or row["label_scope"] != "official_origin_reference" or row["label_status"] != "assistant_curated" or row["reviewer_ids"]:
            raise ValueError("Curated references cannot become risk labels or human gold in place.")
        if any(row[k] != v for k, v in selected[row["id"]].items()) or row["exposure"] != overlap(row["url"], index):
            raise ValueError("Selection metadata or overlap assignment changed.")
        evidence = row["evidence"]
        for snapshot in (evidence, evidence["robots"]):
            if sha(snapshot["snapshot_path"]) != snapshot["snapshot_sha256"]:
                raise ValueError("Evidence snapshot changed or missing.")
        result = {"body": Path(evidence["snapshot_path"]).read_bytes(), "encoding": "utf-8", "url": evidence["final_url"], "status": 200, "content_type": "text/html"}
        # Exact link relation/target can be recomputed without fetching again.
        if publication(row, result)["relation"] != evidence["route_publication"]["relation"]:
            raise ValueError("Publication relation does not match the saved snapshot.")
    return {"verified": True, "records": len(records), "attempts": len(attempts), "API_calls": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    lock = sub.add_parser("lock")
    lock.add_argument("--plan", required=True)
    lock.add_argument("--registration", required=True)
    lock.add_argument("--out", required=True)
    get = sub.add_parser("collect")
    get.add_argument("--out", required=True)
    get.add_argument("--raw-dir", required=True)
    check = sub.add_parser("verify")
    check.add_argument("--out", required=True)
    args = parser.parse_args()
    if args.command == "lock":
        result = lock_selection(args.out, json.loads(Path(args.plan).read_text()), args.registration)
        print(json.dumps({"locked": True, "selected": len(result["selections"])}, indent=2))
    elif args.command == "collect":
        print(json.dumps(collect(args.out, args.raw_dir), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(verify(args.out), indent=2))


if __name__ == "__main__":
    main()
