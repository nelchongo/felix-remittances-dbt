"""Finance: volume and revenue by method, ticket size, chargebacks, pay-in performance."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root, for `dashboard.*` and `scripts.*`

import plotly.express as px  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from dashboard.components import ALL, chart, filter_row, page_header  # noqa: E402
from dashboard.db import load  # noqa: E402
from dashboard.theme import color_map, label, tokens  # noqa: E402

page_header("Finance", "Pay-in, revenue, ticket size and chargebacks.")
f = filter_row(corridor=True, note="Payment method filters the method charts; corridor filters the ticket-by-corridor chart.")
methods = color_map("payment_method")
t = tokens()

by_method = f.months(load("dash_finance_by_method_monthly"))
if f.method != ALL:
    by_method = by_method[by_method["payment__payment_method"] == f.method]
by_method = by_method.assign(method=by_method["payment__payment_method"].map(label))
method_colors = {label(k): v for k, v in methods.items()}

left, right = st.columns(2)
with left:
    st.markdown("**Gross volume by payment method**")
    fig = px.bar(by_method, x="metric_time__month", y="gross_volume_usd", color="method", barmode="stack",
                 color_discrete_map=method_colors, labels={"gross_volume_usd": "", "metric_time__month": ""})
    fig.update_traces(hovertemplate="%{x|%b %Y}<br>$%{y:,.0f}<extra>%{fullData.name}</extra>")
    chart(fig, by_method[["metric_time__month", "method", "gross_volume_usd", "transfers"]], key="fin_volume", y_format="$,.0f")
with right:
    st.markdown("**Net revenue by payment method**")
    fig = px.bar(by_method, x="metric_time__month", y="net_revenue_usd", color="method", barmode="stack",
                 color_discrete_map=method_colors, labels={"net_revenue_usd": "", "metric_time__month": ""})
    fig.update_traces(hovertemplate="%{x|%b %Y}<br>$%{y:,.0f}<extra>%{fullData.name}</extra>")
    chart(fig, by_method[["metric_time__month", "method", "net_revenue_usd", "fee_revenue_usd", "fx_revenue_usd",
                          "chargeback_loss_usd"]], key="fin_revenue", y_format="$,.0f")

left, right = st.columns(2)
with left:
    st.markdown("**Average vs median ticket by payment method (Q7)**")
    ticket = load("q7_transaction_value")
    long = ticket.melt(id_vars="payment__payment_method", value_vars=["atv_usd", "median_ticket_usd"],
                       var_name="measure", value_name="usd")
    long["measure"] = long["measure"].map({"atv_usd": "Average (ATV)", "median_ticket_usd": "Median"})
    long["method"] = long["payment__payment_method"].map(label)
    # Color keeps meaning the payment method, as everywhere on the page; the x axis carries the measure.
    fig = px.bar(long, x="measure", y="usd", color="method", barmode="group", text_auto="$.0f",
                 color_discrete_map=method_colors, labels={"usd": "", "measure": ""})
    fig.update_traces(textposition="outside", hovertemplate="%{x}<br>$%{y:,.2f}<extra>%{fullData.name}</extra>")
    chart(fig, ticket, key="fin_ticket", y_format="$,.0f")
with right:
    st.markdown("**Average ticket by corridor**")
    corridor = load("dash_ticket_by_corridor")
    if f.method != ALL:
        corridor = corridor[corridor["payment__payment_method"] == f.method]
    if f.corridor != ALL:
        corridor = corridor[corridor["payment__corridor"] == f.corridor]
    corridor = corridor.assign(method=corridor["payment__payment_method"].map(label))
    fig = px.bar(corridor, x="payment__corridor", y="atv_usd", color="method", barmode="group",
                 color_discrete_map=method_colors, labels={"atv_usd": "", "payment__corridor": ""},
                 category_orders={"payment__corridor": ["MX", "GT", "HN", "SV", "DO", "CO"]})
    fig.update_traces(hovertemplate="%{x}<br>$%{y:,.2f}<extra>%{fullData.name}</extra>")
    chart(fig, corridor, key="fin_corridor", y_format="$,.0f")

st.divider()
left, right = st.columns(2)
with left:
    st.markdown("**Chargeback rate by payment month (Q6, debit card)**")
    cb = f.months(load("dash_chargeback_rate_by_method_monthly")).sort_values("metric_time__month")
    fig = go.Figure(go.Scatter(x=cb["metric_time__month"], y=cb["chargeback_rate"], mode="lines+markers",
                               line_color=t["series"][0], name="Chargeback rate",
                               hovertemplate="%{x|%b %Y}<br>%{y:.2%}<extra></extra>"))
    if len(cb) >= 3:  # chargebacks arrive up to ~75 days later (var chargeback_maturity_days = 90)
        fig.add_vrect(x0=cb["metric_time__month"].iloc[-3], x1=cb["metric_time__month"].iloc[-1], fillcolor=t["shade"],
                      line_width=0, annotation_text="still maturing", annotation_position="top left",
                      annotation_font_color=t["muted"])
    chart(fig, cb, key="fin_cb_month", y_format=".1%", legend=False)
with right:
    st.markdown("**Chargeback rate by issuing bank (Q6)**")
    banks = load("q6_chargeback_rate_by_bank").sort_values("chargeback_rate")
    fig = go.Figure(go.Bar(x=banks["chargeback_rate"], y=banks["payment__funding_institution"], orientation="h",
                           marker_color=t["series"][0], text=[f"{v:.1%}" for v in banks["chargeback_rate"]],
                           textposition="outside", hovertemplate="%{y}<br>%{x:.2%}<extra></extra>"))
    chart(fig, banks, key="fin_cb_bank", x_format=".1%", legend=False, label_headroom=True)

st.divider()
payin = load("payin_performance")
left, right = st.columns(2)
with left:
    st.markdown("**Card decline rate by issuing bank**")
    cards = payin.dropna(subset=["card_decline_rate"]).sort_values("card_decline_rate")
    fig = go.Figure(go.Bar(x=cards["card_decline_rate"], y=cards["payment__funding_institution"] + " · "
                           + cards["payment__payment_processor"], orientation="h", marker_color=t["series"][0],
                           hovertemplate="%{y}<br>%{x:.1%}<extra></extra>"))
    chart(fig, cards[["payment__payment_processor", "payment__funding_institution", "payments_created",
                      "card_decline_rate", "payment_success_rate"]], key="fin_declines", x_format=".0%", legend=False,
          height=420)
with right:
    st.markdown("**Cash barcode expiry rate by store**")
    cash = payin.dropna(subset=["cash_expiry_rate"]).sort_values("cash_expiry_rate")
    fig = go.Figure(go.Bar(x=cash["cash_expiry_rate"], y=cash["payment__funding_institution"], orientation="h",
                           marker_color=t["series"][1], hovertemplate="%{y}<br>%{x:.1%}<extra></extra>"))
    chart(fig, cash[["payment__funding_institution", "payments_created", "cash_expiry_rate", "payment_success_rate"]],
          key="fin_expiry", x_format=".0%", legend=False, height=420)
    processors = load("dash_payin_by_processor")
    st.caption("Payment success by processor: " + " · ".join(
        f"{r.payment__payment_processor} {r.payment_success_rate:.1%}" for r in processors.itertuples()))
