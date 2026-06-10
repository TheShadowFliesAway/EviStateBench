from pathlib import Path
import json

import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np
from matplotlib.colors import TwoSlopeNorm

from plot_style import (
    GRID_LINEWIDTH,
    apply_paper_style,
)


OUT_DIR = Path(__file__).resolve().parent
OUT_NAME = "signal_ablation_dense"
DATA_PATH = OUT_DIR / f"{OUT_NAME}_data.json"

DATASETS = ["LIBERO", "CALVIN"]
METRICS = ["NormL1", "TransL1", "TGripF1"]
ERROR_METRICS = {"NormL1", "TransL1"}

CMAP = plt.get_cmap("RdYlGn")
NORM = TwoSlopeNorm(vmin=-5.0, vcenter=0.0, vmax=18.0)

PANEL_TITLE_SIZE = 13.0
AXIS_LABEL_SIZE_LOCAL = 12.0
TICK_LABEL_SIZE_LOCAL = 10.2
ANNOTATION_SIZE_LOCAL = 9.2
DENSE_ANNOTATION_SIZE_LOCAL = 8.8
NOTE_SIZE_LOCAL = 9.4

ROW_LABELS = {
    "A only": "A",
    "C only": "C",
    "Full - now": "Full-n",
    "Full - horizon": "Full-h",
    "Full A+B+C": "Full",
}

METRIC_LABELS = {
    "NormL1": "N",
    "TransL1": "T",
    "TGripF1": "TG",
}


def set_style():
    apply_paper_style(
        {
            "font.size": 10.8,
            "axes.labelsize": AXIS_LABEL_SIZE_LOCAL,
            "axes.titlesize": PANEL_TITLE_SIZE,
            "xtick.labelsize": TICK_LABEL_SIZE_LOCAL,
            "ytick.labelsize": TICK_LABEL_SIZE_LOCAL,
        }
    )


def load_data():
    with DATA_PATH.open("r") as f:
        return json.load(f)


def improvement(base_value, value, metric):
    if metric in ERROR_METRICS:
        return (base_value - value) / base_value * 100.0
    return (value - base_value) * 100.0


def row_group(name):
    if name.startswith("Full"):
        if "-" in name:
            return "partial"
        return "full"
    if "*" in name:
        return "planned"
    if "+" in name:
        return "pair"
    return "single"


def build_matrix(data):
    status = data.get("status", {})
    rows = [
        row
        for row in data["order"]
        if status.get(row) != "planned_target_not_measured"
    ]
    values = data["values"]
    base = data["base"]
    matrix = []
    raw = []
    columns = []
    for dataset in DATASETS:
        for metric in METRICS:
            columns.append((dataset, metric))
    for row in rows:
        vals, raws = [], []
        for dataset, metric in columns:
            base_v = float(base[dataset][metric])
            cur_v = float(values[row][dataset][metric])
            vals.append(improvement(base_v, cur_v, metric))
            raws.append(cur_v)
        matrix.append(vals)
        raw.append(raws)
    return rows, columns, np.asarray(matrix), np.asarray(raw)


def draw_heatmap(ax, data, rows, columns, matrix):
    im = ax.imshow(matrix, aspect="auto", cmap=CMAP, norm=NORM)

    ax.set_yticks(np.arange(len(rows)))
    ax.set_yticklabels([ROW_LABELS.get(row, row) for row in rows])
    labels = []
    for dataset, metric in columns:
        labels.append(f"{dataset[:3]} {METRIC_LABELS[metric]}")
    ax.set_xticks(np.arange(len(columns)))
    ax.set_xticklabels(labels, rotation=26, ha="right", rotation_mode="anchor")

    ax.set_title("(a) Per-metric improvement", fontsize=PANEL_TITLE_SIZE, fontweight="normal", pad=5)
    ax.tick_params(length=0, labelsize=TICK_LABEL_SIZE_LOCAL)

    for i, row in enumerate(rows):
        group = row_group(row)
        if group == "planned":
            for j in range(len(columns)):
                ax.add_patch(
                    patches.Rectangle(
                        (j - 0.5, i - 0.5),
                        1,
                        1,
                        fill=False,
                        hatch="///",
                        edgecolor="#6B7280",
                        linewidth=0.0,
                        zorder=3,
                    )
                )
        if group == "full":
            ax.add_patch(
                patches.Rectangle(
                    (-0.5, i - 0.5),
                    len(columns),
                    1,
                    fill=False,
                    edgecolor="#0072B2",
                    linewidth=1.2,
                    zorder=4,
                )
            )
        for j, val in enumerate(matrix[i]):
            if columns[j][1] in ERROR_METRICS:
                text = f"{val:+.1f}%"
            else:
                text = f"{val:+.1f}"
            ax.text(
                j,
                i,
                text,
                ha="center",
                va="center",
                fontsize=DENSE_ANNOTATION_SIZE_LOCAL,
                color="#111827",
            )

    separators = []
    for marker in ["C only", "B+C", "Full - horizon"]:
        if marker in rows:
            separators.append(rows.index(marker) + 0.5)
    for y in separators:
        ax.axhline(y, color="#111827", linewidth=0.7, alpha=0.55)
    ax.axvline(2.5, color="#111827", linewidth=0.7, alpha=0.55)
    return im


def draw_score(ax, rows, matrix):
    y = np.arange(len(rows))
    score = matrix.mean(axis=1)
    for yi, row, val in zip(y, rows, score, strict=False):
        group = row_group(row)
        color = CMAP(NORM(val))
        hatch = "///" if group == "planned" else None
        edge = "#111827"
        linewidth = 1.15 if group == "full" else 0.65
        ax.barh(
            yi,
            val,
            height=0.55,
            color=color,
            edgecolor=edge,
            linewidth=linewidth,
            hatch=hatch,
            alpha=0.95,
            zorder=3,
        )
        ax.text(
            val + 0.35,
            yi,
            f"{val:+.1f}",
            ha="left",
            va="center",
            fontsize=ANNOTATION_SIZE_LOCAL,
            color="#111827",
        )

    ax.axvline(0, color="#111827", linewidth=0.8)
    ax.set_yticks(y)
    ax.set_yticklabels([])
    ax.invert_yaxis()
    ax.set_xlim(-4.0, 16.5)
    ax.set_title("(b) Mean gain", fontsize=PANEL_TITLE_SIZE, fontweight="normal", pad=5)
    ax.set_xlabel("mean over cells", fontsize=AXIS_LABEL_SIZE_LOCAL)
    ax.grid(axis="x", linestyle="--", linewidth=GRID_LINEWIDTH, alpha=0.32, zorder=0)
    ax.tick_params(axis="y", length=0, labelsize=TICK_LABEL_SIZE_LOCAL)
    ax.tick_params(axis="x", labelsize=TICK_LABEL_SIZE_LOCAL)


def main():
    set_style()
    data = load_data()
    rows, columns, matrix, _ = build_matrix(data)

    fig = plt.figure(figsize=(5.25, 3.65))
    gs = fig.add_gridspec(1, 2, width_ratios=[2.85, 0.78], wspace=0.18)
    ax_heat = fig.add_subplot(gs[0, 0])
    ax_score = fig.add_subplot(gs[0, 1])

    im = draw_heatmap(ax_heat, data, rows, columns, matrix)
    draw_score(ax_score, rows, matrix)

    cbar = fig.colorbar(im, ax=ax_heat, fraction=0.038, pad=0.018)
    cbar.set_label("")
    cbar.ax.tick_params(labelsize=TICK_LABEL_SIZE_LOCAL, length=2)

    fig.text(
        0.105,
        0.975,
        "A = phase belief   |   B = local progress   |   C = boundary likelihood",
        ha="left",
        va="top",
        fontsize=NOTE_SIZE_LOCAL,
        color="#374151",
        bbox={
            "boxstyle": "round,pad=0.22",
            "facecolor": "#F8FAFC",
            "edgecolor": "#E5E7EB",
            "linewidth": 0.5,
        },
    )

    fig.subplots_adjust(left=0.08, right=0.985, top=0.82, bottom=0.15)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for ext in ("pdf", "png"):
        out = OUT_DIR / f"{OUT_NAME}.{ext}"
        fig.savefig(out, dpi=300, bbox_inches="tight")
        print(out)


if __name__ == "__main__":
    main()
