"""Step 3: run the rule catalogue in sql/dq_rules.sql and write results, samples and the issue log.

Outputs in the mart folder
    dq_rules.csv        one row per rule, with national failure counts and rates
    dq_results.parquet  failures and denominators per rule, state and year
    issue_log.csv       every rule that failed, with severity, status, treatment and sample records
"""
from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import MART, PARQUET, SQL, YEARS, connect, pq  # noqa: E402
from standardize import ANALYSIS_CUTOFF, COLLECTION_END  # noqa: E402

SAMPLE_FIELDS = ("ddl_case_id, state_code, year, date_of_filing, date_of_decision, date_first_list, "
                 "date_last_list, date_next_list")


@dataclass
class Rule:
    id: str
    title: str
    dimension: str
    severity: str
    status: str
    treatment: str
    grain: str
    body: str
    applies_to: str = "TRUE"
    sample: str = ""


def parse_rules(path: Path) -> list[Rule]:
    text = path.read_text(encoding="utf8")
    rules = []
    for block in re.split(r"(?m)^(?=-- id: )", text)[1:]:
        meta = dict(re.findall(r"(?m)^-- (\w+): (.*)$", block))
        body = "\n".join(line for line in block.splitlines() if not line.startswith("--")).strip()
        rules.append(Rule(meta["id"], meta["title"], meta["dimension"], meta["severity"], meta["status"],
                          meta["treatment"], meta["grain"], body, meta.get("applies_to", "TRUE"), meta.get("sample", "")))
    return rules


def register_views(con) -> None:
    con.execute(f"CREATE OR REPLACE VIEW cases AS SELECT * FROM read_parquet('{pq('cases/cases_*.parquet')}')")
    con.execute(f"CREATE OR REPLACE VIEW fact AS SELECT * FROM read_parquet('{pq('fact_case/fact_case_*.parquet')}')")
    con.execute(f"CREATE OR REPLACE VIEW map_type AS SELECT * FROM read_parquet('{pq('maps/map_type.parquet')}')")
    con.execute(f"CREATE OR REPLACE VIEW map_purpose AS SELECT * FROM read_parquet('{pq('maps/map_purpose.parquet')}')")
    con.execute(f"CREATE OR REPLACE VIEW map_disp AS SELECT * FROM read_parquet('{pq('maps/map_disp.parquet')}')")
    con.execute(f"CREATE OR REPLACE VIEW map_act AS SELECT * FROM read_parquet('{pq('maps/map_act.parquet')}')")
    con.execute(f"CREATE OR REPLACE VIEW judge_key AS SELECT * FROM read_parquet('{pq('keys/judge_case_merge_key.parquet')}')")
    con.execute(f"CREATE OR REPLACE VIEW dim_district AS SELECT * FROM read_parquet('{pq('maps/dim_district.parquet')}')")
    con.execute(f"CREATE OR REPLACE VIEW cases_state_key AS SELECT * FROM read_parquet('{pq('keys/cases_state_key.parquet')}')")
    con.execute(f"CREATE OR REPLACE VIEW cases_court_key AS SELECT * FROM read_parquet('{pq('keys/cases_court_key.parquet')}')")
    acts = PARQUET / "acts_sections.parquet"
    if acts.exists():
        con.execute(f"CREATE OR REPLACE VIEW acts AS SELECT * FROM read_parquet('{acts.as_posix()}')")
    judges = PARQUET / "keys" / "judges_clean.parquet"
    if judges.exists():
        con.execute(f"""
            CREATE OR REPLACE VIEW judges AS
            SELECT TRY_CAST(ddl_judge_id AS DOUBLE) AS ddl_judge_id, state_code, dist_code, court_no, judge_position,
                   TRY_CAST(female_judge AS INTEGER) AS female_judge,
                   -- The judge table writes dates as DD-MM-YYYY, unlike the case table.
                   TRY_STRPTIME(start_date, '%d-%m-%Y')::DATE AS start_date,
                   TRY_STRPTIME(end_date, '%d-%m-%Y')::DATE AS end_date
            FROM read_parquet('{judges.as_posix()}')
        """)
    con.execute(f"""
        CREATE OR REPLACE VIEW v_dq_case AS
        SELECT c.*, coalesce(d.disp_group, 'Missing') AS disp_group,
               c.date_of_decision IS NOT NULL AS decided,
               DATE '{COLLECTION_END}' AS collection_end,
               DATE '{ANALYSIS_CUTOFF}' AS analysis_cutoff,
               -- Plain dates, because one raw value has a year above two million and cannot become a timestamp.
               (DATE '{COLLECTION_END}' + INTERVAL 5 YEAR)::DATE AS collection_end_plus_5y,
               (DATE '{ANALYSIS_CUTOFF}' - INTERVAL 2 YEAR)::DATE AS cutoff_minus_2y
        FROM cases c LEFT JOIN map_disp d ON c.disp_name = d.disp_name AND c.year = d.year
    """)


def run_case_rules(con, rules: list[Rule]) -> pd.DataFrame:
    selects = []
    for r in rules:
        selects.append(f"count(*) FILTER ({r.applies_to}) AS \"{r.id}__checked\"")
        selects.append(f"count(*) FILTER (({r.body}) AND ({r.applies_to})) AS \"{r.id}__failures\"")
    frames = []
    for year in YEARS:
        t0 = time.time()
        df = con.execute(f"""
            SELECT state_code, year, {', '.join(selects)}
            FROM v_dq_case WHERE year = {year} GROUP BY 1, 2
        """).df()
        frames.append(df)
        print(f"  case rules {year}: {time.time() - t0:.0f}s", flush=True)
    wide = pd.concat(frames, ignore_index=True)
    long = wide.melt(id_vars=["state_code", "year"], var_name="key", value_name="n")
    long[["rule_id", "measure"]] = long["key"].str.split("__", expand=True)
    out = long.pivot_table(index=["rule_id", "state_code", "year"], columns="measure", values="n", aggfunc="sum").reset_index()
    return out[["rule_id", "state_code", "year", "failures", "checked"]]


def run_set_rule(con, rule: Rule) -> pd.DataFrame:
    def execute(sql: str) -> pd.DataFrame:
        return con.execute(sql).df()

    if "{year}" in rule.body or "{cases_year}" in rule.body:
        parts = []
        for year in YEARS:
            sql = rule.body.replace("{year}", str(year)).replace("{cases_year}", pq(f"cases/cases_{year}.parquet"))
            parts.append(execute(sql))
        df = pd.concat(parts, ignore_index=True)
    else:
        df = execute(rule.body)
    df["rule_id"] = rule.id
    return df


def sample_records(con, rule: Rule, top_year: int, n: int = 5) -> str:
    if rule.grain != "case":
        if not rule.sample:
            return ""
        sql = re.sub(r"\{cases_(\d{4})\}", lambda m: pq(f"cases/cases_{m.group(1)}.parquet"), rule.sample)
        return json.dumps(con.execute(sql).df().astype(str).to_dict("records"))
    if top_year is None or pd.isna(top_year):
        return ""
    # Sampled in an outer query, because USING SAMPLE alongside WHERE samples before filtering.
    df = con.execute(f"""
        SELECT * FROM (
            SELECT {SAMPLE_FIELDS}
            FROM v_dq_case
            WHERE year = {int(top_year)} AND ({rule.body}) AND ({rule.applies_to})
        ) USING SAMPLE {n} ROWS (reservoir, 42)
    """).df()
    for c in df.columns:
        if c.startswith("date_"):
            df[c] = df[c].astype(str)
    return json.dumps(df.to_dict("records"))


def run() -> None:
    MART.mkdir(parents=True, exist_ok=True)
    con = connect()
    register_views(con)
    rules = parse_rules(SQL / "dq_rules.sql")
    needs = {"acts": (PARQUET / "acts_sections.parquet").exists(), "judges": (PARQUET / "keys" / "judges_clean.parquet").exists()}
    case_rules = [r for r in rules if r.grain == "case"]
    print(f"{len(rules)} rules: {len(case_rules)} on case rows, {len(rules) - len(case_rules)} on sets", flush=True)
    results = [run_case_rules(con, case_rules)]

    base = con.execute("SELECT state_code, year, count(*) AS n FROM cases GROUP BY 1, 2").df()
    for r in rules:
        if r.grain != "set":
            continue
        uses_acts = re.search(r"\bacts\b", r.body) and not needs["acts"]
        uses_judges = re.search(r"\bjudges\b", r.body) and not needs["judges"]
        if uses_acts or uses_judges:
            print(f"  {r.id}: skipped, its table is not loaded yet", flush=True)
            continue
        t0 = time.time()
        df = run_set_rule(con, r)
        if "checked" not in df.columns:
            # A SELECT returns only the state-years that failed, so the denominator must come from all of them.
            df = base.merge(df, how="outer", on=["state_code", "year"]).rename(columns={"n": "checked"})
            df["failures"] = df["failures"].fillna(0)
            df["checked"] = df["checked"].fillna(0)
            df["rule_id"] = r.id
        results.append(df[["rule_id", "state_code", "year", "failures", "checked"]])
        print(f"  {r.id}: {df['failures'].sum():,.0f} failures, {time.time() - t0:.0f}s", flush=True)

    res = pd.concat(results, ignore_index=True)
    res["failures"] = res["failures"].fillna(0).astype("int64")
    # A clean rule returns no rows from its SELECT, and it still needs a denominator for the national rate.
    catalogue = []
    n_cases = int(base["n"].sum())
    for r in rules:
        sub = res[res.rule_id == r.id]
        ran = not sub.empty or (r.grain == "set" and not (re.search(r"\bacts\b", r.body) and not needs["acts"])
                                and not (re.search(r"\bjudges\b", r.body) and not needs["judges"]))
        failures = int(sub["failures"].sum())
        checked = int(sub["checked"].sum()) or n_cases
        top = sub.sort_values("failures", ascending=False).iloc[0] if failures else None
        catalogue.append({
            "rule_id": r.id, "title": r.title, "dimension": r.dimension, "severity": r.severity, "status": r.status,
            "grain": r.grain, "ran": ran, "failures": failures, "checked": checked,
            "failure_rate": failures / checked if checked else 0.0,
            "worst_state_code": None if top is None else top["state_code"],
            "treatment": r.treatment,
            "sample_records": sample_records(con, r, top["year"] if len(top) and "year" in top else None) if top is not None else "",
        })
    cat = pd.DataFrame(catalogue)
    con.register("res_df", res)
    con.execute(f"COPY res_df TO '{(MART / 'dq_results.parquet').as_posix()}' (FORMAT PARQUET)")
    cat.drop(columns="sample_records").to_csv(MART / "dq_rules.csv", index=False)
    failed = cat[cat.failures > 0].copy()
    failed.insert(0, "issue_id", [f"DQ-{i + 1:03d}" for i in range(len(failed))])
    failed.to_csv(MART / "issue_log.csv", index=False)
    pd.set_option("display.width", 200, "display.max_colwidth", 60, "display.max_rows", 100)
    print(cat[["rule_id", "title", "severity", "ran", "failures", "failure_rate"]].to_string())
    con.close()


if __name__ == "__main__":
    run()
