"""Risk: sender clusters (Q5), high fan-in beneficiaries, chargeback rate by cluster type."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root, for `dashboard.*` and `scripts.*`

import plotly.express as px  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from dashboard.components import chart, page_header  # noqa: E402
from dashboard.db import load  # noqa: E402
from dashboard.theme import color_map, label, tokens  # noqa: E402

page_header("Risk", "The sender ↔ beneficiary network: households and possible mules (AML).")
st.caption("Full history; the month and dimension filters don't apply on this page.")
t = tokens()

clusters = load("q5_sender_clusters")
c1, c2, c3 = st.columns(3)
for column, ctype in zip((c1, c2, c3), ("individual", "household", "high_fan_in")):
    row = clusters[clusters["user__cluster_type"] == ctype]
    if not row.empty:
        r = row.iloc[0]
        column.metric(f"{label(ctype)} senders", f"{int(r['senders']):,}", border=True,
                      help="Senders in clusters of this type (Q5).")
        column.caption(f"Chargeback rate {r['chargeback_rate']:.1%} · volume ${r['gross_volume_usd']:,.0f}")

left, right = st.columns(2)
with left:
    st.markdown("**Chargeback rate by cluster type**")
    order = ["individual", "household", "high_fan_in"]
    data = clusters.set_index("user__cluster_type").reindex(order).reset_index()
    # Emphasis: the high fan-in cluster carries the story; the others recede to neutral gray.
    colors = [t["series"][0] if c == "high_fan_in" else t["neutral"] for c in data["user__cluster_type"]]
    fig = go.Figure(go.Bar(x=[label(c) for c in data["user__cluster_type"]], y=data["chargeback_rate"], marker_color=colors,
                           text=[f"{v:.1%}" for v in data["chargeback_rate"]], textposition="outside",
                           hovertemplate="%{x}<br>%{y:.2%}<extra></extra>"))
    chart(fig, clusters, key="risk_cb", y_format=".0%", legend=False)
with right:
    st.markdown("**Clusters by number of senders**")
    sizes = load("dash_cluster_sizes")
    sizes = sizes.assign(type=sizes["sender_cluster__cluster_type"].map(label),
                         senders=sizes["sender_cluster__n_users"].astype(int)).sort_values("senders")
    fig = px.bar(sizes, x=sizes["senders"].astype(str), y="sender_clusters", color="type", barmode="stack",
                 color_discrete_map={label(k): v for k, v in color_map("cluster_type").items()},
                 labels={"x": "Senders in the cluster", "sender_clusters": ""}, log_y=True)
    fig.update_traces(hovertemplate="%{x} senders<br>%{y:,} clusters<extra>%{fullData.name}</extra>")
    fig.update_yaxes(dtick=1)
    chart(fig, sizes.drop(columns=["type", "senders"]), key="risk_sizes")
    st.caption("Log scale: most senders send alone; the two high fan-in clusters hold 14 and 19 senders.")

st.markdown("**Beneficiaries paid by the most senders (fan-in)**")
fan_in = load("dash_top_fan_in_beneficiaries").sort_values("distinct_senders_per_beneficiary")
colors = [t["series"][0] if c == "high_fan_in" else t["neutral"] for c in fan_in["user_beneficiary__cluster_type"]]
fig = go.Figure(go.Bar(x=fan_in["distinct_senders_per_beneficiary"], y=fan_in["user_beneficiary__beneficiary_id"],
                       orientation="h", marker_color=colors,
                       text=[label(c) for c in fan_in["user_beneficiary__cluster_type"]], textposition="outside",
                       hovertemplate="%{y}<br>%{x} distinct senders<extra></extra>"))
chart(fig, fan_in, key="risk_fan_in", legend=False, height=440, label_headroom=True)
st.caption("Beneficiaries with 10 or more unrelated senders put their whole cluster in `high_fan_in` for AML review.")
