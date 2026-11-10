"""Independent arithmetic/provenance checks for the paired v3/v4 pilot."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from app.services.llm.message import payload_for
from app.services.llm.client import _parse_verdict_with_validation, LLMFailure
from evaluation.data.sms import read_jsonl, sha, write_json
from evaluation.messages.quality_pilot import ARMS, score, level
from evaluation.messages.url_context import canonical_sha
from scripts.evaluation.report_components import paired_bootstrap
from scripts.evaluation.report_url_context import check_metrics


def verify(run):
    cfg = json.loads((run / "execution.json").read_text())["configuration"]
    assert all(sha(p) == digest for p, digest in cfg["source_hashes"].items())
    cases, records, attempts = (read_jsonl(run / name) for name in ("cases.jsonl", "predictions.jsonl", "attempts.jsonl"))
    assert canonical_sha(cases) == cfg["cases_sha256"]
    lookup = {(r["id"], r["arm"]): r for r in records}
    journal = {(r["id"], r["arm"]): r for r in attempts}
    expected = {(c["id"], a) for c in cases for a in ARMS}
    assert set(lookup) == set(journal) == expected
    assert len(records) == len(lookup) == len(attempts) == cfg["max_calls"]
    for c in cases:
        for arm in ARMS:
            r = lookup[(c["id"], arm)]
            payload, _ = payload_for(text=c["text"], urls=[], include_ml=False, sources=[], model=cfg["model"], max_tokens=8192, profile=arm)
            digest = canonical_sha(payload)
            assert journal[(c["id"], arm)]["payload_sha256"] == digest
            assert r.get("payload_sha256", digest if r.get("code") == "INTERRUPTED_REQUEST" else None) == digest
            if r["status"] == "ok":
                verdict, warnings, validation = _parse_verdict_with_validation(r["raw_content"], c["text"], None, "message-v3")
                assert verdict.model_dump() == r["verdict"] and warnings == r["warnings"] and validation == r["validation"]
            elif r["code"] == "OUTPUT_TRUNCATED":
                assert r["finish_reason"] == "length"
    saved = json.loads((run / "summary.json").read_text())
    recalculated = score(cases, records)
    assert saved["metrics_ready"] and saved["state"]["stop_reason"] == "all_calls_completed"
    assert all(saved[k] == value for k, value in recalculated.items())
    adapted = {(id_, arm, 1): {"status": r["status"], "outputs": {"message_behavior": level(r)}} for (id_, arm), r in lookup.items()}
    bootstrap = {}
    for dataset, arms in saved["metrics"].items():
        subset = [c for c in cases if c["dataset"] == dataset]
        for arm, m in arms.items():
            check_metrics(subset, adapted, arm, 1, "message_behavior", {**m,
                "reference_unknown_count": sum(c["targets"]["message_behavior"] is None for c in subset),
                "reference_unknown_predictions": m["reference_unknown"],
                "technical_errors": sum(lookup[(c["id"], arm)]["status"] == "error" for c in subset)})
        paired = {(id_, arm): r for (id_, arm, repeat), r in adapted.items()}
        bootstrap[dataset] = paired_bootstrap(subset, paired, "message_behavior", *ARMS)
    return cfg, cases, records, saved, bootstrap


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("Choose a new output directory.")
    cfg, cases, records, result, bootstrap = verify(args.run)
    args.out.mkdir(parents=True)
    write_json(args.out / "summary.json", {"configuration": cfg, "results": result, "bootstrap": bootstrap})
    fmt = lambda v: "N/A" if v is None else f"{100*v:.2f}%"
    lines = ["# Paired v3/v4 message-policy dev pilot", "",
        "**AI SMS reference labels and authored regression contexts; not human gold.** Both profiles use the production "
        "MessageVerdict schema and the same structural validator, model, text and decoding budget. Only the system prompt differs. "
        "No URL scores or RAG were supplied to either arm. This is separate from the earlier three-target component prompt.", "",
        f"{len(cases)} inputs, {len(records)} provider attempts, one generation/profile; errors retained. Test untouched.", ""]
    for dataset, arms in result["metrics"].items():
        lines += ["## " + dataset, "", "| Policy | n | Precision | Recall | F1 | FPR | Accuracy | Coverage | UNKNOWN +/− |",
                  "|---|---:|---:|---:|---:|---:|---:|---:|---|"]
        for arm, m in arms.items():
            lines.append(f"| {arm} | {m['n']} | {fmt(m['precision'])} | {fmt(m['recall'])} | {fmt(m['f1'])} | "
                         f"{fmt(m['false_positive_rate'])} | {fmt(m['accuracy'])} | {fmt(m['coverage'])} | {m['unknown_positive']}/{m['unknown_negative']} |")
        lines += ["", f"Paired counts: {result['paired'][dataset]}", f"Exploratory group-bootstrap F1 delta: {bootstrap[dataset]}", "",
                  "Reference UNKNOWN distributions: " + str({a: m["reference_unknown"] for a, m in arms.items()}), ""]
    lines += ["## Predeclared development gates", "", str(result["gates"]), "",
        "These gates constrain false-alarm reduction, recall, coverage and educational regressions. Passing does not certify generalization. "
        "References/development inputs were previously inspected; only one candidate was tested in this round. "
        "RAG configurations were not re-evaluated live in this pilot.", "",
        "Errors: " + str(result["errors"]), "Token usage: " + str(result["usage"])]
    (args.out / "report.md").write_text("\n".join(lines) + "\n")
    write_json(args.out / "verification.json", {"verified": True, "created_at": datetime.now(timezone.utc).isoformat(),
        "cases": len(cases), "provider_attempts": len(records), "checks": "raw responses, payloads, source hashes, sklearn P/R/F1/accuracy/FPR/coverage, paired counts",
        "reporter_sha256": sha(__file__), "source_support_or_human_labels_verified": False,
        "input_hashes": {n: sha(args.run / n) for n in ("execution.json", "cases.jsonl", "predictions.jsonl", "attempts.jsonl", "summary.json")}})
    print(json.dumps({"report": str(args.out / "report.md"), "verified": True, "development_gates_passed": result["gates"]["passed"]}))


if __name__ == "__main__":
    main()
