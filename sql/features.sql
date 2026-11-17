-- Point-in-time features for the delay-risk model. src/ml/features.py fills the {placeholders} from config.yaml and
-- adds the fallbacks and pooled categories. docs/features.md lists each feature with its rule; docs/feature_audit.md
-- marks every source column as known at filing or known after filing.
--
-- The rule: a feature for a case filed on day d uses only information dated before d.
--   * Yearly court history for a case filed in year Y uses events dated in Y-1 or earlier.
--   * Pending load uses events dated before the first day of the filing month.
--   * The cohort rate uses cases filed in Y-3: every one of their 730-day windows closed by the end of Y-1.
-- History counts every case with a valid filing date, not just the sample, as a court registry would see it; a
-- decision counts from its own date, and only when that date is valid (see filed_ok and decision_ok in sql/labels.sql).
-- tests/test_ml_features.py rebuilds these tables with all later events deleted and checks nothing changes.

-- 0. Lookup tables with one row per key, so no join can add rows.
CREATE OR REPLACE TEMP TABLE type_map AS
SELECT year, type_name, any_value(type_category) AS type_category, any_value(lower(trim(type_name_s))) AS type_label
FROM read_parquet('{map_type}') GROUP BY ALL;

CREATE OR REPLACE TEMP TABLE act_map AS
SELECT act, any_value(act_canonical) AS act_canonical, any_value(act_family) AS act_family
FROM read_parquet('{map_act}') GROUP BY ALL;

CREATE OR REPLACE TEMP TABLE section_map AS
SELECT TRY_CAST(section AS BIGINT) AS section,
       any_value(upper(regexp_extract(section_s, '[0-9]+[A-Za-z]?'))) AS section_norm
FROM read_parquet('{section_key}') GROUP BY 1;

CREATE OR REPLACE TEMP TABLE purpose_map AS
SELECT year, purpose_name, any_value(stage) AS stage
FROM read_parquet('{map_purpose}') GROUP BY ALL;

-- Court level, from the establishment's name in DDL's court key (its latest spelling). A property of the court, so it
-- is known at filing.
CREATE OR REPLACE TEMP TABLE court_info AS
WITH k AS (
    SELECT state_code || '-' || dist_code || '-' || court_no AS court,
           arg_max(court_name, TRY_CAST(year AS INTEGER)) AS court_name
    FROM read_parquet('{court_key}') GROUP BY 1
), n AS (SELECT court, court_name, lower(coalesce(court_name, '')) AS s FROM k)
SELECT court, court_name,
       CASE WHEN regexp_matches(s, 'family') THEN 'Family court'
            WHEN regexp_matches(s, 'juvenile|juveniel') THEN 'Juvenile justice board'
            WHEN regexp_matches(s, 'motor accident|m\.?a\.?c\.?t\b|claims? tribunal') THEN 'Motor accident claims tribunal'
            WHEN regexp_matches(s, 'co-?op|cooperative|labour|industrial|consumer|small cause|\brent\b|railway|tribunal|special|\bcbi\b|lok adalat')
                 THEN 'Special court or tribunal'
            WHEN regexp_matches(s, 'senior division|sr\.? ?div|senior civil|sub[- ]?court|subordinate judge|\bcjsd\b') THEN 'Civil judge, senior division'
            WHEN regexp_matches(s, 'junior division|jr\.? ?div|junior civil|munsif|civil judge\s*(and|cum|&)\s*(jmfc|judicial)|taluka')
                 THEN 'Civil judge, junior division'
            WHEN regexp_matches(s, 'district|session|\bdj\b|d\.? ?j\.? ?div|principal judge|city civil') THEN 'District and sessions court'
            WHEN regexp_matches(s, 'civil (and|&) criminal') THEN 'Combined civil and criminal court'
            WHEN regexp_matches(s, 'magistrate|\bcjm\b|c\.? ?j\.? ?m\b|jmfc|\bcmm\b|acmm|\bmm\b|criminal|judicial first class') THEN 'Magistrate court'
            WHEN regexp_matches(s, 'civil') THEN 'Civil court, level not stated'
            ELSE 'Other or not stated' END AS court_level
FROM n;

-- 1. Yearly filings and decisions per court and case type, from every validly filed case.
CREATE OR REPLACE TEMP TABLE flow_ct AS
WITH base AS (
    SELECT l.state_code,
           l.state_code || '-' || l.dist_code AS district,
           l.state_code || '-' || l.dist_code || '-' || l.court_no AS court,
           coalesce(t.type_category, 'Other / unmapped') AS case_type,
           year(l.date_of_filing) AS filed_year,
           CASE WHEN l.decision_ok AND l.date_of_decision <= DATE '{t_end}' THEN year(l.date_of_decision) END AS decided_year
    FROM case_label l
    LEFT JOIN type_map t ON l.type_name = t.type_name AND l.year = t.year
    WHERE l.filed_ok
), filed AS (
    SELECT state_code, district, court, case_type, filed_year AS yr, count(*) AS filed FROM base GROUP BY ALL
), decided AS (
    SELECT state_code, district, court, case_type, decided_year AS yr, count(*) AS decided
    FROM base WHERE decided_year IS NOT NULL GROUP BY ALL
)
SELECT coalesce(f.state_code, d.state_code) AS state_code, coalesce(f.district, d.district) AS district,
       coalesce(f.court, d.court) AS court, coalesce(f.case_type, d.case_type) AS case_type,
       coalesce(f.yr, d.yr) AS yr, coalesce(f.filed, 0) AS filed, coalesce(d.decided, 0) AS decided
FROM filed f
FULL OUTER JOIN decided d ON f.court = d.court AND f.case_type = d.case_type AND f.yr = d.yr;

-- 2. A dense court x case type x year grid, with the stock pending on 1 January of each year: everything filed
--    before that year minus everything decided before it.
CREATE OR REPLACE TEMP TABLE ct_year AS
WITH keys AS (SELECT DISTINCT state_code, district, court, case_type FROM flow_ct),
grid AS (SELECT k.*, y.yr FROM keys k CROSS JOIN (SELECT unnest(range({first_year}, {last_year} + 1)) AS yr) y),
g AS (
    SELECT g.state_code, g.district, g.court, g.case_type, g.yr,
           coalesce(f.filed, 0) AS filed, coalesce(f.decided, 0) AS decided
    FROM grid g LEFT JOIN flow_ct f ON f.court = g.court AND f.case_type = g.case_type AND f.yr = g.yr
)
SELECT *,
       coalesce(sum(filed - decided) OVER (PARTITION BY court, case_type ORDER BY yr
                                           ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) AS pending_start
FROM g;

-- 3. Disposal rate in a year: decisions dated that year over that year's workload (pending on 1 January plus new
--    filings). The feature for a case filed in Y is the rate of Y-1, so it uses nothing dated in Y or later.
CREATE OR REPLACE TEMP TABLE court_year AS
SELECT state_code, district, court, yr, sum(filed) AS filed, sum(decided) AS decided, sum(pending_start) AS pending_start,
       sum(decided) / nullif(sum(pending_start) + sum(filed), 0) AS disp_rate
FROM ct_year GROUP BY ALL;

CREATE OR REPLACE TEMP TABLE district_year AS
SELECT district, yr, sum(decided) / nullif(sum(pending_start) + sum(filed), 0) AS disp_rate
FROM ct_year GROUP BY ALL;

CREATE OR REPLACE TEMP TABLE state_year AS
SELECT state_code, yr, sum(decided) / nullif(sum(pending_start) + sum(filed), 0) AS disp_rate
FROM ct_year GROUP BY ALL;

CREATE OR REPLACE TEMP TABLE national_year AS
SELECT yr, sum(decided) / nullif(sum(pending_start) + sum(filed), 0) AS disp_rate
FROM ct_year GROUP BY ALL;

-- Court x case type, shrunk towards the court's own rate, so a court with three cases of a type cannot score 0% or 100%.
CREATE OR REPLACE TEMP TABLE court_type_year AS
SELECT t.court, t.case_type, t.yr,
       (t.decided + {shrink_k} * c.disp_rate) / (t.pending_start + t.filed + {shrink_k}) AS disp_rate_shrunk,
       t.filed / nullif(c.filed, 0) AS type_share
FROM ct_year t JOIN court_year c ON c.court = t.court AND c.yr = t.yr;

-- 4. Monthly flows per court, for the stock pending on the first day of the filing month and the decisions in the
--    twelve months before it.
CREATE OR REPLACE TEMP TABLE court_month AS
WITH base AS (
    SELECT l.state_code || '-' || l.dist_code || '-' || l.court_no AS court,
           date_trunc('month', l.date_of_filing)::DATE AS filed_month,
           CASE WHEN l.decision_ok AND l.date_of_decision <= DATE '{t_end}' THEN date_trunc('month', l.date_of_decision)::DATE END AS decided_month
    FROM case_label l WHERE l.filed_ok
), filed AS (SELECT court, filed_month AS m, count(*) AS filed FROM base GROUP BY ALL),
decided AS (SELECT court, decided_month AS m, count(*) AS decided FROM base WHERE decided_month IS NOT NULL GROUP BY ALL),
months AS (SELECT unnest(generate_series(TIMESTAMP '{first_filing}', TIMESTAMP '{t_end}', INTERVAL 1 MONTH))::DATE AS m),
grid AS (SELECT c.court, months.m FROM (SELECT DISTINCT court FROM filed) c CROSS JOIN months),
g AS (
    SELECT grid.court, grid.m, coalesce(f.filed, 0) AS filed, coalesce(d.decided, 0) AS decided
    FROM grid
    LEFT JOIN filed f ON f.court = grid.court AND f.m = grid.m
    LEFT JOIN decided d ON d.court = grid.court AND d.m = grid.m
)
SELECT court, m,
       coalesce(sum(filed - decided) OVER (PARTITION BY court ORDER BY m ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) AS pending_at_month_start,
       coalesce(sum(decided) OVER (PARTITION BY court ORDER BY m ROWS BETWEEN 12 PRECEDING AND 1 PRECEDING), 0) AS decided_prev_12m
FROM g;

-- 5. The court's 730-day disposal rate for the cohort filed three years earlier. A case filed in Y-3 had its window
--    close by the end of Y-1 at the latest, so this rate was fully known before the filing year began.
CREATE OR REPLACE TEMP TABLE court_cohort AS
SELECT state_code || '-' || dist_code || '-' || court_no AS court, year(date_of_filing) AS cohort_year,
       count(*) AS cohort_cases, avg(history_decided_24m) AS cohort_rate
FROM case_label WHERE filed_ok AND eligible_24m GROUP BY ALL;

-- 6. The first year a court files anything in this data. A case's own filing is in the data, so this is never later
--    than the filing year.
CREATE OR REPLACE TEMP TABLE court_first AS
SELECT court, min(yr) AS first_year FROM court_year WHERE filed > 0 GROUP BY 1;

-- 7. Court history as of the test year, for every court and case type the court heard the year before. The dashboard's
--    what-if scores a typical case of each type filed in each court, so it needs no row-level data. Courts in districts
--    flagged for incomplete closure records are left out, as they are from the model.
COPY (
    SELECT c.state_code AS state, c.district, c.court, coalesce(ci.court_level, 'Other or not stated') AS court_level,
           ci.court_name, t.case_type,
           c.disp_rate AS court_disp_rate_py, t.disp_rate_shrunk AS court_type_disp_rate_py,
           dy.disp_rate AS district_disp_rate_py, sy.disp_rate AS state_disp_rate_py, ny.disp_rate AS national_disp_rate_py,
           c.filed AS court_filings_py, t.type_share AS court_type_share_py,
           cc.cohort_rate AS court_cohort_rate_lag3,
           cm.pending_at_month_start AS court_pending_at_filing, cm.decided_prev_12m AS court_decided_prev_12m,
           {test_year} - cf.first_year AS court_years_active
    FROM court_year c
    JOIN court_type_year t ON t.court = c.court AND t.yr = c.yr
    LEFT JOIN court_info ci ON ci.court = c.court
    LEFT JOIN district_year dy ON dy.district = c.district AND dy.yr = c.yr
    LEFT JOIN state_year sy ON sy.state_code = c.state_code AND sy.yr = c.yr
    LEFT JOIN national_year ny ON ny.yr = c.yr
    LEFT JOIN court_cohort cc ON cc.court = c.court AND cc.cohort_year = {test_year} - 3
    LEFT JOIN court_month cm ON cm.court = c.court AND cm.m = DATE '{test_year}-07-01'
    LEFT JOIN court_first cf ON cf.court = c.court
    WHERE c.yr = {test_year} - 1 AND t.type_share > 0 AND c.district NOT IN ({suspect_list})
    ORDER BY c.court, t.case_type
) TO '{whatif_out}' (FORMAT PARQUET, COMPRESSION ZSTD);

-- 8. The sampled cases with their fields known at filing, and three post-filing fields kept apart (prefix leak_)
--    for the leakage test only. src/ml/train.py never selects a leak_ column unless the test asks for it.
COPY (
    WITH x AS (
        SELECT s.ddl_case_id, s.label_24m, s.label_12m, s.duration_days, s.event_by_t_end,
               s.state_code, s.state_code || '-' || s.dist_code AS district,
               s.state_code || '-' || s.dist_code || '-' || s.court_no AS court,
               s.date_of_filing, year(s.date_of_filing) AS filing_year,
               c.year AS file_year, c.type_name, c.purpose_name, c.date_last_list,
               c.female_petitioner, c.female_defendant, c.female_adv_pet, c.female_adv_def
        FROM read_parquet('{sample}') s
        JOIN read_parquet('{cases}') c USING (ddl_case_id)
    )
    SELECT x.ddl_case_id, x.label_24m, x.label_12m, x.duration_days, x.event_by_t_end,
           x.date_of_filing, x.filing_year,
           month(x.date_of_filing) AS filing_month,
           isodow(x.date_of_filing) AS filing_weekday,
           x.state_code AS state, x.district, x.court,
           coalesce(ci.court_level, 'Other or not stated') AS court_level,
           coalesce(t.type_category, 'Other / unmapped') AS case_type,
           coalesce(t.type_label, 'missing') AS case_type_label,
           CASE WHEN a.ddl_case_id IS NULL THEN 'No act record'
                ELSE coalesce(am.act_canonical, 'Blank or unusable label') END AS act,
           CASE WHEN a.ddl_case_id IS NULL THEN 'No act record'
                ELSE coalesce(am.act_canonical, 'Blank or unusable label') || ' s.' || coalesce(nullif(sm.section_norm, ''), 'none') END AS act_section,
           coalesce(a.criminal::VARCHAR, 'missing') AS ddl_criminal_flag,
           CASE x.female_petitioner WHEN 1 THEN 'woman' WHEN 0 THEN 'man' WHEN -9998 THEN 'unclear' ELSE 'missing' END AS petitioner_gender,
           CASE x.female_defendant WHEN 1 THEN 'woman' WHEN 0 THEN 'man' WHEN -9998 THEN 'unclear' ELSE 'missing' END AS defendant_gender,
           CASE x.female_adv_pet WHEN 1 THEN 'woman' WHEN 0 THEN 'man' WHEN -9998 THEN 'unclear' ELSE 'none named' END AS petitioner_advocate,
           -- Court history, all as of the end of the year before filing.
           cy.disp_rate AS court_disp_rate_py,
           cty.disp_rate_shrunk AS court_type_disp_rate_py,
           dy.disp_rate AS district_disp_rate_py,
           sy.disp_rate AS state_disp_rate_py,
           ny.disp_rate AS national_disp_rate_py,
           cy.filed AS court_filings_py,
           cty.type_share AS court_type_share_py,
           cc.cohort_rate AS court_cohort_rate_lag3,
           cc.cohort_cases AS court_cohort_cases_lag3,
           -- Load on the first day of the filing month.
           cm.pending_at_month_start AS court_pending_at_filing,
           cm.decided_prev_12m AS court_decided_prev_12m,
           x.filing_year - cf.first_year AS court_years_active,
           -- Known only after filing. Never a model input except in the leakage test.
           CASE WHEN x.date_last_list BETWEEN x.date_of_filing AND DATE '{collection_end}'
                THEN date_diff('day', x.date_of_filing, x.date_last_list) END AS leak_days_to_last_hearing,
           (x.female_adv_def IS NOT NULL AND x.female_adv_def <> -9999)::TINYINT AS leak_defendant_advocate_named,
           coalesce(pm.stage, 'unknown') AS leak_last_hearing_stage
    FROM x
    LEFT JOIN type_map t ON x.type_name = t.type_name AND x.file_year = t.year
    LEFT JOIN read_parquet('{acts}') a ON a.ddl_case_id = x.ddl_case_id
    LEFT JOIN act_map am ON a.act = am.act
    LEFT JOIN section_map sm ON a.section = sm.section
    LEFT JOIN purpose_map pm ON x.purpose_name = pm.purpose_name AND x.file_year = pm.year
    LEFT JOIN court_info ci ON ci.court = x.court
    LEFT JOIN court_year cy ON cy.court = x.court AND cy.yr = x.filing_year - 1
    LEFT JOIN court_type_year cty ON cty.court = x.court AND cty.case_type = coalesce(t.type_category, 'Other / unmapped')
                                  AND cty.yr = x.filing_year - 1
    LEFT JOIN district_year dy ON dy.district = x.district AND dy.yr = x.filing_year - 1
    LEFT JOIN state_year sy ON sy.state_code = x.state_code AND sy.yr = x.filing_year - 1
    LEFT JOIN national_year ny ON ny.yr = x.filing_year - 1
    LEFT JOIN court_month cm ON cm.court = x.court AND cm.m = date_trunc('month', x.date_of_filing)::DATE
    LEFT JOIN court_cohort cc ON cc.court = x.court AND cc.cohort_year = x.filing_year - 3
    LEFT JOIN court_first cf ON cf.court = x.court
    ORDER BY x.ddl_case_id
) TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD);
