"""Offline safeguards for the small, author-exposed evidence development pilot."""
from copy import deepcopy
import csv
import json
from types import SimpleNamespace

import pytest

from evaluation.data.sms import read_jsonl, sha, write_json, write_jsonl
from evaluation.messages import evidence_pilot as study


def review(case_id, label, *, reviewer="codex_ai_A", quote="Thông báo"):
    return {"id": case_id, "behavior_label": label, "quote": quote if label is not None else "",
            "reviewer": reviewer, "human_gold": False, "notes": "Visible action only; provisional AI review."}


def test_review_requires_exact_inventory_and_evidence_not_fabricated_truth():
    inputs = [{"id": "a", "text": "Thông báo lịch hẹn."}, {"id": "b", "text": "Cần bổ sung thông tin."}]
    rows = [review("a", 0), review("b", None)]
    assert study.validate_review(rows, inputs, "codex_ai_A") == {r["id"]: r for r in rows}
    for invalid in (rows[:1], rows + [rows[0]], [rows[0], {**rows[1], "id": "other"}]):
        with pytest.raises(ValueError, match="inventory"):
            study.validate_review(invalid, inputs, "codex_ai_A")


@pytest.mark.parametrize("patch", [
    {"behavior_label": True}, {"behavior_label": "0"}, {"behavior_label": 2},
    {"quote": "invented evidence"}, {"quote": ""}, {"quote": "x" * 241},
    {"human_gold": True}, {"human_gold": None}, {"reviewer": "anonymous"}, {"notes": ""},
    {"behavior_label": None, "quote": "Thông báo"},
])
def test_review_rejects_invalid_or_untraceable_labels(patch):
    with pytest.raises(ValueError):
        study.validate_review([{**review("a", 0), **patch}], [{"id": "a", "text": "Thông báo lịch hẹn."}], "codex_ai_A")


@pytest.fixture
def review_scope(tmp_path, monkeypatch):
    pack = tmp_path / "pack"; pack.mkdir()
    root = tmp_path / "pilot"; root.mkdir()
    dev = [{"id": "a", "text": "Thông báo lịch hẹn.", "behavior_label": 1, "label": 1},
           {"id": "b", "text": "Thông báo chưa rõ.", "behavior_label": 0, "label": None},
           {"id": "c", "text": "Thông báo về tài khoản.", "behavior_label": None, "label": 1}]
    monkeypatch.setattr(study, "development", lambda p: deepcopy(dev))
    write_jsonl(pack / "cases.jsonl", dev); write_json(pack / "manifest.json", {"frozen": True})
    write_jsonl(root / "blind_dev_inputs.jsonl", [{"id": r["id"], "text": r["text"]} for r in dev])
    write_json(root / "label_review_protocol.json", {"human_gold": False})
    a = [review("a", 0), review("b", 0), review("c", None)]
    b = [review("a", 0, reviewer="codex_ai_B"), review("b", 1, reviewer="codex_ai_B"),
         review("c", None, reviewer="codex_ai_B")]
    write_jsonl(root / "reviewer_a.jsonl", a); write_jsonl(root / "reviewer_b.jsonl", b)
    return root, pack, dev


def test_reference_pack_preserves_originals_and_ai_disagreement_is_unknown(review_scope):
    root, pack, original = review_scope
    before = sha(pack / "cases.jsonl")
    result = study.reference_pack(root, pack)
    labels = study.load_reference(root / "reference")
    assert [labels[r["id"]]["author_behavior_label"] for r in original] == [1, 0, None]
    assert [labels[r["id"]][study.PRIMARY_SCOPE] for r in original] == [0, None, None]
    assert [labels[r["id"]]["scenario_label"] for r in original] == [1, None, 1]
    assert result["human_gold"] is False and result["classifier_outputs_seen"] is False
    assert result["agreement"] == 2 and result["different_from_author"] == 2
    assert sha(pack / "cases.jsonl") == before
    with (root / "reference/review_differences.csv").open(encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[1]["agreed_behavior"] == ""  # Null must not silently become zero.
    with pytest.raises(ValueError, match="Preserve"):
        study.reference_pack(root, pack)


@pytest.mark.parametrize("target", ["reviewer_a.jsonl", "reference/labels.jsonl"])
def test_reference_hashes_detect_input_or_output_relabeling(review_scope, target):
    root, pack, _ = review_scope
    study.reference_pack(root, pack)
    with (root / target).open("a") as stream: stream.write("\n")
    with pytest.raises(ValueError, match="changed"):
        study.load_reference(root / "reference")


def test_blind_review_inputs_must_match_frozen_text(review_scope):
    root, pack, _ = review_scope
    inputs = read_jsonl(root / "blind_dev_inputs.jsonl"); inputs[0]["text"] += " changed"
    write_jsonl(root / "blind_dev_inputs.jsonl", inputs)
    with pytest.raises(ValueError, match="Blind review inputs differ"):
        study.reference_pack(root, pack)
    assert not (root / "reference").exists()


def candidate_inventory():
    rows = []
    for has_url in (True, False):
        for index in range(8):
            group = f"{'URL' if has_url else 'plain'}-group-{index}"
            for alternative in range(2):
                case_id = f"{group}-case-{alternative}"
                rows.append({"id": case_id, "group_id": group, "split": "dev", "text": "Tin nhắn.",
                    "urls": [f"https://host{index}.example/"] if has_url else [],
                    "label": index % 2, "behavior_label": 1, "score": index / 10})
    return rows


def test_selection_is_deterministic_label_score_independent_and_source_group_unique():
    rows = candidate_inventory(); before = deepcopy(rows)
    selected = study.select_cases(rows)
    assert len(selected) == 12 and len({r["group_id"] for r in selected}) == 12
    assert sum(bool(r["urls"]) for r in selected) == 6
    assert rows == before
    altered = deepcopy(list(reversed(rows)))
    for row in altered: row.update(label=None, behavior_label=0, score=1)
    assert [r["id"] for r in study.select_cases(altered)] == [r["id"] for r in selected]


def test_selection_rejects_holdout_and_missing_strata():
    rows = candidate_inventory()
    rows[0]["split"] = "test"
    with pytest.raises(ValueError, match="Holdout"):
        study.select_cases(rows)
    with pytest.raises(ValueError, match="six independent"):
        study.select_cases([r for r in rows[1:] if not r["urls"]])


def test_development_verifies_frozen_pack_and_returns_only_dev(tmp_path, monkeypatch):
    rows = [{"id": "development", "text": "Visible dev.", "split": "dev"},
            {"id": "holdout", "text": "Never select.", "split": "test"}]
    write_jsonl(tmp_path / "cases.jsonl", rows)
    verified = []
    monkeypatch.setattr(study.evidence_messages, "verify", lambda pack: verified.append(pack))
    assert study.development(tmp_path) == rows[:1]
    assert verified == [tmp_path.resolve()]


def test_selection_prioritizes_url_representative_within_mixed_component():
    rows = candidate_inventory()
    for row in rows:
        if row["id"].startswith("URL-") and row["id"].endswith("-0"): row["urls"] = []
    selected = study.select_cases(rows)
    assert sum(bool(r["urls"]) for r in selected) == 6
    assert all(r["id"].endswith("-1") for r in selected if r["urls"])


def test_injection_selection_adds_at_most_four_existing_pairs_on_selected_bases():
    rows = candidate_inventory()
    selected = study.select_cases(rows)
    rows = candidate_inventory() + [{**base, "id": base["id"] + f"-injection-{index}", "base_id": base["id"]}
                                  for base in candidate_inventory() for index in range(2)]
    combined = study.select_cases(rows)
    base_ids = {r["id"] for r in selected}
    variants = [r for r in combined if r.get("base_id")]
    assert len(variants) == 4
    assert all(r["base_id"] in base_ids for r in variants)
    assert {r["id"] for r in combined if not r.get("base_id")} == base_ids


def payload_inventory():
    cases = [{"id": "with", "text": "Thông báo https://example.org/verify", "label": 1,
              "source_ids": ["DO_NOT_SEND_SOURCE"], "reference_basis": "DO_NOT_SEND_REFERENCE"},
             {"id": "without", "text": "Thông báo lịch hẹn.", "label": 0}]
    metadata = {"id": "URL-01", "url": "https://example.org/verify", "score": .9,
                "risk_level": "HIGH", "warning_threshold": .8, "high_threshold": .8}
    prepared = {"with": {"real_metadata": [metadata]}, "without": {"real_metadata": []}}
    return cases, prepared


def test_payloads_vary_only_url_metadata_rag_arms_alias_and_missing_url_reuses_response():
    cases, prepared = payload_inventory(); before = deepcopy(prepared)
    requests, cells = study.bind_requests(cases, prepared, "fixture")
    assert len(requests) == 3 and len(cells) == 8 and prepared == before
    by_key = {row["key"]: row for row in requests}
    lookup = {(r["id"], r["arm"]): r for r in cells}
    for case in cases:
        assert lookup[(case["id"], "llm_only")]["request_key"] == lookup[(case["id"], "llm_rag_post")]["request_key"]
        assert lookup[(case["id"], "llm_url")]["request_key"] == lookup[(case["id"], "llm_url_rag_post")]["request_key"]
        bodies = []
        for cell in (r for r in cells if r["id"] == case["id"]):
            body = deepcopy(by_key[cell["request_key"]]["payload"])
            assert body["max_tokens"] == 2048 and body["thinking"] == {"type": "disabled"}
            data = json.loads(body["messages"][1]["content"])
            assert set(data) <= {"text", "assessment_target", "output_schema", "url_results"}
            assert "DO_NOT_SEND" not in json.dumps(body)
            data.pop("url_results", None); body["messages"][1]["content"] = data; bodies.append(body)
        assert all(body == bodies[0] for body in bodies)
    assert len({r["request_key"] for r in cells if r["id"] == "without"}) == 1
    assert requests == study.bind_requests(list(reversed(cases)), prepared, "fixture")[0]


def test_provider_metadata_must_match_declared_approved_metadata():
    cases, prepared = payload_inventory()
    prepared["with"]["real_metadata"][0]["url"] = "https://absent.example/"
    with pytest.raises(ValueError, match="Provider metadata differs"):
        study.bind_requests(cases, prepared, "fixture")


@pytest.fixture
def preparation(tmp_path, monkeypatch):
    root = tmp_path / "pilot"; root.mkdir()
    (root / "reference").mkdir()
    write_json(root / "reference/manifest.json", {"human_gold": False})
    write_json(root / "label_review_protocol.json", {"human_gold": False})
    pack = tmp_path / "pack"; pack.mkdir()
    write_json(pack / "manifest.json", {"locked": True})
    write_jsonl(pack / "cases.jsonl", [])
    model_dir = tmp_path / "URL_model"; model_dir.mkdir()
    (model_dir / "weights").write_text("fixture weights")
    preprocessing = tmp_path / "preprocessing.py"; preprocessing.write_text("fixture = True\n")
    settings = SimpleNamespace(root=tmp_path, llm_model="fixture", rag_corpus="corpus.jsonl",
                               rag_index_dir="rag_index", rag_model_dir="rag_model")
    for relative in ("rag_index/index", "rag_model/weights", "app/services/url/resources/rules"):
        path = tmp_path / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_text("fixture")
    (tmp_path / settings.rag_corpus).write_text("{}\n")
    rows = []
    for has_url in (True, False):
        for index in range(6):
            case_id = f"{'URL' if has_url else 'plain'}-{index}"
            urls = [f"https://host{index}.example/notice"] if has_url else []
            rows.append({"id": case_id, "group_id": case_id, "split": "dev", "urls": urls,
                         "text": "Thông báo " + " ".join(urls) if urls else "Thông báo lịch hẹn."})
    refs = {r["id"]: {"id": r["id"], study.PRIMARY_SCOPE: None, "author_behavior_label": None} for r in rows}
    monkeypatch.setattr(study, "development", lambda p: deepcopy(rows))
    monkeypatch.setattr(study, "load_reference", lambda p: deepcopy(refs))
    monkeypatch.setattr(study, "Settings", lambda: settings)
    class Model:
        path = model_dir
        preprocessing_path = preprocessing
        ready = True
        def status(self): return {"ready": self.ready, "fixture": True}
    model = Model()
    monkeypatch.setattr(study, "CharURLService", lambda: model)
    def score(cases, local):
        prepared = {}
        for row in cases:
            metadata = [{"id": "URL-01", "url": url, "score": .9, "risk_level": "HIGH",
                         "warning_threshold": .8, "high_threshold": .8, "status": "ok"} for url in row["urls"]]
            prepared[row["id"]] = {"raw_url_results": metadata, "operating_url_results": metadata}
        return prepared
    monkeypatch.setattr(study, "score_cases", score)
    registrations = []
    def register(out, requests, **kwargs):
        registrations.append((out, requests, kwargs))
        out.mkdir()
        return {"source_files_sha256": {}, "metadata": kwargs["metadata"], "max_attempts": len(requests)}
    monkeypatch.setattr(study.registered, "register", register)
    return SimpleNamespace(root=root, pack=pack, model=model, registrations=registrations, settings=settings)


def test_prepare_pins_bounded_runtime_assets_and_control_design(preparation):
    item = preparation
    result = study.prepare(item.root, item.pack)
    assert result["workers"] == 1 and result["timeout_seconds"] == 45
    assert result["metadata"]["logical_cells"] == 48 and result["max_attempts"] == 18
    assert result["metadata"]["human_gold"] is False
    assert result["metadata"]["holdout_inference"] is False
    assert result["metadata"]["old_120_reserve_inference"] is False
    assert result["metadata"]["pilot_unique_requests"] == 4
    assert result["metadata"]["no_auto_app_promotion"] is True
    _, requests, kwargs = item.registrations[0]
    assert kwargs["max_tokens"] == 2048 and kwargs["token_budget"] == 100000
    assert all(r["payload"]["model"] == "fixture" for r in requests)
    locks = {str(path) for path in kwargs["locks"]}
    assert str(item.pack / "manifest.json") in locks
    assert str(item.root / "reference/manifest.json") in locks
    assert str(item.settings.root / "rag_index/index") in locks
    assert str(item.settings.root / "rag_model/weights") in locks
    assert str(item.settings.root / "corpus.jsonl") in locks
    assert (item.root / "classification/registration.sha256").read_text().strip() == sha(item.root / "classification/execution.json")
    with pytest.raises(ValueError, match="Preserve"):
        study.prepare(item.root, item.pack)


def test_failed_local_preflight_never_registers_provider_requests(preparation):
    item = preparation; item.model.ready = False
    with pytest.raises(ValueError, match="Local URL preflight failed"):
        study.prepare(item.root, item.pack)
    assert item.registrations == []
    assert not (item.root / "classification").exists()


@pytest.fixture
def report_fixture(tmp_path, monkeypatch):
    inputs = tmp_path / "classification_inputs"; inputs.mkdir()
    cases = [{"id": "a", "group_id": "ga"}, {"id": "b", "group_id": "gb"},
             {"id": "c", "group_id": "gc"}, {"id": "d", "group_id": "gd"},
             {"id": "a-inj", "group_id": "ga", "base_id": "a"}]
    refs = [{"id": row["id"], study.PRIMARY_SCOPE: [1, 0, None, 1, 1][i],
             "author_behavior_label": [0, 0, 1, 1, 0][i]} for i, row in enumerate(cases)]
    cells, records = [], {}
    stage = "fixture-stage"
    for row in cases:
        for arm in study.ARMS:
            parent = "llm_url" if arm in {"llm_url", "llm_url_rag_post"} else "llm_only"
            key = row["id"] + "::" + parent
            cells.append({"id": row["id"], "arm": arm, "request_key": key,
                          "URL_context_available": row["id"] in {"a", "c"}, "injection": bool(row.get("base_id"))})
            parsed = {"status": "error", "code": "OUTPUT_TRUNCATED"} if row["id"] == "a" else {
                "status": "ok", "verdict": {"risk_level": {"b": "UNKNOWN", "c": "HIGH", "d": "HIGH", "a-inj": "LOW"}[row["id"]]}}
            records[(stage, key)] = {"parsed": parsed, "elapsed_ms": 5, "usage": {"total_tokens": 12}}
    cfg = {"stage": stage, "max_attempts": len(records), "metadata": {"inputs": str(inputs)}}
    write_jsonl(inputs / "cases.jsonl", cases); write_jsonl(inputs / "references.jsonl", refs)
    write_jsonl(inputs / "cells.jsonl", cells)
    monkeypatch.setattr(study.registered, "verify", lambda *args: {"complete": True})
    monkeypatch.setattr(study.registered, "load", lambda *args: (cfg, {}))
    monkeypatch.setattr(study.registered, "checkpoints", lambda *args: ({}, records))
    return tmp_path, cfg, records


def test_complete_report_keeps_errors_and_unknowns_and_separates_injection_and_original_scope(report_fixture):
    root, cfg, records = report_fixture
    result = study.report(root)
    assert result["complete"] and result["independent_accuracy"] is None
    m = result["blind_AI_agreement"]["llm_only"]["all"]
    assert m["n"] == 3 and m["all_cases"] == 4 and m["reference_UNKNOWN"] == 1
    assert m["unknown_positive"] == 1 and m["unknown_negative"] == 1 and m["tp"] == 1
    assert m["accuracy"] == pytest.approx(1 / 3) and m["coverage"] == pytest.approx(1 / 3)
    assert m["recall"] == .5 and m["f1"] == pytest.approx(2 / 3)
    assert m["technical_errors"] == 1 and m["semantic_UNKNOWN"] == 1
    assert m["UNKNOWN_reference_predictions"] == {"HIGH": 1}
    assert result["blind_AI_agreement"]["llm_rag_post"] == result["blind_AI_agreement"]["llm_only"]
    original = result["original_author_sensitivity"]["llm_only"]["all"]
    assert original["n"] == 4 and original["tp"] == 2 and original["unknown_negative"] == 2
    assert len(result["injection_pairs"]) == 2
    assert all(row["attack_success_rate"] is None for row in result["injection_pairs"])
    assert result["physical_run"]["errors"] == {"OUTPUT_TRUNCATED": 2}
    assert len(read_jsonl(root / "decisions.jsonl")) == 20


def test_incomplete_run_preserves_pending_without_publishing_quality_table(report_fixture, monkeypatch):
    root, cfg, records = report_fixture
    records.pop(next(iter(records)))
    monkeypatch.setattr(study.registered, "verify", lambda *args: {"complete": False})
    result = study.report(root)
    assert result["complete"] is False
    assert "blind_AI_agreement" not in result and "original_author_sensitivity" not in result
    assert any(row["status"] == "pending" and row["level"] == "UNKNOWN" for row in read_jsonl(root / "decisions.jsonl"))
    assert "| Precision |" not in (root / "report.md").read_text()
