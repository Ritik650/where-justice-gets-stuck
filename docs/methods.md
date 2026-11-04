# Methods

Why the analysis is built the way it is, written so each decision can be defended in a review or an interview.

## What "open" and "closed" mean

Every question uses one definition, set in the `base` view in `pipeline/analysis.py`.

- **Closed:** decided on or before 31 Dec 2018.
- **Open at the cut-off:** filed 2010-2018 and not closed by then. A case decided in 2019 counts as open.
- **Unusable:** no filing date, decided before filing, or decided after 31 Dec 2020. These 0.4% of rows are left out of durations.

### Why one cut-off date

Monthly recorded decisions run at about 10 lakh through 2018, fall to about 1 lakh by April 2019, and trickle on to September 2020 (`outputs/charts/coverage_cliff.png`). Most courts were collected in early 2019 and only some were collected again later.

With no shared date, courts collected later would have extra months in which cases could close, so they would look faster for a reason that has nothing to do with speed. Treating everything as open on 31 Dec 2018 removes that advantage. It gives up 24.5 lakh later decisions, which are counted as open on the cut-off rather than as closed.

## Survival analysis

A plain average of closed cases leaves out every case still open, and those are the slowest ones. So durations are estimated with Kaplan-Meier, in which a case still open at the cut-off counts towards delay until that date and then leaves the risk set.

Fitting this row by row is not practical at 81M rows. The estimator only needs counts of closures and censored cases at each duration, so DuckDB computes those and `pipeline/km.py` turns them into the exact curve. `tests/test_km.py` checks the result against the `lifelines` library on simulated data, to within 1e-9.

The median is the first day on which half of the cases have closed. It is blank when a group never gets there, and no curve is extrapolated beyond its follow-up.

**Limits.** The pooled curve mixes filing years, and older filings look much slower (median 1,138 days for 2010 against 228 for 2018). That is probably selection, because early digital records lean towards long-running cases, so results are also reported by filing year. A transfer also closes a file without resolving the dispute. Counting transfers as still open raises the pooled median from 450 to 512 days.

## Judge transfers: why the plain comparison misleads

Comparing cases that changed judges with those that did not gives a huge gap (516 against 13 days), but the direction is ambiguous. A slow case has more time in which to see a transfer, so slowness can cause the change. Matching on district, case type and filing year narrows the comparison and leaves that problem in place.

The fairer test uses something the case cannot influence: how long the filing judge had left in the post on the day of filing. Within matched groups, cases filed in the last six months of a judge's tenure are compared with cases filed when the judge had two or more years left. The outcome is the share closed within two years, counting open cases too, on filings up to 2016 so that everyone has two years of follow-up. Tenures still running when the data was collected are excluded.

This gives a modest effect: 2.9 points lower for magistrate trials and 5.4 points lower for sessions trials. It is stronger evidence than the plain comparison but still an association, since tenure endings can coincide with other changes in a court.

## District comparisons

**Unit.** Districts have split since 2011, so a newer district has cases but no 2011 population, and its parent keeps the full population but loses those cases. Using 2011 census districts as the unit, with newer districts counted towards their parents, keeps per-lakh rates honest. `data/external/district_crosswalk_overrides.csv` records the link type for each hand-made link. Mumbai's two census districts are measured as one, because its courts serve both.

**Case mix.** A district with a lot of bail or traffic looks fast for no good reason. The two-year closure share is therefore reweighted to the national mix of case types.

**Incomplete records.** In some districts almost nothing appears to close within two years, even bail, which normally closes within days. That points to unrecorded closures rather than slow courts. A district is flagged when under half of its bail matters (with at least 100 in total) closed within two years, or under 2% of all its cases did. Flagged districts are left off rankings and shaded as no data, and the affected state's median is also reported without them.

**Low volume.** Districts with under 3,000 filings in 2016-18 are not ranked.

**Clearance rate** is closures dated 2016-18 divided by filings in 2016-18. Disposals of pre-2010 cases are absent, so this is a lower bound, better for comparing places than for reading as an absolute figure.

## When the backlog would clear

Two measures are reported, because they answer different questions:

1. **Net flow.** Stock divided by (disposals minus filings). This is what the plan asked for, and it says "never" whenever filings exceed disposals. It is fragile: disposals are understated, and a small error in the difference of two large numbers changes the answer a lot.
2. **Years of disposals.** 2026 stock divided by annual disposals, ignoring new filings. This is a sturdier number for ranking states, so it is the one charted.

Both apply 2016-18 flows to 2026 pendency, so they are scenarios rather than forecasts.

## What drives delay: the Cox model

Survival curves compare one factor at a time, so a state with many slow case types looks slow for that reason alone. A Cox proportional-hazards model (`pipeline/model.py`) holds case type, filing year, state and the people involved constant at once. A hazard ratio above 1 means a case closes faster than its reference group, and below 1 means slower. The references are a magistrate trial, in Maharashtra, filed in 2018.

The model is fitted on a random sample of 3 lakh cases, because that already pins the ratios down. A second sample with a different seed moved them by a median of about 1%. Flagged districts are left out, so incomplete records cannot make a state look slower. Concordance is 0.70: given two cases, the model orders them correctly about 70% of the time.

**Limits.** A hazard ratio averages over the life of a case, and proportional hazards is only an approximation here, since bail closes almost entirely in the first days. The model has no judge numbers or caseload per judge. A named advocate often marks a contested case, so those ratios say nothing about whether a lawyer causes delay.

## How cases end

The 52 raw outcome labels are grouped into six: decided on merits, plea or admission, settled or Lok Adalat, withdrawn or lapsed, transferred or committed, and vague or missing. A fifth of closures carry a label such as "disposed", which does not say how the case ended, and these keep their own group and are never spread over the others.

Conviction shares are reported by case type only, and include guilty pleas and fines. State comparisons are deliberately left out, because labelling is so uneven that they would mostly measure labelling. The share of criminal closures recording a verdict runs from about 0% in Goa to 68% in Kerala.

## First hearing and judge postings

**Time to first hearing** runs from filing to the recorded first listing, using dates between filing and the end of collection. A first listing can be routine, so this measures when a case first reaches a court's list, which may not be a substantive hearing.

**Time in a post** is a Kaplan-Meier median over judge postings, so a posting still running counts rather than being dropped. A posting is one judge in one court position. Moving between court numbers counts as a new posting, which can shorten the figure, so it is used for scale and states are not ranked on it.

## Standardising free text

`pipeline/mappings.py` holds ordered rules for acts, hearing stages, case types and outcomes. Acts are matched after removing everything but letters and digits, so "I.P.C.", "ipc" and "I P C" are the same. Every raw label and its result is written to `data/mart/map_*.csv` for review.

Labels that are not act names ("U/s", "Under") and acts that look like dropdown defaults stay in their own groups, and nothing is forced into a real act. Unit tests pin real labels from the data, including regressions for two rules that once matched far too much.

## Checks that caught real errors

Worth knowing about, because each one passed some earlier check:

| What went wrong | How it was caught |
|---|---|
| A pattern meant for "NACT" matched every name ending in "-ion act", which moved 18 lakh cases into the NI Act | A unit test on "Dowry Prohibition Act" |
| Narrowing a join by the last digits of the case ID lost about 40 lakh act links, while row counts still matched | Reviewing link rates by filing year |
| Judge dates in `DD-MM-YYYY` parsed to nothing, which emptied the tenure test | A query that returned no rows |
| Denominators counted only state-years that failed, which inflated failure rates | Reading the rule table: one rule showed 100% |
| The map polygons had reversed rings, which filled the whole globe with colour | Looking at the rendered map, after all tests had passed |
| Districts with no data first rendered white, then in the scale's palest blue, so they read as fast | Looking at the rendered map again, and then drawing them as a separate grey layer |
| State conviction rates looked dramatic (0% in Goa, 6% in Bihar) but were an artefact of labelling | Checking how many closures recorded a verdict at all |

## Checks against outside data

- DDL's open cases by state against NJDG's 2026 pendency shares: correlation 0.98.
- DDL's median duration by state against the share of NJDG's 2026 cases over five years old: rank correlation 0.63 across 24 large states. Bihar, Odisha, Uttar Pradesh and West Bengal lead both, from sources eight years apart.
- Share of criminal cases with a judge link: 51%, in line with DDL's stated 50-75% match rate.

## What this project cannot say

- It does not describe courts today. Case data ends in 2018.
- It cannot say why a court is slow. Judge vacancies, caseload per judge and local practice are not in the data.
- It does not count cases filed before 2010, which are a large part of the oldest backlog.
- Gender is predicted from names, counts cases rather than people, and is often unclassifiable.
