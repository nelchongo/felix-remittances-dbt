"""Shared page pieces: header, the filter row, KPI tiles, chart + table-view pairs."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.db import load
from dashboard.theme import style
from scripts.render_answers import fmt_money

ALL = "All"


def page_header(title: str, subtitle: str) -> None:
    st.title(title)
    st.caption(subtitle + " Every number is a MetricFlow saved query (`dbt/models/semantic/`), compiled to SQL.")


@dataclass
class Filters:
    start: pd.Timestamp
    end: pd.Timestamp
    method: str
    corridor: str

    def months(self, df: pd.DataFrame, column: str = "metric_time__month") -> pd.DataFrame:
        return df[(df[column] >= self.start) & (df[column] <= self.end)]


def filter_row(method: bool = True, corridor: bool = True, note: str = "") -> Filters:
    """One filter row above everything it scopes. Values persist across pages in session_state."""
    months = list(load("dash_overview_monthly")["metric_time__month"])
    state = st.session_state
    default = (months[max(0, len(months) - 12)], months[-1])
    start, end = state.get("filter_range", default)
    start, end = (start if start in months else default[0]), (end if end in months else default[1])
    cols = st.columns([3, 1, 1])
    with cols[0]:
        rng = st.select_slider("Months", options=months, value=(start, end), format_func=lambda m: m.strftime("%Y-%m"))
    state["filter_range"] = rng
    methods = [ALL, "debit_card", "cash"]
    corridors = [ALL, "MX", "GT", "HN", "SV", "DO", "CO"]
    with cols[1]:
        m = st.selectbox("Payment method", methods, index=methods.index(state.get("filter_method", ALL)),
                         disabled=not method, format_func=lambda v: v.replace("_", " "))
    with cols[2]:
        c = st.selectbox("Corridor", corridors, index=corridors.index(state.get("filter_corridor", ALL)),
                         disabled=not corridor)
    state["filter_method"], state["filter_corridor"] = m, c
    if note:
        st.caption(note)
    return Filters(rng[0], rng[1], m, c)


def growth(value: float) -> str:
    return "–" if value is None or pd.isna(value) else f"{value * 100:+.1f}%"


def compact_money(value: float) -> str:
    """Tile-sized money: $1.8M, $286.0K, $2,220, $4.87."""
    sign = "-" if value < 0 else ""
    if abs(value) >= 1e6:
        return f"{sign}${abs(value) / 1e6:,.1f}M"
    if abs(value) >= 1e4:
        return f"{sign}${abs(value) / 1e3:,.1f}K"
    return fmt_money(value)


def kpi(column, title: str, value: float, kind: str, mom: float | None, yoy: float | None, help_text: str) -> None:
    if value is None or pd.isna(value):
        shown = "–"
    elif kind == "money":
        shown = compact_money(value)
    elif kind == "percent":
        shown = f"{value * 100:.2f}%"
    else:
        shown = f"{int(value):,}"
    with column:
        has_mom = mom is not None and not pd.isna(mom)
        yoy_text = f"{growth(yoy)} Y/Y"
        if has_mom:
            st.metric(title, shown, delta=growth(mom), delta_description=f"M/M · {yoy_text}", help=help_text, border=True)
        else:
            st.metric(title, shown, delta=None if yoy is None or pd.isna(yoy) else growth(yoy),
                      delta_description="Y/Y" if yoy is not None and not pd.isna(yoy) else None,
                      help=help_text, border=True)


def chart(fig: go.Figure, table: pd.DataFrame, *, key: str, **style_kwargs) -> None:
    """A chart and its table-view twin (values never only in a tooltip)."""
    st.plotly_chart(style(fig, **style_kwargs), theme=None, key=key, config={"displayModeBar": False})
    with st.expander("Table view"):
        st.dataframe(table, hide_index=True)
