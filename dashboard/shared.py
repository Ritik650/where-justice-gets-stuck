"""Helpers shared by the dashboard pages. The app reads only data/mart, never row-level data."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import charts as C  # noqa: E402
from samples import short_samples  # noqa: E402, F401 - shared with the pages

MART = ROOT / "data" / "mart"
OUTPUTS = ROOT / "outputs"

SOURCES = (
    "Sources: Development Data Lab eCourts data (CC BY-NC-SA 4.0, non-commercial); NJDG via Lok Sabha Unstarred Question 3371, 7 Aug 2026; "
    "Census 2011; DataMeet district boundaries (CC BY 4.0). Gender is predicted from names by DDL's model."
)
# DDL lists these two territories apart, while NJDG reports them as one.
NJDG_NAME = {"Daman and Diu": "The Dadra and Nagar Haveli and Daman and Diu", "Dadra and Nagar Haveli": "The Dadra and Nagar Haveli and Daman and Diu"}
DIMENSIONS = ["Completeness", "Validity", "Consistency", "Uniqueness", "Linkage"]


@st.cache_data(show_spinner=False, max_entries=64)
def table(name: str) -> pd.DataFrame:
    return pd.read_parquet(MART / f"{name}.parquet")


@st.cache_data(show_spinner=False, max_entries=8)
def csv(path: str) -> pd.DataFrame:
    return pd.read_csv(ROOT / path, dtype=str, keep_default_na=False)


@st.cache_data(show_spinner=False)
def findings() -> dict:
    return json.loads((MART / "findings.json").read_text())


@st.cache_data(show_spinner=False)
def rule_sql() -> dict[str, str]:
    """Each rule's SQL, as written in the catalogue."""
    out = {}
    for block in re.split(r"(?m)^(?=-- id: )", (ROOT / "sql" / "dq_rules.sql").read_text(encoding="utf8"))[1:]:
        rid = re.search(r"(?m)^-- id: (\S+)", block).group(1)
        out[rid] = "\n".join(line for line in block.splitlines() if not line.startswith("--")).strip()
    return out


def show(chart, description: str, alt_text: str | None = None) -> None:
    """Draw a chart in the shared style. The caption doubles as its text alternative unless one is given."""
    st.altair_chart(C.styled(chart), theme=None, width="stretch", alt=alt_text or description)
    st.caption(description)


def finding_block(entry: dict) -> None:
    with st.container(border=True):
        st.markdown(f"**Finding.** {entry['finding']}")
        st.caption(f"Read with care: {entry['caveat']}")


def national_score(scores: pd.DataFrame, dimension: str) -> float:
    return float((scores[dimension] * scores["cases"]).sum() / scores["cases"].sum())
