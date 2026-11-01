"""Félix remittances dashboard: the answers to the brief, one tab per question.  `python run.py dashboard`

It shows the same saved queries as docs/answers.md. `python run.py compile-metrics` writes the SQL MetricFlow
generates for them to dashboard/compiled/, and this app runs that SQL on a short-lived read-only DuckDB
connection: no formulas live here (plotly only draws) and `dbt build` can run while the app is open.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import duckdb
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.render_answers import fmt_money, trim_empty_months

DB = Path(os.environ.get("DUCKDB_PATH", ROOT / "warehouse" / "felix.duckdb"))
COMPILED = ROOT / "dashboard" / "compiled"
MANIFEST = ROOT / "dbt" / "target" / "semantic_manifest.json"

# Validated reference palette (fixed order, light / dark steps). Status colors only for good / bad tiers.
PALETTE = {
    "light": {"series": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"], "neutral": "#c3c2b7",
              "grid": "#e1e0d9", "axis": "#c3c2b7", "ink": "#52514e", "shade": "rgba(137,135,129,0.12)"},
    "dark": {"series": ["#3987e5", "#d95926", "#199e70", "#c98500"], "neutral": "#52514e",
             "grid": "#2c2c2a", "axis": "#383835", "ink": "#c3c2b7", "shade": "rgba(137,135,129,0.18)"},
}
TIER_COLOR = {"healthy": "#0ca30c", "watch": "#fab219", "critical": "#d03b3b", "insufficient_data": "#ec835a"}
TIER_ICON = {"healthy": "✅", "watch": "⚠️", "critical": "⛔", "insufficient_data": "❔"}
ORDINAL_BLUE = ["#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95"]
METHOD = {"debit_card": "Debit card", "cash": "Cash"}


def colors() -> dict:
    theme = getattr(getattr(st.context, "theme", None), "type", None)
    return PALETTE["dark" if theme == "dark" else "light"]


# --------------------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------------------
@st.cache_data(ttl=60, show_spinner=False)
def saved_query(name: str) -> pd.DataFrame:
    sql = COMPILED / f"{name}.sql"
    if not DB.exists() or not sql.exists():
        raise FileNotFoundError("Run `python run.py all` first (it builds the warehouse and compiles the SQL).")
    try:
        with duckdb.connect(str(DB), read_only=True) as con:
            df = con.execute(sql.read_text(encoding="utf-8")).fetch_df()
    except duckdb.IOException as exc:
        raise FileNotFoundError("dbt is writing to the warehouse right now. Refresh in a few seconds.") from exc
    if "metric_time__month" in df.columns:
        df["metric_time__month"] = pd.to_datetime(df["metric_time__month"])
        df = trim_empty_months(df)
    return df


def load(name: str) -> pd.DataFrame:
    try:
        return saved_query(name)
    except FileNotFoundError as exc:
        st.info(str(exc), icon="ℹ️")
        st.stop()


@st.cache_data(ttl=60, show_spinner=False)
def descriptions() -> dict[str, str]:
    if not MANIFEST.exists():
        return {}
    return {q["name"]: q.get("description", "") for q in json.loads(MANIFEST.read_text())["saved_queries"]}


# --------------------------------------------------------------------------------------
# Presentation helpers
# --------------------------------------------------------------------------------------
def show(fig: go.Figure, table: pd.DataFrame, *, key: str, y: str | None = None, x: str | None = None,
         legend: bool = False, height: int = 320, headroom: bool = False) -> None:
    """Style a chart (one y-axis, hairline grid) and add its table view."""
    c = colors()
    fig.update_layout(height=height, margin={"l": 12, "r": 16, "t": 40 if legend else 16, "b": 12},
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", showlegend=legend,
                      font={"family": 'system-ui, -apple-system, "Segoe UI", sans-serif', "color": c["ink"]},
                      legend={"orientation": "h", "y": 1.02, "yanchor": "bottom", "x": 0, "title": None},
                      barcornerradius=4, bargap=0.25)
    axis = {"gridcolor": c["grid"], "linecolor": c["axis"], "zerolinecolor": c["axis"], "showline": True,
            "automargin": True, "title": None}
    fig.update_xaxes(**axis, showgrid=False, tickformat=x)
    fig.update_yaxes(**axis, tickformat=y, rangemode="tozero")
    fig.update_traces(selector={"type": "scatter"}, line_width=2, marker_size=8)
    if headroom:  # room for labels drawn outside horizontal bars
        top = max(max(t.x) for t in fig.data if t.type == "bar")
        fig.update_xaxes(range=[0, float(top) * 1.3])
    st.plotly_chart(fig, theme=None, key=key, config={"displayModeBar": False})
    with st.expander("Table view"):
        st.dataframe(table, hide_index=True)


def header(name: str) -> None:
    st.caption(f"{descriptions().get(name, '').strip()} · saved query `{name}`")


def growth(value: float) -> str:
    return "–" if value is None or pd.isna(value) else f"{value * 100:+.1f}%"


def tile(column, title: str, value: str, mom: float | None = None, yoy: float | None = None) -> None:
    delta = growth(mom) if mom is not None and not pd.isna(mom) else None
    note = " · ".join(p for p in [("M/M" if delta else ""), (f"{growth(yoy)} Y/Y" if yoy is not None else "")] if p)
    column.metric(title, value, delta=delta, delta_description=note or None, border=True)


def line(df: pd.DataFrame, y: str, hover: str) -> go.Figure:
    return go.Figure(go.Scatter(x=df["metric_time__month"], y=df[y], mode="lines+markers",
                                line_color=colors()["series"][0], hovertemplate=f"%{{x|%b %Y}}<br>{hover}<extra></extra>"))


def hbar(df: pd.DataFrame, x: str, y: str, hover: str, colors_: list[str] | str | None = None,
         text: list[str] | None = None) -> go.Figure:
    return go.Figure(go.Bar(x=df[x], y=df[y], orientation="h", marker_color=colors_ or colors()["series"][0],
                            text=text, textposition="outside", hovertemplate=f"%{{y}}<br>{hover}<extra></extra>"))


# --------------------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------------------
st.set_page_config(page_title="Félix remittances", page_icon="💸", layout="wide")
st.title("Félix remittances")
st.caption("Every number is a MetricFlow saved query (`dbt/models/semantic/`), the same ones behind `docs/answers.md`.")
c = colors()
tabs = st.tabs(["Q1 Volume", "Q2 Top 50%", "Q3 Recurring", "Q4 Providers", "Q5 Clusters", "Q6 Chargebacks",
                "Q7 Ticket", "Q8 LTV", "Growth", "Pay-in"])

with tabs[0]:
    header("q1_monthly_volume")
    q1 = load("q1_monthly_volume")
    last = q1.iloc[-1]
    st.subheader(f"{last['metric_time__month']:%B %Y}")
    a, b, d = st.columns(3)
    tile(a, "Gross volume", fmt_money(last["gross_volume_usd"]), last["gross_volume_usd_mom_pct"], last["gross_volume_usd_yoy_pct"])
    tile(b, "Transfers", f"{int(last['transfers']):,}")
    tile(d, "Net revenue", fmt_money(last["net_revenue_usd"]))
    left, right = st.columns(2)
    with left:
        st.markdown("**Gross volume by month**")
        fig = go.Figure(go.Bar(x=q1["metric_time__month"], y=q1["gross_volume_usd"], marker_color=c["series"][0],
                               hovertemplate="%{x|%b %Y}<br>$%{y:,.0f}<extra></extra>"))
        show(fig, q1, key="q1_volume", y="$,.0f")
    with right:
        st.markdown("**Growth vs the same month last year**")
        show(line(q1, "gross_volume_usd_yoy_pct", "%{y:+.1%}"), q1, key="q1_yoy", y="+.0%")

with tabs[1]:
    header("q2_volume_concentration")
    q2 = load("q2_volume_concentration")
    left, right = st.columns(2)
    with left:
        st.markdown("**Gross volume by segment**")
        show(hbar(q2, "gross_volume_usd", "user__volume_segment", "$%{x:,.0f}"), q2, key="q2_volume", x="$,.0f")
    with right:
        st.markdown("**Senders by segment**")
        show(hbar(q2, "active_senders", "user__volume_segment", "%{x:,} senders"), q2, key="q2_senders")

with tabs[2]:
    header("q3_recurring_customers")
    q3 = load("q3_recurring_customers")
    left, right = st.columns(2)
    with left:
        st.markdown("**Recurring share of active customers**")
        show(line(q3, "recurring_share", "%{y:.1%}"), q3, key="q3_share", y=".0%")
    with right:
        st.markdown("**Monthly churn rate**")
        show(line(q3, "churn_rate", "%{y:.1%}"), q3, key="q3_churn", y=".0%")

with tabs[3]:
    header("q4_payout_providers")
    q4 = load("q4_payout_providers").sort_values("payout_attempt_failure_rate")
    tiers = q4["payout_provider__reliability_tier"]
    fig = hbar(q4, "payout_attempt_failure_rate", "attempt__provider_name", "%{x:.1%} of attempts failed",
               [TIER_COLOR.get(t, c["neutral"]) for t in tiers],
               [f"{r:.1%} · {TIER_ICON.get(t, '')} {t}" for r, t in zip(q4["payout_attempt_failure_rate"], tiers)])
    show(fig, q4, key="q4_providers", x=".0%", headroom=True, height=380)
    st.caption("Tiers: ✅ healthy < 5% · ⚠️ watch 5–10% · ⛔ critical ≥ 10% of payout attempts failed.")

with tabs[4]:
    header("q5_sender_clusters")
    q5 = load("q5_sender_clusters").set_index("user__cluster_type").reindex(["individual", "household", "high_fan_in"])
    q5 = q5.dropna(how="all").reset_index()
    emphasis = [c["series"][0] if t == "high_fan_in" else c["neutral"] for t in q5["user__cluster_type"]]
    left, right = st.columns(2)
    with left:
        st.markdown("**Senders by cluster type**")
        show(hbar(q5, "senders", "user__cluster_type", "%{x:,} senders", emphasis), q5, key="q5_senders")
    with right:
        st.markdown("**Chargeback rate by cluster type**")
        show(hbar(q5, "chargeback_rate", "user__cluster_type", "%{x:.2%}", emphasis,
                  [f"{v:.1%}" for v in q5["chargeback_rate"]]), q5, key="q5_cb", x=".0%", headroom=True)

with tabs[5]:
    header("q6_chargeback_rate")
    total = load("q6_chargeback_rate_total").iloc[0]
    a, b, _ = st.columns(3)
    tile(a, "Chargeback rate (debit card)", f"{total['chargeback_rate']:.2%}")
    tile(b, "By amount", f"{total['chargeback_rate_amount']:.2%}")
    left, right = st.columns(2)
    with left:
        st.markdown("**By payment month (latest months still maturing)**")
        q6 = load("q6_chargeback_rate")
        fig = line(q6, "chargeback_rate", "%{y:.2%}")
        fig.add_vrect(x0=q6["metric_time__month"].iloc[-3], x1=q6["metric_time__month"].iloc[-1],
                      fillcolor=c["shade"], line_width=0)
        show(fig, q6, key="q6_month", y=".1%")
    with right:
        st.markdown("**By issuing bank**")
        banks = load("q6_chargeback_rate_by_bank").sort_values("chargeback_rate")
        show(hbar(banks, "chargeback_rate", "payment__funding_institution", "%{x:.2%}", None,
                  [f"{v:.1%}" for v in banks["chargeback_rate"]]), banks, key="q6_bank", x=".1%", headroom=True)

with tabs[6]:
    header("q7_transaction_value")
    q7 = load("q7_transaction_value")
    long = q7.melt(id_vars="payment__payment_method", value_vars=["atv_usd", "median_ticket_usd"], var_name="measure")
    long["measure"] = long["measure"].map({"atv_usd": "Average (ATV)", "median_ticket_usd": "Median"})
    long["method"] = long["payment__payment_method"].map(METHOD)
    fig = px.bar(long, x="measure", y="value", color="method", barmode="group", text_auto="$.0f",
                 color_discrete_map={"Debit card": c["series"][0], "Cash": c["series"][1]})
    show(fig, q7, key="q7_ticket", y="$,.0f", legend=True)

with tabs[7]:
    header("q8_ltv")
    ltv = load("q8_ltv").iloc[0]
    projection = load("q8_ltv_projection").dropna(subset=["projected_ltv_12m_usd"])
    a, b, _ = st.columns(3)
    tile(a, "Historical LTV per sender", fmt_money(ltv["historical_ltv_usd"]))
    tile(b, f"Projected 12-month LTV ({projection['metric_time__month'].iloc[-1]:%b %Y})",
         fmt_money(projection["projected_ltv_12m_usd"].iloc[-1]))
    st.markdown("**Net revenue per user by cohort, N months after the first transfer**")
    curve = load("q8_ltv_curve")
    curve["cohort"] = curve["customer_month__cohort_month"].astype(str).str[:7]
    quarterly = sorted(m for m in curve["cohort"].unique() if m[5:7] in {"01", "04", "07", "10"})[-8:]
    curve = curve[curve["cohort"].isin(quarterly)]
    fig = px.line(curve, x="customer_month__months_since_first_transfer", y="ltv_per_cohort_user", color="cohort",
                  color_discrete_sequence=ORDINAL_BLUE[-len(quarterly):], category_orders={"cohort": quarterly})
    show(fig, curve.drop(columns="cohort"), key="q8_curve", y="$,.0f", legend=True)

with tabs[8]:
    header("growth_kpis_monthly")
    g = load("growth_kpis_monthly")
    last = g.iloc[-1]
    a, b, d = st.columns(3)
    tile(a, "Active senders", f"{int(last['active_senders']):,}", None, last["active_senders_yoy_pct"])
    tile(b, "New senders", f"{int(last['new_senders']):,}")
    tile(d, "ARPU", fmt_money(last["arpu_usd"]), last["arpu_usd_mom_pct"], last["arpu_usd_yoy_pct"])
    left, right = st.columns(2)
    with left:
        st.markdown("**Active and new senders**")
        long = g.melt(id_vars="metric_time__month", value_vars=["active_senders", "new_senders"], var_name="series")
        fig = px.line(long, x="metric_time__month", y="value", color="series", markers=True,
                      color_discrete_sequence=c["series"][:2])
        show(fig, g, key="growth_senders", legend=True)
    with right:
        st.markdown("**ARPU by month**")
        fig = go.Figure(go.Bar(x=g["metric_time__month"], y=g["arpu_usd"], marker_color=c["series"][0],
                               hovertemplate="%{x|%b %Y}<br>$%{y:,.2f}<extra></extra>"))
        show(fig, g, key="growth_arpu", y="$,.0f")

with tabs[9]:
    header("payin_performance")
    payin = load("payin_performance")
    left, right = st.columns(2)
    with left:
        st.markdown("**Card decline rate by issuing bank and processor**")
        cards = payin.dropna(subset=["card_decline_rate"]).sort_values("card_decline_rate")
        cards = cards.assign(bank=cards["payment__funding_institution"] + " · " + cards["payment__payment_processor"])
        show(hbar(cards, "card_decline_rate", "bank", "%{x:.1%}"), cards.drop(columns="bank"), key="payin_cards",
             x=".0%", height=440)
    with right:
        st.markdown("**Cash barcode expiry rate by store**")
        cash = payin.dropna(subset=["cash_expiry_rate"]).sort_values("cash_expiry_rate")
        show(hbar(cash, "cash_expiry_rate", "payment__funding_institution", "%{x:.1%}", c["series"][1]), cash,
             key="payin_cash", x=".0%", height=440)
