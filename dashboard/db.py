"""Data access for the dashboard: run SQL compiled by MetricFlow on a short-lived read-only DuckDB connection.

The dashboard never calls `mf` and never keeps a connection open, so `dbt build` can write between refreshes
(DuckDB allows one writer OR many readers). Results are cached for 60 seconds.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.render_answers import trim_empty_months  # noqa: E402  (shared presentation helper)

COMPILED = ROOT / "dashboard" / "compiled"
DB = Path(os.environ.get("DUCKDB_PATH", ROOT / "warehouse" / "felix.duckdb"))


class DataUnavailable(Exception):
    """The warehouse or the compiled SQL is missing, or dbt holds the write lock."""


@st.cache_data(ttl=60, show_spinner=False)
def saved_query(name: str) -> pd.DataFrame:
    sql_path = COMPILED / f"{name}.sql"
    if not DB.exists():
        raise DataUnavailable("The warehouse doesn't exist yet. Run `python run.py all` first.")
    if not sql_path.exists():
        raise DataUnavailable(f"`dashboard/compiled/{name}.sql` is missing. Run `python run.py compile-metrics`.")
    try:
        with duckdb.connect(str(DB), read_only=True) as con:
            df = con.execute(sql_path.read_text(encoding="utf-8")).fetch_df()
    except duckdb.IOException as exc:
        if "lock" in str(exc).lower():
            raise DataUnavailable("dbt is writing to the warehouse right now. Refresh in a few seconds.") from exc
        raise
    except duckdb.CatalogException as exc:
        raise DataUnavailable(f"The warehouse is missing a table ({exc}). Run `python run.py build`.") from exc
    if "metric_time__month" in df.columns:
        df["metric_time__month"] = pd.to_datetime(df["metric_time__month"])
        df = trim_empty_months(df)
    return df


def load(name: str) -> pd.DataFrame:
    """saved_query() for pages: show a friendly message and stop the page when data is unavailable."""
    try:
        return saved_query(name)
    except DataUnavailable as exc:
        st.info(str(exc), icon="ℹ️")
        st.stop()
