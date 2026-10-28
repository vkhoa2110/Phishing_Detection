"""Plot a completed four-arm comparison, retaining UNKNOWN and failures."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

SYSTEMS = ("llm_only", "llm_url", "llm_rag", "llm_url_rag", "fusion_llm_url_rag")
NAMES = ("LLM", "LLM + URL", "LLM + RAG", "LLM + URL + RAG", "Full app after fusion")
COLORS = ("#0f766e", "#2563eb", "#9333ea", "#c2410c", "#64748b")


def save(fig, path):
    for ext in ("png", "svg"):
        fig.savefig(path.with_suffix("." + ext), dpi=180, bbox_inches="tight")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    s = json.loads((args.out / "summary.json").read_text(encoding="utf-8"))
    if s["run_state"]["stop_reason"] != "all_calls_completed":
        parser.error("Finish all planned attempts first; errors remain UNKNOWN.")
    fig, axes = plt.subplots(1, 4, figsize=(15, 5), layout="constrained")
    for ax, key, title in zip(axes, ("precision", "recall", "f1", "false_positive_rate"),
                              ("Precision", "Recall", "F1", "False alarms (lower is better)")):
        values = [s["metrics"][a][key] for a in SYSTEMS]
        y = np.arange(len(SYSTEMS))
        bars = ax.barh(y, [100 * v if v is not None else 0 for v in values], color=COLORS)
        ax.bar_label(bars, labels=[f"{100*v:.1f}%" if v is not None else "N/A" for v in values], padding=3, fontsize=9)
        ax.set_yticks(y, NAMES if ax is axes[0] else [""] * len(y))
        ax.invert_yaxis()
        ax.set_xlim(0, 115)
        ax.set_xticks([0, 25, 50, 75, 100])
        ax.set_title(title, fontsize=11)
        ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle(f"{s['n']} synthetic Vietnamese messages | 50 scam / 50 normal\nOne run per arm; UNKNOWN retained. Not a real-world benchmark.")
    save(fig, args.out / "metrics")
    fig, axes = plt.subplots(2, 2, figsize=(13, 9), layout="constrained")
    for row, (group, group_name) in enumerate((("with_url", "60 messages with URLs"), ("without_url", "40 messages without URLs"))):
        for col, (key, metric_name) in enumerate((("f1", "F1"), ("false_positive_rate", "False alarms"))):
            ax = axes[row, col]
            vals = [s["by_url"][group][a][key] for a in SYSTEMS]
            bars = ax.bar(np.arange(5), [100*v if v is not None else 0 for v in vals], color=COLORS)
            ax.bar_label(bars, labels=[f"{100*v:.1f}%" if v is not None else "N/A" for v in vals], padding=3)
            ax.set_xticks(np.arange(5), NAMES, rotation=15, ha="right", fontsize=8)
            ax.set_ylim(0, 115)
            ax.set_title(f"{group_name} — {metric_name}")
            ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle("Stratified diagnostic comparison | synthetic labels, unverified by independent annotators")
    save(fig, args.out / "strata")
    fig, axes = plt.subplots(1, 5, figsize=(15, 3.8), layout="constrained")
    for ax, arm, name in zip(axes, SYSTEMS, NAMES):
        m = s["metrics"][arm]
        matrix = np.array([[m["tn"], m["fp"], m["unknown_negative"]], [m["fn"], m["tp"], m["unknown_positive"]]])
        ax.imshow(matrix, vmin=0, vmax=50, cmap="Blues")
        for (i, j), n in np.ndenumerate(matrix):
            ax.text(j, i, str(n), ha="center", va="center", color="white" if n > 25 else "#172554", fontsize=13)
        ax.set_xticks([0, 1, 2], ["Normal", "Alarm", "Unknown"], rotation=30, fontsize=9)
        ax.set_yticks([0, 1], ["Normal", "Scam"], fontsize=9)
        ax.set_xlabel("Prediction")
        ax.set_title(name, fontsize=10)
    fig.suptitle("Confusion matrices | 100 synthetic messages")
    save(fig, args.out / "confusion_matrices")
    print("Saved metrics, strata and confusion matrices (PNG/SVG).")


if __name__ == "__main__":
    main()
