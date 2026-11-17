"""A small synthetic dataset with the same schema as data/parquet, for tests, CI and the fresh-clone check.

The real case data is 81M rows under a non-commercial licence, so CI runs the whole ML pipeline on this instead. It is
not a sample of real cases: every row is simulated. Durations depend on court speed, case type and filing year, so
the models have something to find, and each data-quality problem the label rules handle is planted a few times:
missing filing dates, decisions before filing, decisions dated after collection ended, outcomes without a date, and
one district whose closures go unrecorded.

    python -m src.ml.fixture            writes data/fixture/parquet (the fixture profile's source)
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .settings import load

SEED = 7
YEARS = list(range(2010, 2019))
VOLUME = {2010: 0.45, 2011: 0.55, 2012: 0.65, 2013: 0.75, 2014: 0.85, 2015: 0.92, 2016: 1.0, 2017: 1.05, 2018: 1.1}
CASES_PER_COURT_YEAR = 140
STATES = {"91": ("Fixture State A", 1.0), "92": ("Fixture State B", 0.45), "93": ("Fixture State C", 1.8)}
DISTRICTS = ["North", "South", "East", "West"]
SUSPECT = ("92", "04")  # closures here mostly go unrecorded, as in the districts the real pipeline flags

# label, category, median days, act code, section codes, DDL criminal flag
CASE_TYPES = {
    1: ("bail appl.", "Bail", 12, 2, [11], 1),
    2: ("r.c.c.", "Criminal trial (magistrate)", 700, 1, [4, 5, 6], 1),
    3: ("s.c.", "Sessions trial", 650, 1, [1, 2, 3], 1),
    4: ("o.s.", "Civil suit", 1100, 6, [10], 0),
    5: ("m.a.c.p.", "Motor accident claim", 650, 4, [8], 0),
    6: ("n.i. act case", "Cheque bounce (NI Act)", 800, 3, [7], 0),
    7: ("h.m.a. petition", "Family / matrimonial", 420, 5, [9], 0),
    8: ("darkhast", "Execution", 750, 6, [10], 0),
    9: ("misc. appl.", "Civil misc. / appeal", 450, 7, [13], 0),
    10: ("petty case", "Traffic / petty offence", 30, 4, [12], 1),
}
# court number, establishment name, case types it hears (with weights), relative volume
COURTS = {
    "01": ("District and Sessions Court", {3: 3, 1: 3, 9: 2, 5: 2}, 0.8),
    "02": ("Chief Judicial Magistrate", {2: 5, 1: 2, 6: 3, 10: 2}, 1.4),
    "03": ("Civil Judge Junior Division", {4: 4, 8: 2, 9: 2}, 1.0),
    "04": ("Civil Judge Senior Division", {4: 5, 8: 2}, 0.7),
    "05": ("Family Court", {7: 1}, 0.6),
}
ACTS = {1: ("I.P.C.", "Indian Penal Code", "Penal"), 2: ("Cr.P.C.", "Code of Criminal Procedure", "Criminal procedure"),
        3: ("N.I. Act", "Negotiable Instruments Act", "Commercial"), 4: ("M.V. Act", "Motor Vehicles Act", "Road traffic"),
        5: ("H.M. Act", "Hindu Marriage Act", "Family"), 6: ("C.P.C.", "Code of Civil Procedure", "Civil procedure"),
        7: ("Specific Relief Act", "Specific Relief Act", "Civil and property")}
SECTIONS = {1: "302", 2: "307", 3: "376", 4: "379", 5: "420", 6: "323", 7: "138", 8: "166", 9: "13", 10: "9", 11: "439", 12: "177", 13: "38"}
DISPOSITIONS = {1: ("convicted", "Merits"), 2: ("acquitted", "Merits"), 3: ("disposed", "Generic 'disposed'"),
                4: ("transferred", "Transferred / committed"), 5: ("compromise", "Settled / ADR"),
                6: ("withdrawn", "Withdrawn / lapsed"), 7: ("disposition var missing", "Missing"), 8: ("decided", "Merits")}
PURPOSES = {1: ("evidence", "5 Evidence"), 2: ("summons", "2 Summons / notice / service"), 3: ("judgment", "7 Judgment / orders"),
            4: ("arguments", "6 Arguments"), 5: ("appearance", "3 Appearance of parties"), 6: ("admission", "1 Admission / first hearing")}


def days(d: np.ndarray) -> np.ndarray:
    return np.asarray(d, dtype="int64").astype("timedelta64[D]")


def simulate(rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    seq = 0
    for state, (_, state_speed) in STATES.items():
        for d_idx in range(len(DISTRICTS)):
            dist = f"{d_idx + 1:02d}"
            for court_no, (_, mix, volume) in COURTS.items():
                court_speed = float(np.exp(rng.normal(0, 0.45)))
                drift = float(rng.choice([-0.05, 0.0, 0.04]))  # some courts slow down over the years, some speed up
                collected = np.datetime64("2020-06-30") if rng.random() < 0.15 else np.datetime64("2019-01-20")
                types = np.array(list(mix))
                weights = np.array(list(mix.values()), dtype=float)
                for year in YEARS:
                    n = rng.poisson(CASES_PER_COURT_YEAR * VOLUME[year] * volume)
                    start = np.datetime64(f"{year}-01-01")
                    span = 366 if year % 4 == 0 else 365
                    filed = start + days(rng.integers(0, span, n))
                    ctype = rng.choice(types, n, p=weights / weights.sum())
                    median = np.array([CASE_TYPES[t][2] for t in ctype], dtype=float)
                    speed = state_speed * court_speed * (1 + drift * (year - 2010)) * (1 + 0.04 * (year - 2010))
                    pet = rng.choice([1, 0, -9998, -9999], n, p=[0.25, 0.55, 0.15, 0.05])
                    speed_case = speed * np.where(pet == 1, 0.9, 1.0)
                    dur = np.maximum(0, np.round(median / speed_case * np.exp(rng.normal(0, 1.0, n)))).astype(int)
                    seq_ids = np.arange(seq, seq + n)
                    seq += n
                    rows.append(pd.DataFrame({
                        "seq": seq_ids, "state_code": state, "dist_code": dist, "court_no": court_no, "year": year,
                        "type_code": ctype, "filed": filed, "true_duration": dur, "collected": collected, "female_petitioner": pet,
                    }))
    df = pd.concat(rows, ignore_index=True)
    # Early digital records lean towards long-running cases: quick cases filed in 2010-11 were often never entered.
    early_quick = (df["year"] <= 2011) & (df["true_duration"] < 180) & (rng.random(len(df)) < 0.4)
    return df[~early_quick].reset_index(drop=True)


def build_cases(df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    n = len(df)
    filed = df["filed"].to_numpy().astype("datetime64[D]")
    decision = filed + days(df["true_duration"].to_numpy())
    collected = df["collected"].to_numpy().astype("datetime64[D]")
    decided = decision <= collected
    suspect = (df["state_code"] == SUSPECT[0]) & (df["dist_code"] == SUSPECT[1])
    lost = suspect.to_numpy() & (rng.random(n) < 0.75)  # closure happened but was never recorded
    decided &= ~lost
    dec = np.where(decided, decision, np.datetime64("NaT", "D"))

    # Who appeared. A defendant's advocate is entered once the defendant contests, which is after filing and far more
    # common in long cases: the leakage test uses this column.
    def_adv_named = rng.random(n) < np.where(df["true_duration"].to_numpy() > 400, 0.75, 0.25)
    out = pd.DataFrame({
        "ddl_case_id": [f"{s}-{d}-{c}-{q:08d}-{y}" for s, d, c, q, y in zip(df.state_code, df.dist_code, df.court_no, df.seq, df.year)],
        "year": df["year"].astype("int16"),
        "state_code": df["state_code"], "dist_code": df["dist_code"], "court_no": df["court_no"],
        "judge_position": [COURTS[c][0].lower() for c in df["court_no"]],
        "female_defendant": rng.choice([1, 0, -9998, -9999], n, p=[0.15, 0.6, 0.2, 0.05]).astype("int16"),
        "female_petitioner": df["female_petitioner"].astype("int16"),
        "female_adv_def": np.where(def_adv_named, rng.choice([1, 0], n, p=[0.1, 0.9]), -9999).astype("int16"),
        "female_adv_pet": rng.choice([1, 0, -9999], n, p=[0.1, 0.7, 0.2]).astype("int16"),
        "type_name": df["type_code"].astype("int32"),
    })
    disp = np.where(decided, rng.choice([1, 2, 3, 4, 5, 6, 8], n, p=[0.2, 0.2, 0.2, 0.05, 0.15, 0.1, 0.1]), 7)
    outcome_no_date = ~decided & (rng.random(n) < 0.01)  # rule X04
    disp = np.where(outcome_no_date, 3, disp)
    out["disp_name"] = disp.astype("int32")
    out["purpose_name"] = np.where(decided, 3, rng.choice([1, 2, 4, 5, 6], n)).astype("int32")
    out["date_of_filing"] = filed
    out["date_of_decision"] = dec
    first = filed + days(rng.exponential(30, n).astype(int))
    out["date_first_list"] = np.where(first <= collected, first, np.datetime64("NaT", "D"))
    last_pending = collected - days(rng.integers(0, 400, n))
    last_pending = np.maximum(last_pending, filed)
    out["date_last_list"] = np.where(decided, dec, last_pending)
    out["date_next_list"] = np.where(decided, np.datetime64("NaT", "D"), collected + days(rng.integers(10, 120, n)))
    out["date_parse_failures"] = np.zeros(n, dtype="int8")

    # Planted data-quality problems, each handled by a rule in sql/labels.sql.
    idx = rng.permutation(n)
    no_filing, before, after = idx[:150], idx[150:250], idx[250:300]
    out.loc[no_filing, "date_of_filing"] = pd.NaT  # C01
    out.loc[no_filing, "date_parse_failures"] = 1
    out.loc[before, "date_of_decision"] = out.loc[before, "date_of_filing"] - pd.to_timedelta(rng.integers(1, 300, len(before)), unit="D")  # V01
    out.loc[after, "date_of_decision"] = pd.Timestamp("2031-03-01")  # V03
    for c in ["date_of_filing", "date_of_decision", "date_first_list", "date_last_list", "date_next_list"]:
        out[c] = [v.date() if pd.notna(v) else None for v in pd.to_datetime(out[c])]
    # The real files use 5000-01-01 as a placeholder last-hearing date (rule V09). It is beyond what a nanosecond
    # timestamp can hold, so it must be handled before any date arithmetic in pandas.
    for i in idx[300:340]:
        out.at[i, "date_last_list"] = date(5000, 1, 1)
    return out


def build_acts(cases: pd.DataFrame, df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    n = len(cases)
    # Act records are thin for early filings, as in the real data.
    has_act = rng.random(n) < np.where(df["year"].to_numpy() <= 2012, 0.55, 0.95)
    ctype = df["type_code"].to_numpy()
    act = np.array([CASE_TYPES[t][3] for t in ctype])
    section = np.array([rng.choice(CASE_TYPES[t][4]) for t in ctype])
    criminal = np.array([CASE_TYPES[t][5] for t in ctype])
    acts = pd.DataFrame({
        "ddl_case_id": cases["ddl_case_id"], "act": act.astype("int32"), "section": section.astype("int64"),
        "bailable_ipc": np.where(act == 1, "1", None), "number_sections_ipc": np.where(act == 1, 1, None),
        "criminal": criminal.astype("int8"),
    })[has_act]
    acts["number_sections_ipc"] = acts["number_sections_ipc"].astype("Int16")
    # An act record whose case is not in the case files, as the real acts table has for 2019-20 IDs.
    orphan = pd.DataFrame({"ddl_case_id": ["91-01-01-99999999-2019"], "act": [1], "section": [4], "bailable_ipc": ["1"],
                           "number_sections_ipc": pd.array([1], dtype="Int16"), "criminal": [1]})
    return pd.concat([acts, orphan], ignore_index=True)


def write(table: pd.DataFrame, path: Path, schema: pa.Schema | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pandas(table, schema=schema, preserve_index=False), path)


CASE_SCHEMA = pa.schema([
    ("ddl_case_id", pa.string()), ("year", pa.int16()), ("state_code", pa.string()), ("dist_code", pa.string()),
    ("court_no", pa.string()), ("judge_position", pa.string()), ("female_defendant", pa.int16()),
    ("female_petitioner", pa.int16()), ("female_adv_def", pa.int16()), ("female_adv_pet", pa.int16()),
    ("type_name", pa.int32()), ("purpose_name", pa.int32()), ("disp_name", pa.int32()),
    ("date_of_filing", pa.date32()), ("date_of_decision", pa.date32()), ("date_first_list", pa.date32()),
    ("date_last_list", pa.date32()), ("date_next_list", pa.date32()), ("date_parse_failures", pa.int8()),
])


def generate(out: Path, seed: int = SEED) -> dict:
    rng = np.random.default_rng(seed)
    sim = simulate(rng)
    cases = build_cases(sim, rng)
    cols = [f.name for f in CASE_SCHEMA]
    for year in YEARS:
        write(cases.loc[cases["year"] == year, cols], out / "cases" / f"cases_{year}.parquet", CASE_SCHEMA)
    write(build_acts(cases, sim, rng), out / "acts_sections.parquet", pa.schema([
        ("ddl_case_id", pa.string()), ("act", pa.int32()), ("section", pa.int64()), ("bailable_ipc", pa.string()),
        ("number_sections_ipc", pa.int16()), ("criminal", pa.int8())]))

    # Key and mapping tables, in the shapes pipeline/load.py and pipeline/standardize.py write.
    write(pd.DataFrame({"section_s": list(SECTIONS.values()), "count": "1", "section": [str(k) for k in SECTIONS]}),
          out / "keys" / "section_key.parquet")
    court_rows = []
    for state, (state_name, _) in STATES.items():
        for d_idx, district in enumerate(DISTRICTS):
            for court_no, (name, _, _) in COURTS.items():
                for year in YEARS:
                    court_rows.append({"year": str(year), "state_code": state, "state_name": state_name, "district_name": district,
                                       "dist_code": f"{d_idx + 1:02d}", "court_no": court_no, "court_name": f"{name}, {district}"})
    write(pd.DataFrame(court_rows), out / "keys" / "cases_court_key.parquet")
    year_rows = [(y, code) for y in YEARS for code in CASE_TYPES]
    write(pd.DataFrame({"year": [y for y, _ in year_rows], "type_name": [c for _, c in year_rows],
                        "type_name_s": [CASE_TYPES[c][0] for _, c in year_rows], "count": "1",
                        "type_category": [CASE_TYPES[c][1] for _, c in year_rows]}).astype({"year": "Int64", "type_name": "Int64"}),
          out / "maps" / "map_type.parquet")
    write(pd.DataFrame({"act": list(ACTS), "act_s": [v[0] for v in ACTS.values()], "act_canonical": [v[1] for v in ACTS.values()],
                        "act_family": [v[2] for v in ACTS.values()], "declared_count": 1.0}).astype({"act": "Int64"}),
          out / "maps" / "map_act.parquet")
    disp_rows = [(y, code) for y in YEARS for code in DISPOSITIONS]
    write(pd.DataFrame({"year": [y for y, _ in disp_rows], "disp_name": [c for _, c in disp_rows],
                        "disp_name_s": [DISPOSITIONS[c][0] for _, c in disp_rows], "count": "1",
                        "disp_group": [DISPOSITIONS[c][1] for _, c in disp_rows]}).astype({"year": "Int64", "disp_name": "Int64"}),
          out / "maps" / "map_disp.parquet")
    purpose_rows = [(y, code) for y in YEARS for code in PURPOSES]
    write(pd.DataFrame({"year": [y for y, _ in purpose_rows], "purpose_name": [c for _, c in purpose_rows],
                        "purpose_name_s": [PURPOSES[c][0] for _, c in purpose_rows], "count": "1",
                        "stage": [PURPOSES[c][1] for _, c in purpose_rows]}).astype({"year": "Int64", "purpose_name": "Int64"}),
          out / "maps" / "map_purpose.parquet")
    dims = []
    for state, (state_name, _) in STATES.items():
        for d_idx, district in enumerate(DISTRICTS):
            unit = 9000 + int(state) * 10 + d_idx
            dims.append({"state_code": state, "dist_code": f"{d_idx + 1:02d}", "state_name": state_name, "district_name": district,
                         "pc11_id": unit, "unit_id": unit, "unit_name": district, "population": 1_000_000,
                         "census_state": state_name.upper(), "link_type": "ddl_crosswalk"})
    dim = pd.DataFrame(dims).astype({"pc11_id": "Int64", "unit_id": "Int64"})
    write(dim, out / "maps" / "dim_district.parquet")
    write(pd.DataFrame({"state_code": list(STATES), "state_name": [v[0] for v in STATES.values()], "population": 4_000_000}),
          out / "maps" / "dim_state.parquet")
    flags = dim[["unit_id", "unit_name", "state_name"]].rename(columns={"unit_name": "district", "state_name": "state"})
    flags["suspect_closure_records"] = (dim["state_code"] == SUSPECT[0]) & (dim["dist_code"] == SUSPECT[1])
    flags["low_volume"] = False
    write(flags, out / "q5_districts.parquet")
    return {"cases": int(len(cases)), "courts": len(STATES) * len(DISTRICTS) * len(COURTS)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, help="defaults to the fixture profile's source folder")
    a = ap.parse_args()
    out = a.out or load("fixture").source
    info = generate(out)
    print(f"fixture: {info['cases']:,} simulated cases in {info['courts']} courts -> {out}", flush=True)


if __name__ == "__main__":
    main()
