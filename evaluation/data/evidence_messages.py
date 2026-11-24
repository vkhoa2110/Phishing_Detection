"""Build a source-backed supplementary challenge, without inference or gold claims.

Source documents support provenance; reconstructed messages and historical URL
warnings never become observed specimens or current site-safety ground truth.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import io
from importlib.metadata import version as package_version
import json
from pathlib import Path
import re
import sys
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import zipfile

import tldextract

from app.core.settings import ROOT
from app.services.url.intake import inspect_url_intake
from evaluation.data.sms import normal, read_jsonl, sha, spreadsheet_cell, template, write_json, write_jsonl

VERSION = "evidence-message-challenge-1.0"
SEED = 20261118
ORIGINS = {"observed_exact", "observed_redacted", "documented_template", "paraphrased", "reconstructed", "self_authored"}
URL_STATUSES = {"historical_bad", "historical_defanged_target", "documented_service", "illustrative", "unverified"}
REFERENCE_STATUS = "assistant_evidence_design_not_gold"
SOURCE_DEFAULT = ROOT / "data/evaluation/evidence_messages_v1/sources.jsonl"
CASES_DEFAULT = ROOT / "data/evaluation/evidence_messages_v1/cases.jsonl"
SUFFIXES = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def canonical_source(value):
    p = urlsplit(value)
    if p.scheme not in {"https", "http"} or not p.hostname or p.username or p.password:
        raise ValueError("A public source HTTP(S) page without credentials is required.")
    # This is an evidence identity, not a URL request/redirect policy. Keep
    # article query IDs, remove only known tracking fields, and join web aliases.
    host = p.hostname.lower().removeprefix("www.")
    port = "" if p.port in (None, 80, 443) else ":" + str(p.port)
    query = sorted((k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                   if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"})
    return urlunsplit(("https", host + port, p.path.rstrip("/"), urlencode(query), ""))


def domains(urls):
    result = set()
    for value in urls:
        p = urlsplit(value if "://" in value else "https://" + value)
        host = (p.hostname or "").lower().rstrip(".")
        if host:
            e = SUFFIXES(host)
            result.add(e.top_domain_under_public_suffix or host)
    return sorted(result)


def url_key(value):
    """Normalized model-input overlap cue; not exact URI identity."""
    value = value.strip()
    return re.sub(r"(?i)^https?://", "", value).lower().rstrip("/")


def documented_target_present(value, content):
    full_uri = "://" in value
    head = r"(?<![\w])" if full_uri else r"(?<![\w@.\-])"
    tail = r"(?![\w/~%?#@&=+:\-]|\.[A-Za-z0-9])" if full_uri else r"(?![\w-]|\.[A-Za-z0-9])"
    matches = list(re.finditer(head + re.escape(value) + tail, content))
    if full_uri:
        return bool(matches)
    uri_spans = list(re.finditer(r"(?i)https?://[^\s<>\"']+", content))
    for match in matches:
        enclosing = next((uri for uri in uri_spans if uri.start() <= match.start() < uri.end()), None)
        if enclosing:
            try:
                if (urlsplit(enclosing.group()).hostname or "").casefold().rstrip(".") == value.casefold().rstrip("."):
                    return True
            except ValueError:
                pass
            continue
        # A bare target embedded in somebody else's scheme-less path or query
        # is not a source attribution of that hostname.
        prefix = re.split(r"\s", content[:match.start()])[-1]
        if not any(c in prefix for c in "/?&#=@"):
            return True
    return False


def validate_sources(rows, base=ROOT):
    sources = {}
    for source in rows:
        key = source["id"]
        if not isinstance(key, str) or not key or key in sources:
            raise ValueError("Unique nonempty source IDs are required.")
        canonical_source(source["url"])
        if not source.get("publisher") or not source.get("title") or source.get("verified_primary") is not True:
            raise ValueError("A verified primary publisher/title is required: " + key)
        path = Path(source["snapshot_path"])
        if not path.is_absolute(): path = Path(base) / path
        if not path.is_file() or sha(path) != source["snapshot_sha256"]:
            raise ValueError("Source snapshot missing or changed: " + key)
        content = normal(path.read_text(encoding="utf-8"))
        quote = source.get("evidence_excerpt", "")
        if not quote or normal(quote) not in content or len(quote.split()) > 25:
            raise ValueError("Source excerpt must match its snapshot and be at most25 words: " + key)
        for value in source.get("documented_urls", []):
            # Permit terminal punctuation, never a hostname/path prefix. Bare
            # hosts may be documented as hosts inside a full URI.
            if not documented_target_present(value, content):
                raise ValueError("Claimed URL is absent from its source snapshot: " + key)
        aliases = {canonical_source(source["url"])}
        aliases.update(canonical_source(u) for u in source.get("aliases", []) if u)
        sources[key] = {**source, "snapshot_path": str(path.resolve()),
                        "canonical_url": canonical_source(source["url"]), "document_keys": sorted(aliases)}
    if not sources: raise ValueError("At least one verified source is required.")
    return sources


def validate_cases(rows, sources):
    by_id, seen_text = {}, set()
    for original in rows:
        row = dict(original)
        key, text = row["id"], row["text"]
        normalized = normal(text).casefold()
        if not key or key in by_id or normalized in seen_text or not text.strip() or len(text) > 8000:
            raise ValueError("Duplicate/invalid message identity or text: " + key)
        if row.get("text_origin") not in ORIGINS:
            raise ValueError("Explicit message origin is required: " + key)
        if row.get("reference_status") != REFERENCE_STATUS or row.get("human_reviewed") is not False:
            raise ValueError("This builder accepts only explicit assistant design references, never human gold.")
        for field in ("label", "behavior_label"):
            if row.get(field) is not None and (type(row[field]) is not int or row[field] not in {0, 1}):
                raise ValueError("References must be0/1/null: " + key)
        if not row.get("source_ids") or any(s not in sources for s in row["source_ids"]):
            raise ValueError("Every case requires known source provenance: " + key)
        if not row.get("template_family") or not row.get("scenario") or not row.get("reference_basis"):
            raise ValueError("Scenario/template/reference basis missing: " + key)
        if not isinstance(row.get("campaign_ids", []), list):
            raise ValueError("Campaign hints must be an explicit list.")
        if row.get("behavior_label") == 1:
            q = row.get("behavior_quote", "")
            if not q or q not in text:
                raise ValueError("Positive behavior requires an exact action quotation: " + key)
        observed = row["text_origin"] in {"observed_exact", "observed_redacted", "documented_template"}
        if observed:
            quote = row.get("source_message_quote", "")
            artifacts = [normal(Path(sources[s]["snapshot_path"]).read_text()) for s in row["source_ids"]]
            if not quote or not any(normal(quote) in artifact for artifact in artifacts):
                raise ValueError("An observed/template quote must be in its source artifact: " + key)
            transformed = quote
            for change in row.get("substitutions", []):
                if not change.get("old") or change["old"] not in transformed:
                    raise ValueError("A redaction substitution is not reproducible: " + key)
                if change.get("kind") != "redaction" or not re.fullmatch(r"\[[A-Z_]+\]", change.get("new", "")):
                    raise ValueError("Only declared placeholder redactions preserve observed/template origin: " + key)
                if change["old"] == quote or len(change["old"].split()) > 8:
                    raise ValueError("Whole-message or long-prose replacement is not redaction: " + key)
                transformed = transformed.replace(change["old"], change["new"])
            if row["text_origin"] == "observed_exact" and row.get("substitutions"):
                raise ValueError("An observed_exact specimen cannot contain substitutions.")
            if row["text_origin"] == "observed_redacted" and not row.get("substitutions"):
                raise ValueError("A redacted specimen needs a transformation log.")
            if transformed != text:
                raise ValueError("Observed/template message differs beyond declared redactions: " + key)
        urls = inspect_url_intake(text, "text")["urls"]
        if row.get("urls") != urls:
            raise ValueError("Declared URLs disagree with current intake: " + key)
        evidence = row.get("url_evidence", [])
        if len({e["url"] for e in evidence}) != len(evidence) or {e["url"] for e in evidence} != set(urls):
            raise ValueError("Every message URL needs exactly one scoped evidence record: " + key)
        for e in evidence:
            if e.get("status") not in URL_STATUSES:
                raise ValueError("Invalid URL evidence scope: " + key)
            if e["status"] in {"historical_bad", "historical_defanged_target", "documented_service"}:
                source = sources.get(e.get("source_id"))
                if not source or e["source_id"] not in row["source_ids"]:
                    raise ValueError("URL evidence needs a linked source: " + key)
                documented = e.get("source_target") if e["status"] == "historical_defanged_target" else e["url"]
                if documented not in source.get("documented_urls", []):
                    raise ValueError("URL not literally documented; use unverified instead: " + key)
                if e["status"] == "historical_defanged_target" and (
                        "[.]" not in documented or documented.replace("[.]", ".") != e["url"]):
                    raise ValueError("Only exact, logged [.] restoration may use defanged target evidence.")
                expected = "service_workflow" if e["status"] == "documented_service" else "historical_scam_url"
                if source.get("url_scope") != expected:
                    raise ValueError("Source does not support that URL status: " + key)
            if e.get("current_safety_verified") is not False:
                raise ValueError("Historic/publication evidence is not current URL safety verification.")
        row["domains"] = domains(urls)
        row["source_document_keys"] = sorted({u for s in row["source_ids"] for u in sources[s]["document_keys"]})
        by_id[key] = row
        seen_text.add(normalized)
    for row in by_id.values():
        if row.get("base_id") and row["base_id"] not in by_id:
            raise ValueError("An injection/derived variant requires its base in the same inventory.")
    if not by_id: raise ValueError("Messages are required.")
    return list(by_id.values())


def connected_groups(rows, threshold=.75):
    """Recompute all leakage edges; never trust a supplied group/split value."""
    rows = sorted(rows, key=lambda r: r["id"])
    parent = list(range(len(rows)))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i
    edges = []
    def join(a, b, reason):
        edges.append({"left": rows[a]["id"], "right": rows[b]["id"], "reason": reason})
        x,y = find(a),find(b)
        if x != y: parent[max(x,y)] = min(x,y)
    seen = {}
    ids = {r["id"]:i for i,r in enumerate(rows)}
    words = []
    for i,row in enumerate(rows):
        tokens = template(row["text"]); words.append(set(tokens))
        hints = [("source_document",s) for s in row["source_document_keys"]]
        hints += [("domain",d) for d in row["domains"]]
        hints += [("campaign",c) for c in row.get("campaign_ids", [])]
        hints += [("template_family",row["template_family"]), ("exact_template"," ".join(tokens))]
        for hint in hints:
            if hint in seen: join(i,seen[hint],hint[0])
            else: seen[hint] = i
        if row.get("base_id"): join(i,ids[row["base_id"]],"derivation")
    for i,left in enumerate(words):
        if not left: continue
        for j in range(i):
            right=words[j]
            if right and len(left & right)/len(left | right) >= threshold:
                join(i,j,"near_template")
    members=defaultdict(list)
    for i,row in enumerate(rows): members[find(i)].append(row["id"])
    groups={member:"evidence-group-"+digest(sorted(cluster))[:16] for cluster in members.values() for member in cluster}
    return groups,edges


def assign_splits(rows, seed=SEED):
    groups,edges=connected_groups(rows)
    assigned=[]
    for row in rows:
        group=groups[row["id"]]
        fraction=int(digest([seed,group])[:16],16)/2**64
        assigned.append({**row,"group_id":group,"split":"dev" if fraction < .6 else "test"})
    lookup={r["id"]:r for r in assigned}
    if any(lookup[e["left"]]["split"] != lookup[e["right"]]["split"] for e in edges):
        raise ValueError("Leakage edge crosses the proposed split.")
    return assigned,edges


def corpus_overlap(sources, paths):
    known=defaultdict(list)
    documents=[]
    for path in paths:
        for row in read_jsonl(path):
            documents.append((str(path),row))
            for field in ("source_url","resolved_url","url"):
                if row.get(field): known[canonical_source(row[field])].append({"corpus":str(path),"document_id":row.get("id")})
    overlaps={}
    for key,source in sources.items():
        matches=[]
        for alias in source["document_keys"]:
            matches += [{**entry,"match":"source_url_or_alias"} for entry in known.get(alias,[])]
        excerpt=normal(source["evidence_excerpt"])
        for path,row in documents:
            if len(excerpt)>=50 and excerpt in normal(row.get("text","")):
                matches.append({"corpus":path,"document_id":row.get("id"),"match":"excerpt_text_possible_overlap"})
            if row.get("id") in source.get("known_corpus_document_ids",[]):
                matches.append({"corpus":path,"document_id":row.get("id"),"match":"manual_topical_overlap"})
        overlaps[key]=list({digest(m):m for m in matches}.values())
    return {"scope":"Exact source URLs/aliases, exact short excerpts, and declared topical matches; semantic overlap is not exhaustively detected", "sources":overlaps}


def historical_overlap(rows, archive):
    """Read only existing URL inventories; no model scores or SMS reserve."""
    if not archive or not Path(archive).is_file(): return {"checked":False,"reason":"URL archive unavailable; unseen status unknown"}
    lookup=defaultdict(lambda:defaultdict(set))
    target={url_key(u) for r in rows for u in r["urls"]}
    targets={d for r in rows for d in r["domains"]}
    with zipfile.ZipFile(archive) as bundle:
        for split in ("train","val","test"):
            with bundle.open("data/splits/url_"+split+".csv") as raw:
                for original in csv.DictReader(io.TextIOWrapper(raw,encoding="utf-8-sig")):
                    value=original["url"];key=url_key(value)
                    if key in target: lookup["url"][key].add(split)
                    for domain in domains([value]):
                        if domain in targets: lookup["domain"][domain].add(split)
    return {"checked":True,"archive_sha256":sha(archive),"archive":str(Path(archive).resolve()),
        "case_overlaps":{r["id"]:{"normalized_url_splits":sorted({s for u in r["urls"] for s in lookup["url"].get(url_key(u),())}),
            "domain_splits":sorted({s for d in r["domains"] for s in lookup["domain"].get(d,())})} for r in rows},
        "limits":"Normalization/domain overlap only; does not certify absence from LLM pretraining or other model data."}


def readiness(rows):
    result={"independent_gold_ready":False,"reference_status":REFERENCE_STATUS,
        "test_status":"locked_author_exposed_holdout_not_independent_blind",
        "heldout_model_inference":False,"classifier_API_calls":0,"URL_fetches":0,"splits":{}}
    for split in ("dev","test"):
        selected=[r for r in rows if r["split"]==split and not r.get("base_id")]
        pos=[r for r in selected if r["label"]==1]
        result["splits"][split]={"base_cases":len(selected),"labels":dict(Counter("UNKNOWN" if r["label"] is None else str(r["label"]) for r in selected)),
            "positive_URL_cases":sum(bool(r["urls"]) for r in pos),
            "positive_URL_components":len({r["group_id"] for r in pos if r["urls"]}),
            "positive_components":len({r["group_id"] for r in pos}),
            "positive_scenarios":dict(Counter(r["scenario"] for r in pos)),
            "origins":dict(Counter(r["text_origin"] for r in selected)),
            "diagnostic_strata_present":bool(pos) and any(r["label"]==0 for r in selected) and any(r["urls"] for r in pos)}
    result["limits"]=["Provisional design references; no human-gold claim", "Purposive challenge sample, not population accuracy", "Sources and all authored text already viewed by dataset builder", "New preregistration required before any diagnostic inference; no automatic model run"]
    return result


def prepare(sources_path, cases_path, out, *, corpus_paths=(), archive=None):
    out=Path(out)
    if out.exists(): raise ValueError("Choose fresh output; preserve existing labels/splits/review sheets.")
    if archive is not None and not Path(archive).is_file():
        raise ValueError("The explicitly supplied URL archive is missing.")
    sources=validate_sources(read_jsonl(sources_path))
    cases=validate_cases(read_jsonl(cases_path),sources)
    rows,edges=assign_splits(cases)
    rows=sorted(rows,key=lambda r:digest([SEED,"input_order",r["id"]]))
    overlaps=corpus_overlap(sources,corpus_paths)
    historical=historical_overlap(rows,archive)
    out.mkdir(parents=True)
    write_jsonl(out/"cases.jsonl",rows)
    write_jsonl(out/"leakage_edges.jsonl",edges)
    write_json(out/"corpus_overlap.json",overlaps)
    write_json(out/"URL_history_overlap.json",historical)
    for split in ("dev","test"):
        write_jsonl(out/(split+"_inputs.jsonl"),[{"id":r["id"],"text":r["text"]} for r in rows if r["split"]==split])
    fields=["id","text","label","behavior_label","notes","reviewer_id"]
    for side in ("a","b"):
        with (out/f"annotator_{side}.csv").open("w",newline="",encoding="utf-8-sig") as f:
            writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
            review_order=sorted(rows,key=lambda r:digest([SEED,"review",side,r["id"]]))
            writer.writerows({"id":spreadsheet_cell(r["id"]),"text":spreadsheet_cell(r["text"])} for r in review_order)
    state=readiness(rows);write_json(out/"readiness.json",state)
    locks=[Path(sources_path),Path(cases_path),Path(__file__),*map(Path,corpus_paths)]
    if archive is not None: locks.append(Path(archive))
    # Imported parsing/grouping helpers are part of the frozen protocol too.
    locks += [ROOT / p for p in ("evaluation/data/sms.py", "app/services/url/intake.py",
                                "app/services/url/parsing.py", "app/services/url/authority.py",
                                "app/services/url/domain_reference.py", "app/services/url/resources/iana_tlds.txt")]
    locks += [Path(s["snapshot_path"]) for s in sources.values()]
    manifest={"version":VERSION,"created_at":datetime.now(timezone.utc).isoformat(),"seed":SEED,
        "sources_path":str(Path(sources_path).resolve()),"cases_path":str(Path(cases_path).resolve()),
        "source_count":len(sources),"case_count":len(rows),"components":len({r["group_id"] for r in rows}),
        "split_method":"seeded hash of recomputed connected source/campaign/domain/template/lineage components; dev<0.6",
        "near_template_jaccard":.75,"reference_status":REFERENCE_STATUS,"human_reviewed":False,
        "export_order":"Label-independent hash(seed, role, opaque ID); reviewer A/B independently ordered",
        "environment":{"python":sys.version,"tldextract":package_version("tldextract"),"idna":package_version("idna")},
        "input_files_sha256":{str(p.resolve()):sha(p) for p in locks},
        "files_sha256":{p.name:sha(p) for p in sorted(out.iterdir()) if p.is_file()},
        "author_exposed_test":True,"old_120_reserve_inference":False,"classifier_API_calls":0,
        "sources_added_to_RAG":False,"readiness":state}
    write_json(out/"manifest.json",manifest)
    return manifest


def verify(out):
    out=Path(out);config=json.loads((out/"manifest.json").read_text())
    if config.get("version")!=VERSION or config.get("reference_status")!=REFERENCE_STATUS or config.get("human_reviewed") is not False:
        raise ValueError("Unexpected supplement provenance/status.")
    for p,h in config["input_files_sha256"].items():
        if sha(p)!=h: raise ValueError("Frozen supplement input changed: "+p)
    for name,h in config["files_sha256"].items():
        if sha(out/name)!=h: raise ValueError("Frozen supplement output changed: "+name)
    rows=read_jsonl(out/"cases.jsonl")
    sources=validate_sources(read_jsonl(config["sources_path"]))
    cases=validate_cases(read_jsonl(config["cases_path"]),sources)
    recalculated,edges=assign_splits(cases)
    recalculated=sorted(recalculated,key=lambda r:digest([SEED,"input_order",r["id"]]))
    if recalculated!=rows or edges!=read_jsonl(out/"leakage_edges.jsonl"):
        raise ValueError("Recomputed source/domain/template/lineage split differs.")
    return {"verified":True,"cases":len(rows),"components":config["components"],"classifier_API_calls":0,"gold":False}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("command",choices=("prepare","verify"))
    p.add_argument("--sources",type=Path,default=SOURCE_DEFAULT);p.add_argument("--cases",type=Path,default=CASES_DEFAULT)
    p.add_argument("--out",type=Path,required=True);p.add_argument("--corpus",type=Path,action="append",default=[])
    p.add_argument("--url-archive",type=Path);a=p.parse_args()
    result=prepare(a.sources,a.cases,a.out,corpus_paths=a.corpus,archive=a.url_archive) if a.command=="prepare" else verify(a.out)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=="__main__":main()
