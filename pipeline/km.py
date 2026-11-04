"""Kaplan-Meier estimation from pre-aggregated counts.

Fitting survival curves row by row is not practical at 81M rows, but the estimator only needs, for each
duration t, how many cases closed at t (d) and how many left without closing at t (c). DuckDB can
count those in seconds, and the curve is then exact, not an approximation. tests/test_km.py checks the
results against the lifelines library.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def km_from_counts(t: np.ndarray, d: np.ndarray, c: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (sorted unique t, S(t)) from counts of events d and censored rows c at each t."""
    order = np.argsort(t)
    t, d, c = t[order], d[order], c[order]
    leaving = d + c
    at_risk = leaving[::-1].cumsum()[::-1]  # everyone still in the study just before t
    with np.errstate(divide="ignore", invalid="ignore"):
        factor = np.where(at_risk > 0, 1.0 - d / at_risk, 1.0)
    return t, np.cumprod(factor)


def median_from_curve(t: np.ndarray, s: np.ndarray) -> float:
    """Smallest t with S(t) <= 0.5. NaN when the curve never gets there (the median is not reached)."""
    below = np.nonzero(s <= 0.5)[0]
    return float(t[below[0]]) if below.size else float("nan")


def survival_at(t: np.ndarray, s: np.ndarray, when: float) -> float:
    """S(when). NaN when follow-up does not reach that far, so the curve is never extrapolated."""
    if t.size == 0 or when > t[-1]:
        return float("nan")
    idx = np.searchsorted(t, when, side="right") - 1
    return 1.0 if idx < 0 else float(s[idx])


def summarise(df: pd.DataFrame, group: str, grid_days: np.ndarray) -> tuple[pd.DataFrame, pd.DataFrame]:
    """df has columns [group, t, d, c]. Returns one summary row per group, plus curve points on the grid."""
    summaries, curves = [], []
    for name, g in df.groupby(group, sort=False):
        t, s = km_from_counts(g["t"].to_numpy(float), g["d"].to_numpy(float), g["c"].to_numpy(float))
        summaries.append({
            group: name,
            "n": int(g["d"].sum() + g["c"].sum()),
            "closed": int(g["d"].sum()),
            "km_median_days": median_from_curve(t, s),
            "open_after_1y": survival_at(t, s, 365),
            "open_after_3y": survival_at(t, s, 3 * 365),
            "open_after_5y": survival_at(t, s, 5 * 365),
        })
        curves.append(pd.DataFrame({
            group: name, "days": grid_days,
            "share_open": [survival_at(t, s, x) for x in grid_days],
        }))
    return pd.DataFrame(summaries), pd.concat(curves, ignore_index=True) if curves else pd.DataFrame()
