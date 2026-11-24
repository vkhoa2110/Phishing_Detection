"""Offline provenance and freeze gates, using only temporary fictional sources."""
from copy import deepcopy
import csv
import json
from pathlib import Path
import zipfile

import pytest

from evaluation.data import evidence_messages as evidence


@pytest.fixture
def source_factory(tmp_path):
    def make(identity="source-a", *, text="An authority described a fictional account notice.",
             url=None, documented_urls=(), **changes):
        snapshot = tmp_path / (identity + ".txt")
        snapshot.write_text(text, encoding="utf-8")
        source = {
            "id": identity,
            "url": url or "https://fakeauthority.example/articles/" + identity,
            "publisher": "Fictional Authority",
            "title": "Offline fixture " + identity,
            "verified_primary": True,
            "snapshot_path": str(snapshot),
            "snapshot_sha256": evidence.sha(snapshot),
            "evidence_excerpt": text.splitlines()[0],
            "documented_urls": list(documented_urls),
            **changes,
        }
        return source
    return make


def case(identity="case-a", text="A fictional account notice asks for a payment.", **changes):
    urls = evidence.inspect_url_intake(text, "text")["urls"]
    return {
        "id": identity,
        "text": text,
        "text_origin": "reconstructed",
        "reference_status": evidence.REFERENCE_STATUS,
        "human_reviewed": False,
        "label": 1,
        "behavior_label": None,
        "source_ids": ["source-a"],
        "template_family": identity,
        "scenario": "offline fixture",
        "reference_basis": "Assistant design for an offline unit test; no human gold.",
        "campaign_ids": [],
        "urls": urls,
        "url_evidence": [{"url": url, "status": "unverified", "current_safety_verified": False}
                         for url in urls],
        **changes,
    }


def write_inventory(tmp_path, sources, cases):
    sources_path, cases_path = tmp_path / "sources.jsonl", tmp_path / "cases.jsonl"
    evidence.write_jsonl(sources_path, sources)
    evidence.write_jsonl(cases_path, cases)
    return sources_path, cases_path


def group_row(identity, **changes):
    return {"id": identity, "text": "unique" + identity,
            "source_document_keys": [], "domains": [], "campaign_ids": [],
            "template_family": "family-" + identity, **changes}


def test_source_excerpt_hash_primary_and_resolved_relative_snapshot(source_factory, tmp_path):
    source = source_factory(text="An authority described a fictional account notice.\nAdditional context.")
    source["snapshot_path"] = Path(source["snapshot_path"]).name
    validated = evidence.validate_sources([source], base=tmp_path)[source["id"]]
    assert validated["snapshot_path"] == str((tmp_path / source["snapshot_path"]).resolve())
    assert validated["snapshot_sha256"] == evidence.sha(validated["snapshot_path"])
    assert validated["document_keys"] == [source["url"]]


@pytest.mark.parametrize("change", [
    {"evidence_excerpt": "This sentence is absent from the fixture."},
    {"evidence_excerpt": ""},
    {"snapshot_sha256": "0" * 64},
    {"verified_primary": False},
    {"verified_primary": 1},
    {"documented_urls": ["https://invented.example/not-in-source"]},
])
def test_unsupported_source_claims_are_rejected(source_factory, change):
    source = source_factory(**change)
    with pytest.raises(ValueError):
        evidence.validate_sources([source])


def test_source_excerpt_word_limit_is_enforced(source_factory):
    source = source_factory(text=" ".join("word" for _ in range(26)))
    with pytest.raises(ValueError):
        evidence.validate_sources([source])


@pytest.mark.parametrize("suffix", ["/extra", "?redirect=1", "#section"])
def test_documented_full_uri_cannot_be_a_prefix_of_the_artifact_uri(source_factory, suffix):
    claimed = "https://service.example/account"
    source = source_factory(text="An authority described " + claimed + suffix,
                            documented_urls=[claimed])
    with pytest.raises(ValueError):
        evidence.validate_sources([source])


def test_documented_bare_host_can_be_supported_inside_a_full_uri(source_factory):
    source = source_factory(text="An authority described https://service.example/account.",
                            documented_urls=["service.example"])
    assert evidence.validate_sources([source])["source-a"]["documented_urls"] == ["service.example"]


@pytest.mark.parametrize("mentioned", [
    "evilservice.example", "https://evilservice.example/path", "user@service.example",
])
def test_documented_bare_host_cannot_match_another_host_or_an_email(source_factory, mentioned):
    source = source_factory(text="An authority mentioned " + mentioned,
                            documented_urls=["service.example"])
    with pytest.raises(ValueError):
        evidence.validate_sources([source])


@pytest.mark.parametrize("mentioned", [
    "https://unrelated.example/service.example",
    "https://unrelated.example/?next=service.example",
    "unrelated.example/service.example",
    "unrelated.example/?next=service.example",
])
def test_documented_bare_host_inside_another_uris_path_or_query_is_not_attribution(source_factory, mentioned):
    source = source_factory(text="An authority mentioned " + mentioned,
                            documented_urls=["service.example"])
    with pytest.raises(ValueError):
        evidence.validate_sources([source])


def test_documented_standalone_bare_host_remains_supported(source_factory):
    source = source_factory(text="An authority mentioned service.example in its warning.",
                            documented_urls=["service.example"])
    assert evidence.validate_sources([source])["source-a"]["documented_urls"] == ["service.example"]


@pytest.mark.parametrize("punctuation", [".", ",", ")"])
def test_documented_full_uri_can_end_at_prose_punctuation(source_factory, punctuation):
    url = "https://service.example/account"
    source = source_factory(text="An authority described " + url + punctuation,
                            documented_urls=[url])
    assert evidence.validate_sources([source])["source-a"]["documented_urls"] == [url]


@pytest.mark.parametrize("changes", [
    {"text_origin": "observed"},
    {"text_origin": None},
    {"reference_status": "human_gold"},
    {"human_reviewed": True},
    {"human_reviewed": 0},
    {"label": True},
    {"behavior_label": False},
    {"label": 2},
])
def test_origin_human_gold_and_noninteger_binary_references_are_rejected(source_factory, changes):
    sources = evidence.validate_sources([source_factory()])
    with pytest.raises(ValueError):
        evidence.validate_cases([case(**changes)], sources)


def test_observed_quote_must_exist_in_one_artifact_not_across_artifacts(source_factory):
    first = source_factory(text="Please transfer the")
    second = source_factory("source-b", text="requested amount today.")
    sources = evidence.validate_sources([first, second])
    quote = "Please transfer the requested amount today."
    row = case(text=quote, text_origin="observed_exact", source_ids=["source-a", "source-b"],
               source_message_quote=quote)
    with pytest.raises(ValueError):
        evidence.validate_cases([row], sources)


def test_exact_and_placeholder_redacted_specimens_are_reproducible(source_factory):
    quote = "Please call Alice about the fictional account notice."
    sources = evidence.validate_sources([source_factory(text=quote)])
    exact = case(text=quote, text_origin="observed_exact", source_message_quote=quote)
    assert evidence.validate_cases([exact], sources)[0]["text"] == quote
    redacted = case(text=quote.replace("Alice", "[PERSON]"), text_origin="observed_redacted",
                    source_message_quote=quote,
                    substitutions=[{"old": "Alice", "new": "[PERSON]", "kind": "redaction"}])
    assert evidence.validate_cases([redacted], sources)[0]["text"] == redacted["text"]


@pytest.mark.parametrize("origin, substitutions, replacement", [
    ("observed_redacted", [], "Please call Alice about the fictional account notice."),
    ("observed_exact", [{"old": "Alice", "new": "[PERSON]", "kind": "redaction"}],
     "Please call [PERSON] about the fictional account notice."),
    ("observed_redacted", [{"old": "Alice", "new": "Bob", "kind": "redaction"}],
     "Please call Bob about the fictional account notice."),
    ("observed_redacted", [{"old": "Alice", "new": "[PERSON]", "kind": "paraphrase"}],
     "Please call [PERSON] about the fictional account notice."),
    ("observed_redacted", [{"old": "Please call Alice about the fictional account notice.",
                            "new": "[MESSAGE]", "kind": "redaction"}], "[MESSAGE]"),
])
def test_observed_origin_cannot_hide_authored_replacements(source_factory, origin, substitutions, replacement):
    quote = "Please call Alice about the fictional account notice."
    sources = evidence.validate_sources([source_factory(text=quote)])
    row = case(text=replacement, text_origin=origin, source_message_quote=quote,
               substitutions=substitutions)
    with pytest.raises(ValueError):
        evidence.validate_cases([row], sources)


def test_long_prose_redaction_is_rejected_even_with_a_placeholder(source_factory):
    quote = "First second third fourth fifth sixth seventh eighth ninth remaining text."
    old = "First second third fourth fifth sixth seventh eighth ninth"
    sources = evidence.validate_sources([source_factory(text=quote)])
    row = case(text=quote.replace(old, "[PROSE]"), text_origin="observed_redacted",
               source_message_quote=quote,
               substitutions=[{"old": old, "new": "[PROSE]", "kind": "redaction"}])
    with pytest.raises(ValueError):
        evidence.validate_cases([row], sources)


def test_observed_unlogged_text_change_and_unbacked_behavior_quote_are_rejected(source_factory):
    quote = "Please call Alice about the fictional account notice."
    sources = evidence.validate_sources([source_factory(text=quote)])
    for row in [case(text=quote + " Urgent.", text_origin="observed_exact", source_message_quote=quote),
                case(behavior_label=1, behavior_quote="invented action")]:
        with pytest.raises(ValueError):
            evidence.validate_cases([row], sources)


@pytest.mark.parametrize("mutation", [
    lambda row: row.update(urls=[]),
    lambda row: row.update(url_evidence=[]),
    lambda row: row["url_evidence"].append(deepcopy(row["url_evidence"][0])),
    lambda row: row["url_evidence"][0].update(url="https://invented.example"),
    lambda row: row["url_evidence"][0].update(status="currently_safe"),
    lambda row: row["url_evidence"][0].update(current_safety_verified=True),
])
def test_every_input_url_has_exactly_one_scoped_noncurrent_record(source_factory, mutation):
    sources = evidence.validate_sources([source_factory()])
    row = case(text="A fixture mentions https://service.example/account and https://other.example/help")
    mutation(row)
    with pytest.raises(ValueError):
        evidence.validate_cases([row], sources)


@pytest.mark.parametrize("status, scope", [
    ("historical_bad", "historical_scam_url"),
    ("documented_service", "service_workflow"),
])
def test_url_historical_or_service_status_requires_the_linked_literal_source(source_factory, status, scope):
    url = "https://service.example/fixture"
    source = source_factory(text="An authority described " + url, documented_urls=[url], url_scope=scope)
    sources = evidence.validate_sources([source])
    row = case(text="Fixture notice: " + url,
               url_evidence=[{"url": url, "status": status, "source_id": "source-a",
                              "current_safety_verified": False}])
    assert evidence.validate_cases([row], sources)[0]["urls"] == [url]
    for mutation in [lambda r: r["url_evidence"][0].update(source_id="unknown"),
                     lambda r: r["url_evidence"][0].update(status="documented_service" if status == "historical_bad" else "historical_bad")]:
        changed = deepcopy(row)
        mutation(changed)
        with pytest.raises(ValueError):
            evidence.validate_cases([changed], sources)
    source["documented_urls"] = []
    with pytest.raises(ValueError):
        evidence.validate_cases([row], evidence.validate_sources([source]))


def test_historical_defanged_target_requires_exact_logged_source_restoration(source_factory):
    target = "https://historical[.]example/fixture"
    url = "https://historical.example/fixture"
    source = source_factory(text="An authority warned about " + target,
                            documented_urls=[target], url_scope="historical_scam_url")
    sources = evidence.validate_sources([source])
    row = case(text="Offline reconstruction mentions " + url,
               url_evidence=[{"url": url, "status": "historical_defanged_target",
                              "source_id": "source-a", "source_target": target,
                              "current_safety_verified": False}])
    result = evidence.validate_cases([row], sources)[0]
    assert result["url_evidence"][0]["source_target"] == target
    assert result["url_evidence"][0]["current_safety_verified"] is False
    for changes in [
        {"source_target": "https://invented[.]example/fixture"},
        {"source_target": url},
        {"status": "historical_bad"},
    ]:
        altered = deepcopy(row)
        altered["url_evidence"][0].update(changes)
        with pytest.raises(ValueError):
            evidence.validate_cases([altered], sources)
    changed_url = case(text="Offline reconstruction mentions " + url + "/invented",
                       url_evidence=[{**row["url_evidence"][0], "url": url + "/invented"}])
    with pytest.raises(ValueError):
        evidence.validate_cases([changed_url], sources)
    source["url_scope"] = "service_workflow"
    with pytest.raises(ValueError):
        evidence.validate_cases([row], evidence.validate_sources([source]))


def test_grouping_recomputes_all_transitive_leakage_edges_and_overrides_forged_splits():
    near = "amber birch cedar dogwood elm fir ginkgo hawthorn"
    rows = [
        group_row("a", source_document_keys=["https://fakeauthority.example/article"]),
        group_row("b", source_document_keys=["https://fakeauthority.example/article"], campaign_ids=["campaign"]),
        group_row("c", campaign_ids=["campaign"], domains=["shared.example"]),
        group_row("d", domains=["shared.example"], template_family="shared-family"),
        group_row("e", template_family="shared-family", text=near),
        group_row("f", text=near + " ivy"),
        group_row("g", base_id="f"),
    ]
    for index, row in enumerate(rows):
        row.update(group_id="forged-" + row["id"], split="dev" if index % 2 else "test")
    assigned, edges = evidence.assign_splits(rows)
    assert len({row["group_id"] for row in assigned}) == 1
    assert len({row["split"] for row in assigned}) == 1
    assert {edge["reason"] for edge in edges} >= {
        "source_document", "campaign", "domain", "template_family", "near_template", "derivation"}
    assert all(row["group_id"].startswith("evidence-group-") for row in assigned)


def test_source_aliases_join_articles_but_same_publisher_does_not(source_factory):
    first = source_factory(aliases=["http://www.fakeauthority.example/alternate?utm_source=fixture"])
    alias = source_factory("source-b", url="https://fakeauthority.example/alternate")
    other = source_factory("source-c")
    sources = evidence.validate_sources([first, alias, other])
    rows = evidence.validate_cases([
        case("one", "Amber birch cedar.", source_ids=["source-a"]),
        case("two", "Jade kite lemon.", source_ids=["source-b"]),
        case("three", "Nectar orange plum.", source_ids=["source-c"]),
    ], sources)
    groups, _ = evidence.connected_groups(rows)
    assert groups["one"] == groups["two"]
    assert groups["one"] != groups["three"]


def test_canonical_source_normalizes_web_aliases_tracking_and_query_order_only():
    expected = "https://fakeauthority.example/article?a=1&id=42"
    assert evidence.canonical_source("http://www.fakeauthority.example/article/?utm_source=x&id=42&a=1#section") == expected
    assert evidence.canonical_source("https://fakeauthority.example/article?gclid=x&a=1&id=42&fbclid=y") == expected
    assert evidence.canonical_source("https://fakeauthority.example/article?id=43&a=1") != expected


def test_seeded_sixty_forty_component_assignment_is_deterministic_and_pure(tmp_path):
    rows = [group_row(chr(97 + index // 26) + chr(97 + index % 26)) for index in range(80)]
    first, _ = evidence.assign_splits(rows)
    second, _ = evidence.assign_splits(list(reversed(rows)))
    assert {r["id"]: (r["group_id"], r["split"]) for r in first} == {
        r["id"]: (r["group_id"], r["split"]) for r in second}
    for row in first:
        fraction = int(evidence.digest([evidence.SEED, row["group_id"]])[:16], 16) / 2**64
        assert row["split"] == ("dev" if fraction < .6 else "test")
    assert {row["split"] for row in first} == {"dev", "test"}
    assert list(tmp_path.iterdir()) == []


def test_prepare_writes_input_only_payloads_blank_safe_review_and_non_gold_readiness(source_factory, tmp_path):
    sources_path, cases_path = write_inventory(tmp_path, [source_factory()], [
        case("formula", "  =HYPERLINK(\"fixture\")", label=0),
        case("positive", "Fictional notice: https://service.example/account"),
    ])
    out = tmp_path / "frozen"
    manifest = evidence.prepare(sources_path, cases_path, out)
    payloads = evidence.read_jsonl(out / "dev_inputs.jsonl") + evidence.read_jsonl(out / "test_inputs.jsonl")
    assert {row["id"] for row in payloads} == {"formula", "positive"}
    assert all(set(row) == {"id", "text"} for row in payloads)
    assert next(row for row in payloads if row["id"] == "formula")["text"].startswith("  =")
    for side in ("a", "b"):
        with (out / f"annotator_{side}.csv").open(encoding="utf-8-sig", newline="") as stream:
            review = list(csv.DictReader(stream))
        assert next(row for row in review if row["id"] == "formula")["text"].startswith("'  =")
        assert all(row[field] == "" for row in review for field in ("label", "behavior_label", "notes", "reviewer_id"))
    ready = json.loads((out / "readiness.json").read_text())
    assert ready["independent_gold_ready"] is False
    assert ready["reference_status"] == evidence.REFERENCE_STATUS
    assert ready["heldout_model_inference"] is False
    assert ready["classifier_API_calls"] == ready["URL_fetches"] == 0
    assert manifest["old_120_reserve_inference"] is False
    assert manifest["author_exposed_test"] is True
    assert manifest["sources_added_to_RAG"] is False
    assert json.loads((out / "URL_history_overlap.json").read_text())["checked"] is False
    assert evidence.verify(out)["gold"] is False


@pytest.mark.parametrize("identity", ["=FIXTURE()", "+FIXTURE()", "-FIXTURE()", "  @FIXTURE()"])
def test_review_csv_escapes_formula_ids_without_changing_frozen_input_ids(source_factory, tmp_path, identity):
    sources_path, cases_path = write_inventory(tmp_path, [source_factory()], [case(identity)])
    out = tmp_path / "frozen"
    evidence.prepare(sources_path, cases_path, out)
    payloads = evidence.read_jsonl(out / "dev_inputs.jsonl") + evidence.read_jsonl(out / "test_inputs.jsonl")
    assert payloads[0]["id"] == identity
    assert evidence.read_jsonl(out / "cases.jsonl")[0]["id"] == identity
    for side in ("a", "b"):
        with (out / f"annotator_{side}.csv").open(encoding="utf-8-sig", newline="") as stream:
            review = list(csv.DictReader(stream))
        assert review[0]["id"] == "'" + identity


def test_export_order_is_deterministic_label_independent_and_separate_for_reviewers(source_factory, tmp_path):
    sources_path = tmp_path / "sources.jsonl"
    evidence.write_jsonl(sources_path, [source_factory()])
    original = [case("fixture-" + chr(97 + index), "Unique fixture message " + chr(97 + index),
                     label=int(index >= 6)) for index in range(12)]
    relabeled = [{**row, "label": 1 - row["label"]} for row in original]
    exports = []
    for index, rows in enumerate((original, list(reversed(original)), relabeled)):
        cases_path = tmp_path / f"cases-{index}.jsonl"
        evidence.write_jsonl(cases_path, rows)
        out = tmp_path / f"frozen-{index}"
        evidence.prepare(sources_path, cases_path, out)
        order = {"inputs": [row["id"] for row in evidence.read_jsonl(out / "cases.jsonl")]}
        for side in ("a", "b"):
            with (out / f"annotator_{side}.csv").open(encoding="utf-8-sig", newline="") as stream:
                order[side] = [row["id"] for row in csv.DictReader(stream)]
        exports.append(order)
        assert evidence.verify(out)["verified"] is True
    assert exports[0] == exports[1] == exports[2]
    assert exports[0]["a"] != exports[0]["b"]
    assert exports[0]["inputs"] not in (exports[0]["a"], exports[0]["b"])
    labels = {row["id"]: row["label"] for row in original}
    for order in exports[0].values():
        assert set(order) == set(labels)
        values = [labels[identity] for identity in order]
        assert sum(left != right for left, right in zip(values, values[1:])) > 1


@pytest.mark.parametrize("target", ["source_inventory", "case_inventory", "snapshot", "output"])
def test_verify_rejects_source_case_snapshot_and_output_tampering(source_factory, tmp_path, target):
    source = source_factory()
    sources_path, cases_path = write_inventory(tmp_path, [source], [case()])
    out = tmp_path / "frozen"
    evidence.prepare(sources_path, cases_path, out)
    selected = {"source_inventory": sources_path, "case_inventory": cases_path,
                "snapshot": Path(source["snapshot_path"]), "output": out / "test_inputs.jsonl"}[target]
    selected.write_bytes(selected.read_bytes() + b"\n ")
    with pytest.raises(ValueError):
        evidence.verify(out)


def test_verify_rebuilds_provenance_from_originals_even_if_output_hash_is_updated(source_factory, tmp_path):
    sources_path, cases_path = write_inventory(tmp_path, [source_factory()], [case()])
    out = tmp_path / "frozen"
    evidence.prepare(sources_path, cases_path, out)
    frozen_cases = evidence.read_jsonl(out / "cases.jsonl")
    frozen_cases[0]["source_document_keys"] = ["https://invented.example/unsupported-source"]
    evidence.write_jsonl(out / "cases.jsonl", frozen_cases)
    manifest = json.loads((out / "manifest.json").read_text())
    manifest["files_sha256"]["cases.jsonl"] = evidence.sha(out / "cases.jsonl")
    evidence.write_json(out / "manifest.json", manifest)
    with pytest.raises(ValueError):
        evidence.verify(out)


def test_url_history_archive_is_frozen_and_tampering_invalidates_verification(source_factory, tmp_path):
    archive = tmp_path / "url-history.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        for split in ("train", "val", "test"):
            bundle.writestr("data/splits/url_" + split + ".csv",
                            "url\nhttps://service.example/account\n")
    row = case(text="A fictional notice mentions https://service.example/account")
    sources_path, cases_path = write_inventory(tmp_path, [source_factory()], [row])
    out = tmp_path / "frozen"
    manifest = evidence.prepare(sources_path, cases_path, out, archive=archive)
    history = json.loads((out / "URL_history_overlap.json").read_text())
    assert history["checked"] is True
    assert history["case_overlaps"][row["id"]]["normalized_url_splits"] == ["test", "train", "val"]
    assert manifest["input_files_sha256"][str(archive.resolve())] == evidence.sha(archive)
    assert evidence.verify(out)["verified"] is True
    archive.write_bytes(archive.read_bytes() + b"archive changed")
    with pytest.raises(ValueError):
        evidence.verify(out)


def test_explicit_missing_url_history_archive_fails_before_creating_output(source_factory, tmp_path):
    sources_path, cases_path = write_inventory(tmp_path, [source_factory()], [case()])
    out = tmp_path / "frozen"
    with pytest.raises(ValueError):
        evidence.prepare(sources_path, cases_path, out, archive=tmp_path / "missing.zip")
    assert not out.exists()


def test_prepare_preserves_existing_output_before_reading_any_input(tmp_path):
    out = tmp_path / "existing"
    out.mkdir()
    sentinel = out / "review.csv"
    sentinel.write_text("human work", encoding="utf-8")
    with pytest.raises(ValueError, match="fresh output"):
        evidence.prepare(tmp_path / "missing-sources.jsonl", tmp_path / "missing-cases.jsonl", out)
    assert sentinel.read_text() == "human work"
    assert list(out.iterdir()) == [sentinel]


def test_diagnostic_strata_never_imply_independent_gold_or_inference():
    rows = [
        case("positive", "A fictional link https://service.example/account", split="test", group_id="positive"),
        case("negative", "An unrelated informational notice.", label=0, split="test", group_id="negative"),
    ]
    result = evidence.readiness(rows)
    assert result["splits"]["test"]["diagnostic_strata_present"] is True
    assert result["independent_gold_ready"] is False
    assert result["test_status"] == "locked_author_exposed_holdout_not_independent_blind"
    assert result["heldout_model_inference"] is False
    assert result["classifier_API_calls"] == result["URL_fetches"] == 0
