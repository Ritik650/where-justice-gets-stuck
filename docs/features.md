# Feature schema

The 25 model inputs of the delay-risk model, each with its type, source and point-in-time rule. They are built in DuckDB
SQL (`sql/features.sql`) and finished in `src/ml/features.py`; the feature list itself is `FEATURES` in that file, and
`tests/test_ml_features.py` checks that every one is documented here.

**The point-in-time rule.** A feature for a case filed on day *d* uses only information dated before *d*:

- yearly court history for a case filed in year *Y* uses events dated in *Y*-1 or earlier;
- the pending load uses events dated before the first day of the filing month;
- the cohort rate uses cases filed in *Y*-3, whose 730-day windows all closed by the end of *Y*-1.

History counts every case with a valid filing date (rules C01 and V02 pass), and a decision only from its own date and
only when that date is valid (rules V01 and V03 pass). Filtering history on whether a case's eventual decision date
turns out valid would use the future, so it is not done. Two tests rebuild the features after deleting every event on
or after a case's filing month (or filing year, for the yearly features) and check that no input changes.

Category vocabularies (`case_type_label`, `act_section`) are counted on the training years only, and rarer values are
pooled into `other`, so the test years cannot shape them.

## Case

| Feature | Type | Source | Point-in-time rule |
|---|---|---|---|
| `case_type` | categorical, 12 levels (11 categories and Other / unmapped) | `type_name` decoded by `type_name_key` (code and year), then `pipeline/mappings.py` | Assigned at registration. |
| `case_type_label` | categorical, top 150 + `other` | The raw case-type label, lower-cased | Assigned at registration. |
| `act` | categorical | `acts_sections.act` standardised by `pipeline/mappings.py`; `No act record` when the case has none | Entered at registration, as recorded at collection. |
| `act_section` | categorical, top 60 + `other` | Standardised act plus the first section number (`section_key`) | As above. |
| `ddl_criminal_flag` | categorical: 0, 1, missing | `acts_sections.criminal` | DDL's classification of the filing. |
| `petitioner_gender` | categorical: woman, man, unclear, missing | `female_petitioner` (predicted from the name by DDL) | The petitioner is named in the filing. |
| `defendant_gender` | categorical: woman, man, unclear, missing | `female_defendant` | The respondent or accused is named in the filing. |
| `petitioner_advocate` | categorical: woman, man, unclear, none named | `female_adv_pet` | The petitioner's advocate files the case. |

## Court identity

| Feature | Type | Source | Point-in-time rule |
|---|---|---|---|
| `state` | categorical | `state_code` | Where the case is filed. |
| `district` | categorical | `state_code` + `dist_code` | As above. |
| `court` | categorical, about 7,000 establishments | `state_code` + `dist_code` + `court_no` | As above. |
| `court_level` | categorical, 11 levels | The establishment's name in `cases_court_key` (latest spelling), mapped by rules in `sql/features.sql`: district and sessions, magistrate, civil judge senior or junior division, family court, and so on | A property of the court, not of any case. |

## Court history

All computed from every validly filed case in the data, not only the sample.

| Feature | Type | Definition | Point-in-time rule |
|---|---|---|---|
| `court_disp_rate_py` | numeric, 0-1 | The court's decisions dated in *Y*-1 divided by its workload in *Y*-1 (cases pending on 1 January *Y*-1 plus filings in *Y*-1). **This is baseline B1.** | Events dated in *Y*-1 or earlier. |
| `court_type_disp_rate_py` | numeric, 0-1 | The same for the court and this case type, shrunk towards the court's rate: (decisions + 20 x court rate) / (workload + 20). **This is baseline B2.** | As above. |
| `district_disp_rate_py` | numeric, 0-1 | The district's rate in *Y*-1 | As above. |
| `state_disp_rate_py` | numeric, 0-1 | The state's rate in *Y*-1 | As above. |
| `court_type_share_py` | numeric, 0-1 | This case type's share of the court's filings in *Y*-1 | Filings dated in *Y*-1. |
| `log_court_filings_py` | numeric | log(1 + the court's filings in *Y*-1) | Filings dated in *Y*-1. |
| `court_cohort_rate_lag3` | numeric, 0-1 | The share of the court's cases filed in *Y*-3 that were decided within 730 days. Missing before 2013. | Every such window closed by 31 December *Y*-1. |
| `log_court_pending_at_filing` | numeric | log(1 + cases pending in the court on the first day of the filing month) | Filings and decisions dated before that day. |
| `court_backlog_months` | numeric | Pending cases on that day divided by (decisions in the previous 12 months / 12 + 1): months of decisions needed to clear the stock | As above. |
| `court_years_active` | numeric | Filing year minus the first year the court files anything in this data | The court's first filing is never later than this case's. |

When a court had no workload in *Y*-1, its rates are missing. LightGBM handles missing values directly; the logistic
regression imputes the median and adds a missing-value indicator. The B1 score falls back to the district, then the
state, then the national rate; B2 falls back to B1. **B1b** (`b1b_score`), an alternative court baseline, is
`court_cohort_rate_lag3` with the same fallback.

Because the data starts in 2010, pending loads and rates count only cases filed from 2010, so they rise mechanically in
the early years. Filing year is an input so the model can allow for this.

## Timing

| Feature | Type | Definition |
|---|---|---|
| `filing_year` | numeric | Year of filing |
| `filing_month` | numeric, 1-12 | Month of filing |
| `filing_weekday` | numeric, 1-7 | ISO weekday of filing (1 = Monday) |

## Kept apart for the leakage test

These are in the feature table with the prefix `leak_` and are never model inputs, except in the leakage experiment
that adds one on purpose to show the effect ([feature_audit.md](feature_audit.md)).

| Column | Why it leaks |
|---|---|
| `leak_days_to_last_hearing` | Days from filing to the last hearing listed at collection. For a decided case this is close to the time to decision. |
| `leak_defendant_advocate_named` | Whether a defendant's advocate is on record: entered when the defendant contests, after filing, and mostly in long cases. |
| `leak_last_hearing_stage` | The stage of the last listed hearing (`purpose_name`), for example "judgment" for a decided case. |

## Labels carried in the same table

`label_24m` and `label_12m` (the targets), and `duration_days` with `event_by_t_end` for the Cox model. See
[label_definition.md](label_definition.md).
