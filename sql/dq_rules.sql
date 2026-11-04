-- Data-quality rule catalogue. pipeline/quality.py parses this file, so keep the block format.
--
-- grain: case   The body is a boolean predicate over one row of v_dq_case. TRUE means the row FAILS.
--               All case rules are evaluated in one scan per year, grouped by state and year.
-- grain: set    The body is a full SELECT returning state_code, year, failures and optionally checked.
--               {year} marks a rule that runs once per year to keep large anti-joins in memory.
-- applies_to    Optional predicate for the denominator, e.g. only decided cases. Default: all rows.
-- sample        Optional query for the issue log, for set rules. {cases_YYYY} names one year's case file.
-- status        What happens to failing rows: Mitigated (the pipeline handles them), Accepted (a known
--               limit, documented and reported), or Open (needs a decision or a better source).
--
-- Dates: collection_end (2020-12-31) is the latest date any genuine record can carry.
--        analysis_cutoff (2018-12-31) is the shared date on which every undecided case counts as open.

-- id: C01
-- status: Mitigated
-- title: Filing date missing
-- dimension: Completeness
-- severity: High
-- treatment: Excluded from every duration metric because the clock has no start.
-- grain: case
date_of_filing IS NULL

-- id: C02
-- status: Accepted
-- applies_to: decided
-- title: Decided case with no recorded outcome
-- dimension: Completeness
-- severity: High
-- treatment: Kept in duration metrics. Reported as outcome unknown.
-- grain: case
decided AND disp_group = 'Missing'

-- id: C03
-- status: Accepted
-- title: First hearing date missing
-- dimension: Completeness
-- severity: Low
-- treatment: Kept. First-hearing date is not used in duration metrics.
-- grain: case
date_first_list IS NULL

-- id: C04
-- status: Mitigated
-- title: Last hearing date missing
-- dimension: Completeness
-- severity: Medium
-- treatment: Kept. Excluded only from the days-since-last-hearing metric.
-- grain: case
date_last_list IS NULL

-- id: C05
-- status: Accepted
-- applies_to: NOT decided
-- title: Undecided case with no hearing purpose
-- dimension: Completeness
-- severity: Medium
-- treatment: Reported in the 'Not a stage / blank' bar of Q1.
-- grain: case
NOT decided AND purpose_name IS NULL

-- id: C06
-- status: Accepted
-- title: Judge designation missing
-- dimension: Completeness
-- severity: Low
-- treatment: Kept. Designation is descriptive only in this project.
-- grain: case
judge_position IS NULL

-- id: C07
-- status: Accepted
-- title: Petitioner gender not classifiable
-- dimension: Completeness
-- severity: Low
-- treatment: Excluded from the denominator of women's share in Q6, and the excluded share is reported.
-- grain: case
coalesce(female_petitioner, -9999) < 0

-- id: C08
-- status: Accepted
-- title: Defendant gender not classifiable
-- dimension: Completeness
-- severity: Low
-- treatment: Excluded from the denominator of women's share in Q6, and the excluded share is reported.
-- grain: case
coalesce(female_defendant, -9999) < 0

-- id: C09
-- status: Accepted
-- title: Petitioner advocate gender not classifiable
-- dimension: Completeness
-- severity: Low
-- treatment: Excluded from the denominator of women's share in Q6, and the excluded share is reported.
-- grain: case
coalesce(female_adv_pet, -9999) < 0

-- id: C10
-- status: Accepted
-- title: Defendant advocate gender not classifiable
-- dimension: Completeness
-- severity: Low
-- treatment: Excluded from the denominator of women's share in Q6, and the excluded share is reported.
-- grain: case
coalesce(female_adv_def, -9999) < 0

-- id: V01
-- status: Mitigated
-- applies_to: decided
-- title: Decision date before filing date
-- dimension: Validity
-- severity: High
-- treatment: Excluded from duration metrics. A negative duration has no meaning.
-- grain: case
date_of_decision < date_of_filing

-- id: V02
-- status: Mitigated
-- title: Filing date outside the file's year
-- dimension: Validity
-- severity: Medium
-- treatment: Kept in counts by file year. Excluded from durations when the filing date falls outside 2010-2018.
-- grain: case
date_part('year', date_of_filing) <> year

-- id: V03
-- status: Mitigated
-- applies_to: decided
-- title: Decision dated after data collection ended
-- dimension: Validity
-- severity: High
-- treatment: Excluded from duration metrics. The date cannot be real, and the true date is unknown.
-- grain: case
date_of_decision > collection_end

-- id: V04
-- status: Mitigated
-- title: Date earlier than 1950
-- dimension: Validity
-- severity: Medium
-- treatment: The bad date is ignored. Rows with a bad decision date also fail V01.
-- grain: case
least(date_of_filing, date_of_decision, date_first_list, date_last_list, date_next_list) < DATE '1950-01-01'

-- id: V05
-- status: Mitigated
-- title: Last or first hearing dated after data collection ended
-- dimension: Validity
-- severity: Medium
-- treatment: The hearing date is ignored when computing time since last hearing.
-- grain: case
(date_last_list > collection_end AND date_last_list <> DATE '5000-01-01') OR date_first_list > collection_end

-- id: V06
-- status: Accepted
-- title: Next hearing more than five years after data collection ended
-- dimension: Validity
-- severity: Low
-- treatment: Next-hearing date is not used in any metric.
-- grain: case
date_next_list > collection_end_plus_5y

-- id: V07
-- status: Mitigated
-- title: Unparseable date string
-- dimension: Validity
-- severity: Medium
-- treatment: The value is stored as NULL at load.
-- grain: case
date_parse_failures > 0

-- id: V08
-- status: Mitigated
-- title: Gender code outside the documented values
-- dimension: Validity
-- severity: Low
-- treatment: Treated as not classifiable.
-- grain: case
(female_petitioner NOT IN (-9999, -9998, 0, 1)) OR (female_defendant NOT IN (-9999, -9998, 0, 1))
OR (female_adv_pet NOT IN (-9999, -9998, 0, 1)) OR (female_adv_def NOT IN (-9999, -9998, 0, 1))

-- id: V09
-- status: Mitigated
-- title: Last-hearing date is the placeholder 5000-01-01
-- dimension: Validity
-- severity: Medium
-- treatment: Read as missing. It is not used in any duration, and the stale-case check compares earlier dates only.
-- grain: case
date_last_list = DATE '5000-01-01'

-- id: X01
-- status: Accepted
-- title: First hearing before filing
-- dimension: Consistency
-- severity: Medium
-- treatment: Kept. First-hearing date is not used in duration metrics.
-- grain: case
date_first_list < date_of_filing

-- id: X02
-- status: Accepted
-- title: Last hearing before first hearing
-- dimension: Consistency
-- severity: Medium
-- treatment: Kept. Time since last hearing uses the last-hearing date alone.
-- grain: case
date_last_list < date_first_list

-- id: X03
-- status: Accepted
-- applies_to: decided
-- title: Last hearing after the decision
-- dimension: Consistency
-- severity: Medium
-- treatment: Kept. Decision date is used as the end of the case.
-- grain: case
decided AND date_last_list > date_of_decision AND date_last_list <> DATE '5000-01-01'

-- id: X04
-- status: Open
-- applies_to: NOT decided
-- title: Undecided case with an outcome recorded
-- dimension: Consistency
-- severity: High
-- treatment: Kept as open (censored). Counted separately so pendency can be read with and without them.
-- grain: case
NOT decided AND disp_group <> 'Missing'

-- id: X05
-- status: Accepted
-- applies_to: decided
-- title: Decided case with a later hearing scheduled
-- dimension: Consistency
-- severity: Low
-- treatment: Kept. Next-hearing date is not used in any metric.
-- grain: case
decided AND date_next_list > date_of_decision

-- id: X06
-- status: Open
-- applies_to: NOT decided
-- title: Never-decided case with no hearing in the two years before the cut-off
-- dimension: Consistency
-- severity: Medium
-- treatment: Kept as open. Could be real inactivity or an unclosed record, so it is reported as a stale share.
-- grain: case
NOT decided AND date_last_list < cutoff_minus_2y

-- id: X07
-- status: Accepted
-- title: Case-ID year differs from the file year
-- dimension: Consistency
-- severity: Low
-- treatment: Kept. Case IDs are used only for joining.
-- grain: case
TRY_CAST(right(ddl_case_id, 4) AS INTEGER) <> year

-- id: X08
-- status: Accepted
-- applies_to: decided
-- title: Closed with a generic label such as 'disposed'
-- dimension: Consistency
-- severity: Low
-- treatment: Kept in duration metrics. Excluded from any outcome reading.
-- grain: case
decided AND disp_group = 'Generic ''disposed'''

-- id: X09
-- status: Mitigated
-- applies_to: decided
-- title: Closed by transfer or committal rather than a resolution
-- dimension: Consistency
-- severity: Medium
-- treatment: Counted as closed in the main curves, to match official disposal counts. Removed in the sensitivity curve.
-- grain: case
decided AND disp_group = 'Transferred / committed'

-- id: X10
-- status: Mitigated
-- applies_to: decided
-- title: Decided after the 2018 cut-off
-- dimension: Consistency
-- severity: Info
-- treatment: Counted as open on the cut-off, because only some courts were collected again after January 2019.
-- grain: case
date_of_decision > analysis_cutoff AND date_of_decision <= collection_end

-- id: U01
-- status: Mitigated
-- title: Duplicate case ID
-- dimension: Uniqueness
-- severity: High
-- treatment: Only the first row per ID would be kept in the analysis table.
-- grain: set
WITH d AS (SELECT ddl_case_id, count(*) AS n, min(state_code) AS state_code, min(year) AS year
           FROM cases GROUP BY 1 HAVING count(*) > 1)
SELECT state_code, year, sum(n - 1) AS failures FROM d GROUP BY 1, 2

-- id: U02
-- sample: SELECT state_code, date_of_filing::VARCHAR AS filed, count(*) AS identical_rows, min(ddl_case_id) AS first_id, max(ddl_case_id) AS last_id FROM read_parquet('{cases_2018}') GROUP BY state_code, dist_code, court_no, judge_position, type_name, purpose_name, disp_name, date_of_filing, date_of_decision, date_first_list, date_last_list, date_next_list, female_petitioner, female_defendant, female_adv_pet, female_adv_def HAVING count(*) > 1 ORDER BY 3 DESC LIMIT 3
-- status: Accepted
-- title: Rows identical on every field except the ID
-- dimension: Uniqueness
-- severity: Low
-- treatment: Kept. Many are genuine batch filings (one complainant, many cases), which rows alone cannot separate from double entry.
-- grain: set
WITH g AS (
    SELECT state_code, year, count(*) AS n
    FROM read_parquet('{cases_year}')
    WHERE date_of_filing IS NOT NULL
    GROUP BY state_code, dist_code, court_no, year, judge_position, type_name, purpose_name, disp_name,
             date_of_filing, date_of_decision, date_first_list, date_last_list, date_next_list,
             female_petitioner, female_defendant, female_adv_pet, female_adv_def
    HAVING count(*) > 1
)
SELECT state_code, year, sum(n - 1) AS failures FROM g GROUP BY 1, 2

-- id: L01
-- status: Mitigated
-- title: State code absent from the state key
-- dimension: Linkage
-- severity: High
-- treatment: The case would stay in national totals and drop out of state views.
-- grain: set
SELECT f.state_code, f.year, count(*) AS failures
FROM fact f ANTI JOIN (SELECT DISTINCT state_code FROM cases_state_key) k USING (state_code)
GROUP BY 1, 2

-- id: L02
-- sample: SELECT c.ddl_case_id, c.state_code, c.dist_code FROM read_parquet('{cases_2018}') c ANTI JOIN dim_district k USING (state_code, dist_code) LIMIT 3
-- status: Mitigated
-- title: District code absent from the district key
-- dimension: Linkage
-- severity: High
-- treatment: The case stays in state totals and drops out of district views.
-- grain: set
SELECT f.state_code, f.year, count(*) AS failures
FROM fact f ANTI JOIN dim_district k USING (state_code, dist_code)
GROUP BY 1, 2

-- id: L03
-- status: Accepted
-- title: Court code absent from the court key
-- dimension: Linkage
-- severity: Medium
-- treatment: Kept. Court names are not used in the headline metrics.
-- grain: set
SELECT f.state_code, f.year, count(*) AS failures
FROM fact f ANTI JOIN (SELECT DISTINCT state_code, dist_code, court_no FROM cases_court_key) k
     USING (state_code, dist_code, court_no)
GROUP BY 1, 2

-- id: L04
-- status: Mitigated
-- title: Case-type code absent from the type key for that year
-- dimension: Linkage
-- severity: Medium
-- treatment: Placed in the 'Other / unmapped' case category.
-- grain: set
SELECT c.state_code, c.year, count(*) AS failures
FROM cases c ANTI JOIN map_type k ON c.type_name = k.type_name AND c.year = k.year
WHERE c.type_name IS NOT NULL
GROUP BY 1, 2

-- id: L05
-- status: Mitigated
-- title: Purpose code absent from the purpose key for that year
-- dimension: Linkage
-- severity: Medium
-- treatment: Placed in the 'Not a stage / blank' bar of Q1.
-- grain: set
SELECT c.state_code, c.year, count(*) AS failures
FROM cases c ANTI JOIN map_purpose k ON c.purpose_name = k.purpose_name AND c.year = k.year
WHERE c.purpose_name IS NOT NULL
GROUP BY 1, 2

-- id: L06
-- sample: SELECT c.ddl_case_id, c.date_of_filing::VARCHAR AS filed FROM read_parquet('{cases_2012}') c ANTI JOIN acts a USING (ddl_case_id) LIMIT 3
-- status: Accepted
-- title: Case with no act or section record
-- dimension: Linkage
-- severity: High
-- treatment: Kept in overall metrics. Shown as 'No act record' in Q3.
-- grain: set
SELECT state_code, year, count(*) AS failures FROM fact WHERE NOT has_act_row GROUP BY 1, 2

-- id: L07
-- sample: SELECT ddl_case_id FROM acts WHERE right(ddl_case_id, 4) = '2019' LIMIT 3
-- status: Mitigated
-- title: Act record with no matching case
-- dimension: Linkage
-- severity: Medium
-- treatment: Ignored, because all analysis starts from the case table.
-- grain: set
WITH a AS (SELECT substr(ddl_case_id, 1, 2) AS state_code, count(*) AS rows_in_acts FROM acts GROUP BY 1),
     m AS (SELECT state_code, count(*) AS matched FROM fact WHERE has_act_row GROUP BY 1)
SELECT a.state_code, NULL::INTEGER AS year, a.rows_in_acts - coalesce(m.matched, 0) AS failures, a.rows_in_acts AS checked
FROM a LEFT JOIN m USING (state_code)

-- id: L08
-- sample: SELECT act_s AS raw_label, declared_count::BIGINT AS cases FROM map_act WHERE act_family = 'Unknown' ORDER BY declared_count DESC LIMIT 5
-- status: Accepted
-- title: Act label blank, not an act name, or implausible
-- dimension: Linkage
-- severity: Medium
-- treatment: Shown as its own group in Q3 and never forced into a real act.
-- grain: set
SELECT state_code, year, count(*) AS failures FROM fact WHERE has_act_row AND act_family = 'Unknown' GROUP BY 1, 2

-- id: L09
-- sample: SELECT act_s AS raw_label, declared_count::BIGINT AS cases FROM map_act WHERE act_canonical = 'Other / unmapped' ORDER BY declared_count DESC LIMIT 5
-- status: Open
-- title: Act label not mapped to a canonical act
-- dimension: Linkage
-- severity: Low
-- treatment: Shown as 'Other / unmapped' in Q3. The mapping table lists every label for review.
-- grain: set
SELECT state_code, year, count(*) AS failures FROM fact WHERE act_canonical = 'Other / unmapped' GROUP BY 1, 2

-- id: L10
-- sample: SELECT act_s AS raw_label, declared_count::BIGINT AS cases FROM map_act WHERE act_family IN ('Criminal procedure', 'Civil procedure') ORDER BY declared_count DESC LIMIT 5
-- status: Accepted
-- title: Filed only under a procedural code (CrPC or CPC)
-- dimension: Linkage
-- severity: Medium
-- treatment: Kept, but the underlying law cannot be identified, so Q3 reports these separately.
-- grain: set
SELECT state_code, year, count(*) AS failures FROM fact WHERE act_family IN ('Criminal procedure', 'Civil procedure') GROUP BY 1, 2

-- id: L11
-- sample: SELECT a.ddl_case_id FROM (SELECT ddl_case_id FROM acts WHERE criminal = 1 AND right(ddl_case_id, 4) = '2014') a ANTI JOIN judge_key j USING (ddl_case_id) LIMIT 3
-- status: Accepted
-- title: Criminal case with no judge link
-- dimension: Linkage
-- severity: Medium
-- treatment: Excluded from Q4 only. DDL states that links exist only for criminal cases and match 50-75% of them.
-- grain: set
SELECT state_code, year, count(*) FILTER (NOT has_judge_row) AS failures, count(*) AS checked
FROM fact WHERE criminal = 1 GROUP BY 1, 2

-- id: L12
-- sample: SELECT j.ddl_case_id, j.ddl_filing_judge_id AS filing_judge FROM judge_key j ANTI JOIN judges g ON TRY_CAST(j.ddl_filing_judge_id AS DOUBLE) = g.ddl_judge_id LIMIT 3
-- status: Mitigated
-- title: Filing judge missing from the judge table
-- dimension: Linkage
-- severity: Medium
-- treatment: Excluded from the tenure-based part of Q4.
-- grain: set
SELECT f.state_code, f.year, count(*) FILTER (j.ddl_judge_id IS NULL) AS failures, count(*) AS checked
FROM fact f LEFT JOIN judges j ON f.filing_judge = j.ddl_judge_id
WHERE f.has_judge_row
GROUP BY 1, 2

-- id: L13
-- status: Mitigated
-- title: Filing date outside the filing judge's tenure
-- dimension: Consistency
-- severity: Medium
-- treatment: Excluded from the tenure-based part of Q4.
-- grain: set
SELECT f.state_code, f.year,
       count(*) FILTER (f.date_of_filing < j.start_date OR f.date_of_filing > j.end_date) AS failures,
       count(*) AS checked
FROM fact f JOIN judges j ON f.filing_judge = j.ddl_judge_id
GROUP BY 1, 2

-- id: L14
-- sample: SELECT state_name, district_name FROM dim_district WHERE population IS NULL LIMIT 5
-- status: Accepted
-- title: Case in a court with no Census 2011 population link
-- dimension: Linkage
-- severity: Medium
-- treatment: The state total keeps the case. District per-lakh figures cannot include it (statewide tribunals).
-- grain: set
SELECT f.state_code, f.year, count(*) AS failures
FROM fact f JOIN dim_district d USING (state_code, dist_code)
WHERE d.population IS NULL
GROUP BY 1, 2

-- id: L15
-- status: Mitigated
-- title: Judge tenure ends before it starts
-- dimension: Validity
-- severity: Medium
-- treatment: The judge row is excluded from the tenure-based part of Q4.
-- grain: set
SELECT state_code, NULL::INTEGER AS year, count(*) FILTER (end_date < start_date) AS failures, count(*) AS checked
FROM judges GROUP BY 1, 2

-- id: L16
-- sample: SELECT type_name_s AS raw_label, sum(TRY_CAST(count AS DOUBLE))::BIGINT AS cases FROM map_type WHERE type_category = 'Other / unmapped' GROUP BY 1 ORDER BY 2 DESC LIMIT 5
-- status: Mitigated
-- title: Case-type label not mapped to a category
-- dimension: Linkage
-- severity: Low
-- treatment: Shown as 'Other / unmapped' in the survival curves.
-- grain: set
SELECT state_code, year, count(*) AS failures FROM fact WHERE type_category = 'Other / unmapped' GROUP BY 1, 2

-- id: L17
-- sample: SELECT purpose_name_s AS raw_label, sum(TRY_CAST(count AS DOUBLE))::BIGINT AS cases FROM map_purpose WHERE stage = '11 Not a stage / blank' GROUP BY 1 ORDER BY 2 DESC LIMIT 5
-- status: Accepted
-- title: Hearing label says nothing about the stage
-- dimension: Linkage
-- severity: Low
-- treatment: Shown as 'Not a stage / blank' in Q1 and never spread across real stages.
-- grain: set
SELECT state_code, year, count(*) AS failures FROM fact WHERE stage = '11 Not a stage / blank' GROUP BY 1, 2
