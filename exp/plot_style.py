"""Shared plotting style for paper experiment figures."""

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib import font_manager


_PREFERRED_FONT_FILES = [
    "/usr/share/fonts/opentype/urw-base35/NimbusRoman-Regular.otf",
    "/usr/share/fonts/opentype/urw-base35/NimbusRoman-Bold.otf",
    "/usr/share/fonts/opentype/urw-base35/NimbusRoman-Italic.otf",
    "/usr/share/fonts/opentype/urw-base35/NimbusRoman-BoldItalic.otf",
    "/usr/share/texmf/fonts/opentype/public/tex-gyre/texgyretermes-regular.otf",
    "/usr/share/texmf/fonts/opentype/public/tex-gyre/texgyretermes-bold.otf",
]

FONT_SERIF = ["Nimbus Roman", "TeX Gyre Termes", "Times New Roman", "Times", "DejaVu Serif"]

BASE_FONT_SIZE = 8.6
AXIS_LABEL_SIZE = 8.8
AXIS_TITLE_SIZE = 9.0
LEGEND_FONT_SIZE = 7.8
TICK_LABEL_SIZE = 8.0
ANNOTATION_SIZE = 7.0
DENSE_ANNOTATION_SIZE = 6.8
NOTE_FONT_SIZE = 7.2

AXIS_LINEWIDTH = 0.8
GRID_LINEWIDTH = 0.5
HATCH_LINEWIDTH = 0.75

PAPER_STYLE = {
    "font.family": "serif",
    "font.serif": FONT_SERIF,
    "font.size": BASE_FONT_SIZE,
    "axes.labelsize": AXIS_LABEL_SIZE,
    "axes.titlesize": AXIS_TITLE_SIZE,
    "legend.fontsize": LEGEND_FONT_SIZE,
    "xtick.labelsize": TICK_LABEL_SIZE,
    "ytick.labelsize": TICK_LABEL_SIZE,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.linewidth": AXIS_LINEWIDTH,
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
}


def _register_preferred_fonts() -> None:
    for path in _PREFERRED_FONT_FILES:
        if Path(path).exists():
            font_manager.fontManager.addfont(path)


def apply_paper_style(extra: dict | None = None) -> None:
    """Apply the shared LaTeX-paper plotting style."""
    _register_preferred_fonts()
    style = dict(PAPER_STYLE)
    if extra:
        style.update(extra)
    plt.rcParams.update(style)
