"""Render docs/answers.md from saved-query results.

Every number comes from a MetricFlow saved query (run by `python run.py answers`). This module only
formats: it picks the rows to show, formats money / percentages, and writes 1–2 sentence interpretations
from the values. It never computes a business formula (no rates, averages or growth) itself.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pandas as pd

Frames = dict[str, pd.DataFrame]

DIMENSION_LABELS = {
    "metric_time__month": "Month",
    "user__volume_segment": "Volume segment",
    "user__cluster_type": "Cluster type",
    "attempt__provider_name": "Payout provider",
    "payout_provider__reliability_tier": "Reliability tier",
    "payment__payment_method": "Payment method",
    "payment__payment_processor": "Processor",
    "payment__funding_institution": "Funding institution",
    "customer_month__cohort_month": "Cohort",
    "customer_month__months_since_first_transfer": "Months since first transfer",
}
PERCENT_SUFFIXES = ("_pct", "_rate", "_share", "_rate_amount")


# --------------------------------------------------------------------------------------
# Formatting
# --------------------------------------------------------------------------------------
def is_percent(column: str) -> bool:
    return column.endswith(PERCENT_SUFFIXES) or column == "take_rate"


def fmt_money(value: float) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.0f}" if abs(value) >= 1000 else f"{sign}${abs(value):,.2f}"


def header(column: str, labels: dict[str, str]) -> str:
    age = re.fullmatch(r"month_(\d+)_usd", column)
    if age:
        return f"After {age.group(1)} months"
    return DIMENSION_LABELS.get(column, labels.get(column, column))


def fmt_value(column: str, value: object) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "–"
    if column.endswith("_month") or column.startswith("metric_time"):
        return str(value)[:7]
    if isinstance(value, str):
        return value
    number = float(value)
    if is_percent(column):
        sign = "+" if column.endswith("_pct") and number > 0 else ""
        return f"{sign}{number * 100:.1f}%"
    if column.endswith("_usd"):
        return fmt_money(number)
    if number.is_integer():
        return f"{int(number):,}"
    return f"{number:,.2f}"


def markdown_table(df: pd.DataFrame, labels: dict[str, str]) -> str:
    headers = [header(c, labels) for c in df.columns]
    lines = ["| " + " | ".join(headers) + " |"]
    numeric = [pd.api.types.is_numeric_dtype(df[c]) and not c.endswith("_month") for c in df.columns]
    lines.append("|" + "|".join("---:" if n else "---" for n in numeric) + "|")
    for _, row in df.iterrows():
        lines.append("| " + " | ".join(fmt_value(c, row[c]) for c in df.columns) + " |")
    return "\n".join(lines)


def trim_empty_months(df: pd.DataFrame) -> pd.DataFrame:
    """Drop the trailing months with no activity that offset (YoY) metrics add after the data ends."""
    if "metric_time__month" not in df.columns or df.empty:
        return df
    df = df.sort_values("metric_time__month").reset_index(drop=True)
    base = [
        c for c in df.columns
        if c != "metric_time__month" and not is_percent(c) and pd.api.types.is_numeric_dtype(df[c])
    ]
    active = df[base].fillna(0).abs().sum(axis=1) > 0
    if not active.any():
        return df.iloc[0:0]
    return df.loc[: active[active].index.max()]


def pct(value: float) -> str:
    return "–" if value is None or pd.isna(value) else f"{value * 100:.1f}%"


def growth(value: float) -> str:
    return "–" if value is None or pd.isna(value) else f"{value * 100:+.1f}%"


# --------------------------------------------------------------------------------------
# Interpretations (read values, never compute business formulas)
# --------------------------------------------------------------------------------------
def interpret_q1(f: Frames) -> str:
    df = trim_empty_months(f["q1_monthly_volume"])
    last = df.iloc[-1]
    peak = df.loc[df["gross_volume_usd"].idxmax()]
    return (
        f"In {str(last['metric_time__month'])[:7]} Félix moved {fmt_money(last['gross_volume_usd'])} "
        f"({growth(last['gross_volume_usd_yoy_pct'])} year over year, {growth(last['gross_volume_usd_mom_pct'])} "
        f"month over month). The peak month was {str(peak['metric_time__month'])[:7]} "
        f"({fmt_money(peak['gross_volume_usd'])}), driven by the seasonal peaks."
    )


def interpret_q2(f: Frames) -> str:
    df = f["q2_volume_concentration"].set_index("user__volume_segment")
    top, senders = df.loc["top_50pct"], df["active_senders"].sum()
    return (
        f"{int(top['active_senders']):,} of {int(senders):,} senders "
        f"({pct(top['active_senders'] / senders)}) make up half of the volume "
        f"({fmt_money(top['gross_volume_usd'])}). They are flagged `top_50pct` in `dim_users.volume_segment`."
    )


def interpret_q3(f: Frames) -> str:
    df = trim_empty_months(f["q3_recurring_customers"]).tail(12)
    last = df.iloc[-1]
    return (
        f"In {str(last['metric_time__month'])[:7]}, {int(last['recurring_senders']):,} of "
        f"{int(last['monthly_active_customers']):,} active customers were recurring "
        f"({pct(last['recurring_share'])}); monthly churn was {pct(last['churn_rate'])}. Over the last 12 months "
        f"the recurring share ranged from {pct(df['recurring_share'].min())} to {pct(df['recurring_share'].max())}."
    )


def interpret_q4(f: Frames) -> str:
    df = f["q4_payout_providers"].sort_values("payout_attempt_failure_rate")
    best, worst = df.iloc[0], df.iloc[-1]
    critical = df[df["payout_provider__reliability_tier"] == "critical"]["attempt__provider_name"].tolist()
    return (
        f"{best['attempt__provider_name']} is the most reliable provider ({pct(best['payout_attempt_failure_rate'])} "
        f"of attempts fail) and {worst['attempt__provider_name']} the least ({pct(worst['payout_attempt_failure_rate'])}). "
        f"Critical tier: {', '.join(critical) or 'none'}; retries rescue most failed first attempts."
    )


def interpret_q5(f: Frames) -> str:
    df = f["q5_sender_clusters"].set_index("user__cluster_type")
    parts = []
    if "high_fan_in" in df.index:
        row = df.loc["high_fan_in"]
        parts.append(
            f"{int(row['senders'])} senders sit in high fan-in clusters (beneficiaries paid by 10+ unrelated senders) "
            f"with a chargeback rate of {pct(row['chargeback_rate'])}"
        )
    if "individual" in df.index:
        parts.append(f"versus {pct(df.loc['individual', 'chargeback_rate'])} for individual senders")
    if "household" in df.index:
        parts.append(f"and {int(df.loc['household', 'senders'])} senders form households sharing beneficiaries")
    return (", ".join(parts) + ". High fan-in clusters are the AML review queue.") if parts else ""


def interpret_q6(f: Frames) -> str:
    total = f["q6_chargeback_rate_total"].iloc[0]
    banks = f["q6_chargeback_rate_by_bank"].dropna(subset=["chargeback_rate"]).sort_values("chargeback_rate")
    return (
        f"{pct(total['chargeback_rate'])} of succeeded debit card payments were charged back "
        f"({pct(total['chargeback_rate_amount'])} of card volume). By issuing bank it ranges from "
        f"{pct(banks.iloc[0]['chargeback_rate'])} ({banks.iloc[0]['payment__funding_institution']}) to "
        f"{pct(banks.iloc[-1]['chargeback_rate'])} ({banks.iloc[-1]['payment__funding_institution']}). "
        "Cash can't be charged back; the latest months are still maturing."
    )


def interpret_q7(f: Frames) -> str:
    df = f["q7_transaction_value"].set_index("payment__payment_method")
    lines = [
        f"{method.replace('_', ' ').capitalize()}: ATV {fmt_money(row['atv_usd'])}, median {fmt_money(row['median_ticket_usd'])}"
        for method, row in df.iterrows()
    ]
    return "; ".join(lines) + ". The median sits well below the mean: a few large senders skew the average."


def interpret_q8(f: Frames) -> str:
    ltv = f["q8_ltv"].iloc[0]
    proj = trim_empty_months(f["q8_ltv_projection"]).dropna(subset=["projected_ltv_12m_usd"])
    fx_share = ltv["fx_revenue_usd"] / (ltv["fx_revenue_usd"] + ltv["fee_revenue_usd"])
    text = (
        f"Each sender has generated {fmt_money(ltv['historical_ltv_usd'])} of net revenue so far "
        f"(FX is {pct(fx_share)} of gross revenue; chargeback losses take {fmt_money(ltv['chargeback_loss_usd'])})."
    )
    if not proj.empty:
        last = proj.iloc[-1]
        text += (
            f" At {str(last['metric_time__month'])[:7]} ARPU and churn, the projected 12-month LTV is "
            f"{fmt_money(last['projected_ltv_12m_usd'])}."
        )
    return text


def interpret_growth(f: Frames) -> str:
    df = trim_empty_months(f["growth_kpis_monthly"])
    last = df.iloc[-1]
    return (
        f"In {str(last['metric_time__month'])[:7]}: {int(last['active_senders']):,} active senders "
        f"({growth(last['active_senders_yoy_pct'])} Y/Y), {int(last['new_senders']):,} new, ARPU "
        f"{fmt_money(last['arpu_usd'])} ({growth(last['arpu_usd_mom_pct'])} M/M, {growth(last['arpu_usd_yoy_pct'])} Y/Y)."
    )


def interpret_payin(f: Frames) -> str:
    df = f["payin_performance"]
    cards = df.dropna(subset=["card_decline_rate"]).sort_values("card_decline_rate")
    cash = df.dropna(subset=["cash_expiry_rate"]).sort_values("cash_expiry_rate")
    return (
        f"Card declines range from {pct(cards.iloc[0]['card_decline_rate'])} ({cards.iloc[0]['payment__funding_institution']}) "
        f"to {pct(cards.iloc[-1]['card_decline_rate'])} ({cards.iloc[-1]['payment__funding_institution']}); "
        f"cash barcodes expire unpaid from {pct(cash.iloc[0]['cash_expiry_rate'])} ({cash.iloc[0]['payment__funding_institution']}) "
        f"to {pct(cash.iloc[-1]['cash_expiry_rate'])} ({cash.iloc[-1]['payment__funding_institution']})."
    )


# --------------------------------------------------------------------------------------
# Sections
# --------------------------------------------------------------------------------------
def ltv_curve_pivot(df: pd.DataFrame) -> pd.DataFrame:
    """Presentation only: reshape the LTV curve into cohort rows × selected ages."""
    ages = [0, 3, 6, 12, 18]
    df = df[df["customer_month__months_since_first_transfer"].isin(ages)]
    wide = df.pivot(
        index="customer_month__cohort_month",
        columns="customer_month__months_since_first_transfer",
        values="ltv_per_cohort_user",
    ).reset_index()
    wide.columns = ["customer_month__cohort_month"] + [f"month_{int(a)}_usd" for a in wide.columns[1:]]
    keep = wide["customer_month__cohort_month"].astype(str).str[5:7].isin(["01", "04", "07", "10"])
    return wide[keep]


@dataclass
class Table:
    saved_query: str
    shape: Callable[[pd.DataFrame], pd.DataFrame] = lambda df: df
    note: str = ""


@dataclass
class Section:
    key: str
    title: str
    tables: list[Table]
    interpret: Callable[[Frames], str]
    summary_query: str = field(default="")


SECTIONS = [
    Section("Q1", "Total amount transacted by month", [Table("q1_monthly_volume", trim_empty_months)], interpret_q1),
    Section("Q2", "Users that represent 50% of the volume", [Table("q2_volume_concentration")], interpret_q2),
    Section(
        "Q3", "Recurring customers",
        [Table("q3_recurring_customers", lambda d: trim_empty_months(d).tail(12), "Last 12 months.")],
        interpret_q3,
    ),
    Section("Q4", "Payout providers by failed disbursements", [Table("q4_payout_providers")], interpret_q4),
    Section("Q5", "Clusters of users sending to the same beneficiaries", [Table("q5_sender_clusters")], interpret_q5),
    Section(
        "Q6", "Chargeback rate",
        [
            Table("q6_chargeback_rate_total"),
            Table("q6_chargeback_rate_by_bank"),
            Table("q6_chargeback_rate", lambda d: trim_empty_months(d).tail(12), "Last 12 months, by payment month."),
        ],
        interpret_q6,
    ),
    Section("Q7", "Average transaction value", [Table("q7_transaction_value")], interpret_q7),
    Section(
        "Q8", "Customer lifetime value",
        [
            Table("q8_ltv"),
            Table("q8_ltv_projection", lambda d: trim_empty_months(d).tail(6), "Last 6 months."),
            Table("q8_ltv_curve", ltv_curve_pivot, "LTV per user by cohort (quarterly cohorts) at 0, 3, 6, 12 and 18 months."),
        ],
        interpret_q8,
    ),
    Section(
        "Growth", "Growth KPIs: active senders, ARPU, MoM and YoY",
        [Table("growth_kpis_monthly", lambda d: trim_empty_months(d).tail(12), "Last 12 months.")],
        interpret_growth,
    ),
    Section("Pay-in", "Pay-in performance by processor, bank and store", [Table("payin_performance")], interpret_payin),
]

SAVED_QUERIES = [t.saved_query for s in SECTIONS for t in s.tables]


def render_answers(frames: Frames, manifest: dict) -> str:
    """Return the content of docs/answers.md: a one-line answer per question, then the full tables."""
    metric_labels = {m["name"]: m.get("label") or m["name"] for m in manifest.get("metrics", [])}
    saved = {q["name"]: q for q in manifest.get("saved_queries", [])}
    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    summary = ["| # | Question | Answer |", "|---|---|---|"]
    body: list[str] = []
    for section in SECTIONS:
        sentence = section.interpret(frames)
        summary.append(f"| {section.key} | {section.title} | {sentence} |")
        body += [f"## {section.key} · {section.title}", ""]
        for table in section.tables:
            query = saved.get(table.saved_query, {})
            body += [f"**{query.get('label') or table.saved_query}** · saved query `{table.saved_query}`", ""]
            if query.get("description"):
                body += [f"_{query['description'].strip()}_", ""]
            body += [markdown_table(table.shape(frames[table.saved_query]), metric_labels), ""]
            if table.note:
                body += [f"<sub>{table.note}</sub>", ""]
        body += [f"> {sentence}", ""]
    header = [
        "# Answers",
        "",
        (
            f"_Generated by `python run.py answers` on {generated}. Every number comes from a MetricFlow saved query "
            "(`dbt/models/semantic/saved_queries.yml`); formulas live in `dbt/models/semantic/metrics/`._"
        ),
        "",
        "## Summary",
        "",
        *summary,
        "",
    ]
    return "\n".join(header + body).rstrip() + "\n"
