"""The what-if's case mix: a sample of each state's own training cases per case type, the national sample for thin states."""
import pandas as pd
from ml_helpers import settings_in

from src.ml.train import CASE_DETAIL, NATIONAL, whatif_profiles


def cases(state: str, case_type: str, n: int, act: str) -> pd.DataFrame:
    """`n` cases that differ only in their act: three in four carry `act`, the rest a rarer one."""
    details = {c: ["same"] * n for c in CASE_DETAIL}
    details["act"] = [act if i % 4 else "rare act" for i in range(n)]
    return pd.DataFrame({"state": state, "case_type": case_type, **details})


def frame(*parts: pd.DataFrame) -> pd.DataFrame:
    return pd.concat(parts, ignore_index=True).astype("category")  # as train.read_frame loads it


def test_each_state_is_scored_on_its_own_cases_and_thin_states_on_the_nations(tmp_path):
    s = settings_in(tmp_path, whatif={"cases": 50, "min_state_cases": 100})
    prof = whatif_profiles(frame(cases("A", "Civil suit", 400, "act of A"), cases("B", "Civil suit", 60, "act of B")), s)
    weight = prof.groupby(["state", "case_type"])["weight"].sum()
    assert weight[("A", "Civil suit")] == 50, "a sample of the state's cases, not all of them"
    assert ("B", "Civil suit") not in weight.index, "under the floor, a state has no mix of its own"
    assert weight[(NATIONAL, "Civil suit")] == 50
    assert set(prof.loc[prof["state"] == "A", "act"]) <= {"act of A", "rare act"}, "a state's mix holds only its own cases"
    # The mix keeps the spread of real cases instead of one most-common case.
    assert len(prof[prof["state"] == "A"]) == 2


def test_the_mix_repeats(tmp_path):
    s = settings_in(tmp_path, whatif={"cases": 50, "min_state_cases": 100})
    train = cases("A", "Civil suit", 400, "act of A")
    train["act"] = [f"act {i}" for i in range(len(train))]  # every case distinct, so a different draw always shows
    train = frame(train)
    first = whatif_profiles(train, s)
    assert first.equals(whatif_profiles(train, s))
    reseeded = settings_in(tmp_path, whatif={"cases": 50, "min_state_cases": 100})
    reseeded.cfg["seed"] = s.seed + 1
    assert not first.equals(whatif_profiles(train, reseeded)), "the seed decides which cases are drawn"
