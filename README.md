# Where Justice Gets Stuck

Where and why Indian lower courts are delayed, from **80,935,944 cases** filed 2010-2018, with 2026 pendency for context.

**[Open the live dashboard](https://where-justice-gets-stuck.streamlit.app/)** | [Always-on copy](https://ritik650.github.io/where-justice-gets-stuck/) | [Read the two-page brief](outputs/where_justice_gets_stuck_brief.pdf)

Indian district and subordinate courts held 4.99 crore pending cases in July 2026. This project finds where those cases stall, using case-level records and a data-quality layer that documents every problem found along the way.

> **Case data ends in 2018.** These findings describe that period, not courts today. 2026 figures come from NJDG and are context only.

![District map of median time to close](outputs/charts/q5_map.png)

## The headline

The usual measure of delay is misleading. Closed cases alone give a median of **181 days**, but counting cases still open gives **450 days**, 2.5 times longer, because the slowest cases are the ones that have not finished. 19% of cases are still open after five years.

## Findings

| Question | Finding | |
|---|---|---|
| How long does justice take? | Half of all cases take more than 450 days to close once open cases are counted. Closed cases alone say 181 days, which understates it 2.5 times. 19% of cases are still open after five years. Civil suits take a median of 983 days, while bail takes 9. | [chart](outputs/charts/q2_survival.png) |
| Where do cases get stuck? | 38% of cases that never closed (80.2 lakh) were last listed for admission, summons, notice or appearance: the steps that get parties to court. Evidence is the largest single stage at 22%. Criminal cases sit in those early steps more often than civil ones (41% against 30%). | [chart](outputs/charts/q1_stages.png) |
| Does your district decide your speed of justice? | Yes: a slow district (90th percentile) takes 6.5 times as long as a fast one (10th percentile), 1,200 days against 184. States explain 67% of the variation after adjusting for case mix, so districts matter but states matter more. Only 55 of 558 districts disposed of as many cases as were filed in 2016-18. | [chart](outputs/charts/q5_map.png) |
| Which laws clog the system? | The Indian Penal Code holds the most open cases (75.8 lakh), followed by the Code of Civil Procedure (39.5 lakh). Among large groups, Specific Relief Act cases are slowest at a median 3.8 years. Section 138 (cheque bounce) is the largest single section by volume, with 19.6 lakh NI Act cases filed 2010-2018 still open at the end of 2018 (8% of all open cases). That fits the Supreme Court's 35.2 lakh for end-2019, which also counts older cases, but this data alone cannot confirm it. | [chart](outputs/charts/q3_laws.png) |
| Do judge transfers slow cases? | Much less than it first appears. Cases that changed judges took a median 516 days against 13, and matched trials still differ by 464 days, but slow cases simply have more time to see a transfer. A fairer test uses what a slow case cannot influence: how long the judge had left at filing. With a judge about to leave, the share closed within two years was 2.9 points lower in magistrate trials and 5.4 points lower in sessions trials. | [chart](outputs/charts/q4_judges.png) |
| When would the backlog clear? | On 2016-18 flows, it would not: filings outran recorded disposals in 28 of 31 states. Even if filings stopped, the 2026 backlog equals 4.6 years of disposals nationally, led by Bihar (13.0), West Bengal (12.8) and Odisha (11.0). | [chart](outputs/charts/q7_backlog.png) |
| How visible are women in court? | Women are 29% of named petitioners and 15% of defendants, but only about 10% of advocates. Family cases are the exception among litigants, with women as 52% of petitioners. | [chart](outputs/charts/q6_women.png) |
| How do cases end? | Only 51% of closures are decided on the merits. 20% carry a label too vague to say how the case ended, 10% are settled or sent to Lok Adalat, and 7% are withdrawn or lapse. Cheque-bounce cases stand out: only 25% end on the merits, while 37% are settled or withdrawn. | [chart](outputs/charts/q8_outcomes.png) |
| How long until the first hearing? | Half of cases get a first hearing within 30 days, but one in ten waits more than 416 days. Among large states the median runs from 1 day in Punjab to 122 days in Odisha. | [chart](outputs/charts/q9_first_hearing.png) |
| What drives delay? | Case mix does not explain the gaps between states. With case type, filing year and the people involved held constant, a case closes at 0.42 times the rate of a comparable Maharashtra case in Odisha and 0.43 in Bihar, against 1.71 in Karnataka: a 4.0-fold gap. Cases with a named defendant's advocate close 23% more slowly, and those with a woman petitioner 9% more slowly. | [chart](outputs/charts/q10_model.png) |

Every figure has its limits spelled out in [the brief](outputs/where_justice_gets_stuck_brief.pdf), the dashboard and [docs/methods.md](docs/methods.md).

## Delay-risk model

Can we tell, on the day a case is filed, whether it will be decided within 24 months, and how much does a model add over
each court's own history? A proof of concept on a 3.0M-case sample, trained on filings 2010-2014,
validated on 2015 and tested on 2016. **[Read the report](reports/ml_poc_report.md)** | [Model card](docs/model_card.md) |
[Label definition](docs/label_definition.md) | [Feature schema](docs/features.md)

**The answer: mostly the case.** With court features alone (identity, level, history) LightGBM reaches a test ROC-AUC of
0.679; with case features alone (type, act and section, parties), 0.770. The full model (M2) reaches
**0.793**, against **0.679** for the court's prior-year disposal rate (B1): a gain of
**+0.114** (95% interval +0.105 to +0.122 resampling courts; +0.112 to +0.115 resampling
cases, 1,000 resamples). On courts held out of training entirely it scores 0.789.

| Model (test year 2016) | ROC-AUC | PR-AUC | Brier | ROC-AUC, unseen courts |
|---|---|---|---|---|
| B0 majority class | 0.500 | 0.644 | 0.247 | 0.500 |
| B1 court prior-year rate | 0.679 | 0.785 | 0.209 | 0.679 |
| B2 court x case-type prior-year rate | 0.746 | 0.852 | 0.191 | 0.740 |
| M1 logistic regression | 0.764 | 0.866 | 0.191 | 0.741 |
| M2 LightGBM, calibrated | 0.793 | 0.885 | 0.176 | 0.789 |
| M3 Cox (P(decided by day 730)) | 0.759 | 0.860 | 0.191 | 0.752 |

M2 is shown after isotonic recalibration on 2015. Flagging cases whose calibrated chance of a decision within 24 months
is below 0.5 marks 34% of 2016 filings, with precision 62% and recall 59% for overruns.
Every number above is from logged runs `2e6c4f052f` (M2) and `c7d5b105ba` (evaluation), run from commit [`0fcf707`](https://github.com/Ritik650/where-justice-gets-stuck/commit/0fcf707); the log is below.

```mermaid
flowchart LR
    P["Typed Parquet, 80.9M cases"] -->|"sql/labels.sql + DQ rules"| L["Label: decided within 730 days"]
    L -->|"censoring rule, exclusions"| Q["53.7M labelable cases"]
    Q -->|"sample.py, state x year, seeded hash"| S["3.0M-case sample"]
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

Train / valid / test: 1,554,034 / 506,111 / 548,258 cases, plus 80,357 from 636 held-out courts.

## What is here

| Deliverable | Where |
|---|---|
| DuckDB + Parquet pipeline: loaders, SQL rules, act-name mapping | [pipeline/](pipeline/), [sql/dq_rules.sql](sql/dq_rules.sql) |
| Excel data-quality scorecard, with live formulas | [outputs/data_quality_scorecard.xlsx](outputs/data_quality_scorecard.xlsx) |
| Streamlit dashboard: findings, district map, state profiles, data-quality explorer, delay-risk model, what-if calculators | [Live](https://where-justice-gets-stuck.streamlit.app/), [dashboard/](dashboard/) |
| Always-on static copy of the dashboard on GitHub Pages | [Open](https://ritik650.github.io/where-justice-gets-stuck/), [pipeline/build_site.py](pipeline/build_site.py) |
| Two-page brief with the top findings | [outputs/where_justice_gets_stuck_brief.pdf](outputs/where_justice_gets_stuck_brief.pdf) |
| Delay-risk model: labels, point-in-time features, baselines, LightGBM, evaluation, model card | [reports/ml_poc_report.md](reports/ml_poc_report.md), [src/ml/](src/ml/), [docs/model_card.md](docs/model_card.md) |

### Data-management work

| Work | What was built | Where |
|---|---|---|
| Validation rules | 48 rules across completeness, validity, consistency, uniqueness and linkage; 36 found failures | [sql/dq_rules.sql](sql/dq_rules.sql) |
| Standardisation | 17,964 of 29,856 raw act labels mapped to 60 canonical acts, covering 95% of cases with an act record; stages, case types and outcomes too | [pipeline/mappings.py](pipeline/mappings.py), `data/mart/map_*.csv` |
| Coverage check | Cases by state and year, compared with NJDG: share correlation 0.98 | Coverage sheet in the scorecard, Data quality page |
| Documentation | Data dictionary and schema diagram of the files as they really are | [docs/data_dictionary.md](docs/data_dictionary.md) |
| Issue log | Every rule failure and anomaly, with severity, sample records and status | Issue log sheet, Data quality page, [docs/analyst_issues.csv](docs/analyst_issues.csv) |
| Scorecard | Quality scores by state and dimension, with adjustable weights | [outputs/data_quality_scorecard.xlsx](outputs/data_quality_scorecard.xlsx) |

## Run it

The [live dashboard](https://where-justice-gets-stuck.streamlit.app/) needs no setup. To run it yourself, it needs only the small aggregate tables included here:

```
python -m venv .venv
.venv\Scripts\activate
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

The [live copy](https://where-justice-gets-stuck.streamlit.app/) runs on [Streamlit Community Cloud](https://streamlit.io/cloud) and updates when `main` changes. To host your own, point a new app at this repository with `dashboard/app.py` as the main file. It installs the short [dashboard/requirements.txt](dashboard/requirements.txt), and no secrets or row-level data are needed. The case data licence is non-commercial, so keep any hosted copy non-commercial too.

Community Cloud puts an app to sleep when nobody has opened it for a while, so an [always-on copy](https://ritik650.github.io/where-justice-gets-stuck/) is also published with GitHub Pages. It is plain files built from the same tables and the same chart definitions, so its figures always match the app. To rebuild and publish it:

```
python -I pipeline/build_site.py           # writes site/
python -I pipeline/publish_site.py --push   # commits site/ to the gh-pages branch and pushes it
```

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

## Experiment log

The runs every number in this README comes from: one training session and its evaluation, run from commit [`0fcf707`](https://github.com/Ritik650/where-justice-gets-stuck/commit/0fcf707).
[reports/experiments.csv](reports/experiments.csv) keeps every run, with its parameters, feature version, split version,
row counts, config hash and commit. Grid candidates carry no test metrics: the test set was scored only by the models
chosen on validation. Stages: `final` models, `grid` candidates, `experiment` (leakage tests, ablations, the 12-month
label), `evaluation` (bootstrap intervals and threshold).

| Run | Commit | Stage | Model | Label | Valid AUC | Test AUC | Unseen-court AUC | Test Brier | Seconds |
|---|---|---|---|---|---|---|---|---|---|
| `36c90eb4b1` | `0fcf707` | final | B0 majority class | 24m | 0.500 | 0.500 | 0.500 | 0.247 | 0 |
| `ad1400f932` | `0fcf707` | final | B1 court prior-year disposal rate | 24m | 0.687 | 0.679 | 0.679 | 0.209 | 0 |
| `a2dce0620d` | `0fcf707` | final | B2 court x case-type prior-year rate | 24m | 0.742 | 0.746 | 0.740 | 0.191 | 0 |
| `f0a590ab88` | `0fcf707` | experiment | B1b court 24-month rate, cohort filed 3 years earlier | 24m | 0.636 | 0.640 | 0.630 | 0.217 | 0 |
| `2a87396922` | `0fcf707` | final | M1 logistic regression | 24m | 0.784 | 0.764 | 0.741 | 0.191 | 120 |
| `018f013093` | `0fcf707` | grid | M2 LightGBM candidate | 24m | 0.821 |  |  |  | 217 |
| `475174fea4` | `0fcf707` | grid | M2 LightGBM candidate | 24m | 0.821 |  |  |  | 135 |
| `648b1ead30` | `0fcf707` | grid | M2 LightGBM candidate | 24m | 0.820 |  |  |  | 86 |
| `200b441ea0` | `0fcf707` | grid | M2 LightGBM candidate | 24m | 0.821 |  |  |  | 109 |
| `4dcdc58871` | `0fcf707` | grid | M2 LightGBM candidate | 24m | 0.821 |  |  |  | 134 |
| `be398bf530` | `0fcf707` | grid | M2 LightGBM candidate | 24m | 0.821 |  |  |  | 120 |
| `31e78b8245` | `0fcf707` | grid | M2 LightGBM candidate | 24m | 0.820 |  |  |  | 86 |
| `55d9b13a8b` | `0fcf707` | grid | M2 LightGBM candidate | 24m | 0.821 |  |  |  | 84 |
| `2e6c4f052f` | `0fcf707` | final | M2 LightGBM | 24m | 0.821 | 0.793 | 0.789 | 0.187 | 194 |
| `e1b2783e40` | `0fcf707` | final | M3 Cox proportional hazards | 24m | 0.757 | 0.759 | 0.752 | 0.191 | 42 |
| `e602704dac` | `0fcf707` | experiment | M2 + leak: days to last hearing | 24m | 0.999 | 0.997 | 0.995 | 0.017 | 52 |
| `ac87b866d6` | `0fcf707` | experiment | M2 + leak: defendant's advocate named | 24m | 0.826 | 0.796 | 0.790 | 0.185 | 147 |
| `4bfba81659` | `0fcf707` | experiment | M2 court + timing features only | 24m | 0.711 | 0.679 | 0.678 | 0.213 | 50 |
| `26003db628` | `0fcf707` | experiment | M2 case + timing features only | 24m | 0.780 | 0.770 | 0.778 | 0.187 | 54 |
| `ed51f4bc63` | `0fcf707` | experiment | M2 without court and district IDs | 24m | 0.818 | 0.803 | 0.797 | 0.175 | 104 |
| `07a192c44b` | `0fcf707` | experiment | M2 12-month label | 12m | 0.823 | 0.806 | 0.813 | 0.184 | 64 |
| `9ee767d4b9` | `0fcf707` | experiment | M2 trained on 2012-2014 only | 24m | 0.821 | 0.791 | 0.791 | 0.188 | 96 |
| `c7d5b105ba` | `0fcf707` | evaluation | M2 vs B1 on test (bootstrap, calibration, threshold) | 24m |  | 0.793 | 0.789 | 0.176 | 646 |

<details>
<summary>23 earlier runs, superseded by the ones above</summary>

A commit ending in `-dirty` means the code, SQL or config differed from that commit when the run started.

| Run | Commit | Stage | Model | Label | Valid AUC | Test AUC | Unseen-court AUC | Test Brier | Seconds |
|---|---|---|---|---|---|---|---|---|---|
| `b6bdc6564e` | `a4a143a-dirty` | final | B0 majority class | 24m | 0.500 | 0.500 | 0.500 | 0.247 | 0 |
| `4eb252b4f9` | `a4a143a-dirty` | final | B1 court prior-year disposal rate | 24m | 0.687 | 0.679 | 0.679 | 0.209 | 0 |
| `dee389ff94` | `a4a143a-dirty` | final | B2 court x case-type prior-year rate | 24m | 0.742 | 0.746 | 0.740 | 0.191 | 0 |
| `4d273f4d51` | `a4a143a-dirty` | experiment | B1b court 24-month rate, cohort filed 3 years earlier | 24m | 0.636 | 0.640 | 0.630 | 0.217 | 0 |
| `af5f8fec25` | `a4a143a-dirty` | final | M1 logistic regression | 24m | 0.784 | 0.764 | 0.741 | 0.191 | 120 |
| `26ae3e3d82` | `a4a143a-dirty` | grid | M2 LightGBM candidate | 24m | 0.821 |  |  |  | 241 |
| `5e4356525e` | `a4a143a-dirty` | grid | M2 LightGBM candidate | 24m | 0.821 |  |  |  | 172 |
| `b467f3c442` | `a4a143a-dirty` | grid | M2 LightGBM candidate | 24m | 0.820 |  |  |  | 91 |
| `4e568e01bf` | `a4a143a-dirty` | grid | M2 LightGBM candidate | 24m | 0.821 |  |  |  | 136 |
| `cad2c4ab99` | `a4a143a-dirty` | grid | M2 LightGBM candidate | 24m | 0.821 |  |  |  | 139 |
| `1155abb6a6` | `a4a143a-dirty` | grid | M2 LightGBM candidate | 24m | 0.821 |  |  |  | 136 |
| `e9bde2506e` | `a4a143a-dirty` | grid | M2 LightGBM candidate | 24m | 0.820 |  |  |  | 87 |
| `966897ba3b` | `a4a143a-dirty` | grid | M2 LightGBM candidate | 24m | 0.821 |  |  |  | 84 |
| `765fb934f7` | `a4a143a-dirty` | final | M2 LightGBM | 24m | 0.821 | 0.793 | 0.789 | 0.187 | 201 |
| `6fa473e88b` | `a4a143a-dirty` | final | M3 Cox proportional hazards | 24m | 0.757 | 0.759 | 0.752 | 0.191 | 45 |
| `ecf789913e` | `a4a143a-dirty` | experiment | M2 + leak: days to last hearing | 24m | 0.999 | 0.997 | 0.995 | 0.017 | 52 |
| `f1de46cf60` | `a4a143a-dirty` | experiment | M2 + leak: defendant's advocate named | 24m | 0.826 | 0.796 | 0.790 | 0.185 | 172 |
| `6370b06b3b` | `a4a143a-dirty` | experiment | M2 court + timing features only | 24m | 0.711 | 0.679 | 0.678 | 0.213 | 42 |
| `dae581640d` | `a4a143a-dirty` | experiment | M2 case + timing features only | 24m | 0.780 | 0.770 | 0.778 | 0.187 | 34 |
| `e37e37744d` | `a4a143a-dirty` | experiment | M2 without court and district IDs | 24m | 0.818 | 0.803 | 0.797 | 0.175 | 115 |
| `de21eb9582` | `a4a143a-dirty` | experiment | M2 12-month label | 12m | 0.823 | 0.806 | 0.813 | 0.184 | 108 |
| `d7acddc100` | `a4a143a-dirty` | experiment | M2 trained on 2012-2014 only | 24m | 0.821 | 0.791 | 0.791 | 0.188 | 179 |
| `67d928e3ec` | `f8c49c7-dirty` | evaluation | M2 vs B1 on test (bootstrap, calibration, threshold) | 24m |  | 0.793 | 0.789 | 0.176 | 739 |

</details>

## Sources and licences

The code is under the [MIT licence](LICENSE). The data is not: derived tables and charts carry **CC BY-NC-SA 4.0, for non-commercial use only**. See [DATA_LICENSE.md](DATA_LICENSE.md).

- **Case data:** [Development Data Lab](https://www.devdatalab.org/judicial-data), eCourts cases 2010-2018. Cite Ash, Asher, Bhowmick, Bhupatiraju, Chen, Devi, Goessmann, Novosad and Siddiqi (2025), *In-Group Bias in the Indian Judiciary*, The Review of Economics and Statistics.
- **Pendency and judge numbers:** NJDG and the Department of Justice, via [Lok Sabha Unstarred Question 3371](https://sansad.in/getFile/lsapps/loksabhaquestions/annex/188/AU3371_Lq6K9K.pdf), 7 Aug 2026.
- **Section 138 benchmark:** [In Re: Expeditious Trial of Cases under Section 138 NI Act](https://api.sci.gov.in/supremecourt/2020/9631/9631_2020_31_501_27616_Judgement_16-Apr-2021.pdf), Supreme Court of India, 16 Apr 2021.
- **Population:** Census 2011, via [this mirror](https://github.com/nishusharma1608/India-Census-2011-Analysis).
- **Boundaries:** [DataMeet India community](https://github.com/datameet/maps), CC BY 4.0. For display only, and not an official map of India.
- **Dashboard design:** generated with Google Stitch, see [docs/design/](docs/design/stitch_design_tokens.md).
