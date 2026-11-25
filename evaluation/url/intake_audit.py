"""Compare extraction contracts and known dev intake offline; not phishing quality."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

from app.core.settings import ROOT
from app.services.url import intake
from app.services.url.domain_reference import reference_manifest

DEFAULT_CASES = ROOT / "data/evaluation/url_intake_boundary_v2.jsonl"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def load_cases(path):
    cases = read_jsonl(path)
    if not cases or len({case["id"] for case in cases}) != len(cases):
        raise ValueError("Nonempty unique extraction contract IDs required.")
    for case in cases:
        if (case.get("synthetic_input") is not True or case.get("phishing_label") is not None
                or case.get("label_scope") != "url_extraction_contract"
                or case.get("mode") not in {"text", "url"} or not isinstance(case.get("text"), str)):
            raise ValueError("Authored extraction contracts only; no phishing labels.")
        for key in ("expected_urls", "expected_unscored", "expected_invalid"):
            if not isinstance(case.get(key), list) or any(not isinstance(v, str) for v in case[key]):
                raise ValueError("Explicit string inventories required.")
        if case.get("expected_error") not in {None, "ValueError"}:
            raise ValueError("Unknown expected contract error.")
    return cases


def load_before(source, expected_sha, protocol):
    source, protocol = Path(source), Path(protocol)
    locks = json.loads(protocol.read_text())["source_before_sha256"]
    if sha(source) != expected_sha or locks["app/services/url/intake.py"] != expected_sha:
        raise ValueError("Before intake source hash changed.")
    # The old intake imports these shared modules. Verify them, rather than
    # accidentally claiming historical replay with modified dependencies.
    for name in ("app/services/url/parsing.py", "app/services/url/authority.py"):
        if sha(ROOT / name) != locks[name]:
            raise ValueError("Before intake shared dependency changed: " + name)
    spec = importlib.util.spec_from_file_location("frozen_intake_for_contract_audit", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def observe(module, text, mode):
    try:
        result = module.inspect_url_intake(text, mode)
        return {"urls": result["urls"], "invalid": result["invalid_urls"],
                "unscored": [row["analysis_url"] for row in result.get("unscored_candidates", [])],
                "unscored_candidates": result.get("unscored_candidates", []), "error": None}
    except ValueError as exc:
        return {"urls": [], "invalid": [], "unscored": [], "unscored_candidates": [],
                "error": "ValueError", "error_message": str(exc)}


def matches(result, case):
    return all(result[key] == case[expected] for key, expected in (
        ("urls", "expected_urls"), ("invalid", "expected_invalid"),
        ("unscored", "expected_unscored"), ("error", "expected_error")))


def known_dev(pack):
    pack = Path(pack)
    manifest = json.loads((pack / "manifest.json").read_text())
    if sha(pack / "sms.jsonl") != manifest["files"]["sms.jsonl"]:
        raise ValueError("Known dev SMS hash changed.")
    rows = read_jsonl(pack / "sms.jsonl")
    if len(rows) != 80 or len({row["id"] for row in rows}) != 80:
        raise ValueError("Exactly eighty unique known dev SMS required; no reserve.")
    return rows


def run(*, before_source, before_sha256, before_protocol, cases_path, dev_pack, out):
    out = Path(out)
    if out.exists():
        raise ValueError("Choose a new output directory; preserve earlier results.")
    cases = load_cases(cases_path)
    before = load_before(before_source, before_sha256, before_protocol)
    dev = known_dev(dev_pack) if dev_pack else []
    rows = []
    for case in cases:
        old, new = (observe(module, case["text"], case["mode"]) for module in (before, intake))
        rows.append({"id": case["id"], "group": case["group"], "before": old, "after": new,
                     "before_matches_current_contract": matches(old, case),
                     "after_matches_current_contract": matches(new, case), "phishing_label": None})
    dev_rows = []
    for case in dev:
        old, new = (observe(module, case["text"], "text") for module in (before, intake))
        dev_rows.append({"id": case["id"], "before": old, "after": new,
                         "changed": old != new, "AI_context_review_is_not_gold": True})
    summary = {"contract_cases": len(rows),
               "before_matches_current_contract": sum(row["before_matches_current_contract"] for row in rows),
               "after_matches_current_contract": sum(row["after_matches_current_contract"] for row in rows),
               "current_failed_ids": [row["id"] for row in rows if not row["after_matches_current_contract"]],
               "known_dev": {"n": len(dev_rows), "changed": sum(row["changed"] for row in dev_rows),
                             "before_URL_cases": sum(bool(row["before"]["urls"]) for row in dev_rows),
                             "after_URL_cases": sum(bool(row["after"]["urls"]) for row in dev_rows),
                             "after_unscored_cases": sum(bool(row["after"]["unscored"]) for row in dev_rows)},
               "old_version": before.VERSION, "new_version": intake.VERSION,
               "reference": reference_manifest(), "live_provider_calls": 0, "model_inference_calls": 0,
               "new_phishing_quality_metrics": None, "new_gold_labels": 0, "reserve_inference": False}
    out.mkdir(parents=True)
    for name, values in (("per_case.jsonl", rows), ("known_dev.jsonl", dev_rows)):
        (out / name).write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in values))
    write_json(out / "summary.json", summary)
    (out / "report.md").write_text(f"""# Kiểm tra trích xuất URL

{len(rows)} ca do trợ lý soạn cho chính sách hiện tại: bản trước khớp {summary['before_matches_current_contract']}, bản mới khớp {summary['after_matches_current_contract']}. Đây là regression phát triển có chủ đích, không phải benchmark độc lập hoặc Accuracy/F1 phishing. Kết quả bản cũ được giữ nguyên, không dùng nhãn phishing để chọn quy tắc.

Đúng {len(dev_rows)} SMS dev đã biết: số mẫu có URL {summary['known_dev']['before_URL_cases']} → {summary['known_dev']['after_URL_cases']}; {summary['known_dev']['after_unscored_cases']} mẫu có chuỗi chưa chấm. `known_dev.jsonl` giữ ID, token và lỗi trước/sau, không chép nội dung SMS. Review ngữ cảnh bằng AI và phiếu người riêng; không đổi nhãn nguồn.

IANA là tín hiệu nhận dạng miền trần, không kiểm DNS/đăng ký/uy tín. Không mở URL, không gọi model/LLM/embedding, không suy luận reserve. Replay cũ chỉ kiểm module intake và hai dependency đã khóa, không tái hiện toàn bộ ứng dụng/môi trường lịch sử.
""")
    inputs = [Path(before_source), Path(before_protocol), Path(cases_path)]
    if dev_pack:
        inputs += [Path(dev_pack) / "manifest.json", Path(dev_pack) / "sms.jsonl"]
    sources = list((ROOT / "app").rglob("*.py"))
    sources += [p for folder in (ROOT / "app/static", ROOT / "app/services/url/resources")
                for p in folder.rglob("*") if p.is_file()]
    sources.append(Path(__file__))
    write_json(out / "manifest.json", {
        "input_sha256": {str(p): sha(p) for p in inputs},
        "source_sha256": {str(p.relative_to(ROOT)): sha(p) for p in sorted(set(sources))},
        "reference": reference_manifest(),
        "artifacts_sha256": {p.name: sha(p) for p in out.iterdir() if p.is_file()},
        "scope": "authored development extraction contracts and exact known dev; not phishing classification"})
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before-source", type=Path, required=True)
    parser.add_argument("--before-sha256", required=True)
    parser.add_argument("--before-protocol", type=Path, required=True)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--dev-pack", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    summary = run(before_source=args.before_source, before_sha256=args.before_sha256,
                  before_protocol=args.before_protocol, cases_path=args.cases, dev_pack=args.dev_pack, out=args.out)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["current_failed_ids"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
