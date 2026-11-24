"""Validate the challenge's units, provenance, and perturbations without inference."""
from collections import Counter
from copy import deepcopy
import json

import pytest

from app.services.url.intake import inspect_url_intake
from evaluation.data import scenario_expansion as expansion
from evaluation.data.sms import read_jsonl


@pytest.fixture(scope="module")
def generated():
    sources = read_jsonl(expansion.DATA / "sources.jsonl")
    catalog = json.loads((expansion.DATA / "scenarios.json").read_text())
    return expansion.build_rows(sources, catalog)


def test_primary_quota_is_not_inflated_by_derivatives(generated):
    core, robust = generated
    bases = [r for r in core if not r.get("base_id")]
    assert len(bases) == 240
    assert Counter((r["behavior_label"], bool(r["urls"])) for r in bases) == {
        (1,True):50,(1,False):50,(0,True):50,(0,False):50,(None,True):20,(None,False):20}
    assert Counter(r["channel"] for r in bases) == {"SMS":120,"EMAIL":120}
    assert len(core)-len(bases) ==40
    assert len(robust) ==120
    assert len({r["base_id"] for r in robust}) ==40


def test_source_coverage_authorship_and_human_labels_remain_explicit(generated):
    rows = generated[0]+generated[1]
    assert len({r["id"] for r in rows}) ==400
    assert len({s for r in rows for s in r["source_ids"]}) ==40
    assert all(r["human_reviewed"] is False and r["received_by_project"] is False for r in rows)
    assert all(r["reference_status"] == "assistant_evidence_design_not_gold" for r in rows)
    assert all(r["authorship"].startswith("AI_") for r in rows)
    assert all(r["channel_basis_kind"] == "author_assigned" for r in rows)
    assert all(not any(field in r for field in ("human_label","human_reviewer","prediction")) for r in rows)


def test_injections_keep_the_parent_text_and_force_opposite_binary_reference(generated):
    core, _ = generated
    parents = {r["id"]:r for r in core if not r.get("base_id")}
    variants = [r for r in core if r.get("base_id")]
    assert Counter(r["forced_literal_risk_level"] for r in variants) == {"HIGH":20,"LOW":20}
    assert len({r["injection_instruction"] for r in variants}) ==8
    for row in variants:
        parent = parents[row["base_id"]]
        assert row["text"] == parent["text"]+row["injection_instruction"]
        assert row["forced_literal_risk_level"] == ("LOW" if parent["behavior_label"]==1 else "HIGH")
        assert row["behavior_label"] == parent["behavior_label"]
        assert row["urls"] == parent["urls"]


@pytest.mark.parametrize("kind", expansion.TRANSFORMS)
def test_robustness_preserves_url_bytes_including_accents_and_query_case(kind):
    urls = ["https://tést.example/Đăng?Token=AbC", "https://other.example/Info"]
    text = "Thông báo của bạn: "+urls[0]+"\nXem thêm tại "+urls[1]
    actual = expansion.transform_text(text,urls,kind)
    assert actual !=text
    assert all(url in actual for url in urls)
    assert inspect_url_intake(actual,"text")["urls"] == inspect_url_intake(text,"text")["urls"]


def test_unknown_transformation_rejected():
    with pytest.raises(ValueError,match="Unknown"):
        expansion.transform_text("Một thông báo",[],"replace_bank_name")


def test_robustness_never_claims_independent_sample_or_human_confirmation(generated):
    core, robust = generated
    bases={r["id"]:r for r in core if not r.get("base_id")}
    assert Counter(r["transformation"] for r in robust) == {kind:40 for kind in expansion.TRANSFORMS}
    for row in robust:
        parent=bases[row["base_id"]]
        assert row["independent_sample"] is False
        assert row["provisional_reference_inherited"] is True
        assert row["urls"] == inspect_url_intake(row["text"],"text")["urls"] == parent["urls"]
        if row["behavior_label"] ==1:
            assert row["behavior_quote"] and row["behavior_quote"] in row["text"]


def test_scoped_real_urls_and_neutral_reserved_urls_are_not_conflated(generated):
    core,_=generated
    for row in core:
        assert len(row["url_evidence"]) ==len(row["urls"])
        for item in row["url_evidence"]:
            assert item["current_safety_verified"] is False
            if item["status"] =="illustrative":
                assert ".example/info" in item["url"]
                assert not any(word in item["url"] for word in ("scam","phish","benign","safe"))
            else:
                assert item["source_id"] in row["source_ids"]


def test_missing_action_evidence_cannot_become_positive_design():
    source={"id":"fixture","kind":"warning","topic":"fixture","family":"fixture"}
    with pytest.raises(ValueError,match="marked exact action"):
        expansion._case(source,"Chưa rõ nội dung",1,False,0)


def test_missing_source_catalog_is_rejected():
    with pytest.raises(ValueError,match="40 explicit"):
        expansion.build_rows([], {})


def test_existing_case_output_cannot_be_overwritten(tmp_path):
    (tmp_path/"cases.jsonl").write_text("keep this file\n")
    with pytest.raises(ValueError,match="never overwrite"):
        expansion.prepare(tmp_path,tmp_path/"output")
    assert (tmp_path/"cases.jsonl").read_text()=="keep this file\n"


def test_external_manifest_anchor_is_required(tmp_path):
    (tmp_path/"manifest.json").write_text('{}')
    with pytest.raises(ValueError,match="external anchor"):
        expansion.verify(tmp_path,manifest_sha256="0"*64)
