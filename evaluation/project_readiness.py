"""Read-only evidence gates, keeping software checks separate from research claims.

This command verifies explicitly supplied artifacts. It never reads .env, loads
models, calls a provider, generates a human label, or changes the app profile.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib
import json
from pathlib import Path
import re
import shlex
import xml.etree.ElementTree as ET


VERSION = "project-readiness-1.0"
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _anchor(value, name):
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase SHA-256 anchor.")
    return value


def _bytes(path, *, limit=16_000_000):
    path = Path(path)
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Evidence artifact exceeds the read limit: " + path.name)
    return data


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _json(path):
    return json.loads(_bytes(path))


def _checks(path):
    """Validate recorded pytest execution against actual JUnit test cases.

    A passing old run does not prove that the current worktree was tested.
    Counts are derived from JUnit, never from a collect-only console message.
    """
    if path is None:
        return {"provided": False, "verified": False, "current_worktree_verified": False}
    path = Path(path).resolve()
    checks_packet = _bytes(path)
    data = json.loads(checks_packet)
    command = data.get("command")
    args = shlex.split(command) if isinstance(command, str) else command
    if not isinstance(args, list) or not args or any(not isinstance(s, str) for s in args):
        raise ValueError("Software checks require a recorded command.")
    if not any(Path(token).name in {"pytest", "pytest.exe"} or token == "pytest" for token in args):
        raise ValueError("Software checks must record a pytest execution.")
    forbidden = ("--collect-only", "--co", "--setup-only", "--setup-plan")
    if any(token.split("=", 1)[0] in forbidden for token in args):
        raise ValueError("Collect/setup-only is not a completed software check.")
    if type(data.get("returncode")) is not int:
        raise ValueError("Software checks require an integer returncode.")
    junit = data.get("junit")
    if isinstance(junit, dict):
        junit_name, pinned = junit.get("path"), junit.get("sha256")
    else:
        junit_name, pinned = junit, None
    # Existing local records omit this field but keep junit.xml next to checks.
    junit_path = Path(junit_name) if isinstance(junit_name, str) else Path("junit.xml")
    if not junit_path.is_absolute():
        junit_path = path.parent / junit_path
    packet = _bytes(junit_path)
    if pinned is not None and _sha(packet) != _anchor(pinned, "JUnit SHA"):
        raise ValueError("JUnit artifact differs from its recorded SHA-256.")
    if b"<!DOCTYPE" in packet.upper() or b"<!ENTITY" in packet.upper():
        raise ValueError("JUnit declarations are not supported.")
    root = ET.fromstring(packet)
    if root.tag not in {"testsuite", "testsuites"}:
        raise ValueError("Invalid JUnit document.")
    cases = list(root.iter("testcase"))
    counts = Counter(total=len(cases), passed=0, failed=0, errors=0, skipped=0)
    for case in cases:
        outcomes = [key for key in ("failure", "error", "skipped") if case.find(key) is not None]
        if len(outcomes) > 1:
            raise ValueError("JUnit case has conflicting outcomes.")
        counts[{"failure": "failed", "error": "errors", "skipped": "skipped"}.get(
            outcomes[0] if outcomes else "", "passed")] += 1
    for suite in root.iter("testsuite"):
        nested = list(suite.iter("testcase"))
        for attribute, key in (("tests", "total"), ("failures", "failed"), ("errors", "errors"), ("skipped", "skipped")):
            if attribute not in suite.attrib:
                continue
            actual = len(nested) if key == "total" else sum(
                node.find({"failed": "failure", "errors": "error", "skipped": "skipped"}[key]) is not None
                for node in nested)
            if int(suite.attrib[attribute]) != actual:
                raise ValueError("JUnit suite counters differ from actual test cases.")
    declared = data.get("tests", {})
    if not isinstance(declared, dict):
        raise ValueError("Invalid recorded software test counts.")
    for key in ("total", "passed", "failed", "errors", "skipped"):
        if key in declared and (type(declared[key]) is not int or declared[key] != counts[key]):
            raise ValueError("Recorded software test counts differ from JUnit: " + key)
    passed = data["returncode"] == 0 and counts["passed"] > 0 and not counts["failed"] and not counts["errors"]
    return {"provided": True, "verified": passed, "counts": dict(counts),
            "returncode": data["returncode"], "checks_sha256": _sha(checks_packet),
            "junit_sha256": _sha(packet), "current_worktree_verified": False,
            "scope": "Recorded execution only; no source snapshot equivalence is inferred."}


def _optional_verify(module, path, anchor, name):
    if path is None:
        if anchor is not None:
            raise ValueError(name + " SHA requires its artifact.")
        return None
    _anchor(anchor, name + " SHA")
    try:
        verifier = importlib.import_module(module).verify
    except (ImportError, AttributeError) as exc:
        raise ValueError(name + " verifier is unavailable.") from exc
    result = verifier(Path(path), manifest_sha256=anchor)
    if not isinstance(result, dict) or result.get("verified") is not True:
        raise ValueError(name + " artifact was not verified.")
    return result


def check(pack, pack_sha256, registration=None, final_reference=None, reference_sha=None,
          runtime_run=None, run_sha=None, checkslatest=None, out=None):
    """Return conservative gates, without treating a software pass as model quality."""
    from evaluation.data import evidence_supplement, human_review

    pack = Path(pack).resolve()
    _anchor(pack_sha256, "Pack SHA")
    verified = evidence_supplement.verify(pack, manifest_sha256=pack_sha256)
    if verified.get("verified") is not True:
        raise ValueError("Supplement pack was not verified.")
    packet_path, packet_sha = human_review.registered_inventory(
        Path(registration) if registration else pack / "human_review.registration.json")
    packet, _, inputs = human_review.load_inventory(packet_path, packet_sha)
    if packet.get("kind") != "classification":
        raise ValueError("The annotation packet must classify this frozen supplement.")
    manifest = _json(pack / "manifest.json")
    registered_packet = manifest.get("review_packet", {})
    if registered_packet.get("manifest_sha256") != packet_sha or packet.get("rows") != verified.get("cases"):
        raise ValueError("The human annotation packet is unrelated to this supplement.")
    counts, readiness, overlap = (_json(pack / name) for name in ("counts.json", "readiness.json", "corpus_overlap.json"))
    rows = [json.loads(line) for line in _bytes(pack / "cases.jsonl").splitlines() if line.strip()]
    components = {}
    for split in ("dev", "holdout"):
        group = [r for r in rows if r.get("split") == split and not r.get("base_id")]
        components[split] = {
            "base_cases": len(group),
            "scenario_positive_URL_cases": sum(r.get("label") == 1 and bool(r.get("urls")) for r in group),
            "scenario_positive_URL_components": len({r["group_id"] for r in group if r.get("label") == 1 and r.get("urls")}),
            "behavior_positive_URL_cases": sum(r.get("behavior_label") == 1 and bool(r.get("urls")) for r in group),
            "behavior_positive_URL_components": len({r["group_id"] for r in group if r.get("behavior_label") == 1 and r.get("urls")}),
        }
    overlapping_sources = sum(bool(items) for items in overlap.get("sources", {}).values())
    reference = _optional_verify("evaluation.data.adjudicated_reference", final_reference, reference_sha, "Final reference")
    if reference is not None:
        if reference.get("status") != "declared_human_adjudicated_reference_not_independently_authenticated":
            raise ValueError("Final reference must explicitly declare human adjudication and its authentication limits.")
        labels = reference.get("labels", [])
        keyed_inputs = {row["sample_id"]: row for row in inputs.values()}
        if (reference.get("rows") != len(inputs) or not isinstance(labels, list)
                or {row.get("sample_id") for row in labels} != set(keyed_inputs)
                or len(labels) != len(inputs)):
            raise ValueError("Final human reference does not match the frozen annotation inventory.")
        if any(row.get("text_sha256") != human_review.text_digest(keyed_inputs[row["sample_id"]]["text_redacted"])
               for row in labels):
            raise ValueError("Final human reference text differs from the frozen annotation inventory.")
        provenance = reference.get("provenance", {})
        ref_packet_sha = provenance.get("inventory_manifest_sha256", provenance.get("manifest_sha256"))
        if ref_packet_sha != packet_sha:
            raise ValueError("Final reference is not tied to the frozen human packet.")
    runtime = _optional_verify("evaluation.messages.runtime_evaluation", runtime_run, run_sha, "Runtime run")
    if runtime is not None:
        if reference is None or runtime.get("reference_sha256") != reference_sha:
            raise ValueError("Runtime run differs from the supplied finalized reference.")
        if runtime.get("split") != "dev" or runtime.get("mode") != "registered_runtime_development_evaluation":
            raise ValueError("Only declared development runtime evidence is supported.")
    software = _checks(checkslatest)
    blockers = {"runtime_evaluation": [], "independent_quality_claim": [], "release": []}
    if reference is None:
        blockers["runtime_evaluation"].append("human_reference_not_finalized")
    blockers["independent_quality_claim"].append("author_exposed_purposive_supplement_is_not_independent_population_test")
    if counts.get("received_original_messages", 0) == 0:
        blockers["independent_quality_claim"].append("no_authenticated_received_original_messages")
    if any(v["behavior_positive_URL_components"] < 5 for v in components.values()):
        blockers["independent_quality_claim"].append("few_independent_positive_URL_components")
    if overlapping_sources:
        blockers["independent_quality_claim"].append("evaluation_sources_overlap_RAG_corpus")
    if reference is None:
        blockers["independent_quality_claim"].append("human_reference_not_finalized")
    if runtime is None or runtime.get("complete") is not True:
        blockers["independent_quality_claim"].append("runtime_evaluation_not_completed")
    else:
        blockers["independent_quality_claim"].append("completed_runtime_evaluation_is_development_only")
    if not software["verified"]:
        blockers["release"].append("recorded_software_checks_missing_or_failed")
    blockers["release"] += ["independent_detection_quality_not_established", "operating_configuration_not_validated_for_real_use"]
    result = {"version": VERSION, "status": "blocked", "ready_for_human_annotation": True,
        "ready_for_runtime_evaluation": reference is not None,
        "ready_for_independent_quality_claim": False, "ready_for_release": False,
        "software_verified": software["verified"], "software_checks": software,
        "research_independence": "not_established", "production_readiness": "not_established",
        "blockers": blockers,
        "annotation": {"rows": len(inputs), "packet_manifest_sha256": packet_sha,
            "final_reference_verified": reference is not None,
            "completed_human_labels": len(inputs) if reference else None,
            "completion_note": "No returned reviews inspected when no finalized reference is supplied; pending is not inferred as a label."},
        "data": {"cases": verified["cases"], "sources": verified.get("sources"),
            "base_cases": counts.get("base_cases"), "injection_variants": counts.get("injection_variants"),
            "received_original_messages": counts.get("received_original_messages"),
            "author_exposed": readiness.get("test_status") == "locked_author_exposed_holdout_not_independent_blind",
            "source_overlap_count": overlapping_sources, "source_overlap_denominator": len(overlap.get("sources", {})),
            "components": components, "collection_shortfalls": [r for r in counts.get("quotas", []) if r.get("shortfall", 0)]},
        "runtime": None if runtime is None else {key: runtime.get(key) for key in (
            "complete", "profile", "split", "mode", "physical_requests", "real_provider_calls")},
        "provenance": {"pack_manifest_sha256": pack_sha256, "reference_manifest_sha256": reference_sha,
            "runtime_manifest_sha256": run_sha},
        "limits": ["A verified manifest confirms artifact consistency, not correctness or independence of human judgments.",
            "Software node counts are not a model accuracy score; gold/silver dataset tiers are not new human labels.",
            "Fewer than five positive-URL components is a diagnostic scarcity flag, not a statistical power or quality threshold.",
            "This command does not run tests or inference, scan secrets, fill labels, or change application defaults."],
        "provider_calls_by_this_check": 0, "labels_generated": 0}
    if out is not None:
        target = Path(out)
        if target.exists():
            raise ValueError("Choose a new readiness output; existing evidence is preserved.")
        if target.suffix.lower() != ".json":
            target.mkdir(parents=True)
            target = target / "readiness.json"
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--pack-sha256", required=True)
    parser.add_argument("--registration", type=Path)
    parser.add_argument("--final-reference", type=Path)
    parser.add_argument("--reference-sha256")
    parser.add_argument("--runtime-run", type=Path)
    parser.add_argument("--run-sha256")
    parser.add_argument("--checks", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    try:
        result = check(args.pack, args.pack_sha256, args.registration, args.final_reference,
            args.reference_sha256, args.runtime_run, args.run_sha256, args.checks, args.out)
    except (ValueError, OSError, json.JSONDecodeError, ET.ParseError) as exc:
        print(json.dumps({"status": "invalid_evidence", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
