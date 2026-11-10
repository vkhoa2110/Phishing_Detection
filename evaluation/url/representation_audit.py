"""Audit information lost between raw URLs and the deployed character view.

No model is fitted and the official test split is never opened.  This is a
development-data audit of representation collisions and selected invariances.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import numpy as np

from app.services.url.character import CharURLService
from evaluation.url.calibration import sha, write_json
from evaluation.url.representation import ARCHIVE, load_frames


from app.core.settings import ROOT
def lower_model_view(value: str) -> str:
    return value.lower()


def group_collisions(frame, field: str) -> dict:
    groups = defaultdict(list)
    for row in frame.to_dict("records"):
        groups[row[field]].append(row)
    collided = [rows for rows in groups.values() if len(rows) > 1]
    return {
        "groups": len(collided),
        "rows": sum(len(rows) for rows in collided),
        "label_conflict_groups": sum(len({row["labels"] for row in rows}) > 1 for rows in collided),
        "source_conflict_groups": sum(len({row["source"] for row in rows}) > 1 for rows in collided),
        "tier_conflict_groups": sum(len({row["tier"] for row in rows}) > 1 for rows in collided),
        "examples": [{"ids": [row["id"] for row in rows[:8]],
                      "labels": sorted({int(row["labels"]) for row in rows}),
                      "sources": sorted({row["source"] for row in rows})}
                     for rows in collided[:20]],
    }


def host_case_variant(url: str) -> str:
    raw = url if "://" in url else "https://" + url
    parts = urlsplit(raw)
    host = (parts.hostname or "").swapcase()
    port = f":{parts.port}" if parts.port is not None else ""
    variant = urlunsplit((parts.scheme, host + port, parts.path, parts.query, parts.fragment))
    return variant.removeprefix("https://") if "://" not in url else variant


def percent_hex_case_variant(url: str) -> str:
    result, index = [], 0
    while index < len(url):
        if index + 2 < len(url) and url[index] == "%" and all(c in "0123456789abcdefABCDEF" for c in url[index + 1:index + 3]):
            result.append("%" + url[index + 1:index + 3].swapcase())
            index += 3
        else:
            result.append(url[index])
            index += 1
    return "".join(result)


def path_case_variant(url: str) -> str:
    """Swap only path letter case, which can change an HTTP resource."""
    raw = url if "://" in url else "https://" + url
    parts = urlsplit(raw)
    variant = urlunsplit((parts.scheme, parts.netloc, parts.path.swapcase(),
                          parts.query, parts.fragment))
    return variant.removeprefix("https://") if "://" not in url else variant


def invariance(service, urls: list[str]) -> dict:
    output = {}
    transforms = (("host_case", host_case_variant),
                  ("path_case", path_case_variant),
                  ("percent_hex_case", percent_hex_case_variant))
    for name, transform in transforms:
        # Target examples that actually exercise the transformation; otherwise
        # a mostly bare-domain prefix can make the audit vacuous.
        eligible = [url for url in urls if transform(url) != url][:500]
        if not eligible:
            output[name] = {
                "n": 0, "text_changed": 0, "score_changed": 0,
                "max_abs_delta": None, "mean_abs_delta": None,
                "expected_relation": "no eligible URL in historical validation",
            }
            continue
        original_scores = service._scores(eligible)
        variants = [transform(url) for url in eligible]
        changed = np.array([a != b for a, b in zip(eligible, variants)])
        variant_scores = service._scores(variants)
        delta = np.abs(original_scores - variant_scores)
        output[name] = {
            "n": len(eligible), "text_changed": int(changed.sum()),
            "score_changed": int((delta > 1e-12).sum()),
            "max_abs_delta": float(delta.max(initial=0)),
            "mean_abs_delta": float(delta.mean()),
            "expected_relation": (
                "potentially different HTTP resource; invariance exposes information loss"
                if name == "path_case" else
                "same URI component meaning under RFC3986 syntax normalization; does not prove same live content"
            ),
        }
    return output


def run(out: Path) -> dict:
    if out.exists():
        raise ValueError("Choose a new output directory; audits are immutable.")
    service = CharURLService()
    if not service.load()["ready"]:
        raise ValueError(service.error)
    frames, checks = load_frames(preprocessing=service.preprocessing)
    out.mkdir(parents=True)
    results = {}
    for split, frame in frames.items():
        work = frame.copy()
        work["lower_model_input"] = work.model_input.map(lower_model_view)
        raw_duplicate = group_collisions(work.assign(raw_key=work.url), "raw_key")
        formatted = group_collisions(work, "model_input")
        lower = group_collisions(work, "lower_model_input")
        results[split] = {
            "rows": len(work), "raw_exact": raw_duplicate,
            "formatted_before_vectorizer_lowercase": formatted,
            "lowercased_model_view": lower,
            "additional_groups_from_lowercase": lower["groups"] - formatted["groups"],
            "additional_rows_from_lowercase": lower["rows"] - formatted["rows"],
        }
    sample = frames["val"].url.tolist()
    summary = {
        "schema": "url-representation-audit-v3-1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scope": "official train and historical validation only; no test opened, no fit, no threshold selection",
        "data_checks": checks,
        "splits": results,
        "metamorphic_probe": invariance(service, sample),
        "conclusion_limit": "A collision is loss of distinction in this model view; it is not automatically a label error or proof of identical server behavior.",
        "input_hashes": {str(path.resolve()): sha(path) for path in [Path(__file__), ARCHIVE,
            ROOT / "app/services/url/character.py", ROOT / "models/inference_XGBoost_d6_s42/url_preprocessing.py"]},
    }
    write_json(out / "summary.json", summary)
    lines = ["# URL representation audit v3", "", summary["scope"], "",
             "| Split | Rows | Lowercase collision groups | Rows in groups | Label-conflict groups | Additional groups vs formatted view |",
             "|---|---:|---:|---:|---:|---:|"]
    for split, value in results.items():
        lower = value["lowercased_model_view"]
        lines.append(f"| {split} | {value['rows']} | {lower['groups']} | {lower['rows']} | {lower['label_conflict_groups']} | {value['additional_groups_from_lowercase']} |")
    lines += ["", "Each metamorphic probe uses up to 500 eligible historical validation URLs and does not create new labels.", "",
              "| Transformation | Text changed | Score changed | Maximum absolute score change |",
              "|---|---:|---:|---:|"]
    for name, value in summary["metamorphic_probe"].items():
        delta = "N/A" if value["max_abs_delta"] is None else f"{value['max_abs_delta']:.12g}"
        lines.append(f"| {name} | {value['text_changed']}/{value['n']} | {value['score_changed']}/{value['n']} | {delta} |")
    lines += ["", summary["conclusion_limit"], ""]
    (out / "report.md").write_text("\n".join(lines))
    return summary


def verify(out: Path) -> dict:
    stored = json.loads((out / "summary.json").read_text())
    for path, expected in stored["input_hashes"].items():
        if sha(path) != expected:
            raise ValueError("Audit input changed: " + path)
    return {"verified": True, "fit_count": 0, "test_opened": False, "API_calls": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["run", "verify"])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.out) if args.command == "run" else verify(args.out), ensure_ascii=False, indent=2))
