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
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DBT_DIR = ROOT / "dbt"
WAREHOUSE_DIR = ROOT / "warehouse"
DEFAULT_DB_PATH = WAREHOUSE_DIR / "felix.duckdb"
DATA_DIR = ROOT / "data"
SOURCE_DIR = DATA_DIR / "source"  # untouched baseline extract, never modified
TEST_BATCHES_DIR = DATA_DIR / "test_batches"  # never modified
LANDING_DIR = DATA_DIR / "landing"  # working copy read by the loader (git-ignored)
SEMANTIC_MANIFEST = DBT_DIR / "target" / "semantic_manifest.json"
ANSWERS_MD = ROOT / "docs" / "answers.md"
README = ROOT / "README.md"
ANSWERS_START, ANSWERS_END = "<!-- ANSWERS:START -->", "<!-- ANSWERS:END -->"
COMPILED_DIR = ROOT / "dashboard" / "compiled"


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


# --------------------------------------------------------------------------------------
# MetricFlow helpers (shared by `answers`, `compile-metrics` and tests_py)
# --------------------------------------------------------------------------------------
def mf_query(
    saved_query: str | None = None,
    metrics: list[str] | None = None,
    group_by: list[str] | None = None,
    where: str | None = None,
):
    """Run `mf query ... --csv` inside dbt/ and return a pandas DataFrame. Raises RuntimeError on failure."""
    import pandas as pd

    args = ["query"]
    if saved_query:
        args += ["--saved-query", saved_query]
    if metrics:
        args += ["--metrics", ",".join(metrics)]
    if group_by:
        args += ["--group-by", ",".join(group_by)]
    if where:
        args += ["--where", where]
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "result.csv"
        result = subprocess.run(
            [find_tool("mf"), *args, "--csv", str(out), "--quiet"],
            cwd=DBT_DIR, env=tool_env(), capture_output=True, text=True, encoding="utf-8", check=False,
        )
        if result.returncode != 0 or not out.exists():
            raise RuntimeError(f"mf {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}")
        return pd.read_csv(out)


def strip_explain_header(output: str) -> str:
    """`mf query --explain` prints spinner lines and a `🔎 SQL (...):` header before the SQL.
    Keep only the SQL: everything after the first blank line that follows the header."""
    lines = output.replace("\r", "\n").splitlines()
    header = next((i for i, line in enumerate(lines) if "SQL (" in line), None)
    if header is None:
        raise RuntimeError(f"unexpected `mf --explain` output (no SQL header):\n{output}")
    body = lines[header + 1 :]
    while body and not body[0].strip():
        body = body[1:]
    sql = "\n".join(body).strip()
    if not sql.upper().startswith(("WITH", "SELECT")):
        raise RuntimeError(f"unexpected `mf --explain` output (SQL not found):\n{output}")
    return sql + "\n"


def mf_explain_sql(saved_query: str) -> str:
    """SQL that MetricFlow generates for a saved query (DuckDB dialect)."""
    result = subprocess.run(
        [find_tool("mf"), "query", "--saved-query", saved_query, "--explain"],
        cwd=DBT_DIR, env=tool_env(), capture_output=True, text=True, encoding="utf-8", check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"mf query --saved-query {saved_query} --explain failed:\n{result.stdout}\n{result.stderr}")
    return strip_explain_header(result.stdout)


def load_semantic_manifest() -> dict:
    if not SEMANTIC_MANIFEST.exists():
        dbt("parse")
    return json.loads(SEMANTIC_MANIFEST.read_text(encoding="utf-8"))


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
    """Write the SQL of every saved query to dashboard/compiled/<name>.sql. The dashboard runs these files on a
    read-only DuckDB connection and never calls MetricFlow at runtime."""
    dbt("parse")  # refresh target/semantic_manifest.json
    names = [q["name"] for q in load_semantic_manifest()["saved_queries"]]
    COMPILED_DIR.mkdir(parents=True, exist_ok=True)
    for old in COMPILED_DIR.glob("*.sql"):
        old.unlink()
    for name in names:
        print(f"  mf query --saved-query {name} --explain", flush=True)
        header = f"-- Generated by `python run.py compile-metrics` from saved query `{name}`. Do not edit.\n"
        (COMPILED_DIR / f"{name}.sql").write_text(header + mf_explain_sql(name), encoding="utf-8")
    print(f"Compiled {len(names)} saved queries to {COMPILED_DIR.relative_to(ROOT)}/")


def cmd_answers(_: argparse.Namespace) -> None:
    """Run every saved query used by the answers and write docs/answers.md + the README block."""
    from scripts.render_answers import SAVED_QUERIES, render_answers

    dbt("parse")  # refresh target/semantic_manifest.json
    frames = {}
    for name in SAVED_QUERIES:
        print(f"  mf query --saved-query {name}", flush=True)
        frames[name] = mf_query(saved_query=name)
    answers_md, readme_block = render_answers(frames, load_semantic_manifest())
    ANSWERS_MD.write_text(answers_md, encoding="utf-8")
    readme = README.read_text(encoding="utf-8")
    start, end = readme.index(ANSWERS_START) + len(ANSWERS_START), readme.index(ANSWERS_END)
    README.write_text(readme[:start] + "\n" + readme_block + "\n" + readme[end:], encoding="utf-8")
    print(f"Wrote {ANSWERS_MD.relative_to(ROOT)} and the README answers block ({len(frames)} saved queries).")


def cmd_dashboard(_: argparse.Namespace) -> None:
    if not any(COMPILED_DIR.glob("*.sql")):
        cmd_compile_metrics(_)
    run(["streamlit", "run", "dashboard/app.py", "--browser.gatherUsageStats", "false"], cwd=ROOT)


def cmd_test(_: argparse.Namespace) -> None:
    dbt("test")
    run([sys.executable, "-m", "pytest", "tests_py", "-q"], cwd=ROOT)


def cmd_lint(_: argparse.Namespace) -> None:
    not_implemented("lint", 8)


def cmd_validate_metrics() -> None:
    run(["mf", "validate-configs"])


def cmd_all(args: argparse.Namespace) -> None:
    cmd_reset_data(args)
    cmd_replay(args)
    cmd_build(args)
    cmd_validate_metrics()
    cmd_compile_metrics(args)
    cmd_answers(args)


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
    ("all", "reset-data, replay, build, mf validate-configs, compile-metrics, answers", cmd_all),
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
