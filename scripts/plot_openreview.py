"""Generate the ICLR pilot's figures and LaTeX tables from held-out measurements."""

import json
from itertools import pairwise
from pathlib import Path

import matplotlib
import numpy as np
from sklearn.metrics import roc_curve

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
study = json.loads((REPORTS / "iclr2026-study.json").read_text())
test = [row for row in study["papers"] if row["split"] == "test"]
y = np.array([row["label"] for row in test])
p = np.array([row["acceptance_probability"] for row in test])
metrics, baseline = study["metrics"], study["baseline"]
green, copper, ink = "#526e4a", "#aa5038", "#2b342e"
plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 10,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.labelcolor": ink,
        "text.color": ink,
        "axes.titleweight": "bold",
        "figure.facecolor": "white",
    }
)
fig, axes = plt.subplots(2, 2, figsize=(10, 7.4), constrained_layout=True)
fpr, tpr, _ = roc_curve(y, p)
axes[0, 0].plot(fpr, tpr, color=green, lw=2, label=f"Jev classifier (AUROC {metrics['roc_auc']:.3f})")
axes[0, 0].plot([0, 1], [0, 1], "--", color="#a0a59c", label="Chance ranking")
axes[0, 0].set(
    title="A. Held-out ranking",
    xlabel="False-positive rate",
    ylabel="True-positive rate",
    xlim=(0, 1),
    ylim=(0, 1.02),
)
axes[0, 0].legend(loc="lower right", frameon=False, fontsize=8)

matrix = np.array(metrics["confusion_matrix"])
axes[0, 1].imshow(matrix, cmap="Greens", vmin=0, vmax=max(matrix.max(), 1))
for i in range(2):
    for j in range(2):
        axes[0, 1].text(
            j,
            i,
            str(matrix[i, j]),
            ha="center",
            va="center",
            fontsize=22,
            color="white" if matrix[i, j] > matrix.max() * 0.65 else ink,
        )
axes[0, 1].set(
    title="B. Decisions at probability 0.50",
    xticks=[0, 1],
    yticks=[0, 1],
    xticklabels=["Reject", "Accept"],
    yticklabels=["Rejected", "Accepted"],
    xlabel="Predicted decision",
    ylabel="Recorded decision",
)

edges = np.linspace(0, 1, 6)
for low, high in pairwise(edges):
    selected = (p >= low) & ((p < high) | ((high == 1) & (p <= high)))
    if selected.any():
        xp, yp = p[selected].mean(), y[selected].mean()
        axes[1, 0].scatter(xp, yp, s=30 + 4 * selected.sum(), color=green, zorder=3)
        axes[1, 0].annotate(
            f"n={selected.sum()}",
            (xp, yp),
            xytext=(7, -14 if yp > 0.9 else 6),
            textcoords="offset points",
            fontsize=8,
        )
axes[1, 0].plot([0, 1], [0, 1], "--", color="#a0a59c")
axes[1, 0].set(
    title="C. Reliability (five fixed bins)",
    xlabel="Mean predicted probability",
    ylabel="Observed acceptance fraction",
    xlim=(0, 1),
    ylim=(-0.03, 1.03),
)

bins = np.linspace(0, 1, 21)
axes[1, 1].hist(p[y == 0], bins=bins, color=copper, alpha=0.65, label="Recorded reject")
axes[1, 1].hist(p[y == 1], bins=bins, histtype="step", lw=2, color=green, label="Recorded accept")
axes[1, 1].axvline(0.5, color=ink, linestyle="--", lw=1)
axes[1, 1].set(
    title="D. Considerable overlap between classes",
    xlabel="Estimated acceptance probability",
    ylabel="Number of test papers",
    xlim=(0, 1),
)
axes[1, 1].legend(frameon=False, fontsize=8)
for ax in (axes[0, 0], axes[1, 0], axes[1, 1]):
    ax.grid(alpha=0.12)
fig.savefig(REPORTS / "iclr2026-evaluation.pdf")
fig.savefig(REPORTS / "iclr2026-evaluation.png", dpi=180)

lines = [
    r"% Generated from iclr2026-study.json; do not edit measurements by hand.",
    r"\newcommand{\StudySplitTable}{\begin{tabular}{lrrr}\toprule Split & Accepted & Rejected & Total \\ \midrule",
]
for name, count in study["counts"].items():
    lines.append(f"{name.title()} & {count['accepted']} & {count['rejected']} & {count['total']} " + r"\\")
lines.append(r"\bottomrule\end{tabular}}")
lines.append(
    r"\newcommand{\StudyMetricTable}{\begin{tabular}{lrrl}\toprule Metric & Classifier & Baseline & 95\% bootstrap interval \\ \midrule"
)
for label, key, percent in (
    ("Accuracy", "accuracy", True),
    ("Balanced accuracy", "balanced_accuracy", True),
    ("AUROC", "roc_auc", False),
    ("Brier score", "brier", False),
    ("Log loss", "log_loss", False),
):

    def format_value(value, percent=percent):
        return f"{value * 100:.1f}" + r"\%" if percent else f"{value:.3f}"

    interval = metrics.get("bootstrap_95_ci", {}).get(key)
    ci = "--".join(format_value(v) for v in interval) if interval else "Not estimated"
    lines.append(f"{label} & {format_value(metrics[key])} & {format_value(baseline[key])} & {ci} " + r"\\")
lines.append(r"\bottomrule\end{tabular}}")
(REPORTS / "iclr2026-measurements.tex").write_text("\n".join(lines) + "\n")
print("Wrote held-out evaluation figures and measurement tables.")
