"""Registered, serial single-URL latency measurements with deployed local models.

Run ``python -m evaluation.url.latency --out <new-directory>``. This measures
warm latency, not classification quality; it never opens a destination or fits
a model. Preserve the protocol/raw observations when a run fails.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import importlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import resource
import statistics
import time


ROOT = Path(__file__).resolve().parents[2]
URLS = (
    "https://example.org/orders/status",
    "http://192.0.2.1/account/verify",
    "https://subdomain.example.com/a/b/c?reference=EXAMPLE",
    "https://xn--bcher-kva.example/catalog",
    "https://example.net/" + "a" * 140,
)
PROFILES = ("stable", "focused")
SCOPES = ("intake_and_model", "ASGI_single_URL")
SOURCE_PATHS = (
    "evaluation/url/latency.py", "app/api/runtime.py", "app/api/stable.py",
    "app/api/focused.py", "app/api/interaction.py", "app/api/candidate.py",
    "app/api/legacy.py", "app/services/analysis.py", "app/services/interaction_analysis.py",
    "app/services/url/features.py", "app/services/url/character.py",
    "app/services/url/policy.py", "app/services/url/parsing.py",
    "app/services/url/intake.py", "app/services/url/authority.py",
    "app/services/url/domain_reference.py", "app/services/url/resources/iana_tlds.txt",
    "app/domain/decisions.py", "app/domain/schemas.py",
)
ASSET_PATHS = {
    "stable": tuple("models/inference_XGBoost_d6_s42/" + name for name in
                    ("model.ubj", "config.json", "predict_url.py", "url_features.py", "url_preprocessing.py")),
    "focused": tuple("models/url_character/" + name for name in
                     ("export.json", "vocabulary.json", "weights.npz")),
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def machine():
    def read(path):
        file = Path(path)
        return file.read_text().strip() if file.exists() else None
    cpu = next((line.split(":", 1)[1].strip() for line in (read("/proc/cpuinfo") or "").splitlines()
                if line.startswith("model name")), platform.processor())
    memory = next((int(line.split()[1]) for line in (read("/proc/meminfo") or "").splitlines()
                   if line.startswith("MemTotal:")), None)
    return {"CPU": cpu, "logical_CPUs_host": os.cpu_count(),
            "CPU_affinity": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
            "host_RAM_GiB": memory / 1024 ** 2 if memory else None,
            "cgroup_CPU_max": read("/sys/fs/cgroup/cpu.max"),
            "cgroup_memory_max": read("/sys/fs/cgroup/memory.max"),
            "RAM_limit_applied_by_benchmark": False,
            "platform": platform.platform(), "python": platform.python_version(),
            "thread_environment": {name: os.getenv(name) for name in
                                   ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")}}


def dependency_versions():
    result = {}
    for distribution, module in (("numpy", "numpy"), ("scipy", "scipy"), ("scikit-learn", "sklearn"),
                                 ("xgboost", "xgboost"), ("fastapi", "fastapi"), ("httpx", "httpx")):
        try:
            result[distribution] = {"version": importlib.metadata.version(distribution), "source": "distribution_metadata"}
        except importlib.metadata.PackageNotFoundError:
            installed = importlib.import_module(module)
            result[distribution] = {"version": getattr(installed, "__version__", "unavailable"),
                                    "source": "module.__version__; distribution metadata missing"}
    return result


def percentile(values, percent):
    """Linear interpolation (the default numpy percentile convention)."""
    if not values or not 0 <= percent <= 100:
        raise ValueError("Nonempty observations and percentile in [0, 100] are required.")
    ordered = sorted(float(value) for value in values)
    if any(not math.isfinite(value) or value < 0 for value in ordered):
        raise ValueError("Latency observations must be finite and nonnegative.")
    position = (len(ordered) - 1) * percent / 100
    lower = math.floor(position)
    return ordered[lower] + (ordered[math.ceil(position)] - ordered[lower]) * (position - lower)


def summarize(rows):
    values = [row["total_ms"] for row in rows]
    # percentile also validates all observations; no fast failures are dropped.
    return {"observations": len(values), "median_ms": percentile(values, 50),
            "p95_ms": percentile(values, 95), "maximum_ms": max(values),
            "minimum_ms": min(values), "mean_ms": statistics.mean(values),
            "within_one_second": sum(value <= 1000 for value in values)}


def register(out, rounds, warmup):
    """Write workload before model loading or measurement; never overwrite."""
    if type(rounds) is not int or rounds < 6 or type(warmup) is not int or warmup < 1:
        raise ValueError("Use at least six rounds (30 observations/model/scope) and one warmup round.")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    hashes = {name: sha(ROOT / name) for name in SOURCE_PATHS}
    assets = {profile: {name: {"bytes": (ROOT / name).stat().st_size, "sha256": sha(ROOT / name)}
                       for name in names} for profile, names in ASSET_PATHS.items()}
    protocol = {
        "schema": "single-url-latency-1.0", "registered_at": datetime.now(timezone.utc).isoformat(),
        "profiles_in_order": list(PROFILES), "scopes_in_order_per_URL": list(SCOPES),
        "rounds": rounds, "warmup_rounds_per_profile": warmup, "URLs": list(URLS),
        "URL_origin": "Five fixed reserved example/test-net fixtures reused from runtime_checks_20261113; no safety labels.",
        "observations_per_profile_per_scope": rounds * len(URLS),
        "schedule": "serial, round-robin URL order, one URL per invocation; fixed URL strings, no prediction cache introduced",
        "intake_and_model_scope": "profile parser/intake + existing ConservativeURLModel.predict([URL]); includes normalization, lexical features or TF-IDF, inference and URL decision policy",
        "ASGI_scope": "TestClient.post start to response receipt: JSON encoding, in-process ASGI API, profile intake, model and serialization; response JSON validation is outside timer",
        "timer": "time.perf_counter_ns", "percentile": "linear interpolation on sorted raw milliseconds",
        "model_loading_excluded": True, "physical_HTTP_network_included": False,
        "LLM_calls_permitted": 0, "destination_fetches_permitted": 0,
        "RAG": "disabled; fail-closed RAG sentinel injected, not retrieval benchmark",
        "API_input": {"mode": "text", "use_llm": False, "use_rag": False, "include_ml": False},
        "abort_policy": "Abort on unavailable/error model, wrong URL count, score disagreement, provider/RAG call or changed source/assets; preserve protocol/raw and record failure, no rerun filtering.",
        "hardware": machine(), "source_sha256": hashes, "model_assets": assets,
        "limits": "Warm serial synthetic workload only; no concurrent users, physical network, cold start or LLM SLA; no inference-quality comparison or population performance guarantee.",
    }
    write_json(out / "protocol.json", protocol)
    return protocol


def validate_prediction(rows, expected_url):
    if len(rows) != 1 or rows[0].get("status") != "ok" or rows[0].get("url") != expected_url:
        raise ValueError("Unavailable/failed/wrong-URL output cannot count as a fast inference.")
    score = rows[0].get("score")
    if type(score) not in (float, int) or not math.isfinite(score) or not 0 <= score <= 1:
        raise ValueError("Prediction needs one finite score in [0, 1].")
    return float(score)


class DisabledRAG:
    def status(self):
        return {"ready": False, "message": "Disabled for the local URL-only benchmark."}

    def search(self, *args, **kwargs):
        raise AssertionError("A URL-only benchmark must not retrieve RAG documents.")


def benchmark(out, rounds=20, warmup=3):
    protocol = register(out, rounds, warmup)
    out = Path(out)
    try:
        from dataclasses import replace
        import httpx
        from fastapi.testclient import TestClient
        from app.api.runtime import create_app
        from app.core.settings import Settings
        from app.services.url.character import CharURLService
        from app.services.url.features import ModelService
        from app.services.url.intake import extract_urls_v2
        from app.services.url.parsing import extract_urls
        from app.services.url.policy import ConservativeURLModel

        versions = dependency_versions()
        calls = []

        def no_provider(request):
            calls.append(True)
            raise AssertionError("A URL benchmark must not call a provider.")

        settings = replace(Settings(), root=ROOT, model_dir="models/inference_XGBoost_d6_s42", api_key="")
        rows, loads, models = [], {}, {}
        fields = ("profile", "scope", "round", "fixture", "URL", "intake_ms", "predict_ms", "total_ms", "score", "status")
        with (out / "observations.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for profile in PROFILES:
                raw = ModelService(settings) if profile == "stable" else CharURLService()
                loaded_at = time.perf_counter_ns()
                model = ConservativeURLModel(raw)
                models[profile] = model.load()
                loads[profile] = (time.perf_counter_ns() - loaded_at) / 1_000_000
                if not models[profile]["ready"]:
                    raise ValueError("The deployed URL package is unavailable: " + profile)
                extractor = extract_urls if profile == "stable" else extract_urls_v2
                app = create_app(profile, settings, transport=httpx.MockTransport(no_provider),
                                 model_service=raw, rag_service=DisabledRAG())
                with TestClient(app) as client:
                    for round_number in range(-warmup, rounds):
                        for fixture, url in enumerate(URLS, 1):
                            started = time.perf_counter_ns()
                            urls, invalid = extractor(url, "text")
                            parsed_at = time.perf_counter_ns()
                            predictions = model.predict(urls)
                            ended = time.perf_counter_ns()
                            if invalid or urls != [url]:
                                raise ValueError("Registered input was not parsed as exactly one URL.")
                            score = validate_prediction(predictions, url)
                            direct = {"profile": profile, "scope": SCOPES[0], "round": round_number + 1,
                                      "fixture": fixture, "URL": url, "intake_ms": (parsed_at - started) / 1_000_000,
                                      "predict_ms": (ended - parsed_at) / 1_000_000,
                                      "total_ms": (ended - started) / 1_000_000, "score": score, "status": "ok"}
                            started = time.perf_counter_ns()
                            response = client.post("/api/analyze", json={"mode": "text", "text": url,
                                                   "use_llm": False, "use_rag": False, "include_ml": False})
                            ended = time.perf_counter_ns()
                            payload = response.json()
                            if response.status_code != 200:
                                raise ValueError("API failed; never report failed requests as fast success.")
                            api_score = validate_prediction(payload.get("urls", []), url)
                            if api_score != score or calls or payload["execution"]["runtime"]["calls_attempted"] != 0:
                                raise ValueError("Direct/API score mismatch or an external call was attempted.")
                            api = {**direct, "scope": SCOPES[1], "intake_ms": None, "predict_ms": None,
                                   "total_ms": (ended - started) / 1_000_000, "score": api_score}
                            if round_number >= 0:
                                for observation in (direct, api):
                                    writer.writerow(observation)
                                    rows.append(observation)
                                handle.flush()
        for name, expected in protocol["source_sha256"].items():
            if sha(ROOT / name) != expected:
                raise ValueError("Source changed during measurement: " + name)
        for assets in protocol["model_assets"].values():
            for name, expected in assets.items():
                if sha(ROOT / name) != expected["sha256"]:
                    raise ValueError("Model asset changed during measurement: " + name)
        grouped = {profile: {scope: summarize([row for row in rows if row["profile"] == profile and row["scope"] == scope])
                             for scope in SCOPES} for profile in PROFILES}
        result = {"completed_at": datetime.now(timezone.utc).isoformat(), "protocol_sha256": sha(out / "protocol.json"),
                  "observations": len(rows), "results": grouped, "model_load_ms_excluded": loads,
                  "models": models, "provider_calls": len(calls), "versions": versions,
                  "process_peak_RSS_MiB": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
                  "RSS_scope": "whole benchmark process after both profiles, not isolated per-model memory",
                  "hardware_after": machine(), "all_source_and_asset_hashes_unchanged": True,
                  "independent_accuracy_test": False, "API_predictions_match_direct_scores": True}
        write_json(out / "summary.json", result)
        lines = ["# Single-URL latency, 21/11/2026", "", "Real deployed local packages; fixed reserved fixtures, no labels, LLM/RAG off, no destination fetch. Protocol was saved before loading/measurement. Each observation invokes exactly one URL; no batch latency was divided by five.", "",
                 "| Profile/model | Scope | Observations | Median ms | P95 ms | Max ms |", "|---|---|---:|---:|---:|---:|"]
        for profile in PROFILES:
            for scope, metrics in grouped[profile].items():
                lines.append(f"| {profile}/{models[profile]['run_id']} | {scope} | {metrics['observations']} | {metrics['median_ms']:.4f} | {metrics['p95_ms']:.4f} | {metrics['maximum_ms']:.4f} |")
        lines += ["", "`intake_and_model` includes profile parsing/intake, normalization and all lexical-feature/TF-IDF construction, inference and policy. Stage `predict_ms` includes features; it is not estimator-only time. `ASGI_single_URL` also includes request/response JSON, API validation/middleware/threadpool, serialization and the profile's normal orchestration. Stages for ASGI are intentionally unreported rather than copied from rounded API telemetry.", "",
                  "Warm model loading is excluded and separately recorded. API timing uses TestClient in process; no physical HTTP network, LLM SLA or concurrent-load claim. RAG is a fail-closed disabled sentinel, not a measured retrieval service. CPU affinity/hardware/thread settings and asset hashes are in protocol.json. Peak RSS is the combined process, not model footprint. Results on five synthetic strings describe this fixed workload, not detection quality or a general performance guarantee.", "",
                  "Reproduce in a NEW directory: `.venv/bin/python -m evaluation.url.latency --out artifacts/evaluations/<new-run> --rounds 20 --warmup 3 --cpu-cores 4`.", "",
                  "Files: [protocol](protocol.json), [raw observations](observations.csv), [summary](summary.json), [manifest](manifest.json)."]
        (out / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        write_json(out / "manifest.json", {name: sha(out / name) for name in ("protocol.json", "observations.csv", "summary.json", "README.md")})
        return grouped
    except Exception as exc:
        write_json(out / "failure.json", {"failed_at": datetime.now(timezone.utc).isoformat(),
                   "exception_type": type(exc).__name__, "message": str(exc)[:500], "results_are_incomplete": True})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--cpu-cores", type=int, default=4)
    args = parser.parse_args()
    if args.cpu_cores < 1:
        parser.error("CPU core count must be positive.")
    previous = os.sched_getaffinity(0) if hasattr(os, "sched_getaffinity") else None
    try:
        if previous is not None:
            os.sched_setaffinity(0, sorted(previous)[:args.cpu_cores])
        print(json.dumps(benchmark(args.out, args.rounds, args.warmup), indent=2, allow_nan=False))
    finally:
        if previous is not None:
            os.sched_setaffinity(0, previous)


if __name__ == "__main__":
    main()
