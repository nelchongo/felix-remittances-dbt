"""Félix Pago brand for the dashboard: logos, Streamlit theme and chart palette.

Tokens come from felixpago.com's public stylesheet (slate, linen, brand cyan, stone, concrete, papaya, blueberry).
Chart colors are those tokens stepped where needed so each palette passes the data-viz checks against its own
background (lightness band, chroma floor, colour-blind and normal-vision separation, 3:1 contrast). The brand
cyan is too light to draw on linen, so light mode uses a deeper step of the same hue (194°); the 6-step cohort
ramps are that hue only, and in dark mode the newest cohort is the brand cyan itself. The fonts (Plain, Saans)
are licensed, so the dashboard keeps the system font.
"""

from __future__ import annotations

import os
from pathlib import Path

ASSETS = Path(__file__).resolve().parent / "assets"
LOGO_ON_DARK = ASSETS / "felix_logo_white.svg"  # linen wordmark (the slate one, felix_logo.svg, is for light surfaces)
FAVICON = ASSETS / "felix_favicon.png"

SLATE, LINEN, CYAN = "#082422", "#fefcf9", "#2bf2f1"
STONE, CONCRETE, EVERGREEN = "#edebe9", "#cfcabf", "#35605f"

# Streamlit theme, one per mode. run.py passes it as `--theme.<mode>.<option>` flags (no config file).
THEME = {
    "light": {"primaryColor": "#028382", "backgroundColor": LINEN, "secondaryBackgroundColor": STONE,
              "textColor": SLATE},
    "dark": {"primaryColor": CYAN, "backgroundColor": SLATE, "secondaryBackgroundColor": "#142e2c",
             "textColor": LINEN},
}

# Chart roles per mode. `series` is the fixed categorical order (teal, papaya, blueberry); `ordinal` runs from
# the oldest cohort to the newest (most emphasis); status colors for good / bad tiers live in the dashboard.
CHARTS = {
    "light": {"series": ["#0d9999", "#f26629", "#6060bf"],
              "ordinal": ["#00bcbb", "#059f9e", "#028382", "#006868", "#024e4e", "#003635"],
              "neutral": CONCRETE, "grid": STONE, "axis": CONCRETE, "ink": "rgba(8,36,34,0.72)",
              "shade": "rgba(207,202,191,0.35)"},
    "dark": {"series": ["#06a7a6", "#e85f22", "#8080d8"],
             "ordinal": ["#036262", "#027d7d", "#059999", "#02b6b6", "#22d4d3", CYAN],
             "neutral": EVERGREEN, "grid": "#213a37", "axis": "#394f4d", "ink": "rgba(254,252,249,0.75)",
             "shade": "rgba(207,202,191,0.12)"},
}


def streamlit_flags() -> list[str]:
    """`streamlit run` flags that apply the brand theme in light and dark mode."""
    return [f"--theme.{mode}.{option}={value}" for mode, options in THEME.items() for option, value in options.items()]


# The wordmark in block letters for the terminal (run.py's menu), with the accent over the é.
_LETTERS = {
    "F": ["███████╗", "██╔════╝", "█████╗  ", "██╔══╝  ", "██║     ", "╚═╝     "],
    "E": ["███████╗", "██╔════╝", "█████╗  ", "██╔══╝  ", "███████╗", "╚══════╝"],
    "L": ["██╗     ", "██║     ", "██║     ", "██║     ", "███████╗", "╚══════╝"],
    "I": ["██╗", "██║", "██║", "██║", "██║", "╚═╝"],
    "X": ["██╗  ██╗", "╚██╗██╔╝", " ╚███╔╝ ", " ██╔██╗ ", "██╔╝ ██╗", "╚═╝  ╚═╝"],
}


def terminal_logo(color: bool = True) -> str:
    rows = ["".join(_LETTERS[letter][row] for letter in "FELIX") for row in range(6)]
    accent = " " * (len(_LETTERS["F"][0]) + 3) + "▄█▀"
    lines = [accent, *rows]
    if not color:
        return "\n".join(f"  {line}" for line in lines)
    truecolor = os.environ.get("COLORTERM", "") in ("truecolor", "24bit")
    red, green, blue = (int(CYAN[i:i + 2], 16) for i in (1, 3, 5))
    paint = f"\x1b[1;38;2;{red};{green};{blue}m" if truecolor else "\x1b[1;96m"
    return "\n".join(f"  {paint}{line}\x1b[0m" for line in lines)
