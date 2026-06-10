import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from plot_style import apply_paper_style


OUT_DIR = Path(__file__).resolve().parent
OUT_NAME = "main_policy_improvement"
DATA_FILE = OUT_DIR / "main_policy_improvement_data.json"

DATASETS = ["LIBERO", "CALVIN"]
ACTION_METRICS = ["NormL1", "TransL1", "NonTransL1", "ChunkL1"]
GRIPPER_METRICS = ["GripF1", "TGripF1"]
METHODS = ["DP-Base", "Clock-pre", "LaDyP"]

SHORT_LABELS = {
    "NormL1": "Norm",
    "TransL1": "Trans",
    "NonTransL1": "NonT",
    "ChunkL1": "Chunk",
    "GripF1": "Grip",
    "TGripF1": "TGrip",
}

COLORS = {
    "DP-Base": "#6B7280",
    "Clock-pre": "#E69F00",
    "LaDyP": "#0072B2",
}

HATCHES = {
    "DP-Base": "",
    "Clock-pre": "xxx",
    "LaDyP": "///",
}

PANEL_TITLE_SIZE = 13.2
AXIS_LABEL_SIZE_LOCAL = 13.0
TICK_LABEL_SIZE_LOCAL = 11.0
LEGEND_SIZE_LOCAL = 10.6
DELTA_LABEL_SIZE = 9.0
BAR_VALUE_SIZE = 7.6


def load_values():
    payload = json.loads(DATA_FILE.read_text())
    return payload["values"]


def set_style():
    apply_paper_style(
        {
            "font.size": 11.0,
            "axes.labelsize": AXIS_LABEL_SIZE_LOCAL,
            "axes.titlesize": PANEL_TITLE_SIZE,
            "legend.fontsize": LEGEND_SIZE_LOCAL,
            "xtick.labelsize": TICK_LABEL_SIZE_LOCAL,
            "ytick.labelsize": TICK_LABEL_SIZE_LOCAL,
            "axes.grid": True,
            "grid.linestyle": "--",
            "grid.linewidth": 0.5,
            "grid.alpha": 0.28,
        }
    )


def metric_values(values, dataset, metric):
    return np.array([values[method][dataset][metric] for method in METHODS], dtype=float)


def draw_panel(ax, values, dataset, metrics, title, kind):
    x = np.arange(len(metrics))
    width = 0.24
    offsets = np.linspace(-width, width, len(METHODS))

    raw = np.array([[values[method][dataset][metric] for metric in metrics] for method in METHODS])
    if kind == "f1":
        plot_values = raw * 100.0
        ylabel = "F1 (%)"
        value_fmt = "{:.1f}"
    else:
        plot_values = raw
        ylabel = "L1 error"
        value_fmt = "{:.3f}"

    ymax = float(plot_values.max())
    ymin = float(plot_values.min())
    span = max(ymax - ymin, 1e-6)
    lower = 0.0 if kind == "error" else max(0.0, ymin - span * 0.55)
    upper = ymax + span * (0.65 if kind == "error" else 0.45)
    ax.set_ylim(lower, upper)

    for j, method in enumerate(METHODS):
        bars = ax.bar(
            x + offsets[j],
            plot_values[j],
            width,
            label=method,
            color=COLORS[method],
            edgecolor="#111827",
            linewidth=0.55,
            hatch=HATCHES[method],
            alpha=0.92,
            zorder=3,
        )
        for bar, value in zip(bars, plot_values[j]):
            visible_bottom = max(lower, 0.0)
            label_y = visible_bottom + (bar.get_height() - visible_bottom) * 0.52
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                label_y,
                value_fmt.format(value),
                ha="center",
                va="center",
                fontsize=BAR_VALUE_SIZE,
                rotation=90,
                color="#111827",
                bbox={
                    "boxstyle": "round,pad=0.12",
                    "facecolor": "white",
                    "edgecolor": "none",
                    "alpha": 0.78,
                },
                zorder=5,
            )

    base = raw[METHODS.index("DP-Base")]
    ladyp = raw[METHODS.index("LaDyP")]
    for i, metric in enumerate(metrics):
        if kind == "error":
            delta = (base[i] - ladyp[i]) / base[i] * 100.0
            label = f"-{delta:.1f}%"
        else:
            delta = (ladyp[i] - base[i]) * 100.0
            label = f"+{delta:.1f}"
        ax.text(
            x[i],
            upper - (upper - lower) * 0.08,
            label,
            ha="center",
            va="top",
            fontsize=DELTA_LABEL_SIZE,
            color=COLORS["LaDyP"],
            fontweight="bold",
        )

    ax.set_title(title, fontsize=PANEL_TITLE_SIZE, fontweight="normal", pad=5)
    ax.set_xticks(x)
    ax.set_xticklabels([SHORT_LABELS[m] for m in metrics])
    ax.set_ylabel(ylabel, fontsize=AXIS_LABEL_SIZE_LOCAL, labelpad=4)
    ax.grid(axis="y", zorder=0)
    ax.grid(axis="x", visible=False)
    ax.tick_params(axis="x", length=0, labelsize=TICK_LABEL_SIZE_LOCAL, pad=2)
    ax.tick_params(axis="y", labelsize=TICK_LABEL_SIZE_LOCAL)


def main():
    set_style()
    values = load_values()

    fig, axes = plt.subplots(2, 2, figsize=(5.25, 4.15), sharex=False)

    draw_panel(axes[0, 0], values, "LIBERO", ACTION_METRICS, "(a) LIBERO action error", "error")
    draw_panel(axes[0, 1], values, "CALVIN", ACTION_METRICS, "(b) CALVIN action error", "error")
    draw_panel(axes[1, 0], values, "LIBERO", GRIPPER_METRICS, "(c) LIBERO gripper F1", "f1")
    draw_panel(axes[1, 1], values, "CALVIN", GRIPPER_METRICS, "(d) CALVIN gripper F1", "f1")

    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        ncol=3,
        frameon=False,
        loc="upper center",
        bbox_to_anchor=(0.52, 1.025),
        handlelength=1.35,
        columnspacing=0.9,
        handletextpad=0.45,
        fontsize=LEGEND_SIZE_LOCAL,
    )
    fig.subplots_adjust(left=0.095, right=0.995, top=0.845, bottom=0.12, wspace=0.28, hspace=0.54)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for ext in ("pdf", "png"):
        out = OUT_DIR / f"{OUT_NAME}.{ext}"
        fig.savefig(out, dpi=300, bbox_inches="tight")
        print(out)


if __name__ == "__main__":
    main()
