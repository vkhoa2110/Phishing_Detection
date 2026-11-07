"""Lock and validate a future URL benchmark without fetching URLs or fitting models.

External-source labels remain provisional. A documented official origin is a
separate reference scope, never an automatically benign URL label. Registration
and declared reviewer IDs are audit trails, not authentication of people or truth.
"""
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import math
from pathlib import Path
import re
from urllib.parse import urlsplit, urlunsplit

import tldextract

from .message_data import read_jsonl, sha, spreadsheet_cell, write_json, write_jsonl
from .metrics import measure
from .url_diagnostics import projected_precision, wilson95

VERSION = "prospective-url-benchmark-1.0"
EXPOSURES = {"train", "validation", "historical_test", "adaptive"}
LABEL_STATUSES = {"external_source_provisional", "human_verified"}
STAGES = ("calibration", "test")
DEFAULT_QUOTAS = {"positive": 200, "negative": 400, "sources_per_class": 2}
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
SUFFIXES = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None,
                               include_psl_private_domains=True)


def utc(value):
    """Require an explicit UTC timestamp; never interpret a local naive time."""
    if not isinstance(value, str) or not value.endswith(("Z", "+00:00")):
        raise ValueError("Timestamps must explicitly use UTC (Z or +00:00).")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Invalid UTC timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("Timestamp must use UTC.")
    return parsed


def normalize_url(value):
    """Conservative identity key, not a website-safety check; no network access."""
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("URL must be a nonempty unpadded string.")
    if any(ord(c) < 33 or ord(c) == 127 for c in value) or "\\" in value:
        raise ValueError("Ambiguous whitespace/control/backslash in URL.")
    try:
        parts = urlsplit(value)
        if parts.scheme.lower() not in {"https", "http"} or not parts.hostname:
            raise ValueError("Only explicit HTTP(S) URLs are supported.")
        host = parts.hostname.rstrip(".").encode("idna").decode("ascii").lower()
        port = parts.port
        if "%" in host:
            raise ValueError("Scoped/encoded IP hosts are outside this benchmark's scope.")
        try:
            ip = ipaddress.ip_address(host)
            domain = ip.ipv4_mapped.compressed if ip.version == 6 and ip.ipv4_mapped else ip.compressed
            host = "[" + ip.compressed + "]" if ip.version == 6 else ip.compressed
        except ValueError:
            labels = host.split(".")
            # Browsers may parse shortened/octal/hexadecimal IPv4 differently
            # from ipaddress. Fail closed rather than invent an identity key.
            if re.fullmatch(r"(?:[0-9]+|0[xX][0-9a-fA-F]+)", labels[-1]):
                raise ValueError("Noncanonical numeric host is outside benchmark scope.")
            if len(labels) < 2 or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", x) for x in labels):
                raise ValueError("Invalid hostname.")
            parsed_domain = SUFFIXES(host)
            # Unknown/new suffixes are conservatively grouped by their last two
            # labels, rather than letting subdomains escape the overlap gate.
            domain = parsed_domain.top_domain_under_public_suffix or ".".join(labels[-2:])
        userinfo = parts.netloc.rpartition("@")[0] + "@" if "@" in parts.netloc else ""
        default = (parts.scheme.lower() == "http" and port == 80) or (parts.scheme.lower() == "https" and port == 443)
        netloc = userinfo + host + (":" + str(port) if port is not None and not default else "")
        return urlunsplit((parts.scheme.lower(), netloc, parts.path or "/", parts.query, "")), domain
    except (UnicodeError, ValueError) as exc:
        raise ValueError("Invalid URL: " + str(exc)) from exc


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _lock(path):
    path = Path(path).resolve(strict=True)
    if not path.is_file():
        raise ValueError("A lock must reference a file.")
    return {"path": str(path), "sha256": sha(path)}


def _normalizer_locks():
    package = Path(tldextract.__file__).parent
    return [_lock(Path(__file__)), *[_lock(p) for p in sorted(package.glob("*.py"))],
            _lock(package / ".tld_set_snapshot"),
            *[_lock(Path(__file__).parent / name) for name in ("message_data.py", "metrics.py", "url_diagnostics.py")]]


def _model_bundle(path):
    """A directory lock covers every weight/vocabulary file, not only its manifest."""
    path = Path(path).resolve(strict=True)
    files = [_lock(p) for p in sorted(path.rglob("*")) if p.is_file()] if path.is_dir() else [_lock(path)]
    if not files:
        raise ValueError("Empty model bundle.")
    return {"path": str(path), "files": files}


def _checked_read(directory, filename="protocol.json"):
    directory = Path(directory)
    expected = (directory / (filename + ".sha256")).read_text().strip()
    if not HEX64.fullmatch(expected) or sha(directory / filename) != expected:
        raise ValueError("Frozen registration/manifest metadata changed: " + filename)
    protocol = _read_json(directory / filename)
    if protocol.get("version") != VERSION:
        raise ValueError("Unexpected benchmark version.")
    for info in protocol["locks"]:
        if sha(info["path"]) != info["sha256"]:
            raise ValueError("Locked input/code changed: " + info["path"])
    for model in protocol.get("models", {}).values():
        root = Path(model["path"])
        if root.is_dir() and {str(p.resolve()) for p in root.rglob("*") if p.is_file()} != {p["path"] for p in model["files"]}:
            raise ValueError("Locked model bundle file list changed.")
    if "thresholds" in protocol and _read_json(protocol["thresholds"]["path"]) != protocol["policies"]:
        raise ValueError("Frozen threshold source differs from copied policies.")
    return protocol


def _exclusion_index(paths):
    index = {"urls": set(), "domains": set(), "campaigns": set()}
    exposures = set()
    for path in paths:
        for row in read_jsonl(path):
            if row.get("exposure") not in EXPOSURES:
                raise ValueError("Exclusions need train/validation/historical_test/adaptive exposure.")
            exposures.add(row["exposure"])
            if not row.get("url") and not row.get("domain") and not row.get("campaign"):
                raise ValueError("An exclusion needs URL, domain or campaign.")
            if row.get("url"):
                url, domain = normalize_url(row["url"])
                index["urls"].add(url)
                index["domains"].add(domain)
            if row.get("domain"):
                _, domain = normalize_url("https://" + row["domain"] + "/")
                if domain != row["domain"]:
                    raise ValueError("Exclusion domain must be the normalized registrable domain.")
                index["domains"].add(domain)
            if row.get("campaign"):
                if not isinstance(row["campaign"], str) or row["campaign"] != row["campaign"].strip():
                    raise ValueError("Exclusion campaign IDs must be unpadded strings.")
                index["campaigns"].add(row["campaign"].casefold())
    if exposures != EXPOSURES:
        raise ValueError("Declare exclusions for all four historical exposure groups.")
    return {key: sorted(values) for key, values in index.items()}


def register(out, *, exclusions, model_locks, corpus_lock, thresholds, collection_start,
             cutoff, quotas=None, now=None):
    """Register before future test collection; no incoming records are inspected."""
    out = Path(out)
    if out.exists():
        raise ValueError("Choose a new output directory; never overwrite a registration.")
    created = now or datetime.now(timezone.utc)
    start, boundary = utc(collection_start), utc(cutoff)
    if created.tzinfo is None or start >= boundary or created >= boundary:
        raise ValueError("Registration must precede the test cutoff; collection start must be earlier.")
    quota = dict(DEFAULT_QUOTAS if quotas is None else quotas)
    if set(quota) != set(DEFAULT_QUOTAS) or any(type(n) is not int or n < 1 for n in quota.values()):
        raise ValueError("Quotas must contain three positive integer fields.")
    if not model_locks or not all(isinstance(k, str) and k.strip() for k in model_locks):
        raise ValueError("At least one named model lock is required.")
    policies = _read_json(thresholds)
    if set(policies) != set(model_locks):
        raise ValueError("Frozen threshold names must match model-lock names.")
    for policy in policies.values():
        if set(policy) != {"low", "high"} or any(type(v) not in (int, float) or not math.isfinite(v) for v in policy.values()) or not 0 <= policy["low"] <= policy["high"] <= 1:
            raise ValueError("Frozen thresholds require 0 <= low <= high <= 1.")
    index = _exclusion_index(exclusions)
    models = {name: _model_bundle(path) for name, path in model_locks.items()}
    paths = [*map(Path, exclusions), Path(corpus_lock), Path(thresholds)]
    locks = [_lock(p) for p in paths] + [item for bundle in models.values() for item in bundle["files"]] + _normalizer_locks()
    protocol = {"version": VERSION, "created_at": created.astimezone(timezone.utc).isoformat(),
                "collection_start": collection_start, "test_cutoff": cutoff, "quotas_per_stage": quota,
                "models": models,
                "corpus": _lock(corpus_lock), "thresholds": _lock(thresholds), "policies": policies, "locks": locks,
                "tldextract_version": tldextract.__version__, "exclusion_index": index,
                "status": "registered_no_new_data_collected", "API_calls": 0,
                "scope": "URL fraud/abuse reference, not verification of present website safety.",
                "limitations": "Exclusion completeness, primary-source truth and reviewer identities are declarations; this tool does not authenticate them. Private PSL boundaries included; campaign unknowns cannot prove campaign isolation."}
    out.mkdir(parents=True)
    write_json(out / "protocol.json", protocol)
    (out / "protocol.json.sha256").write_text(sha(out / "protocol.json") + "\n")
    write_jsonl(out / "incoming_template.jsonl", [])
    return protocol


def _record(row, base, protocol, now):
    allowed = {"id", "url", "domain", "campaign", "collected_at", "source", "label",
               "label_status", "label_scope", "tier", "evidence", "reviewer_ids", "rationale"}
    required = allowed - {"tier", "rationale"}
    if set(row) - allowed or not required <= set(row):
        raise ValueError("Incoming record has missing/unknown fields; predictions are forbidden.")
    for key in ("id", "source", "domain"):
        if not isinstance(row[key], str) or not row[key].strip() or row[key] != row[key].strip():
            raise ValueError("Nonempty unpadded ID, source and domain required.")
    if row["campaign"] is not None and (not isinstance(row["campaign"], str) or not row["campaign"].strip() or row["campaign"] != row["campaign"].strip()):
        raise ValueError("Campaign must be an unpadded nonempty string or null when unknown.")
    if row["label_status"] not in LABEL_STATUSES or row["label_scope"] not in {"url_risk", "official_origin_reference"}:
        raise ValueError("Invalid label status/scope; no automatic gold promotion.")
    label = row["label"]
    if label is not None and (type(label) is not int or label not in (0, 1)):
        raise ValueError("Label must be 0, 1 or null.")
    if row["label_scope"] == "official_origin_reference" and label is not None:
        raise ValueError("Official origin does not establish a benign URL-risk label.")
    reviewers = row["reviewer_ids"]
    if not isinstance(reviewers, list) or any(not isinstance(v, str) or not v.strip() or v != v.strip() for v in reviewers) or len({v.casefold() for v in reviewers}) != len(reviewers):
        raise ValueError("Reviewer IDs must be distinct nonempty strings.")
    if row["label_status"] == "human_verified" and (len(reviewers) < 2 or not row.get("rationale", "").strip()):
        raise ValueError("Human-verified records need two declared reviewers and a rationale.")
    key, domain = normalize_url(row["url"])
    if row["domain"] != domain:
        raise ValueError("Declared domain does not match the URL's registrable domain.")
    collected = utc(row["collected_at"])
    if collected < utc(protocol["collection_start"]) or collected > now:
        raise ValueError("Collection date is outside the registered window or in the future.")
    stage = "calibration" if collected < utc(protocol["test_cutoff"]) else "test"
    evidence = row["evidence"]
    if not isinstance(evidence, dict) or set(evidence) != {"url", "publisher", "kind", "published_at", "snapshot_path", "snapshot_sha256"}:
        raise ValueError("Evidence requires primary HTTPS metadata and a local snapshot/hash.")
    evidence_url, _ = normalize_url(evidence["url"])
    if not evidence_url.startswith("https://") or "@" in urlsplit(evidence_url).netloc or evidence["kind"] != "primary" or not isinstance(evidence["publisher"], str) or not evidence["publisher"].strip():
        raise ValueError("Evidence must name a primary publisher and HTTPS URL without userinfo.")
    if utc(evidence["published_at"]) > collected:
        raise ValueError("Evidence postdates the claimed collection time.")
    digest = evidence["snapshot_sha256"]
    if not isinstance(digest, str) or not HEX64.fullmatch(digest):
        raise ValueError("Invalid evidence snapshot SHA-256.")
    snapshot = (base / evidence["snapshot_path"]).resolve(strict=True)
    if not snapshot.is_file() or not snapshot.stat().st_size or sha(snapshot) != digest:
        raise ValueError("Evidence snapshot is absent or does not match its hash.")
    return {**row, "normalized_url": key, "stage": stage,
            "campaign_key": row["campaign"].casefold() if row["campaign"] is not None else None,
            "evidence": {**evidence, "snapshot_path": str(snapshot)}}


def _status(rows, protocol):
    status = {}
    quota = protocol["quotas_per_stage"]
    for stage in STAGES:
        selected = [r for r in rows if r["stage"] == stage]
        verified = [r for r in selected if r["label_scope"] == "url_risk" and r["label_status"] == "human_verified" and r["label"] is not None]
        counts = Counter(str(r["label"]) for r in verified)
        sources = {str(label): sorted({r["source"].casefold() for r in verified if r["label"] == label}) for label in (0, 1)}
        unknown_campaign = sum(r["campaign"] is None for r in verified)
        blockers = []
        if counts["1"] < quota["positive"]:
            blockers.append("insufficient_verified_positives")
        if counts["0"] < quota["negative"]:
            blockers.append("insufficient_verified_negatives")
        if any(len(sources[str(label)]) < quota["sources_per_class"] for label in (0, 1)):
            blockers.append("insufficient_class_source_diversity")
        if unknown_campaign:
            blockers.append("unresolved_campaign_isolation")
        status[stage] = {"ready": not blockers, "records": len(selected), "verified_class_counts": dict(counts),
                         "verified_sources_by_class": sources, "unknown_verified_campaigns": unknown_campaign,
                         "provisional_records": sum(r["label_status"] == "external_source_provisional" for r in selected),
                         "official_origin_references": sum(r["label_scope"] == "official_origin_reference" for r in selected),
                         "blockers": blockers}
    return {"ready": all(v["ready"] for v in status.values()), "stages": status,
            "note": "Readiness verifies declared metadata/quota constraints, not true labels, representative sampling, or deployment quality."}


def _blind(path, rows):
    fields = ["id", "url", "collected_at", "evidence_url", "publisher", "snapshot_path", "label", "rationale", "reviewer_id"]
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in sorted(rows, key=lambda r: hashlib.sha256(("blind|" + r["id"]).encode()).hexdigest()):
            values = {"id": row["id"], "url": row["url"], "collected_at": row["collected_at"],
                      "evidence_url": row["evidence"]["url"], "publisher": row["evidence"]["publisher"],
                      "snapshot_path": row["evidence"]["snapshot_path"]}
            writer.writerow({k: spreadsheet_cell(str(values.get(k, ""))) for k in fields})


def prepare(protocol_dir, incoming, out, *, now=None):
    out, incoming = Path(out), Path(incoming).resolve(strict=True)
    if out.exists():
        raise ValueError("Choose a new output directory; preserve old packs/reviews.")
    protocol = _checked_read(protocol_dir)
    current = now or datetime.now(timezone.utc)
    rows = [_record(row, incoming.parent, protocol, current) for row in read_jsonl(incoming)]
    if len({r["id"] for r in rows}) != len(rows):
        raise ValueError("Duplicate incoming IDs.")
    # One registrable domain/campaign is one observation cluster, never split by stage.
    groups = {stage: {key: {r[key] for r in rows if r["stage"] == stage and r[key] is not None}
                      for key in ("normalized_url", "domain", "campaign_key")} for stage in STAGES}
    for key in ("normalized_url", "domain", "campaign_key"):
        if groups["calibration"][key] & groups["test"][key]:
            raise ValueError("Cross-stage " + key + " leakage.")
    if len({r["normalized_url"] for r in rows}) != len(rows):
        raise ValueError("Duplicate normalized URLs.")
    if len({r["domain"] for r in rows}) != len(rows):
        raise ValueError("Use one URL per registrable domain; quota counts independent domains.")
    index = {k: set(v) for k, v in protocol["exclusion_index"].items()}
    accepted, excluded = [], []
    for row in rows:
        reasons = [name for name, key in (("urls", "normalized_url"), ("domains", "domain"), ("campaigns", "campaign_key")) if row[key] in index[name]]
        (excluded if reasons else accepted).append({**row, "exclusion_reasons": reasons} if reasons else row)
    readiness = _status(accepted, protocol)
    snapshot_locks = [_lock(r["evidence"]["snapshot_path"]) for r in rows]
    manifest = {"version": VERSION, "created_at": current.astimezone(timezone.utc).isoformat(),
                "protocol_dir": str(Path(protocol_dir).resolve()), "protocol_sha256": sha(Path(protocol_dir) / "protocol.json"),
                "incoming": _lock(incoming), "locks": [*protocol["locks"], _lock(incoming), *snapshot_locks],
                "readiness": readiness, "accepted": len(accepted), "excluded_historical": len(excluded),
                "historical_exclusions_are_regression_not_future_test": True, "API_calls": 0}
    out.mkdir(parents=True)
    write_jsonl(out / "records.jsonl", accepted)
    write_jsonl(out / "excluded_regression.jsonl", excluded)
    for stage in STAGES:
        _blind(out / (stage + "_blind_review.csv"), [r for r in accepted if r["stage"] == stage])
    manifest["files"] = {p.name: sha(p) for p in out.iterdir() if p.is_file()}
    write_json(out / "manifest.json", manifest)
    (out / "manifest.json.sha256").write_text(sha(out / "manifest.json") + "\n")
    return manifest


def verify(pack):
    pack = Path(pack)
    manifest = _checked_read(pack, "manifest.json")
    protocol = _checked_read(manifest["protocol_dir"])
    if sha(Path(manifest["protocol_dir"]) / "protocol.json") != manifest["protocol_sha256"]:
        raise ValueError("Registered protocol changed.")
    for name, digest in manifest["files"].items():
        if sha(pack / name) != digest:
            raise ValueError("Frozen pack file changed: " + name)
    records = read_jsonl(pack / "records.jsonl")
    if _status(records, protocol) != manifest["readiness"]:
        raise ValueError("Stored readiness does not match the records.")
    return manifest, protocol, records


def report(pack, predictions, out, *, stage="calibration"):
    """Read already-saved scores using frozen policies; never tune or run a model."""
    out = Path(out)
    if out.exists():
        raise ValueError("Choose a new output directory.")
    manifest, protocol, records = verify(pack)
    if stage not in STAGES:
        raise ValueError("Invalid stage.")
    if stage == "test" and not manifest["readiness"]["ready"]:
        raise ValueError("Future test reporting is blocked until both stages satisfy the human-label gate.")
    chosen = [r for r in records if r["stage"] == stage and r["label_scope"] == "url_risk" and r["label"] is not None]
    saved = read_jsonl(predictions)
    lookup = {}
    for row in saved:
        if set(row) != {"id", "model", "score", "status"} or row["model"] not in protocol["models"] or row["status"] not in {"ok", "error"}:
            raise ValueError("Invalid saved prediction schema/model/status.")
        key = (row["id"], row["model"])
        if key in lookup:
            raise ValueError("Duplicate prediction.")
        if row["status"] == "ok" and (type(row["score"]) not in (int, float) or not math.isfinite(row["score"]) or not 0 <= row["score"] <= 1):
            raise ValueError("Invalid prediction score.")
        if row["status"] == "error" and row["score"] is not None:
            raise ValueError("Error predictions require a null score.")
        lookup[key] = row
    expected = {(r["id"], model) for r in chosen for model in protocol["models"]}
    if set(lookup) != expected:
        raise ValueError("Predictions must cover exactly the selected binary-reference records/models.")
    result = {}
    for model, policy in protocol["policies"].items():
        def metrics_for(selected):
            levels = []
            for row in selected:
                item = lookup[(row["id"], model)]
                score = item["score"]
                levels.append("UNKNOWN" if item["status"] == "error" else "HIGH" if score >= policy["high"] else "LOW" if score < policy["low"] else "UNKNOWN")
            m = measure([r["label"] for r in selected], levels)
            positives = sum(r["label"] for r in selected)
            negatives = len(selected) - positives
            if not positives or not negatives:
                # A one-class source cannot establish mixed-class Precision/F1.
                m["precision"], m["f1"] = None, None
            return {**m, "positive_references": positives, "negative_references": negatives,
                    "recall_wilson95": wilson95(m["tp"], positives),
                    "fpr_wilson95": wilson95(m["fp"], negatives),
                    "ppv_at_assumed_prior": {str(p): projected_precision(m["recall"], m["false_positive_rate"], p) for p in (.001, .01, .05)}}
        groups = {}
        for status in sorted(LABEL_STATUSES):
            selected = [r for r in chosen if r["label_status"] == status]
            groups[status] = {**metrics_for(selected), "by_source": {
                source: metrics_for([r for r in selected if r["source"].casefold() == source])
                for source in sorted({r["source"].casefold() for r in selected})}}
        result[model] = groups
    summary = {"version": VERSION, "stage": stage, "metrics": result, "pack_manifest_sha256": sha(Path(pack) / "manifest.json"),
               "predictions": _lock(predictions), "API_calls": 0, "threshold_selection": "none; policies frozen at registration",
               "caveat": "Wilson assumes independent observations, not clustered URLs; intervals omit label/source/time uncertainty. PPV is a prior-sensitivity scenario assuming conditional rates transfer, not measured prevalence or calibrated individual risk. Provisional and human-declared labels are separate; no deployment-quality claim."}
    out.mkdir(parents=True)
    write_json(out / "summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    register_parser = sub.add_parser("register")
    register_parser.add_argument("--out", type=Path, required=True)
    register_parser.add_argument("--exclusions", type=Path, action="append", required=True)
    register_parser.add_argument("--model-lock", action="append", required=True, metavar="NAME=FILE")
    register_parser.add_argument("--corpus-lock", type=Path, required=True)
    register_parser.add_argument("--thresholds", type=Path, required=True)
    register_parser.add_argument("--collection-start", required=True)
    register_parser.add_argument("--cutoff", required=True)
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("--protocol", type=Path, required=True)
    prepare_parser.add_argument("--incoming", type=Path, required=True)
    prepare_parser.add_argument("--out", type=Path, required=True)
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--pack", type=Path, required=True)
    report_parser = sub.add_parser("report")
    report_parser.add_argument("--pack", type=Path, required=True)
    report_parser.add_argument("--predictions", type=Path, required=True)
    report_parser.add_argument("--stage", choices=STAGES, default="calibration")
    report_parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.action == "register":
            models = {}
            for declaration in args.model_lock:
                name, path = declaration.split("=", 1)
                if name in models:
                    raise ValueError("Duplicate model-lock name.")
                models[name] = Path(path)
            result = register(args.out, exclusions=args.exclusions, model_locks=models, corpus_lock=args.corpus_lock,
                              thresholds=args.thresholds, collection_start=args.collection_start, cutoff=args.cutoff)
            message = {"status": result["status"], "protocol": str(args.out), "API_calls": 0}
        elif args.action == "prepare":
            result = prepare(args.protocol, args.incoming, args.out)
            message = {"readiness": result["readiness"], "accepted": result["accepted"], "excluded_historical": result["excluded_historical"], "API_calls": 0}
        elif args.action == "verify":
            result, _, _ = verify(args.pack)
            message = {"verified": True, "readiness": result["readiness"], "API_calls": 0}
        else:
            result = report(args.pack, args.predictions, args.out, stage=args.stage)
            message = {"summary": str(args.out / "summary.json"), "stage": result["stage"], "API_calls": 0}
        print(json.dumps(message, ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(2, f"Prospective benchmark stopped: {exc}\n")


if __name__ == "__main__":
    main()
