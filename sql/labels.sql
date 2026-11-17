-- Labels for the delay-risk model, defined once. src/ml/dq.py (the audit), src/ml/sample.py and the tests all read
-- the `case_label` view, so they cannot disagree. Python fills the {placeholders} from config.yaml.
-- docs/label_definition.md explains each choice; the numbers it quotes come from reports/label_audit.csv.
--
-- label_24m = 1 when a decision is dated within {horizon} days of filing, 0 when the case was decided later or was
-- still pending at that point. It is only defined (eligible_24m) when the whole window ends by t_end, the observation
-- end, so every label is observed. label_12m is the same with {horizon2} days, as a secondary check.
--
-- Data-quality flags reuse the rules in sql/dq_rules.sql and keep their IDs:
--   C01  filing date missing                       -> excluded: the clock has no start
--   V02  filing date outside 2010-2018             -> excluded (the rule's treatment for durations)
--   V01  decision dated before filing              -> excluded: a negative duration has no meaning
--   V03  decision dated after collection ended     -> excluded: the true date is unknown, so the label is too
--   X04  undecided, but an outcome is recorded     -> kept, labelled pending (0); counted in the label checks
--   X09  closed by transfer or committal           -> kept, labelled decided (1); counted in the label checks
-- A district flagged for incomplete closure records (data/mart/q5_districts) is excluded when the config says so.

CREATE OR REPLACE VIEW case_label AS
WITH disp AS (
    -- One row per code and year, so the join can never add rows.
    SELECT year, disp_name, any_value(disp_group) AS disp_group
    FROM read_parquet('{map_disp}') GROUP BY ALL
), c AS (
    SELECT c.ddl_case_id, c.year, c.state_code, c.dist_code, c.court_no,
           c.date_of_filing, c.date_of_decision, c.type_name,
           coalesce(d.disp_group, 'Missing') AS disp_group
    FROM read_parquet('{cases}') c
    LEFT JOIN disp d ON c.disp_name = d.disp_name AND c.year = d.year
), f AS (
    SELECT *,
           date_of_filing IS NULL AS dq_c01,
           coalesce(date_of_filing NOT BETWEEN DATE '{first_filing}' AND DATE '{last_filing}', FALSE) AS dq_v02,
           coalesce(date_of_decision < date_of_filing, FALSE) AS dq_v01,
           coalesce(date_of_decision > DATE '{collection_end}', FALSE) AS dq_v03,
           date_of_decision IS NULL AND disp_group <> 'Missing' AS dq_x04,
           date_of_decision IS NOT NULL AND disp_group = 'Transferred / committed' AS dq_x09,
           (state_code || '-' || dist_code) IN ({suspect_list}) AS suspect_district
    FROM c
)
SELECT *,
       NOT (dq_c01 OR dq_v02 OR dq_v01 OR dq_v03) AS usable,
       -- Point-in-time views for court history (sql/features.sql). A filing is known when it is filed, so history
       -- counts every case with a valid filing date. A decision counts from its date only when that date is valid.
       -- Filtering history on `usable` instead would use the future: whether a later decision date turns out bogus.
       NOT (dq_c01 OR dq_v02) AS filed_ok,
       NOT (dq_c01 OR dq_v02 OR dq_v01 OR dq_v03) AND date_of_decision IS NOT NULL AS decision_ok,
       coalesce(NOT (dq_c01 OR dq_v02 OR dq_v01 OR dq_v03) AND date_of_decision <= date_of_filing + {horizon}, FALSE)::TINYINT AS history_decided_24m,
       coalesce(date_of_filing + {horizon} <= DATE '{t_end}', FALSE) AS eligible_24m,
       coalesce(date_of_filing + {horizon2} <= DATE '{t_end}', FALSE) AS eligible_12m,
       coalesce(date_of_decision <= date_of_filing + {horizon}, FALSE)::TINYINT AS label_24m,
       coalesce(date_of_decision <= date_of_filing + {horizon2}, FALSE)::TINYINT AS label_12m,
       -- For the Cox model: days to decision, or to t_end for a case still open then (censored).
       CASE WHEN date_of_decision <= DATE '{t_end}' THEN date_diff('day', date_of_filing, date_of_decision)
            ELSE date_diff('day', date_of_filing, DATE '{t_end}') END AS duration_days,
       coalesce(date_of_decision <= DATE '{t_end}', FALSE)::TINYINT AS event_by_t_end
FROM f;
