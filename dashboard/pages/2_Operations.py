"""Operations: payout provider reliability (Q4), failure reasons, delivery time."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root, for `dashboard.*` and `scripts.*`

import plotly.express as px  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from dashboard.components import chart, filter_row, page_header  # noqa: E402
from dashboard.db import load  # noqa: E402
from dashboard.theme import STATUS, TIER_ICON, TIER_STATUS, color_map, label, tokens  # noqa: E402

page_header("Operations", "Delivery of remittances through payout providers.")
f = filter_row(method=False, corridor=False, note="Provider tables cover the full history; the month range filters the delivery trend.")
t = tokens()

providers = load("q4_payout_providers").sort_values("payout_attempt_failure_rate")
providers["tier"] = providers["payout_provider__reliability_tier"].map(lambda v: f"{TIER_ICON.get(v, '')} {label(v)}")
st.markdown("**Payout providers by failed disbursements (Q4)**")
left, right = st.columns([3, 2])
with left:
    colors = [STATUS[TIER_STATUS[tier]] for tier in providers["payout_provider__reliability_tier"]]
    fig = go.Figure(go.Bar(
        x=providers["payout_attempt_failure_rate"], y=providers["attempt__provider_name"], orientation="h",
        marker_color=colors, text=[f"{r:.1%} · {label(tier)}" for r, tier in
                                   zip(providers["payout_attempt_failure_rate"], providers["payout_provider__reliability_tier"])],
        textposition="outside", hovertemplate="%{y}<br>%{x:.1%} of attempts failed<extra></extra>"))
    fig.add_vline(x=0.05, line_width=1, line_color=t["axis"])
    fig.add_vline(x=0.10, line_width=1, line_color=t["axis"])
    chart(fig, providers.drop(columns="tier"), key="ops_providers", x_format=".0%", legend=False, height=360,
          label_headroom=True)
with right:
    st.dataframe(
        providers[["attempt__provider_name", "tier", "payout_attempts", "payout_attempt_failure_rate",
                   "first_attempt_success_rate", "rescued_by_retry_rate"]],
        hide_index=True,
        column_config={
            "attempt__provider_name": "Provider", "tier": "Tier", "payout_attempts": "Attempts",
            "payout_attempt_failure_rate": st.column_config.NumberColumn("Failure rate", format="percent"),
            "first_attempt_success_rate": st.column_config.NumberColumn("1st-attempt success", format="percent"),
            "rescued_by_retry_rate": st.column_config.NumberColumn("Rescued by retry", format="percent"),
        },
    )
    st.caption("Tiers: ✅ healthy < 5% · ⚠️ watch 5–10% · ⛔ critical ≥ 10% of attempts failed.")

left, right = st.columns(2)
with left:
    st.markdown("**Failed attempts by reason**")
    reasons = load("dash_failure_reasons")
    reason_colors = {label(k): v for k, v in color_map("failure_reason").items()}
    reasons = reasons.assign(reason=reasons["attempt__failure_reason"].map(label))
    fig = px.bar(reasons, x="payout_attempts_failed", y="attempt__provider_name", color="reason", orientation="h",
                 color_discrete_map=reason_colors, labels={"payout_attempts_failed": "", "attempt__provider_name": ""})
    fig.update_traces(hovertemplate="%{y}<br>%{x} failed attempts<extra>%{fullData.name}</extra>")
    chart(fig, reasons.drop(columns="reason"), key="ops_reasons", height=380)
with right:
    st.markdown("**Median minutes from receipt to delivery, by final provider**")
    delivery = load("dash_delivery_by_provider").sort_values("median_minutes_to_deliver")
    fig = go.Figure(go.Bar(x=delivery["median_minutes_to_deliver"], y=delivery["remittance__final_provider_name"],
                           orientation="h", marker_color=t["series"][0],
                           hovertemplate="%{y}<br>%{x:,.0f} min<extra></extra>"))
    chart(fig, delivery, key="ops_delivery_provider", legend=False, height=380)

st.markdown("**Delivery rate and time by receipt month**")
monthly = f.months(load("dash_delivery_monthly")).sort_values("metric_time__month")
left, right = st.columns(2)
with left:
    st.caption("Share of remittances delivered")
    fig = go.Figure(go.Scatter(x=monthly["metric_time__month"], y=monthly["delivery_rate"], mode="lines+markers",
                               line_color=t["series"][0], hovertemplate="%{x|%b %Y}<br>%{y:.1%} delivered<extra></extra>"))
    chart(fig, monthly, key="ops_delivery_rate", y_format=".0%", legend=False)
with right:
    st.caption("Median minutes from receipt to delivery")
    fig = go.Figure(go.Scatter(x=monthly["metric_time__month"], y=monthly["median_minutes_to_deliver"],
                               mode="lines+markers", line_color=t["series"][0],
                               hovertemplate="%{x|%b %Y}<br>%{y:,.0f} min<extra></extra>"))
    chart(fig, monthly, key="ops_delivery_minutes", legend=False)
