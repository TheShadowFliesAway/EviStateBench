from pathlib import Path
import json

import matplotlib.pyplot as plt
import numpy as np

from plot_style import apply_paper_style


OUT_DIR = Path(__file__).resolve().parent
OUT_NAME = "training_convergence"
DATA_PATH = OUT_DIR / f"{OUT_NAME}_data.json"

METHODS = ["DP-Base", "Clock-pre", "LaDyP"]
SHORT_METHOD_LABELS = {
    "DP-Base": "Base",
    "Clock-pre": "Clock",
    "LaDyP": "LaDyP",
}
COLORS = {
    "DP-Base": "#6B7280",
    "Clock-pre": "#E69F00",
    "LaDyP": "#0072B2",
}
MARKERS = {
    "DP-Base": "o",
    "Clock-pre": "s",
    "LaDyP": "D",
}

PANEL_TITLE_SIZE = 13.0
AXIS_LABEL_SIZE_LOCAL = 13.0
TICK_LABEL_SIZE_LOCAL = 11.0
RIGHT_TICK_LABEL_SIZE = 9.6
LEGEND_SIZE_LOCAL = 10.6
ANNOTATION_SIZE_LOCAL = 9.4
NOTE_SIZE_LOCAL = 9.2


def set_style():
    apply_paper_style(
        {
            "font.size": 11.0,
            "axes.labelsize": AXIS_LABEL_SIZE_LOCAL,
            "axes.titlesize": PANEL_TITLE_SIZE,
            "legend.fontsize": LEGEND_SIZE_LOCAL,
            "xtick.labelsize": TICK_LABEL_SIZE_LOCAL,
            "ytick.labelsize": TICK_LABEL_SIZE_LOCAL,
        }
    )


def load_data():
    with DATA_PATH.open("r") as f:
        return json.load(f)


def draw_curve(ax, data):
    epochs = np.asarray(data["epochs"], dtype=float)
    base_best = float(data["base_best_selection_score"])

    for method in METHODS:
        summary = data["summary"][method]
        mean = np.asarray(summary["curve_mean"], dtype=float)
        low = np.asarray(summary["curve_min"], dtype=float)
        high = np.asarray(summary["curve_max"], dtype=float)
        color = COLORS[method]

        if summary["num_runs"] > 1:
            ax.fill_between(epochs, low, high, color=color, alpha=0.13, linewidth=0)
        ax.plot(
            epochs,
            mean,
            color=color,
            linewidth=2.35 if method == "LaDyP" else 2.0,
            label=method,
            zorder=4 if method == "LaDyP" else 3,
        )
        mark_epochs = [1, 4, 8, 12, 16, 20, 24, 28]
        mark_x, mark_y = [], []
        for ep in mark_epochs:
            idx = int(ep - 1)
            if idx < len(mean) and np.isfinite(mean[idx]):
                mark_x.append(ep)
                mark_y.append(mean[idx])
        ax.scatter(
            mark_x,
            mark_y,
            color=color,
            marker=MARKERS[method],
            s=23,
            edgecolor="black",
            linewidth=0.35,
            zorder=5,
        )

    ax.axhline(
        base_best,
        color=COLORS["DP-Base"],
        linewidth=0.95,
        linestyle="--",
        alpha=0.75,
        zorder=1,
    )
    ax.text(
        1.2,
        base_best + 0.006,
        "DP-Base best",
        color="#4B5563",
        fontsize=NOTE_SIZE_LOCAL,
        va="bottom",
    )

    ax.set_title("(a) Validation score", fontsize=PANEL_TITLE_SIZE, fontweight="normal", pad=5)
    ax.set_xlabel("Training epoch", fontsize=AXIS_LABEL_SIZE_LOCAL)
    ax.set_ylabel("Selection score", fontsize=AXIS_LABEL_SIZE_LOCAL)
    ax.set_xlim(1, 30)
    ax.set_ylim(0.245, 0.63)
    ax.set_xticks([1, 4, 8, 12, 16, 20, 24, 28, 30])
    ax.set_yticks([0.25, 0.35, 0.45, 0.55, 0.62])
    ax.grid(axis="y", linestyle="--", linewidth=0.5, alpha=0.35)
    ax.tick_params(axis="both", labelsize=TICK_LABEL_SIZE_LOCAL)
    ax.legend(frameon=False, loc="upper right", borderaxespad=0.2, fontsize=LEGEND_SIZE_LOCAL)


def value_with_runs(summary, key):
    values = summary.get(key + "_runs", [])
    mean = summary[key + "_mean"]
    return mean, values


def draw_summary_bars(ax, data, title, key, xlim, fmt, xlabel=None):
    y = np.arange(len(METHODS))
    vals = [float(data["summary"][method][key]) for method in METHODS]
    for yi, method, val in zip(y, METHODS, vals, strict=False):
        ax.barh(
            yi,
            val,
            color=COLORS[method],
            edgecolor="#111827",
            linewidth=0.45,
            height=0.55,
            alpha=0.92,
            zorder=3,
        )
        ax.text(
            val + (xlim[1] - xlim[0]) * 0.025,
            yi,
            fmt.format(val),
            va="center",
            ha="left",
            fontsize=ANNOTATION_SIZE_LOCAL,
            color="#111827",
        )
    ax.set_title(title, fontsize=PANEL_TITLE_SIZE, fontweight="normal", pad=4)
    ax.set_yticks(y)
    ax.set_yticklabels([SHORT_METHOD_LABELS[m] for m in METHODS])
    ax.invert_yaxis()
    ax.set_xlim(*xlim)
    ax.grid(axis="x", linestyle="--", linewidth=0.5, alpha=0.35, zorder=0)
    ax.tick_params(axis="y", length=0, labelsize=RIGHT_TICK_LABEL_SIZE, pad=1)
    ax.tick_params(axis="x", labelsize=TICK_LABEL_SIZE_LOCAL)
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=AXIS_LABEL_SIZE_LOCAL)


def main():
    set_style()
    data = load_data()

    fig = plt.figure(figsize=(5.25, 3.75))
    gs = fig.add_gridspec(
        3,
        2,
        width_ratios=[2.05, 1.0],
        height_ratios=[1, 1, 1],
        wspace=0.22,
        hspace=1.02,
    )
    ax_curve = fig.add_subplot(gs[:, 0])
    ax_best = fig.add_subplot(gs[0, 1])
    ax_speed = fig.add_subplot(gs[1, 1])
    ax_early = fig.add_subplot(gs[2, 1])

    draw_curve(ax_curve, data)
    draw_summary_bars(
        ax_best,
        data,
        "(b) Best score ↓",
        "best_score_mean",
        (0.0, 0.32),
        "{:.3f}",
    )
    draw_summary_bars(
        ax_speed,
        data,
        "(c) Match DP-Base ↓",
        "reach_base_best_epoch_mean",
        (0, 32),
        "{:.1f}",
    )
    draw_summary_bars(
        ax_early,
        data,
        "(d) Early AUC ↓",
        "auc12_mean",
        (0.0, 0.46),
        "{:.3f}",
        "epoch 1-12 mean",
    )

    fig.subplots_adjust(left=0.095, right=0.99, top=0.91, bottom=0.14)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for ext in ("pdf", "png"):
        out = OUT_DIR / f"{OUT_NAME}.{ext}"
        fig.savefig(out, dpi=300, bbox_inches="tight")
        print(out)


if __name__ == "__main__":
    main()
