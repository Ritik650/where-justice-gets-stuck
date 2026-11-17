"""Step 3 of `make features`: assign every sampled case to one split, and save the assignment by case ID.

Two splits at once:
  * Temporal. Train on filings in the training years, validate on the next year, test on the year after. A random
    split would let the model learn from cases filed after the ones it is tested on.
  * Unseen courts. A share of courts is held out entirely (GroupShuffleSplit on the court ID). Their test-year cases
    form `test_unseen`; their earlier cases are not used at all. This measures how the model does on a court it never
    saw, which leans on the court-history features rather than the court's ID.

Every run reads splits.parquet, so all models see identical rows; the ID fingerprints in split_summary.csv prove it.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupShuffleSplit

from .sample import id_hash
from .settings import Settings, load

ORDER = ["train", "valid", "test", "test_unseen", "unused_unseen_court"]


def assign(df: pd.DataFrame, s: Settings) -> pd.Series:
    sp = s.cfg["split"]
    df = df.sort_values("ddl_case_id").reset_index(drop=True)
    gss = GroupShuffleSplit(n_splits=1, test_size=float(sp["unseen_court_share"]), random_state=s.seed)
    _, held_idx = next(gss.split(df, groups=df["court"]))
    held = set(df.loc[held_idx, "court"])
    unseen = df["court"].isin(held).to_numpy()
    year = df["filing_year"].to_numpy()
    lo, hi = sp["train_years"]
    split = np.select(
        [~unseen & (year >= lo) & (year <= hi), ~unseen & (year == sp["valid_year"]), ~unseen & (year == sp["test_year"]),
         unseen & (year == sp["test_year"]), unseen],
        ["train", "valid", "test", "test_unseen", "unused_unseen_court"], default="outside_split_years")
    return pd.Series(split, index=df["ddl_case_id"], name="split")


def run(s: Settings) -> pd.DataFrame:
    df = pd.read_parquet(s.features_path, columns=["ddl_case_id", "court", "filing_year", "label_24m"])
    split = assign(df, s)
    out = split.reset_index()
    out.to_parquet(s.splits_path, index=False)
    merged = df.merge(out, on="ddl_case_id")
    summary = (merged.groupby("split")
               .agg(cases=("ddl_case_id", "size"), courts=("court", "nunique"), positive_rate=("label_24m", "mean"),
                    first_year=("filing_year", "min"), last_year=("filing_year", "max"))
               .reindex([o for o in ORDER if o in set(merged["split"])]))
    summary["id_hash"] = [id_hash(merged.loc[merged["split"] == name, "ddl_case_id"]) for name in summary.index]
    summary.to_csv(s.reports / "split_summary.csv")
    version = id_hash(out["ddl_case_id"] + ":" + out["split"])
    (s.reports / "split_summary.json").write_text(json.dumps({"split_version": version, "seed": s.seed} | s.cfg["split"], indent=1))
    print(summary.to_string(), flush=True)
    print(f"split version {version}", flush=True)
    return summary


def split_version(s: Settings) -> str:
    return json.loads((s.reports / "split_summary.json").read_text())["split_version"]


if __name__ == "__main__":
    run(load())
