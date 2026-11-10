import pandas as pd

from evaluation.url_representation_audit_v3 import (
    group_collisions, host_case_variant, path_case_variant, percent_hex_case_variant,
)


def test_collision_audit_reports_label_and_source_conflicts():
    frame = pd.DataFrame([
        {"id": "a", "view": "same", "labels": 0, "source": "A", "tier": "gold"},
        {"id": "b", "view": "same", "labels": 1, "source": "B", "tier": "bronze"},
        {"id": "c", "view": "other", "labels": 0, "source": "A", "tier": "gold"},
    ])
    result = group_collisions(frame, "view")
    assert result["groups"] == 1 and result["rows"] == 2
    assert result["label_conflict_groups"] == result["source_conflict_groups"] == 1


def test_only_documented_syntax_components_are_transformed():
    assert host_case_variant("https://Example.COM/Case") == "https://EXAMPLE.COM/Case"
    assert path_case_variant("https://Example.COM/Case?q=Keep") == "https://Example.COM/cASE?q=Keep"
    assert percent_hex_case_variant("https://example.com/%2fA") == "https://example.com/%2FA"
