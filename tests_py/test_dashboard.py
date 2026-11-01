"""Dashboard smoke tests: every page renders without exceptions on the compiled SQL (Streamlit AppTest)."""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
PAGES = ["dashboard/app.py", *sorted(str(p.relative_to(ROOT)) for p in (ROOT / "dashboard" / "pages").glob("*.py"))]


@pytest.fixture(scope="module", autouse=True)
def compiled_sql(warehouse):
    if not any((ROOT / "dashboard" / "compiled").glob("*.sql")):
        pytest.skip("dashboard SQL not compiled: run `python run.py compile-metrics`")


@pytest.mark.parametrize("page", PAGES)
def test_page_renders(page):
    at = AppTest.from_file(str(ROOT / page), default_timeout=60).run()
    assert not at.exception, [e.value for e in at.exception]
    assert not at.info, [i.value for i in at.info]  # data-unavailable messages
    assert len(at.get("plotly_chart")) > 0


def test_overview_filters_pick_the_matching_grain():
    at = AppTest.from_file(str(ROOT / "dashboard/app.py"), default_timeout=60).run()
    all_volume = at.metric[0].value
    at.selectbox[0].select("cash").run()
    at.selectbox[1].select("MX").run()
    assert not at.exception
    assert at.metric[0].value != all_volume
