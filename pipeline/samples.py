"""Readable sample records for the issue log. No dependencies, so the dashboard can use it when hosted."""
from __future__ import annotations

import json


def short_samples(raw: str, limit: int = 3) -> str:
    """Turn sample rows into a readable cell: the case ID and its dates, with blanks dropped."""
    if not isinstance(raw, str) or not raw:
        return ""
    keep = []
    rows = json.loads(raw)
    for row in rows[:limit if "date_of_filing" in rows[0] else 5]:
        if "date_of_filing" in row:
            dates = [f"{k.replace('date_of_', '').replace('date_', '')}={v}" for k, v in row.items()
                     if k.startswith("date_") and v not in (None, "NaT", "None", "nan")]
            keep.append(f"{row['ddl_case_id']} ({', '.join(dates)})")
        else:  # set rules sample whatever explains the failure best, often a raw label and its volume
            keep.append(", ".join(f"{k}={v}" for k, v in row.items()))
    return "\n".join(keep)
