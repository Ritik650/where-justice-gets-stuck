"""Step 2: build the mapping tables and the analysis table `fact_case`.

Outputs
    map_act, map_purpose, map_type, map_disp   raw label -> standard category, one row per raw label
    dim_state, dim_district                    geography, with the Census 2011 population link
    fact_case/fact_case_YYYY.parquet           one row per case, with the fields every question needs

fact_case deliberately has no case ID. Nothing downstream needs one, and it keeps the table small and
free of anything that identifies a case. Case IDs stay in the raw Parquet for the issue-log samples.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mappings as M  # noqa: E402
from common import EXTERNAL, MART, PARQUET, YEARS, connect, pq  # noqa: E402

# Every case is treated as open on this date unless it was decided by then. Recorded decisions fall by about
# 90% in early 2019 because only some courts were collected again later, so without one shared date those
# courts would look faster than the rest. See docs/methods.md.
ANALYSIS_CUTOFF = "2018-12-31"
# No genuine record can be later than this: the last-hearing dates stop in late 2020.
COLLECTION_END = "2020-12-31"

STATE_DISPLAY = {
    "Orissa": "Odisha",
    "Diu and Daman": "Daman and Diu",
    "DNH at Silvasa": "Dadra and Nagar Haveli",
}
# Mumbai's courts serve the island city and the suburbs together, and DDL has one court district for both,
# so the two census districts are measured as one unit. Otherwise the per-lakh rate would be about 4x too high.
CENSUS_UNIT_MERGE = {518: 519}
# DDL's own crosswalk links Delhi's "South East" to "South West". It was carved out of South.
CROSSWALK_FIXES = {("26", "South East"): "South"}


def build_maps(con) -> None:
    (PARQUET / "maps").mkdir(parents=True, exist_ok=True)
    MART.mkdir(parents=True, exist_ok=True)

    act = con.execute(f"SELECT act, act_s, count FROM read_parquet('{pq('keys/act_key.parquet')}')").df()
    mapped = [M.map_act(x if isinstance(x, str) else None) for x in act["act_s"]]
    act["act_canonical"] = [m[0] for m in mapped]
    act["act_family"] = [m[1] for m in mapped]
    act["act"] = pd.to_numeric(act["act"], errors="coerce").astype("Int64")
    act = act.dropna(subset=["act"])
    act["declared_count"] = pd.to_numeric(act.pop("count"), errors="coerce")
    con.register("act_df", act)
    con.execute(f"COPY act_df TO '{pq('maps/map_act.parquet')}' (FORMAT PARQUET)")

    purpose = con.execute(
        f"SELECT year, purpose_name, purpose_name_s, count FROM read_parquet('{pq('keys/purpose_name_key.parquet')}')"
    ).df()
    purpose["stage"] = [M.map_stage(x if isinstance(x, str) else None) for x in purpose["purpose_name_s"]]
    purpose["year"] = pd.to_numeric(purpose["year"], errors="coerce").astype("Int64")
    purpose["purpose_name"] = pd.to_numeric(purpose["purpose_name"], errors="coerce").astype("Int64")
    purpose = purpose.dropna(subset=["purpose_name", "year"])
    con.register("purpose_df", purpose)
    con.execute(f"COPY purpose_df TO '{pq('maps/map_purpose.parquet')}' (FORMAT PARQUET)")

    typ = con.execute(
        f"SELECT year, type_name, type_name_s, count FROM read_parquet('{pq('keys/type_name_key.parquet')}')"
    ).df()
    typ["type_category"] = [M.map_type(x if isinstance(x, str) else None) for x in typ["type_name_s"]]
    typ["year"] = pd.to_numeric(typ["year"], errors="coerce").astype("Int64")
    typ["type_name"] = pd.to_numeric(typ["type_name"], errors="coerce").astype("Int64")
    typ = typ.dropna(subset=["type_name", "year"])
    con.register("type_df", typ)
    con.execute(f"COPY type_df TO '{pq('maps/map_type.parquet')}' (FORMAT PARQUET)")

    disp = con.execute(
        f"SELECT year, disp_name, disp_name_s, count FROM read_parquet('{pq('keys/disp_name_key.parquet')}')"
    ).df()
    disp["disp_group"] = [M.map_disposition(x if isinstance(x, str) else None) for x in disp["disp_name_s"]]
    disp["year"] = pd.to_numeric(disp["year"], errors="coerce").astype("Int64")
    disp["disp_name"] = pd.to_numeric(disp["disp_name"], errors="coerce").astype("Int64")
    disp = disp.dropna(subset=["disp_name", "year"])
    con.register("disp_df", disp)
    con.execute(f"COPY disp_df TO '{pq('maps/map_disp.parquet')}' (FORMAT PARQUET)")


def build_geography(con) -> None:
    census = pd.read_csv(EXTERNAL / "census2011_districts_raw.csv", dtype=str)
    census = census[["District code", "State name", "District name", "Population"]]
    census.columns = ["pc11_id", "census_state", "census_district", "population"]
    census["pc11_id"] = census["pc11_id"].astype(int)
    census["population"] = census["population"].astype("int64")
    by_name = {(s, d): i for s, d, i in zip(census.census_state, census.census_district, census.pc11_id)}

    key = con.execute(f"SELECT * FROM read_parquet('{pq('keys/cases_district_key.parquet')}')").df()
    # A few codes appear twice with different spellings. The later year's spelling is the corrected one.
    key = key.sort_values("year").drop_duplicates(["state_code", "dist_code"], keep="last")
    key["pc11_id"] = pd.to_numeric(key["pc11_district_id"], errors="coerce").astype("Int64")
    key["link_type"] = key["pc11_id"].map(lambda v: "ddl_crosswalk" if pd.notna(v) else None)

    over = pd.read_csv(EXTERNAL / "district_crosswalk_overrides.csv", dtype=str).fillna("")
    for row in over.itertuples():
        mask = (key.state_code == row.state_code) & (key.dist_code == row.dist_code)
        if not mask.any():
            raise ValueError(f"override refers to an unknown district: {row}")
        key.loc[mask, "link_type"] = row.link_type
        if row.link_type == "non_territorial":
            key.loc[mask, "pc11_id"] = pd.NA
            continue
        code = by_name.get((row.census_state, row.census_district))
        if code is None:
            raise ValueError(f"override names an unknown census district: {row}")
        key.loc[mask, "pc11_id"] = code
    for (state, name), census_name in CROSSWALK_FIXES.items():
        mask = (key.state_code == state) & (key.district_name == name)
        code = census.loc[(census.census_district == census_name) & (census.census_state == "NCT OF DELHI"), "pc11_id"]
        key.loc[mask, "pc11_id"] = int(code.iloc[0])
        key.loc[mask, "link_type"] = "carved_after_2011"

    census["unit_id"] = census["pc11_id"].map(lambda i: CENSUS_UNIT_MERGE.get(i, i))
    units = (
        census.groupby("unit_id")
        .agg(unit_population=("population", "sum"), unit_name=("census_district", "first"),
             census_state=("census_state", "first"))
        .reset_index()
    )
    key["unit_id"] = key["pc11_id"].map(lambda i: CENSUS_UNIT_MERGE.get(int(i), int(i)) if pd.notna(i) else pd.NA)
    key["unit_id"] = key["unit_id"].astype("Int64")
    dim = key.merge(units, how="left", on="unit_id")
    dim = dim[["state_code", "dist_code", "state_name", "district_name", "pc11_id", "unit_id", "unit_name",
               "unit_population", "census_state", "link_type"]]
    dim["state_name"] = dim["state_name"].replace(STATE_DISPLAY)
    dim = dim.rename(columns={"unit_population": "population"})
    con.register("dim_df", dim)
    con.execute(f"COPY dim_df TO '{pq('maps/dim_district.parquet')}' (FORMAT PARQUET)")

    st = con.execute(f"SELECT DISTINCT state_code, state_name FROM read_parquet('{pq('keys/cases_state_key.parquet')}')").df()
    st["state_name"] = st["state_name"].replace(STATE_DISPLAY)
    st = st.drop_duplicates("state_code")
    # State population sums the unique census units reached by the state's DDL districts.
    pop = (dim.dropna(subset=["unit_id"]).drop_duplicates(["state_code", "unit_id"])
           .groupby("state_code")["population"].sum().reset_index())
    st = st.merge(pop, how="left", on="state_code")
    con.register("st_df", st)
    con.execute(f"COPY st_df TO '{pq('maps/dim_state.parquet')}' (FORMAT PARQUET)")
    linked = dim["unit_id"].notna().sum()
    print(f"districts: {len(dim)} in DDL, {linked} linked to a Census 2011 unit, "
          f"{dim['link_type'].eq('non_territorial').sum()} non-territorial; "
          f"{dim['unit_id'].nunique()} of {len(units)} census units reached", flush=True)
    print(dim["link_type"].value_counts().to_string(), flush=True)


def build_fact(con) -> None:
    (PARQUET / "fact_case").mkdir(parents=True, exist_ok=True)
    acts_path = PARQUET / "acts_sections.parquet"
    has_acts = acts_path.exists()
    audit = []
    for year in YEARS:
        src = PARQUET / "cases" / f"cases_{year}.parquet"
        if not src.exists():
            continue
        out = PARQUET / "fact_case" / f"fact_case_{year}.parquet"
        # Join on the full ID. The last four digits of ddl_case_id often differ from the filing year, so
        # they cannot be used to narrow the join: an early version did that and lost about 4M links.
        acts_select = (
            f"(SELECT ddl_case_id, act, section, criminal, 1 AS act_rows FROM read_parquet('{acts_path.as_posix()}'))"
            if has_acts else
            "(SELECT NULL::VARCHAR ddl_case_id, NULL::INT act, NULL::BIGINT section, NULL::TINYINT criminal, 0 act_rows WHERE false)"
        )
        con.execute(f"""
            COPY (
                WITH j AS (
                    SELECT ddl_case_id,
                           TRY_CAST(ddl_filing_judge_id AS DOUBLE) AS filing_judge,
                           TRY_CAST(ddl_decision_judge_id AS DOUBLE) AS decision_judge
                    FROM read_parquet('{pq('keys/judge_case_merge_key.parquet')}')
                )
                SELECT c.year, c.state_code, c.dist_code, c.court_no, c.judge_position,
                       c.date_of_filing, c.date_of_decision, c.date_first_list, c.date_last_list, c.date_next_list,
                       c.female_petitioner, c.female_defendant, c.female_adv_pet, c.female_adv_def,
                       coalesce(t.type_category, '{M.TYPE_OTHER}') AS type_category,
                       coalesce(p.stage, '{M.STAGE_NONE}') AS stage,
                       coalesce(d.disp_group, 'Missing') AS disp_group,
                       lower(trim(d.disp_name_s)) AS disp_label,
                       a.act, a.section, a.criminal,
                       coalesce(ma.act_canonical, CASE WHEN a.act_rows IS NULL THEN 'No act record' ELSE '{M.ACT_BLANK}' END) AS act_canonical,
                       coalesce(ma.act_family, 'Unknown') AS act_family,
                       a.act_rows IS NOT NULL AS has_act_row,
                       j.filing_judge, j.decision_judge,
                       j.ddl_case_id IS NOT NULL AS has_judge_row
                FROM read_parquet('{src.as_posix()}') c
                LEFT JOIN {acts_select} a USING (ddl_case_id)
                LEFT JOIN j USING (ddl_case_id)
                LEFT JOIN read_parquet('{pq('maps/map_type.parquet')}') t ON c.type_name = t.type_name AND c.year = t.year
                LEFT JOIN read_parquet('{pq('maps/map_purpose.parquet')}') p ON c.purpose_name = p.purpose_name AND c.year = p.year
                LEFT JOIN read_parquet('{pq('maps/map_disp.parquet')}') d ON c.disp_name = d.disp_name AND c.year = d.year
                LEFT JOIN read_parquet('{pq('maps/map_act.parquet')}') ma ON a.act = ma.act
            ) TO '{out.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 1000000)
        """)
        rows = con.execute(f"SELECT count(*) FROM read_parquet('{out.as_posix()}')").fetchone()[0]
        src_rows = con.execute(f"SELECT count(*) FROM read_parquet('{src.as_posix()}')").fetchone()[0]
        audit.append((year, src_rows, rows, out.stat().st_size))
        print(f"  fact_case_{year}: {rows:,} rows from {src_rows:,}, {out.stat().st_size / 1e6:,.0f} MB", flush=True)
        if rows != src_rows:
            raise ValueError(f"fact_case_{year} has {rows} rows but the source has {src_rows}: a join fanned out")


if __name__ == "__main__":
    con = connect()
    build_maps(con)
    build_geography(con)
    build_fact(con)
    con.close()
