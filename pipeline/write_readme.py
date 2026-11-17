"""Write the README and the private prep notes from findings.json, so their figures always match the data.

The delay-risk model's section, experiment table and resume line come from reports/ (ml_results.json and
experiments.csv, written by `make evaluate`), and are left out until those exist.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import LIVE_DASHBOARD, MART, OUTPUTS, REPOSITORY, ROOT, SCOPE  # noqa: E402

PRIVATE = ROOT / "private"  # kept out of git: prep material for the author, not part of the published project
REPORTS = ROOT / "reports"


def ml_inputs() -> dict | None:
    """Logged results of the delay-risk model, or None before `make evaluate` has run on the full data."""
    needed = ["ml_results.json", "experiments.csv", "train_summary.json", "sample_summary.json", "split_summary.csv"]
    if not all((REPORTS / n).exists() for n in needed):
        return None
    res = json.loads((REPORTS / "ml_results.json").read_text())
    if res.get("profile") != "full":
        return None
    exp = pd.read_csv(REPORTS / "experiments.csv")
    session = exp[(exp["stage"] == "final") & (exp["model"] == "M2 LightGBM")].iloc[-1]["session"]
    runs = exp[exp["session"] == session]
    return {"res": res, "exp": exp, "runs": runs, "train": json.loads((REPORTS / "train_summary.json").read_text()),
            "sample": json.loads((REPORTS / "sample_summary.json").read_text()),
            "splits": pd.read_csv(REPORTS / "split_summary.csv").set_index("split"),
            "eval": exp[exp["stage"] == "evaluation"].iloc[-1]}


def run_id(m: dict, model: str, stage: str = "final") -> str:
    hit = m["runs"][(m["runs"]["model"] == model) & (m["runs"]["stage"] == stage)]
    return hit.iloc[-1]["run_id"]


def ml_section(m: dict) -> str:
    res, train = m["res"], m["train"]
    t, tu = res["test"], res["test_unseen"]
    gc, g = res["gaps"]["m2_vs_b1_court"], res["gaps"]["m2_vs_b1_case"]
    exp = train["experiments"]
    court_only, case_only = exp["court_only"]["test_auc"], exp["case_only"]["test_auc"]
    winner = ("mostly the court" if court_only >= case_only else "mostly the case")
    th = res["threshold"]["test"]
    rows = []
    for key in ["b0", "b1", "b2", "m1", "m2_cal", "m3"]:
        r = t[key]
        u = tu.get(key, {})
        rows.append(f"| {r['model']} | {r['roc_auc']:.3f} | {r['pr_auc']:.3f} | {r['brier']:.3f} | {u.get('roc_auc', float('nan')):.3f} |")
    table = "\n".join(rows)
    split = m["splits"]
    return f"""## Delay-risk model

Can we tell, on the day a case is filed, whether it will be decided within 24 months, and how much does a model add over
each court's own history? A proof of concept on a {m['sample']['sampled'] / 1e6:.1f}M-case sample, trained on filings 2010-2014,
validated on 2015 and tested on 2016. **[Read the report](reports/ml_poc_report.md)** | [Model card](docs/model_card.md) |
[Label definition](docs/label_definition.md) | [Feature schema](docs/features.md)

**The answer: {winner}.** With court features alone (identity, level, history) LightGBM reaches a test ROC-AUC of
{court_only:.3f}; with case features alone (type, act and section, parties), {case_only:.3f}. The full model (M2) reaches
**{t['m2']['roc_auc']:.3f}**, against **{t['b1']['roc_auc']:.3f}** for the court's prior-year disposal rate (B1): a gain of
**{gc['gap']:+.3f}** (95% interval {gc['ci_low']:+.3f} to {gc['ci_high']:+.3f} resampling courts; {g['ci_low']:+.3f} to {g['ci_high']:+.3f} resampling
cases, {g['resamples']:,} resamples). On courts held out of training entirely it scores {tu['m2']['roc_auc']:.3f}.

| Model (test year {split.loc['test', 'first_year']}) | ROC-AUC | PR-AUC | Brier | ROC-AUC, unseen courts |
|---|---|---|---|---|
{table}

M2 is shown after isotonic recalibration on 2015. Flagging cases whose calibrated chance of a decision within 24 months
is below 0.5 marks {th['flagged_share']:.0%} of 2016 filings, with precision {th['precision_delay']:.0%} and recall {th['recall_delay']:.0%} for overruns.
Every number above is from logged runs `{run_id(m, 'M2 LightGBM')}` (M2) and `{m['eval']['run_id']}` (evaluation); the full log is below.

```mermaid
flowchart LR
    P["Typed Parquet, 80.9M cases"] -->|"sql/labels.sql + DQ rules"| L["Label: decided within 730 days"]
    L -->|"censoring rule, exclusions"| Q["{m['sample']['population'] / 1e6:.1f}M labelable cases"]
    Q -->|"sample.py, state x year, seeded hash"| S["{m['sample']['sampled'] / 1e6:.1f}M-case sample"]
    P -->|"sql/features.sql"| H["Court history, point in time"]
    S --> F["Features known at filing"]
    H --> F
    F -->|"split.py"| T["Train 2010-14, valid 2015, test 2016, 10 percent of courts held out"]
    T -->|"train.py"| M["B0-B2 baselines, logistic, LightGBM, Cox"]
    M --> X[("experiments.csv and MLflow")]
    M -->|"evaluate.py"| E["Metrics, bootstrap intervals, slices, errors"]
    E -->|"report.py"| R["Report, model card, dashboard page"]
```

**Limitations.** Records end in 2018 and thin out after early 2019, which fixes the observation end at 31 Dec 2018 and
the test year at 2016. Early filing years over-represent long cases because courts digitised mid-period. Some districts'
closures go unrecorded (those districts are excluded), and outcomes without a decision date count as pending. Act records are thin
for early years and act labels are standardised by rules. The most confident mistakes come from courts whose recorded
disposal rate was near zero the year before, often a gap in decision records ([error analysis](docs/error_analysis.md)).
The model learns associations and says nothing about why a case or court is slow. It is for research only, never for
decisions about individual cases.

Train / valid / test: {split.loc['train', 'cases']:,} / {split.loc['valid', 'cases']:,} / {split.loc['test', 'cases']:,} cases, plus {split.loc['test_unseen', 'cases']:,} from {split.loc['test_unseen', 'courts']:,} held-out courts.
"""


def experiment_log(m: dict) -> str:
    def fmt(v):
        return "" if pd.isna(v) or v == "" else f"{float(v):.3f}"
    lines = ["| Run | Stage | Model | Label | Valid AUC | Test AUC | Unseen-court AUC | Test Brier | Seconds |", "|---|---|---|---|---|---|---|---|---|"]
    for r in m["exp"].itertuples():
        lines.append(f"| `{r.run_id}` | {r.stage} | {r.model} | {str(r.label).replace('label_', '')} | {fmt(r.valid_auc)} | {fmt(r.test_auc)} | "
                     f"{fmt(r.test_unseen_auc)} | {fmt(r.test_brier)} | {float(r.runtime_s):,.0f} |")
    return f"""## Experiment log

Every run of the delay-risk model, from [reports/experiments.csv](reports/experiments.csv), which also records each run's
parameters, feature version, split version, row counts, config hash and git commit. Grid candidates carry no test
metrics: the test set was scored only by the models chosen on validation. Stages: `final` models, `grid` candidates,
`experiment` (leakage tests, ablations, the 12-month label), `evaluation` (bootstrap intervals and threshold).

{chr(10).join(lines)}
"""


def readme(f: dict, t: dict, m: dict | None = None) -> str:
    order = ["q2", "q1", "q5", "q3", "q4", "q7", "q6", "q8", "q9", "q10"]
    charts = {"q1": "q1_stages", "q2": "q2_survival", "q3": "q3_laws", "q4": "q4_judges", "q5": "q5_map", "q6": "q6_women", "q7": "q7_backlog",
              "q8": "q8_outcomes", "q9": "q9_first_hearing", "q10": "q10_model"}
    rows = "\n".join(
        f"| {t[k]['question']} | {t[k]['finding']} | [chart](outputs/charts/{charts[k]}.png) |"
        for k in order
    )
    ml = ml_section(m) if m else ""
    log = experiment_log(m) if m else ""
    ml_row = ("| Delay-risk model: labels, point-in-time features, baselines, LightGBM, evaluation, model card | "
              "[reports/ml_poc_report.md](reports/ml_poc_report.md), [src/ml/](src/ml/), [docs/model_card.md](docs/model_card.md) |"
              + chr(10)) if m else ""
    return f"""# Where Justice Gets Stuck

Where and why Indian lower courts are delayed, from **{f['total_rows']:,} cases** filed 2010-2018, with 2026 pendency for context.

**[Open the live dashboard]({LIVE_DASHBOARD})** | [Read the two-page brief](outputs/where_justice_gets_stuck_brief.pdf)

Indian district and subordinate courts held {f['njdg_total'] / 1e7:.2f} crore pending cases in July 2026. This project finds where those cases stall, using case-level records and a data-quality layer that documents every problem found along the way.

> **Case data ends in 2018.** These findings describe that period, not courts today. 2026 figures come from NJDG and are context only.

![District map of median time to close](outputs/charts/q5_map.png)

## The headline

The usual measure of delay is misleading. Closed cases alone give a median of **{f['q2_naive_median']:,.0f} days**, but counting cases still open gives **{f['q2_km_median']:,.0f} days**, {f['q2_ratio']:.1f} times longer, because the slowest cases are the ones that have not finished. {f['q2_open_5y']:.0%} of cases are still open after five years.

## Findings

| Question | Finding | |
|---|---|---|
{rows}

Every figure has its limits spelled out in [the brief](outputs/where_justice_gets_stuck_brief.pdf), the dashboard and [docs/methods.md](docs/methods.md).

{ml}
## What is here

| Deliverable | Where |
|---|---|
| DuckDB + Parquet pipeline: loaders, SQL rules, act-name mapping | [pipeline/](pipeline/), [sql/dq_rules.sql](sql/dq_rules.sql) |
| Excel data-quality scorecard, with live formulas | [outputs/data_quality_scorecard.xlsx](outputs/data_quality_scorecard.xlsx) |
| Streamlit dashboard: findings, district map, state profiles, data-quality explorer, what-if calculator | [Live]({LIVE_DASHBOARD}), [dashboard/](dashboard/) |
| Two-page brief with the top findings | [outputs/where_justice_gets_stuck_brief.pdf](outputs/where_justice_gets_stuck_brief.pdf) |
{ml_row}
### Data-management work

| Work | What was built | Where |
|---|---|---|
| Validation rules | {f.get('dq_rules', 0)} rules across completeness, validity, consistency, uniqueness and linkage; {f.get('dq_failed', 0)} found failures | [sql/dq_rules.sql](sql/dq_rules.sql) |
| Standardisation | {f.get('act_variants_standardized', 0):,} of {f.get('act_variants_total', 0):,} raw act labels mapped to {f.get('canonical_acts', 0)} canonical acts, covering {f.get('act_named_share', 0):.0%} of cases with an act record; stages, case types and outcomes too | [pipeline/mappings.py](pipeline/mappings.py), `data/mart/map_*.csv` |
| Coverage check | Cases by state and year, compared with NJDG: share correlation {f['cov_corr']:.2f} | Coverage sheet in the scorecard, Data quality page |
| Documentation | Data dictionary and schema diagram of the files as they really are | [docs/data_dictionary.md](docs/data_dictionary.md) |
| Issue log | Every rule failure and anomaly, with severity, sample records and status | Issue log sheet, Data quality page, [docs/analyst_issues.csv](docs/analyst_issues.csv) |
| Scorecard | Quality scores by state and dimension, with adjustable weights | [outputs/data_quality_scorecard.xlsx](outputs/data_quality_scorecard.xlsx) |

## Run it

The [live dashboard]({LIVE_DASHBOARD}) needs no setup. To run it yourself, it needs only the small aggregate tables included here:

```
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
streamlit run dashboard/app.py --server.address 127.0.0.1
```

To rebuild everything from the source data (a 5.1 GB stream, of which about 2 GB is kept, plus about 2 GB of Parquet):

```
python -I pipeline/run_all.py                 # all 81M rows
python -I pipeline/run_all.py --pilot 01,08   # a trial on Maharashtra and Bihar, in separate folders
```

The delay-risk model runs step by step with `make` (GNU make; on Windows, for example `mingw32-make`). Settings such as paths, seed, sample size and horizon are in [config.yaml](config.yaml):

```
make all                    # data, dq, features, train, evaluate, report on the full data
make all PROFILE=fixture    # the same steps on a small synthetic fixture, in about a minute
make test                   # pytest
make lint                   # ruff
make mlflow                 # load every logged run into MLflow, then: mlflow ui --backend-store-uri sqlite:///mlflow.db
```

Tests: `pytest tests`. They cover the survival estimator against `lifelines`, the label rules on real labels, the downloader, the Excel formulas against an independent calculation, every dashboard page, and reconciliation of the full build when it is present. For the delay-risk model they check the label's edge cases, that no feature is dated after filing (by rebuilding features with every later event deleted), that splits are disjoint and repeatable, and that the fixture build reproduces its recorded results. GitHub Actions lints, runs the fixture pipeline and runs the tests on every push.

### Host the dashboard

The [live copy]({LIVE_DASHBOARD}) runs on [Streamlit Community Cloud](https://streamlit.io/cloud) and updates when `main` changes. To host your own, point a new app at this repository with `dashboard/app.py` as the main file. It installs the short [dashboard/requirements.txt](dashboard/requirements.txt), and no secrets or row-level data are needed. The case data licence is non-commercial, so keep any hosted copy non-commercial too.

## How it is built

```mermaid
flowchart LR
    A[DDL archive, 5.1 GB stream] -->|download_ddl| B[CSV archives]
    B -->|load| C[Typed Parquet]
    C -->|standardize + mappings| D[fact_case]
    E[Census 2011 + crosswalk] --> D
    D -->|analysis + km| F[Aggregate marts]
    D -->|model| F
    C -->|quality + dq_rules.sql| F
    G[NJDG 2026] --> F
    F -->|findings| H[Every number and sentence]
    H --> I[Dashboard]
    H --> J[Two-page brief]
    H --> K[Excel scorecard]
    H --> L[README]
```

```
pipeline/
  download_ddl.py   stream the Dropbox archive, keeping only the CSV copies, with CRC checks
  load.py           convert to typed Parquet; drops the linkable case number
  mappings.py       rules that standardise acts, stages, case types and outcomes
  standardize.py    mapping tables, geography, and the analysis table fact_case
  quality.py        run the rule catalogue; write results, samples and the issue log
  analysis.py       the questions, as small aggregate tables
  km.py             Kaplan-Meier from counts, exact at any scale
  model.py          Cox model of what drives time to closure
  findings.py       every number and sentence used downstream
  charts.py         one definition of each chart
  scorecard.py      the Excel workbook
  brief.py          chart images and the two-page PDF
  run_all.py        everything, in order
sql/dq_rules.sql    the rule catalogue
sql/labels.sql      the delay-risk label, its exclusions and censoring rule
sql/dq_labels.sql   label checks
sql/features.sql    point-in-time features
src/ml/             the delay-risk model: dq, sample, features, split, train, evaluate, report
reports/            the model's report, figures and experiment log
config.yaml         paths, seed, sample size, horizon
Makefile            make all, or one step at a time
dashboard/          the Streamlit app, reading data/mart only
docs/               methods, data dictionary, schema, label, features, model card, design source
data/mart/          aggregate tables, safe to share
data/geo/           simplified district boundaries
data/MANIFEST.md    source files with sizes and SHA-256 hashes
```

The design decisions worth a look are in [docs/methods.md](docs/methods.md), including the checks that caught real errors while this was built.

{log}
## Sources and licences

The code is under the [MIT licence](LICENSE). The data is not: derived tables and charts carry **CC BY-NC-SA 4.0, for non-commercial use only**. See [DATA_LICENSE.md](DATA_LICENSE.md).

- **Case data:** [Development Data Lab](https://www.devdatalab.org/judicial-data), eCourts cases 2010-2018. Cite Ash, Asher, Bhowmick, Bhupatiraju, Chen, Devi, Goessmann, Novosad and Siddiqi (2025), *In-Group Bias in the Indian Judiciary*, The Review of Economics and Statistics.
- **Pendency and judge numbers:** NJDG and the Department of Justice, via [Lok Sabha Unstarred Question 3371](https://sansad.in/getFile/lsapps/loksabhaquestions/annex/188/AU3371_Lq6K9K.pdf), 7 Aug 2026.
- **Section 138 benchmark:** [In Re: Expeditious Trial of Cases under Section 138 NI Act](https://api.sci.gov.in/supremecourt/2020/9631/9631_2020_31_501_27616_Judgement_16-Apr-2021.pdf), Supreme Court of India, 16 Apr 2021.
- **Population:** Census 2011, via [this mirror](https://github.com/nishusharma1608/India-Census-2011-Analysis).
- **Boundaries:** [DataMeet India community](https://github.com/datameet/maps), CC BY 4.0. For display only, and not an official map of India.
- **Dashboard design:** generated with Google Stitch, see [docs/design/](docs/design/stitch_design_tokens.md).
"""


def resume_line(f: dict) -> str:
    return (
        f"Analysed {f['total_rows'] / 1e6:.1f}M Indian court cases (2010-2018) with DuckDB/SQL. Wrote {f.get('dq_rules', 0)} data-quality rules, "
        f"standardized {f.get('act_variants_standardized', 0):,} act-name variants, and identified the case stages and districts driving delay. "
        "Used survival analysis and a district-level dashboard.\n"
        f"Live dashboard: {LIVE_DASHBOARD}\n"
        f"Code: {REPOSITORY}\n"
    )


def interview_notes(f: dict, t: dict) -> str:
    trial = f["q4_tenure_by_category"]["Criminal trial (magistrate)"]
    sessions = f["q4_tenure_by_category"]["Sessions trial"]
    return f"""# Interview notes

Live dashboard: {LIVE_DASHBOARD}
Code: {REPOSITORY}

Private prep, kept out of git. Every figure comes from the final build. Read `docs/methods.md` alongside this, and be ready to walk through `pipeline/analysis.py`, `pipeline/km.py` and `sql/dq_rules.sql` yourself, because a good interviewer will ask you to open them.

## Thirty-second version

I analysed {f['total_rows'] / 1e6:.1f} million Indian lower-court cases to find where and why justice is delayed. The usual figure, a median of {f['q2_naive_median']:,.0f} days from closed cases, understates delay {f['q2_ratio']:.1f} times, because the slowest cases are the ones still open. Using survival analysis the median is {f['q2_km_median']:,.0f} days. I also built a data-quality layer of {f.get('dq_rules', 0)} SQL rules, a scorecard by state, and a dashboard with a district map.

## Three stories to tell

**1. A number everyone would get wrong (survivorship).** A plain average leaves out every case still open. Kaplan-Meier counts an open case towards delay until the cut-off, then removes it from the risk set. Bihar shows it most clearly: {f['q2_slowest_state_naive']:,.0f} days from closed cases against {f['q2_slowest_state_km']:,.0f} once open cases count.

**2. A finding that fell apart (reverse causation).** Cases that changed judges took {f['q4_changed_median']:,.0f} days against {f['q4_same_median']:,.0f}, which looks damning. But a slow case has more time to see a transfer. So I used something the case cannot influence: how long the judge had left at filing. The gap shrinks to {abs(trial['gap']) * 100:.1f} points for magistrate trials and {abs(sessions['gap']) * 100:.1f} for sessions trials.

**3. A false result I stopped (data quality).** Some Bihar districts looked extremely slow. Then I checked bail, which normally closes in days: in those districts most bail matters never closed either. That points to missing closure records and not slow courts. I flagged {f['q5_flagged']} districts with that test and left them out of the rankings, and Bihar's median fell from {f['q2_slowest_state_km']:,.0f} to {f['q5_state_excl_flagged'].get('Bihar', 0):,.0f} days.

## Questions you should expect

**What is censoring?** A case still open when observation stops: we know it took at least this long, not how long in total. Dropping such cases biases durations downwards.

**Why one cut-off date?** Recorded decisions fall about 90% in early 2019, because only some courts were collected again later. Without a shared date, those courts get extra months in which cases can close and look faster for no real reason.

**Why DuckDB rather than pandas or Spark?** {f['total_rows'] / 1e6:.0f} million rows fit on one laptop with a columnar engine. Parquet came to about 2 GB, and most queries take seconds. Spark would add cluster overhead for no benefit at this size, and pandas would not fit in memory.

**How can you run Kaplan-Meier on {f['total_rows'] / 1e6:.0f} million rows?** The estimator only needs counts of closures and open cases at each duration. SQL computes those, and the curve from them is exact, not an approximation. A test checks it against `lifelines`.

**How do you know your results are right?** Row counts reconcile at each step, the estimator is tested against a reference library, and the Excel formulas match an independent calculation. There are also two outside checks: DDL's open cases by state track NJDG's 2026 shares (correlation {f['cov_corr']:.2f}), and states slow in this data hold NJDG's oldest cases (rank correlation {f['cov_age_spearman']:.2f}).

**What does the Cox model add?** It holds case type, filing year and the people involved constant at once, so a state cannot look slow just because of its case mix. A comparable case closes at {f['q10_slow'][0]['ratio']:.2f} times the Maharashtra rate in {f['q10_slow'][0]['state']} and {f['q10_fast']['ratio']:.2f} in {f['q10_fast']['state']}. Know its limit: a hazard ratio averages over time, and proportional hazards is only an approximation here. Concordance is {f['q10_concordance']:.2f}.

**What was the hardest data problem?** Good answers are the uneven collection after 2019, the {f.get('act_variants_total', 0):,} raw act labels, or the missing closure records. The act labels also gave a good bug story: a loose pattern moved about 18 lakh cases into the NI Act, and a unit test on "Dowry Prohibition Act" caught it.

**What would you do with more time?** Add judge strength by district, to test caseload per judge directly. Get an official filing series to measure coverage by year rather than infer it. Repeat with data after 2018.

**What can this data not tell you?** Why a court is slow. There are no vacancy or caseload figures by district, cases before 2010 are absent, and everything here is an association.

## Facts worth having ready

- {f['total_rows']:,} cases; {f['open_at_cutoff']:,} open on 31 Dec 2018; {f['q2_open_5y']:.0%} still open after five years.
- {f['q1_pretrial_share']:.0%} of never-closed cases were last listed for admission, summons, notice or appearance.
- Section 138: {f['q3_ni_open']:,} NI Act cases open at the end of 2018. The Supreme Court's figure is {f['q3_sc_benchmark']:,} for end-2019, and it also counts older cases.
- Only {f['q8_shares']['Decided on merits']:.0%} of closures are decided on the merits.
- A judge stays a median {f['q4_tenure_median_days']:,.0f} days in a post, shorter than the median case.
- {f['judges_vacant_share']:.0%} of judicial posts were vacant in June 2026 ({f['judges_working']:,} working of {f['judges_sanctioned']:,}).

## Correct these if they come up

The original plan cited the eCourts India blog for two things it does not say. It gives delay's cost as 0.5-1.5% of GDP, not 1-2%, and it never mentions 30-40 lakh Section 138 cases. The 35.16 lakh figure comes from the Supreme Court.
"""


def resume_ml(m: dict) -> str:
    """Resume bullets for the delay-risk model. Every number is read from the logged results."""
    res, train = m["res"], m["train"]
    t, tu = res["test"], res["test_unseen"]
    gc = res["gaps"]["m2_vs_b1_court"]
    leak = train["experiments"]["leak_last_hearing"]
    m2_valid = float(m["runs"][(m["runs"]["model"] == "M2 LightGBM") & (m["runs"]["stage"] == "final")].iloc[-1]["valid_auc"])
    n_runs = len(m["exp"])
    return (
        f"Built a filing-time delay-risk model (LightGBM) on a {m['sample']['sampled'] / 1e6:.1f}M-case stratified sample of "
        f"{m['sample']['population'] / 1e6:.1f}M labelable cases: test ROC-AUC {t['m2']['roc_auc']:.3f} on 2016 filings against "
        f"{t['b1']['roc_auc']:.3f} for each court's prior-year disposal rate (+{gc['gap']:.3f}, 95% CI {gc['ci_low']:.3f}-{gc['ci_high']:.3f}, "
        f"court-level bootstrap); {tu['m2']['roc_auc']:.3f} on courts never seen in training; isotonic-calibrated "
        f"(Brier {t['m2_cal']['brier']:.3f}).\n"
        f"Engineered it as DuckDB SQL + Makefile + config: censoring-aware labels with 6 invariant checks, point-in-time court "
        f"history verified by truncation tests, a leakage test (one post-filing field lifted validation AUC from {m2_valid:.3f} "
        f"to {leak['valid_auc']:.3f}), {n_runs} runs logged to MLflow and CSV, CI on a synthetic fixture.\n"
        f"(Runs: M2 {run_id(m, 'M2 LightGBM')}, evaluation {m['eval']['run_id']}, leak {leak['run_id']}.)\n"
    )


def interview_ml(m: dict) -> str:
    """Answers to the questions an interviewer will ask about the model, with the numbers to quote."""
    res, train = m["res"], m["train"]
    t, tu = res["test"], res["test_unseen"]
    g, gc = res["gaps"]["m2_vs_b1_case"], res["gaps"]["m2_vs_b1_court"]
    exp = train["experiments"]
    leak, leak2 = exp["leak_last_hearing"], exp["leak_defendant_advocate"]
    m2_valid = float(m["runs"][(m["runs"]["model"] == "M2 LightGBM") & (m["runs"]["stage"] == "final")].iloc[-1]["valid_auc"])
    th = res["threshold"]["test"]
    sp = m["splits"]
    imp = res["importance"][:3]
    return f"""
## Delay-risk model

Report: reports/ml_poc_report.md. Model card: docs/model_card.md. Run IDs: M2 `{run_id(m, 'M2 LightGBM')}`, B1
`{run_id(m, 'B1 court prior-year disposal rate')}`, evaluation `{m['eval']['run_id']}`, leakage `{leak['run_id']}`.

**Thirty seconds.** I asked whether you can tell at filing if a case will be decided within 24 months, and how much a
model adds over the court's own history. LightGBM reaches a test ROC-AUC of {t['m2']['roc_auc']:.3f} on 2016 filings against
{t['b1']['roc_auc']:.3f} for the court's prior-year disposal rate, a gain of {gc['gap']:+.3f} (95% CI {gc['ci_low']:+.3f} to {gc['ci_high']:+.3f}, resampling
courts). Court features alone reach {exp['court_only']['test_auc']:.3f}; case features alone {exp['case_only']['test_auc']:.3f}.

**Why a temporal split?** Deployment means predicting cases filed after the training data. A random split mixes 2016
cases into training, lets the model learn court conditions from the test period, and hides the drift: the share
decided within 24 months rises from {sp.loc['train', 'positive_rate']:.0%} in the training years to {sp.loc['test', 'positive_rate']:.0%} in 2016, partly because early
digital records over-represent long cases.

**Censoring?** A case pending at the end of the data has an unknown outcome. The label is only defined when the whole
730-day window is observed (filed by 31 Dec 2016, T_end 31 Dec 2018), so no pending case is guessed. T_end is not the
latest date in the files: decisions fall 89% after early 2019 because most courts were collected only once. The Cox
model uses every case, with open ones censored at T_end.

**Leakage.** Days from filing to the last hearing: validation AUC jumps from {m2_valid:.3f} to {leak['valid_auc']:.3f}. Subtler:
whether a defendant's advocate is on record ({leak2['valid_auc']:.3f}), because the advocate is entered when the defendant
contests. A second, subtle one I found in my own code: court history filtered on "usable" cases used the future, because
whether a case is usable depends on its later decision date. The truncation test catches it.

**Why the court-history baseline?** The honest question is not "is the model better than a coin" but "does it beat
what a registry already knows". B1 is that: the court's disposal rate last year. M2 adds {gc['gap']:+.3f} AUC over it;
B2 (court x case type) alone reaches {t['b2']['roc_auc']:.3f}. Case features alone reach {exp['case_only']['test_auc']:.3f} and court features
alone {exp['court_only']['test_auc']:.3f}: {"what a case is matters more than where it is filed" if exp['case_only']['test_auc'] > exp['court_only']['test_auc'] else "where a case is filed matters more than what it is"}.
Top features: {", ".join(r['feature'] for r in imp)}.

**PR-AUC, Brier, threshold.** ROC-AUC ignores the base rate; PR-AUC shows precision for the class you act on; Brier
and log loss judge the probabilities themselves. M1 used balanced class weights, which help ranking and hurt Brier.
Threshold 0.5 on calibrated probability: flags {th['flagged_share']:.0%}, precision {th['precision_delay']:.0%}, recall {th['recall_delay']:.0%}. With
limited review capacity you pick the cut-off from capacity, set on validation.

**Unseen courts?** {tu['m2']['roc_auc']:.3f} against {t['m2']['roc_auc']:.3f}. A new court has history but no learned identity, so the model
falls back on its rates and its level.

**Bootstrap.** Case-level interval {g['ci_low']:+.3f} to {g['ci_high']:+.3f}; court-level {gc['ci_low']:+.3f} to {gc['ci_high']:+.3f}. Cases in one court
are correlated, so resampling cases overstates certainty; resampling courts is the honest one.

**One DQ rule end to end.** V01, decision dated before filing: 345,896 cases (0.43%). Caught by
`date_of_decision < date_of_filing`, excluded from labels because a negative duration means nothing, and counted
in the audit table.

**Scale to all 80.9M rows.** Labels and court history already run on all rows in DuckDB (seconds); only training
uses the sample. For more: partition Parquet by state and year, compute history incrementally per month, train
LightGBM on a larger sample or with Spark/SynapseML, score in batches.

**SQL: each court's prior-year disposal rate.**

```sql
WITH yearly AS (
  SELECT court, yr, sum(decided) AS decided, sum(filed) AS filed,
         sum(sum(filed) - sum(decided)) OVER (PARTITION BY court ORDER BY yr
             ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS pending_start
  FROM flows GROUP BY court, yr)
SELECT court, yr + 1 AS filing_year, decided / (coalesce(pending_start, 0) + filed) AS prior_year_rate
FROM yearly;
```

The trap: `LAG(avg(decided_within_24m))` over filing cohorts leaks, because last year's cohort's 24-month outcomes are
not known until a year after this case is filed. Use a cohort three years back, or a calendar-year throughput rate.

**Never for individual cases.** It learns recording gaps as well as delay, it would change the outcomes it was
trained on, and party gender is predicted from names. It is a research and planning tool.
"""


def run() -> None:
    data = json.loads((MART / "findings.json").read_text())
    f, t = data["figures"], data["text"]
    m = ml_inputs()
    text = readme(f, t, m)
    if SCOPE == "full":
        (ROOT / "README.md").write_text(text, encoding="utf8")
        PRIVATE.mkdir(exist_ok=True)
        (PRIVATE / "resume_line.txt").write_text(resume_line(f) + ("\n" + resume_ml(m) if m else ""), encoding="utf8")
        (PRIVATE / "interview_notes.md").write_text(interview_notes(f, t) + (interview_ml(m) if m else ""), encoding="utf8")
    else:
        # A pilot run must not replace the real README with two states' numbers.
        OUTPUTS.mkdir(parents=True, exist_ok=True)
        (OUTPUTS / "README_pilot.md").write_text(text, encoding="utf8")
    print("wrote README and private notes\n" + resume_line(f), flush=True)


if __name__ == "__main__":
    run()
