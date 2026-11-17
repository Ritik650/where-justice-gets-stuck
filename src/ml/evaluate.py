"""Step `make evaluate`: everything the report says about the models, measured on the test splits.

    metrics        ROC-AUC, PR-AUC, Brier score, log loss and calibration error for every final model
    calibration    isotonic recalibration of M1 and M2, fitted on the validation split only
    threshold      precision and recall for the delay class at one stated threshold, plus capacity-based cut-offs
    bootstrap      1,000 paired resamples of the AUC gap between M2 and B1: by case, as specified, and by court
    slices         state, case type, court level and filing period; the five worst slices
    unseen courts  the same metrics on courts held out of training entirely
    importance     permutation importance on test (AUC drop) and mean absolute SHAP values from LightGBM itself
    errors         the 50 largest false positives and false negatives, with what happened to each case after filing
    what-if        a typical case of each type, scored in every court, for the dashboard

Writes reports/ml_results.json (every number the report quotes), CSV tables and the dashboard's mart tables, and logs
one `evaluation` row in experiments.csv so the interval and threshold figures trace to a logged run too.
"""
from __future__ import annotations

import json
import pickle
import time

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import roc_auc_score

from .db import connect
from .features import FEATURES, feature_version, whatif_path
from .metrics import binary_metrics, bootstrap_auc_gap, calibration_table, delay_flags_at, slice_auc, threshold_for_share
from .settings import Settings, load
from .split import split_version
from .tracking import Timer, Tracker
from .train import CASE, lgb_matrix

MODELS = {"b0": "B0 majority class", "b1": "B1 court prior-year rate", "b2": "B2 court x case-type prior-year rate",
          "b1b": "B1b court 24-month rate, 3-year-old cohort", "m1": "M1 logistic regression", "m2": "M2 LightGBM",
          "m3": "M3 Cox (P(decided by day 730))"}
THRESHOLD = 0.5  # on the calibrated probability of a decision within the window; see threshold_section()
SLICE_DIMENSIONS = {"state_name": "State", "case_type": "Case type", "court_level": "Court level", "filing_quarter": "Filing quarter"}


def py(v):
    """numpy scalars and NaN to plain JSON values."""
    if isinstance(v, dict):
        return {str(k): py(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [py(x) for x in v]
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, float) and v != v:
        return None
    return v


def load_predictions(s: Settings) -> dict[str, pd.DataFrame]:
    return {k: pd.read_parquet(s.predictions_dir / f"{k}.parquet") for k in MODELS if (s.predictions_dir / f"{k}.parquet").exists()}


def part(df: pd.DataFrame, name: str) -> pd.DataFrame:
    return df[df["split"] == name].reset_index(drop=True)


def calibrate(preds: dict[str, pd.DataFrame], key: str, s: Settings) -> pd.DataFrame:
    """Isotonic regression from the model's validation scores to outcomes, applied to every split."""
    df = preds[key]
    valid = part(df, "valid")
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(valid["score"], valid["y"])
    with open(s.models_dir / f"{key}_isotonic.pkl", "wb") as fh:
        pickle.dump(iso, fh)
    out = df.copy()
    out["p"] = iso.predict(out["score"])
    return out


def metrics_table(preds: dict[str, pd.DataFrame], split_name: str) -> pd.DataFrame:
    """Ranking metrics (ROC-AUC, PR-AUC) from each model's raw score; probability metrics (Brier score, log loss,
    calibration error) from its probability, which for B1, B2 and the *_cal rows is the isotonic-calibrated one."""
    rows = []
    for key, df in preds.items():
        d = part(df, split_name)
        ranking = binary_metrics(d["y"], np.clip(d["score"], 0, 1))
        probability = binary_metrics(d["y"], d["p"])
        m = {"n": ranking["n"], "positive_rate": ranking["positive_rate"]}
        m |= {k: ranking.get(k) for k in ("roc_auc", "pr_auc", "pr_auc_delay")}
        m |= {k: probability.get(k) for k in ("brier", "log_loss", "ece")}
        name = MODELS[key[:-4]] + ", calibrated" if key.endswith("_cal") else MODELS.get(key, key)
        rows.append({"key": key, "model": name} | m)
    return pd.DataFrame(rows)


def attributes(s: Settings) -> pd.DataFrame:
    cols = ["ddl_case_id", "state", "court", "case_type", "court_level", "date_of_filing", "filing_year", "act",
            "leak_last_hearing_stage", "leak_days_to_last_hearing", "b1_score", "b2_score", "court_type_share_py",
            "log_court_pending_at_filing"]
    df = pd.read_parquet(s.features_path, columns=cols)
    states = pd.read_parquet(s.source / "maps" / "dim_state.parquet")[["state_code", "state_name"]].drop_duplicates("state_code")
    df = df.merge(states, how="left", left_on="state", right_on="state_code").drop(columns="state_code")
    df["state_name"] = df["state_name"].fillna(df["state"])
    q = pd.to_datetime(df["date_of_filing"]).dt.quarter
    df["filing_quarter"] = df["filing_year"].astype(str) + " Q" + q.astype(str)
    return df


def slices(test: pd.DataFrame, s: Settings) -> pd.DataFrame:
    ev = s.cfg["evaluate"]
    rows = []
    for column, dimension in SLICE_DIMENSIONS.items():
        for value, g in test.groupby(column):
            n, pos = len(g), int(g["y"].sum())
            row = {"dimension": dimension, "slice": str(value), "n": n, "positive_rate": pos / n,
                   "auc_m2": slice_auc(g["y"], g["m2"]), "auc_b1": slice_auc(g["y"], g["b1"]),
                   "brier_m2": float(np.mean((g["m2_p"] - g["y"]) ** 2)),
                   "mean_predicted": float(g["m2_p"].mean()), "rankable": n >= ev["slice_min_rows"] and min(pos, n - pos) >= ev["slice_min_class"]}
            row["auc_gap"] = row["auc_m2"] - row["auc_b1"]
            rows.append(row)
    return pd.DataFrame(rows)


def importance(s: Settings, test_ids: pd.Series, y: np.ndarray) -> pd.DataFrame:
    meta = json.loads((s.models_dir / "m2_meta.json").read_text())
    booster = lgb.Booster(model_file=str(s.models_dir / "m2_lgbm.txt"))
    ev = s.cfg["evaluate"]
    feats = pd.read_parquet(s.features_path, columns=["ddl_case_id"] + FEATURES)
    feats = feats.set_index("ddl_case_id").loc[test_ids.to_numpy()].reset_index()
    rng = np.random.default_rng(s.seed)
    n = min(int(ev["permutation_rows"]), len(feats))
    pick = np.sort(rng.choice(len(feats), n, replace=False))
    x = lgb_matrix(feats.iloc[pick], FEATURES, meta["categories"]).reset_index(drop=True)
    yy = y[pick]
    base = roc_auc_score(yy, booster.predict(x))
    rows = []
    for c in FEATURES:
        drops = []
        for _ in range(int(ev["permutation_repeats"])):
            shuffled = x.copy()
            order = rng.permutation(n)
            shuffled[c] = x[c].iloc[order].array if isinstance(x[c].dtype, pd.CategoricalDtype) else x[c].to_numpy()[order]
            drops.append(base - roc_auc_score(yy, booster.predict(shuffled)))
        rows.append({"feature": c, "auc_drop": float(np.mean(drops)), "auc_drop_sd": float(np.std(drops))})
    out = pd.DataFrame(rows)
    # SHAP values computed by LightGBM itself (pred_contrib), on a smaller subsample.
    m = min(20_000, n)
    contrib = booster.predict(x.iloc[:m], pred_contrib=True)[:, :-1]
    out["mean_abs_shap"] = np.abs(contrib).mean(axis=0)
    gain = dict(zip(booster.feature_name(), booster.feature_importance("gain")))
    out["gain_share"] = out["feature"].map(gain) / sum(gain.values())
    out["base_auc"] = base
    out["rows"] = n
    return out.sort_values("auc_drop", ascending=False).reset_index(drop=True)


def error_cases(s: Settings, test: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The 50 most confident wrong predictions each way, with what happened after filing, grouped by cause."""
    fp = test[test["y"] == 0].nlargest(50, "m2_p").assign(error="False positive: predicted quick, was not decided within 24 months")
    fn = test[test["y"] == 1].nsmallest(50, "m2_p").assign(error="False negative: predicted slow, was decided within 24 months")
    errs = pd.concat([fp, fn], ignore_index=True)
    con = connect(s)
    con.register("ids", errs[["ddl_case_id"]])
    # A date after collection ended is not real (rules V03, V05, V09; the placeholder 5000-01-01 is one), so it is
    # read as missing, as the rest of the project does.
    end = s.cfg["label"]["collection_end"]
    extra = con.execute(f"""
        SELECT c.ddl_case_id,
               CASE WHEN c.date_of_decision <= DATE '{end}' THEN c.date_of_decision END AS date_of_decision,
               CASE WHEN c.date_last_list <= DATE '{end}' THEN c.date_last_list END AS date_last_list,
               lower(trim(d.disp_name_s)) AS outcome_label, d.disp_group, smp.duration_days
        FROM ids JOIN read_parquet('{s.src('cases/cases_*.parquet')}') c USING (ddl_case_id)
        LEFT JOIN (SELECT year, disp_name, any_value(disp_name_s) AS disp_name_s, any_value(disp_group) AS disp_group
                   FROM read_parquet('{s.src('maps/map_disp.parquet')}') GROUP BY ALL) d
               ON c.disp_name = d.disp_name AND c.year = d.year
        LEFT JOIN read_parquet('{s.sample_path.as_posix()}') smp USING (ddl_case_id)
    """).df()
    con.close()
    errs = errs.merge(extra, on="ddl_case_id", how="left")
    t_end = pd.Timestamp(s.cfg["label"]["t_end"])
    horizon = int(s.cfg["label"]["horizon_days"])
    filed = pd.to_datetime(errs["date_of_filing"]).astype("datetime64[ns]")
    decided = pd.to_datetime(errs["date_of_decision"]).astype("datetime64[ns]")
    last = pd.to_datetime(errs["date_last_list"]).astype("datetime64[ns]")
    days_taken = (decided - filed).dt.days
    # Comparisons done once, as columns, rather than row by row.
    undecided = (decided.isna() | (decided > pd.Timestamp(s.cfg["label"]["collection_end"]))).to_numpy()
    stale = (last.notna() & (last < t_end - np.timedelta64(730, "D"))).to_numpy()
    just_late = (days_taken <= horizon + 120).fillna(False).to_numpy()
    labelled = (errs["disp_group"].notna() & ~errs["disp_group"].isin(["Missing"])).to_numpy()

    def cause(i: int) -> str:
        r = errs.iloc[i]
        if r["y"] == 0:
            if undecided[i]:
                if labelled[i]:
                    return "Outcome recorded but no decision date (rule X04)"
                if stale[i]:
                    return "Never decided; no hearing in the 2 years before T_end (possibly an unclosed record)"
                return "Never decided; still being heard"
            if just_late[i]:
                return "Decided within 4 months after the window closed"
            return "Decided, but well after the window"
        group = r["disp_group"]
        if group == "Transferred / committed":
            return "Closed by transfer or committal, not resolved (rule X09)"
        if group in ("Settled / ADR", "Withdrawn / lapsed"):
            return "Ended early: settled, withdrawn or lapsed"
        if group == "Generic 'disposed'":
            return "Closed with a vague 'disposed' label"
        if group in ("Merits", "Admission / plea"):
            return "Decided on the merits or by plea, faster than this court's history"
        return "Other or missing outcome label"

    errs["likely_cause"] = [cause(i) for i in range(len(errs))]
    errs["days_to_decision"] = days_taken
    errs["days_filing_to_last_hearing"] = (last - filed).dt.days
    keep = ["error", "likely_cause", "m2_p", "state_name", "court_level", "case_type", "act", "filing_quarter", "b1_score",
            "b2_score", "outcome_label", "disp_group", "days_to_decision", "days_filing_to_last_hearing", "leak_last_hearing_stage"]
    table = errs[keep].rename(columns={"m2_p": "predicted_p", "leak_last_hearing_stage": "last_hearing_stage"})
    summary = (table.groupby(["error", "likely_cause"]).size().rename("cases").reset_index()
               .sort_values(["error", "cases"], ascending=[True, False]))
    return table, summary


MIN_CELL = 20  # the smallest court x case-type group whose observed outcomes are published


def suppress_small_cells(table: pd.DataFrame) -> None:
    """Blank observed outcomes for groups under MIN_CELL test cases, so no published cell describes one or two cases."""
    small = table["test_cases"] < MIN_CELL
    table.loc[small, ["observed_rate", "mean_p_actual_cases"]] = np.nan


def whatif(s: Settings, test: pd.DataFrame, preds: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Score a typical case of each type in every court, using the court's history as of the test year."""
    path = whatif_path(s)
    if not path.exists():
        return pd.DataFrame()
    base = pd.read_parquet(path)
    typical = json.loads((s.models_dir / "typical_case.json").read_text())
    meta = json.loads((s.models_dir / "m2_meta.json").read_text())
    booster = lgb.Booster(model_file=str(s.models_dir / "m2_lgbm.txt"))
    with open(s.models_dir / "m2_isotonic.pkl", "rb") as fh:
        iso = pickle.load(fh)
    base = base[base["case_type"].isin(typical)].copy()
    for c in CASE:
        if c != "case_type":
            base[c] = base["case_type"].map(lambda t, c=c: typical[t][c])
    year = int(s.cfg["split"]["test_year"])
    base["filing_year"], base["filing_month"], base["filing_weekday"] = year, 7, 3
    base["log_court_filings_py"] = np.log1p(base["court_filings_py"])
    base["log_court_pending_at_filing"] = np.log1p(base["court_pending_at_filing"])
    base["court_backlog_months"] = base["court_pending_at_filing"] / (base["court_decided_prev_12m"] / 12 + 1)
    for c in ("state", "district", "court", "court_level"):
        base[c] = base[c].astype(str)
    raw = booster.predict(lgb_matrix(base, FEATURES, meta["categories"]))
    base["p_model"] = iso.predict(raw)
    base["b1_rate"] = base["court_disp_rate_py"].fillna(base["district_disp_rate_py"]).fillna(base["state_disp_rate_py"])
    base["b2_rate"] = base["court_type_disp_rate_py"].fillna(base["b1_rate"])
    # A disposal rate is the share of a year's workload decided, not the chance of a decision within 24 months. Map
    # each baseline onto that chance with the same isotonic fit on 2015 used in evaluation, so all four are comparable.
    for key, column in (("b1", "b1_rate"), ("b2", "b2_rate")):
        valid = part(preds[key], "valid")
        fit = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(valid["score"], valid["y"])
        base[f"p_{key}"] = fit.predict(base[column].fillna(valid["score"].median()))
    observed = (test.groupby(["court", "case_type"]).agg(test_cases=("y", "size"), observed_rate=("y", "mean"),
                                                          mean_p_actual_cases=("m2_p", "mean")).reset_index())
    base = base.merge(observed, on=["court", "case_type"], how="left")
    base["test_cases"] = base["test_cases"].fillna(0).astype(int)
    suppress_small_cells(base)
    dims = pd.read_parquet(s.source / "maps" / "dim_district.parquet")[["state_code", "dist_code", "state_name", "district_name"]]
    dims["district"] = dims["state_code"] + "-" + dims["dist_code"]
    base = base.merge(dims[["district", "state_name", "district_name"]].drop_duplicates("district"), on="district", how="left")
    keep = ["state", "state_name", "district", "district_name", "court", "court_name", "court_level", "case_type", "p_model",
            "p_b1", "p_b2", "b1_rate", "b2_rate", "court_type_share_py", "court_pending_at_filing", "test_cases", "observed_rate", "mean_p_actual_cases"]
    return base[keep].sort_values(["state_name", "district_name", "court_name", "case_type"]).reset_index(drop=True)


def run(s: Settings) -> dict:
    s.ensure_dirs()
    t0 = time.time()
    ev = s.cfg["evaluate"]
    preds = load_predictions(s)
    preds["m2_cal"] = calibrate(preds, "m2", s)
    preds["m1_cal"] = calibrate(preds, "m1", s)
    results: dict = {"profile": s.profile, "feature_version": feature_version(s), "split_version": split_version(s)}

    # 1. Metrics on the seen-court and unseen-court test splits.
    seen = metrics_table(preds, "test")
    unseen = metrics_table(preds, "test_unseen")
    valid = metrics_table(preds, "valid")
    seen.to_csv(s.reports / "test_metrics.csv", index=False)
    both = seen.merge(unseen, on=["key", "model"], suffixes=("_seen", "_unseen"))
    both.to_csv(s.reports / "seen_vs_unseen.csv", index=False)
    results["test"] = seen.set_index("key").to_dict("index")
    results["test_unseen"] = unseen.set_index("key").to_dict("index")
    results["valid"] = valid.set_index("key").to_dict("index")

    # 2. Calibration: curves before and after isotonic recalibration.
    curves = []
    for key in ("m2", "m2_cal", "m1", "m1_cal", "b1"):
        d = part(preds[key], "test")
        for r in calibration_table(d["y"], d["p"], int(ev["calibration_bins"])):
            curves.append({"key": key, "model": seen.set_index("key").loc[key, "model"]} | r)
    curves = pd.DataFrame(curves)
    curves.to_csv(s.reports / "calibration.csv", index=False)

    # 3. Threshold. With calibrated probabilities, flagging a case when a decision within the window is less likely
    #    than not (p < 0.5) is the cut-off that minimises expected mistakes when both kinds of mistake cost the same.
    #    Capacity cut-offs answer a different question: if a registry can review only a share of new filings.
    test_cal = part(preds["m2_cal"], "test")
    valid_cal = part(preds["m2_cal"], "valid")
    results["threshold"] = {"rule": "flag when calibrated P(decided within 24 months) < 0.5", "value": THRESHOLD,
                            "valid": delay_flags_at(valid_cal["y"], valid_cal["p"], THRESHOLD),
                            "test": delay_flags_at(test_cal["y"], test_cal["p"], THRESHOLD)}
    capacity = []
    for share in ev["capacity_shares"]:
        cut = threshold_for_share(valid_cal["p"], share)  # chosen on validation, applied to test
        capacity.append({"review_share": share, "threshold_from_valid": cut} | delay_flags_at(test_cal["y"], test_cal["p"], cut))
    results["capacity"] = capacity
    pd.DataFrame(capacity).to_csv(s.reports / "capacity_thresholds.csv", index=False)

    # 4. Paired bootstrap of the AUC gap, by case (as specified) and by court (cases in one court are correlated).
    attrs = attributes(s)
    m2t, b1t = part(preds["m2"], "test"), part(preds["b1"], "test")
    assert (m2t["ddl_case_id"].to_numpy() == b1t["ddl_case_id"].to_numpy()).all(), "predictions must be aligned"
    courts = m2t[["ddl_case_id"]].merge(attrs[["ddl_case_id", "court"]], on="ddl_case_id", how="left")["court"].to_numpy()
    reps = int(ev["bootstrap_resamples"])
    gaps = {}
    gaps["m2_vs_b1_case"] = bootstrap_auc_gap(m2t["y"], m2t["score"], b1t["score"], reps, s.seed)
    gaps["m2_vs_b1_court"] = bootstrap_auc_gap(m2t["y"], m2t["score"], b1t["score"], reps, s.seed, clusters=courts)
    b2t = part(preds["b2"], "test")
    gaps["m2_vs_b2_case"] = bootstrap_auc_gap(m2t["y"], m2t["score"], b2t["score"], reps, s.seed)
    gaps["b2_vs_b1_case"] = bootstrap_auc_gap(m2t["y"], b2t["score"], b1t["score"], reps, s.seed)
    m2u, b1u = part(preds["m2"], "test_unseen"), part(preds["b1"], "test_unseen")
    courts_u = m2u[["ddl_case_id"]].merge(attrs[["ddl_case_id", "court"]], on="ddl_case_id", how="left")["court"].to_numpy()
    gaps["unseen_m2_vs_b1_court"] = bootstrap_auc_gap(m2u["y"], m2u["score"], b1u["score"], reps, s.seed, clusters=courts_u)
    pd.DataFrame({"case": gaps["m2_vs_b1_case"]["gaps"], "court": gaps["m2_vs_b1_court"]["gaps"]}).to_csv(
        s.reports / "bootstrap_gaps.csv", index=False)
    results["gaps"] = {k: {kk: vv for kk, vv in v.items() if kk != "gaps"} for k, v in gaps.items()}

    # 5. Slices on the seen-court test split.
    test = (m2t[["ddl_case_id", "y", "score"]].rename(columns={"score": "m2"})
            .assign(m2_p=test_cal["p"].to_numpy(), b1=b1t["score"].to_numpy())
            .merge(attrs, on="ddl_case_id", how="left"))
    valid_frame = (part(preds["m2"], "valid")[["ddl_case_id", "y", "score"]].rename(columns={"score": "m2"})
                   .assign(m2_p=valid_cal["p"].to_numpy(), b1=part(preds["b1"], "valid")["score"].to_numpy())
                   .merge(attrs, on="ddl_case_id", how="left"))
    sl = slices(test, s)
    years = slices(pd.concat([valid_frame, test]).assign(filing_quarter=lambda d: d["filing_year"].astype(str)), s)
    years = years[years["dimension"] == "Filing quarter"].assign(dimension="Filing year (2015 is validation)")
    sl = pd.concat([sl, years], ignore_index=True)
    sl.to_csv(s.reports / "slices.csv", index=False)
    ranked = sl[sl["rankable"] & sl["dimension"].isin(["State", "Case type", "Court level"])].nsmallest(5, "auc_m2")
    results["worst_slices"] = ranked.to_dict("records")
    results["slice_counts"] = sl.groupby("dimension")["rankable"].agg(["size", "sum"]).rename(columns={"size": "slices", "sum": "rankable"}).to_dict("index")

    # 6. Importance.
    imp = importance(s, m2t["ddl_case_id"], m2t["y"].to_numpy())
    imp.to_csv(s.reports / "importance.csv", index=False)
    results["importance"] = imp.head(15).to_dict("records")

    # 7. Errors.
    errs, causes = error_cases(s, test)
    errs.to_csv(s.reports / "error_cases.csv", index=False)
    causes.to_csv(s.reports / "error_causes.csv", index=False)
    results["error_causes"] = causes.to_dict("records")

    # 8. What-if table for the dashboard.
    wi = whatif(s, test, preds)
    if len(wi):
        wi.to_parquet(s.mart / "ml_whatif.parquet", index=False)
    results["whatif_rows"] = int(len(wi))

    # Dashboard tables: small aggregates only.
    s.mart.mkdir(parents=True, exist_ok=True)
    both.to_parquet(s.mart / "ml_metrics.parquet", index=False)
    curves.to_parquet(s.mart / "ml_calibration.parquet", index=False)
    sl.to_parquet(s.mart / "ml_slices.parquet", index=False)
    imp.to_parquet(s.mart / "ml_importance.parquet", index=False)
    pd.DataFrame(capacity).to_parquet(s.mart / "ml_capacity.parquet", index=False)

    # Log the evaluation itself, so the interval and threshold figures trace to an experiments.csv row.
    tracker = Tracker(s, results["feature_version"], results["split_version"])
    g, gc = results["gaps"]["m2_vs_b1_case"], results["gaps"]["m2_vs_b1_court"]
    th = results["threshold"]["test"]
    cal = results["test"]["m2_cal"]
    row = tracker.log("evaluation", "M2 vs B1 on test (bootstrap, calibration, threshold)",
                      {"resamples": reps, "threshold": THRESHOLD, "calibration": "isotonic on valid"},
                      {"test_auc": results["test"]["m2"]["roc_auc"], "test_pr_auc": results["test"]["m2"]["pr_auc"],
                       "test_brier": cal["brier"], "test_log_loss": cal["log_loss"],
                       "test_unseen_auc": results["test_unseen"]["m2"]["roc_auc"]},
                      time.time() - t0, features=len(FEATURES),
                      extra={"auc_gap_vs_b1": g["gap"], "gap_ci_case_low": g["ci_low"], "gap_ci_case_high": g["ci_high"],
                             "gap_ci_court_low": gc["ci_low"], "gap_ci_court_high": gc["ci_high"],
                             "b1_test_auc": results["test"]["b1"]["roc_auc"], "precision_delay_at_0.5": th["precision_delay"],
                             "recall_delay_at_0.5": th["recall_delay"], "flagged_share_at_0.5": th["flagged_share"],
                             "ece_raw": results["test"]["m2"]["ece"], "ece_calibrated": cal["ece"]},
                      notes="Brier, log loss and ECE use the isotonic-calibrated M2")
    results["evaluation_run_id"] = row["run_id"]
    results["seconds"] = round(time.time() - t0, 1)
    s.results_path.write_text(json.dumps(py(results), indent=1))
    # The few headline numbers the dashboard shows, so it never needs the reports folder.
    train = json.loads((s.reports / "train_summary.json").read_text())
    final = pd.read_csv(s.experiments_path)
    final = final[(final["session"] == final.loc[final["model"] == "M2 LightGBM", "session"].iloc[-1]) & (final["stage"] == "final")]
    summary = {
        "evaluation_run_id": row["run_id"], "m2_run_id": final.loc[final["model"] == "M2 LightGBM", "run_id"].iloc[-1],
        "sample": json.loads((s.reports / "sample_summary.json").read_text()),
        "rows": train["rows"], "gaps": results["gaps"], "threshold": results["threshold"],
        "court_only_auc": train["experiments"]["court_only"]["test_auc"], "case_only_auc": train["experiments"]["case_only"]["test_auc"],
        "test_year": int(s.cfg["split"]["test_year"]), "horizon_days": int(s.cfg["label"]["horizon_days"]),
    }
    (s.mart / "ml_summary.json").write_text(json.dumps(py(summary), indent=1))
    print(seen[["model", "roc_auc", "pr_auc", "brier", "log_loss", "ece"]].round(4).to_string(index=False), flush=True)
    print(json.dumps(py(results["gaps"]), indent=1), flush=True)
    print(f"evaluate done in {results['seconds']}s", flush=True)
    return results


if __name__ == "__main__":
    with Timer():
        run(load())
