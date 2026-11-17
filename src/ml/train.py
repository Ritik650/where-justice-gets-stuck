"""Step `make train`: baselines, logistic regression, LightGBM and a Cox model, with every run logged.

All models learn from the `train` split only. `valid` is used for early stopping, for choosing among the LightGBM
settings and for calibrating the baseline scores. `test` and `test_unseen` are scored once, by the chosen models: grid
candidates are logged with validation metrics only, so the test set never steers a choice.

    B0  majority class: the training base rate, the same for every case
    B1  the court's disposal rate in the year before filing
    B2  the court's disposal rate for the same case type in the year before filing, shrunk towards B1
    M1  logistic regression: one-hot categoricals, scaled numerics, balanced class weights
    M2  LightGBM: native categoricals, early stopping on valid, a small grid
    M3  Cox proportional hazards (lifelines), on durations with open cases censored at T_end

Experiments, logged for the report: the leakage test, the 12-month label, a cohort-based variant of B1, court-only and
case-only feature sets, a shorter training window, and M2 without the court and district IDs.
"""
from __future__ import annotations

import itertools
import json
import pickle
import warnings

import lightgbm as lgb
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from lifelines import CoxPHFitter
from lifelines.utils import concordance_index
from sklearn.compose import ColumnTransformer
from sklearn.exceptions import ConvergenceWarning
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .features import CATEGORICAL, FEATURES, LEAK_CATEGORICAL, NUMERIC, feature_version
from .metrics import binary_metrics, slice_auc
from .settings import Settings, load
from .split import split_version
from .tracking import Timer, Tracker

LABEL = "label_24m"
SCORED = ("valid", "test", "test_unseen")

# Feature groups for the court-versus-case ablation.
TIMING = ["filing_year", "filing_month", "filing_weekday"]
COURT = ["state", "district", "court", "court_level", "court_disp_rate_py", "district_disp_rate_py", "state_disp_rate_py",
         "court_cohort_rate_lag3", "log_court_filings_py", "log_court_pending_at_filing", "court_backlog_months", "court_years_active"]
CASE = ["case_type", "case_type_label", "act", "act_section", "ddl_criminal_flag", "petitioner_gender", "defendant_gender",
        "petitioner_advocate"]
COURT_X_CASE = ["court_type_disp_rate_py", "court_type_share_py"]
assert set(TIMING + COURT + CASE + COURT_X_CASE) == set(FEATURES), "the ablation groups must cover every feature once"


def read_frame(s: Settings) -> pd.DataFrame:
    """Features joined to their split. Strings load as categoricals, which keeps 3M rows small in memory."""
    df = pq.read_table(s.features_path).to_pandas(strings_to_categorical=True)
    df["ddl_case_id"] = df["ddl_case_id"].astype(str)
    splits = pd.read_parquet(s.splits_path)
    df = df.merge(splits, on="ddl_case_id", how="inner", validate="one_to_one")
    df["split"] = df["split"].astype(str)
    return df


class Data:
    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.parts = {name: df.index[df["split"] == name] for name in ("train",) + SCORED}

    def rows(self) -> dict:
        return {name: int(len(idx)) for name, idx in self.parts.items()}

    def y(self, part: str, label: str = LABEL) -> np.ndarray:
        return self.df.loc[self.parts[part], label].to_numpy().astype(int)


def lgb_matrix(df: pd.DataFrame, cols: list[str], categories: dict[str, list]) -> pd.DataFrame:
    """Categoricals keep the training vocabulary; a value never seen in training becomes missing."""
    out = {}
    for c in cols:
        if c in categories:
            out[c] = pd.Categorical(df[c].astype(str), categories=categories[c])
        else:
            out[c] = df[c].astype("float64").to_numpy()
    return pd.DataFrame(out, index=df.index)


def lgb_params(s: Settings, grid_point: dict) -> dict:
    return {
        "objective": "binary", "metric": ["auc", "binary_logloss"], "feature_fraction": 0.9, "bagging_fraction": 0.8,
        "bagging_freq": 1, "lambda_l2": 1.0, "cat_smooth": 10.0, "cat_l2": 10.0, "min_data_per_group": 100,
        "max_cat_threshold": 64, "verbose": -1, "seed": s.seed, "deterministic": True, "force_col_wise": True,
        "num_threads": s.threads,
    } | grid_point


class LGBM:
    """One LightGBM model on a chosen feature list, early-stopped on the validation split."""

    def __init__(self, data: Data, cols: list[str], s: Settings, label: str = LABEL, train_idx=None):
        self.cols, self.s, self.label = cols, s, label
        train_idx = data.parts["train"] if train_idx is None else train_idx
        train = data.df.loc[train_idx]
        cat_cols = [c for c in cols if c in CATEGORICAL or c in LEAK_CATEGORICAL]
        self.categories = {c: sorted(train[c].astype(str).unique()) for c in cat_cols}
        self.data, self.train_idx = data, train_idx

    def matrix(self, idx) -> pd.DataFrame:
        return lgb_matrix(self.data.df.loc[idx], self.cols, self.categories)

    def fit(self, grid_point: dict) -> LGBM:
        cfg = self.s.cfg["train"]
        ytr = self.data.df.loc[self.train_idx, self.label].to_numpy()
        dtrain = lgb.Dataset(self.matrix(self.train_idx), ytr, categorical_feature=list(self.categories) or "auto", free_raw_data=True)
        dvalid = lgb.Dataset(self.matrix(self.data.parts["valid"]), self.data.y("valid", self.label), reference=dtrain)
        self.params = lgb_params(self.s, grid_point)
        self.booster = lgb.train(self.params, dtrain, num_boost_round=int(cfg["lgbm_max_rounds"]), valid_sets=[dvalid],
                                 valid_names=["valid"],
                                 callbacks=[lgb.early_stopping(int(cfg["early_stopping_rounds"]), first_metric_only=True, verbose=False)])
        self.best_iteration = int(self.booster.best_iteration or self.booster.current_iteration())
        return self

    def predict(self, part: str) -> np.ndarray:
        return self.booster.predict(self.matrix(self.data.parts[part]), num_iteration=self.best_iteration)


def logistic(s: Settings) -> Pipeline:
    cat = OneHotEncoder(handle_unknown="infrequent_if_exist", min_frequency=int(s.cfg["features"]["min_category_count"]),
                        sparse_output=True)
    num = make_pipeline(SimpleImputer(strategy="median", add_indicator=True), StandardScaler())
    pre = ColumnTransformer([("cat", cat, CATEGORICAL), ("num", num, NUMERIC)], sparse_threshold=1.0)
    clf = LogisticRegression(C=float(s.cfg["train"]["logistic_c"]), class_weight="balanced",
                             max_iter=int(s.cfg["train"]["logistic_max_iter"]), solver="lbfgs")
    return Pipeline([("pre", pre), ("clf", clf)])


def as_frame(data: Data, cols: list[str], part: str) -> pd.DataFrame:
    x = data.df.loc[data.parts[part], cols].copy()
    for c in cols:
        if c in CATEGORICAL:
            x[c] = x[c].astype(str)
    return x


def cox_design(df: pd.DataFrame, stats: dict | None = None) -> tuple[pd.DataFrame, dict]:
    """A compact design for lifelines: history scores, case type, court level and parties. No court IDs."""
    numeric = ["b1_score", "b2_score", "district_disp_rate_py", "log_court_pending_at_filing", "court_backlog_months",
               "court_type_share_py", "filing_year"]
    x = pd.DataFrame(index=df.index)
    if stats is None:
        stats = {"median": {c: float(df[c].median()) for c in numeric}}
        filled = {c: df[c].astype(float).fillna(stats["median"][c]) for c in numeric}
        stats["mean"] = {c: float(filled[c].mean()) for c in numeric}
        stats["std"] = {c: float(filled[c].std() or 1.0) for c in numeric}
        stats["case_types"] = sorted(df["case_type"].astype(str).unique())[1:]
        stats["court_levels"] = sorted(df["court_level"].astype(str).unique())[1:]
    for c in numeric:
        v = df[c].astype(float).fillna(stats["median"][c])
        x[c] = (v - stats["mean"][c]) / stats["std"][c]
    for level in stats["case_types"]:
        x[f"type={level}"] = (df["case_type"].astype(str) == level).astype(float)
    for level in stats["court_levels"]:
        x[f"court_level={level}"] = (df["court_level"].astype(str) == level).astype(float)
    x["petitioner_woman"] = (df["petitioner_gender"].astype(str) == "woman").astype(float)
    x["defendant_woman"] = (df["defendant_gender"].astype(str) == "woman").astype(float)
    x["petitioner_advocate_named"] = (df["petitioner_advocate"].astype(str) != "none named").astype(float)
    return x, stats


def metric_row(data: Data, scores: dict[str, np.ndarray], probs: dict[str, np.ndarray] | None = None, label: str = LABEL) -> dict:
    """Ranking metrics from the raw score; probability metrics from the probability (calibrated where needed)."""
    probs = probs or scores
    out = {}
    for part in scores:
        y = data.y(part, label)
        m = binary_metrics(y, probs[part])
        m["roc_auc"] = slice_auc(y, scores[part])
        out[part] = m
    row = {}
    for part, prefix in (("valid", "valid"), ("test", "test")):
        if part in out:
            row |= {f"{prefix}_auc": out[part].get("roc_auc"), f"{prefix}_pr_auc": out[part].get("pr_auc"),
                    f"{prefix}_brier": out[part].get("brier"), f"{prefix}_log_loss": out[part].get("log_loss")}
    if "test_unseen" in out:
        row["test_unseen_auc"] = out["test_unseen"].get("roc_auc")
    return row


def save_predictions(s: Settings, data: Data, key: str, scores: dict, probs: dict | None = None) -> None:
    probs = probs or scores
    frames = []
    for part in scores:
        idx = data.parts[part]
        frames.append(pd.DataFrame({"ddl_case_id": data.df.loc[idx, "ddl_case_id"].to_numpy(), "split": part,
                                    "y": data.y(part), "score": scores[part], "p": probs[part]}))
    pd.concat(frames, ignore_index=True).to_parquet(s.predictions_dir / f"{key}.parquet", index=False)


def run(s: Settings) -> dict:
    s.ensure_dirs()
    data = Data(read_frame(s))
    tracker = Tracker(s, feature_version(s), split_version(s))
    rows = data.rows()
    print(f"rows: {rows}", flush=True)
    summary: dict = {"rows": rows}

    # B0: the training base rate for every case.
    with Timer() as t:
        base = float(data.y("train").mean())
        scores = {p: np.full(len(data.parts[p]), base) for p in SCORED}
    tracker.log("final", "B0 majority class", {"base_rate": base}, metric_row(data, scores), t.seconds,
                features=0, rows=rows, extra={"majority_label": int(base >= 0.5)})
    save_predictions(s, data, "b0", scores)

    # B1, B2 (and the cohort variant B1b): history rates are scores, not probabilities. AUC uses them as they are;
    # Brier score and log loss use an isotonic calibration fitted on the validation split.
    for key, column, name, stage, note in (
        ("b1", "b1_score", "B1 court prior-year disposal rate", "final", "fallback: district, then state, then national rate"),
        ("b2", "b2_score", "B2 court x case-type prior-year rate", "final", f"shrunk towards B1 with k={s.cfg['features']['shrink_k']}"),
        ("b1b", "b1b_score", "B1b court 24-month rate, cohort filed 3 years earlier", "experiment", "variant of B1 aligned with the label"),
    ):
        with Timer() as t:
            raw = {p: data.df.loc[data.parts[p], column].astype(float).fillna(base).to_numpy() for p in SCORED}
            iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(raw["valid"], data.y("valid"))
            probs = {p: iso.predict(raw[p]) for p in SCORED}
        tracker.log(stage, name, {"score": column, "calibration": "isotonic on valid"}, metric_row(data, raw, probs), t.seconds,
                    features=1, rows=rows, notes=note)
        save_predictions(s, data, key, raw, probs)

    # M1: logistic regression.
    with Timer() as t, warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ConvergenceWarning)
        m1 = logistic(s).fit(as_frame(data, FEATURES, "train"), data.y("train"))
        scores = {p: m1.predict_proba(as_frame(data, FEATURES, p))[:, 1] for p in SCORED}
    converged = not any(issubclass(w.category, ConvergenceWarning) for w in caught)
    n_columns = int(m1.named_steps["pre"].transform(as_frame(data, FEATURES, "valid").head(5)).shape[1])
    tracker.log("final", "M1 logistic regression", {"C": s.cfg["train"]["logistic_c"], "class_weight": "balanced",
                "max_iter": s.cfg["train"]["logistic_max_iter"], "min_frequency": s.cfg["features"]["min_category_count"]},
                metric_row(data, scores), t.seconds, features=len(FEATURES), rows=rows,
                extra={"design_columns": n_columns, "converged": converged, "iterations": int(m1.named_steps["clf"].n_iter_[0])},
                notes="" if converged else "lbfgs hit max_iter")
    save_predictions(s, data, "m1", scores)
    with open(s.models_dir / "m1_logistic.pkl", "wb") as fh:
        pickle.dump(m1, fh)

    # M2: LightGBM grid, chosen on validation AUC. Candidates get no test metrics.
    grid = s.cfg["train"]["lgbm_grid"]
    points = [dict(zip(grid, values)) for values in itertools.product(*grid.values())]
    best = None
    for point in points:
        with Timer() as t:
            model = LGBM(data, FEATURES, s).fit(point)
            valid = model.predict("valid")
        auc = slice_auc(data.y("valid"), valid)
        tracker.log("grid", "M2 LightGBM candidate", point | {"best_iteration": model.best_iteration},
                    metric_row(data, {"valid": valid}), t.seconds, features=len(FEATURES), rows=rows)
        if best is None or auc > best[0]:
            best = (auc, point, model, t.seconds)
    _, best_point, m2, fit_seconds = best
    with Timer() as t:
        scores = {p: m2.predict(p) for p in SCORED}
    tracker.log("final", "M2 LightGBM", best_point | {"best_iteration": m2.best_iteration, "selected_from": len(points)},
                metric_row(data, scores), fit_seconds + t.seconds, features=len(FEATURES), rows=rows,
                notes="best of the grid on validation AUC")
    save_predictions(s, data, "m2", scores)
    m2.booster.save_model(str(s.models_dir / "m2_lgbm.txt"), num_iteration=m2.best_iteration)
    (s.models_dir / "m2_meta.json").write_text(json.dumps({
        "params": m2.params, "best_iteration": m2.best_iteration, "features": FEATURES, "categories": m2.categories,
        "grid_point": best_point}, indent=1, default=str))
    summary["m2"] = {"grid_point": best_point, "best_iteration": m2.best_iteration}

    # M3: Cox model on a seeded subsample of the training split, open cases censored at T_end.
    with Timer() as t:
        train = data.df.loc[data.parts["train"]]
        n = min(int(s.cfg["train"]["cox_rows"]), len(train))
        train = train.sample(n=n, random_state=s.seed)
        x, stats = cox_design(train)
        x["duration"] = train["duration_days"].to_numpy() + 0.5
        x["event"] = train["event_by_t_end"].to_numpy()
        cph = CoxPHFitter(penalizer=0.01).fit(x, duration_col="duration", event_col="event")
        horizon = float(s.cfg["label"]["horizon_days"]) + 0.5
        scores, cindex = {}, {}
        for part in SCORED:
            frame = data.df.loc[data.parts[part]]
            xp, _ = cox_design(frame, stats)
            surv = cph.predict_survival_function(xp, times=[horizon]).to_numpy().ravel()
            scores[part] = 1.0 - surv
            hazard = cph.predict_partial_hazard(xp).to_numpy()
            cindex[part] = float(concordance_index(frame["duration_days"] + 0.5, -hazard, frame["event_by_t_end"]))
    tracker.log("final", "M3 Cox proportional hazards", {"rows": n, "penalizer": 0.01, "covariates": int(x.shape[1] - 2)},
                metric_row(data, scores), t.seconds, features=int(x.shape[1] - 2), rows=rows | {"train": n},
                extra={f"c_index_{p}": v for p, v in cindex.items()} | {"c_index_train": float(cph.concordance_index_)},
                notes="score = 1 - S(730 days); C-index on durations censored at T_end")
    save_predictions(s, data, "m3", scores)
    summary["m3"] = {"c_index": cindex}

    # Experiments with the chosen LightGBM settings.
    def experiment(name: str, cols: list[str], note: str, label: str = LABEL, train_idx=None) -> dict:
        with Timer() as t:
            model = LGBM(data, cols, s, label=label, train_idx=train_idx).fit(best_point)
            exp_scores = {p: model.predict(p) for p in SCORED}
        row = tracker.log("experiment", name, best_point | {"best_iteration": model.best_iteration, "features": cols},
                          metric_row(data, exp_scores, label=label), t.seconds, label=label, features=len(cols),
                          rows=rows | ({"train": int(len(train_idx))} if train_idx is not None else {}), notes=note)
        return {"valid_auc": row["valid_auc"], "test_auc": row["test_auc"], "test_unseen_auc": row["test_unseen_auc"], "run_id": row["run_id"]}

    exp = {}
    exp["leak_last_hearing"] = experiment("M2 + leak: days to last hearing", FEATURES + ["leak_days_to_last_hearing"],
                                          "LEAKAGE TEST. Post-filing column added on purpose, then removed.")
    exp["leak_defendant_advocate"] = experiment("M2 + leak: defendant's advocate named", FEATURES + ["leak_defendant_advocate_named"],
                                                "LEAKAGE TEST. Entered when the defendant appears, after filing.")
    exp["court_only"] = experiment("M2 court + timing features only", COURT + TIMING, "No case features: what the court alone predicts")
    exp["case_only"] = experiment("M2 case + timing features only", CASE + TIMING, "No court identity or history: what the case alone predicts")
    exp["no_court_id"] = experiment("M2 without court and district IDs", [c for c in FEATURES if c not in ("court", "district")],
                                    "History features only describe the court")
    exp["label_12m"] = experiment("M2 12-month label", FEATURES, "Secondary label: decided within 365 days", label="label_12m")
    lo, hi = s.cfg["split"]["train_years"]
    recent = data.parts["train"][data.df.loc[data.parts["train"], "filing_year"].to_numpy() >= hi - 2]
    exp["recent_window"] = experiment(f"M2 trained on {hi - 2}-{hi} only", FEATURES,
                                      "Shorter window: early filings over-represent long cases", train_idx=recent)
    summary["experiments"] = exp

    # Typical case-level values per case type, for the dashboard's what-if (most common value in training).
    train = data.df.loc[data.parts["train"]]
    typical = {}
    for ctype, g in train.groupby("case_type", observed=True):
        typical[str(ctype)] = {c: str(g[c].astype(str).mode().iloc[0]) for c in CASE if c != "case_type"}
    (s.models_dir / "typical_case.json").write_text(json.dumps(typical, indent=1))
    (s.reports / "train_summary.json").write_text(json.dumps(summary, indent=1, default=str))
    print(json.dumps(summary, indent=1, default=str), flush=True)
    return summary


if __name__ == "__main__":
    run(load())
