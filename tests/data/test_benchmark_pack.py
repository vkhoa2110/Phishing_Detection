"""Evaluation setup tests use no LLM, model loading or human-review fabrication."""
import csv
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

import evaluation.data.benchmark as pack
from evaluation.data.sms import read_jsonl, sha, write_json
from evaluation.data.review import ReviewPending, finalize, validate_gold


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    model, index = tmp_path / "model", tmp_path / "index"
    model.mkdir(); index.mkdir()
    for path in (model / "config.json", model / "model.ubj"):
        path.write_text("offline fixture, not a model")
    (index / "manifest.json").write_text(json.dumps({"corpus_sha256": sha(pack.ROOT / "data/knowledge/corpus_v1/documents.jsonl")}))
    (index / "calibration.json").write_text(json.dumps({"index_manifest_sha256": sha(index / "manifest.json")}))
    monkeypatch.setattr(pack, "Settings", lambda: SimpleNamespace(
        model_dir=str(model), rag_index_dir=str(index), llm_model="offline-fixture", endpoint="https://example.org/v1/chat/completions"))
    source = pack.ROOT / "data/annotation/vn_sms_v2"
    original = {p.name: sha(p) for p in source.iterdir() if p.is_file()}
    out = tmp_path / "pack"
    summary = pack.prepare(out)
    assert {p.name: sha(p) for p in source.iterdir() if p.is_file()} == original
    return out, summary


def test_pack_has_isolated_inputs_and_no_unreviewed_gold(prepared, tmp_path):
    out, summary = prepared
    assert summary == {"status": "inputs_verified_not_gold", "sms": 200, "challenge": 72,
        "retrieval_queries": 24, "documents": 25, "pairs_per_rater": 600,
        "provider_requests": 0, "reference_labels_are_gold": False, "historical_runtime_verified": True}
    challenge = read_jsonl(out / "classification/challenge/items.jsonl")
    assert sum(i["prompt_injection"] for i in challenge) == 24
    assert {i["group_id"] for i in challenge if i["split"] == "dev"}.isdisjoint(
           {i["group_id"] for i in challenge if i["split"] == "test"})
    assert len({i["text"] for i in challenge}) == 72
    assert all("label" not in i for i in challenge)
    with pytest.raises(ReviewPending):
        finalize(out / "classification/sms", tmp_path / "gold")
    assert not (tmp_path / "gold").exists()
    for name in ("sms", "challenge"):
        ref = out / "provisional_reference" / name
        with pytest.raises(ValueError, match="double-reviewed"):
            validate_gold(ref / "manifest.json", ref / "test.jsonl")


def test_blind_packages_hide_references_scores_splits_and_each_others_reviews(prepared):
    out, _ = prepared
    for side in ("a", "b"):
        with zipfile.ZipFile(out / f"reviewer_{side}.zip") as archive:
            assert set(archive.namelist()) == {"sms.csv", "challenge.csv", "retrieval.csv", "README.md", "classification_rubric.json", "retrieval_rubric.json"}
            for name in ("sms.csv", "challenge.csv"):
                rows = list(csv.DictReader(archive.read(name).decode("utf-8-sig").splitlines()))
                assert all(not r[k] for r in rows for k in ("label", "notes", "rater_id", "evidence_quote"))
                assert not {"split", "variant", "source_label", "prediction", "risk_level"} & rows[0].keys()
    a = list(csv.DictReader((out / "classification/sms/annotator_a.csv").open(encoding="utf-8-sig")))
    b = list(csv.DictReader((out / "classification/sms/annotator_b.csv").open(encoding="utf-8-sig")))
    assert {r["id"] for r in a} == {r["id"] for r in b} and [r["id"] for r in a] != [r["id"] for r in b]


def test_reference_counts_unknowns_and_additional_masking_are_explicit(prepared):
    out, _ = prepared
    ref = out / "provisional_reference/sms"
    rows = [r for name in ("dev", "test", "dev_unknown", "test_unknown") for r in read_jsonl(ref / f"{name}.jsonl")]
    assert len(rows) == 200
    assert sum(r["label"] == 1 for r in rows) == 21
    assert sum(r["label"] == 0 for r in rows) == 111
    assert sum(r["label"] is None for r in rows) == 68
    assert all(r["annotation_status"] == "ai_reference_unverified" and r["rater_ids"] == [] for r in rows)
    assert all(q in r["text"] for r in rows for q in r["evidence_quotes"])
    assert all(r["rationale"].strip() for r in rows)
    mask = next(r for r in rows if r["id"] == "VN-SMS-9ba8ac88b6d21447")
    assert "MKC2) la [SECRET]" in mask["text"]
    with (ref / "review.csv").open(encoding="utf-8-sig") as f:
        exported = list(csv.DictReader(f))
    assert sum(r["label"] == "0" for r in exported) == 111


def test_frozen_inputs_refuse_tampering_and_existing_pack_is_immutable(prepared):
    out, _ = prepared
    before = {str(p.relative_to(out)): sha(p) for p in out.rglob("*") if p.is_file()}
    with pytest.raises(ValueError, match="fresh pack"):
        pack.prepare(out)
    assert before == {str(p.relative_to(out)): sha(p) for p in out.rglob("*") if p.is_file()}
    path = out / "provisional_reference/sms/review.csv"
    path.write_text(path.read_text(encoding="utf-8-sig") + "\n", encoding="utf-8-sig")
    with pytest.raises(ValueError, match="input changed"):
        pack.verify(out)


def test_rating_files_are_editable_but_candidate_text_is_not(prepared):
    out, _ = prepared
    path = out / "classification/sms/annotator_a.csv"
    path.write_text(path.read_text(encoding="utf-8-sig") + "\n", encoding="utf-8-sig")
    assert pack.verify(out)["status"] == "inputs_verified_not_gold"
    path = out / "classification/sms/items.jsonl"
    path.write_text(path.read_text() + "\n")
    with pytest.raises(ValueError, match="input changed"):
        pack.verify(out)


def test_reusing_inputs_does_not_claim_historical_runtime_equivalence(prepared):
    out, _ = prepared
    protocol = json.loads((out / "protocol.json").read_text())
    protocol["runtime_files_sha256"] = {"app/missing_historical_runtime.py": "0" * 64}
    write_json(out / "protocol.json", protocol)
    manifest = json.loads((out / "manifest.json").read_text())
    manifest["files"]["protocol.json"] = sha(out / "protocol.json")
    write_json(out / "manifest.json", manifest)
    with pytest.raises(ValueError, match="Runtime code changed"):
        pack.verify(out)
    assert pack.verify(out, check_runtime=False)["historical_runtime_verified"] is False
    (out / "classification/sms/items.jsonl").write_text("changed")
    with pytest.raises(ValueError, match="input changed"):
        pack.verify(out, check_runtime=False)


def test_ai_runner_is_diagnostic_and_bound_to_protocol(prepared, monkeypatch, tmp_path):
    import evaluation.messages.objective as objective_run
    out, _ = prepared
    monkeypatch.setattr(objective_run, "Settings", lambda: SimpleNamespace(llm_model="offline-fixture", endpoint="https://example.org/v1/chat/completions"))
    args = objective_run.configure(out, "sms", "dev", "ai", out=tmp_path / "run")
    assert args.diagnostic is True and args.live is False
    assert args.max_new_calls == 4 * len(read_jsonl(args.dataset))
    assert args.evaluation_protocol["gold_unknown_count"] > 0
    assert args.evaluation_protocol["reference"] == "ai"
    assert args.prompt_profile == "message-v3" and args.max_tokens == 8192
    assert not (tmp_path / "run").exists()
    with pytest.raises(ValueError, match="actual"):
        objective_run.configure(out, "sms", "test", "human", out=tmp_path / "run")
    protocol = json.loads((out / "protocol.json").read_text())
    artifact = protocol["frozen_artifacts"]["url_model"]["path"]
    Path(artifact).write_text("changed fixture model")
    with pytest.raises(ValueError, match="artifact changed"):
        objective_run.configure(out, "sms", "dev", "ai", out=tmp_path / "run")
