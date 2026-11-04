"""Write the README and the private prep notes from findings.json, so their figures always match the data."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import LIVE_DASHBOARD, MART, OUTPUTS, REPOSITORY, ROOT, SCOPE  # noqa: E402

PRIVATE = ROOT / "private"  # kept out of git: prep material for the author, not part of the published project


def readme(f: dict, t: dict) -> str:
    order = ["q2", "q1", "q5", "q3", "q4", "q7", "q6", "q8", "q9", "q10"]
    charts = {"q1": "q1_stages", "q2": "q2_survival", "q3": "q3_laws", "q4": "q4_judges", "q5": "q5_map", "q6": "q6_women", "q7": "q7_backlog",
              "q8": "q8_outcomes", "q9": "q9_first_hearing", "q10": "q10_model"}
    rows = "\n".join(
        f"| {t[k]['question']} | {t[k]['finding']} | [chart](outputs/charts/{charts[k]}.png) |"
        for k in order
    )
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

## What is here

| Deliverable | Where |
|---|---|
| DuckDB + Parquet pipeline: loaders, SQL rules, act-name mapping | [pipeline/](pipeline/), [sql/dq_rules.sql](sql/dq_rules.sql) |
| Excel data-quality scorecard, with live formulas | [outputs/data_quality_scorecard.xlsx](outputs/data_quality_scorecard.xlsx) |
| Streamlit dashboard: findings, district map, state profiles, data-quality explorer, what-if calculator | [Live]({LIVE_DASHBOARD}), [dashboard/](dashboard/) |
| Two-page brief with the top findings | [outputs/where_justice_gets_stuck_brief.pdf](outputs/where_justice_gets_stuck_brief.pdf) |

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

Tests: `pytest tests`. They cover the survival estimator against `lifelines`, the label rules on real labels, the downloader, the Excel formulas against an independent calculation, every dashboard page, and reconciliation of the full build when it is present. GitHub Actions runs them on every push.

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
dashboard/          the Streamlit app, reading data/mart only
docs/               methods, data dictionary, schema, analyst issue log, design source
data/mart/          aggregate tables, safe to share
data/geo/           simplified district boundaries
```

The design decisions worth a look are in [docs/methods.md](docs/methods.md), including the checks that caught real errors while this was built.

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


def run() -> None:
    data = json.loads((MART / "findings.json").read_text())
    f, t = data["figures"], data["text"]
    text = readme(f, t)
    if SCOPE == "full":
        (ROOT / "README.md").write_text(text, encoding="utf8")
        PRIVATE.mkdir(exist_ok=True)
        (PRIVATE / "resume_line.txt").write_text(resume_line(f), encoding="utf8")
        (PRIVATE / "interview_notes.md").write_text(interview_notes(f, t), encoding="utf8")
    else:
        # A pilot run must not replace the real README with two states' numbers.
        OUTPUTS.mkdir(parents=True, exist_ok=True)
        (OUTPUTS / "README_pilot.md").write_text(text, encoding="utf8")
    print("wrote README and private notes\n" + resume_line(f), flush=True)


if __name__ == "__main__":
    run()
