"""Drives the real Streamlit app through every page, view and control, and fails on any exception."""
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "dashboard" / "app.py"
MART = ROOT / "data" / "mart"
VIEWS = ["District map", "Where cases get stuck", "How long justice takes", "Which laws clog the system",
         "Do judge transfers slow cases", "Women in court", "When the backlog clears", "How cases end", "First hearing", "What drives delay"]

pytestmark = pytest.mark.skipif(not (MART / "findings.json").exists(), reason="mart not built")


def start() -> AppTest:
    return AppTest.from_file(str(APP), default_timeout=180).run()


def page(name: str) -> AppTest:
    at = start()
    at.switch_page(f"app_pages/{name}.py")
    return at.run()


def select(at: AppTest, view: str) -> AppTest:
    at.segmented_control(key="question").set_value(view)
    return at.run()


def metric(at: AppTest, label: str):
    return next(m for m in at.metric if m.label == label)


def test_opens_on_the_map_with_four_kpis():
    at = start()
    assert not at.exception
    assert at.title[0].value == "Where Justice Gets Stuck"
    assert at.metric[0].label == "Cases analysed"


@pytest.mark.parametrize("view", VIEWS)
def test_every_question_renders_without_error(view):
    at = select(start(), view)
    assert not at.exception, at.exception
    assert any("Finding." in m.value for m in at.markdown), "each view leads with its finding"


def test_map_controls():
    at = start()
    for chosen in at.selectbox(key="map_metric").options:
        at.selectbox(key="map_metric").set_value(chosen)
        at = at.run()
        assert not at.exception, chosen
    at.selectbox(key="map_state").set_value("Bihar")
    at = at.run()
    assert not at.exception
    at.segmented_control(key="map_order").set_value("Fastest")
    assert not at.run().exception


def test_survival_groups_keep_their_colours_when_the_selection_changes():
    at = select(start(), "How long justice takes")
    at.multiselect(key="q2_groups_Case category").set_value(["Civil suit", "Bail"])
    at = at.run()
    assert not at.exception
    assert at.session_state["q2_slots_Case category"]["Civil suit"] == 0
    for option in ["State", "Filing year", "What counts as closed"]:
        at.segmented_control(key="q2_dim").set_value(option)
        at = at.run()
        assert not at.exception, option


def test_stage_filters():
    at = select(start(), "Where cases get stuck")
    at.segmented_control(key="q1_family").set_value("Civil")
    at = at.run()
    assert not at.exception
    at.selectbox(key="q1_state").set_value("Bihar")
    assert not at.run().exception


def test_women_roles():
    at = select(start(), "Women in court")
    for role in ["Petitioner", "Defendant", "Defendant's advocate"]:
        at.segmented_control(key="q6_role").set_value(role)
        at = at.run()
        assert not at.exception, role


def test_law_tables():
    at = select(start(), "Which laws clog the system")
    at.segmented_control(key="q3_table").set_value("Largest sections")
    assert not at.run().exception


def test_outcomes_by_state():
    at = select(start(), "How cases end")
    at.segmented_control(key="q8_dim").set_value("State")
    assert not at.run().exception


def test_scenario_arithmetic():
    """The calculator must agree with a hand calculation, and say "Never" when filings outrun disposals."""
    q7 = pd.read_parquet(MART / "q7_backlog.parquet").set_index("njdg_state")
    row = q7.loc["Gujarat"]
    at = select(start(), "When the backlog clears")
    at.selectbox(key="scenario_state").set_value("Gujarat")
    at.slider(key="scenario_disposals").set_value(50)
    at.slider(key="scenario_filings").set_value(0)
    at = at.run()
    assert not at.exception
    net = row["closed_per_year"] * 1.5 - row["filed_per_year"]
    assert metric(at, "Years to clear").value == f"{row['pending_total'] / net:,.1f}"
    at.slider(key="scenario_disposals").set_value(-20)
    at = at.run()
    assert metric(at, "Years to clear").value == "Never"


def test_state_profile_works_for_every_state():
    states = pd.read_parquet(MART / "q2_km_summary.parquet").query("dimension == 'State'")["grp"].dropna().unique()
    at = page("state_profile")
    assert not at.exception, at.exception
    for state in states:
        at.selectbox(key="profile_state").set_value(state)
        at = at.run()
        assert not at.exception, state


@pytest.mark.parametrize("view", ["Scorecard", "Rules", "Issue log", "Coverage"])
def test_data_quality_views(view):
    at = page("data_quality")
    at.segmented_control(key="dq_view").set_value(view)
    at = at.run()
    assert not at.exception, at.exception


def test_issue_search_filters():
    at = page("data_quality")
    at.segmented_control(key="dq_view").set_value("Issue log")
    at = at.run()
    at.text_input(key="issue_search").set_value("bail")
    at = at.run()
    assert not at.exception


def test_methods_page_shows_the_methods_file():
    at = page("methods")
    assert not at.exception
    assert any("Why one cut-off date" in m.value for m in at.markdown)
