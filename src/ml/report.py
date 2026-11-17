"""Step `make report`: write reports/ml_poc_report.md, docs/model_card.md and the figures, from logged results only.

Every number comes from reports/ml_results.json, the CSV tables beside it, or a row of reports/experiments.csv, and
each headline figure names the run it came from. Sentences that depend on a result (which model wins, whether an
interval excludes zero) are chosen by the numbers, so a rerun cannot leave a stale claim behind. For the full profile
this step also refreshes the README through pipeline/write_readme.py.
"""
from __future__ import annotations

import json
import subprocess
import sys

import pandas as pd

from . import figures as F
from .features import CATEGORICAL, FEATURES, NUMERIC
from .settings import ROOT, Settings, load


def pct(v: float, digits: int = 0) -> str:
    return f"{v * 100:.{digits}f}%"


def n(v: float) -> str:
    return f"{int(round(v)):,}"


def a3(v: float) -> str:
    return f"{v:.3f}"


def md_table(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    return "\n".join(lines)


class Inputs:
    def __init__(self, s: Settings):
        r = s.reports
        self.s = s
        self.res = json.loads(s.results_path.read_text())
        self.audit = pd.read_csv(r / "label_audit.csv")
        self.balance = pd.read_csv(r / "class_balance.csv")
        self.checks = pd.read_csv(r / "label_checks.csv")
        self.end = json.loads((r / "observation_end.json").read_text())
        self.sample = json.loads((r / "sample_summary.json").read_text())
        self.splits = pd.read_csv(r / "split_summary.csv")
        self.feat = json.loads((r / "features_summary.json").read_text())
        self.train = json.loads((r / "train_summary.json").read_text())
        self.exp = pd.read_csv(r / "experiments.csv")
        self.both = pd.read_csv(r / "seen_vs_unseen.csv")
        self.slices = pd.read_csv(r / "slices.csv")
        self.imp = pd.read_csv(r / "importance.csv")
        self.causes = pd.read_csv(r / "error_causes.csv")
        self.errors = pd.read_csv(r / "error_cases.csv")
        self.calib = pd.read_csv(r / "calibration.csv")
        self.capacity = pd.read_csv(r / "capacity_thresholds.csv")
        # The runs this report describes: the latest training session, and the latest evaluation.
        finals = self.exp[(self.exp["stage"] == "final") & (self.exp["model"] == "M2 LightGBM")]
        self.session = finals.iloc[-1]["session"]
        self.runs = self.exp[self.exp["session"] == self.session]
        self.eval_row = self.exp[self.exp["stage"] == "evaluation"].iloc[-1]
        # Those runs and the commit they ran from; older runs stay in the log, folded away in the appendix.
        cited = self.runs.index.union([self.eval_row.name])
        self.cited, self.earlier = self.exp.loc[cited], self.exp.drop(cited)
        self.commit = ", ".join(dict.fromkeys(self.cited["git_commit"].astype(str)))

    def run(self, model: str, stage: str = "final") -> pd.Series:
        hit = self.runs[(self.runs["model"] == model) & (self.runs["stage"] == stage)]
        return hit.iloc[-1]

    def run_id(self, model: str, stage: str = "final") -> str:
        return f"`{self.run(model, stage)['run_id']}`"

    def by_year(self) -> pd.DataFrame:
        b = self.balance[self.balance["cases_24m"] > 0]
        g = b.groupby("filing_year").apply(lambda d: pd.Series({
            "cases": d["cases_24m"].sum(), "rate_24m": (d["rate_24m"] * d["cases_24m"]).sum() / d["cases_24m"].sum(),
            "rate_12m": (d["rate_12m"] * d["cases_12m"]).sum() / d["cases_12m"].sum()}), include_groups=False).reset_index()
        return g


def figures(i: Inputs) -> dict[str, str]:
    out = i.s.figures_dir
    test = pd.DataFrame.from_dict(i.res["test"], orient="index").reset_index(names="key")
    keep = ["b0", "b1", "b2", "m1", "m2", "m3"]
    table = test[test["key"].isin(keep)][["model", "roc_auc"]]
    return {
        "balance": F.class_balance(i.by_year(), out / "class_balance.png"),
        "auc": F.model_auc(table, out / "test_auc.png", focus="M2 LightGBM"),
        "gap": F.gap_intervals(i.res["gaps"], out / "auc_gap.png"),
        "calibration": F.calibration(i.calib, out / "calibration.png"),
        "importance": F.importance(i.imp, out / "importance.png"),
        "unseen": F.seen_unseen(i.both, out / "seen_vs_unseen.png", ["b1", "b2", "m1", "m2"]),
        "states": F.state_slices(i.slices, out / "state_slices.png"),
    }


def results_table(i: Inputs) -> pd.DataFrame:
    rows = []
    order = ["b0", "b1", "b2", "m1", "m1_cal", "m2", "m2_cal", "m3"]
    for key in order:
        m = i.res["test"].get(key)
        if not m:
            continue
        u = i.res["test_unseen"].get(key, {})
        rows.append({"Model": m["model"], "ROC-AUC": a3(m["roc_auc"]), "PR-AUC": a3(m["pr_auc"]),
                     "PR-AUC (delay)": a3(m["pr_auc_delay"]), "Brier": a3(m["brier"]), "Log loss": a3(m["log_loss"]),
                     "ECE": a3(m["ece"]), "ROC-AUC, unseen courts": a3(u["roc_auc"]) if u.get("roc_auc") is not None else ""})
    return pd.DataFrame(rows)


def experiment_table(exp: pd.DataFrame) -> pd.DataFrame:
    """Logged runs in the order they ran, for the report appendix."""
    d = exp.copy()

    def fmt(v):
        return "" if pd.isna(v) or v == "" else f"{float(v):.3f}"

    out = pd.DataFrame({
        "Run": "`" + d["run_id"].astype(str) + "`", "Commit": "`" + d["git_commit"].astype(str) + "`",
        "Stage": d["stage"], "Model": d["model"], "Label": d["label"].str.replace("label_", ""),
        "Valid AUC": d["valid_auc"].map(fmt), "Test AUC": d["test_auc"].map(fmt), "Unseen-court AUC": d["test_unseen_auc"].map(fmt),
        "Test Brier": d["test_brier"].map(fmt), "Seconds": d["runtime_s"].map(lambda v: f"{float(v):,.0f}"),
    })
    return out


def earlier_runs(exp: pd.DataFrame) -> str:
    """Runs older than the ones a document quotes, folded under them."""
    if exp.empty:
        return ""
    return (f"\n<details>\n<summary>{len(exp)} earlier runs, superseded by the ones above</summary>\n\n"
            "A commit ending in `-dirty` means the code, SQL or config differed from that commit when the run started.\n\n"
            f"{md_table(experiment_table(exp))}\n\n</details>\n")


def write_report(i: Inputs, figs: dict[str, str]) -> str:
    s, res = i.s, i.res
    t, tu = res["test"], res["test_unseen"]
    g, gc, gb2 = res["gaps"]["m2_vs_b1_case"], res["gaps"]["m2_vs_b1_court"], res["gaps"]["m2_vs_b2_case"]
    gu = res["gaps"]["unseen_m2_vs_b1_court"]
    exp = i.train["experiments"]
    lab = s.cfg["label"]
    sp = s.cfg["split"]
    by_year = i.by_year()
    audit = i.audit
    pop = int(audit.loc[audit["step"] == audit["step"].max(), "rows"].iloc[0])
    total = int(audit.loc[audit["step"] == 0, "rows"].iloc[0])
    th = res["threshold"]["test"]
    cal_better = t["m2_cal"]["brier"] < t["m2"]["brier"]
    court_only, case_only = exp["court_only"]["test_auc"], exp["case_only"]["test_auc"]
    leak, leak2 = exp["leak_last_hearing"], exp["leak_defendant_advocate"]
    m3_c = i.train["m3"]["c_index"]["test"]

    if court_only >= case_only:
        who = (f"Mostly the court. With only court features (its identity, level and history) the model reaches a test "
               f"ROC-AUC of {a3(court_only)}; with only case features (type, act and section, parties) it reaches {a3(case_only)}.")
    else:
        who = (f"Mostly the case. With only case features (type, act and section, parties) the model reaches a test ROC-AUC "
               f"of {a3(case_only)}; with only court features it reaches {a3(court_only)}.")
    excludes_zero = gc["ci_low"] > 0
    gap_sentence = (
        f"The full model (M2) adds {gc['gap']:+.3f} ROC-AUC over the court's own prior-year disposal rate (B1): "
        f"{a3(t['m2']['roc_auc'])} against {a3(t['b1']['roc_auc'])}. The 95% interval is {gc['ci_low']:+.3f} to {gc['ci_high']:+.3f} "
        f"when whole courts are resampled, and {g['ci_low']:+.3f} to {g['ci_high']:+.3f} when cases are resampled "
        f"({g['resamples']:,} resamples each). " + ("Both intervals exclude zero, so the gain is not resampling noise."
                                                   if excludes_zero else "The court-level interval includes zero, so the gain is not established."))
    unseen_drop = t["m2"]["roc_auc"] - tu["m2"]["roc_auc"]

    worst = pd.DataFrame(res["worst_slices"])
    worst_tbl = worst.assign(**{"Slice": worst["dimension"] + ": " + worst["slice"], "Cases": worst["n"].map(n),
                                "Decided in 24m": worst["positive_rate"].map(pct), "M2 AUC": worst["auc_m2"].map(a3),
                                "B1 AUC": worst["auc_b1"].map(a3)})[["Slice", "Cases", "Decided in 24m", "M2 AUC", "B1 AUC"]]
    years = i.slices[i.slices["dimension"].str.startswith("Filing year")]
    years_tbl = years.assign(**{"Filing year": years["slice"], "Cases": years["n"].map(n), "Decided in 24m": years["positive_rate"].map(pct),
                                "M2 AUC": years["auc_m2"].map(a3), "B1 AUC": years["auc_b1"].map(a3)})[["Filing year", "Cases", "Decided in 24m", "M2 AUC", "B1 AUC"]]
    levels = i.slices[(i.slices["dimension"] == "Court level") & i.slices["rankable"]].sort_values("n", ascending=False)
    levels_tbl = levels.assign(**{"Court level": levels["slice"], "Cases": levels["n"].map(n), "Decided in 24m": levels["positive_rate"].map(pct),
                                  "M2 AUC": levels["auc_m2"].map(a3), "B1 AUC": levels["auc_b1"].map(a3)})[["Court level", "Cases", "Decided in 24m", "M2 AUC", "B1 AUC"]]
    types = i.slices[(i.slices["dimension"] == "Case type") & i.slices["rankable"]].sort_values("n", ascending=False)
    types_tbl = types.assign(**{"Case type": types["slice"], "Cases": types["n"].map(n), "Decided in 24m": types["positive_rate"].map(pct),
                                "M2 AUC": types["auc_m2"].map(a3), "B1 AUC": types["auc_b1"].map(a3)})[["Case type", "Cases", "Decided in 24m", "M2 AUC", "B1 AUC"]]
    audit_tbl = audit.assign(**{"Step": audit["description"], "Rule": audit["rule"].fillna(""), "Cases left": audit["rows"].map(n),
                                "Removed": audit["dropped"].map(lambda v: "" if pd.isna(v) else n(v))})[["Step", "Rule", "Cases left", "Removed"]]
    checks = i.checks.assign(**{"Check": i.checks["id"] + " " + i.checks["title"], "Status": i.checks["status"],
                                "Cases": i.checks["failures"].map(n), "Share": i.checks["rate"].map(lambda v: pct(v, 2))})[["Check", "Status", "Cases", "Share"]]
    yr_tbl = by_year.assign(**{"Filing year": by_year["filing_year"].astype(int), "Cases": by_year["cases"].map(n),
                               "Decided within 24 months": by_year["rate_24m"].map(pct), "Within 12 months": by_year["rate_12m"].map(pct)}
                            )[["Filing year", "Cases", "Decided within 24 months", "Within 12 months"]]
    st = i.balance[i.balance["cases_24m"] > 0].groupby("state_name").apply(lambda d: pd.Series({
        "cases": d["cases_24m"].sum(), "rate": (d["rate_24m"] * d["cases_24m"]).sum() / d["cases_24m"].sum()}), include_groups=False)
    st = st.sort_values("cases", ascending=False).head(12).reset_index()
    st_tbl = st.assign(**{"State": st["state_name"], "Cases filed 2010-16": st["cases"].map(n), "Decided within 24 months": st["rate"].map(pct)}
                       )[["State", "Cases filed 2010-16", "Decided within 24 months"]]
    split_tbl = i.splits.assign(**{"Split": i.splits["split"], "Cases": i.splits["cases"].map(n), "Courts": i.splits["courts"].map(n),
                                   "Years": i.splits["first_year"].astype(str) + "-" + i.splits["last_year"].astype(str),
                                   "Decided in 24m": i.splits["positive_rate"].map(pct), "ID fingerprint": "`" + i.splits["id_hash"] + "`"}
                                )[["Split", "Years", "Cases", "Courts", "Decided in 24m", "ID fingerprint"]]
    imp = i.imp.head(10)
    imp_tbl = imp.assign(**{"Feature": "`" + imp["feature"] + "`", "AUC drop when shuffled": imp["auc_drop"].map(lambda v: f"{v:.4f}"),
                            "Mean abs. SHAP": imp["mean_abs_shap"].map(lambda v: f"{v:.3f}")})[["Feature", "AUC drop when shuffled", "Mean abs. SHAP"]]
    cause_tbl = i.causes.assign(**{"Error": i.causes["error"].str.split(":").str[0], "Likely cause": i.causes["likely_cause"],
                                   "Cases (of 50)": i.causes["cases"]})[["Error", "Likely cause", "Cases (of 50)"]]
    cap_tbl = i.capacity.assign(**{"Review": i.capacity["review_share"].map(pct), "Cut-off (from 2015)": i.capacity["threshold_from_valid"].map(a3),
                                   "Flagged in 2016": i.capacity["flagged_share"].map(pct),
                                   "Precision (delay)": i.capacity["precision_delay"].map(pct),
                                   "Recall (delay)": i.capacity["recall_delay"].map(pct)})[["Review", "Cut-off (from 2015)", "Flagged in 2016", "Precision (delay)", "Recall (delay)"]]
    ablation = pd.DataFrame([
        {"Features": "All (M2)", "Test AUC": a3(t["m2"]["roc_auc"]), "Unseen-court AUC": a3(tu["m2"]["roc_auc"]), "Run": i.run_id("M2 LightGBM")},
        {"Features": "Court + timing only", "Test AUC": a3(court_only), "Unseen-court AUC": a3(exp["court_only"]["test_unseen_auc"]), "Run": f"`{exp['court_only']['run_id']}`"},
        {"Features": "Case + timing only", "Test AUC": a3(case_only), "Unseen-court AUC": a3(exp["case_only"]["test_unseen_auc"]), "Run": f"`{exp['case_only']['run_id']}`"},
        {"Features": "All except court and district IDs", "Test AUC": a3(exp["no_court_id"]["test_auc"]), "Unseen-court AUC": a3(exp["no_court_id"]["test_unseen_auc"]), "Run": f"`{exp['no_court_id']['run_id']}`"},
        {"Features": "B1 alone (court prior-year rate)", "Test AUC": a3(t["b1"]["roc_auc"]), "Unseen-court AUC": a3(tu["b1"]["roc_auc"]), "Run": i.run_id("B1 court prior-year disposal rate")},
    ])
    leak_tbl = pd.DataFrame([
        {"Model": "M2 (no post-filing columns)", "Valid AUC": a3(i.run("M2 LightGBM")["valid_auc"]), "Test AUC": a3(t["m2"]["roc_auc"]), "Run": i.run_id("M2 LightGBM")},
        {"Model": "M2 + days from filing to last hearing", "Valid AUC": a3(leak["valid_auc"]), "Test AUC": a3(leak["test_auc"]), "Run": f"`{leak['run_id']}`"},
        {"Model": "M2 + defendant's advocate named", "Valid AUC": a3(leak2["valid_auc"]), "Test AUC": a3(leak2["test_auc"]), "Run": f"`{leak2['run_id']}`"},
    ])
    leak_jump = leak["valid_auc"] - i.run("M2 LightGBM")["valid_auc"]
    m2_row = i.run("M2 LightGBM")
    m2_params = json.loads(m2_row["params"])
    grid_n = len(i.runs[i.runs["stage"] == "grid"])
    worst_text = "; ".join(f"{r['slice']} ({r['dimension'].lower()}, {a3(r['auc_m2'])})" for r in res["worst_slices"][:3])
    b1b_auc = float(i.run("B1b court 24-month rate, cohort filed 3 years earlier", "experiment")["test_auc"])
    top_feats = ", ".join(f"`{f}`" for f in i.imp["feature"].head(4))
    fp_top = i.causes[i.causes["error"].str.startswith("False positive")].head(2)
    fn_top = i.causes[i.causes["error"].str.startswith("False negative")].head(2)
    fp_text = " and ".join(f'"{r.likely_cause}" ({r.cases})' for r in fp_top.itertuples())
    fn_text = " and ".join(f'"{r.likely_cause}" ({r.cases})' for r in fn_top.itertuples())
    b2_share = (t["b2"]["roc_auc"] - t["b1"]["roc_auc"]) / max(t["m2"]["roc_auc"] - t["b1"]["roc_auc"], 1e-9)
    m1_extra = json.loads(i.run("M1 logistic regression")["extra_metrics"])
    m1_note = ("" if m1_extra.get("converged") else
               f"M1 stopped at its limit of {s.cfg['train']['logistic_max_iter']} L-BFGS iterations without fully converging "
               f"({m1_extra.get('design_columns', 0):,} design columns), so its scores are a lower bound for a fully fitted "
               "logistic regression.")
    no_id = exp["no_court_id"]
    id_note = ("" if no_id["test_auc"] - t["m2"]["roc_auc"] < 0.005 else
               f"Without the court and district IDs, validation AUC is lower ({a3(no_id['valid_auc'])} against "
               f"{a3(i.run('M2 LightGBM')['valid_auc'])}) but test AUC is higher ({a3(no_id['test_auc'])} against "
               f"{a3(t['m2']['roc_auc'])}): court effects learned from {sp['train_years'][0]}-{sp['train_years'][1]} go stale, while last "
               "year's rates stay current. Choosing the model on the test year would be peeking, so M2 stays the model "
               "chosen on validation; a next version should prefer history over identity, checked on a later validation year.")
    banner = ("> **Synthetic fixture.** This report was built on generated data (`src/ml/fixture.py`), not on court records. "
              "Its numbers only show that the pipeline runs end to end." + chr(10) * 2 if s.profile == "fixture" else "")
    window_note = ("No large state recorded under 80% of its late-2017 decisions in the last quarter of 2018."
                   if not i.end.get("states_last_quarter_below_80pct") else
                   f"In {', '.join(i.end['states_last_quarter_below_80pct'])}, decisions recorded in the last quarter of 2018 fell "
                   "below 80% of the same quarter a year earlier, so some labels for late-2016 filings there may be too low.")

    return f"""# Delay-risk model: proof of concept

*Generated by `make report` from logged runs; do not edit by hand. Profile `{s.profile}`, training session `{i.session}`,
evaluation run `{i.eval_row['run_id']}`, commit `{i.commit}`, feature version `{res['feature_version']}`, split version `{res['split_version']}`.*

{banner}
## Question

When a case is filed in an Indian district or subordinate court, can we predict whether it will be decided within
24 months, and how much does a model add over each court's own history? Put another way: **does the case matter, or
mostly the court?**

This is research on 2010-2018 records. It is not a tool for deciding anything about an individual case
([model card](../docs/model_card.md)).

## The answer

{who}

{gap_sentence}

Against the court's own rate for the same case type (B2), the gain is {gb2['gap']:+.3f} (case-level interval
{gb2['ci_low']:+.3f} to {gb2['ci_high']:+.3f}): B2 alone closes {b2_share:.0%} of the distance from B1 to M2. On courts
held out of training entirely, M2 scores {a3(tu['m2']['roc_auc'])}, {abs(unseen_drop):.3f} {"lower" if unseen_drop > 0 else "higher"} than on seen
courts, and its gain over B1 there is {gu['gap']:+.3f} ({gu['ci_low']:+.3f} to {gu['ci_high']:+.3f}, resampling courts).

![Test ROC-AUC by model](figures/{figs['auc']})

![AUC gain over court history](figures/{figs['gap']})

## Data

[Development Data Lab](https://www.devdatalab.org/judicial-data) eCourts records: {n(total)} cases filed 2010-2018, the
same files the rest of this project uses. Source files, sizes and SHA-256 hashes are in [data/MANIFEST.md](../data/MANIFEST.md).

**Observation end (T_end).** The latest plausible decision date in the files is {i.end['latest_decision_plausible']}
(the latest raw value, {i.end['latest_decision_raw']}, is a typing error caught by rule V03). But recorded decisions
fall from about {i.end['monthly_decisions_2018_mean'] / 1e5:.1f} lakh a month in 2018 to about {i.end['monthly_decisions_apr_dec_2019_mean'] / 1e5:.1f} lakh
from April 2019, because most courts were collected in early 2019 and only some again later. Using the latest date
would give re-collected courts extra months to close cases, so T_end is **{lab['t_end']}**, the cut-off the rest of the
project uses. {window_note}

**Censoring rule.** A label is only defined when its whole window is observed: filed on or before T_end minus
{lab['horizon_days']} days. Every case filed in 2017-2018 is therefore excluded from the 24-month label.

**Exclusions, with the existing data-quality rules** (`sql/labels.sql`, rule IDs from `sql/dq_rules.sql`):

{md_table(audit_tbl)}

The {n(pop)} cases left form the modelling population. A stratified sample of **{n(i.sample['sampled'])}** cases
({pct(i.sample['fraction'], 1)} of it, by state x filing year, seed {i.sample['seed']}, fingerprint `{i.sample['id_hash']}`)
is drawn by hashing each case ID with the seed, so the same cases are drawn on any machine.

## Label

`label_24m` = 1 if a decision is dated within {lab['horizon_days']} days of filing; 0 if the case was decided later or
was still pending at day {lab['horizon_days']}. `label_12m` uses {lab['secondary_horizon_days']} days, as a secondary check.
Full definition and edge cases: [docs/label_definition.md](../docs/label_definition.md).

{md_table(yr_tbl)}

![Class balance by filing year](figures/{figs['balance']})

Early filing years are slower because records were digitised mid-period: a 2010 case that closed quickly often never
entered the system, while a long-running one did. The temporal split below trains on these years and tests on 2016,
so this shift is part of what the test measures.

Largest states:

{md_table(st_tbl)}

Label checks (`sql/dq_labels.sql`). The six invariants must be zero, and the build stops if one is not:

{md_table(checks)}

## Features

{len(FEATURES)} features, every one known on the day of filing ([docs/features.md](../docs/features.md) gives each one's
point-in-time rule; [docs/feature_audit.md](../docs/feature_audit.md) marks every source column):

- **Case** ({len([c for c in CATEGORICAL if c not in ('state', 'district', 'court', 'court_level')])} categorical): standardised case type and raw type label, standardised act and act + section, DDL's criminal flag,
  petitioner and defendant gender as predicted from names (their "unclear" and "missing" codes double as party-type
  flags: a state or a company has no gendered name), and whether the petitioner's advocate is named.
- **Court identity**: state, district, court establishment and court level (from the establishment's name).
- **Court history** ({len([c for c in NUMERIC if c.startswith(('court', 'district', 'state', 'log_court'))])} numeric), computed in DuckDB SQL (`sql/features.sql`) from every validly filed case, not just the sample:
  the court's disposal rate in the previous calendar year, the same for its case type (shrunk towards the court's rate),
  district and state rates, the case type's share of last year's filings, last year's filing volume, the court's
  24-month rate for the cohort filed three years earlier, cases pending on the first day of the filing month, months of
  backlog at the recent disposal pace, and years since the court's first filing in the data.
- **Timing**: filing year, month and weekday.

**Excluded as known after filing**: decision date, disposition, hearing stage (purpose), first, last and next hearing
dates, judge designation (it reflects where a case sits at collection), the defendant's advocate, and the date-parse
audit field.

**Leakage test.** Adding an excluded column shows what a leak looks like. Each was added alone, measured, and removed again:

{md_table(leak_tbl)}

The days from filing to the last hearing lift validation AUC by {leak_jump:+.3f}. A score that high would be a
warning sign on its own. The defendant's advocate is a subtler leak: it is entered once the defendant contests, which
happens after filing and mostly in long cases.

## Splits

Temporal: train on filings {sp['train_years'][0]}-{sp['train_years'][1]}, validate on {sp['valid_year']}, test on {sp['test_year']}. A random split would let
the model learn from cases filed after the ones it is tested on, and it would hide the shift between filing years.
Unseen courts: {pct(sp['unseen_court_share'])} of courts are held out entirely with `GroupShuffleSplit`; their {sp['test_year']}
cases are `test_unseen` and their earlier cases are not used. Split IDs are saved, so every run uses identical rows.

{md_table(split_tbl)}

## Models

| Model | What it is |
|---|---|
| B0 | Majority class: the training base rate for every case |
| B1 | The court's disposal rate in the year before filing (district, then state rate if missing) |
| B2 | The court's rate for the same case type, shrunk towards B1 |
| M1 | Logistic regression: one-hot categoricals (levels with under {s.cfg['features']['min_category_count']} training cases pooled), scaled numerics, balanced class weights |
| M2 | LightGBM with native categoricals, early stopping on validation AUC; best of {grid_n} settings: `num_leaves` {m2_params['num_leaves']}, `learning_rate` {m2_params['learning_rate']}, `min_child_samples` {m2_params['min_child_samples']}, {m2_params['best_iteration']} trees |
| M3 | Cox proportional hazards (lifelines) on {n(json.loads(i.run('M3 Cox proportional hazards')['params'])['rows'])} training cases, open cases censored at T_end; scored as P(decided by day 730) |

Selection used validation AUC only. Grid candidates were logged without test metrics. {m1_note}

## Results on the {sp['test_year']} test filings

{md_table(results_table(i))}

ROC-AUC and PR-AUC come from each model's score; Brier score, log loss and expected calibration error (ECE) from its
probability. B1 and B2 are rates, not probabilities, so they are calibrated with isotonic regression on the
{sp['valid_year']} validation year. PR-AUC treats "decided within 24 months" as the positive class; PR-AUC (delay) treats
the overrun as positive, which is the case a registry would act on. M3's C-index on the test filings is {a3(m3_c)}.

**Why several metrics.** ROC-AUC says whether the model ranks cases correctly, regardless of base rate. PR-AUC shows
how precise the flags are when one class is rarer. Brier score and log loss judge the probabilities themselves, which
matter if anyone reads "62%" as a number. M1's balanced class weights shift its probabilities away from the observed
rates, which its calibration error before recalibration ({a3(t['m1']['ece'])}) shows.

**Calibration.** {"Isotonic recalibration on the validation year moved M2's Brier score from " + f"{t['m2']['brier']:.4f}" + " to " + f"{t['m2_cal']['brier']:.4f}" + " and its ECE from " + f"{t['m2']['ece']:.4f}" + " to " + f"{t['m2_cal']['ece']:.4f}" + "." if cal_better else "M2 was already close to calibrated: isotonic recalibration on the validation year did not improve its Brier score (" + f"{t['m2']['brier']:.4f}" + " against " + f"{t['m2_cal']['brier']:.4f}" + "), so the gain is in ECE (" + f"{t['m2']['ece']:.4f}" + " to " + f"{t['m2_cal']['ece']:.4f}" + ")."}
The calibrated model is the one used for thresholds and the dashboard.

![Calibration](figures/{figs['calibration']})

**Threshold.** A case is flagged as at risk of delay when its calibrated chance of a decision within 24 months is
below **0.5**: a delay is then more likely than not, which is the cut-off with the fewest expected mistakes when a
missed delay and a false alarm cost the same. On the test filings it flags {pct(th['flagged_share'])} of cases, with
**precision {pct(th['precision_delay'])}** (flagged cases that did overrun) and **recall {pct(th['recall_delay'])}** (overruns
that were flagged). If a registry could review only a fixed share of new filings, the cut-off would follow its
capacity instead. These cut-offs were set on 2015 and applied to 2016:

{md_table(cap_tbl)}

**Seen and unseen courts.**

![Seen versus unseen courts](figures/{figs['unseen']})

**Court versus case.**

{md_table(ablation)}

{id_note}

**Other checks.** The 12-month label gives a test AUC of {a3(exp['label_12m']['test_auc'])} (run `{exp['label_12m']['run_id']}`).
Training only on {sp['train_years'][1] - 2}-{sp['train_years'][1]}, which avoids the most unevenly digitised years, gives {a3(exp['recent_window']['test_auc'])}
(run `{exp['recent_window']['run_id']}`). B1b, the court's 24-month rate for the cohort filed three years earlier, gives
{a3(b1b_auc)}{", weaker than B1, so measuring against it would only widen the gap" if b1b_auc < t['b1']['roc_auc'] else ", stronger than B1, so the gap over the best court baseline is " + f"{t['m2']['roc_auc'] - b1b_auc:+.3f}"}.

## Slices

Five worst slices by M2's ROC-AUC (at least {s.cfg['evaluate']['slice_min_rows']:,} test cases and {s.cfg['evaluate']['slice_min_class']} of each class):

{md_table(worst_tbl)}

Court level:

{md_table(levels_tbl)}

Case type:

{md_table(types_tbl)}

Filing year (2015 is the validation year, used for early stopping, so it flatters M2):

{md_table(years_tbl)}

![ROC-AUC by state](figures/{figs['states']})

## What the model relies on

{md_table(imp_tbl)}

Permutation importance shuffles one feature in {n(i.imp['rows'].iloc[0])} test cases and measures the AUC drop; SHAP
values come from LightGBM's own `pred_contrib`. Correlated features share credit, so a feature with a small drop can
still carry signal another feature duplicates.

![Permutation importance](figures/{figs['importance']})

## Error analysis

The 50 most confident false positives (predicted quick, not decided within 24 months) and false negatives (predicted
slow, decided within 24 months) on the test filings, grouped by rule from what happened to each case after filing
(`reports/error_cases.csv` has all 100, and [docs/error_analysis.md](../docs/error_analysis.md) reads them):

{md_table(cause_tbl)}

## Findings

1. {who} Combining both, M2 gains {gc['gap']:+.3f} AUC over the court's own history (B1), an interval of {gc['ci_low']:+.3f} to {gc['ci_high']:+.3f} resampling courts{"" if excludes_zero else ", which includes zero"}.
2. The court's rate for the case type (B2) alone reaches {a3(t['b2']['roc_auc'])}, closing {b2_share:.0%} of the distance from B1 to
   M2. The top features by permutation importance are {top_feats}.
3. On courts it never saw, M2 scores {a3(tu['m2']['roc_auc'])} against {a3(t['m2']['roc_auc'])} on seen courts{" (" + f"{unseen_drop:.3f}" + " lower): history features describe a new court, but its identity cannot" if unseen_drop > 0.005 else ", so it does not depend on having seen a court before"}.
4. The weakest slices are {worst_text}.
5. Among the 50 most confident errors each way, false positives are led by {fp_text}; false negatives by {fn_text}
   ([docs/error_analysis.md](../docs/error_analysis.md) reads them case by case).

## Limitations

- **Coverage.** Case data ends in 2018 and collection thinned after early 2019, which sets T_end. Filings before 2010
  are absent, so pending loads and disposal rates count only the 2010+ caseload, and early filing years over-represent
  long cases.
- **Missing dispositions.** {pct(i.checks.set_index('id').loc['LB07', 'rate'], 2)} of modelling cases record an outcome but no decision date
  and are labelled pending; some districts' closures go unrecorded altogether (those flagged by the bail check are
  excluded). Closures by transfer count as decisions: {pct(i.checks.set_index('id').loc['LB08', 'rate'], 1)} of cases.
- **Act-name noise.** About half of early filings have no act record, and act labels are standardised by rules
  (`pipeline/mappings.py`) that leave some labels unmapped or vague.
- **Recorded at collection.** Act, section and party fields are as recorded when the data was collected; a charge
  sheet can add sections after filing.
- **Label maturity.** The 2014 training labels were only fully known at the end of 2016. A model deployed on 1 January
  2016 would have had to train on filings up to 2013.
- **Association, not cause.** Nothing here says why a court is slow; judge vacancies and caseload per judge are not in the data.

## Next steps

Drop or regularise the court and district IDs in favour of history features, choosing on a later validation year;
let the logistic regression run to convergence; add judge strength by district; retrain on post-2018 data when it is
available; compare the Cox model's full time-to-decision curve with the 24-month classifier; monitor calibration by
filing year.

## Reproduce

```
make all                 # full data: download, load, label, sample, features, train, evaluate, report
make all PROFILE=fixture # the synthetic fixture, in about a minute (what CI runs)
make mlflow              # load these runs into a local MLflow store
```

The runs this report quotes, all run from commit `{i.commit}`. [experiments.csv](experiments.csv) keeps every run.

{md_table(experiment_table(i.cited))}
{earlier_runs(i.earlier)}"""


def write_model_card(i: Inputs) -> str:
    s, res = i.s, i.res
    t, tu = res["test"], res["test_unseen"]
    gc = res["gaps"]["m2_vs_b1_court"]
    th = res["threshold"]["test"]
    worst = pd.DataFrame(res["worst_slices"])
    worst_lines = "\n".join(f"| {r.dimension}: {r.slice} | {n(r.n)} | {a3(r.auc_m2)} | {a3(r.auc_b1)} |" for r in worst.itertuples())
    exp = i.train["experiments"]
    case_wins = exp["case_only"]["test_auc"] > exp["court_only"]["test_auc"]
    return f"""# Model card: delay-risk model (M2)

*Generated by `make report` from run `{i.run('M2 LightGBM')['run_id']}` and evaluation `{i.eval_row['run_id']}` (commit `{i.commit}`); numbers update with each build.*

## What it is

A LightGBM classifier that estimates, at filing, the chance that a case in an Indian district or subordinate court is
decided within 24 months. Inputs are known on the day of filing: case type, act and section, parties as recorded, the
court and its recent history. Probabilities are recalibrated with isotonic regression on the 2015 validation year.

## Intended use

- Research and description: which courts and case types carry delay risk, and how much a court's own history explains.
- Planning questions at an aggregate level, for example where new filings are likely to add to backlog.
- Teaching: a worked example of censoring, temporal validation and leakage control on public court data.

## Not for

- **Any decision about an individual case, litigant, lawyer or judge**: listing, bail, adjournments, priority or
  resources. The model describes 2010-2018 patterns in incomplete records, and it would turn those patterns, including
  recording gaps, into decisions about people.
- Ranking or judging courts or judges. A low score can reflect missing closure records rather than a slow court.
- Use on courts or years outside 2010-2018 without retraining and recalibration.

## Data

DDL eCourts records filed 2010-2016 with a fully observed 24-month window (T_end {s.cfg['label']['t_end']}), a
{n(i.sample['sampled'])}-case sample stratified by state and filing year. Exclusions and label rules:
[docs/label_definition.md](label_definition.md). Features: [docs/features.md](features.md).
Licence: CC BY-NC-SA 4.0, non-commercial.

## Performance (2016 test filings)

| Measure | M2 | B1: court's prior-year rate |
|---|---|---|
| ROC-AUC, seen courts | {a3(t['m2']['roc_auc'])} | {a3(t['b1']['roc_auc'])} |
| ROC-AUC, courts never seen in training | {a3(tu['m2']['roc_auc'])} | {a3(tu['b1']['roc_auc'])} |
| PR-AUC | {a3(t['m2']['pr_auc'])} | {a3(t['b1']['pr_auc'])} |
| Brier score (calibrated) | {a3(t['m2_cal']['brier'])} | {a3(t['b1']['brier'])} |
| Expected calibration error | {a3(t['m2_cal']['ece'])} | {a3(t['b1']['ece'])} |

Gain over B1: {gc['gap']:+.3f} ROC-AUC, 95% interval {gc['ci_low']:+.3f} to {gc['ci_high']:+.3f} (1,000 resamples of courts).
At a cut-off of 0.5 it flags {pct(th['flagged_share'])} of cases as likely to overrun, with precision {pct(th['precision_delay'])} and
recall {pct(th['recall_delay'])} for overruns.

## Slices

Weakest slices by ROC-AUC (full table in `reports/slices.csv`):

| Slice | Test cases | M2 | B1 |
|---|---|---|---|
{worst_lines}

## Risks and limitations

- **Records, not courts.** Unrecorded closures make a court look slow; outcomes without dates are labelled pending.
  Its most confident mistakes come from courts whose recorded disposal rate the year before was near zero, often a gap
  in decision records rather than a stalled court ([error_analysis.md](error_analysis.md)).
- **Shift.** Early filing years over-represent long cases; the test year is the most recent fully observed one, and
  performance on later years is unknown.
- **Feedback.** Used to prioritise cases, the model would change the outcomes it was trained on.
- **Fairness.** Party gender is predicted from names and is often unclassifiable. The model was not audited for
  disparate error rates by party, and should not be used where that matters.
- **Association, not cause.** {"What a case is (its type, act and section) carries more of the signal than where it is filed" if case_wins else "Where a case is filed carries more of the signal than what it is"}
  (case features alone {a3(exp['case_only']['test_auc'])}, court features alone {a3(exp['court_only']['test_auc'])}). None of it says why a case or a court is slow.

## Ethical considerations

The data is public and pseudonymised: case numbers are dropped at load and only DDL's case ID is kept for joins.
Nothing in this repository identifies a litigant.
"""


def run(s: Settings) -> None:
    i = Inputs(s)
    figs = figures(i)
    report = write_report(i, figs)
    (s.reports / "ml_poc_report.md").write_text(report, encoding="utf8")
    card = write_model_card(i)
    if s.profile == "full":
        (ROOT / "docs" / "model_card.md").write_text(card, encoding="utf8")
        # Refresh the README so its ML section and experiment table match these runs.
        subprocess.run([sys.executable, "-I", "-X", "utf8", str(ROOT / "pipeline" / "write_readme.py")], cwd=ROOT, check=True)
    else:
        (s.reports / "model_card.md").write_text(card, encoding="utf8")
    print(f"report: {s.reports / 'ml_poc_report.md'} ({len(report):,} characters, {len(figs)} figures)", flush=True)


if __name__ == "__main__":
    run(load())
