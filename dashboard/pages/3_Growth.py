"""Growth: senders, ARPU with MoM / YoY, recurrence (Q3), Pareto (Q2) and LTV curves (Q8)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root, for `dashboard.*` and `scripts.*`

import plotly.express as px  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from dashboard.components import chart, filter_row, kpi, page_header  # noqa: E402
from dashboard.db import load  # noqa: E402
from dashboard.theme import ORDINAL_BLUE, color_map, label, tokens  # noqa: E402

page_header("Growth", "Customer engagement and value.")
f = filter_row(method=False, corridor=False, note="The month range filters the trends; Pareto and LTV curves cover the full history.")
t = tokens()

kpis = f.months(load("growth_kpis_monthly")).sort_values("metric_time__month")
last = kpis.iloc[-1]
st.subheader(f"{last['metric_time__month']:%B %Y}")
c1, c2, c3, _ = st.columns(4)
kpi(c1, "Active senders", last["active_senders"], "count", None, last["active_senders_yoy_pct"],
    "Distinct senders with a succeeded transfer in the month.")
kpi(c2, "New senders", last["new_senders"], "count", None, None, "First-ever succeeded transfer in the month.")
kpi(c3, "ARPU", last["arpu_usd"], "money", last["arpu_usd_mom_pct"], last["arpu_usd_yoy_pct"],
    "Net revenue ÷ active senders.")

left, right = st.columns(2)
with left:
    st.markdown("**Active and new senders**")
    long = kpis.melt(id_vars="metric_time__month", value_vars=["active_senders", "new_senders"], var_name="series")
    long["series"] = long["series"].map({"active_senders": "Active senders", "new_senders": "New senders"})
    fig = px.line(long, x="metric_time__month", y="value", color="series", markers=True,
                  color_discrete_sequence=t["series"][:2], labels={"value": "", "metric_time__month": ""})
    fig.update_traces(hovertemplate="%{x|%b %Y}<br>%{y:,}<extra>%{fullData.name}</extra>")
    chart(fig, kpis[["metric_time__month", "active_senders", "new_senders"]], key="gr_senders")
with right:
    st.markdown("**ARPU growth vs the same month last year**")
    # Month-over-month ARPU swings by thousands of % around a near-zero month; it stays in the tile and table.
    fig = go.Figure(go.Scatter(x=kpis["metric_time__month"], y=kpis["arpu_usd_yoy_pct"], mode="lines+markers",
                               line_color=t["series"][0], hovertemplate="%{x|%b %Y}<br>%{y:+.1%}<extra></extra>"))
    fig.add_hline(y=0, line_width=1, line_color=t["axis"])
    chart(fig, kpis[["metric_time__month", "arpu_usd", "arpu_usd_mom_pct", "arpu_usd_yoy_pct"]], key="gr_arpu_growth",
          y_format="+.0%", legend=False)

left, right = st.columns(2)
with left:
    st.markdown("**ARPU by month (net revenue per active sender)**")
    fig = go.Figure(go.Bar(x=kpis["metric_time__month"], y=kpis["arpu_usd"], marker_color=t["series"][0],
                           hovertemplate="%{x|%b %Y}<br>$%{y:,.2f}<extra></extra>"))
    chart(fig, kpis[["metric_time__month", "arpu_usd"]], key="gr_arpu", y_format="$,.0f", legend=False)
with right:
    st.markdown("**Recurring share of active customers (Q3)**")
    rec = f.months(load("q3_recurring_customers")).sort_values("metric_time__month")
    fig = go.Figure(go.Scatter(x=rec["metric_time__month"], y=rec["recurring_share"], mode="lines+markers",
                               line_color=t["series"][0], hovertemplate="%{x|%b %Y}<br>%{y:.1%}<extra></extra>"))
    chart(fig, rec, key="gr_recurring", y_format=".0%", legend=False)

st.markdown("**Customers by lifecycle status (Q3)**")
mix = f.months(load("dash_lifecycle_mix_monthly"))
mix = mix.assign(status=mix["customer_month__lifecycle_status"].map(label))
fig = px.bar(mix, x="metric_time__month", y="customer_months", color="status", barmode="stack",
             color_discrete_map={label(k): v for k, v in color_map("lifecycle_status").items()},
             category_orders={"status": [label(s) for s in ["new", "recurring", "returning", "at_risk", "churned"]]},
             labels={"customer_months": "", "metric_time__month": ""})
fig.update_traces(hovertemplate="%{x|%b %Y}<br>%{y:,} customers<extra>%{fullData.name}</extra>")
chart(fig, mix.drop(columns="status"), key="gr_mix")

st.divider()
left, right = st.columns(2)
with left:
    st.markdown("**Pareto: cumulative share of volume by sender rank (Q2)**")
    pareto = load("dash_pareto").sort_values("user__volume_rank").reset_index(drop=True)
    # Presentation only: cumulative share for the Pareto curve (DESIGN §5).
    pareto["share_of_senders"] = (pareto.index + 1) / len(pareto)
    pareto["cumulative_share_of_volume"] = pareto["gross_volume_usd"].cumsum() / pareto["gross_volume_usd"].sum()
    crossing = pareto[pareto["cumulative_share_of_volume"] >= 0.5].iloc[0]
    fig = go.Figure(go.Scatter(x=pareto["share_of_senders"], y=pareto["cumulative_share_of_volume"], mode="lines",
                               line_color=t["series"][0], hovertemplate="Top %{x:.1%} of senders<br>%{y:.1%} of volume<extra></extra>"))
    fig.add_hline(y=0.5, line_width=1, line_color=t["axis"])
    fig.add_annotation(x=crossing["share_of_senders"], y=0.5, text=f"{int(crossing.name) + 1} senders "
                       f"({crossing['share_of_senders']:.1%}) = 50% of volume", showarrow=True, arrowcolor=t["muted"],
                       ax=150, ay=25, font={"color": t["ink2"]})
    chart(fig, pareto.head(200), key="gr_pareto", x_format=".0%", y_format=".0%", legend=False)
with right:
    st.markdown("**LTV curves: net revenue per user by cohort (Q8)**")
    curve = load("q8_ltv_curve")
    curve["cohort"] = curve["customer_month__cohort_month"].astype(str).str[:7]
    quarterly = sorted(c for c in curve["cohort"].unique() if c[5:7] in {"01", "04", "07", "10"})[-len(ORDINAL_BLUE):]
    curve = curve[curve["cohort"].isin(quarterly)]
    # Ordered categories → ordinal one-hue ramp (older cohorts lighter).
    fig = px.line(curve, x="customer_month__months_since_first_transfer", y="ltv_per_cohort_user", color="cohort",
                  color_discrete_sequence=ORDINAL_BLUE[-len(quarterly):] if quarterly else ORDINAL_BLUE,
                  category_orders={"cohort": quarterly},
                  labels={"ltv_per_cohort_user": "", "customer_month__months_since_first_transfer": "Months since first transfer"})
    fig.update_traces(hovertemplate="Month %{x}<br>$%{y:,.2f} per user<extra>Cohort %{fullData.name}</extra>")
    chart(fig, curve.drop(columns="cohort"), key="gr_ltv", y_format="$,.0f")
    ltv = load("q8_ltv").iloc[0]
    st.caption(f"Historical LTV: ${ltv['historical_ltv_usd']:,.2f} net revenue per sender to date.")
