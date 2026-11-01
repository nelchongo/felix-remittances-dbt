"""Dashboard smoke test: every tab renders without errors on the compiled SQL (Streamlit AppTest)."""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_renders_every_tab(warehouse):
    if not any((ROOT / "dashboard" / "compiled").glob("*.sql")):
        pytest.skip("dashboard SQL not compiled: run `python run.py compile-metrics`")
    at = AppTest.from_file(str(ROOT / "dashboard" / "app.py"), default_timeout=60).run()
    assert not at.exception, [e.value for e in at.exception]
    assert not at.info, [i.value for i in at.info]  # "run python run.py all" messages
    assert len(at.tabs) == 10
    assert len(at.get("plotly_chart")) >= 15
