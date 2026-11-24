"""Register and evaluate the managed app on finalized human development labels.

This compares actual application configurations, not a pure prompt ablation.
Stable changes its RAG prompt; focused uses post-verdict RAG. Independent calls
are retained even when payloads match. No holdout, retry, or automatic promotion.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from importlib import import_module
import time

import httpx
from fastapi.testclient import TestClient

from app.api.runtime import create_app
from app.core.settings import ROOT, Settings
from app.services.llm.telemetry import MAX_BYTES, fingerprint, observe
from evaluation.data import adjudicated_reference, evidence_supplement, human_review
from evaluation.data.sms import read_jsonl, sha, write_json, write_jsonl

VERSION = "managed-runtime-development-evaluation-1.0"
ARMS = {"llm_only": (False, False), "llm_url": (True, False),
        "llm_rag": (False, True), "llm_url_rag": (True, True)}
PROFILES = ("stable", "focused", "verifier-shadow")
OPTIONS = ("PHISHLENS_CORE_MAX_TOKENS", "PHISHLENS_CORE_THINKING",
           "PHISHLENS_FOCUSED_RETRIEVAL", "PHISHLENS_CANDIDATE_RAG_MODE")
FORBIDDEN = {"endpoint", "api_key", "authorization", "headers", "reasoning_content", "raw_response"}


def _time():
    return datetime.now(timezone.utc).isoformat()


def _append(path, row):
    with Path(path).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _safe(value):
    """Persist app verdicts/usage, never connection configuration or reasoning."""
    if isinstance(value, dict):
        return {k: _safe(v) for k, v in value.items() if k.casefold() not in FORBIDDEN}
    if isinstance(value, list):
        return [_safe(v) for v in value]
    return value


def safe_status(value):
    return {"runtime": _safe(value["runtime"]), "limits": value["limits"],
        "ml": {k: value["ml"].get(k) for k in ("ready", "run_id", "kind", "feature_count", "thresholds")},
        "rag": {k: value["rag"].get(k) for k in ("ready", "model", "revision", "documents", "chunks", "min_score", "top_k")},
        "analysis_policy": _safe(value.get("analysis_policy", {}))}


def _environment(settings):
    fields = ("model_dir", "llm_model", "timeout_seconds", "max_tokens", "rag_model_dir", "rag_index_dir", "rag_corpus")
    versions = {name: getattr(import_module(name), "__version__", "unknown")
                for name in ("httpx", "fastapi", "pydantic", "numpy", "scipy", "sklearn", "xgboost")}
    return {"settings": {key: getattr(settings, key) for key in fields}, "package_versions": versions,
            "endpoint_sha256": hashlib.sha256(settings.endpoint.encode()).hexdigest(),
            "profile_options": {key: os.getenv(key) for key in OPTIONS}}


def _assets(settings, profile):
    directories = [settings.root / settings.model_dir, settings.root / settings.rag_model_dir,
                   settings.root / settings.rag_index_dir, settings.root / "app/services/url/resources"]
    if profile != "stable":
        directories.append(ROOT / "models/url_character")
    paths = {p.resolve() for directory in directories for p in directory.rglob("*") if p.is_file()}
    paths.add((settings.root / settings.rag_corpus).resolve())
    if profile != "stable":
        paths.update((ROOT / name).resolve() for name in
                     ("models/inference_XGBoost_d6_s42/url_preprocessing.py", "evaluation/url/character_baseline.py"))
    paths.update(p.resolve() for p in (ROOT / "app").rglob("*.py"))
    paths.update((ROOT / name).resolve() for name in ("evaluation/messages/runtime_evaluation.py",
        "evaluation/common/runtime_metrics.py", "evaluation/data/adjudicated_reference.py",
        "evaluation/data/human_review.py", "evaluation/data/evidence_supplement.py"))
    return sorted(paths)


def _scope(pack, pack_sha256, reference, reference_sha256):
    pack, reference = Path(pack).resolve(), Path(reference).resolve()
    evidence_supplement.verify(pack, manifest_sha256=pack_sha256)
    human = adjudicated_reference.verify(reference, reference_sha256)
    inventory, anchor = human_review.registered_inventory(pack / "human_review.registration.json")
    manifest, _, inputs = human_review.load_inventory(inventory, anchor)
    if (human["scope"] != "visible_message_actions"
            or human["inventory_manifest_sha256"] != anchor
            or human["inventory_sha256"] != manifest["inventory_sha256"]
            or human["registration_sha256"] != sha(pack / "human_review.registration.json")):
        raise ValueError("Human reference belongs to a different frozen packet or scope.")
    refs = {r["sample_id"]: r for r in human["labels"]}
    mapping = read_jsonl(pack / "review_ID_key_OPERATOR_ONLY.jsonl")
    rows = read_jsonl(pack / "cases.jsonl")
    by_case = {r["id"]: r for r in rows}
    if (len(mapping) != len(rows) or len(refs) != len(rows) or len(human["labels"]) != len(refs)
            or len({r["case_id"] for r in mapping}) != len(rows)
            or {r["case_id"] for r in mapping} != set(by_case)
            or {r["sample_id"] for r in mapping} != set(refs)):
        raise ValueError("Reference/mapping must cover the complete frozen packet without duplicates.")
    selected = []
    for item in mapping:
        row, ref = by_case[item["case_id"]], refs[item["sample_id"]]
        if human_review.text_digest(row["text"]) != ref["text_sha256"]:
            raise ValueError("Human reference text differs from the app input.")
        if row["split"] == "dev":
            selected.append({"id": row["id"], "text": row["text"], "sample_id": item["sample_id"],
                "reference_label": ref["label"], "base_id": row.get("base_id"),
                "forced_level": row.get("forced_literal_risk_level"),
                "has_URL": bool(row["urls"]), "group_id": row["group_id"]})
    if not selected:
        raise ValueError("No development inputs in the registered human scope.")
    return sorted(selected, key=lambda r: r["id"])


def prepare(out, pack, pack_sha256, reference, reference_sha256, *, profile="stable", repeats=1,
            token_budget=100000, pacing_seconds=4, settings=None):
    out = Path(out).resolve()
    if out.exists():
        raise ValueError("Choose a fresh evaluation directory.")
    if profile not in PROFILES or type(repeats) is not int or not 1 <= repeats <= 3:
        raise ValueError("Register a supported profile and 1–3 repetitions before inference.")
    if type(token_budget) is not int or token_budget <= 0 or not 0 <= pacing_seconds <= 60:
        raise ValueError("Register a positive observed-token budget and pacing from 0 to 60 seconds.")
    # Reject missing/provisional labels before loading app/models or transport.
    cases = _scope(pack, pack_sha256, reference, reference_sha256)
    settings = settings or Settings()
    denied = httpx.MockTransport(lambda request: (_ for _ in ()).throw(AssertionError("Preparation must not call provider.")))
    requests = []
    with TestClient(create_app(profile, settings, transport=denied)) as client:
        status = safe_status(client.get("/api/status").json())
        if not status["ml"]["ready"] or not status["rag"]["ready"]:
            raise ValueError("Both real URL and RAG services must be ready for this comparison.")
        for case in cases:
            response = client.post("/api/preview", json={"mode": "text", "text": case["text"]})
            if response.status_code != 200 or response.json().get("text") != case["text"]:
                raise ValueError("Preview changes the human-reviewed text; create and review a new packet first.")
            for repeat in range(repeats):
                for arm, (ml, rag) in ARMS.items():
                    body = {"mode": "text", "text": case["text"], "llm_text": case["text"],
                            "use_llm": True, "consent": True, "include_ml": ml, "use_rag": rag}
                    requests.append({**case, "id": case["id"] + (f"::repeat-{repeat}" if repeats > 1 else ""),
                        "base_id": case["base_id"] + (f"::repeat-{repeat}" if repeats > 1 else "") if case["base_id"] else None,
                        "case_id": case["id"], "arm": arm, "repeat": repeat,
                        "key": fingerprint([case["id"], arm, repeat]), "body": body})
    # Fixed hash order; never reorder on output/labels/score. No dedup/caching of
    # whole app requests: each physical request exercises the managed deadline.
    requests.sort(key=lambda r: fingerprint([20261121, "runtime_order", r["key"]]))
    locks = _assets(settings, profile)
    locks += [Path(pack).resolve() / "manifest.json", Path(reference).resolve() / "manifest.json"]
    locks += [p for p in Path(reference).resolve().rglob("*") if p.is_file()]
    out.mkdir(parents=True)
    write_jsonl(out / "requests.jsonl", requests)
    config = {"version": VERSION, "created_utc": _time(), "profile": profile, "split": "dev",
        "mode": "registered_runtime_development_evaluation", "human_reference_status": "declared_human_not_independently_authenticated",
        "pack": str(Path(pack).resolve()), "pack_sha256": pack_sha256,
        "reference": str(Path(reference).resolve()), "reference_sha256": reference_sha256,
        "cases": len(cases), "repeats": repeats, "arms": list(ARMS), "physical_requests": len(requests),
        "effective_status": status, "environment": _environment(settings),
        "token_budget": token_budget, "pacing_seconds": pacing_seconds,
        "requests_sha256": sha(out / "requests.jsonl"),
        "input_files_sha256": {str(p): sha(p) for p in sorted(set(locks))},
        "limits": ["Actual app configuration comparison, not a pure same-system-prompt ablation.",
                   "Stable switches RAG instructions; focused/shadow use post-verdict RAG.",
                   "Identical classifier payloads are still independently sampled; equal/different F1 is not isolated RAG efficacy.",
                   "Human-origin/independence are operator declarations, not software-authenticated identities.",
                   "Author-exposed reconstructed development data; never an independent holdout result.",
                   "Observed token budget may be exceeded by one app request; missing usage is unknown cost."]}
    write_json(out / "manifest.json", config)
    return {"registered": True, "physical_requests": len(requests), "provider_calls": 0,
            "manifest_sha256": sha(out / "manifest.json"), "profile": profile, "split": "dev"}


def verify(out, manifest_sha256, *, results_sha256=None):
    out = Path(out).resolve()
    if sha(out / "manifest.json") != manifest_sha256:
        raise ValueError("Runtime evaluation registration SHA differs.")
    config = json.loads((out / "manifest.json").read_text())
    if (config["version"] != VERSION or config["split"] != "dev" or config["profile"] not in PROFILES
            or type(config["repeats"]) is not int or not 1 <= config["repeats"] <= 3):
        raise ValueError("Unexpected runtime evaluation registration.")
    for path, value in config["input_files_sha256"].items():
        if sha(path) != value:
            raise ValueError("Frozen app/model/reference source changed: " + path)
    if sha(out / "requests.jsonl") != config["requests_sha256"]:
        raise ValueError("Frozen requests changed.")
    if (out / "results_manifest.json").exists():
        if results_sha256 is not None and sha(out / "results_manifest.json") != results_sha256:
            raise ValueError("Runtime result manifest differs from its external anchor.")
        seal = json.loads((out / "results_manifest.json").read_text())
        if seal.get("registration_sha256") != manifest_sha256:
            raise ValueError("Result manifest belongs to another registration.")
        for name, expected_hash in seal["files_sha256"].items():
            if name not in {"attempts.jsonl", "responses.jsonl", "provider_attempts.jsonl",
                            "provider_observations.jsonl", "run_mode.json", "report.json"}:
                raise ValueError("Unexpected result artifact.")
            if sha(out / name) != expected_hash:
                raise ValueError("Sealed runtime result changed: " + name)
    elif results_sha256 is not None:
        raise ValueError("Runtime results are not sealed yet.")
    cases = _scope(config["pack"], config["pack_sha256"], config["reference"], config["reference_sha256"])
    requests = read_jsonl(out / "requests.jsonl")
    expected = {(r["id"], arm, repeat): r for r in cases for arm in ARMS for repeat in range(config["repeats"])}
    if config["cases"] != len(cases) or config["physical_requests"] != len(expected) or config["arms"] != list(ARMS):
        raise ValueError("Registration counts/arms differ from the human reference scope.")
    if len(requests) != len(expected) or len({r["key"] for r in requests}) != len(expected):
        raise ValueError("Incomplete or duplicate registered cells.")
    seen = set()
    for req in requests:
        original = expected.get((req["case_id"], req["arm"], req["repeat"]))
        if original is None:
            raise ValueError("Request does not match human reference scope.")
        ml, rag = ARMS[req["arm"]]
        suffix = f"::repeat-{req['repeat']}" if config["repeats"] > 1 else ""
        body = {"mode": "text", "text": original["text"], "llm_text": original["text"],
                "use_llm": True, "consent": True, "include_ml": ml, "use_rag": rag}
        identity = (req["case_id"], req["arm"], req["repeat"])
        if (identity in seen or req["body"] != body or req["id"] != original["id"] + suffix
                or req["key"] != fingerprint([original["id"], req["arm"], req["repeat"]])
                or req["base_id"] != (original["base_id"] + suffix if original["base_id"] else None)
                or any(req.get(k) != original.get(k) for k in
                       ("text", "sample_id", "reference_label", "has_URL", "group_id", "forced_level"))):
            raise ValueError("Request arm/body/identity differs from the registered human scope.")
        seen.add(identity)
    starts = read_jsonl(out / "attempts.jsonl") if (out / "attempts.jsonl").exists() else []
    rows = read_jsonl(out / "responses.jsonl") if (out / "responses.jsonl").exists() else []
    keys = {r["key"] for r in requests}
    if (len({r["key"] for r in starts}) != len(starts) or len({r["key"] for r in rows}) != len(rows)
            or {r["key"] for r in rows} - {r["key"] for r in starts} or {r["key"] for r in starts} - keys):
        raise ValueError("Duplicate or unregistered attempts/responses.")
    lookup = {r["key"]: r for r in requests}
    if any(row.get("body_sha256") != fingerprint(lookup[row["key"]]["body"]) for row in starts):
        raise ValueError("Attempt body differs from the registered request.")
    for row in rows:
        original = lookup[row["key"]]
        if any(row.get(k) != original.get(k) for k in ("id", "case_id", "arm", "repeat", "base_id",
                "sample_id", "reference_label", "has_URL", "group_id", "forced_level")):
            raise ValueError("Response identity/reference differs from the registered request.")
    return {"verified": True, "complete": len(rows) == len(requests), "reference_sha256": config["reference_sha256"],
        "profile": config["profile"], "split": "dev", "physical_requests": len(requests), "completed_requests": len(rows),
        "real_provider_calls": len(read_jsonl(out / "provider_attempts.jsonl")) if (out / "provider_attempts.jsonl").exists()
            and (out / "run_mode.json").exists() and json.loads((out / "run_mode.json").read_text())["live"] else 0,
        "mode": config["mode"]}


class TraceTransport(httpx.AsyncBaseTransport):
    def __init__(self, out, inner):
        self.out, self.inner, self.key, self.rows = Path(out), inner, None, []

    async def handle_async_request(self, request):
        payload = json.loads(await request.aread())
        data = json.loads(payload["messages"][1]["content"])
        index = len(self.rows)
        observation = {"cell_key": self.key, "stage_index": index, "payload_sha256": fingerprint(payload),
            "system_sha256": fingerprint(payload["messages"][0]),
            "input_text_sha256": hashlib.sha256(data.get("text", data.get("approved_message", "")).encode("utf-8")).hexdigest(),
            "URL_metadata_count": len(data.get("url_results", [])), "RAG_document_count": len(data.get("reference_documents", []))}
        _append(self.out / "provider_attempts.jsonl", {**observation, "started_utc": _time()})
        started = time.perf_counter()
        try:
            response = await self.inner.handle_async_request(request)
            try:
                chunks, size = [], 0
                async for part in response.aiter_bytes():
                    size += len(part)
                    if size > MAX_BYTES:
                        raise httpx.RemoteProtocolError("Provider output exceeds bound.")
                    chunks.append(part)
                packet = b"".join(chunks)
                try:
                    result = json.loads(packet)
                except (ValueError, UnicodeError, RecursionError):
                    result = {}
                observation.update(observe(result, payload, http_status=response.status_code))
                headers = [(k, v) for k, v in response.headers.multi_items()
                           if k.lower() not in {"content-encoding", "content-length", "transfer-encoding"}]
                return httpx.Response(response.status_code, headers=headers, content=packet, request=request)
            finally:
                await response.aclose()
        except BaseException as exc:
            observation["transport_error"] = "TIMEOUT" if isinstance(exc, (TimeoutError, httpx.TimeoutException)) else "INTERRUPTED_OR_CONNECTION_ERROR"
            raise
        finally:
            observation["elapsed_ms"] = round(1000 * (time.perf_counter() - started), 3)
            self.rows.append(observation)
            _append(self.out / "provider_observations.jsonl", observation)

    async def aclose(self):
        await self.inner.aclose()


def _failure(code):
    return {"llm": {"status": "error", "code": code}, "urls": [], "retrieval": {"status": "unavailable", "sources": []},
            "execution": {}, "timing": {}}


def run(out, manifest_sha256, *, live=False, inner=None, limit=None, settings=None):
    if not live and not isinstance(inner, httpx.MockTransport):
        raise ValueError("Live provider calls require --live; offline execution requires MockTransport.")
    if live and inner is not None:
        raise ValueError("Do not mix live runs with an injected provider transport.")
    if limit is not None and (type(limit) is not int or limit < 0):
        raise ValueError("The request limit must be a nonnegative integer.")
    out = Path(out).resolve()
    verify(out, manifest_sha256)
    config = json.loads((out / "manifest.json").read_text())
    settings = settings or Settings()
    if _environment(settings) != config["environment"]:
        raise ValueError("App environment differs from registered configuration.")
    if live and not settings.api_key:
        raise ValueError("Server API key is not configured.")
    if (out / "STOPPED.json").exists():
        return export(out, manifest_sha256)
    mode = {"live": live, "mode": "live_development_comparison" if live else "offline_contract_not_quality"}
    # An exclusive process marker prevents duplicate sends by concurrent workers.
    lock = out / "RUNNING.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    try:
        if (out / "run_mode.json").exists():
            if json.loads((out / "run_mode.json").read_text()) != mode:
                raise ValueError("Do not mix offline and live results.")
        else:
            write_json(out / "run_mode.json", mode)
        trace = TraceTransport(out, inner if inner is not None else httpx.AsyncHTTPTransport(trust_env=False))
        starts = read_jsonl(out / "attempts.jsonl") if (out / "attempts.jsonl").exists() else []
        done = {r["key"] for r in read_jsonl(out / "responses.jsonl")} if (out / "responses.jsonl").exists() else set()
        requests = read_jsonl(out / "requests.jsonl")
        lookup = {r["key"]: r for r in requests}
        # A crash after send is not permission to retry. Preserve the cell as
        # an interrupted technical outcome and proceed only with unsent cells.
        interrupted = False
        for start in starts:
            if start["key"] not in done:
                req = lookup[start["key"]]
                _append(out / "responses.jsonl", {**{k: v for k, v in req.items() if k not in {"body", "text"}},
                    **_failure("INTERRUPTED_REQUEST"), "provider_calls": None, "usage_unknown": True})
                done.add(start["key"])
                interrupted = True
        if interrupted:
            write_json(out / "STOPPED.json", {"reason": "INTERRUPTED_USAGE_UNKNOWN", "created_utc": _time()})
            return export(out, manifest_sha256)
        with TestClient(create_app(config["profile"], settings, transport=trace), raise_server_exceptions=False) as client:
            if safe_status(client.get("/api/status").json()) != config["effective_status"]:
                raise ValueError("Loaded runtime differs from the registration.")
            sent, previous = 0, None
            usage_total = sum(r.get("usage", {}).get("total_tokens", 0)
                for r in (read_jsonl(out / "provider_observations.jsonl") if (out / "provider_observations.jsonl").exists() else []))
            for req in requests:
                if req["key"] in done or (limit is not None and sent >= limit):
                    continue
                if usage_total >= config["token_budget"]:
                    break
                if previous is not None:
                    time.sleep(max(0, config["pacing_seconds"] - (time.monotonic() - previous)))
                trace.key, trace.rows = req["key"], []
                _append(out / "attempts.jsonl", {"key": req["key"], "started_utc": _time(), "body_sha256": fingerprint(req["body"])})
                previous = time.monotonic()
                response = client.post("/api/analyze", json=req["body"])
                try:
                    data = response.json() if response.status_code == 200 else _failure("APP_HTTP_" + str(response.status_code))
                    if not isinstance(data, dict) or not isinstance(data.get("llm"), dict):
                        data = _failure("APP_RESPONSE_INVALID")
                except (ValueError, RecursionError):
                    data = _failure("APP_RESPONSE_INVALID")
                observations = trace.rows
                first = observations[0] if observations else {}
                record = {**{k: v for k, v in req.items() if k not in {"body", "text"}}, **_safe(data),
                    "HTTP_status": response.status_code, "provider_calls": len(observations),
                    "URL_metadata_available": bool(first.get("URL_metadata_count")),
                    "RAG_documents_available": bool(data.get("retrieval", {}).get("sources")),
                    "classifier_payload_sha256": first.get("payload_sha256"),
                    "classifier_system_sha256": first.get("system_sha256"), "run_mode": mode["mode"]}
                _append(out / "responses.jsonl", record)
                sent += 1
                usage_total += sum(r.get("usage", {}).get("total_tokens", 0) for r in observations)
                fatal = next((r.get("http_status") for r in observations if r.get("http_status") in {400, 401, 402, 403, 404, 429}), None)
                if fatal is not None:
                    write_json(out / "STOPPED.json", {"reason": "HTTP_" + str(fatal), "cell_key": req["key"], "created_utc": _time()})
                    break
                if observations and any("total_tokens" not in r.get("usage", {}) for r in observations):
                    write_json(out / "STOPPED.json", {"reason": "USAGE_UNKNOWN", "cell_key": req["key"], "created_utc": _time()})
                    break  # Unknown usage is not free usage; retain and stop.
    finally:
        lock.unlink(missing_ok=True)
    return export(out, manifest_sha256)


def export(out, manifest_sha256):
    out = Path(out).resolve()
    result = verify(out, manifest_sha256)
    mode = json.loads((out / "run_mode.json").read_text()) if (out / "run_mode.json").exists() else None
    observations = read_jsonl(out / "provider_observations.jsonl") if (out / "provider_observations.jsonl").exists() else []
    usage = {"physical_provider_calls_observed": len(observations),
        "total_tokens_observed": sum(r.get("usage", {}).get("total_tokens", 0) for r in observations),
        "calls_with_unknown_usage": sum("total_tokens" not in r.get("usage", {}) for r in observations),
        "scope": "Observed only; missing/interrupted usage is not zero cost. Mock usage is not real consumption."}
    stopped = json.loads((out / "STOPPED.json").read_text()) if (out / "STOPPED.json").exists() else None
    if result["complete"]:
        from evaluation.common.runtime_metrics import score
        rows = read_jsonl(out / "responses.jsonl")
        # Repetitions are separate observations of the same clustered case,
        # never additional independent messages/campaigns.
        ordinary = [r for r in rows if not r.get("base_id")]
        report = {"verification": result, "run_mode": mode, "provider_usage": usage,
            "independent_quality_claim": False,
            "base_message_metrics": score(ordinary) if ordinary else None,
            "all_including_injection_diagnostic": score(rows),
            "note": "Do not mix paired injection variants with base-message quality or count repeats as independent examples."}
        write_json(out / "report.json", report)
    write_json(out / "progress.json", {**result, "run_mode": mode, "metrics_exported": result["complete"],
        "provider_usage": usage, "stopped": stopped})
    if result["complete"]:
        files = [name for name in ("attempts.jsonl", "responses.jsonl", "provider_attempts.jsonl",
                 "provider_observations.jsonl", "run_mode.json", "report.json") if (out / name).exists()]
        write_json(out / "results_manifest.json", {"registration_sha256": manifest_sha256,
            "files_sha256": {name: sha(out / name) for name in files}, "run_mode": mode,
            "note": "Keep this result-manifest SHA independently; registration SHA alone does not authenticate new outputs."})
        result["results_manifest_sha256"] = sha(out / "results_manifest.json")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "verify", "run", "export"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--manifest-sha256")
    parser.add_argument("--results-sha256")
    parser.add_argument("--pack", type=Path)
    parser.add_argument("--pack-sha256")
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--reference-sha256")
    parser.add_argument("--profile", choices=PROFILES, default="stable")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--token-budget", type=int, default=100000)
    parser.add_argument("--pacing-seconds", type=float, default=4)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.command == "prepare":
        if any(value is None for value in (args.pack, args.pack_sha256, args.reference, args.reference_sha256)):
            parser.error("Preparation requires externally anchored frozen pack and finalized human reference.")
        result = prepare(args.out, args.pack, args.pack_sha256, args.reference, args.reference_sha256,
                         profile=args.profile, repeats=args.repeats,
                         token_budget=args.token_budget, pacing_seconds=args.pacing_seconds)
    else:
        if not args.manifest_sha256:
            parser.error("Provide the independently stored registration SHA-256.")
        result = run(args.out, args.manifest_sha256, live=args.live, limit=args.limit) if args.command == "run" else \
            export(args.out, args.manifest_sha256) if args.command == "export" else \
            verify(args.out, args.manifest_sha256, results_sha256=args.results_sha256)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "invalid_or_incomplete_evidence", "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(2)
