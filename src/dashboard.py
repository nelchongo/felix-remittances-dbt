"""Félix remittances dashboard: the answers to the brief, one tab per question, in the Félix Pago brand.

`python run.py` starts it in the background (or `python run.py dashboard` in the foreground).

It shows the same saved queries as docs/answers.md. `python run.py compile-metrics` writes the SQL MetricFlow
generates for them to warehouse/compiled/, and this app runs that SQL on a short-lived read-only DuckDB
connection: no formulas live here (plotly only draws) and `dbt build` can run while the app is open.
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
from pathlib import Path

import duckdb
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.brand import CHARTS, CYAN, FAVICON, LINEN, LOGO_ON_DARK, SLATE
from src.render_answers import fmt_money, trim_empty_months

DB = Path(os.environ.get("DUCKDB_PATH", ROOT / "warehouse" / "felix.duckdb"))
COMPILED = ROOT / "warehouse" / "compiled"
MANIFEST = ROOT / "dbt" / "target" / "semantic_manifest.json"
DBT_MANIFEST = ROOT / "dbt" / "target" / "manifest.json"
MARTS = ["finance", "operations", "growth", "risk"]
DIM_ORDER = ["date", "users", "beneficiaries", "payment_methods", "payment_processors", "funding_institutions",
             "payout_providers", "corridors"]  # most shared first; any other core dimension follows

# Status colors are reserved for the good / bad tiers (never a series), always with an icon and a label.
TIER_COLOR = {"healthy": "#0ca30c", "watch": "#fab219", "critical": "#d03b3b", "insufficient_data": "#ec835a"}
TIER_ICON = {"healthy": "✅", "watch": "⚠️", "critical": "⛔", "insufficient_data": "❔"}
METHOD = {"debit_card": "Debit card", "cash": "Cash"}


def mode() -> str:
    return "dark" if getattr(getattr(st.context, "theme", None), "type", None) == "dark" else "light"


def colors() -> dict:
    return CHARTS[mode()]


# --------------------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def saved_query(name: str, warehouse_version: float) -> pd.DataFrame:
    """Cached per warehouse version (the file's modification time), so a refresh after a build shows new data."""
    sql = COMPILED / f"{name}.sql"
    if not DB.exists() or not sql.exists():
        raise FileNotFoundError("No data yet. In the terminal, run `python run.py` and choose 1 (Run the dbt sequence).")
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
        return saved_query(name, DB.stat().st_mtime if DB.exists() else 0.0)
    except FileNotFoundError as exc:
        st.info(str(exc), icon="ℹ️")
        st.stop()


@st.cache_data(ttl=300, show_spinner=False)
def descriptions() -> dict[str, str]:
    if not MANIFEST.exists():
        return {}
    return {q["name"]: q.get("description", "") for q in json.loads(MANIFEST.read_text())["saved_queries"]}


@st.cache_data(show_spinner=False)
def data_model(manifest_version: float) -> tuple[pd.DataFrame, dict]:
    """The bus matrix, read from dbt's manifest: a ✔ is a `relationships` test from a mart model's key to a core
    dimension, so the page always matches the model. Returns the matrix and {model: (mart, dims)} for the diagram."""
    nodes = json.loads(DBT_MANIFEST.read_text(encoding="utf-8"))["nodes"]
    models = {n["name"]: n for n in nodes.values() if n["resource_type"] == "model"}
    dims = sorted((name for name, n in models.items() if n["schema"] == "core" and name.startswith("dim_")),
                  key=lambda d: (DIM_ORDER.index(d[4:]) if d[4:] in DIM_ORDER else len(DIM_ORDER), d))
    links: dict[str, dict[str, list[str]]] = {}
    for test in nodes.values():
        meta = test.get("test_metadata") or {}
        if test["resource_type"] != "test" or meta.get("name") != "relationships":
            continue
        source = nodes.get(test.get("attached_node") or "", {}).get("name", "")
        target = re.search(r"ref\('(\w+)'\)", str(meta.get("kwargs", {}).get("to", "")))
        if source in models and models[source]["schema"] in MARTS and target and target[1] in dims:
            links.setdefault(source, {}).setdefault(target[1], []).append(test.get("column_name") or "")
    rows, graph = [], {}
    for name in sorted(links, key=lambda n: (MARTS.index(models[n]["schema"]), n)):
        node_meta = models[name]["config"].get("meta", {})
        row = {"mart": models[name]["schema"], "fact": name}
        for dim in dims:
            keys = links[name].get(dim, [])
            row[dim.removeprefix("dim_")] = ("✔" * len(keys)) if keys else ""
        rows.append(row)
        graph[name] = (models[name]["schema"], sorted(links[name]), node_meta.get("kimball_fact_type", ""),
                       node_meta.get("grain", ""))
    matrix = pd.DataFrame(rows)
    shared = {"mart": "", "fact": "shared by"}
    shared |= {d.removeprefix("dim_"): f"{(matrix[d.removeprefix('dim_')] != '').sum()} facts" for d in dims}
    return pd.concat([matrix, pd.DataFrame([shared])], ignore_index=True), graph


def star_diagram(graph: dict) -> str:
    """Graphviz DOT: one cluster per mart on the left, the conformed dimensions in core on the right."""
    graph = {name: (mart, dims) for name, (mart, dims, *_) in graph.items()}
    c, ink = colors(), "#fefcf9" if mode() == "dark" else "#082422"
    lines = ['digraph { rankdir=LR; bgcolor="transparent"; nodesep=0.12; ranksep=1.6; size="9,5.5";',
             f'node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=11, color="{c["axis"]}"];',
             f'edge [color="{c["axis"]}", arrowsize=0.5]; fontname="Helvetica"; fontcolor="{ink}";']
    for mart in MARTS:
        members = [name for name, (m, _) in graph.items() if m == mart]
        lines.append(f'subgraph cluster_{mart} {{ label="{mart}"; color="{c["axis"]}"; style="rounded";')
        lines += [f'"{name}" [fillcolor="{c["series"][0]}", fontcolor="white"];' for name in members]
        lines.append("}")
    dims = sorted({d for _, (_, ds) in graph.items() for d in ds})
    lines.append(f'subgraph cluster_core {{ label="core · conformed dimensions"; color="{c["axis"]}"; style="rounded";')
    lines += [f'"{d}" [fillcolor="{c["neutral"]}", fontcolor="{ink if mode() == "dark" else "#082422"}"];' for d in dims]
    lines.append("}")
    lines += [f'"{name}" -> "{d}";' for name, (_, ds) in graph.items() for d in ds]
    return "\n".join(lines + ["}"])


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
def hero() -> None:
    """Brand header: the linen wordmark on a slate band with a cyan rule, as on felixpago.com."""
    logo = base64.b64encode(LOGO_ON_DARK.read_bytes()).decode()
    border = f"border:1px solid {CYAN};" if mode() == "dark" else ""
    st.markdown(
        f"""<div style="background:{SLATE};{border}border-radius:16px;padding:20px 24px;display:flex;
        align-items:center;gap:20px;flex-wrap:wrap;margin-bottom:8px">
          <img src="data:image/svg+xml;base64,{logo}" alt="Félix Pago" style="height:32px">
          <div style="border-left:3px solid {CYAN};padding-left:16px;color:{LINEN}">
            <div style="font-size:1.4rem;font-weight:700;line-height:1.25">Remittances analytics</div>
            <div style="font-size:0.85rem;opacity:0.75">Take-home prototype on synthetic data · every number is a
            MetricFlow saved query, the same ones behind docs/answers.md</div>
          </div>
        </div>""",
        unsafe_allow_html=True,
    )


st.set_page_config(page_title="Félix Pago · Remittances analytics", page_icon=str(FAVICON), layout="wide")
hero()
c = colors()
tabs = st.tabs(["Q1 Volume", "Q2 Top 50%", "Q3 Recurring", "Q4 Providers", "Q5 Clusters", "Q6 Chargebacks",
                "Q7 Ticket", "Q8 LTV", "Growth", "Pay-in", "Data model"])

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
    ramp = c["ordinal"]  # one hue, oldest → newest cohort (most emphasis)
    quarterly = sorted(m for m in curve["cohort"].unique() if m[5:7] in {"01", "04", "07", "10"})[-len(ramp):]
    curve = curve[curve["cohort"].isin(quarterly)]
    fig = px.line(curve, x="customer_month__months_since_first_transfer", y="ltv_per_cohort_user", color="cohort",
                  color_discrete_sequence=ramp[-len(quarterly):], category_orders={"cohort": quarterly})
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

with tabs[10]:
    st.caption("Kimball data marts by business process. Facts store additive ingredients; they share the conformed "
               "dimensions in `core`, so metrics from different marts can be compared by the same user, date, "
               "corridor or provider (drill-across). Read from dbt's manifest, so it always matches the model.")
    if not DBT_MANIFEST.exists():
        st.info("No dbt manifest yet. In the terminal, run `python run.py` and choose 1 (Run sequentially).", icon="ℹ️")
        st.stop()
    matrix, graph = data_model(DBT_MANIFEST.stat().st_mtime)
    st.markdown("**Star schemas: facts per mart → conformed dimensions**")
    st.graphviz_chart(star_diagram(graph), use_container_width=False)
    st.markdown("**Bus matrix: which dimensions each fact can be sliced by**")
    st.dataframe(matrix, hide_index=True, use_container_width=True)
    st.markdown("**Facts: Kimball type and grain**")
    st.dataframe(pd.DataFrame([{"fact": name, "mart": mart, "type": kind, "grain": grain}
                               for name, (mart, _, kind, grain) in graph.items()]), hide_index=True)
    st.caption("✔ one foreign key to the dimension · ✔✔ role-playing (two keys, e.g. payment date and chargeback "
               "date) · `users` and `beneficiaries` are SCD2: facts join the version valid at the event time. "
               "A dimension shared by several facts is the bridge between marts.")

