import asyncio
import json

from evaluation import ablation
from test_ablation_v3 import offline_environment


def test_objective_offline_preparation_cannot_publish_fake_zero_f1(monkeypatch, tmp_path):
    args, _, _ = offline_environment(monkeypatch, tmp_path)
    args.evaluation_protocol = {"protocol_sha256": "unit-test-only", "reference": "ai"}
    result = asyncio.run(ablation.evaluate(args))
    assert result["metrics_ready"] is False and result["evaluation_status"] == "prepared"
    assert result["metrics"] is None and result["comparisons"] is None
    saved = json.loads((args.out / "summary.json").read_text())
    assert saved["metrics"] is None
    assert saved["run_state"]["new_api_calls"] == 0
    assert "chưa công bố Precision/Recall/F1" in (args.out / "report.md").read_text()
    assert json.loads((args.out / "manifest.json").read_text())["configuration"]["evaluation_protocol"] == args.evaluation_protocol
