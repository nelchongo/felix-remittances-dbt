#!/usr/bin/env python3
"""Load landing CSVs into the DuckDB `raw` schema (no dbt seeds).

Layout read:   data/landing/<table>/<table>__<batch>.csv   (one folder per table, one file per batch)
Tables:        raw.users, raw.payments, raw.receipts, raw.disbursements

File-level incremental load, tracked in raw._ingestion_log (one row per loaded file):
    * new file           -> insert its rows
    * changed file (MD5) -> delete that file's rows and insert them again
    * missing file       -> delete its rows
Every value is loaded as text (`all_varchar`). Typing and cleaning happen in dbt staging.
Each row gets lineage columns: _source_file, _file_md5, _batch_id (the `__<batch>` suffix), _loaded_at (UTC).
A file with a new column adds that column to the raw table (older rows get NULL).

Replay (`--replay monthly`), first load only: rows are inserted month by month in the order of
coalesce(updated_at, created_at), and a callback runs after each step. run.py uses it to run
`dbt snapshot`, so the SCD2 snapshots get a real version history from the baseline extract.
A snapshot only sees the latest version of a record when it runs, so for tables in VERSIONED_KEYS
(users) a month is split into passes: pass k inserts each record's k-th version of that month.
Most KYC approvals land days after sign-up, and without passes the monthly snapshot would miss them.
The snapshots use the timestamp strategy (business-time validity), so the extra runs do not distort history.

Usage:
    python scripts/load_raw.py [--db warehouse/felix.duckdb] [--landing data/landing] [--replay monthly]
"""

from __future__ import annotations

import argparse
import hashlib
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = Path(os.environ.get("DUCKDB_PATH", ROOT / "warehouse" / "felix.duckdb"))
DEFAULT_LANDING = ROOT / "data" / "landing"

TABLES = ("users", "payments", "receipts", "disbursements")
SCHEMA = "raw"
LOG_TABLE = f"{SCHEMA}._ingestion_log"
# Month a row belongs to during replay: YYYY-MM prefix of updated_at (or created_at). Both source
# timestamp formats (ISO `...Z` and `YYYY-MM-DD HH:MM:SS`) start with it. Unparseable values sort last.
UNPARSEABLE_MONTH = "9999-12"
# Tables whose successive versions inside one replay month are fed in separate passes (key column).
VERSIONED_KEYS = {"users": "user_id"}
TIMESTAMP_FORMATS = "['%Y-%m-%dT%H:%M:%S.%gZ', '%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%d %H:%M:%S']"

MonthCallback = Callable[[str], None]


@dataclass
class TableSummary:
    table: str
    new: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    unchanged: int = 0
    rows_inserted: int = 0
    rows_deleted: int = 0
    rows_total: int = 0


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------
def file_md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def batch_id_from(path: Path) -> str:
    """`payments__2026-07.csv` -> `2026-07`. A file without the suffix uses its stem."""
    stem = path.stem
    return stem.split("__", 1)[1] if "__" in stem else stem


def display(path: Path) -> str:
    """Repo-relative path for messages when possible."""
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def csv_scan(path: Path) -> str:
    """SQL for reading one landing file, every column as text."""
    literal = str(path).replace("'", "''")
    return f"read_csv('{literal}', all_varchar = true, header = true, delim = ',', quote = '\"')"


def ensure_log(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(f"create schema if not exists {SCHEMA}")
    con.execute(
        f"""
        create table if not exists {LOG_TABLE} (
            table_name varchar not null,
            file_name  varchar not null,
            file_md5   varchar not null,
            row_count  bigint  not null,
            batch_id   varchar not null,
            loaded_at  timestamp not null
        )
        """
    )


def table_exists(con: duckdb.DuckDBPyConnection, table: str) -> bool:
    return bool(
        con.execute(
            "select count(*) from information_schema.tables where table_schema = ? and table_name = ?",
            [SCHEMA, table],
        ).fetchone()[0]
    )


def prepare_table(con: duckdb.DuckDBPyConnection, table: str, path: Path) -> list[str]:
    """Create raw.<table> if needed and add any column the file has that the table lacks.

    Returns the file's columns (in file order).
    """
    file_cols = [row[0] for row in con.execute(f"describe select * from {csv_scan(path)}").fetchall()]
    target = f"{SCHEMA}.{quote_ident(table)}"
    if not table_exists(con, table):
        cols_sql = ",\n".join(f"{quote_ident(c)} varchar" for c in file_cols)
        con.execute(
            f"""
            create table {target} (
                {cols_sql},
                _source_file varchar,
                _file_md5 varchar,
                _batch_id varchar,
                _loaded_at timestamp
            )
            """
        )
    else:
        existing = {
            row[0]
            for row in con.execute(
                "select column_name from information_schema.columns where table_schema = ? and table_name = ?",
                [SCHEMA, table],
            ).fetchall()
        }
        for col in file_cols:
            if col not in existing:
                print(f"  {table}: new column {col!r} found in {path.name}, adding it to {target}")
                con.execute(f"alter table {target} add column {quote_ident(col)} varchar")
    return file_cols


def month_key_sql(file_cols: list[str]) -> str:
    """SQL expression giving the replay month (YYYY-MM) of a row."""
    ts = "coalesce(nullif(trim(updated_at), ''), created_at)" if "updated_at" in file_cols else "created_at"
    key = f"left(trim({ts}), 7)"
    return f"coalesce(case when regexp_full_match({key}, '\\d{{4}}-\\d{{2}}') then {key} end, '{UNPARSEABLE_MONTH}')"


def replay_scan_sql(path: Path, file_cols: list[str], table: str) -> str:
    """The file's rows with `_replay_month` (YYYY-MM) and `_replay_pass` (1 unless the table is versioned)."""
    month = month_key_sql(file_cols)
    key = VERSIONED_KEYS.get(table)
    if key and key in file_cols and "updated_at" in file_cols:
        replay_pass = (
            f"dense_rank() over (partition by trim({quote_ident(key)}), _replay_month "
            f"order by try_strptime(trim(updated_at), {TIMESTAMP_FORMATS}) nulls last, updated_at)"
        )
    else:
        replay_pass = "1"
    return f"""(
        select *, {replay_pass} as _replay_pass
        from (select *, {month} as _replay_month from {csv_scan(path)})
    )"""


def insert_file(
    con: duckdb.DuckDBPyConnection,
    table: str,
    path: Path,
    md5: str,
    loaded_at: datetime,
    source_sql: str | None = None,
) -> int:
    """Insert a landing file (or the subset given by `source_sql`) into raw.<table>. Returns the row count."""
    sql = f"""
        insert into {SCHEMA}.{quote_ident(table)} by name
        select
            *,
            ? as _source_file,
            ? as _file_md5,
            ? as _batch_id,
            ? as _loaded_at
        from {source_sql or csv_scan(path)}
    """
    return con.execute(sql, [path.name, md5, batch_id_from(path), loaded_at]).fetchone()[0]


def delete_file_rows(con: duckdb.DuckDBPyConnection, table: str, file_name: str) -> int:
    if not table_exists(con, table):
        return 0
    return con.execute(
        f"delete from {SCHEMA}.{quote_ident(table)} where _source_file = ?", [file_name]
    ).fetchone()[0]


def write_log(
    con: duckdb.DuckDBPyConnection, table: str, path: Path, md5: str, rows: int, loaded_at: datetime
) -> None:
    con.execute(f"delete from {LOG_TABLE} where table_name = ? and file_name = ?", [table, path.name])
    con.execute(
        f"insert into {LOG_TABLE} values (?, ?, ?, ?, ?, ?)",
        [table, path.name, md5, rows, batch_id_from(path), loaded_at],
    )


def landing_files(landing: Path, table: str) -> dict[str, Path]:
    folder = landing / table
    return {p.name: p for p in sorted(folder.glob("*.csv"))} if folder.is_dir() else {}


def print_summary(summaries: list[TableSummary], title: str) -> None:
    print(f"\n{title}")
    header = f"  {'table':<14}{'new':>5}{'changed':>9}{'removed':>9}{'unchanged':>11}{'+rows':>9}{'-rows':>9}{'total':>9}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for s in summaries:
        print(
            f"  {s.table:<14}{len(s.new):>5}{len(s.changed):>9}{len(s.removed):>9}{s.unchanged:>11}"
            f"{s.rows_inserted:>9,}{s.rows_deleted:>9,}{s.rows_total:>9,}"
        )
    for s in summaries:
        for label, names in (("new", s.new), ("changed", s.changed), ("removed", s.removed)):
            for name in names:
                print(f"    {label:<8} {s.table}/{name}")


def table_count(con: duckdb.DuckDBPyConnection, table: str) -> int:
    if not table_exists(con, table):
        return 0
    return con.execute(f"select count(*) from {SCHEMA}.{quote_ident(table)}").fetchone()[0]


# --------------------------------------------------------------------------------------
# Incremental load
# --------------------------------------------------------------------------------------
def incremental_load(db_path: Path, landing: Path) -> list[TableSummary]:
    loaded_at = datetime.now(UTC).replace(tzinfo=None)
    summaries: list[TableSummary] = []
    with duckdb.connect(str(db_path)) as con:
        ensure_log(con)
        for table in TABLES:
            summary = TableSummary(table)
            files = landing_files(landing, table)
            logged = dict(
                con.execute(
                    f"select file_name, file_md5 from {LOG_TABLE} where table_name = ?", [table]
                ).fetchall()
            )

            for name in sorted(set(logged) - set(files)):  # removed from landing
                con.begin()
                summary.rows_deleted += delete_file_rows(con, table, name)
                con.execute(f"delete from {LOG_TABLE} where table_name = ? and file_name = ?", [table, name])
                con.commit()
                summary.removed.append(name)

            for name, path in files.items():
                md5 = file_md5(path)
                if logged.get(name) == md5:
                    summary.unchanged += 1
                    continue
                con.begin()
                if name in logged:  # content changed: reload the whole file
                    summary.rows_deleted += delete_file_rows(con, table, name)
                    summary.changed.append(name)
                else:
                    summary.new.append(name)
                prepare_table(con, table, path)
                rows = insert_file(con, table, path, md5, loaded_at)
                write_log(con, table, path, md5, rows, loaded_at)
                con.commit()
                summary.rows_inserted += rows

            summary.rows_total = table_count(con, table)
            summaries.append(summary)
    print_summary(summaries, f"Loaded {display(landing)} -> {display(db_path)} ({SCHEMA} schema)")
    return summaries


# --------------------------------------------------------------------------------------
# Monthly replay (first load only)
# --------------------------------------------------------------------------------------
def is_first_load(db_path: Path) -> bool:
    if not db_path.exists():
        return True
    with duckdb.connect(str(db_path)) as con:
        ensure_log(con)
        return con.execute(f"select count(*) from {LOG_TABLE}").fetchone()[0] == 0


def replay_monthly(db_path: Path, landing: Path, on_month: MonthCallback | None = None) -> list[TableSummary]:
    """First load, month by month. The DuckDB connection is closed before each callback so that
    another process (dbt) can open the database."""
    loaded_at = datetime.now(UTC).replace(tzinfo=None)
    files = {table: landing_files(landing, table) for table in TABLES}

    # 1. Create the tables and find every month (and the passes it needs) in the landing files.
    plan: dict[str, list[tuple[Path, str, str]]] = {}  # table -> [(path, md5, replay_scan_sql)]
    passes: dict[str, int] = {}  # month -> number of passes
    with duckdb.connect(str(db_path)) as con:
        ensure_log(con)
        for table, table_files in files.items():
            plan[table] = []
            for path in table_files.values():
                scan = replay_scan_sql(path, prepare_table(con, table, path), table)
                plan[table].append((path, file_md5(path), scan))
                for month, n in con.execute(
                    f"select _replay_month, max(_replay_pass) from {scan} group by 1"
                ).fetchall():
                    passes[month] = max(passes.get(month, 1), n)
    ordered = sorted(m for m in passes if m != UNPARSEABLE_MONTH)
    if not ordered:
        print("Nothing to replay: the landing folder has no rows.")
        return incremental_load(db_path, landing)
    # Rows with an unparseable timestamp go with the last month.
    last = ordered[-1]
    passes[last] = max(n for m, n in passes.items() if m >= last)
    print(
        f"Replaying {len(ordered)} months ({ordered[0]} -> {last}, {sum(passes[m] for m in ordered)} steps) "
        f"into {display(db_path)}"
    )

    # 2. Insert month by month, and pass by pass inside a month.
    try:
        for month in ordered:
            month_filter = f"_replay_month >= '{month}'" if month == last else f"_replay_month = '{month}'"
            for replay_pass in range(1, passes[month] + 1):
                inserted = 0
                with duckdb.connect(str(db_path)) as con:
                    con.begin()
                    for table, entries in plan.items():
                        for path, md5, scan in entries:
                            subset = (
                                f"(select * exclude (_replay_month, _replay_pass) from {scan} "
                                f"where {month_filter} and _replay_pass = {replay_pass})"
                            )
                            inserted += insert_file(con, table, path, md5, loaded_at, subset)
                    con.commit()
                step = month if passes[month] == 1 else f"{month} pass {replay_pass}/{passes[month]}"
                print(f"  {step}: {inserted:,} rows", flush=True)
                if on_month:
                    on_month(step)
    except BaseException:
        print("Replay failed: removing the partially loaded rows so the next load starts clean.")
        with duckdb.connect(str(db_path)) as con:
            for table, entries in plan.items():
                for path, _, _ in entries:
                    delete_file_rows(con, table, path.name)
        raise

    # 3. Record the files only once every month is in.
    summaries: list[TableSummary] = []
    with duckdb.connect(str(db_path)) as con:
        for table, entries in plan.items():
            summary = TableSummary(table)
            for path, md5, _ in entries:
                rows = con.execute(
                    f"select count(*) from {SCHEMA}.{quote_ident(table)} where _source_file = ?", [path.name]
                ).fetchone()[0]
                write_log(con, table, path, md5, rows, loaded_at)
                summary.new.append(path.name)
                summary.rows_inserted += rows
            summary.rows_total = table_count(con, table)
            summaries.append(summary)
    print_summary(summaries, f"Replayed {display(landing)} -> {display(db_path)} ({SCHEMA} schema)")
    return summaries


def load(
    db_path: Path = DEFAULT_DB,
    landing: Path = DEFAULT_LANDING,
    replay: str | None = None,
    on_month: MonthCallback | None = None,
) -> list[TableSummary]:
    """Entry point used by run.py."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if not Path(landing).is_dir():
        raise SystemExit(f"error: {display(landing)} does not exist. Run `python run.py reset-data` first.")
    if replay == "monthly":
        if is_first_load(db_path):
            return replay_monthly(db_path, Path(landing), on_month)
        print("raw is already loaded: replay only applies to the first load, doing an incremental load.")
    return incremental_load(db_path, Path(landing))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="DuckDB file (default: $DUCKDB_PATH or warehouse/felix.duckdb)")
    parser.add_argument("--landing", type=Path, default=DEFAULT_LANDING, help="landing folder (default: data/landing)")
    parser.add_argument("--replay", choices=["monthly"], help="first load only: insert rows month by month")
    args = parser.parse_args()
    load(args.db, args.landing, args.replay)


if __name__ == "__main__":
    main()
