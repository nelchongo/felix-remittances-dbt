"""Félix remittances dashboard. Run with `python run.py dashboard`.

Entry point and router (st.navigation). The Overview page lives here; the other pages are in pages/.
Business formulas come only from the semantic layer: every figure is a MetricFlow saved query compiled
to SQL (`python run.py compile-metrics`); plotly and pandas only select rows and draw.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root, for `dashboard.*` and `scripts.*`

import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from dashboard.components import ALL, chart, filter_row, kpi, page_header  # noqa: E402
from dashboard.db import load  # noqa: E402
from dashboard.theme import tokens  # noqa: E402

OVERVIEW_QUERY = {
    (False, False): "dash_overview_monthly",
    (True, False): "dash_overview_by_method_monthly",
    (False, True): "dash_overview_by_corridor_monthly",
    (True, True): "dash_overview_by_method_corridor_monthly",
}


def overview() -> None:
    page_header("Overview", "Monthly KPIs with month-over-month and year-over-year change.")
    f = filter_row(note="Tiles show the last month of the range. Filters pick the saved query computed at that grain.")
    df = load(OVERVIEW_QUERY[(f.method != ALL, f.corridor != ALL)])
    if f.method != ALL:
        df = df[df["payment__payment_method"] == f.method]
    if f.corridor != ALL:
        df = df[df["payment__corridor"] == f.corridor]
    df = f.months(df).sort_values("metric_time__month")
    if df.empty:
        st.info("No activity for this selection.")
        return
    last = df.iloc[-1]
    st.subheader(f"{last['metric_time__month']:%B %Y}")
    tiles = [
        ("Gross volume", "gross_volume_usd", "money", "Σ principal of succeeded payments (Q1)."),
        ("Net revenue", "net_revenue_usd", "money", "Fees + FX revenue − chargeback losses."),
        ("Active senders", "active_senders", "count", "Distinct senders with a succeeded transfer in the month."),
        ("ARPU", "arpu_usd", "money", "Net revenue ÷ active senders."),
        ("ATV", "atv_usd", "money", "Average transaction value: gross volume ÷ transfers (Q7)."),
        ("Take rate", "take_rate", "percent", "Net revenue ÷ gross volume."),
    ]
    columns = [*st.columns(3), *st.columns(3)]
    for column, (title, metric, kind, help_text) in zip(columns, tiles):
        kpi(column, title, last[metric], kind, last.get(f"{metric}_mom_pct"), last.get(f"{metric}_yoy_pct"), help_text)

    blue = tokens()["series"][0]
    months = df["metric_time__month"]
    left, right = st.columns(2)
    with left:
        st.markdown("**Gross volume by month**")
        fig = go.Figure(go.Bar(x=months, y=df["gross_volume_usd"], marker_color=blue, name="Gross volume",
                               hovertemplate="%{x|%b %Y}<br>$%{y:,.0f}<extra></extra>"))
        chart(fig, df[["metric_time__month", "gross_volume_usd", "transfers"]], key="ov_volume",
              y_format="$,.0f", legend=False)
    with right:
        st.markdown("**Volume growth vs the same month last year**")
        fig = go.Figure(go.Scatter(x=months, y=df["gross_volume_usd_yoy_pct"], mode="lines+markers", line_color=blue,
                                   name="Y/Y", hovertemplate="%{x|%b %Y}<br>%{y:+.1%}<extra></extra>"))
        chart(fig, df[["metric_time__month", "gross_volume_usd_yoy_pct", "gross_volume_usd_mom_pct"]], key="ov_yoy",
              y_format="+.0%", legend=False)


if __name__ == "__main__":
    st.set_page_config(page_title="Félix remittances", page_icon="💸", layout="wide")
    navigation = st.navigation([
        st.Page(overview, title="Overview", icon="📊", default=True),
        st.Page("pages/1_Finance.py", title="Finance", icon="💵"),
        st.Page("pages/2_Operations.py", title="Operations", icon="🚚"),
        st.Page("pages/3_Growth.py", title="Growth", icon="📈"),
        st.Page("pages/4_Risk.py", title="Risk", icon="🛡️"),
    ])
    navigation.run()
