from pathlib import Path
import json

import matplotlib.pyplot as plt
import numpy as np

from plot_style import apply_paper_style


OUT_DIR = Path(__file__).resolve().parent
OUT_NAME = "corrupted_control_summary"
DATA_PATH = OUT_DIR / f"{OUT_NAME}_data.json"

DATASETS = ["LIBERO", "CALVIN"]
ACTION_METRICS = ["NormL1", "TransL1", "ChunkL1"]
METHODS = ["Full LaDyP", "Random beta", "Shifted signal", "Shuffled episode"]

COLORS = {
    "Full LaDyP": "#0072B2",
    "Random beta": "#E69F00",
    "Shifted signal": "#7EA6D9",
    "Shuffled episode": "#9CA3AF",
}

PANEL_TITLE_SIZE = 12.8
AXIS_LABEL_SIZE_LOCAL = 11.8
TICK_LABEL_SIZE_LOCAL = 10.8
ROW_LABEL_SIZE = 11.2
ANNOTATION_SIZE_LOCAL = 9.8


def set_style():
    apply_paper_style(
        {
            "font.size": 11.2,
            "axes.labelsize": AXIS_LABEL_SIZE_LOCAL,
            "axes.titlesize": PANEL_TITLE_SIZE,
            "xtick.labelsize": TICK_LABEL_SIZE_LOCAL,
            "ytick.labelsize": ROW_LABEL_SIZE,
        }
    )


def load_values():
    with DATA_PATH.open("r") as f:
        return json.load(f)["values"]


def mean_action_gain(values, method):
    base = values["DP-Base"]
    current = values[method]
    gains = []
    for dataset in DATASETS:
        for metric in ACTION_METRICS:
            base_v = float(base[dataset][metric])
            current_v = float(current[dataset][metric])
            gains.append((base_v - current_v) / base_v * 100.0)
    return float(np.mean(gains))


def mean_tgrip_gain(values, method):
    base = values["DP-Base"]
    current = values[method]
    gains = []
    for dataset in DATASETS:
        gains.append(
            (float(current[dataset]["TGripF1"]) - float(base[dataset]["TGripF1"]))
            * 100.0
        )
    return float(np.mean(gains))


def annotate_bar(ax, value, y, suffix, xpad=0.14):
    ha = "left" if value >= 0 else "right"
    x = value + (xpad if value >= 0 else -xpad)
    ax.text(
        x,
        y,
        f"{value:+.1f}{suffix}",
        ha=ha,
        va="center",
        fontsize=ANNOTATION_SIZE_LOCAL,
        color="#111827",
    )


def draw_panel(ax, y, panel_values, title, xlabel, xlim, suffix):
    ax.axvline(0.0, color="#111827", linewidth=0.9, alpha=0.75, zorder=1)
    for yi, method, value in zip(y, METHODS, panel_values, strict=False):
        ax.barh(
            yi,
            value,
            height=0.52,
            color=COLORS[method],
            edgecolor="#111827",
            linewidth=0.5,
            alpha=0.95,
            zorder=2,
        )
        annotate_bar(ax, value, yi, suffix)

    ax.set_title(title, fontsize=PANEL_TITLE_SIZE, fontweight="semibold", pad=5)
    ax.set_xlim(*xlim)
    ax.grid(axis="x", linestyle="--", linewidth=0.55, alpha=0.35, zorder=0)
    ax.set_xlabel(xlabel, fontsize=AXIS_LABEL_SIZE_LOCAL, labelpad=3)
    ax.tick_params(axis="y", length=0, labelsize=ROW_LABEL_SIZE)
    ax.tick_params(axis="x", labelsize=TICK_LABEL_SIZE_LOCAL)


def main():
    set_style()
    values = load_values()

    action_values = [mean_action_gain(values, method) for method in METHODS]
    tgrip_values = [mean_tgrip_gain(values, method) for method in METHODS]
    y = np.arange(len(METHODS))

    fig, axes = plt.subplots(
        1,
        2,
        figsize=(5.25, 2.8),
        sharey=True,
        gridspec_kw={"width_ratios": [1.18, 1.0], "wspace": 0.12},
    )

    draw_panel(
        axes[0],
        y,
        action_values,
        "Action prediction gain",
        "mean L1 reduction (%)",
        (-1.0, 13.4),
        "%",
    )
    draw_panel(
        axes[1],
        y,
        tgrip_values,
        "Transition gripper gain",
        "TGripF1 gain (pts)",
        (-0.65, 4.35),
        "",
    )

    axes[0].set_yticks(y)
    axes[0].set_yticklabels(METHODS, fontsize=ROW_LABEL_SIZE)
    axes[1].set_yticks(y)
    axes[1].tick_params(axis="y", labelleft=False)
    axes[0].invert_yaxis()

    fig.subplots_adjust(left=0.245, right=0.985, top=0.84, bottom=0.22)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for ext in ("pdf", "png"):
        out = OUT_DIR / f"{OUT_NAME}.{ext}"
        fig.savefig(out, dpi=300, bbox_inches="tight")
        print(out)


if __name__ == "__main__":
    main()
