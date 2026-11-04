"""The NJDG table was typed from a PDF, so check it against the totals the PDF itself prints."""
from pathlib import Path

import pandas as pd

EXTERNAL = Path(__file__).resolve().parent.parent / "data" / "external"


def njdg() -> pd.DataFrame:
    return pd.read_csv(EXTERNAL / "njdg_state_pendency_2026-07-30.csv")


def test_rows_sum_to_the_printed_totals():
    df = njdg()
    assert len(df) == 36
    assert df["pending_total"].sum() == 49_911_920
    assert df["pending_over_10y"].sum() == 5_451_914
    assert df["pending_5_to_10y"].sum() == 9_397_617


def test_age_bands_are_mutually_exclusive():
    """The PDF labels the last column 'More than 5 years', but it cannot be cumulative: in some states it
    is smaller than the 'More than 10 years' column. It is stored as 5-10 years for that reason."""
    df = njdg()
    west_bengal = df[df.state == "West Bengal"].iloc[0]
    assert west_bengal.pending_over_10y > west_bengal.pending_5_to_10y
    assert (df["pending_over_10y"] + df["pending_5_to_10y"] <= df["pending_total"]).all()


def test_crosswalk_overrides_have_no_duplicates_or_blanks():
    over = pd.read_csv(EXTERNAL / "district_crosswalk_overrides.csv", dtype=str).fillna("")
    assert not over.duplicated(["state_code", "dist_code"]).any()
    territorial = over[over.link_type != "non_territorial"]
    assert (territorial.census_district != "").all()
    assert (over[over.link_type == "non_territorial"].census_district == "").all()
