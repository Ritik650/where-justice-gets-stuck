"""Reconciliation checks on the real build. They skip when row-level Parquet is absent, as on a fresh clone.

The join checks exist because a left join keeps its row count even when matches are lost. An early version
narrowed the acts join by the last four digits of the case ID, silently lost about 4M links, and still passed
a row-count check.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from common import MART, PARQUET, connect, pq  # noqa: E402

needs_build = pytest.mark.skipif(not (PARQUET / "fact_case").exists(), reason="row-level build not present")


@pytest.fixture(scope="module")
def con():
    return connect(memory_limit="6GB")


@needs_build
def test_every_case_reaches_the_analysis_table(con):
    cases = con.execute(f"SELECT count(*) FROM read_parquet('{pq('cases/cases_*.parquet')}')").fetchone()[0]
    fact = con.execute(f"SELECT count(*) FROM read_parquet('{pq('fact_case/fact_case_*.parquet')}')").fetchone()[0]
    assert cases == fact == 80_935_944


@needs_build
def test_case_ids_are_unique(con):
    n, u = con.execute(f"SELECT count(*), count(DISTINCT ddl_case_id) FROM read_parquet('{pq('cases/cases_*.parquet')}')").fetchone()
    assert n == u


@needs_build
def test_act_links_are_not_lost_in_the_join(con):
    # The acts table also holds about 9M rows with IDs ending 2019 or 2020, which no case file contains.
    in_scope = con.execute(f"""
        SELECT count(*) FROM read_parquet('{pq('acts_sections.parquet')}')
        WHERE right(ddl_case_id, 4) NOT IN ('2019', '2020')
    """).fetchone()[0]
    linked = con.execute(f"SELECT count(*) FROM read_parquet('{pq('fact_case/fact_case_*.parquet')}') WHERE has_act_row").fetchone()[0]
    assert linked / in_scope > 0.97


@needs_build
def test_judge_links_are_not_lost_in_the_join(con):
    keys = con.execute(f"SELECT count(*) FROM read_parquet('{pq('keys/judge_case_merge_key.parquet')}')").fetchone()[0]
    linked = con.execute(f"SELECT count(*) FROM read_parquet('{pq('fact_case/fact_case_*.parquet')}') WHERE has_judge_row").fetchone()[0]
    assert linked / keys > 0.99


@needs_build
def test_judge_dates_parse(con):
    bad = con.execute(f"""
        SELECT count(*) FILTER (start_date IS NOT NULL AND TRY_STRPTIME(start_date, '%d-%m-%Y') IS NULL)
        FROM read_parquet('{pq('keys/judges_clean.parquet')}')
    """).fetchone()[0]
    assert bad == 0


@needs_build
def test_cino_is_never_stored(con):
    cols = con.execute(f"DESCRIBE SELECT * FROM read_parquet('{pq('cases/cases_2010.parquet')}')").df()["column_name"]
    assert "cino" not in set(cols)


@pytest.mark.skipif(not (MART / "headline.parquet").exists(), reason="mart not built")
def test_headline_adds_up():
    h = pd.read_parquet(MART / "headline.parquet").iloc[0]
    assert h.usable_rows + h.unusable_rows == h.total_rows
    assert h.closed_by_cutoff + h.open_at_cutoff == h.usable_rows


@pytest.mark.skipif(not (MART / "q1_stage.parquet").exists(), reason="mart not built")
def test_stage_counts_add_up_to_never_decided_usable_cases():
    q1 = pd.read_parquet(MART / "q1_stage.parquet")
    assert q1["share"].sum() == pytest.approx(1.0)
    assert q1["stuck_cases"].sum() <= pd.read_parquet(MART / "headline.parquet").iloc[0].never_decided


@pytest.mark.skipif(not (MART / "q5_districts.parquet").exists(), reason="mart not built")
def test_districts_cover_most_cases_and_population_is_positive():
    d = pd.read_parquet(MART / "q5_districts.parquet")
    h = pd.read_parquet(MART / "headline.parquet").iloc[0]
    assert d["total_cases"].sum() / h.total_rows > 0.99
    assert (d["population"] > 0).all()
    assert d["unit_id"].is_unique
