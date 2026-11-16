"""Measure warm five-URL API batches with real local models and no provider calls."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

URLS = ("https://example.org/orders/status", "http://192.0.2.1/account/verify",
        "https://subdomain.example.com/a/b/c?reference=EXAMPLE",
        "https://xn--bcher-kva.example/catalog", "https://example.net/" + "a" * 140)


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def hardware():
    def value(path):
        p = Path(path)
        return p.read_text().strip() if p.exists() else None
    memory = next((line.split()[1] for line in Path("/proc/meminfo").read_text().splitlines()
                   if line.startswith("MemTotal:")), None)
    model = next((line.split(":", 1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines()
                  if line.startswith("model name")), platform.processor())
    return {"CPU": model, "logical_CPUs_host": os.cpu_count(),
        "CPU_affinity": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
        "host_RAM_GiB": round(int(memory) / 1024 ** 2, 2) if memory else None,
        "cgroup_CPU_max": value("/sys/fs/cgroup/cpu.max"),
        "cgroup_memory_max": value("/sys/fs/cgroup/memory.max"),
        "platform": platform.platform(), "python": platform.python_version()}


def benchmark(profile, out, trials=100):
    from dataclasses import replace
    import httpx
    import numpy as np
    from fastapi.testclient import TestClient
    from app.api.runtime import create_app
    from app.core.settings import Settings

    if trials < 30: raise ValueError("The proposal requires at least thirty batches.")
    out = Path(out)
    if out.exists(): raise ValueError("Preserve previous benchmarks.")
    out.mkdir(parents=True)
    (out / "protocol.json").write_text(json.dumps({"registered_at": datetime.now(timezone.utc).isoformat(),
        "profile": profile, "trials": trials, "warmup_batches": 3, "URLs_per_batch": 5,
        "URL_examples": list(URLS), "target_seconds": 1, "target_fraction": .95,
        "in_process_HTTP_API": True, "physical_network_included": False, "LLM_calls_permitted": 0,
        "models_are_real": True, "unique_query_value_each_trial": True, "hardware": hardware(),
        "source_hashes": {p: sha(ROOT / p) for p in ("app/api/runtime.py", "scripts/evaluation/benchmark_url_runtime.py")}}, indent=2) + "\n")
    provider_calls = []
    def no_provider(request):
        provider_calls.append(True)
        raise AssertionError("URL benchmark must never call an external provider.")
    app = create_app(profile, replace(Settings(), api_key=""), transport=httpx.MockTransport(no_provider))
    with TestClient(app) as client:
        start = time.perf_counter()
        status = client.get("/api/status").json()
        cold_status_ms = (time.perf_counter() - start) * 1000
        if not status["ml"]["ready"]: raise ValueError("Real URL model is unavailable.")
        folder = ROOT / "models" / status["ml"]["folder"]
        model_hashes = {p.name: sha(p) for p in folder.iterdir() if p.is_file()}
        rows = []
        for index in range(-3, trials):
            text = "\n".join(u + ("&" if "?" in u else "?") + f"trial={index}" for u in URLS)
            started = time.perf_counter()
            response = client.post("/api/analyze", json={"mode": "text", "text": text, "use_llm": False})
            elapsed = (time.perf_counter() - started) * 1000
            result = response.json()
            if (response.status_code != 200 or len(result.get("urls", [])) != 5
                    or any(r["status"] != "ok" for r in result["urls"]) or provider_calls):
                raise ValueError("A model failure/provider call is not a valid fast batch.")
            if index >= 0:
                rows.append({"trial": index + 1, "API_ms": round(elapsed, 3),
                    "model_ms": result["timing"]["ml_ms"], "URLs_ok": 5, "within_1_second": elapsed <= 1000})
    samples = [r["API_ms"] for r in rows]
    result = {"profile": profile, "trials": trials, "URLs_per_batch": 5,
        "warm_model_ready_status_ms": round(cold_status_ms, 3), "median_API_ms": float(np.median(samples)),
        "p95_API_ms": float(np.percentile(samples, 95)), "max_API_ms": max(samples),
        "batches_within_1_second": sum(r["within_1_second"] for r in rows),
        "fraction_within_1_second": sum(r["within_1_second"] for r in rows) / trials,
        "meets_observed_target": sum(r["within_1_second"] for r in rows) / trials >= .95,
        "provider_calls": len(provider_calls), "model": status["ml"], "model_file_hashes": model_hashes,
        "hardware": hardware(), "process_peak_RSS_MiB": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
        "exact_4_core_8_GiB_machine_verified": False,
        "limitations": "API measured in-process after warmup; no physical HTTP network or LLM. "
            "CPU affinity may be limited to four cores, but RAM is not constrained to 8 GiB. "
            "Observed batch fraction is not a population performance guarantee. URLs are synthetic inputs, not safety labels."}
    (out / "batches.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (out / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    (out / "manifest.json").write_text(json.dumps({name: sha(out / name) for name in
        ("protocol.json", "batches.jsonl", "summary.json")}, indent=2) + "\n")
    return {k: result[k] for k in ("profile", "trials", "p95_API_ms", "fraction_within_1_second", "provider_calls")}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--profile", choices=["stable", "focused"], required=True)
    p.add_argument("--trials", type=int, default=100)
    p.add_argument("--cpu-cores", type=int, default=4)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    previous = os.sched_getaffinity(0) if hasattr(os, "sched_getaffinity") else None
    if a.cpu_cores < 1: p.error("CPU core count must be positive.")
    try:
        if previous is not None: os.sched_setaffinity(0, sorted(previous)[:a.cpu_cores])
        print(json.dumps(benchmark(a.profile, a.out, a.trials), ensure_ascii=False, indent=2))
    finally:
        if previous is not None: os.sched_setaffinity(0, previous)
