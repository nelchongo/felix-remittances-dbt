# Félix Remittances: dbt + DuckDB take-home

[![ci](https://github.com/nelchongo/felix-remittances-dbt/actions/workflows/ci.yml/badge.svg)](https://github.com/nelchongo/felix-remittances-dbt/actions/workflows/ci.yml)

Data Engineering Manager take-home for Félix Pago ([brief](docs/ASSIGNMENT.md)). This page is the step-by-step
guide to run and review it. The answers are in [`docs/answers.md`](docs/answers.md), and the architecture and
decisions are in [`docs/DESIGN.md`](docs/DESIGN.md).

## 1. Install (about 1 minute)

You need Python 3.11 or newer (CI tests 3.11 and 3.13) and git. You don't need a database server or Docker:
the warehouse is a DuckDB file.

```bash
git clone https://github.com/nelchongo/felix-remittances-dbt.git
cd felix-remittances-dbt
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run.py setup              # dbt deps + dbt debug, which ends with "All checks passed!"
```

## 2. Build the warehouse (about 4 minutes)

```bash
python run.py all
```

This one command does what the brief asks, in order:

| Brief step | What runs | Where |
|---|---|---|
| Ingest the CSVs as raw data, **no seeds** | a Python loader writes the CSVs as text into schema `raw`, month by month | `src/load_raw.py` |
| First layer: dedupe and schema patterns | `dbt build` staging models: types, normalised codes, CDC dedupe | `dbt/models/staging/` |
| Intermediate layer by business context | payment lifecycle, remittance joins, provider reliability, sender clusters | `dbt/models/intermediate/` |
| Data modelling | Kimball marts (`core`, `finance`, `operations`, `growth`, `risk`) and SCD2 snapshots | `dbt/models/marts/`, `dbt/snapshots/` |
| Metrics | MetricFlow metrics and saved queries, written to `docs/answers.md` | `dbt/models/semantic/` |
| Data tests | about 250 dbt tests run inside `dbt build` | YAML next to each model, `dbt/tests/` |

The run should end with `Done. PASS=289 WARN=1 ERROR=0` and `Wrote docs/answers.md`. The one warning is
intentional: the source data has 4 receipts whose payment doesn't exist.

## 3. Read the answers

Open [`docs/answers.md`](docs/answers.md). It starts with a one-line answer per question, then gives the full
table for each one and names the saved query that produced it. The six metrics from the brief are Q1–Q6.
Q7–Q8, Growth and Pay-in are extras (ATV, LTV, ARPU, MoM/YoY, pay-in performance).

## 4. Open the dashboard

```bash
python run.py dashboard          # http://localhost:8501 (Ctrl+C to stop)
```

The dashboard has one tab per question. It reads the same saved queries as `docs/answers.md`, and every chart has
a table view under it.

![Dashboard](docs/img/dashboard.png)

## 5. Run the checks (what CI runs on every pull request)

```bash
python run.py test               # dbt test + pytest (MetricFlow reconciles with the facts; the dashboard renders)
python run.py lint               # ruff on Python, sqlfluff on dbt SQL
python run.py check-incremental  # loads the monthly batches with late rows: incremental facts = full refresh
python run.py check-edge-cases   # loads 6 bad rows: exactly 7 tests must fail and 1 must warn
python run.py all                # rebuild from the clean baseline (the two checks leave their data loaded)
```

[`docs/DESIGN.md` §15](docs/DESIGN.md) explains which row breaks which test and how the incremental facts work.

## 6. Optional: load new monthly data

```bash
python run.py add-batch 2026-07  # also 2026-08 and 2026-09: load, SCD2 snapshot and incremental build
python run.py answers            # refresh docs/answers.md with the new months
```

## 7. Optional: query by hand

`run.py` sets these variables for you. Export them to use dbt or MetricFlow directly, as absolute paths from the
repo root:

```bash
export DBT_PROJECT_DIR=$PWD/dbt DBT_PROFILES_DIR=$PWD/dbt DUCKDB_PATH=$PWD/warehouse/felix.duckdb DO_NOT_TRACK=1
dbt build --select staging+
cd dbt && mf query --metrics gross_volume_usd,gross_volume_usd_yoy_pct --group-by metric_time__month
```

`python run.py --help` lists every command, and `python run.py reset-data` deletes the warehouse and restores the
original data.

## Making changes

Nobody pushes to `main` directly. Push a branch and open a pull request: CI runs steps 2 and 5 on Python 3.11
and 3.13, and the pull request merges only when both checks are green.
