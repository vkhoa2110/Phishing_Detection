"""Binary alarm metrics that keep UNKNOWN/error/pending separate."""
from collections import Counter
import math


def prediction(level):
    if level in {"HIGH", "WARNING"}:
        return 1
    if level == "LOW":
        return 0
    return None


def ratio(a, b):
    return a / b if b else None


def measure(labels, levels):
    if len(labels) != len(levels):
        raise ValueError("Labels and predictions have different lengths.")
    counts = Counter(tp=0, fp=0, tn=0, fn=0, unknown_positive=0, unknown_negative=0)
    for label, level in zip(labels, levels):
        if type(label) is not int or label not in (0, 1):
            raise ValueError("Labels must be 0 or 1.")
        pred = prediction(level)
        name = ("unknown_positive" if label else "unknown_negative") if pred is None else (
            "tp" if label and pred else "fn" if label else "fp" if pred else "tn")
        counts[name] += 1
    n = len(labels)
    covered = counts["tp"] + counts["tn"] + counts["fp"] + counts["fn"]
    precision = ratio(counts["tp"], counts["tp"] + counts["fp"])
    recall = ratio(counts["tp"], sum(labels))
    # Abstained positives count as missed detections in the full-set F1.
    denominator = 2 * counts["tp"] + counts["fp"] + counts["fn"] + counts["unknown_positive"]
    return {"n": n, **counts, "coverage": ratio(covered, n),
            "accuracy": ratio(counts["tp"] + counts["tn"], n),
            "selective_accuracy": ratio(counts["tp"] + counts["tn"], covered),
            "precision": precision, "recall": recall,
            "f1": ratio(2 * counts["tp"], denominator),
            "false_positive_rate": ratio(counts["fp"], n - sum(labels)),
            "risk_counts": dict(Counter(levels))}


def paired_comparison(labels, baseline, treatment):
    """Paired correctness on the same messages; abstentions are incorrect."""
    if len(labels) != len(baseline) or len(labels) != len(treatment):
        raise ValueError("Paired arrays must have the same length.")
    improved = regressed = both_correct = both_wrong = 0
    for y, left, right in zip(labels, baseline, treatment):
        a, b = prediction(left) == y, prediction(right) == y
        improved += not a and b
        regressed += a and not b
        both_correct += a and b
        both_wrong += not a and not b
    discordant = improved + regressed
    p = min(1.0, 2 * sum(math.comb(discordant, k) for k in range(min(improved, regressed) + 1)) / 2**discordant) if discordant else 1.0
    return {"n": len(labels), "improved": improved, "regressed": regressed,
            "both_correct": both_correct, "both_wrong": both_wrong,
            "accuracy_delta": ratio(improved - regressed, len(labels)),
            "mcnemar_exact_p": p}
