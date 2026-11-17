"""The dashboard's caches notice a changed file.

Streamlit Cloud keeps its in-memory cache across deploys. When the cache was keyed on the file name alone, an update
that added a column to a table kept serving the old table, and the page that read the new column crashed.
"""
import os
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "dashboard"))
import shared  # noqa: E402


def test_a_table_is_read_again_once_its_file_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(shared, "MART", tmp_path)
    path = tmp_path / "example.parquet"
    pd.DataFrame({"p_model": [0.5]}).to_parquet(path)
    assert list(shared.table("example").columns) == ["p_model"]

    pd.DataFrame({"case_mix": ["state"], "p_model": [0.5]}).to_parquet(path)
    later = time.time_ns() + 5_000_000_000  # a deploy rewrites the file, so its modification time moves on
    os.utime(path, ns=(later, later))
    assert list(shared.table("example").columns) == ["case_mix", "p_model"]
