"""Chart tokens and plotly styling. Presentation only: no business formulas live here.

Palette: the validated reference palette (categorical order fixed, light and dark steps selected
separately, status colors reserved for good/warning/critical). Color follows the entity, never its rank.
"""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'

LIGHT = {
    "ink": "#0b0b0b", "ink2": "#52514e", "muted": "#898781", "grid": "#e1e0d9", "axis": "#c3c2b7",
    "neutral": "#c3c2b7", "shade": "rgba(137,135,129,0.12)",
    "series": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"],
}
DARK = {
    "ink": "#f0efec", "ink2": "#c3c2b7", "muted": "#898781", "grid": "#2c2c2a", "axis": "#383835",
    "neutral": "#52514e", "shade": "rgba(137,135,129,0.18)",
    "series": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
}
# Status palette: only where the color *means* good / bad, always shown with an icon + label.
STATUS = {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"}
TIER_STATUS = {"healthy": "good", "watch": "warning", "critical": "critical", "insufficient_data": "serious"}
TIER_ICON = {"healthy": "✅", "watch": "⚠️", "critical": "⛔", "insufficient_data": "❔"}
# Ordinal blue ramp (steps 250 → 600): valid on both surfaces, for ordered categories such as cohorts.
ORDINAL_BLUE = ["#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95"]

# Fixed entity → slot assignments (identity never depends on rank or filter).
ENTITY_ORDER = {
    "payment_method": ["debit_card", "cash"],
    "corridor": ["MX", "GT", "HN", "SV", "DO", "CO"],
    "lifecycle_status": ["new", "recurring", "returning", "at_risk", "churned"],
    "cluster_type": ["individual", "household", "high_fan_in"],
    "failure_reason": ["invalid_account", "provider_timeout", "beneficiary_name_mismatch",
                       "insufficient_provider_liquidity", "compliance_hold"],
}
LABELS = {
    "debit_card": "Debit card", "cash": "Cash", "at_risk": "At risk", "high_fan_in": "High fan-in",
    "new": "New", "recurring": "Recurring", "returning": "Returning", "churned": "Churned",
    "individual": "Individual", "household": "Household",
}


def tokens() -> dict:
    theme_type = getattr(getattr(st.context, "theme", None), "type", None)
    return DARK if theme_type == "dark" else LIGHT


def label(value: object) -> str:
    return LABELS.get(str(value), str(value).replace("_", " ").capitalize())


def color_map(kind: str) -> dict[str, str]:
    series = tokens()["series"]
    return {entity: series[i] for i, entity in enumerate(ENTITY_ORDER[kind])}


def style(fig: go.Figure, *, y_format: str | None = None, x_format: str | None = None, height: int = 320,
          legend: bool = True, label_headroom: bool = False) -> go.Figure:
    t = tokens()
    fig.update_layout(
        height=height,
        margin={"l": 12, "r": 16, "t": 40 if legend else 16, "b": 12},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": FONT, "color": t["ink2"], "size": 12},
        hoverlabel={"font": {"family": FONT}},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0, "title": None,
                "font": {"color": t["ink2"]}},
        showlegend=legend,
        barcornerradius=4,
        bargap=0.25,
        bargroupgap=0.08,
    )
    axis = {"gridcolor": t["grid"], "linecolor": t["axis"], "zerolinecolor": t["axis"], "tickfont": {"color": t["muted"]},
            "title": {"font": {"color": t["ink2"]}}, "showline": True, "gridwidth": 1, "automargin": True}
    fig.update_xaxes(**axis, showgrid=False, tickformat=x_format)
    fig.update_yaxes(**axis, showgrid=True, tickformat=y_format, rangemode="tozero")
    fig.update_traces(selector={"type": "scatter"}, line={"width": 2}, marker={"size": 8})
    fig.update_traces(selector={"type": "bar"}, marker_line_width=0)
    if label_headroom:  # room for labels drawn outside horizontal bar ends
        top = max((max(tr.x) for tr in fig.data if tr.type == "bar" and tr.x is not None and len(tr.x)), default=None)
        if top:
            fig.update_xaxes(range=[0, float(top) * 1.28])
    return fig
