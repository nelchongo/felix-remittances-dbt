"""Semantic-layer smoke and reconciliation tests.

Run after a build (`python run.py all`, then `python run.py test`). They check that every saved query
returns rows and that MetricFlow's formulas reconcile with the ingredients stored in the facts.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from scripts.render_answers import SAVED_QUERIES


def saved_query_names() -> list[str]:
    import json

    import run

    if run.SEMANTIC_MANIFEST.exists():
        return [q["name"] for q in json.loads(run.SEMANTIC_MANIFEST.read_text())["saved_queries"]]
    return SAVED_QUERIES


@pytest.mark.parametrize("name", saved_query_names())
def test_every_saved_query_returns_rows(mf, manifest, warehouse, name):
    df = mf(saved_query=name)
    assert not df.empty, f"saved query {name} returned no rows"


def test_answers_cover_every_question(manifest):
    names = {q["name"] for q in manifest["saved_queries"]}
    for prefix in ("q1_", "q2_", "q3_", "q4_", "q5_", "q6_", "q7_", "q8_", "growth_kpis_monthly", "payin_performance"):
        assert any(n.startswith(prefix) for n in names), f"no saved query for {prefix}"


def test_every_metric_has_label_and_description(manifest):
    missing = [m["name"] for m in manifest["metrics"] if not m.get("label") or not m.get("description")]
    assert not missing, f"metrics without label/description: {missing}"


def test_gross_volume_reconciles_with_fct_payments(mf, warehouse):
    total = mf(metrics=["gross_volume_usd"])["gross_volume_usd"].iloc[0]
    expected = warehouse.one(
        "select sum(send_amount_usd) from finance.fct_payments where is_succeeded"
    )[0]
    assert total == pytest.approx(float(expected), abs=0.01)


def test_net_revenue_reconciles_with_fct_payments(mf, warehouse):
    total = mf(metrics=["net_revenue_usd"])["net_revenue_usd"].iloc[0]
    expected = warehouse.one(
        "select sum(fee_revenue_usd + fx_revenue_usd - chargeback_loss_usd) from finance.fct_payments"
    )[0]
    assert total == pytest.approx(float(expected), abs=0.01)


def test_monthly_arpu_times_active_senders_equals_net_revenue(mf):
    df = mf(metrics=["arpu_usd", "active_senders", "net_revenue_usd"], group_by=["metric_time__month"])
    df = df[df["active_senders"] > 0]
    assert len(df) >= 12
    product = df["arpu_usd"] * df["active_senders"]
    assert product.to_numpy() == pytest.approx(df["net_revenue_usd"].to_numpy(), abs=0.01)


def test_active_senders_is_recomputed_per_grain(mf):
    """A quarter's distinct senders is not the sum of its months (that would double count)."""
    monthly = mf(metrics=["active_senders"], group_by=["metric_time__month"]).dropna()
    quarterly = mf(metrics=["active_senders"], group_by=["metric_time__quarter"]).dropna()
    assert quarterly["active_senders"].sum() < monthly["active_senders"].sum()


def test_chargeback_rate_is_null_or_zero_for_cash(mf):
    df = mf(metrics=["chargeback_rate"], group_by=["payment__payment_method"])
    cash = df.loc[df["payment__payment_method"] == "cash", "chargeback_rate"]
    assert cash.empty or all(pd.isna(v) or v == 0 for v in cash)
    card = df.loc[df["payment__payment_method"] == "debit_card", "chargeback_rate"].iloc[0]
    assert 0 < card < 0.05


def test_chargeback_rate_matches_fct_payments(mf, warehouse):
    rate = mf(metrics=["chargeback_rate"])["chargeback_rate"].iloc[0]
    charged, succeeded = warehouse.one(
        "select sum(is_charged_back::int), sum(is_succeeded::int) from finance.fct_payments "
        "where payment_method = 'debit_card'"
    )
    assert rate == pytest.approx(charged / succeeded)


def test_top_volume_segment_holds_half_the_volume(mf):
    df = mf(saved_query="q2_volume_concentration").set_index("user__volume_segment")
    share = df.loc["top_50pct", "gross_volume_usd"] / df["gross_volume_usd"].sum()
    assert share >= 0.5


def test_yoy_matches_the_definition(mf):
    df = mf(metrics=["gross_volume_usd", "gross_volume_usd_yoy_pct"], group_by=["metric_time__month"])
    df = df.dropna(subset=["metric_time__month"]).set_index("metric_time__month").sort_index()
    df.index = pd.to_datetime(df.index)
    month = df.index[df["gross_volume_usd"] > 0].max()
    prior = month - pd.DateOffset(years=1)
    expected = (df.loc[month, "gross_volume_usd"] - df.loc[prior, "gross_volume_usd"]) / df.loc[prior, "gross_volume_usd"]
    assert math.isclose(df.loc[month, "gross_volume_usd_yoy_pct"], expected, rel_tol=1e-9)
