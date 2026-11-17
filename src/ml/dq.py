"""Step `make dq`: the label, its data-quality exclusions and its checks, with row counts at every step.

Writes to the reports folder:
    observation_end.json   latest dates present, and why T_end is the 2018 cut-off rather than the latest raw date
    decisions_by_month.csv decisions recorded per month around T_end
    window_completeness.csv decisions in the last quarter before T_end against a year earlier, by state
    label_audit.csv        rows remaining after each exclusion, with the rule that removed them
    class_balance.csv      cases and label rates by filing year and state, for both labels
    label_checks.csv       sql/dq_labels.sql: failures per check over the modelling population
"""
from __future__ import annotations

import json
import re
import time

import pandas as pd

from .db import connect, create_label_view, label_params
from .settings import SQL_DIR, Settings, load

POPULATION = "usable AND NOT suspect_district AND eligible_24m"


def parse_checks(text: str) -> list[dict]:
    checks = []
    for block in re.split(r"(?m)^(?=-- id: )", text)[1:]:
        meta = dict(re.findall(r"(?m)^-- (\w+): (.*)$", block))
        body = "\n".join(line for line in block.splitlines() if not line.startswith("--")).strip()
        checks.append({"id": meta["id"], "status": meta["status"], "title": meta["title"], "treatment": meta["treatment"], "body": body})
    return checks


def observation_end(con, s: Settings) -> dict:
    lab = s.cfg["label"]
    row = con.execute(f"""
        SELECT max(date_of_filing)::VARCHAR AS latest_filing,
               max(date_of_decision)::VARCHAR AS latest_decision_raw,
               max(date_of_decision) FILTER (date_of_decision <= DATE '{lab['collection_end']}')::VARCHAR AS latest_decision_plausible,
               count(*) FILTER (date_of_decision > DATE '{lab['collection_end']}') AS decisions_after_collection_end,
               count(*) FILTER (date_of_decision > DATE '{lab['t_end']}' AND date_of_decision <= DATE '{lab['collection_end']}') AS decisions_after_t_end
        FROM case_label
    """).df().iloc[0].to_dict()
    monthly = con.execute(f"""
        SELECT strftime(date_of_decision, '%Y-%m') AS month, count(*) AS decisions
        FROM case_label
        WHERE usable AND date_of_decision BETWEEN DATE '2017-01-01' AND DATE '{lab['collection_end']}'
        GROUP BY 1 ORDER BY 1
    """).df()
    monthly.to_csv(s.reports / "decisions_by_month.csv", index=False)
    by_month = monthly.set_index("month")["decisions"]
    before = by_month[(by_month.index >= "2018-01") & (by_month.index <= "2018-12")]
    after = by_month[(by_month.index >= "2019-04") & (by_month.index <= "2019-12")]
    out = {k: (v.item() if hasattr(v, "item") else v) for k, v in row.items()}  # numpy scalars -> plain Python
    out |= {
        "t_end": lab["t_end"],
        "monthly_decisions_2018_mean": float(before.mean()) if len(before) else None,
        "monthly_decisions_apr_dec_2019_mean": float(after.mean()) if len(after) else None,
    }
    if out["monthly_decisions_2018_mean"] and out["monthly_decisions_apr_dec_2019_mean"] is not None:
        out["drop_after_t_end"] = 1 - out["monthly_decisions_apr_dec_2019_mean"] / out["monthly_decisions_2018_mean"]
    # Was the last stretch before T_end recorded as fully as earlier ones? If a state's courts were collected before
    # the end of 2018, its last-quarter decisions would fall short and some labels near T_end would be wrong.
    completeness = con.execute(f"""
        SELECT state_code,
               count(*) FILTER (date_of_decision BETWEEN DATE '{lab['t_end']}' - INTERVAL 91 DAY AND DATE '{lab['t_end']}') AS last_quarter,
               count(*) FILTER (date_of_decision BETWEEN DATE '{lab['t_end']}' - INTERVAL 456 DAY AND DATE '{lab['t_end']}' - INTERVAL 365 DAY) AS same_quarter_year_before
        FROM case_label WHERE usable GROUP BY 1
    """).df()
    completeness["ratio"] = completeness["last_quarter"] / completeness["same_quarter_year_before"].where(completeness["same_quarter_year_before"] > 0)
    completeness = completeness.merge(state_names(s), how="left", on="state_code").sort_values("ratio")
    completeness.to_csv(s.reports / "window_completeness.csv", index=False)
    big = completeness[completeness["same_quarter_year_before"] >= 10_000]
    out["states_last_quarter_below_80pct"] = big.loc[big["ratio"] < 0.8, "state_name"].dropna().tolist()
    return out


def state_names(s: Settings) -> pd.DataFrame:
    return pd.read_parquet(s.source / "maps" / "dim_state.parquet")[["state_code", "state_name"]].drop_duplicates("state_code")


def audit(con) -> pd.DataFrame:
    steps = [
        ("All cases in the case files", "TRUE", ""),
        ("Filing date present", "NOT dq_c01", "C01"),
        ("Filing date within 2010-2018", "NOT dq_c01 AND NOT dq_v02", "V02"),
        ("Decision not dated before filing", "NOT dq_c01 AND NOT dq_v02 AND NOT dq_v01", "V01"),
        ("Decision not dated after collection ended", "usable", "V03"),
        ("District's closure records complete", "usable AND NOT suspect_district", "q5_districts flag"),
        ("12-month window observed (12-month label)", "usable AND NOT suspect_district AND eligible_12m", "Censoring rule"),
        ("24-month window observed (main label)", POPULATION, "Censoring rule"),
    ]
    sql = ", ".join(f"count(*) FILTER ({cond}) AS s{i}" for i, (_, cond, _) in enumerate(steps))
    counts = con.execute(f"SELECT {sql} FROM case_label").df().iloc[0]
    rows, previous = [], None
    for i, (label, cond, rule) in enumerate(steps):
        n = int(counts[f"s{i}"])
        # The 24-month population is a subset of the 12-month one, so both are measured from the district step.
        base = int(counts["s5"]) if i == 7 else previous
        rows.append({"step": i, "description": label, "rule": rule, "rows": n,
                     "dropped": None if base is None else base - n})
        previous = n
    return pd.DataFrame(rows)


def class_balance(con, s: Settings) -> pd.DataFrame:
    df = con.execute("""
        SELECT year(date_of_filing) AS filing_year, state_code,
               count(*) FILTER (eligible_24m) AS cases_24m,
               avg(label_24m) FILTER (eligible_24m) AS rate_24m,
               count(*) FILTER (eligible_12m) AS cases_12m,
               avg(label_12m) FILTER (eligible_12m) AS rate_12m
        FROM case_label WHERE usable AND NOT suspect_district
        GROUP BY ALL ORDER BY 1, 2
    """).df()
    return df.merge(state_names(s), how="left", on="state_code")


def label_checks(con, s: Settings) -> pd.DataFrame:
    params = label_params(s)
    checks = parse_checks((SQL_DIR / "dq_labels.sql").read_text(encoding="utf8"))
    sql = ", ".join(f"count(*) FILTER (({c['body'].format(**params)})) AS \"{c['id']}\"" for c in checks)
    row = con.execute(f"SELECT count(*) AS checked, {sql} FROM case_label WHERE {POPULATION}").df().iloc[0]
    out = pd.DataFrame([{k: c[k] for k in ("id", "status", "title", "treatment")} | {
        "failures": int(row[c["id"]]), "checked": int(row["checked"]), "rate": int(row[c["id"]]) / max(int(row["checked"]), 1)}
        for c in checks])
    return out


def run(s: Settings) -> dict:
    s.ensure_dirs()
    if not (s.source / "cases").exists():
        raise SystemExit(f"no case files under {s.source}; run `make data` first")
    t0 = time.time()
    con = connect(s)
    create_label_view(con, s)
    end = observation_end(con, s)
    steps = audit(con)
    steps.to_csv(s.reports / "label_audit.csv", index=False)
    balance = class_balance(con, s)
    balance.to_csv(s.reports / "class_balance.csv", index=False)
    checks = label_checks(con, s)
    checks.to_csv(s.reports / "label_checks.csv", index=False)
    con.close()
    (s.reports / "observation_end.json").write_text(json.dumps(end, indent=1, default=str))

    print(steps.to_string(index=False), flush=True)
    print(checks[["id", "status", "failures", "rate", "title"]].to_string(index=False), flush=True)
    broken = checks[(checks["status"] == "Invariant") & (checks["failures"] > 0)]
    if len(broken):
        raise SystemExit(f"label invariants failed: {broken['id'].tolist()}")
    by_year = balance.groupby("filing_year").apply(
        lambda g: pd.Series({"cases": g["cases_24m"].sum(),
                             "rate_24m": (g["rate_24m"] * g["cases_24m"]).sum() / max(g["cases_24m"].sum(), 1)}),
        include_groups=False)
    print(by_year.to_string(), flush=True)
    print(f"observation end: {json.dumps(end, default=str)}", flush=True)
    print(f"dq done in {time.time() - t0:.0f}s", flush=True)
    return {"steps": steps, "checks": checks, "observation_end": end}


if __name__ == "__main__":
    run(load())
