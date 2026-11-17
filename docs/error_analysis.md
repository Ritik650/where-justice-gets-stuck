# Error analysis: the 100 most confident mistakes

The delay-risk model's 50 most confident false positives (predicted to be decided within 24 months, but not) and 50
most confident false negatives (predicted not to be, but decided) on the 2016 test filings, read case by case.
`reports/error_cases.csv` lists all 100 with what happened to each case after filing; `src/ml/evaluate.py` attaches a
first, rule-based cause to each, and this page groups them by reading them. Counts are from evaluation run
`67d928e3ec`. All 100 sit at the extremes of the calibrated scale (above 0.99 or below 0.02), so they show where the
model is confidently wrong, not where it is typically wrong.

## The headline: most confident mistakes are about records

Both groups are dominated by cases where the court's records, not the court's speed, drove the prediction.

## False negatives: courts whose history reads near zero

All 50 come from courts whose recorded disposal rate in 2015 was under 10%: 38 in Jammu and Kashmir (16 of them in
courts with no recorded decision at all that year), 6 in Bihar, 5 in West Bengal and 1 in Tamil Nadu. The model learned
that such courts almost never decide a case within two years, and predicted under 2%. These cases were decided in 23 to
722 days, most with a vague label: "disposed" (19), "dismissed" (10), "withdrawn" (5), "compromise" (4).

| Group | Cases |
|---|---|
| Court recorded no decisions in 2015 | 16 |
| Court's recorded 2015 rate above zero but under 10% | 34 |

The reading: a court that files cases all year but records almost no decisions is more likely missing decision records
than closing nothing. Jammu and Kashmir's recorded decisions swing from 31,484 in 2015 to 18,771 in 2016 and 75,848 in
2018. Across the whole test set, 2% of cases come from courts with zero recorded decisions in 2015; 33% of those were
decided within 24 months, while the model predicted 17% on average. The zero is real in some places (under 1% decided
in Bihar's zero-rate courts) and a recording gap in others (about 70% in Chhattisgarh and Gujarat), and the model has
no way to tell which. Logged as issue AN-23 in [analyst_issues.csv](analyst_issues.csv).

## False positives: closures never recorded, near misses, and two local practices

| Group | Cases | What happened |
|---|---|---|
| Bail never recorded as decided | 17 | Bail matters in eight states with no decision date and no outcome; the last hearing was on the day of filing, within 13 days of it, or never. Bail is heard in days, so these look like records left open, the same problem that got nine districts excluded from the model. |
| Cases never decided, stuck at an early or middle stage | 13 | 8 were last listed for summons, notice, service or appearance: the steps that get parties to court, which the project's Q1 finding identifies as where open cases stall. These are real delays the filing-day information could not foresee. |
| Kerala summary trials decided just after the window | 8 | Decided in 737 to 970 days, mostly with a fine. Kerala labels summary trials "ST", which the project's type rules read as sessions trials (issue AN-22). The model also sees the raw label, so it judged them correctly as quick petty matters; these few just took a little over two years. |
| Karnataka birth and death registration petitions | 8 | Petitions under the Registration of Births and Deaths Act, usually quick, that took 752 to 1,039 days or are still open. A local cluster, likely a batch in a few courts. |
| Bail decided after the window | 2 | Decided in 736 and 845 days. |
| Other cases decided after the window | 2 | Decided in 731 and 874 days. |

Of the 16 that were eventually decided, 12 were decided within four months after the window closed (731 to 845 days):
near misses that any fixed 730-day cut-off produces.

## What to change

1. **Treat a court-year with filings but no recorded decisions as missing**, not as a disposal rate of zero, so the
   model falls back on the district's rate (AN-23).
2. **Fix the Kerala "ST" mapping** in `pipeline/mappings.py` and re-run the descriptive analyses (AN-22).
3. **Extend the closure-records check below the district level.** The bail test that flags districts would also
   catch individual courts whose bail matters never close.
4. Accept the rest: a filing-day model cannot know that a summons will not be served, and the 730-day cut-off will
   always have near misses. The calibrated probabilities, not a hard label, are the honest output.
