from pathlib import Path
import json

import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
import numpy as np

from plot_style import apply_paper_style


OUT_DIR = Path(__file__).resolve().parent
OUT_NAME = "beta_injection_study"
DATA_PATH = OUT_DIR / f"{OUT_NAME}_data.json"

DATASETS = ["LIBERO", "CALVIN"]
REFERENCE = "Adapter 0.50"
ROWS = ["Adapter 0.25", "Adapter 1.00", "Gripper adapter", "+ beta_horizon"]
HIGHLIGHT = "+ beta_horizon"

COLORS = {
    "positive": "#0072B2",
    "negative": "#D55E00",
    "neutral": "#A7B0BE",
    "highlight": "#0072B2",
    "edge": "#111827",
}

PANEL_TITLE_SIZE = 12.8
AXIS_LABEL_SIZE_LOCAL = 12.4
TICK_LABEL_SIZE_LOCAL = 11.2
ROW_LABEL_SIZE = 11.6
ANNOTATION_SIZE_LOCAL = 10.8


def set_style():
    apply_paper_style(
        {
            "font.size": 11.8,
            "axes.labelsize": AXIS_LABEL_SIZE_LOCAL,
            "axes.titlesize": PANEL_TITLE_SIZE,
            "xtick.labelsize": TICK_LABEL_SIZE_LOCAL,
            "ytick.labelsize": ROW_LABEL_SIZE,
        }
    )


def load_data():
    with DATA_PATH.open("r") as f:
        return json.load(f)


def mean_metric(data, row, metric):
    return float(
        np.mean([float(data["values"][row][dataset][metric]) for dataset in DATASETS])
    )


def value(data, row, metric):
    if metric == "SelectionScore":
        return float(data["values"][row]["SelectionScore"])
    return mean_metric(data, row, metric)


def relative_gain(data, row, metric, error_metric=True, percent=True):
    ref = value(data, REFERENCE, metric)
    cur = value(data, row, metric)
    if error_metric:
        gain = (ref - cur) / ref
    else:
        gain = cur - ref
    if percent:
        gain *= 100.0
    return gain


def build_panel_values(data):
    return {
        "TransL1": [
            relative_gain(data, row, "TransL1", error_metric=True, percent=True)
            for row in ROWS
        ],
        "ActionDeltaL1Beta": [
            relative_gain(
                data, row, "ActionDeltaL1Beta", error_metric=True, percent=True
            )
            for row in ROWS
        ],
        "TGripF1": [
            relative_gain(data, row, "TGripF1", error_metric=False, percent=True)
            for row in ROWS
        ],
        "SelectionScore": [
            relative_gain(data, row, "SelectionScore", error_metric=True, percent=True)
            for row in ROWS
        ],
    }


def add_row_guides(ax):
    for i, row in enumerate(ROWS):
        if i % 2 == 1:
            ax.axhspan(i - 0.42, i + 0.42, color="#F8FAFC", zorder=0)
        if row == HIGHLIGHT:
            ax.axhspan(i - 0.42, i + 0.42, color="#EAF4FF", zorder=0)


def style_yaxis(ax, show_labels):
    y = np.arange(len(ROWS))
    ax.set_yticks(y)
    if show_labels:
        labels = ax.set_yticklabels(ROWS, fontsize=ROW_LABEL_SIZE)
        for label, row in zip(labels, ROWS, strict=False):
            if row == HIGHLIGHT:
                label.set_color("#0B5C9A")
                label.set_fontweight("bold")
    else:
        ax.set_yticklabels([])
    ax.invert_yaxis()
    ax.tick_params(axis="y", length=0, labelsize=ROW_LABEL_SIZE)


def bar_color(row, val):
    if row == HIGHLIGHT:
        return COLORS["highlight"]
    if val < 0:
        return COLORS["negative"]
    return COLORS["neutral"]


def draw_panel(ax, values, title, xlabel, xlim, fmt, show_labels=False):
    y = np.arange(len(ROWS))
    add_row_guides(ax)
    ax.axvline(0.0, color="#111827", linewidth=0.8, zorder=1)

    for yi, row, val in zip(y, ROWS, values, strict=False):
        ax.barh(
            yi,
            val,
            height=0.52,
            color=bar_color(row, val),
            edgecolor=COLORS["edge"],
            linewidth=0.45,
            zorder=3,
        )
        dx = (xlim[1] - xlim[0]) * 0.018
        if val >= 0:
            text_x = val + dx
            ha = "left"
        else:
            text_x = val - dx
            ha = "right"
        label = ax.text(
            text_x,
            yi,
            fmt.format(val),
            ha=ha,
            va="center",
            fontsize=ANNOTATION_SIZE_LOCAL,
            fontweight="bold" if row == HIGHLIGHT else "normal",
            color="#111827",
            clip_on=False,
            zorder=4,
            bbox={
                "boxstyle": "round,pad=0.08",
                "facecolor": "white",
                "edgecolor": "none",
                "alpha": 0.68,
            },
        )
        label.set_path_effects(
            [
                pe.SimpleLineShadow(offset=(0.65, -0.65), alpha=0.22),
                pe.Normal(),
            ]
        )

    ax.set_title(title, fontsize=PANEL_TITLE_SIZE, fontweight="semibold", pad=5)
    ax.set_xlabel(xlabel, fontsize=AXIS_LABEL_SIZE_LOCAL, labelpad=3)
    ax.set_xlim(*xlim)
    style_yaxis(ax, show_labels)
    ax.tick_params(axis="x", labelsize=TICK_LABEL_SIZE_LOCAL)
    ax.grid(axis="x", linestyle="--", linewidth=0.5, color="#CBD5E1", alpha=0.55)


def main():
    set_style()
    data = load_data()
    panel_values = build_panel_values(data)

    fig = plt.figure(figsize=(5.25, 4.55))
    gs = fig.add_gridspec(2, 2, wspace=0.35, hspace=0.72)
    axes = [fig.add_subplot(gs[i, j]) for i in range(2) for j in range(2)]

    draw_panel(
        axes[0],
        panel_values["TransL1"],
        "(a) Transition action error",
        "reduction vs. A0.50 (%)",
        (-2.25, 4.2),
        "{:+.1f}",
        show_labels=True,
    )
    draw_panel(
        axes[1],
        panel_values["ActionDeltaL1Beta"],
        "(b) Beta-window action delta",
        "reduction vs. A0.50 (%)",
        (-0.3, 3.4),
        "{:+.1f}",
        show_labels=False,
    )
    draw_panel(
        axes[2],
        panel_values["TGripF1"],
        "(c) Transition gripper F1",
        "gain vs. A0.50 (pts)",
        (-1.55, 1.15),
        "{:+.1f}",
        show_labels=True,
    )
    draw_panel(
        axes[3],
        panel_values["SelectionScore"],
        "(d) Overall validation score",
        "reduction vs. A0.50 (%)",
        (-2.55, 4.4),
        "{:+.1f}",
        show_labels=False,
    )

    fig.subplots_adjust(left=0.235, right=0.985, top=0.94, bottom=0.12)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for ext in ("pdf", "png"):
        out = OUT_DIR / f"{OUT_NAME}.{ext}"
        fig.savefig(out, dpi=300, bbox_inches="tight")
        print(out)


if __name__ == "__main__":
    main()
