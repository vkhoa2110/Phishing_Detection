import csv
import json

from evaluation.messages.conversation import CASES, prepare, prepare_paired


def test_conversation_pack_is_balanced_blinded_and_offline(tmp_path):
    out = tmp_path / "pack"
    protocol = prepare(out)
    assert protocol["provider_calls"] == 0
    assert protocol["risk_distribution"] == {"HIGH": 3, "LOW": 3}
    requests = [json.loads(line) for line in (out / "requests.jsonl").read_text().splitlines()]
    private = [json.loads(line) for line in (out / "private_design_map.jsonl").read_text().splitlines()]
    review = list(csv.DictReader((out / "blind_review.csv").open()))
    assert len(requests) == len(private) == len(review) == len(CASES)
    assert all("risk" not in row and "stage" not in row for row in requests)
    assert all(not row["reviewer_id"] for row in review)
    assert all("conversation_turns" in json.loads(row["payload"]["messages"][1]["content"]) for row in requests)


def test_paired_prefix_pack_never_exposes_future_turns_or_copies_final_labels(tmp_path):
    out = tmp_path / "paired"
    protocol = prepare_paired(out, model="fixture-model")
    rows = [json.loads(line) for line in (out / "requests.jsonl").read_text().splitlines()]
    private = [json.loads(line) for line in (out / "private_design_map.jsonl").read_text().splitlines()]
    assert protocol["requests"] == 72 and protocol["provider_calls"] == 0
    by_case = {case["id"]: case for case in CASES}
    for row, design in zip(rows, private):
        lines = by_case[design["case_id"]]["text"].splitlines()
        prefix = design["prefix"]
        expected = "\n".join(lines[:prefix]) if design["history"] == "full_history" else lines[prefix - 1]
        assert row["text"] == expected
        assert row["payload"]["model"] == "fixture-model"
        assert expected in json.loads(row["payload"]["messages"][1]["content"]).values()
        assert design["risk_reference"] is None
        assert "risk" not in row and "reference" not in row
    review = list(csv.DictReader((out / "input_review.csv").open()))
    assert len(review) == protocol["unique_inputs"]
    assert all(not item["risk_reference"] and not item["reviewer_id"] for item in review)
