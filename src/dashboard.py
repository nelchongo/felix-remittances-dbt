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
import streamlit.components.v1 as components

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.brand import (
    CHART,
    CYAN,
    FAVICON,
    HEADING_FONT,
    LINEN,
    LOGO_ON_DARK,
    SLATE,
    TEXT_FONT,
)
from src.render_answers import fmt_money, trim_empty_months

DB = Path(os.environ.get("DUCKDB_PATH", ROOT / "warehouse" / "felix.duckdb"))
COMPILED = ROOT / "warehouse" / "compiled"
MANIFEST = ROOT / "dbt" / "target" / "semantic_manifest.json"
DBT_MANIFEST = ROOT / "dbt" / "target" / "manifest.json"
DOCS_SITE = ROOT / "dbt" / "target" / "static_index.html"  # `python run.py docs` (dbt docs generate --static)
LAYERS = {"source": "Source (raw)", "staging": "Staging", "intermediate": "Intermediate", "snapshot": "Snapshots",
          "core": "Core dimensions", "marts": "Marts"}
MARTS = ["finance", "operations", "growth", "risk"]
DIM_ORDER = ["date", "users", "beneficiaries", "payment_methods", "payment_processors", "funding_institutions",
             "payout_providers", "corridors"]  # most shared first; any other core dimension follows

# Status colors are reserved for the good / bad tiers (never a series), always with an icon and a label.
TIER_COLOR = {"healthy": "#0ca30c", "watch": "#fab219", "critical": "#d03b3b", "insufficient_data": "#ec835a"}
TIER_ICON = {"healthy": "✅", "watch": "⚠️", "critical": "⛔", "insufficient_data": "❔"}
METHOD = {"debit_card": "Debit card", "cash": "Cash"}
SEGMENT = {"top_50pct": "Top 50% of volume", "middle_30pct": "Middle 30%", "tail_20pct": "Tail 20%"}
CLUSTER = {"individual": "Individual", "household": "Household", "high_fan_in": "High fan-in"}


def colors() -> dict:
    return CHART


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


@st.cache_data(show_spinner=False)
def catalog(manifest_version: float) -> dict[str, dict]:
    """Every source, model and snapshot from dbt's manifest: layer, description, metadata, columns and lineage."""
    manifest = json.loads(DBT_MANIFEST.read_text(encoding="utf-8"))
    entries: dict[str, dict] = {}
    for uid, node in {**manifest["nodes"], **manifest["sources"]}.items():
        kind = node["resource_type"]
        if kind not in ("model", "snapshot", "source"):
            continue
        layer = "source" if kind == "source" else next((t for t in node.get("tags", []) if t in LAYERS), "")
        meta = node.get("config", {}).get("meta", {}) or node.get("meta", {})
        entries[uid] = {
            "name": f"raw.{node['name']}" if kind == "source" else node["name"],
            "layer": layer, "kind": kind, "schema": node.get("schema", ""),
            "materialized": "table (loaded by src/load_raw.py)" if kind == "source" else node["config"].get("materialized", ""),
            "description": node.get("description", "").strip(),
            "owner": meta.get("owner", ""), "grain": meta.get("grain", ""),
            "columns": [{"column": c["name"], "type": c.get("data_type") or "", "description": c.get("description", "")}
                        for c in node.get("columns", {}).values()],
            "parents": [u for u in node.get("depends_on", {}).get("nodes", []) if u.split(".")[0] in ("model", "snapshot", "source")],
        }
    for uid, entry in entries.items():
        entry["children"] = [other for other, e in entries.items() if uid in e["parents"]]
    return entries


def lineage_diagram(entries: dict, selected: str, depth: int = 2) -> str:
    """Graphviz DOT of the selected node with `depth` levels upstream and downstream (sources, models, snapshots)."""
    def walk(start: str, direction: str) -> set[str]:
        seen, level = set(), {start}
        for _ in range(depth):
            level = {nxt for uid in level for nxt in entries[uid][direction] if nxt in entries} - seen
            seen |= level
        return seen

    keep = walk(selected, "parents") | walk(selected, "children") | {selected}
    c = colors()
    lines = ['digraph { rankdir=LR; bgcolor="transparent"; nodesep=0.1; ranksep=0.5;',
             f'node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=10, color="{c["axis"]}"];',
             f'edge [color="{c["axis"]}", arrowsize=0.5];']
    for uid in sorted(keep):
        e = entries[uid]
        fill, font = (c["series"][0], "white") if uid == selected else (c["neutral"], SLATE)
        lines.append(f'"{uid}" [label="{e["name"]}\\n{LAYERS.get(e["layer"], "")}", fillcolor="{fill}", fontcolor="{font}"];')
    lines += [f'"{parent}" -> "{uid}";' for uid in keep for parent in entries[uid]["parents"] if parent in keep]
    return "\n".join(lines + ["}"])


def star_diagram(graph: dict) -> str:
    """Graphviz DOT: one cluster per mart on the left, the conformed dimensions in core on the right."""
    graph = {name: (mart, dims) for name, (mart, dims, *_) in graph.items()}
    c, ink = colors(), SLATE
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
    lines += [f'"{d}" [fillcolor="{c["neutral"]}", fontcolor="{ink}"];' for d in dims]
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
                      font={"family": f'"{TEXT_FONT}", system-ui, sans-serif', "color": c["ink"]},
                      legend={"orientation": "h", "y": 1.02, "yanchor": "bottom", "x": 0, "title": None},
                      barcornerradius=4, bargap=0.25)
    axis = {"gridcolor": c["grid"], "linecolor": c["axis"], "zerolinecolor": c["axis"], "showline": True,
            "automargin": True, "title": None}
    fig.update_xaxes(**axis, showgrid=False, tickformat=x)
    fig.update_yaxes(**axis, tickformat=y, rangemode="tozero")
    fig.update_traces(selector={"type": "scatter"}, line_width=2, marker_size=8)
    if headroom:  # room for labels drawn outside horizontal bars
        top = float(max(max(t.x) for t in fig.data if t.type == "bar"))
        upper = top * 1.3
        if x and "%" in x and top <= 1 < upper:  # a share never needs an axis past 100% plus room for its label
            upper = max(top * 1.12, 1.0)
        fig.update_xaxes(range=[0, upper])
    st.plotly_chart(fig, theme=None, key=key, config={"displayModeBar": False})
    with st.expander("Table view"):
        st.dataframe(table, hide_index=True)


CARD_HEIGHT, CHART_HEIGHT = 150, 360


def question(text: str, name: str) -> None:
    """Every tab opens the same way: the question in plain words, then how it is measured."""
    st.subheader(text)
    st.caption(f"{descriptions().get(name, '').strip()} · saved query `{name}`")


def growth(value: float) -> str:
    return "–" if value is None or pd.isna(value) else f"{value * 100:+.1f}%"


def pct(value: float, digits: int = 1) -> str:
    return "–" if value is None or pd.isna(value) else f"{value * 100:.{digits}f}%"


def cards(*items: tuple) -> None:
    """Four cards of the same size: (label, value) or (label, value, delta, note)."""
    for column, (label, value, *extra) in zip(st.columns(4), items, strict=True):
        delta, note = (extra + [None, None])[:2]
        column.metric(label, value, delta=delta, delta_description=note, border=True, height=CARD_HEIGHT)


def charts(left: tuple, right: tuple) -> None:
    """Two charts side by side, same height, each with its title and table view: (title, figure, table, key, options)."""
    for column, (title, fig, table, key, options) in zip(st.columns(2), (left, right), strict=True):
        with column:
            st.markdown(f"**{title}**")
            show(fig, table, key=key, height=CHART_HEIGHT, **options)


def line(df: pd.DataFrame, y: str, hover: str) -> go.Figure:
    return go.Figure(go.Scatter(x=df["metric_time__month"], y=df[y], mode="lines+markers",
                                line_color=colors()["series"][0], hovertemplate=f"%{{x|%b %Y}}<br>{hover}<extra></extra>"))


def lines(df: pd.DataFrame, series: dict[str, str], hover: str) -> go.Figure:
    """Several series on one axis (same unit), in the fixed categorical order, with a legend."""
    fig = go.Figure()
    for (column, label), color in zip(series.items(), colors()["series"], strict=False):
        fig.add_trace(go.Scatter(x=df["metric_time__month"], y=df[column], name=label, mode="lines+markers",
                                 line_color=color, hovertemplate=f"%{{x|%b %Y}}<br>{label}: {hover}<extra></extra>"))
    return fig


def bars(df: pd.DataFrame, x: str, y: str, hover: str) -> go.Figure:
    return go.Figure(go.Bar(x=df[x], y=df[y], marker_color=colors()["series"][0],
                            hovertemplate=f"%{{x|%b %Y}}<br>{hover}<extra></extra>"))


def hbar(df: pd.DataFrame, x: str, y: str, hover: str, colors_: list[str] | str | None = None,
         text: list[str] | None = None) -> go.Figure:
    return go.Figure(go.Bar(x=df[x], y=df[y], orientation="h", marker_color=colors_ or colors()["series"][0],
                            text=text, textposition="outside", hovertemplate=f"%{{y}}<br>{hover}<extra></extra>"))


def hero() -> None:
    """Brand header: the linen wordmark on a slate band with a cyan rule, as on felixpago.com."""
    logo = base64.b64encode(LOGO_ON_DARK.read_bytes()).decode()
    st.markdown(
        f"""<div style="background:{SLATE};border-radius:16px;padding:20px 24px;display:flex;
        align-items:center;gap:20px;flex-wrap:wrap;margin-bottom:8px">
          <img src="data:image/svg+xml;base64,{logo}" alt="Félix Pago" style="height:32px">
          <div style="border-left:3px solid {CYAN};padding-left:16px;color:{LINEN}">
            <div style="font-family:'{HEADING_FONT}',sans-serif;font-size:1.5rem;font-weight:800;line-height:1.2;
            letter-spacing:-0.02em">Remittances analytics</div>
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
                "Q7 Ticket", "Q8 LTV", "Growth", "Pay-in", "Data model", "Data catalog"])

with tabs[0]:
    question("How much money moves through Félix each month, and how much does Félix keep?", "q1_monthly_volume")
    q1 = load("q1_monthly_volume")
    last = q1.iloc[-1]
    cards((f"Gross volume · {last['metric_time__month']:%b %Y}", fmt_money(last["gross_volume_usd"]),
           growth(last["gross_volume_usd_mom_pct"]), f"M/M · {growth(last['gross_volume_usd_yoy_pct'])} Y/Y"),
          ("Revenue (fees + FX)", fmt_money(last["revenue_before_losses_usd"])),
          ("Chargeback losses", fmt_money(-last["chargeback_loss_usd"])),
          ("Net revenue", fmt_money(last["net_revenue_usd"])))
    charts(("Gross volume by month", bars(q1, "metric_time__month", "gross_volume_usd", "$%{y:,.0f}"), q1, "q1_volume",
            {"y": "$,.0f"}),
           ("Revenue, chargeback losses and net revenue by month",
            lines(q1, {"revenue_before_losses_usd": "Revenue (fees + FX)", "chargeback_loss_usd": "Chargeback losses",
                       "net_revenue_usd": "Net revenue"}, "$%{y:,.0f}"), q1, "q1_revenue", {"y": "$,.0f", "legend": True}))
    st.caption("A chargeback costs the whole principal (the money was already paid out), so a handful of chargebacks "
               "can take a large share of a month's revenue. The latest months are still maturing.")

with tabs[1]:
    question("Which users make up half of the volume?", "q2_volume_concentration")
    q2 = load("q2_volume_concentration").set_index("user__volume_segment")
    top = q2.loc["top_50pct"]
    cards(("Senders in the top 50%", f"{int(top['active_senders']):,}"),
          ("Their volume", fmt_money(top["gross_volume_usd"])),
          ("Senders in the middle 30%", f"{int(q2.loc['middle_30pct', 'active_senders']):,}"),
          ("Senders in the tail 20%", f"{int(q2.loc['tail_20pct', 'active_senders']):,}"))
    q2 = q2.reindex(list(SEGMENT)[::-1]).reset_index()
    q2["segment"] = q2["user__volume_segment"].map(SEGMENT)
    table = q2.drop(columns="segment")
    charts(("Gross volume by segment", hbar(q2, "gross_volume_usd", "segment", "$%{x:,.0f}"), table, "q2_volume",
            {"x": "$,.0f"}),
           ("Senders by segment", hbar(q2, "active_senders", "segment", "%{x:,} senders"), table, "q2_senders", {}))

with tabs[2]:
    question("How many customers keep coming back?", "q3_recurring_customers")
    q3 = load("q3_recurring_customers")
    last = q3.iloc[-1]
    cards((f"Active customers · {last['metric_time__month']:%b %Y}", f"{int(last['monthly_active_customers']):,}"),
          ("Recurring customers", f"{int(last['recurring_senders']):,}"),
          ("Recurring share", pct(last["recurring_share"])),
          ("Monthly churn", pct(last["churn_rate"])))
    charts(("Recurring share of active customers", line(q3, "recurring_share", "%{y:.1%}"), q3, "q3_share",
            {"y": ".0%"}),
           ("Monthly churn rate", line(q3, "churn_rate", "%{y:.1%}"), q3, "q3_churn", {"y": ".0%"}))

with tabs[3]:
    question("Which payout providers fail most often?", "q4_payout_providers")
    q4 = load("q4_payout_providers").sort_values("payout_attempt_failure_rate")
    tiers = q4["payout_provider__reliability_tier"]
    cards(("Payout providers", f"{len(q4)}"),
          ("✅ Healthy (< 5% failed)", f"{(tiers == 'healthy').sum()}"),
          ("⚠️ Watch (5–10%)", f"{(tiers == 'watch').sum()}"),
          ("⛔ Critical (≥ 10%)", f"{(tiers == 'critical').sum()}"))
    failure = hbar(q4, "payout_attempt_failure_rate", "attempt__provider_name", "%{x:.1%} of attempts failed",
                   [TIER_COLOR.get(t, c["neutral"]) for t in tiers],
                   [f"{r:.1%} {TIER_ICON.get(t, '')}" for r, t in zip(q4["payout_attempt_failure_rate"], tiers)])
    rescued = hbar(q4, "rescued_by_retry_rate", "attempt__provider_name", "%{x:.1%} rescued by a retry", None,
                   [f"{r:.0%}" for r in q4["rescued_by_retry_rate"]])
    charts(("Share of payout attempts that failed", failure, q4, "q4_failure", {"x": ".0%", "headroom": True}),
           ("Failed first attempts rescued by a retry", rescued, q4, "q4_rescued", {"x": ".0%", "headroom": True}))

with tabs[4]:
    question("Do groups of users send money to the same beneficiaries?", "q5_sender_clusters")
    q5 = load("q5_sender_clusters").set_index("user__cluster_type").reindex(["individual", "household", "high_fan_in"])
    cards(("Individual senders", f"{int(q5.loc['individual', 'senders']):,}"),
          ("Senders in households", f"{int(q5.loc['household', 'senders']):,}"),
          ("Senders in high fan-in clusters", f"{int(q5.loc['high_fan_in', 'senders']):,}"),
          ("Chargebacks · high fan-in vs individual",
           f"{pct(q5.loc['high_fan_in', 'chargeback_rate'])} vs {pct(q5.loc['individual', 'chargeback_rate'])}"))
    q5 = q5.dropna(how="all").reset_index()
    q5["cluster"] = q5["user__cluster_type"].map(CLUSTER)
    emphasis = [c["series"][0] if t == "high_fan_in" else c["neutral"] for t in q5["user__cluster_type"]]
    table = q5.drop(columns="cluster")
    charts(("Senders by cluster type", hbar(q5, "senders", "cluster", "%{x:,} senders", emphasis), table, "q5_senders",
            {}),
           ("Chargeback rate by cluster type", hbar(q5, "chargeback_rate", "cluster", "%{x:.2%}", emphasis,
                                                    [f"{v:.1%}" for v in q5["chargeback_rate"]]), table, "q5_cb",
            {"x": ".0%", "headroom": True}))
    st.caption("High fan-in: a beneficiary receives money from 10 or more unrelated senders, the AML review queue.")

with tabs[5]:
    question("How often are card payments charged back?", "q6_chargeback_rate")
    total = load("q6_chargeback_rate_total").iloc[0]
    cards(("Chargeback rate (payments)", pct(total["chargeback_rate"], 2)),
          ("Chargeback rate (amount)", pct(total["chargeback_rate_amount"], 2)),
          ("Card payments charged back", f"{int(total['payments_charged_back']):,}"),
          ("Card payments that succeeded", f"{int(total['transfers']):,}"))
    q6 = load("q6_chargeback_rate")
    by_month = line(q6, "chargeback_rate", "%{y:.2%}")
    by_month.add_vrect(x0=q6["metric_time__month"].iloc[-3], x1=q6["metric_time__month"].iloc[-1],
                       fillcolor=c["shade"], line_width=0)
    banks = load("q6_chargeback_rate_by_bank").sort_values("chargeback_rate")
    charts(("By payment month (shaded months are still maturing)", by_month, q6, "q6_month", {"y": ".1%"}),
           ("By issuing bank", hbar(banks, "chargeback_rate", "payment__funding_institution", "%{x:.2%}", None,
                                    [f"{v:.1%}" for v in banks["chargeback_rate"]]), banks, "q6_bank",
            {"x": ".1%", "headroom": True}))
    st.caption("Cash payments can't be charged back, so the rate is over debit card payments only.")

with tabs[6]:
    question("How much does a typical transfer send?", "q7_transaction_value")
    q7 = load("q7_transaction_value").set_index("payment__payment_method")
    cards(("Average ticket · debit card", fmt_money(q7.loc["debit_card", "atv_usd"])),
          ("Median ticket · debit card", fmt_money(q7.loc["debit_card", "median_ticket_usd"])),
          ("Average ticket · cash", fmt_money(q7.loc["cash", "atv_usd"])),
          ("Median ticket · cash", fmt_money(q7.loc["cash", "median_ticket_usd"])))
    q7 = q7.reset_index()
    long = q7.melt(id_vars="payment__payment_method", value_vars=["atv_usd", "median_ticket_usd"], var_name="measure")
    long["measure"] = long["measure"].map({"atv_usd": "Average", "median_ticket_usd": "Median"})
    long["method"] = long["payment__payment_method"].map(METHOD)
    tickets = px.bar(long, x="measure", y="value", color="method", barmode="group", text_auto="$.0f",
                     color_discrete_map={"Debit card": c["series"][0], "Cash": c["series"][1]})
    q7["method"] = q7["payment__payment_method"].map(METHOD)
    transfers = hbar(q7, "transfers", "method", "%{x:,} transfers", None, [f"{int(v):,}" for v in q7["transfers"]])
    charts(("Average vs median ticket by pay-in method", tickets, q7.drop(columns="method"), "q7_ticket",
            {"y": "$,.0f", "legend": True}),
           ("Transfers by pay-in method", transfers, q7.drop(columns="method"), "q7_transfers", {"headroom": True}))
    st.caption("The median sits below the average: a few large senders pull the average up.")

with tabs[7]:
    question("How much is a customer worth over time?", "q8_ltv")
    ltv = load("q8_ltv").iloc[0]
    projection = load("q8_ltv_projection").dropna(subset=["projected_ltv_12m_usd"])
    cards(("Historical LTV per sender", fmt_money(ltv["historical_ltv_usd"])),
          (f"Projected 12-month LTV · {projection['metric_time__month'].iloc[-1]:%b %Y}",
           fmt_money(projection["projected_ltv_12m_usd"].iloc[-1])),
          ("Lifetime net revenue", fmt_money(ltv["net_revenue_usd"])),
          ("Senders so far", f"{int(ltv['active_senders']):,}"))
    curve = load("q8_ltv_curve")
    curve["cohort"] = curve["customer_month__cohort_month"].astype(str).str[:7]
    ramp = c["ordinal"]  # one hue, oldest → newest cohort (most emphasis)
    quarterly = sorted(m for m in curve["cohort"].unique() if m[5:7] in {"01", "04", "07", "10"})[-len(ramp):]
    curve = curve[curve["cohort"].isin(quarterly)]
    cohorts = px.line(curve, x="customer_month__months_since_first_transfer", y="ltv_per_cohort_user", color="cohort",
                      color_discrete_sequence=ramp[-len(quarterly):], category_orders={"cohort": quarterly})
    charts(("Net revenue per user by cohort, N months after the first transfer", cohorts, curve.drop(columns="cohort"),
            "q8_curve", {"y": "$,.0f", "legend": True}),
           ("Projected 12-month LTV by month (ARPU × expected lifetime)",
            line(projection, "projected_ltv_12m_usd", "$%{y:,.2f}"), projection, "q8_projection", {"y": "$,.0f"}))

with tabs[8]:
    question("Is the customer base growing, and is each customer worth more?", "growth_kpis_monthly")
    g = load("growth_kpis_monthly")
    last = g.iloc[-1]
    cards((f"Active senders · {last['metric_time__month']:%b %Y}", f"{int(last['active_senders']):,}",
           growth(last["active_senders_yoy_pct"]), "Y/Y"),
          ("New senders", f"{int(last['new_senders']):,}"),
          ("ARPU (net revenue per active sender)", fmt_money(last["arpu_usd"]), growth(last["arpu_usd_mom_pct"]),
           f"M/M · {growth(last['arpu_usd_yoy_pct'])} Y/Y"),
          ("ARPU a year earlier", fmt_money(g["arpu_usd"].iloc[-13]) if len(g) > 12 else "–"))
    charts(("Active and new senders by month", lines(g, {"active_senders": "Active senders", "new_senders": "New senders"},
                                                     "%{y:,}"), g, "growth_senders", {"legend": True}),
           ("ARPU by month", bars(g, "metric_time__month", "arpu_usd", "$%{y:,.2f}"), g, "growth_arpu", {"y": "$,.0f"}))

with tabs[9]:
    question("Which banks decline cards, and which stores let cash barcodes expire?", "payin_performance")
    payin = load("payin_performance")
    cards_ = payin.dropna(subset=["card_decline_rate"]).sort_values("card_decline_rate")
    cash = payin.dropna(subset=["cash_expiry_rate"]).sort_values("cash_expiry_rate")
    cards((f"Lowest card decline · {cards_['payment__funding_institution'].iloc[0]}", pct(cards_["card_decline_rate"].iloc[0])),
          (f"Highest card decline · {cards_['payment__funding_institution'].iloc[-1]}", pct(cards_["card_decline_rate"].iloc[-1])),
          (f"Lowest cash expiry · {cash['payment__funding_institution'].iloc[0]}", pct(cash["cash_expiry_rate"].iloc[0])),
          (f"Highest cash expiry · {cash['payment__funding_institution'].iloc[-1]}", pct(cash["cash_expiry_rate"].iloc[-1])))
    cards_ = cards_.assign(bank=cards_["payment__funding_institution"] + " · " + cards_["payment__payment_processor"])
    charts(("Card decline rate by issuing bank and processor",
            hbar(cards_, "card_decline_rate", "bank", "%{x:.1%}"), cards_.drop(columns="bank"), "payin_cards",
            {"x": ".0%"}),
           ("Cash barcode expiry rate by store",
            hbar(cash, "cash_expiry_rate", "payment__funding_institution", "%{x:.1%}", c["series"][1]), cash,
            "payin_cash", {"x": ".0%"}))

with tabs[10]:
    st.subheader("How is the warehouse modelled, and which dimensions do the marts share?")
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

with tabs[11]:
    st.subheader("What is in each table, and where does its data come from?")
    st.caption("The dbt docs: every source, model and snapshot with its description, columns and lineage, read from "
               "dbt's manifest. `python run.py docs` refreshes them (the dbt sequence does it too).")
    if not DBT_MANIFEST.exists():
        st.info("No dbt manifest yet. In the terminal, run `python run.py` and choose 1 (Run sequentially).", icon="ℹ️")
        st.stop()
    entries = catalog(DBT_MANIFEST.stat().st_mtime)
    kinds = pd.Series([e["kind"] for e in entries.values()])
    cards(("Sources (raw)", f"{(kinds == 'source').sum()}"),
          ("Models", f"{(kinds == 'model').sum()}"),
          ("Snapshots (SCD2)", f"{(kinds == 'snapshot').sum()}"),
          ("Documented columns", f"{sum(len(e['columns']) for e in entries.values()):,}"))
    order = list(LAYERS)
    options = sorted(entries, key=lambda u: (order.index(entries[u]["layer"]) if entries[u]["layer"] in order else 9,
                                             entries[u]["name"]))
    selected = st.selectbox("Table", options, index=options.index("model.felix.fct_payments") if "model.felix.fct_payments" in options else 0,
                            format_func=lambda u: f"{LAYERS.get(entries[u]['layer'], '')} · {entries[u]['name']}")
    entry = entries[selected]
    left, right = st.columns(2)
    with left, st.container(border=True, height=CHART_HEIGHT + 40):
        st.markdown(f"**{entry['name']}** · `{entry['schema']}` · {entry['materialized']}")
        facts = [f"**Owner** {entry['owner']}" if entry["owner"] else "", f"**Grain** {entry['grain']}" if entry["grain"] else ""]
        if any(facts):
            st.caption(" · ".join(f for f in facts if f))
        st.markdown(entry["description"] or "_No description._")
    with right:
        st.dataframe(pd.DataFrame(entry["columns"]), hide_index=True, height=CHART_HEIGHT + 40)
    st.markdown("**Lineage: two steps upstream (where the data comes from) and downstream (where it goes)**")
    st.graphviz_chart(lineage_diagram(entries, selected), use_container_width=True)
    if DOCS_SITE.exists() and st.toggle("Show the full dbt docs site (searchable, 4 MB)"):
        components.html(DOCS_SITE.read_text(encoding="utf-8"), height=900, scrolling=True)

