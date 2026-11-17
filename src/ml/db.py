"""DuckDB connection and the SQL views every ML step builds on."""
from __future__ import annotations

import time

import duckdb
import pandas as pd

from .settings import ROOT, Settings, read_sql, split_statements


def connect(s: Settings) -> duckdb.DuckDBPyConnection:
    tmp = ROOT / "data" / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"SET memory_limit='{s.memory_limit}'")
    con.execute(f"SET threads={s.threads}")
    con.execute(f"SET temp_directory='{tmp.as_posix()}'")
    con.execute("SET max_temp_directory_size='5GB'")  # the disk is small; fail rather than fill it
    con.execute("SET preserve_insertion_order=false")
    return con


def suspect_districts(s: Settings) -> list[str]:
    """(state_code, dist_code) keys of districts flagged for incomplete closure records, as 'SS-DD' strings.

    The flag comes from pipeline/analysis.py (q5_districts): under half of a district's bail matters closed within two
    years, or under 2% of all its cases did. Bail normally closes in days, so this points to unrecorded closures.
    """
    if not s.cfg["label"]["exclude_suspect_districts"] or not s.district_flags.exists():
        return []
    flags = pd.read_parquet(s.district_flags)
    units = flags.loc[flags["suspect_closure_records"].fillna(False).astype(bool), "unit_id"].dropna().astype(int).tolist()
    if not units:
        return []
    dims = pd.read_parquet(s.source / "maps" / "dim_district.parquet")
    hit = dims[dims["unit_id"].isin(units)]
    return sorted(f"{a}-{b}" for a, b in zip(hit["state_code"], hit["dist_code"]))


def label_params(s: Settings) -> dict:
    lab = s.cfg["label"]
    suspects = suspect_districts(s)
    return {
        "cases": s.src("cases/cases_*.parquet"),
        "map_disp": s.src("maps/map_disp.parquet"),
        "map_type": s.src("maps/map_type.parquet"),
        "t_end": lab["t_end"],
        "collection_end": lab["collection_end"],
        "first_filing": lab["first_filing"],
        "last_filing": lab["last_filing"],
        "horizon": int(lab["horizon_days"]),
        "horizon2": int(lab["secondary_horizon_days"]),
        # An empty list still has to be valid SQL.
        "suspect_list": ", ".join(f"'{k}'" for k in suspects) if suspects else "'__none__'",
    }


def create_label_view(con: duckdb.DuckDBPyConnection, s: Settings) -> None:
    """Create the `case_label` view (sql/labels.sql): every case, its data-quality flags and both labels."""
    for stmt in split_statements(read_sql("labels.sql", **label_params(s))):
        con.execute(stmt)


def run_script(con: duckdb.DuckDBPyConnection, name: str, verbose: bool = True, **params) -> None:
    for stmt in split_statements(read_sql(name, **params)):
        t0 = time.time()
        con.execute(stmt)
        if verbose:
            first = " ".join(stmt.split()[:6])
            print(f"  {first} ... {time.time() - t0:.1f}s", flush=True)
