#!/usr/bin/env python3
"""Single entry point for the Félix remittances project.

Runs anywhere with Python only (Windows, macOS, Linux): no shell scripts, no absolute paths,
no reliance on ~/.dbt. Every external tool (dbt, mf, streamlit, pytest, sqlfluff) is resolved
from the active Python environment and run with the project's environment variables:

    DBT_PROJECT_DIR = <repo>/dbt
    DBT_PROFILES_DIR = <repo>/dbt        (profiles.yml is checked into the repo)
    DUCKDB_PATH      = <repo>/warehouse/felix.duckdb   (unless already set)
    DO_NOT_TRACK     = 1

Usage:
    python run.py --help
    python run.py setup
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DBT_DIR = ROOT / "dbt"
WAREHOUSE_DIR = ROOT / "warehouse"
DEFAULT_DB_PATH = WAREHOUSE_DIR / "felix.duckdb"
DATA_DIR = ROOT / "data"
SOURCE_DIR = DATA_DIR / "source"  # untouched baseline extract, never modified
TEST_BATCHES_DIR = DATA_DIR / "test_batches"  # never modified
LANDING_DIR = DATA_DIR / "landing"  # working copy read by the loader (git-ignored)


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------
def tool_env() -> dict[str, str]:
    """Environment for every child process (dbt, mf, streamlit, ...)."""
    env = os.environ.copy()
    env["DBT_PROJECT_DIR"] = str(DBT_DIR)
    env["DBT_PROFILES_DIR"] = str(DBT_DIR)
    env["DO_NOT_TRACK"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"  # mf prints emoji; keeps Windows consoles happy
    env.setdefault("DUCKDB_PATH", str(DEFAULT_DB_PATH))
    return env


def find_tool(name: str) -> str:
    """Resolve a console script, preferring the one installed next to this interpreter."""
    scripts_dir = Path(sys.executable).parent
    found = shutil.which(name, path=str(scripts_dir)) or shutil.which(name)
    if not found:
        sys.exit(
            f"error: '{name}' was not found. Activate the virtualenv and run "
            "`pip install -r requirements.txt` first."
        )
    return found


def run(cmd: list[str], cwd: Path = DBT_DIR) -> None:
    """Run a tool and stop the whole command on the first failure."""
    WAREHOUSE_DIR.mkdir(exist_ok=True)
    print(f"\n$ {' '.join(cmd)}", flush=True)
    result = subprocess.run([find_tool(cmd[0]), *cmd[1:]], cwd=cwd, env=tool_env(), check=False)
    if result.returncode != 0:
        sys.exit(result.returncode)


def dbt(*args: str) -> None:
    run(["dbt", *args])


def db_path() -> Path:
    return Path(tool_env()["DUCKDB_PATH"])


def require_landing() -> None:
    if not LANDING_DIR.is_dir():
        sys.exit("error: data/landing does not exist. Run `python run.py reset-data` first.")


def not_implemented(command: str, phase: int) -> None:
    sys.exit(f"`{command}` is not implemented yet (Phase {phase} of docs/IMPLEMENTATION_PLAN.md).")


# --------------------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------------------
def cmd_setup(_: argparse.Namespace) -> None:
    dbt("deps")
    dbt("debug")


def cmd_build(_: argparse.Namespace) -> None:
    dbt("build")


def cmd_snapshot(_: argparse.Namespace) -> None:
    dbt("snapshot")


def cmd_reset_data(_: argparse.Namespace) -> None:
    """data/landing <- data/source (as <table>/<table>__baseline.csv) and delete the warehouse."""
    from ingest.load_raw import TABLES

    if LANDING_DIR.exists():
        shutil.rmtree(LANDING_DIR)
    for table in TABLES:
        source = SOURCE_DIR / f"{table}.csv"
        if not source.is_file():
            sys.exit(f"error: {source.relative_to(ROOT)} is missing.")
        (LANDING_DIR / table).mkdir(parents=True)
        shutil.copy2(source, LANDING_DIR / table / f"{table}__baseline.csv")
    db = db_path()
    for path in (db, db.with_name(db.name + ".wal")):
        path.unlink(missing_ok=True)
    print(f"data/landing reset to the baseline ({len(TABLES)} tables). Deleted {db.name}.")


def cmd_load(_: argparse.Namespace) -> None:
    from ingest.load_raw import load

    require_landing()
    load(db_path(), LANDING_DIR)


def cmd_replay(_: argparse.Namespace) -> None:
    """First load month by month. After each month: dbt snapshot (staging/intermediate are views,
    so they are created once and then always see the rows loaded so far)."""
    from ingest.load_raw import load

    require_landing()
    views_built = False

    def after_month(month: str) -> None:
        nonlocal views_built
        if not views_built:
            dbt("run", "--select", "staging", "intermediate")
            views_built = True
        dbt("--quiet", "snapshot")

    load(db_path(), LANDING_DIR, replay="monthly", on_month=after_month)


def cmd_add_batch(args: argparse.Namespace) -> None:
    """Copy data/test_batches/<batch>/<table>.csv to data/landing/<table>/<table>__<batch>.csv,
    then load, snapshot and build."""
    from ingest.load_raw import TABLES, load

    batch_dir = TEST_BATCHES_DIR / args.batch
    if not batch_dir.is_dir():
        available = ", ".join(sorted(p.name for p in TEST_BATCHES_DIR.iterdir() if p.is_dir()))
        sys.exit(f"error: no test batch named {args.batch!r}. Available: {available}")
    require_landing()
    copied = []
    for table in TABLES:
        source = batch_dir / f"{table}.csv"
        if source.is_file():
            (LANDING_DIR / table).mkdir(exist_ok=True)
            shutil.copy2(source, LANDING_DIR / table / f"{table}__{args.batch}.csv")
            copied.append(table)
    print(f"Copied batch {args.batch!r} into data/landing: {', '.join(copied)}")
    load(db_path(), LANDING_DIR)
    dbt("snapshot")
    dbt("build")


def cmd_compile_metrics(_: argparse.Namespace) -> None:
    not_implemented("compile-metrics", 7)


def cmd_answers(_: argparse.Namespace) -> None:
    not_implemented("answers", 6)


def cmd_dashboard(_: argparse.Namespace) -> None:
    not_implemented("dashboard", 7)


def cmd_test(_: argparse.Namespace) -> None:
    not_implemented("test", 6)


def cmd_lint(_: argparse.Namespace) -> None:
    not_implemented("lint", 8)


def cmd_all(_: argparse.Namespace) -> None:
    not_implemented("all", 6)


COMMANDS: list[tuple[str, str, object]] = [
    ("setup", "install dbt packages (dbt deps) and check the connection (dbt debug)", cmd_setup),
    ("load", "load new/changed CSVs from data/landing into the raw schema", cmd_load),
    ("replay", "first load month by month with `dbt snapshot` after each month (SCD2 history)", cmd_replay),
    ("build", "dbt build: models, snapshots and tests", cmd_build),
    ("snapshot", "dbt snapshot", cmd_snapshot),
    ("add-batch", "copy a test batch into landing, load it, snapshot and build", cmd_add_batch),
    ("reset-data", "restore data/landing from data/source and delete the warehouse", cmd_reset_data),
    ("compile-metrics", "compile the dashboard's saved queries to dashboard/compiled/*.sql", cmd_compile_metrics),
    ("answers", "run the saved queries and write docs/answers.md + the README answers block", cmd_answers),
    ("dashboard", "start the Streamlit dashboard", cmd_dashboard),
    ("test", "dbt test + pytest tests_py", cmd_test),
    ("lint", "sqlfluff lint dbt/models", cmd_lint),
    ("all", "reset-data, replay, build, validate metrics, compile metrics, answers", cmd_all),
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run.py",
        description="Félix remittances: dbt + DuckDB + MetricFlow pipeline runner.",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")
    for name, help_text, func in COMMANDS:
        p = sub.add_parser(name, help=help_text, description=help_text)
        if name == "add-batch":
            p.add_argument("batch", help="folder name under data/test_batches/ (e.g. 2026-07, edge_cases)")
        p.set_defaults(func=func)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
