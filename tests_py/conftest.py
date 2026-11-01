"""Shared fixtures: run.py's MetricFlow helper and a read-only DuckDB connection."""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import run


@pytest.fixture(scope="session")
def manifest() -> dict:
    run.dbt("parse")
    return run.load_semantic_manifest()


class Warehouse:
    """Short-lived read-only connections: DuckDB allows one writer OR many readers, and `mf` opens the
    file for writing, so a connection must never stay open while MetricFlow runs."""

    def __init__(self, path: Path):
        self.path = path

    def one(self, sql: str) -> tuple:
        with duckdb.connect(str(self.path), read_only=True) as con:
            return con.execute(sql).fetchone()


@pytest.fixture(scope="session")
def warehouse() -> Warehouse:
    path = run.db_path()
    if not path.exists():
        pytest.skip("warehouse not built: run `python run.py all` first")
    return Warehouse(path)


@pytest.fixture(scope="session")
def mf():
    return run.mf_query
