"""The SQL-aggregated Kaplan-Meier must match lifelines, the reference implementation."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from lifelines import KaplanMeierFitter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from km import km_from_counts, median_from_curve, summarise, survival_at  # noqa: E402


def aggregate(durations: np.ndarray, observed: np.ndarray) -> pd.DataFrame:
    df = pd.DataFrame({"t": durations, "d": observed.astype(int), "c": (~observed).astype(int)})
    return df.groupby("t", as_index=False).sum()


@pytest.mark.parametrize("seed,n,open_share", [(1, 5000, 0.0), (2, 5000, 0.3), (3, 20000, 0.6), (4, 200, 0.9)])
def test_matches_lifelines(seed, n, open_share):
    rng = np.random.default_rng(seed)
    durations = np.floor(rng.exponential(700, n))
    observed = rng.random(n) >= open_share
    reference = KaplanMeierFitter().fit(durations, observed)
    a = aggregate(durations, observed)
    t, s = km_from_counts(a["t"].to_numpy(float), a["d"].to_numpy(float), a["c"].to_numpy(float))
    expected = reference.survival_function_at_times(t).to_numpy()
    np.testing.assert_allclose(s, expected, atol=1e-9)
    if np.isfinite(reference.median_survival_time_):
        assert median_from_curve(t, s) == reference.median_survival_time_
    else:
        assert np.isnan(median_from_curve(t, s))


def test_worked_example_by_hand():
    # Six cases: closed at days 1, 2, 2 and 5; still open at days 3 and 4.
    # S(1) = 5/6, S(2) = 5/6 * 3/5 = 1/2, S(5) = 1/2 * 0/1 = 0.
    t, s = km_from_counts(np.array([1.0, 2, 3, 4, 5]), np.array([1.0, 2, 0, 0, 1]), np.array([0.0, 0, 1, 1, 0]))
    np.testing.assert_allclose(s, [5 / 6, 1 / 2, 1 / 2, 1 / 2, 0.0])
    assert median_from_curve(t, s) == 2


def test_open_cases_raise_the_median():
    """The reason for the method: dropping open cases understates how long justice takes."""
    closed = np.array([100.0] * 60)
    still_open = np.array([3000.0] * 40)
    durations = np.concatenate([closed, still_open])
    observed = np.array([True] * 60 + [False] * 40)
    a = aggregate(durations, observed)
    t, s = km_from_counts(a["t"].to_numpy(float), a["d"].to_numpy(float), a["c"].to_numpy(float))
    assert median_from_curve(t, s) == 100  # 60% closed by day 100
    observed2 = np.array([True] * 30 + [False] * 70)
    a2 = aggregate(np.concatenate([np.array([100.0] * 30), np.array([3000.0] * 70)]), observed2)
    t2, s2 = km_from_counts(a2["t"].to_numpy(float), a2["d"].to_numpy(float), a2["c"].to_numpy(float))
    assert np.isnan(median_from_curve(t2, s2))  # closed cases alone say 100 days; the true median is unreached


def test_survival_at_never_extrapolates():
    t = np.array([10.0, 20.0])
    s = np.array([0.9, 0.8])
    assert survival_at(t, s, 5) == 1.0
    assert survival_at(t, s, 15) == 0.9
    assert survival_at(t, s, 20) == 0.8
    assert np.isnan(survival_at(t, s, 21))


def test_summarise_counts():
    df = pd.DataFrame({"g": ["a", "a", "b"], "t": [1, 2, 1], "d": [2, 0, 1], "c": [0, 2, 0]})
    summary, curves = summarise(df, "g", np.array([0, 1, 2]))
    assert summary.set_index("g").loc["a", "n"] == 4
    assert summary.set_index("g").loc["a", "closed"] == 2
    assert summary.set_index("g").loc["b", "km_median_days"] == 1
    assert len(curves) == 6
