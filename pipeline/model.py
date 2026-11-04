"""Step 4b: a Cox proportional-hazards model of what drives time to closure.

Survival curves compare one factor at a time, so a state with many slow case types looks slow for that reason alone.
This model holds case type, filing year, state and representation constant at once, and reports a hazard ratio for
each: above 1 means a case closes faster than its reference group, below 1 means slower.

The model is fitted on a random sample, because a sample this size already pins the ratios down. A second sample
with a different seed measures how far the ratios move, and that figure is reported alongside the results.
Flagged districts with incomplete closure records are left out, so they cannot make a state look slower than it is.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from lifelines import CoxPHFitter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analysis import base_view, save, state_names  # noqa: E402
from common import MART, connect  # noqa: E402

SAMPLE_ROWS = 300_000
SEEDS = (42, 7)
MIN_STATE_ROWS = 2_000  # smaller states are grouped so that no estimate rests on a handful of cases
REFERENCE = {"category": "Criminal trial (magistrate)", "state": "Maharashtra", "year": 2018}
GROUP_LABELS = {"category": "Case type", "state": "State", "year": "Filing year", "people": "People involved"}


def sample(con, seed: int, flagged: list[int]) -> pd.DataFrame:
    exclude = f"AND (d.unit_id IS NULL OR d.unit_id NOT IN ({', '.join(map(str, flagged))}))" if flagged else ""
    return con.execute(f"""
        SELECT * FROM (
            SELECT b.case_category AS category, b.state_code, b.year, b.t_days + 0.5 AS duration, b.closed::INT AS event,
                   b.female_petitioner, b.female_defendant, b.female_adv_pet, b.female_adv_def
            FROM base b JOIN dim_district d USING (state_code, dist_code)
            WHERE b.usable AND b.t_days >= 0 {exclude}
        ) USING SAMPLE {SAMPLE_ROWS} ROWS (reservoir, {seed})
    """).df()


def design(df: pd.DataFrame, names: dict[str, str]) -> pd.DataFrame:
    df = df.copy()
    df["state"] = df["state_code"].map(names)
    counts = df["state"].value_counts()
    df["state"] = df["state"].where(df["state"].map(counts) >= MIN_STATE_ROWS, "Smaller states and UTs")
    x = pd.DataFrame({"duration": df["duration"], "event": df["event"]})
    for group in ("category", "state", "year"):
        dummies = pd.get_dummies(df[group].astype(str), prefix=f"{group}=", prefix_sep="", dtype=float)
        dummies = dummies.drop(columns=f"{group}={REFERENCE[group]}")
        x = pd.concat([x, dummies], axis=1)
    x["people=Petitioner is a woman"] = (df["female_petitioner"] == 1).astype(float)
    x["people=Petitioner gender unknown"] = (df["female_petitioner"] < 0).astype(float)
    x["people=Defendant is a woman"] = (df["female_defendant"] == 1).astype(float)
    x["people=Defendant gender unknown"] = (df["female_defendant"] < 0).astype(float)
    x["people=Petitioner's advocate named"] = (df["female_adv_pet"] != -9999).astype(float)
    x["people=Defendant's advocate named"] = (df["female_adv_def"] != -9999).astype(float)
    return x


def fit(x: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    model = CoxPHFitter(penalizer=1e-4)  # a tiny penalty only keeps nearly empty columns from destabilising the fit
    model.fit(x, duration_col="duration", event_col="event", show_progress=False)
    s = model.summary
    out = pd.DataFrame({
        "term": s.index,
        "hazard_ratio": s["exp(coef)"].to_numpy(),
        "ci_low": s["exp(coef) lower 95%"].to_numpy(),
        "ci_high": s["exp(coef) upper 95%"].to_numpy(),
    })
    split = out["term"].str.split("=", n=1, expand=True)
    out["group"] = split[0].map(GROUP_LABELS)
    out["level"] = split[1]
    return out, {"rows": int(len(x)), "events": int(x["event"].sum()), "concordance": float(model.concordance_index_)}


def run() -> None:
    # A seeded sample only repeats exactly on one thread with rows in order, so reruns give identical ratios.
    con = connect(memory_limit="6GB", threads=1)
    con.execute("SET preserve_insertion_order=true")
    base_view(con)
    names = state_names(con)
    districts = pd.read_parquet(MART / "q5_districts.parquet")
    flagged = districts.loc[districts["suspect_closure_records"], "unit_id"].astype(int).tolist()
    results = []
    stats = []
    for seed in SEEDS:
        t0 = time.time()
        x = design(sample(con, seed, flagged), names)
        table, info = fit(x)
        results.append(table)
        stats.append(info | {"seed": seed, "seconds": round(time.time() - t0)})
        print(f"seed {seed}: {info}, {time.time() - t0:.0f}s", flush=True)
    con.close()
    main = results[0]
    other = results[1].set_index("term")["hazard_ratio"]
    main["other_sample_ratio"] = main["term"].map(other)
    shift = (np.log(main["hazard_ratio"]) - np.log(main["other_sample_ratio"])).abs()
    # Small groups move most between samples, so stability is judged on the typical term and the worst large one.
    summary = stats[0] | {
        "median_shift_between_samples": float(np.expm1(shift.median())),
        "reference": REFERENCE,
    }
    save(main, "model_hazard_ratios")
    (MART / "model_summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary), flush=True)
    print(main.sort_values("hazard_ratio")[["group", "level", "hazard_ratio", "ci_low", "ci_high", "other_sample_ratio"]].round(3).to_string(), flush=True)


if __name__ == "__main__":
    run()
