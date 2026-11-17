"""Step 2 of `make features`: build point-in-time features for the sampled cases (sql/features.sql).

SQL computes every court-history table from the full population and joins it to the sample. Python then adds the
fallbacks the baselines need and pools rare categories. Category vocabularies are counted on the training years only,
so the test years cannot shape them.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from .db import connect, create_label_view, label_params, run_script
from .settings import SQL_DIR, Settings, load

# Model inputs. Everything here is known on the day of filing; docs/features.md gives each one's point-in-time rule.
CATEGORICAL = [
    "state", "district", "court", "court_level", "case_type", "case_type_label", "act", "act_section",
    "ddl_criminal_flag", "petitioner_gender", "defendant_gender", "petitioner_advocate",
]
NUMERIC = [
    "filing_year", "filing_month", "filing_weekday",
    "court_disp_rate_py", "court_type_disp_rate_py", "district_disp_rate_py", "state_disp_rate_py",
    "court_type_share_py", "court_cohort_rate_lag3", "log_court_filings_py", "log_court_pending_at_filing",
    "court_backlog_months", "court_years_active",
]
FEATURES = CATEGORICAL + NUMERIC
# Known only after filing. Kept in the table for the leakage test and never used otherwise.
LEAK = ["leak_days_to_last_hearing", "leak_defendant_advocate_named", "leak_last_hearing_stage"]
LEAK_CATEGORICAL = {"leak_last_hearing_stage"}
# Source columns recorded after filing (docs/feature_audit.md). No model input may be built from these.
POST_FILING_COLUMNS = {
    "date_of_decision", "disp_name", "purpose_name", "date_first_list", "date_last_list", "date_next_list",
    "judge_position", "female_adv_def", "date_parse_failures", "ddl_decision_judge_id",
}
LABELS = ["label_24m", "label_12m", "duration_days", "event_by_t_end"]
POOLED = {"case_type_label": "top_type_labels", "act_section": "top_sections"}


def whatif_path(s: Settings) -> Path:
    """Court history as of the test year for every court x case type (aggregate, no case rows)."""
    return s.work / "whatif_base.parquet"


def whatif_profiles_path(s: Settings) -> Path:
    """The case mix each court is scored on in the what-if, written by train.py: case details and weights, no case IDs."""
    return s.models_dir / "whatif_profiles.parquet"


def feature_version(s: Settings) -> str:
    """Config version plus a hash of the SQL and the feature list: any change to either gives a new version."""
    text = (SQL_DIR / "features.sql").read_text(encoding="utf8") + json.dumps(FEATURES) + json.dumps(s.cfg["features"], sort_keys=True)
    return f"{s.cfg['features']['version']}-{hashlib.sha256(text.encode()).hexdigest()[:8]}"


def pool_rare(df: pd.DataFrame, column: str, keep: int, train_mask: pd.Series) -> pd.Series:
    top = df.loc[train_mask, column].value_counts().head(keep).index
    return df[column].where(df[column].isin(top), "other")


def finish(df: pd.DataFrame, s: Settings) -> pd.DataFrame:
    lo, hi = s.cfg["split"]["train_years"]
    train_mask = df["filing_year"].between(lo, hi)
    for column, setting in POOLED.items():
        df[column] = pool_rare(df, column, int(s.cfg["features"][setting]), train_mask)
    df["log_court_filings_py"] = np.log1p(df["court_filings_py"])
    df["log_court_pending_at_filing"] = np.log1p(df["court_pending_at_filing"])
    # Months of decisions it would take to clear the stock at the court's recent pace.
    df["court_backlog_months"] = df["court_pending_at_filing"] / (df["court_decided_prev_12m"] / 12 + 1)
    # Baseline scores with fallbacks: a court with no workload last year borrows its district's rate, and so on up.
    df["b1_score"] = (df["court_disp_rate_py"].fillna(df["district_disp_rate_py"]).fillna(df["state_disp_rate_py"])
                      .fillna(df["national_disp_rate_py"]))
    df["b1_source"] = np.select(
        [df["court_disp_rate_py"].notna(), df["district_disp_rate_py"].notna(), df["state_disp_rate_py"].notna(),
         df["national_disp_rate_py"].notna()], ["court", "district", "state", "national"], "none")
    df["b2_score"] = df["court_type_disp_rate_py"].fillna(df["b1_score"])
    df["b1b_score"] = df["court_cohort_rate_lag3"].fillna(df["b1_score"])
    for c in CATEGORICAL + list(LEAK_CATEGORICAL):
        df[c] = df[c].astype(str)
    return df


def run(s: Settings) -> dict:
    s.ensure_dirs()
    if not s.sample_path.exists():
        raise SystemExit("no sample yet; run src.ml.sample first (make features does both)")
    t0 = time.time()
    con = connect(s)
    create_label_view(con, s)
    lab = s.cfg["label"]
    run_script(
        con, "features.sql",
        map_type=s.src("maps/map_type.parquet"), map_act=s.src("maps/map_act.parquet"),
        map_purpose=s.src("maps/map_purpose.parquet"), section_key=s.src("keys/section_key.parquet"),
        court_key=s.src("keys/cases_court_key.parquet"), acts=s.src("acts_sections.parquet"),
        cases=s.src("cases/cases_*.parquet"), sample=s.sample_path.as_posix(), out=s.features_path.as_posix(),
        t_end=lab["t_end"], collection_end=lab["collection_end"], first_filing=lab["first_filing"],
        first_year=int(lab["first_filing"][:4]), last_year=int(lab["last_filing"][:4]),
        shrink_k=float(s.cfg["features"]["shrink_k"]), test_year=int(s.cfg["split"]["test_year"]),
        whatif_out=whatif_path(s).as_posix(), suspect_list=label_params(s)["suspect_list"],
    )
    con.close()
    df = pd.read_parquet(s.features_path)
    n_sample = len(pd.read_parquet(s.sample_path, columns=["ddl_case_id"]))
    if len(df) != n_sample or not df["ddl_case_id"].is_unique:
        raise SystemExit(f"features have {len(df):,} rows for a sample of {n_sample:,}: a join added or lost rows")
    df = finish(df, s)
    df.to_parquet(s.features_path, index=False)

    version = feature_version(s)
    summary = pd.DataFrame({
        "feature": FEATURES,
        "kind": ["categorical"] * len(CATEGORICAL) + ["numeric"] * len(NUMERIC),
        "missing_share": [float(df[c].isna().mean()) if c in NUMERIC else float((df[c] == "nan").mean()) for c in FEATURES],
        "levels": [int(df[c].nunique()) for c in FEATURES],
    })
    summary.to_csv(s.reports / "feature_summary.csv", index=False)
    info = {"rows": int(len(df)), "features": len(FEATURES), "feature_version": version,
            "b1_source_shares": df["b1_source"].value_counts(normalize=True).round(4).to_dict(),
            "seconds": round(time.time() - t0, 1)}
    (s.reports / "features_summary.json").write_text(json.dumps(info, indent=1))
    print(summary.to_string(index=False), flush=True)
    print(f"features: {info}", flush=True)
    return info


if __name__ == "__main__":
    run(load())
