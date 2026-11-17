"""Paths and the DuckDB connection shared by every pipeline step."""
from __future__ import annotations

import os
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "ddl"
EXTERNAL = ROOT / "data" / "external"
TMP = ROOT / "data" / "tmp"
SQL = ROOT / "sql"

# WJGS_SCOPE=pilot keeps a one- or two-state trial run apart from the full 81M-row build.
SCOPE = os.environ.get("WJGS_SCOPE", "full")
PARQUET = ROOT / "data" / ("parquet" if SCOPE == "full" else f"parquet_{SCOPE}")
MART = ROOT / "data" / ("mart" if SCOPE == "full" else f"mart_{SCOPE}")
OUTPUTS = ROOT / ("outputs" if SCOPE == "full" else f"outputs_{SCOPE}")
CHARTS = OUTPUTS / "charts"

YEARS = range(2010, 2019)

LIVE_DASHBOARD = "https://where-justice-gets-stuck.streamlit.app/"
# The always-on static copy (pipeline/build_site.py), served by GitHub Pages from the gh-pages branch.
STATIC_SITE = "https://ritik650.github.io/where-justice-gets-stuck/"
REPOSITORY = "https://github.com/Ritik650/where-justice-gets-stuck"


def connect(memory_limit: str | None = None, threads: int | None = None):
    # A smaller machine can lower the defaults without editing code, e.g. WJGS_MEMORY_LIMIT=6GB WJGS_MAX_TEMP=3GB.
    # A caller's explicit values still win: model.py needs exactly one thread for a repeatable sample.
    memory_limit = memory_limit or os.environ.get("WJGS_MEMORY_LIMIT", "10GB")
    threads = threads or int(os.environ.get("WJGS_THREADS", "12"))
    max_temp = os.environ.get("WJGS_MAX_TEMP", "6GB")
    TMP.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"SET memory_limit='{memory_limit}'")
    con.execute(f"SET threads={threads}")
    con.execute(f"SET temp_directory='{TMP.as_posix()}'")
    con.execute(f"SET max_temp_directory_size='{max_temp}'")  # the disk is small; fail rather than fill it
    con.execute("SET preserve_insertion_order=false")
    return con


def pq(name: str) -> str:
    """Path for read_parquet(), with forward slashes so DuckDB accepts it on Windows."""
    return (PARQUET / name).as_posix()
