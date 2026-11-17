# Label definition

The delay-risk model predicts, at filing, whether a case will be **decided within 24 months**. This file defines that
label, the censoring rule that keeps it honest, and every edge case. The definition lives in one place,
`sql/labels.sql`, which the audit, the sample and the tests all read. Counts below are from `make dq` on the full data
(`reports/label_audit.csv`, `reports/label_checks.csv`, `reports/observation_end.json`).

## The label

| Name | Definition |
|---|---|
| `label_24m` | **1** if a decision is dated within 730 days of filing (day 0 to day 730 inclusive); **0** if the case was decided later, or was still pending on day 730 |
| `label_12m` | The same with 365 days: a secondary check |
| `duration_days`, `event_by_t_end` | For the Cox model: days to decision, or to T_end for a case still open then (censored) |

Days are counted, not calendar months, so a leap day does not shift the boundary.

## The observation end, T_end = 31 December 2018

The latest decision date in the files is 9201-09-27, a typing error that rule V03 already catches. The latest plausible
one is 31 December 2020. Neither is a usable observation end:

- Recorded decisions run at about 10.2 lakh a month through 2018, then fall to about 1.07 lakh a month from April 2019
  (an 89.5% drop), because most courts were collected in early 2019 and only some again later.
- If T_end were in 2020, re-collected courts would have extra months in which cases could close, and their cases would
  look faster for a reason that has nothing to do with speed. A case decided in 2019 in a court collected once in
  January 2019 would be recorded as never decided.

So T_end is 31 December 2018, the cut-off the rest of this project already uses (`docs/methods.md`). December 2018
still records 12.3 lakh decisions, so the months just before T_end are complete nationally.

**One state-level caveat.** Decisions recorded in the last quarter of 2018, against the same quarter of 2017, were 61%
in Odisha, 57% in Mizoram and 64% in Meghalaya (`reports/window_completeness.csv`). If those courts were collected
before the end of 2018, some late-2016 filings there are labelled 0 that should be 1. The two small states barely
affect the model; Odisha is reported as a slice.

## The censoring rule

A label is defined only when its whole window has been observed: filed on or before T_end minus 730 days, that is, by
**31 December 2016** (`eligible_24m`). The 12-month label needs filing by 31 December 2017 (`eligible_12m`).

Without this rule a case filed in mid-2018 and still pending at T_end would be labelled 0 after only six months of
observation, and recent filings would look slow because they had no time to finish. The rule costs every 2017 and 2018
filing, which the Cox model (M3) can still use as censored observations.

## Exclusions, reusing the data-quality rules

| Step | Rule (`sql/dq_rules.sql`) | Cases left | Removed |
|---|---|---|---|
| All cases in the case files | | 80,935,944 | |
| Filing date present | C01 | 80,935,944 | 0 |
| Filing date within 2010-2018 | V02 | 80,935,944 | 0 |
| Decision not dated before filing | V01 | 80,590,048 | 345,896 |
| Decision not dated after collection ended | V03 | 80,588,491 | 1,557 |
| District's closure records complete | `q5_districts` flag | 80,043,425 | 545,066 |
| 24-month window observed | censoring rule | **53,660,034** | 26,383,391 |

(The 12-month window is observed for 66,540,566 cases.)

- **C01, V02:** no clock start, so no label. None occur in these files, but the rules stay in force.
- **V01:** a decision before filing has no meaning as a duration.
- **V03:** the recorded decision date cannot be real, and the true date is unknown, so the label is unknown too.
- **Flagged districts:** `pipeline/analysis.py` flags a district when under half of its bail matters (at least 100) closed
  within two years, or under 2% of all its cases did. Bail normally closes in days, so this points to closures that
  were never recorded, and every case there would carry a false 0. They are excluded, as they are from the project's
  Cox model. The flag uses outcomes from every year, which is acceptable for selecting which records to trust but would
  not be as a model input; it is never an input.

## Edge cases

| Case | Label | Count in the modelling population |
|---|---|---|
| Decided on the day of filing | 1 | 3,682,471 (6.9%), mostly bail and petty matters |
| Decided on day 730 exactly | 1: the window includes its last day | 19,604 |
| Decided on day 731 or later | 0 | 12,930,857 decided after the window |
| Never decided at all | 0 | 10,255,165 (19.1%) |
| Decided after T_end but before collection ended | 0: necessarily after the window | included in the row above |
| Undecided, but an outcome is recorded (rule X04) | 0: counted as pending, as in the main analysis. It may be a decision whose date was lost | 18,763 (0.035%) |
| Closed by transfer or committal within the window (rule X09) | 1: the file closed, matching official disposal counts, though the dispute moved elsewhere | 2,093,787 (3.9%) |
| Decided within 12 months | `label_12m` = 1 implies `label_24m` = 1, checked as invariant LB05 | |

Six invariants are checked on every build, and `make dq` stops if any fails: no label window ends after T_end, no
positive label lacks a decision date, no positive label was decided after its window, no negative label was decided
inside it, the 12-month label implies the 24-month one, and no Cox duration is negative. All six have zero failures.

## Class balance

| Filing year | Cases | Decided within 24 months |
|---|---|---|
| 2010 | 4,225,379 | 36.5% |
| 2011 | 5,143,565 | 43.8% |
| 2012 | 6,341,295 | 49.5% |
| 2013 | 7,495,654 | 56.6% |
| 2014 | 8,813,692 | 61.5% |
| 2015 | 10,396,579 | 63.5% |
| 2016 | 11,243,870 | 64.7% |

The rise is mostly about records, not courts getting faster. Courts began entering cases into eCourts during this
period, and a 2010 case that closed quickly was often never entered, while a long-running one was carried into the
system. Early filing years therefore over-represent slow cases. The temporal split trains on 2010-2014 and tests on
2016, so this shift is part of what the test measures; an experiment trains on 2012-2014 only to see how much it costs.
State-level balance is in `reports/class_balance.csv` and in the report.

## Tests

`tests/test_ml_labels.py` builds cases by hand and runs them through the real view: day 0, 365, 366, 730 and 731; never
decided; decided after T_end; decided after collection ended; decided before filing; no filing date; filed outside the
file years; the last eligible and first ineligible filing days; a leap-day filing; an outcome without a date; a
transfer; and a case in a flagged district.
