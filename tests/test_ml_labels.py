"""Label edge cases, run through the real label view (sql/labels.sql) on hand-built cases.

T_end is 2018-12-31 and the windows are 730 and 365 days, as in config.yaml.
"""
from datetime import date, timedelta

import pandas as pd
import pytest
from ml_helpers import settings_in, write_cases

from src.ml.db import connect, create_label_view
from src.ml.dq import parse_checks
from src.ml.settings import SQL_DIR

FILED = date(2015, 3, 10)


def d(days: int) -> date:
    return FILED + timedelta(days=days)


CASES = {
    # id: (filing, decision, disposition code, expected usable, eligible_24m, label_24m, label_12m)
    "same_day": (FILED, FILED, 3, True, True, 1, 1),
    "day_365": (FILED, d(365), 3, True, True, 1, 1),
    "day_366": (FILED, d(366), 3, True, True, 1, 0),
    "day_730": (FILED, d(730), 3, True, True, 1, 0),
    "day_731": (FILED, d(731), 3, True, True, 0, 0),
    "never_decided": (FILED, None, 7, True, True, 0, 0),
    "decided_after_t_end": (FILED, date(2019, 6, 1), 3, True, True, 0, 0),
    "outcome_without_date": (FILED, None, 3, True, True, 0, 0),
    "transferred_in_window": (FILED, d(100), 4, True, True, 1, 1),
    "decided_after_collection": (FILED, date(2025, 1, 1), 3, False, True, None, None),
    "decided_before_filing": (FILED, d(-30), 3, False, True, None, None),
    "no_filing_date": (None, d(10), 3, False, False, None, None),
    "filed_outside_years": (date(2009, 12, 31), None, 7, False, True, None, None),
    "last_eligible_day": (date(2016, 12, 31), date(2018, 12, 31), 3, True, True, 1, 0),
    "first_ineligible_day": (date(2017, 1, 1), None, 7, True, False, 0, 0),
    "leap_year_filing": (date(2016, 2, 29), date(2016, 2, 29) + timedelta(days=730), 3, True, True, 1, 0),
    "suspect_district": (FILED, d(10), 3, True, True, 1, 1),
}


@pytest.fixture(scope="module")
def labels(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("labels")
    rows = []
    for case_id, (filed, decided, disp, *_rest) in CASES.items():
        rows.append({"ddl_case_id": case_id, "date_of_filing": filed, "date_of_decision": decided, "disp_name": disp,
                     "dist_code": "04" if case_id == "suspect_district" else "01", "state_code": "92" if case_id == "suspect_district" else "91"})
    write_cases(tmp / "parquet", rows)
    s = settings_in(tmp)
    # The district flag is read from q5_districts through dim_district, as on the real data.
    pd.DataFrame({"state_code": ["91", "92"], "dist_code": ["01", "04"], "unit_id": pd.array([1, 2], dtype="Int64")}).to_parquet(
        tmp / "parquet" / "maps" / "dim_district.parquet", index=False)
    pd.DataFrame({"unit_id": [1, 2], "suspect_closure_records": [False, True]}).to_parquet(s.district_flags, index=False)
    con = connect(s)
    create_label_view(con, s)
    out = con.execute("SELECT * FROM case_label").df().set_index("ddl_case_id")
    con.close()
    return out


@pytest.mark.parametrize("case_id", list(CASES))
def test_label_edge_cases(labels, case_id):
    _, _, _, usable, eligible, label_24m, label_12m = CASES[case_id]
    row = labels.loc[case_id]
    assert bool(row["usable"]) is usable
    assert bool(row["eligible_24m"]) is eligible
    if usable:
        assert row["label_24m"] == label_24m
        assert row["label_12m"] == label_12m


def test_window_includes_its_last_day_and_not_the_next(labels):
    assert labels.loc["day_730", "label_24m"] == 1
    assert labels.loc["day_731", "label_24m"] == 0


def test_decision_after_t_end_is_censored_for_survival(labels):
    row = labels.loc["decided_after_t_end"]
    assert row["event_by_t_end"] == 0
    assert row["duration_days"] == (date(2018, 12, 31) - FILED).days


def test_rule_flags(labels):
    assert labels.loc["outcome_without_date", "dq_x04"]
    assert labels.loc["transferred_in_window", "dq_x09"]
    assert labels.loc["decided_before_filing", "dq_v01"]
    assert labels.loc["decided_after_collection", "dq_v03"]
    assert labels.loc["no_filing_date", "dq_c01"]
    assert labels.loc["filed_outside_years", "dq_v02"]
    assert labels.loc["suspect_district", "suspect_district"]
    assert not labels.loc["same_day", "suspect_district"]


def test_twelve_month_label_implies_twenty_four(labels):
    ok = labels[labels["usable"]]
    assert not ((ok["label_12m"] == 1) & (ok["label_24m"] == 0)).any()


def test_label_check_catalogue_parses_and_names_every_invariant():
    checks = parse_checks((SQL_DIR / "dq_labels.sql").read_text(encoding="utf8"))
    ids = [c["id"] for c in checks]
    assert len(ids) == len(set(ids))
    assert {c["status"] for c in checks} <= {"Invariant", "Accepted", "Info"}
    assert sum(c["status"] == "Invariant" for c in checks) >= 5
