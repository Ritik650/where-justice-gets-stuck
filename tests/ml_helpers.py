"""Shared helpers for the ML tests: settings pointed at a temporary folder, and small hand-built case tables."""
from __future__ import annotations

import dataclasses
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from src.ml.fixture import CASE_SCHEMA
from src.ml.settings import Settings, load


def settings_in(tmp: Path, sample_size: int | None = None, **cfg_overrides) -> Settings:
    """The fixture profile with every path moved under `tmp`, so tests never touch the real outputs."""
    s = load("fixture")
    cfg = dict(s.cfg)
    for section, values in cfg_overrides.items():
        cfg[section] = {**cfg[section], **values}
    return dataclasses.replace(
        s, cfg=cfg, source=tmp / "parquet", district_flags=tmp / "parquet" / "q5_districts.parquet", work=tmp / "ml",
        reports=tmp / "reports", mart=tmp / "mart", sample_size=sample_size or s.sample_size)


def write_cases(source: Path, rows: list[dict]) -> None:
    """Write hand-built cases in the real schema, plus the disposition map the label view joins."""
    defaults = {"year": 2015, "state_code": "91", "dist_code": "01", "court_no": "01", "judge_position": "x",
                "female_defendant": 0, "female_petitioner": 0, "female_adv_def": -9999, "female_adv_pet": 0,
                "type_name": 1, "purpose_name": 1, "disp_name": 7, "date_of_decision": None, "date_first_list": None,
                "date_last_list": None, "date_next_list": None, "date_parse_failures": 0}
    df = pd.DataFrame([defaults | r for r in rows])
    for c in ("date_of_filing", "date_of_decision", "date_first_list", "date_last_list", "date_next_list"):
        df[c] = [pd.Timestamp(v).date() if v is not None and not pd.isna(v) else None for v in df[c]]
    (source / "cases").mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pandas(df[[f.name for f in CASE_SCHEMA]], schema=CASE_SCHEMA, preserve_index=False),
                   source / "cases" / "cases_2015.parquet")
    disp = pd.DataFrame({"year": [2015] * 3, "disp_name": [3, 4, 7], "disp_name_s": ["disposed", "transferred", "disposition var missing"],
                         "count": "1", "disp_group": ["Generic 'disposed'", "Transferred / committed", "Missing"]})
    (source / "maps").mkdir(parents=True, exist_ok=True)
    disp.astype({"year": "Int64", "disp_name": "Int64"}).to_parquet(source / "maps" / "map_disp.parquet", index=False)
