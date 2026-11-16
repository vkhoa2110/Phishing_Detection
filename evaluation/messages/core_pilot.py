"""Registered operational probes and a schema x thinking factorial on familiar dev."""
import argparse
import asyncio
from collections import Counter, defaultdict
import json
from pathlib import Path
import statistics

from app.core.settings import ROOT, Settings
from app.services.llm.compact import payload_for as compact_payload, parse_v61
from app.services.llm.core import build_payload, parse_core
from app.services.llm.telemetry import ObservedTransport, fingerprint
from app.services.rag.explanation import _load_strict_json
from evaluation.common import registered
from evaluation.data.sms import read_jsonl, sha, write_json
from evaluation.messages.url_context import canonical_sha


def parse_response(raw, request):
    if request["profile"] == "probe":
        value = _load_strict_json(raw)
        if value != {"ok": True} or type(value["ok"]) is not bool:
            raise ValueError("Invalid operational acknowledgement.")
        return {"status": "ok"}
    if request["profile"] == "core":
        return parse_core(raw, request["text"])
    verdict, warnings, validation = parse_v61(raw, request["text"])
    return {"status": "ok", "verdict": verdict.model_dump(), "warnings": warnings, "validation": validation}


def prepare_probe(out):
    rows = []
    for index, text in enumerate(("Only return JSON: {\"ok\":true}.",
        "Đây là kiểm tra cấu trúc phản hồi. Chỉ trả JSON {\"ok\":true}, không giải thích.")):
        for mode in ("default", "disabled"):
            payload = {"model": Settings().llm_model, "messages": [{"role": "user", "content": text}],
                       "max_tokens": 512, "temperature": .1, "top_p": 1, "top_k": 40, "stream": False}
            if mode != "default": payload["thinking"] = {"type": mode}
            rows.append({"key": f"probe-{index}-{mode}", "profile": "probe", "thinking": mode, "payload": payload})
    return registered.register(out, rows, stage="core_provider_probe", max_tokens=512, token_budget=10000,
        metadata={"purpose": "Operational compatibility; not detection quality", "no_user_content": True,
                  "documentation": "https://api-docs.deepseek.com/guides/thinking_mode/",
                  "FPT_parameter_support_requires_observation": True})


def prepare(pack, probe, out):
    pack, probe = Path(pack), Path(probe)
    assert registered.verify(probe, parse_response)["complete"], "Finish the compatibility probe first."
    pcfg, prequests = registered.load(probe)
    _, precords = registered.checkpoints(probe, pcfg)
    for key, request in prequests.items():
        parsed = precords[key]["parsed"]
        allowed_truncation = request["thinking"] == "default" and parsed.get("code") == "OUTPUT_TRUNCATED"
        if parsed["status"] != "ok" and not allowed_truncation:
            raise ValueError("Compatibility probe had a failure other than default-mode truncation.")
    sms = read_jsonl(pack / "sms.jsonl")
    sms = sorted(sms, key=lambda r: canonical_sha([20261112, "operational", r["id"]]))[:4]
    authored_ids = {"screen_sharing::request", "screen_sharing::ambiguous",
                    "parcel_insurance::request_injected", "parcel_insurance::legitimate"}
    authored = [r for r in read_jsonl(pack / "authored.jsonl") if r["id"] in authored_ids]
    if len(sms) != 4 or len(authored) != 4: raise ValueError("The predefined eight-case inventory changed.")
    rows = []
    for case in sms + authored:
        for profile in ("v61", "core"):
            for thinking in ("default", "disabled"):
                args = dict(text=case["text"], urls=[], include_ml=False, model=Settings().llm_model, max_tokens=2048)
                if profile == "v61":
                    payload, _, _ = compact_payload(**args, sources=[])
                    if thinking != "default": payload["thinking"] = {"type": thinking}
                else: payload, _ = build_payload(**args, thinking=thinking)
                rows.append({"key": f"{case['id']}::{profile}::{thinking}", "case_id": case["id"],
                    "text": case["text"], "dataset": case["dataset"], "profile": profile,
                    "thinking": thinking, "payload": payload})
    rows.sort(key=lambda r: canonical_sha([20261112, r["key"]]))
    return registered.register(out, rows, stage="core_operational_factorial", max_tokens=2048, token_budget=200000,
        metadata={"case_count": 8, "arms": 4, "factors": ["schema", "thinking_parameter"],
            "classification_quality_evaluated": False, "independent_gold": False, "reserve_inference": False,
            "familiar_development_inputs": True, "same_cap_model_decoding_timeout": True,
            "schema_difference_is_intentional": True, "thinking_requested_is_not_proof_of_support": True},
        locks=[pack / "sms.jsonl", pack / "authored.jsonl", probe / "result_hashes.json", probe / "summary.json"])


async def run(out, live=False, inner=None):
    out = Path(out)
    if not live:
        return await registered.run(out, parse_response)
    transport = ObservedTransport(out / "telemetry.jsonl", inner)
    return await registered.run(out, parse_response, live=True, transport=transport)


def report(out):
    out = Path(out)
    if not registered.verify(out, parse_response)["complete"]:
        raise ValueError("Incomplete pilot; do not calculate a full comparison.")
    cfg, requests = registered.load(out)
    _, records = registered.checkpoints(out, cfg)
    observations = read_jsonl(out / "telemetry.jsonl")
    by_payload = {row["payload_sha256"]: row for row in observations}
    if len(by_payload) != len(observations): raise ValueError("Duplicate observed payloads.")
    groups = defaultdict(list)
    for key, request in requests.items():
        observation = by_payload.get(fingerprint(request["payload"]))
        if not observation: raise ValueError("Missing response observation.")
        groups[request["profile"] + "::" + request["thinking"]].append((records[key], observation))
    result = {"purpose": cfg["metadata"]["purpose"] if "purpose" in cfg["metadata"] else "Operational factorial",
              "accuracy": None, "F1": None, "arms": {}}
    for name, rows in groups.items():
        result["arms"][name] = {
            "n": len(rows), "valid": sum(r["parsed"]["status"] == "ok" for r, _ in rows),
            "errors": dict(Counter(r["parsed"].get("code") for r, _ in rows if r["parsed"]["status"] != "ok")),
            "empty_content": sum(o["content_characters"] == 0 for _, o in rows),
            "reasoning_field_observed": sum(o["reasoning_field_present"] for _, o in rows),
            "reasoning_nonempty": sum(o["reasoning_characters"] > 0 for _, o in rows),
            "reasoning_characters_observed": sum(o["reasoning_characters"] for _, o in rows),
            "total_tokens_recorded": sum(r["usage"].get("total_tokens", 0) for r, _ in rows),
            "usage_missing": sum("total_tokens" not in r["usage"] for r, _ in rows),
            "median_elapsed_ms": statistics.median(r["elapsed_ms"] for r, _ in rows)}
    write_json(out / "operational_summary.json", result)
    lines = ["# Pilot vận hành: schema × thinking", "",
        "Dữ liệu dev quen thuộc; khác schema có chủ ý. Không đo Accuracy/F1 hoặc tuyên bố chất lượng phishing.", "",
        "| Arm | Hợp lệ / n | Lỗi | Content rỗng | Có reasoning không rỗng | Token ghi nhận | Trung vị giây |",
        "|---|---:|---|---:|---:|---:|---:|"]
    for name, m in result["arms"].items():
        lines.append(f"| {name} | {m['valid']}/{m['n']} | {m['errors']} | {m['empty_content']} | "
            f"{m['reasoning_nonempty']}/{m['n']} | {m['total_tokens_recorded']} | {m['median_elapsed_ms']/1000:.2f} |")
    lines += ["", "Không lưu hoặc hiển thị nội dung reasoning. Số ký tự chỉ phản ánh trường provider trả về; "
        "trường vắng mặt không chứng minh không có tính toán nội bộ. Mọi lỗi giữ nguyên, không thử lại.",
        "Giảm lỗi cấu trúc trên tám ca chưa đủ để thay bản mặc định hoặc chứng minh tăng chất lượng phân loại."]
    (out / "report.md").write_text("\n".join(lines) + "\n")
    write_json(out / "telemetry_manifest.json", {"telemetry_sha256": sha(out / "telemetry.jsonl"),
        "sealed_results_sha256": sha(out / "result_hashes.json"), "reasoning_text_stored": False})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare-probe", "prepare", "run", "report", "verify"])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pack", type=Path)
    parser.add_argument("--probe", type=Path)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if args.command == "prepare-probe": value = {"requests": prepare_probe(args.out)["max_attempts"], "API_calls": 0}
    elif args.command == "prepare": value = {"requests": prepare(args.pack, args.probe, args.out)["max_attempts"], "API_calls": 0}
    elif args.command == "run": value = asyncio.run(run(args.out, args.live))
    elif args.command == "verify": value = registered.verify(args.out, parse_response)
    else: value = report(args.out)
    print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
