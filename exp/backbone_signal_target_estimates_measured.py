import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from plot_style import apply_paper_style


OUT_DIR = Path(__file__).resolve().parent
OUT_NAME = "backbone_signal_target_estimates_measured"
DATA_FILE = OUT_DIR / f"{OUT_NAME}.json"

DATASETS = ["LIBERO", "CALVIN"]
BACKBONES = ["Octo", "OpenVLA", "RoboFlamingo"]
VARIANTS = ["+Clock", "+LaDyP"]
METRICS = ["NormL1", "TransL1", "GripF1", "TGripF1"]

SHORT_DATASET = {"LIBERO": "LIB", "CALVIN": "CAL"}
SHORT_BACKBONE = {"Octo": "Octo", "OpenVLA": "Open", "RoboFlamingo": "RF"}

COLORS = {
    "+Clock": "#E69F00",
    "+LaDyP": "#0072B2",
}
HATCHES = {
    "+Clock": "xxx",
    "+LaDyP": "///",
}

PANEL_TITLE_SIZE = 14.0
AXIS_LABEL_SIZE_LOCAL = 13.2
TICK_LABEL_SIZE_LOCAL = 11.0
LEGEND_SIZE_LOCAL = 11.4
VALUE_LABEL_SIZE = 9.0


def set_style():
    apply_paper_style(
        {
            "font.size": 11.4,
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


def load_records():
    payload = json.loads(DATA_FILE.read_text())
    records = {}
    for item in payload["records"]:
        key = (item["dataset"], item["backbone"], item["variant"])
        records[key] = item["metrics"]
    return records


def group_labels():
    labels = []
    groups = []
    for dataset in DATASETS:
        for backbone in BACKBONES:
            labels.append(f"{SHORT_DATASET[dataset]}\n{SHORT_BACKBONE[backbone]}")
            groups.append((dataset, backbone))
    return labels, groups


def improvement(records, dataset, backbone, variant, metric):
    base = records[(dataset, backbone, "base")][metric]["mean"]
    value = records[(dataset, backbone, variant)][metric]["mean"]
    if metric.endswith("L1"):
        return (base - value) / base * 100.0
    return value - base


def panel_ylabel(metric):
    if metric.endswith("L1"):
        return "reduction vs. base (%)"
    return "gain vs. base (pts)"


def panel_ylim(values, metric):
    ymax = float(np.nanmax(values))
    upper = ymax + (2.3 if metric.endswith("L1") else 1.0)
    return 0.0, upper


def draw_panel(ax, records, metric, title, show_ylabel=True):
    labels, groups = group_labels()
    x = np.arange(len(groups), dtype=float)
    width = 0.32
    offsets = [-width / 1.8, width / 1.8]

    values = np.array(
        [
            [improvement(records, dataset, backbone, variant, metric) for dataset, backbone in groups]
            for variant in VARIANTS
        ]
    )
    ymin, ymax = panel_ylim(values, metric)

    for j, variant in enumerate(VARIANTS):
        bars = ax.bar(
            x + offsets[j],
            values[j],
            width,
            label=variant.replace("+", ""),
            color=COLORS[variant],
            edgecolor="#111827",
            linewidth=0.55,
            hatch=HATCHES[variant],
            alpha=0.92,
            zorder=3,
        )
        for bar, value in zip(bars, values[j]):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                value + ymax * 0.025,
                f"{value:.1f}",
                ha="center",
                va="bottom",
                fontsize=VALUE_LABEL_SIZE,
                color="#111827",
                rotation=0,
                zorder=5,
            )

    ax.axvline(2.5, color="#9CA3AF", linewidth=0.75, linestyle=":", zorder=1)

    ax.set_title(title, fontsize=PANEL_TITLE_SIZE, fontweight="normal", pad=4)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylim(ymin, ymax)
    if show_ylabel:
        ax.set_ylabel(panel_ylabel(metric), fontsize=AXIS_LABEL_SIZE_LOCAL, labelpad=4)
    ax.grid(axis="y", zorder=0)
    ax.grid(axis="x", visible=False)
    ax.tick_params(axis="x", length=0, labelsize=TICK_LABEL_SIZE_LOCAL, pad=2)
    ax.tick_params(axis="y", labelsize=TICK_LABEL_SIZE_LOCAL)


def main():
    set_style()
    records = load_records()

    fig, axes = plt.subplots(2, 2, figsize=(7.15, 4.25), sharex=False)
    titles = [
        "(a) NormL1",
        "(b) TransL1",
        "(c) GripF1",
        "(d) TGripF1",
    ]
    for ax, metric, title in zip(axes.flat, METRICS, titles, strict=False):
        draw_panel(ax, records, metric, title, show_ylabel=ax in axes[:, 0])

    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        ncol=2,
        frameon=False,
        loc="upper center",
        bbox_to_anchor=(0.52, 1.025),
        handlelength=1.45,
        columnspacing=1.2,
        handletextpad=0.45,
        fontsize=LEGEND_SIZE_LOCAL,
    )
    fig.subplots_adjust(left=0.075, right=0.995, top=0.865, bottom=0.135, wspace=0.15, hspace=0.62)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for ext in ("pdf", "png"):
        out = OUT_DIR / f"{OUT_NAME}.{ext}"
        fig.savefig(out, dpi=300, bbox_inches="tight")
        print(out)


if __name__ == "__main__":
    main()
