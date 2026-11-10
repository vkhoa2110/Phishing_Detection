"""One academic-use Community Feed snapshot, unscored provisional review only.

Never fetch listed URLs. No retries, redirects, TLS bypass, model inference,
training, auto-blacklist or promotion to independently verified labels.
"""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.request

from evaluation.data.sms import read_jsonl, sha, spreadsheet_cell, write_json, write_jsonl
from evaluation.data.prospective_urls import _checked_read, normalize_url

from app.core.settings import ROOT
FEED = "https://raw.githubusercontent.com/openphish/public_feed/refs/heads/main/feed.txt"
SOURCES = {"feed_page": "https://openphish.com/phishing_feeds.html",
           "terms": "https://openphish.com/terms.html", "feed": FEED}
LIMIT = 200
MAX_BYTES = 2_000_000
SELECTION = "sha256(openphish-candidate-v1|normalized_url) ascending; first URL per private-PSL domain; cap 200"


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def candidate_rows(raw, exclusions, observed_at):
    """Offline selection, no score/model/labels beyond provisional source label."""
    historical = set(exclusions["domains"])
    seen, valid = set(), []
    counts = {"nonempty_lines": 0, "invalid_urls": 0, "duplicate_normalized_urls": 0,
              "historical_domain_urls": 0, "eligible_unique_urls": 0}
    for number, line in enumerate(raw.decode("utf-8-sig", errors="strict").splitlines(), 1):
        if not line.strip():
            continue
        counts["nonempty_lines"] += 1
        try:
            normalized, domain = normalize_url(line.strip())
        except ValueError:
            counts["invalid_urls"] += 1
            continue
        if normalized in seen:
            counts["duplicate_normalized_urls"] += 1
            continue
        seen.add(normalized)
        if domain in historical:
            counts["historical_domain_urls"] += 1
            continue
        key = hashlib.sha256(("openphish-candidate-v1|" + normalized).encode()).hexdigest()
        valid.append((key, normalized, domain, number))
    counts["eligible_unique_urls"] = len(valid)
    domains, selected = set(), []
    for key, url, domain, line_number in sorted(valid):
        if domain in domains:
            continue
        domains.add(domain)
        if len(selected) < LIMIT:
            selected.append({"id": "openphish-review-" + key[:16], "url": url, "domain": domain,
                "source": "OpenPhish Community Feed", "source_label": 1,
                "label_status": "external_source_provisional", "human_verified": False,
                "reviewer_ids": [], "campaign": None, "campaign_status": "unknown",
                "observed_at": observed_at, "source_first_seen_at": None, "source_published_at": None,
                "evidence_feed_url": FEED, "snapshot_path": "feed.raw.txt", "snapshot_line": line_number,
                "selection_sha256": key, "prospective_eligible": False,
                "eligibility_blockers": ["unverified_source_label", "unknown_campaign", "unknown_source_first_seen",
                                         "single_positive_source_only", "no_negative_controls"],
                "model_scored": False})
    counts.update(eligible_unique_domains=len(domains), selected=len(selected),
                  selected_unique_domains=len({r["domain"] for r in selected}),
                  human_verified=0, prospective_eligible=0, model_scored=0)
    return selected, counts


def prepare(out, registration):
    out, registration = Path(out), Path(registration).resolve()
    if out.exists():
        raise ValueError("Choose a new output directory; never overwrite a snapshot.")
    protocol = _checked_read(registration)
    out.mkdir(parents=True)
    write_json(out / "exclusions.json", protocol["exclusion_index"])
    write_json(out / "protocol.json", {"version": "openphish-candidates-1.0", "registered_at": now_utc(),
        "sources": SOURCES, "selection": SELECTION, "maximum_unique_domains": LIMIT,
        "maximum_response_bytes": MAX_BYTES, "network_requests_max": 3, "requests_per_url": 1,
        "fetch_listed_urls": False, "model_inference": False, "training": False,
        "research_scope": "personal academic research only; no operational, business or commercial use",
        "distribution": "raw snapshot, URLs and derivatives stay local/ignored; no publication or redistribution",
        "label_scope": "external_source_provisional; not human labels, test gold or first-seen evidence",
        "registration_path": str(registration),
        "registration_sha256": sha(registration / "protocol.json"),
        "exclusions_sha256": sha(out / "exclusions.json"),
        "source_sha256": sha(Path(__file__)),
        "normalizer_sha256": sha(ROOT / "evaluation/data/prospective_urls.py")})


def check_lock(out):
    protocol = json.loads((out / "protocol.json").read_text())
    expected = {"sources": SOURCES, "selection": SELECTION, "maximum_unique_domains": LIMIT,
                "source_sha256": sha(Path(__file__)), "exclusions_sha256": sha(out / "exclusions.json"),
                "normalizer_sha256": sha(ROOT / "evaluation/data/prospective_urls.py")}
    if any(protocol[key] != value for key, value in expected.items()):
        raise ValueError("Registered source, exclusions or selection policy changed.")
    registration = Path(protocol["registration_path"])
    if sha(registration / "protocol.json") != protocol["registration_sha256"]:
        raise ValueError("Historical registration changed.")
    _checked_read(registration)
    return protocol


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Redirect refused; use only the official documented endpoint.")


def fetch_official(url):
    if url not in SOURCES.values():
        raise ValueError("Only the three official fixed source endpoints may be fetched.")
    opener = urllib.request.build_opener(NoRedirect)
    request = urllib.request.Request(url, headers={"User-Agent": "AcademicPhishingResearch/1.0", "Accept": "text/plain,text/html"})
    started = now_utc()
    with opener.open(request, timeout=30) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError("Unexpected HTTP status/endpoint.")
        raw = response.read(MAX_BYTES + 1)
        if not raw or len(raw) > MAX_BYTES:
            raise ValueError("Empty or oversized official response.")
        return raw, {"url": url, "request_started_at": started, "retrieved_at": now_utc(),
                     "status": response.status, "response_headers": dict(response.headers),
                     "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def fetch(out):
    out = Path(out)
    check_lock(out)
    if (out / "fetch_started.json").exists():
        raise ValueError("Fetch already started; do not retry or overwrite this snapshot.")
    write_json(out / "fetch_started.json", {"started_at": now_utc(), "requests_max": 3})
    journal = []
    try:
        for name, url in SOURCES.items():
            raw, metadata = fetch_official(url)
            filename = name + (".raw.txt" if name == "feed" else ".raw.html")
            (out / filename).write_bytes(raw)
            journal.append({**metadata, "file": filename})
            write_json(out / "retrieval.json", journal)
        observed_at = journal[-1]["retrieved_at"]
        rows, counts = candidate_rows((out / "feed.raw.txt").read_bytes(),
                                      json.loads((out / "exclusions.json").read_text()), observed_at)
        write_jsonl(out / "candidates.jsonl", rows)
        with (out / "blind_review.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            fields = ["id", "url", "observed_at", "snapshot_line", "label", "rationale", "reviewer_id", "campaign"]
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow({name: spreadsheet_cell(str(row[name])) if name in row and row[name] is not None else ""
                                 for name in fields})
        write_json(out / "summary.json", {"completed": True, "source": "OpenPhish Community Feed", "counts": counts,
            "selection": SELECTION, "observed_at": observed_at, "source_first_seen_at": None,
            "prospective_ready": False, "API_calls": 0, "model_inference": 0, "listed_URL_requests": 0,
            "terms_url": SOURCES["terms"], "no_redistribution": True})
        names = ["protocol.json", "exclusions.json", "fetch_started.json", "retrieval.json", "feed_page.raw.html",
                 "terms.raw.html", "feed.raw.txt", "candidates.jsonl", "blind_review.csv", "summary.json"]
        write_json(out / "result_hashes.json", {name: sha(out / name) for name in names})
        verify(out)
        return {"completed": True, "counts": counts, "raw_urls_printed": False}
    except Exception as exc:
        # Do not log an exception message that might contain a URL or response body.
        write_json(out / "failure.json", {"failed_at": now_utc(), "exception_type": type(exc).__name__,
            "HTTP_status": getattr(exc, "code", None), "completed_official_requests": len(journal), "retry": False})
        raise


def verify(out):
    out = Path(out)
    check_lock(out)
    for name, expected in json.loads((out / "result_hashes.json").read_text()).items():
        if sha(out / name) != expected:
            raise ValueError("Saved result changed: " + name)
    retrieval = json.loads((out / "retrieval.json").read_text())
    if [item["url"] for item in retrieval] != list(SOURCES.values()):
        raise ValueError("Official retrieval provenance differs.")
    for item in retrieval:
        if sha(out / item["file"]) != item["sha256"]:
            raise ValueError("Source snapshot hash differs.")
    rows, counts = candidate_rows((out / "feed.raw.txt").read_bytes(),
        json.loads((out / "exclusions.json").read_text()), retrieval[-1]["retrieved_at"])
    if rows != read_jsonl(out / "candidates.jsonl") or counts != json.loads((out / "summary.json").read_text())["counts"]:
        raise ValueError("Offline candidate selection differs.")
    write_json(out / "verification.json", {"passed": True, "candidates_checked": len(rows),
        "network_requests": 0, "model_inference": 0, "prospective_eligible": 0, "source_labels_provisional": True})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "fetch", "verify"])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--registration", type=Path)
    args = parser.parse_args()
    if args.action == "prepare":
        if args.registration is None:
            parser.error("prepare requires --registration")
        prepare(args.out, args.registration)
    else:
        result = {"fetch": fetch, "verify": verify}[args.action](args.out)
        print(json.dumps(result or {"verified": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()
