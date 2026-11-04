"""Run a frozen evaluation protocol. Default: offline; AI references: diagnostic.

No option silently converts AI references to reviewed human gold or changes
the registered model, arms, budget, prompt profile or worker count.
"""
import argparse
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from app.settings import ROOT, Settings
from .ablation import evaluate
from .benchmark_pack import verify
from .message_data import read_jsonl, sha
from .review import validate_gold


def configure(pack, dataset, split, reference, reviewed_manifest=None, out=None, live=False):
    pack = Path(pack)
    verify(pack)
    protocol = json.loads((pack / "protocol.json").read_text(encoding="utf-8"))
    if dataset not in {"sms", "challenge"} or split not in {"dev", "test"} or reference not in {"ai", "human"}:
        raise ValueError("Unknown dataset/split/reference type.")
    if reference == "human":
        if reviewed_manifest is None:
            raise ValueError("Human benchmark needs an actual --reviewed-manifest.")
        reviewed_manifest = Path(reviewed_manifest)
        path = reviewed_manifest.parent / f"{split}.jsonl"
        validate_gold(reviewed_manifest, path)
        all_gold = read_jsonl(path) + read_jsonl(reviewed_manifest.parent / f"{split}_unknown.jsonl")
    else:
        if reviewed_manifest is not None:
            raise ValueError("AI references cannot be passed as human reviewed gold.")
        path = pack / "provisional_reference" / dataset / f"{split}.jsonl"
        all_gold = read_jsonl(path) + read_jsonl(path.with_name(f"{split}_unknown.jsonl"))
    expected = [i for i in read_jsonl(pack / "classification" / dataset / "items.jsonl") if i["split"] == split]
    if {i["id"]: i["text"] for i in all_gold} != {i["id"]: i["text"] for i in expected} or len(all_gold) != len(expected):
        raise ValueError("Reference does not cover the exact frozen inputs, including UNKNOWN.")
    settings = Settings()
    if settings.llm_model != protocol["model"] or settings.endpoint != protocol["endpoint"]:
        raise ValueError("Configured LLM differs from the frozen protocol; create a new protocol version.")
    return SimpleNamespace(dataset=path, out=out, live=live,
        reviewed_manifest=reviewed_manifest, diagnostic=reference == "ai", prompt_profile=protocol["prompt_profile"],
        fusion_policy=protocol["fusion_policy"], max_tokens=protocol["max_tokens"], timeout=protocol["timeout_seconds"],
        seed=protocol["seed"], workers=protocol["workers"], max_new_calls=4 * len(read_jsonl(path)),
        evaluation_protocol={"protocol_sha256": sha(pack / "protocol.json"), "pack_manifest_sha256": sha(pack / "manifest.json"),
                             "dataset": dataset, "split": split, "reference": reference,
                             "gold_unknown_count": sum(i["label"] is None for i in all_gold),
                             "unknown_cases_evaluated_here": False})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, default=ROOT / "data/annotation/objective_v1")
    parser.add_argument("--dataset", choices=("sms", "challenge"), required=True)
    parser.add_argument("--split", choices=("dev", "test"), default="dev")
    parser.add_argument("--reference", choices=("ai", "human"), required=True)
    parser.add_argument("--reviewed-manifest", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--live", action="store_true", help="Explicitly enable paid provider calls; omitted means offline preparation only.")
    args = parser.parse_args()
    try:
        config = configure(args.pack, args.dataset, args.split, args.reference, args.reviewed_manifest, args.out, args.live)
        result = asyncio.run(evaluate(config))
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(2, f"Objective evaluation stopped: {exc}\n")
    print(json.dumps({"out": str(args.out), "reference": args.reference, "diagnostic": config.diagnostic,
                      "cases": result["n"], "run_state": result["run_state"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
