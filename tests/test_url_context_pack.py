"""Check selection fairness, target separation and incomplete-run safeguards."""
import copy
import csv
import json

import pandas as pd
import pytest

from evaluation import url_context_pack as pack
from evaluation import url_context_score as scoring


def urls_fixture():
    return [{"id": f"fixture-{split}-{label}", "url": f"https://{split}-{label}.example/path",
             "url_label": label, "split": split, "domain_group": f"{split}-{label}.example",
             "source": "fixture", "tier": "silver"}
            for split in ("dev", "test") for label in (0, 1)]


def complete_records(cases, repetitions=1):
    # Explicitly fake predictions for unit tests, never saved as experiment output.
    return [{"id": c["id"], "arm": arm, "repeat": rep, "status": "ok",
             "outputs": {target: "UNKNOWN" if c["targets"][target] is None or (arm == "url_model" and target != "url_risk")
                         else "HIGH" if c["targets"][target] else "LOW" for target in pack.TARGETS}}
            for c in cases for arm in pack.ARMS for rep in ([0] if arm == "url_model" else range(1, repetitions + 1))]


def test_sampling_is_invariant_to_input_order_and_arbitrary_model_scores():
    frames = {split: pd.DataFrame([{"id": f"{split}-{label}-{i}", "source": "fixture", "tier": "silver",
        "labels": label, "domain_group": f"{split}-{label}-{i}.example", "url": f"https://{split}-{label}-{i}.example/",
        "score": float(i % 2)} for label in (0, 1) for i in range(8)]) for split in ("val", "test")}
    quotas = {split: [("fixture", "silver", label, 3) for label in (0, 1)] for split in ("dev", "test")}
    excluded = {"test-1-0.example"}
    first, _ = pack.select_urls(frames, excluded, quotas)
    perturbed = {k: v.sample(frac=1, random_state=77).assign(score=1 - v.score) for k, v in frames.items()}
    second, _ = pack.select_urls(perturbed, excluded, quotas)
    assert first == second
    assert len(first) == len({r["domain_group"] for r in first}) == 12
    assert all("score" not in r and r["domain_group"] not in excluded for r in first)


def test_not_enough_domains_fails_instead_of_relaxing_quotas():
    row = {"id": "x", "source": "fixture", "tier": "silver", "labels": 1,
           "domain_group": "same.example", "url": "https://same.example"}
    frames = {"val": pd.DataFrame([row, {**row, "id": "y"}])}
    with pytest.raises(ValueError, match="Insufficient distinct domains"):
        pack.select_urls(frames, set(), {"dev": [("fixture", "silver", 1, 2)]})


def test_url_reference_does_not_override_context_and_injection_does_not_change_target():
    urls = urls_fixture()
    cases = pack.make_cases(urls)
    pack.validate_cases(urls, cases)
    for r in urls:
        variants = {c["variant"]: c for c in cases if c["url_id"] == r["id"]}
        assert variants["neutral_link"]["targets"]["message_behavior"] is None
        assert variants["neutral_link"]["targets"]["action_risk"] == r["url_label"]
        assert variants["secret_request"]["targets"]["action_risk"] == 1
        assert variants["education"]["targets"]["action_risk"] == 0
        assert variants["secret_request"]["targets"] == variants["secret_injection"]["targets"]
        assert variants["education"]["targets"] == variants["education_injection"]["targets"]
        assert all(c["targets"]["url_risk"] == r["url_label"] for c in variants.values())


def test_provider_payload_hides_references_and_split():
    c = pack.make_cases(urls_fixture())[0]
    c.update(source="secret source", tier="gold", rationale="answer", label=1)
    assert pack.provider_input(c) == {"task": c["task"], "text": c["text"], "url_model": []}


def test_variant_cannot_move_across_split_or_change_reference():
    urls = urls_fixture()
    cases = pack.make_cases(urls)
    altered = copy.deepcopy(cases)
    altered[0]["split"] = "test"
    with pytest.raises(ValueError, match="leakage"):
        pack.validate_cases(urls, altered)
    altered = copy.deepcopy(cases)
    altered[0]["targets"]["url_risk"] = 1
    with pytest.raises(ValueError, match="URL label"):
        pack.validate_cases(urls, altered)


def test_missing_or_failed_predictions_are_not_silently_dropped():
    urls = urls_fixture()
    cases = [c for c in pack.make_cases(urls) if c["split"] == "dev"]
    records = complete_records(cases)
    pending = scoring.score(cases, urls, records[:-1], 1)
    assert pending["metrics_ready"] is False and pending["metrics"] is None
    positive = next(r for r in records if r["id"] == "fixture-dev-1-url" and r["arm"] == "llm_url")
    positive.update(status="error", outputs={}, error_code="SIMULATED_TEST_ERROR")
    result = scoring.score(cases, urls, records, 1)
    m = result["metrics"]["url_only"]["url_risk"]["by_repeat"]["llm_url"]["1"]
    assert m["n"] == 2 and m["unknown_positive"] == 1
    assert m["recall"] == 0 and m["f1"] == 0 and m["accuracy"] == .5
    behavior = result["metrics"]["message_context"]["message_behavior"]["by_repeat"]["llm_only"]["1"]
    assert behavior["reference_unknown_count"] == 2 and behavior["n"] == 8


def test_duplicates_foreign_ids_and_fake_context_predictions_are_rejected():
    cases = pack.make_cases(urls_fixture())
    records = complete_records(cases)
    with pytest.raises(ValueError, match="Duplicate"):
        scoring.score(cases, urls_fixture(), records + [records[0]], 1)
    records[0]["id"] = "unknown-id"
    with pytest.raises(ValueError, match="unexpected"):
        scoring.score(cases, urls_fixture(), records, 1)
    records = complete_records(cases)
    model = next(r for r in records if r["arm"] == "url_model")
    model["outputs"]["message_behavior"] = "LOW"
    with pytest.raises(ValueError, match="cannot claim"):
        scoring.score(cases, urls_fixture(), records, 1)


def test_repeat_results_are_reported_separately_not_best_selected():
    urls = urls_fixture()
    cases = pack.make_cases(urls)
    records = complete_records(cases, 2)
    for r in records:
        if r["arm"] == "llm_url" and r["repeat"] == 2:
            r["outputs"] = {k: "LOW" for k in pack.TARGETS}
    result = scoring.score(cases, urls, records, 2)
    m = result["metrics"]["url_only"]["url_risk"]
    assert m["by_repeat"]["llm_url"]["1"]["f1"] == 1
    assert m["by_repeat"]["llm_url"]["2"]["f1"] == 0
    assert m["repeat_summary"]["llm_url"]["f1"]["mean"] == .5
    assert m["paired"]["llm_only_to_llm_url"]["2"]["regressed"] == 2


def test_frozen_pack_checksums_and_blind_sheets(tmp_path):
    # Minimal on-disk pack; real source preparation is checked separately offline.
    urls = urls_fixture()
    cases = pack.make_cases(urls)
    pack.write_jsonl(tmp_path / "urls.jsonl", urls)
    for split in ("dev", "test"):
        rows = [c for c in cases if c["split"] == split]
        pack.write_jsonl(tmp_path / f"{split}.jsonl", rows)
        pack.write_jsonl(tmp_path / f"{split}_inputs.jsonl", [{"id": c["id"], "input": pack.provider_input(c)} for c in rows])
    pack.write_json(tmp_path / "audit.json", {"urls": len(urls), "cases": len(cases), "cases_by_split_task": {}})
    pack.export_csv(tmp_path / "reviewer_a.csv", cases, ["id", "task", "text", *pack.TARGETS, "rater_id"])
    files = {p.name: pack.sha(p) for p in tmp_path.iterdir() if p.name != "reviewer_a.csv"}
    pack.write_json(tmp_path / "manifest.json", {"files": files})
    assert pack.verify(tmp_path)["metrics_ready"] is False
    with (tmp_path / "reviewer_a.csv").open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert all(r[k] == "" for r in rows for k in (*pack.TARGETS, "rater_id"))
    (tmp_path / "reviewer_a.csv").write_text("human edits allowed")
    assert pack.verify(tmp_path)["urls"] == 4
    changed = tmp_path / "dev.jsonl"
    changed.write_text(changed.read_text() + "\n")
    with pytest.raises(ValueError, match="Frozen pack input changed"):
        pack.verify(tmp_path)
