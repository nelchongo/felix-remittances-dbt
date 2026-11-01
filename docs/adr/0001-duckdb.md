# ADR 0001: DuckDB as the warehouse

- **Status:** accepted
- **Date:** 2026-11-01

## Context
The brief allows "any database". Reviewers clone the repo and run it on their own machines, and the
assessment values a setup that works without infrastructure. The data is small (tens of thousands of rows),
but the project must still show warehouse patterns: schemas, incremental models, snapshots, contracts and a
semantic layer.

## Decision
Use **DuckDB** (a single file, `warehouse/felix.duckdb`) through `dbt-duckdb`, with the profile checked into
the repo. Everything runs from `python run.py`, with versions pinned in `requirements.txt`.

## Consequences
- Zero setup: `pip install -r requirements.txt` is the whole installation, on Windows, macOS and Linux.
- MetricFlow ships a DuckDB SQL renderer, so the semantic layer and its compiled SQL work locally.
- DuckDB allows **one writer or many readers**. The dashboard uses short-lived read-only connections and
  never calls `mf` at runtime; `mf` itself opens the file read-write, so no connection may stay open while it runs.
- Some SQL is DuckDB-specific (`qualify`, `union all by name`, `try_strptime`, `date_diff`). Moving to
  Snowflake or BigQuery is a profile swap plus small dialect changes in a handful of macros and models.
