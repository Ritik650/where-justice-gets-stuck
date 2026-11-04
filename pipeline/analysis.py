"""Step 4: answer the seven questions and write small aggregate tables to the mart folder.

Everything here reads fact_case, and everything written is aggregated, so the dashboard and the brief need
no row-level data. Each q*() function is one question from the project plan.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import EXTERNAL, MART, PARQUET, connect, pq  # noqa: E402
from km import summarise  # noqa: E402
from standardize import ANALYSIS_CUTOFF, COLLECTION_END  # noqa: E402

CUTOFF = f"DATE '{ANALYSIS_CUTOFF}'"
END = f"DATE '{COLLECTION_END}'"
CUTOFF_MINUS_2Y = f"(DATE '{ANALYSIS_CUTOFF}' - INTERVAL 2 YEAR)::DATE"  # a date, not a timestamp: raw years reach 2,016,310
GRID = np.arange(0, 3301, 30)  # curve points every 30 days, up to about nine years
RECENT = (2016, 2017, 2018)  # the years with the fullest coverage, used for flow rates
MIN_STRATUM = 30  # smallest group in a paired comparison
BAIL_MIN_CASES = 100  # a district needs this many bail matters for the records check to apply
BAIL_MIN_CLOSED = 0.5  # share of bail matters closed within two years, below which closure records look incomplete

# Benchmarks quoted for question 3, with where each comes from.
SC_138_PENDING = 3_516_000  # In Re: Expeditious Trial of Cases under s.138 NI Act, SC, 16 Apr 2021, as on 31 Dec 2019
BLOG_138_PENDING = 5_400_000  # eCourtsIndia blog, full-text index, Oct 2026, includes appeals and revisions


def save(df: pd.DataFrame, name: str) -> pd.DataFrame:
    MART.mkdir(parents=True, exist_ok=True)
    df.to_parquet(MART / f"{name}.parquet", index=False)
    print(f"  {name}: {len(df):,} rows", flush=True)
    return df


def base_view(con) -> None:
    """One definition of 'closed', 'open' and 'duration', used by every question."""
    con.execute(f"CREATE OR REPLACE VIEW dim_district AS SELECT * FROM read_parquet('{pq('maps/dim_district.parquet')}')")
    con.execute(f"CREATE OR REPLACE VIEW dim_state AS SELECT * FROM read_parquet('{pq('maps/dim_state.parquet')}')")
    con.execute(f"""
        CREATE OR REPLACE VIEW base AS
        WITH f AS (
            SELECT *,
                   -- A usable clock: filed, and not closed before filing or after collection ended.
                   date_of_filing IS NOT NULL
                       AND coalesce(date_of_decision >= date_of_filing, TRUE)
                       AND coalesce(date_of_decision <= {END}, TRUE) AS usable,
                   -- Case category: the act overrides the label where the act is more specific.
                   CASE WHEN act_canonical = 'Negotiable Instruments Act' THEN 'Cheque bounce (NI Act)'
                        WHEN act_canonical = 'Motor Vehicles Act' AND type_category <> 'Motor accident claim'
                             THEN 'Traffic / petty offence'
                        ELSE type_category END AS case_category,
                   -- DDL's own `criminal` flag marks cheque-bounce, traffic and excise prosecutions as
                   -- non-criminal, so the family comes from the act, then from the case-type label.
                   CASE WHEN act_family IN ('Penal', 'Criminal procedure', 'Special criminal', 'Excise and liquor',
                                            'Regulatory offences')
                             OR act_canonical = 'Negotiable Instruments Act' THEN 'Criminal'
                        WHEN act_family = 'Road traffic'
                             THEN CASE WHEN type_category = 'Motor accident claim' THEN 'Civil' ELSE 'Criminal' END
                        WHEN act_family IN ('Civil procedure', 'Family', 'Civil and property', 'Labour', 'Commercial',
                                            'Evidence and limitation') THEN 'Civil'
                        WHEN type_category IN ('Bail', 'Traffic / petty offence', 'Sessions trial',
                                               'Criminal misc. / appeal', 'Criminal trial (magistrate)') THEN 'Criminal'
                        WHEN type_category IN ('Motor accident claim', 'Family / matrimonial', 'Execution', 'Civil suit',
                                               'Civil misc. / appeal') THEN 'Civil'
                        ELSE 'Unknown' END AS case_family
            FROM read_parquet('{pq('fact_case/fact_case_*.parquet')}')
        )
        SELECT *,
               usable AND date_of_decision IS NOT NULL AND date_of_decision <= {CUTOFF} AS closed,
               date_of_decision IS NULL AS never_decided,
               CASE WHEN usable AND date_of_decision IS NOT NULL AND date_of_decision <= {CUTOFF}
                    THEN date_diff('day', date_of_filing, date_of_decision)
                    ELSE date_diff('day', date_of_filing, {CUTOFF}) END AS t_days
        FROM f
    """)


def km_counts(con, group_sql: str, where: str = "TRUE", event: str = "closed") -> pd.DataFrame:
    return con.execute(f"""
        SELECT {group_sql} AS grp, t_days AS t,
               count(*) FILTER ({event})::BIGINT AS d,
               count(*) FILTER (NOT ({event}))::BIGINT AS c
        FROM base WHERE usable AND ({where}) GROUP BY 1, 2
    """).df()


def run_km(con, group_sql: str, where: str = "TRUE", event: str = "closed", group_col: str = "grp"):
    df = km_counts(con, group_sql, where, event).rename(columns={"grp": group_col})
    return summarise(df, group_col, GRID)


def state_names(con) -> dict[str, str]:
    return dict(con.execute("SELECT state_code, state_name FROM dim_state").fetchall())


def headline(con) -> dict:
    row = con.execute(f"""
        SELECT count(*) AS total_rows,
               count(*) FILTER (usable) AS usable_rows,
               count(*) FILTER (NOT usable) AS unusable_rows,
               count(*) FILTER (closed) AS closed_by_cutoff,
               count(*) FILTER (usable AND NOT closed) AS open_at_cutoff,
               count(*) FILTER (never_decided) AS never_decided,
               count(*) FILTER (date_of_decision > {CUTOFF} AND date_of_decision <= {END}) AS decided_after_cutoff
        FROM base
    """).df().iloc[0].to_dict()
    return {k: int(v) for k, v in row.items()}


def q1_stages(con) -> None:
    print("Q1 where cases get stuck", flush=True)
    stale = f"date_last_list < {CUTOFF_MINUS_2Y}"
    select = f"""
        count(*) AS stuck_cases,
        count(*) FILTER (date_of_filing < {CUTOFF_MINUS_2Y}) AS filed_2y_before_cutoff,
        count(*) FILTER (date_of_filing < {CUTOFF_MINUS_2Y} AND {stale}) AS stale_2y,
        median(date_diff('day', date_of_filing, {CUTOFF})) AS median_age_days
    """
    nat = con.execute(f"SELECT stage, {select} FROM base WHERE never_decided AND usable GROUP BY 1").df()
    nat["share"] = nat["stuck_cases"] / nat["stuck_cases"].sum()
    nat["stale_share"] = nat["stale_2y"] / nat["filed_2y_before_cutoff"].replace(0, np.nan)
    save(nat.sort_values("stage"), "q1_stage")
    fam = con.execute("""
        SELECT case_family AS family, stage, count(*) AS stuck_cases
        FROM base WHERE never_decided AND usable GROUP BY 1, 2
    """).df()
    save(fam, "q1_stage_family")
    st = con.execute("SELECT state_code, stage, count(*) AS stuck_cases FROM base WHERE never_decided AND usable GROUP BY 1, 2").df()
    st["state"] = st["state_code"].map(state_names(con))
    save(st, "q1_stage_state")


def q2_survival(con) -> None:
    print("Q2 how long justice takes", flush=True)
    summaries, curves = [], []
    groups = {
        "All cases": ("'All cases'", "TRUE"),
        "Case category": ("case_category", "TRUE"),
        "Family": ("case_family", "TRUE"),
        "Filing year": ("year::VARCHAR", "TRUE"),
        "State": ("state_code", "TRUE"),
    }
    names = state_names(con)
    for label, (expr, where) in groups.items():
        s, c = run_km(con, expr, where)
        if label == "State":
            s["grp"] = s["grp"].map(names)
            c["grp"] = c["grp"].map(names)
        s.insert(0, "dimension", label)
        c.insert(0, "dimension", label)
        summaries.append(s)
        curves.append(c)

    # The naive answer, to show how far it misses: durations of closed cases only.
    naive = []
    for label, (expr, where) in groups.items():
        df = con.execute(f"""
            SELECT {expr} AS grp, median(t_days) AS naive_median_days, avg(t_days) AS naive_mean_days
            FROM base WHERE usable AND closed AND ({where}) GROUP BY 1
        """).df()
        if label == "State":
            df["grp"] = df["grp"].map(names)
        df.insert(0, "dimension", label)
        naive.append(df)
    summary = pd.concat(summaries).merge(pd.concat(naive), how="left", on=["dimension", "grp"])
    save(summary, "q2_km_summary")
    save(pd.concat(curves), "q2_km_curves")

    # Sensitivity: a transfer moves a file and does not resolve the dispute, so count those as still open.
    s, c = run_km(con, "'Transfers not counted as closure'", "TRUE", "closed AND disp_group <> 'Transferred / committed'")
    s2, c2 = run_km(con, "'All closures'", "TRUE")
    save(pd.concat([s, s2]), "q2_sensitivity_transfer")
    save(pd.concat([c, c2]), "q2_sensitivity_transfer_curves")


def q3_laws(con) -> dict:
    print("Q3 which laws clog the system", flush=True)
    s, _ = run_km(con, "act_canonical")
    open_counts = con.execute("""
        SELECT act_canonical AS grp, any_value(act_family) AS act_family,
               count(*) FILTER (usable AND NOT closed) AS open_at_cutoff,
               median(t_days) FILTER (usable AND closed) AS naive_median_days
        FROM base GROUP BY 1
    """).df()
    acts = s.merge(open_counts, on="grp").rename(columns={"grp": "act_canonical"})
    acts["share_of_cases"] = acts["n"] / acts["n"].sum()
    acts["share_of_open"] = acts["open_at_cutoff"] / acts["open_at_cutoff"].sum()
    save(acts.sort_values("n", ascending=False), "q3_acts")

    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE map_section AS
        SELECT TRY_CAST(section AS BIGINT) AS section, section_s,
               upper(regexp_extract(section_s, '[0-9]+[A-Za-z]?')) AS section_norm
        FROM read_parquet('{pq('keys/section_key.parquet')}')
    """)
    top_sections = con.execute("""
        WITH x AS (
            SELECT b.act_canonical, m.section_norm, b.t_days, b.closed, b.usable
            FROM base b JOIN map_section m USING (section)
            WHERE b.act_canonical IN ('Indian Penal Code', 'Negotiable Instruments Act', 'Motor Vehicles Act',
                                      'Code of Criminal Procedure', 'Hindu Marriage Act', 'Code of Civil Procedure')
              AND m.section_norm <> ''
        )
        SELECT act_canonical, section_norm, count(*) AS n,
               count(*) FILTER (usable AND NOT closed) AS open_at_cutoff,
               median(t_days) FILTER (usable AND closed) AS naive_median_days
        FROM x GROUP BY 1, 2 HAVING count(*) >= 20000
        ORDER BY n DESC
    """).df()
    save(top_sections, "q3_sections")

    ni = con.execute("""
        SELECT count(*) AS ni_cases,
               count(*) FILTER (usable AND NOT closed) AS ni_open_at_cutoff,
               count(*) FILTER (never_decided) AS ni_never_decided,
               count(*) FILTER (usable AND NOT closed AND m.section_norm = '138') AS ni_open_section_138,
               count(*) FILTER (m.section_norm = '138') AS ni_section_138
        FROM base b LEFT JOIN map_section m USING (section)
        WHERE b.act_canonical = 'Negotiable Instruments Act'
    """).df().iloc[0].to_dict()
    criminal_open = con.execute("SELECT count(*) FROM base WHERE usable AND NOT closed AND case_family = 'Criminal'").fetchone()[0]
    # Act records cover about half of early filings, so also count cases whose type label says NI Act.
    ni_any_open = con.execute("""
        SELECT count(*) FROM base
        WHERE usable AND NOT closed AND (act_canonical = 'Negotiable Instruments Act' OR type_category = 'Cheque bounce (NI Act)')
    """).fetchone()[0]
    all_open = con.execute("SELECT count(*) FROM base WHERE usable AND NOT closed").fetchone()[0]
    test = {k: int(v) for k, v in ni.items()} | {
        "criminal_open_at_cutoff": int(criminal_open), "all_open_at_cutoff": int(all_open),
        "ni_open_act_or_type": int(ni_any_open),
        "supreme_court_benchmark": SC_138_PENDING, "blog_benchmark": BLOG_138_PENDING,
    }
    save(pd.DataFrame([test]), "q3_section_138_test")
    return test


def judges_view(con) -> bool:
    path = PARQUET / "keys" / "judges_clean.parquet"
    if not path.exists():
        return False
    con.execute(f"""
        CREATE OR REPLACE VIEW judges AS
        WITH j AS (
            SELECT TRY_CAST(ddl_judge_id AS DOUBLE) AS ddl_judge_id,
                   -- The judge table writes dates as DD-MM-YYYY, unlike the case table.
                   TRY_STRPTIME(start_date, '%d-%m-%Y')::DATE AS start_date,
                   TRY_STRPTIME(end_date, '%d-%m-%Y')::DATE AS end_date
            FROM read_parquet('{path.as_posix()}')
        )
        SELECT * FROM j WHERE end_date >= start_date
    """)
    return True


def q4_judges(con) -> None:
    print("Q4 do judge transfers slow cases", flush=True)
    if con.execute("SELECT count(*) FROM base WHERE has_judge_row").fetchone()[0] == 0:
        print("  no judge links loaded", flush=True)
        return
    # Step 1, the plain comparison: closed cases that kept or changed their judge. It is biased, because a
    # slow case has more time in which to see a transfer, so slowness can cause the change.
    con.execute("""
        CREATE OR REPLACE VIEW judge_closed AS
        SELECT state_code, dist_code, year, case_category, t_days,
               filing_judge <> decision_judge AS changed
        FROM base
        WHERE usable AND closed AND has_judge_row AND decision_judge IS NOT NULL AND filing_judge IS NOT NULL
    """)
    overall = con.execute("""
        SELECT changed, count(*) AS n,
               quantile_cont(t_days, 0.25) AS q1, median(t_days) AS median_days, quantile_cont(t_days, 0.75) AS q3
        FROM judge_closed GROUP BY 1
    """).df()
    save(overall, "q4_overall")
    # Step 2, paired: the same district, case category and filing year, so the mix cannot explain the gap.
    pairs = con.execute(f"""
        WITH s AS (
            SELECT state_code, dist_code, year, case_category, changed, count(*) AS n, median(t_days) AS med
            FROM judge_closed GROUP BY ALL
        )
        SELECT a.state_code, a.dist_code, a.year, a.case_category,
               a.med AS median_same, b.med AS median_changed, a.n AS n_same, b.n AS n_changed,
               b.med - a.med AS gap_days
        FROM s a JOIN s b USING (state_code, dist_code, year, case_category)
        WHERE NOT a.changed AND b.changed AND a.n >= {MIN_STRATUM} AND b.n >= {MIN_STRATUM}
    """).df()
    save(pairs, "q4_pairs")
    # Step 3, the fairer test: judge's remaining time at filing, which a slow case cannot influence.
    # Compare by share closed within two years, counting every linked case, open ones included.
    if not judges_view(con):
        print("  judge table not loaded; skipped the tenure test", flush=True)
        return
    tenure = con.execute(f"""
        WITH x AS (
            SELECT b.state_code, b.dist_code, b.year, b.case_category,
                   date_diff('day', b.date_of_filing, j.end_date) AS remaining,
                   b.closed AND b.t_days <= 730 AS closed_2y
            FROM base b JOIN judges j ON b.filing_judge = j.ddl_judge_id
            WHERE b.usable AND b.has_judge_row AND b.year <= 2016
              AND b.date_of_filing BETWEEN j.start_date AND j.end_date
              -- A tenure still running when the data was collected is not a transfer.
              AND j.end_date < DATE '2018-06-30'
        ), y AS (
            SELECT *, CASE WHEN remaining <= 180 THEN 'Judge leaves within 6 months'
                           WHEN remaining >= 730 THEN 'Judge stays 2+ years' END AS exposure
            FROM x WHERE remaining <= 180 OR remaining >= 730
        ), s AS (
            SELECT state_code, dist_code, year, case_category, exposure, count(*) AS n, avg(closed_2y::INT) AS closed_2y
            FROM y GROUP BY ALL
        )
        SELECT a.state_code, a.dist_code, a.year, a.case_category,
               a.n AS n_stays, b.n AS n_leaves, a.closed_2y AS closed_2y_stays, b.closed_2y AS closed_2y_leaves,
               b.closed_2y - a.closed_2y AS gap
        FROM s a JOIN s b USING (state_code, dist_code, year, case_category)
        WHERE a.exposure = 'Judge stays 2+ years' AND b.exposure = 'Judge leaves within 6 months'
          AND a.n >= {MIN_STRATUM} AND b.n >= {MIN_STRATUM}
    """).df()
    save(tenure, "q4_tenure_pairs")
    if len(tenure):
        w = tenure["n_leaves"] + tenure["n_stays"]
        print(f"  tenure test: {len(tenure):,} strata, weighted gap {np.average(tenure['gap'], weights=w):+.3f}", flush=True)


def q5_districts(con) -> None:
    print("Q5 does your district decide your speed", flush=True)
    years = ", ".join(str(y) for y in RECENT)
    # A view, because a table would copy all 81M rows to disk.
    con.execute("""
        CREATE OR REPLACE VIEW district_base AS
        SELECT b.*, d.unit_id, d.unit_name, d.population, d.state_name
        FROM base b JOIN dim_district d USING (state_code, dist_code)
    """)
    units = con.execute(f"""
        SELECT unit_id, any_value(unit_name) AS district, any_value(state_name) AS state, any_value(population) AS population,
               count(*) AS total_cases,
               count(*) FILTER (year IN ({years})) AS filed_recent,
               count(*) FILTER (usable AND closed AND year(date_of_decision) IN ({years})) AS closed_recent,
               count(*) FILTER (usable AND NOT closed) AS open_at_cutoff,
               count(*) FILTER (date_last_list < {CUTOFF_MINUS_2Y} AND never_decided AND usable) AS stale_open
        FROM district_base WHERE unit_id IS NOT NULL GROUP BY 1
    """).df()
    units["filed_per_lakh_year"] = units["filed_recent"] / len(RECENT) / units["population"] * 100_000
    units["open_per_lakh"] = units["open_at_cutoff"] / units["population"] * 100_000
    units["clearance_rate"] = units["closed_recent"] / units["filed_recent"].replace(0, np.nan)

    counts = con.execute("""
        SELECT unit_id AS grp, t_days AS t, count(*) FILTER (closed)::BIGINT AS d, count(*) FILTER (NOT closed)::BIGINT AS c
        FROM district_base WHERE usable AND unit_id IS NOT NULL GROUP BY 1, 2
    """).df()
    s, _ = summarise(counts, "grp", np.array([0]))
    units = units.merge(s[["grp", "km_median_days", "open_after_3y"]], left_on="unit_id", right_on="grp", how="left").drop(columns="grp")

    # Case mix: a district heavy with bail or traffic matters looks fast for no good reason, so the
    # two-year closure share is reweighted to the national mix of categories.
    mix = con.execute("""
        SELECT unit_id, case_category, count(*) AS n, avg((closed AND t_days <= 730)::INT) AS closed_2y
        FROM district_base WHERE usable AND unit_id IS NOT NULL AND year <= 2016 GROUP BY 1, 2
    """).df()
    national = mix.groupby("case_category")["n"].sum() / mix["n"].sum()
    mix["w"] = mix["case_category"].map(national)
    adj = (mix.assign(x=mix["closed_2y"] * mix["w"]).groupby("unit_id")
           .agg(x=("x", "sum"), w=("w", "sum")).assign(closed_2y_adjusted=lambda d: d["x"] / d["w"])[["closed_2y_adjusted"]])
    raw = mix.groupby("unit_id").apply(lambda g: np.average(g["closed_2y"], weights=g["n"]), include_groups=False).rename("closed_2y_raw")
    units = units.merge(adj, left_on="unit_id", right_index=True, how="left").merge(raw, left_on="unit_id", right_index=True, how="left")
    units["low_volume"] = units["filed_recent"] < 3000
    # Bail normally closes within days, so a district where most bail matters never close within two years
    # has a records problem, not a speed problem. Ranking such a district as "slow" would be a false finding.
    bail = mix[mix["case_category"] == "Bail"][["unit_id", "n", "closed_2y"]].rename(columns={"n": "bail_n", "closed_2y": "bail_closed_2y"})
    units = units.merge(bail, how="left", on="unit_id")
    bail_fails = (units["bail_n"].fillna(0) >= BAIL_MIN_CASES) & (units["bail_closed_2y"] < BAIL_MIN_CLOSED)
    units["suspect_closure_records"] = ~units["low_volume"] & (bail_fails | (units["closed_2y_raw"] < 0.02))
    save(units, "q5_districts")
    con.register("suspect_units_df", units.loc[units["suspect_closure_records"], ["unit_id"]])
    con.execute("CREATE OR REPLACE TEMP TABLE suspect_units AS SELECT unit_id FROM suspect_units_df")

    # How much those districts move each affected state's median.
    affected = units.loc[units["suspect_closure_records"], "state"].unique().tolist()
    if affected:
        codes = con.execute("SELECT state_code, state_name FROM dim_state").df()
        codes = codes[codes["state_name"].isin(affected)]["state_code"].tolist()
        in_list = ", ".join(f"'{c}'" for c in codes)
        counts = con.execute(f"""
            SELECT state_name AS grp, t_days AS t, count(*) FILTER (closed)::BIGINT AS d, count(*) FILTER (NOT closed)::BIGINT AS c
            FROM district_base
            WHERE usable AND state_code IN ({in_list}) AND (unit_id IS NULL OR unit_id NOT IN (SELECT unit_id FROM suspect_units))
            GROUP BY 1, 2
        """).df()
        excl, _ = summarise(counts, "grp", np.array([0]))
        save(excl[["grp", "n", "closed", "km_median_days", "open_after_3y", "open_after_5y"]], "q5_state_excluding_flagged")


def q6_women(con) -> None:
    print("Q6 how visible women are", flush=True)
    roles = {"Petitioner": "female_petitioner", "Defendant": "female_defendant",
             "Petitioner's advocate": "female_adv_pet", "Defendant's advocate": "female_adv_def"}
    frames = {"state": [], "category": [], "year": []}
    dims = {"state": "state_code", "category": "case_category", "year": "year"}
    for role, col in roles.items():
        for key, dim in dims.items():
            df = con.execute(f"""
                SELECT {dim} AS grp,
                       count(*) AS total,
                       count(*) FILTER ({col} IN (0, 1)) AS classified,
                       count(*) FILTER ({col} = 1) AS women
                FROM base GROUP BY 1
            """).df()
            df.insert(0, "role", role)
            frames[key].append(df)
    names = state_names(con)
    for key, parts in frames.items():
        df = pd.concat(parts, ignore_index=True)
        df["women_share"] = df["women"] / df["classified"].replace(0, np.nan)
        df["classified_share"] = df["classified"] / df["total"]
        if key == "state":
            df["grp"] = df["grp"].map(names)
        save(df, f"q6_women_{key}")


OUTCOME_GROUP = """
    CASE disp_group WHEN 'Merits' THEN 'Decided on merits'
                    WHEN 'Admission / plea' THEN 'Plea or admission'
                    WHEN 'Settled / ADR' THEN 'Settled or Lok Adalat'
                    WHEN 'Withdrawn / lapsed' THEN 'Withdrawn or lapsed'
                    WHEN 'Transferred / committed' THEN 'Transferred or committed'
                    ELSE 'Vague or missing label' END
"""
CONVICTED = "('convicted', 'fine', 'plead guilty', 'confession', 'plea bargaining', 'probation', 'prison')"


def q8_outcomes(con) -> None:
    print("Q8 how cases end", flush=True)
    names = state_names(con)
    dims = {"All cases": "'All cases'", "Family": "case_family", "Case category": "case_category", "State": "state_code"}
    frames = []
    for label, expr in dims.items():
        df = con.execute(f"""
            SELECT {expr} AS grp, {OUTCOME_GROUP} AS outcome, count(*) AS closed_cases, median(t_days) AS median_days
            FROM base WHERE usable AND closed GROUP BY 1, 2
        """).df()
        if label == "State":
            df["grp"] = df["grp"].map(names)
        df.insert(0, "dimension", label)
        df["share"] = df["closed_cases"] / df.groupby("grp")["closed_cases"].transform("sum")
        frames.append(df)
    save(pd.concat(frames, ignore_index=True), "q8_outcomes")

    # Verdicts in criminal cases: convictions (including pleas and fines) against acquittals.
    frames = []
    for label, expr in {"All criminal": "'All criminal'", "Case category": "case_category", "State": "state_code"}.items():
        df = con.execute(f"""
            SELECT {expr} AS grp, count(*) AS closed_cases,
                   count(*) FILTER (disp_label IN {CONVICTED}) AS convicted,
                   count(*) FILTER (disp_label = 'acquitted') AS acquitted
            FROM base WHERE usable AND closed AND case_family = 'Criminal' GROUP BY 1
        """).df()
        if label == "State":
            df["grp"] = df["grp"].map(names)
        df.insert(0, "dimension", label)
        decided = df["convicted"] + df["acquitted"]
        df["conviction_share"] = df["convicted"] / decided.replace(0, np.nan)
        df["verdict_share"] = decided / df["closed_cases"]
        frames.append(df)
    save(pd.concat(frames, ignore_index=True), "q8_verdicts")


def q9_first_hearing(con) -> None:
    print("Q9 time to first hearing", flush=True)
    names = state_names(con)
    valid = f"""usable AND date_first_list IS NOT NULL AND date_first_list >= date_of_filing AND date_first_list <= {END}"""
    frames = []
    for label, expr in {"All cases": "'All cases'", "Case category": "case_category", "State": "state_code"}.items():
        df = con.execute(f"""
            WITH x AS (SELECT {expr} AS grp, date_diff('day', date_of_filing, date_first_list) AS lag FROM base WHERE {valid})
            SELECT grp, count(*) AS n, median(lag) AS median_days, quantile_cont(lag, 0.9) AS p90_days,
                   avg((lag <= 30)::INT) AS within_30_days
            FROM x GROUP BY 1
        """).df()
        if label == "State":
            df["grp"] = df["grp"].map(names)
        df.insert(0, "dimension", label)
        frames.append(df)
    save(pd.concat(frames, ignore_index=True), "q9_first_hearing")


def q4_judge_tenure(con) -> None:
    """How long a judge stays in one post. A posting still running counts as censored, so it is not dropped."""
    print("Q4 extra: how long judges stay in a post", flush=True)
    path = PARQUET / "keys" / "judges_clean.parquet"
    if not path.exists():
        return
    names = state_names(con)
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE postings AS
        SELECT lpad(state_code, 2, '0') AS state_code,
               TRY_STRPTIME(start_date, '%d-%m-%Y')::DATE AS started,
               TRY_STRPTIME(end_date, '%d-%m-%Y')::DATE AS ended
        FROM read_parquet('{path.as_posix()}')
    """)
    frames = []
    for label, expr in {"All India": "'All India'", "State": "state_code"}.items():
        counts = con.execute(f"""
            SELECT {expr} AS grp,
                   date_diff('day', started, coalesce(ended, {CUTOFF})) AS t,
                   count(*) FILTER (ended IS NOT NULL)::BIGINT AS d,
                   count(*) FILTER (ended IS NULL)::BIGINT AS c
            FROM postings
            WHERE started IS NOT NULL AND coalesce(ended, {CUTOFF}) >= started
            GROUP BY 1, 2
        """).df()
        summary, _ = summarise(counts, "grp", np.array([0]))
        if label == "State":
            summary["grp"] = summary["grp"].map(names)
        summary.insert(0, "dimension", label)
        frames.append(summary.rename(columns={"n": "postings", "closed": "ended"})[["dimension", "grp", "postings", "ended", "km_median_days"]])
    save(pd.concat(frames, ignore_index=True), "q4_judge_tenure")


def state_acts(con) -> None:
    print("State profile: largest acts", flush=True)
    df = con.execute("""
        WITH x AS (
            SELECT s.state_name AS state, b.act_canonical, count(*) AS n, count(*) FILTER (b.usable AND NOT b.closed) AS open_at_cutoff
            FROM base b JOIN dim_state s USING (state_code) GROUP BY 1, 2
        )
        SELECT * FROM x QUALIFY row_number() OVER (PARTITION BY state ORDER BY open_at_cutoff DESC) <= 12
    """).df()
    save(df, "state_acts")


def njdg_table() -> pd.DataFrame:
    return pd.read_csv(EXTERNAL / "njdg_state_pendency_2026-07-30.csv")


# DDL state -> NJDG state. DDL lists Daman & Diu and Dadra & Nagar Haveli apart, while NJDG merges them.
NJDG_NAME = {"Daman and Diu": "The Dadra and Nagar Haveli and Daman and Diu",
             "Dadra and Nagar Haveli": "The Dadra and Nagar Haveli and Daman and Diu"}


def q7_backlog(con) -> None:
    print("Q7 when would the backlog clear", flush=True)
    years = ", ".join(str(y) for y in RECENT)
    st = con.execute(f"""
        SELECT s.state_name AS state,
               count(*) FILTER (b.year IN ({years})) / {len(RECENT)}.0 AS filed_per_year,
               count(*) FILTER (b.closed AND year(b.date_of_decision) IN ({years})) / {len(RECENT)}.0 AS closed_per_year,
               count(*) FILTER (b.usable AND NOT b.closed) AS open_at_cutoff
        FROM base b JOIN dim_state s USING (state_code) GROUP BY 1
    """).df()
    st["njdg_state"] = st["state"].map(lambda s: NJDG_NAME.get(s, s))
    st = (st.groupby("njdg_state", as_index=False)
          .agg(filed_per_year=("filed_per_year", "sum"), closed_per_year=("closed_per_year", "sum"),
               open_at_cutoff=("open_at_cutoff", "sum")))
    njdg = njdg_table().rename(columns={"state": "njdg_state"})
    out = njdg.merge(st, how="outer", on="njdg_state")
    out["in_ddl"] = out["filed_per_year"].notna()
    out["net_per_year"] = out["closed_per_year"] - out["filed_per_year"]
    out["clearance_rate"] = out["closed_per_year"] / out["filed_per_year"]
    clears = out["net_per_year"] > 0
    out["never_clears"] = out["in_ddl"] & ~clears
    out["years_to_clear_ddl_stock"] = np.where(clears, out["open_at_cutoff"] / out["net_per_year"], np.nan)
    out["years_to_clear_njdg_stock"] = np.where(clears, out["pending_total"] / out["net_per_year"], np.nan)
    # Robust companion: if filings stopped today, how many years of disposals is the 2026 stock?
    out["years_of_disposals_njdg_stock"] = out["pending_total"] / out["closed_per_year"]
    save(out, "q7_backlog")


def coverage(con) -> None:
    print("Coverage check", flush=True)
    sy = con.execute("""
        SELECT s.state_name AS state, b.year, count(*) AS filed
        FROM base b JOIN dim_state s USING (state_code) GROUP BY 1, 2
    """).df()
    save(sy, "coverage_state_year")
    pivot = sy.pivot_table(index="state", columns="year", values="filed", aggfunc="sum").fillna(0)
    ratio = (pivot[2010] / pivot[2018].replace(0, np.nan)).rename("filed_2010_vs_2018").reset_index()
    njdg = njdg_table().rename(columns={"state": "njdg_state"})
    opens = con.execute("""
        SELECT s.state_name AS state, count(*) FILTER (b.usable AND NOT b.closed) AS ddl_open
        FROM base b JOIN dim_state s USING (state_code) GROUP BY 1
    """).df()
    opens["njdg_state"] = opens["state"].map(lambda s: NJDG_NAME.get(s, s))
    grouped = opens.groupby("njdg_state", as_index=False)["ddl_open"].sum()
    comp = njdg.merge(grouped, how="outer", on="njdg_state")
    comp["ddl_open_share"] = comp["ddl_open"] / comp["ddl_open"].sum()
    comp["njdg_pending_share"] = comp["pending_total"] / comp["pending_total"].sum()
    comp["share_gap_points"] = (comp["ddl_open_share"] - comp["njdg_pending_share"]) * 100
    comp["status"] = np.where(comp["ddl_open"].isna(), "Not in DDL data",
                              np.where(comp["pending_total"].isna(), "Not in NJDG table", "Both"))
    save(comp, "coverage_vs_njdg")
    save(ratio, "coverage_2010_vs_2018")
    # An independent check: states that look slow here should also hold the oldest cases in NJDG's 2026 table.
    age = njdg_table()
    age["old_share"] = (age["pending_over_10y"] + age["pending_5_to_10y"]) / age["pending_total"]
    km, _ = run_km(con, "state_code")
    km["state"] = km["grp"].map(state_names(con))
    age = age.merge(km[["state", "n", "km_median_days", "open_after_5y"]], on="state")
    save(age[["state", "n", "old_share", "km_median_days", "open_after_5y"]], "coverage_age_check")
    monthly = con.execute("""
        SELECT strftime(date_of_decision, '%Y-%m') AS month, count(*) AS decisions
        FROM base WHERE date_of_decision BETWEEN DATE '2017-01-01' AND DATE '2021-03-31' GROUP BY 1 ORDER BY 1
    """).df()
    save(monthly, "coverage_decisions_by_month")


def run() -> None:
    con = connect()
    base_view(con)
    MART.mkdir(parents=True, exist_ok=True)
    head = headline(con)
    print(head, flush=True)
    save(pd.DataFrame([head]), "headline")
    q1_stages(con)
    q2_survival(con)
    q3_laws(con)
    q4_judges(con)
    q5_districts(con)
    q6_women(con)
    q7_backlog(con)
    q8_outcomes(con)
    q9_first_hearing(con)
    q4_judge_tenure(con)
    state_acts(con)
    coverage(con)
    con.close()


if __name__ == "__main__":
    run()
