import json

from evaluation.messages.core_quality import requests_for


def test_no_information_controls_share_payload_and_url_scores_are_the_only_arm_change():
    cases = [{"id": "plain", "text": "Thông báo họp."}, {"id": "url", "text": "Xem https://example.org"}]
    prepared = {
        "plain": {"url_results": [], "url_train_domain_overlap": False},
        "url": {"url_results": [{"id": "URL-01", "url": "https://example.org", "status": "ok", "score": .2,
            "risk_level": "LOW", "warning_threshold": .5, "high_threshold": .9}], "url_train_domain_overlap": False}}
    requests, cells = requests_for(cases, prepared, "fixture")
    assert len(requests) == 5 and len(cells) == 6
    bindings = {(r["id"], r["arm"]): r["request_key"] for r in cells}
    assert bindings[("plain", "core_no_URL")] == bindings[("plain", "core_with_URL")]
    assert bindings[("url", "core_no_URL")] != bindings[("url", "core_with_URL")]
    for row in requests:
        assert row["payload"]["thinking"] == {"type": "disabled"}
        assert row["payload"]["max_tokens"] == 2048
        data = json.loads(row["payload"]["messages"][1]["content"])
        assert "label" not in data and "reference_documents" not in data
