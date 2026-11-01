"""run.py behaviour that CI and reviewers rely on: no hanging menu without a terminal, branded dashboard."""

from __future__ import annotations

import json
import subprocess
import sys

import run


def test_no_command_without_a_terminal_prints_the_help():
    """`python run.py` opens the menu only for a person at a terminal; CI and pipes get the help instead."""
    result = subprocess.run([sys.executable, "run.py"], check=False, cwd=run.ROOT, stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0
    assert "usage: run.py" in result.stdout
    assert "Dashboard" not in result.stdout  # no background dashboard was started


def test_dashboard_command_applies_the_brand_theme_in_both_modes():
    command = run.dashboard_command()
    assert "--theme.light.backgroundColor=#fefcf9" in command  # linen
    assert "--theme.dark.backgroundColor=#082422" in command  # slate
    assert "--theme.dark.primaryColor=#2bf2f1" in command  # brand cyan


def test_pipeline_is_a_command():
    assert run.build_parser().parse_args(["pipeline"]).func is run.cmd_pipeline


def test_sequence_tags_cover_every_node_in_dag_order(manifest):
    """Every model and snapshot carries exactly one sequence tag, and no step depends on a later one."""
    nodes = json.loads((run.DBT_DIR / "target" / "manifest.json").read_text())["nodes"]
    order = [tag for tag, _ in run.SEQUENCE_TAGS]
    step = {}
    for uid, node in nodes.items():
        if node["resource_type"] in ("model", "snapshot"):
            tags = [tag for tag in node["tags"] if tag in order]
            assert len(tags) == 1, f"{node['name']} has sequence tags {tags}"
            step[uid] = order.index(tags[0])
    late = [(nodes[uid]["name"], nodes[parent]["name"]) for uid in step
            for parent in nodes[uid]["depends_on"]["nodes"] if parent in step and step[parent] > step[uid]]
    assert not late, f"nodes that depend on a later step: {late}"


def test_sequence_runs_every_test_exactly_once():
    """The per-step selection (`buildable`, `eager` on the last step) runs the same tests as one `dbt build`."""
    def tests(*selection: str) -> list[str]:
        result = subprocess.run([run.find_tool("dbt"), "--quiet", "ls", "--resource-type", "test", "unit_test",
                                 "--output", "name", *selection], check=True, cwd=run.DBT_DIR, env=run.tool_env(),
                                capture_output=True, text=True)
        return result.stdout.split()

    per_step = [name for tag, _ in run.SEQUENCE_TAGS for name in tests(
        "--select", f"tag:{tag}", "--indirect-selection", "eager" if tag == run.SEQUENCE_TAGS[-1][0] else "buildable")]
    assert sorted(per_step) == sorted(tests())
