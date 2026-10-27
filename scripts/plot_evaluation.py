"""Export metric and confusion-matrix figures from an evaluation summary."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    summary = json.loads((args.run / "summary.json").read_text(encoding="utf-8"))
    manifest = json.loads((args.run / "manifest.json").read_text(encoding="utf-8"))
    is_phishvn = "data.mendeley.com" in manifest["configuration"].get("dataset", "")
    dataset_title = f"{summary['n']} PhishVN test URLs (balanced subset)" if is_phishvn else f"{summary['n']} synthetic Vietnamese messages"
    if any(sum(counts.values()) != summary["n"] or counts.get("pending", 0)
           for counts in summary["status_counts"].values()):
        parser.error("Every planned LLM call must finish before plotting; API failures are kept as UNKNOWN.")
    systems = ["llm_only", "llm_with_url_model", "fusion_with_url_model", "url_model_only"]
    titles = ["LLM only", "LLM + URL metadata", "ML + LLM + fusion", "URL model only"]
    keys = ["accuracy", "precision", "recall", "f1", "false_positive_rate"]
    names = ["Accuracy", "Precision", "Recall", "F1", "False positive rate"]
    colors = ["#0f766e", "#2563eb", "#b45309", "#64748b"]
    fig, ax = plt.subplots(figsize=(12, 5.5), layout="constrained")
    x = np.arange(len(keys))
    width = .18
    for i, (system, title, color) in enumerate(zip(systems, titles, colors)):
        values = [100 * (summary["metrics"][system][key] or 0) for key in keys]
        bars = ax.bar(x + (i - 1.5) * width, values, width, label=title, color=color)
        ax.bar_label(bars, labels=[f"{v:.1f}" for v in values], fontsize=8, padding=3, rotation=90)
    ax.set_xticks(x, names)
    ax.set_ylim(0, 119)
    ax.set_yticks(range(0, 101, 20))
    ax.set_ylabel("Percent")
    ax.set_title(f"URL model ablation | {dataset_title}\nHigher is better except false positive rate; UNKNOWN retained as abstention")
    ax.legend(loc="upper center", bbox_to_anchor=(.5, -.08), ncol=2, frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    for extension in ("png", "svg"):
        fig.savefig(args.run / f"metrics.{extension}", dpi=180, bbox_inches="tight")
    plt.close(fig)
    fig, axes = plt.subplots(1, 4, figsize=(13, 3.8), layout="constrained")
    for ax, system, title in zip(axes, systems, titles):
        m = summary["metrics"][system]
        matrix = np.array([[m["tn"], m["fp"], m["unknown_negative"]], [m["fn"], m["tp"], m["unknown_positive"]]])
        ax.imshow(matrix, cmap="Blues", vmin=0, vmax=max(summary["positive"], summary["negative"]))
        for (i, j), count in np.ndenumerate(matrix):
            ax.text(j, i, str(count), ha="center", va="center", color="white" if count > summary["n"] / 4 else "#172554", fontsize=14)
        ax.set_xticks([0, 1, 2], ["Normal", "Alarm", "Unknown"], rotation=25)
        ax.set_yticks([0, 1], ["Normal", "Phishing"])
        ax.set_xlabel("Prediction")
        ax.set_ylabel("True label")
        ax.set_title(title, fontsize=11)
    fig.suptitle("Confusion matrices — " + dataset_title)
    for extension in ("png", "svg"):
        fig.savefig(args.run / f"confusion_matrices.{extension}", dpi=180, bbox_inches="tight")
    print("Saved metrics and confusion matrices as PNG and SVG.")


if __name__ == "__main__":
    main()
