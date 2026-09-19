"""Regenerate the report figure and table from recorded measurements.

uv run --with matplotlib python scripts/plot_findings.py
"""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
study = json.loads((ROOT / "reports/benchmark-results.json").read_text())
cases = study["cases"]
labels = ["Structured\nsynthetic", "Vague\nsynthetic", "Published\npaper"][: len(cases)]
colors = ["#789065", "#b96146", "#879199"][: len(cases)]
plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.labelcolor": "#33412e",
        "text.color": "#33412e",
        "axes.edgecolor": "#c6ccbf",
        "xtick.color": "#59634f",
        "ytick.color": "#59634f",
        "pdf.fonttype": 42,
    }
)
fig, axes = plt.subplots(1, 2, figsize=(8.2, 3.1))
for i, case in enumerate(cases):
    axes[0].bar(i, case["mean_score"], color=colors[i], width=0.52, alpha=0.85)
    axes[0].errorbar(i, case["mean_score"], yerr=case["score_stdev"], color="#293927", capsize=4, linewidth=1)
    axes[0].text(i, case["mean_score"] + 3, f"{case['mean_score']:.1f}", ha="center", fontsize=9)
    for trial in case["trials"]:
        axes[0].scatter(i, trial["score"], s=9, color="#33412e", zorder=3)
    axes[1].bar(
        i - 0.16,
        case["mean_first_section_ms"] / 1000,
        width=0.3,
        color="#b7c8a0",
        label="First section" if i == 0 else None,
    )
    axes[1].bar(
        i + 0.16,
        case["mean_total_ms"] / 1000,
        width=0.3,
        color="#698054",
        label="Complete review" if i == 0 else None,
    )
axes[0].set(ylabel="Rubric score (0–100)", ylim=(0, 100), title="A. Sensitivity, not scientific validity")
axes[1].set(ylabel="Wall-clock time (seconds)", ylim=(0, 1.6), title="B. Results arrive before completion")
axes[1].legend(frameon=False, fontsize=8, loc="upper left")
for axis in axes:
    axis.set_xticks(range(len(cases)), labels)
    axis.grid(axis="y", alpha=0.16, zorder=0)
    axis.set_axisbelow(True)
fig.tight_layout(pad=1.4)
fig.savefig(ROOT / "reports/benchmark-figure.pdf", bbox_inches="tight")
fig.savefig(ROOT / "reports/benchmark-figure.png", dpi=180, bbox_inches="tight")
names = ["Structured synthetic", "Vague synthetic", "Published paper"]
rows = []
for name, case in zip(names, cases):
    rows.append(
        f"{name} & {case['pages']} & {case['sections']} & {case['mean_score']:.2f} $\\pm$ {case['score_stdev']:.2f} & {case['mean_first_section_ms'] / 1000:.3f} & {case['mean_total_ms'] / 1000:.3f} "
        + r"\\"
    )
table = [
    r"\begin{tabular}{lrrr rr}",
    r"\toprule",
    r"Document & Pages & Units & Score $\pm$ SD & First result & Complete \\",
    r"\midrule",
    *rows,
    r"\bottomrule",
    r"\end{tabular}",
]
(ROOT / "reports/measurement-table.tex").write_text("\n".join(table) + "\n")
print("Wrote benchmark-figure.pdf, benchmark-figure.png, and measurement-table.tex")
