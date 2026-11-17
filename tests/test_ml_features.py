"""No feature is dated after filing, and prior-year features use only prior data.

1. Static: no model input is a post-filing source column or a leak_ column.
2. Point in time: rebuild the features with everything on or after the target cases' filing month removed (later
   filings dropped, later decisions blanked, the targets' own outcomes erased). No model input may change.
3. A case's own post-filing fields (hearing dates, stage, outcome, the defendant's advocate) may change freely: the
   model inputs stay put, while the leak_ columns move, which proves the change was real.

Runs on the synthetic fixture with every case sampled, so targets and history come from the same rows.
"""
import shutil

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from ml_helpers import settings_in

from src.ml import features as F
from src.ml import sample
from src.ml.fixture import CASE_SCHEMA, generate

CUTOFF = pd.Timestamp("2015-07-01")  # targets are the cases filed in July 2015
COMPARED = F.FEATURES + ["b1_score", "b2_score", "b1b_score"]


def read_cases(source) -> pd.DataFrame:
    return pd.concat([pq.read_table(p).to_pandas() for p in sorted((source / "cases").glob("*.parquet"))], ignore_index=True)


def write_cases(source, cases: pd.DataFrame) -> None:
    shutil.rmtree(source / "cases")
    (source / "cases").mkdir()
    cols = [f.name for f in CASE_SCHEMA]
    for year, g in cases.groupby("year"):
        pq.write_table(pa.Table.from_pandas(g[cols], schema=CASE_SCHEMA, preserve_index=False), source / "cases" / f"cases_{year}.parquet")


def rebuild(base, tmp, edit) -> pd.DataFrame:
    """Copy the fixture, apply `edit` to its cases, reuse the same sample rows, and rebuild the features."""
    s = settings_in(tmp, sample_size=base.sample_size)
    shutil.copytree(base.source, s.source)
    cases = edit(read_cases(s.source))
    write_cases(s.source, cases)
    s.ensure_dirs()
    kept = pd.read_parquet(base.sample_path)
    kept[kept["ddl_case_id"].isin(set(cases["ddl_case_id"]))].to_parquet(s.sample_path, index=False)
    F.run(s)
    return pd.read_parquet(s.features_path).set_index("ddl_case_id")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("full")
    s = settings_in(tmp, sample_size=10**9)  # sample every case
    generate(s.source)
    sample.run(s)
    F.run(s)
    feats = pd.read_parquet(s.features_path).set_index("ddl_case_id")
    filed = pd.to_datetime(feats["date_of_filing"])
    targets = set(feats.index[(filed >= CUTOFF) & (filed < CUTOFF + pd.offsets.MonthBegin(1))])
    assert len(targets) > 100
    return s, feats, targets


def assert_same(a: pd.DataFrame, b: pd.DataFrame, columns: list[str]) -> None:
    for c in columns:
        x, y = a[c], b.loc[a.index, c]
        if c in F.NUMERIC or c.endswith("_score"):
            assert np.allclose(x.astype(float), y.astype(float), equal_nan=True, rtol=0, atol=1e-12), c
        else:
            assert (x.astype(str) == y.astype(str)).all(), c


def test_no_model_input_is_known_only_after_filing():
    assert not set(F.FEATURES) & set(F.LEAK)
    assert not any(f.startswith("leak_") for f in F.FEATURES)
    assert not set(F.FEATURES) & F.POST_FILING_COLUMNS
    assert len(F.FEATURES) == len(set(F.FEATURES))


def test_every_feature_is_documented():
    from src.ml.settings import ROOT
    text = (ROOT / "docs" / "features.md").read_text(encoding="utf8")
    missing = [f for f in F.FEATURES + F.LEAK if f"`{f}`" not in text]
    assert not missing, missing


def test_features_ignore_everything_on_or_after_the_filing_month(built, tmp_path):
    s, feats, targets = built

    def as_of_cutoff(cases: pd.DataFrame) -> pd.DataFrame:
        filed = pd.to_datetime(cases["date_of_filing"])
        cases = cases[(filed < CUTOFF) | filed.isna() | cases["ddl_case_id"].isin(targets)].copy()
        decided = pd.to_datetime(cases["date_of_decision"])
        blank = (decided >= CUTOFF) | cases["ddl_case_id"].isin(targets)
        cases.loc[blank, "date_of_decision"] = None
        cases.loc[blank, "disp_name"] = 7
        return cases

    truncated = rebuild(s, tmp_path, as_of_cutoff)
    target = feats.loc[sorted(targets)]
    assert_same(target, truncated, COMPARED)


def test_prior_year_features_ignore_the_whole_filing_year(built, tmp_path):
    """Yearly history for a case filed in Y must not see anything dated in Y, even before its filing month."""
    s, feats, targets = built
    year_start = pd.Timestamp("2015-01-01")

    def as_of_year_start(cases: pd.DataFrame) -> pd.DataFrame:
        filed = pd.to_datetime(cases["date_of_filing"])
        cases = cases[(filed < year_start) | filed.isna() | cases["ddl_case_id"].isin(targets)].copy()
        decided = pd.to_datetime(cases["date_of_decision"])
        blank = (decided >= year_start) | cases["ddl_case_id"].isin(targets)
        cases.loc[blank, "date_of_decision"] = None
        return cases

    truncated = rebuild(s, tmp_path, as_of_year_start)
    yearly = ["court_disp_rate_py", "court_type_disp_rate_py", "district_disp_rate_py", "state_disp_rate_py",
              "court_type_share_py", "court_cohort_rate_lag3", "log_court_filings_py", "court_years_active",
              "b1_score", "b2_score", "b1b_score"]
    assert_same(feats.loc[sorted(targets)], truncated, yearly)


def test_a_case_own_post_filing_fields_do_not_reach_the_model(built, tmp_path):
    s, feats, targets = built

    def scramble(cases: pd.DataFrame) -> pd.DataFrame:
        own = cases["ddl_case_id"].isin(targets)
        filed = pd.to_datetime(cases.loc[own, "date_of_filing"])
        cases.loc[own, "date_last_list"] = (filed + np.timedelta64(5, "D")).dt.date
        cases.loc[own, "date_next_list"] = (filed + np.timedelta64(9, "D")).dt.date
        cases.loc[own, "purpose_name"] = 3
        cases.loc[own, "female_adv_def"] = np.where(cases.loc[own, "female_adv_def"] == -9999, 0, -9999).astype("int16")
        cases.loc[own, "judge_position"] = "somewhere else"
        return cases

    changed = rebuild(s, tmp_path, scramble)
    target = feats.loc[sorted(targets)]
    assert_same(target, changed, COMPARED)
    moved = (target["leak_defendant_advocate_named"] != changed.loc[target.index, "leak_defendant_advocate_named"]).mean()
    assert moved == 1.0
