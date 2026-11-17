"""Step 1 of `make features`: a stratified sample of the modelling population, saved as Parquet.

Strata are state x filing year, with proportional allocation: every stratum keeps round(n x fraction) cases, so the
sample has the population's mix of states and years exactly, not just on average.

Which cases are kept depends only on a hash of the case ID and the seed: each case gets u = md5(id:seed) / 2^128, and
a stratum keeps its lowest values of u. The draw is therefore the same on any machine, thread count or DuckDB version,
and changing the seed gives an independent sample.
"""
from __future__ import annotations

import hashlib
import json
import time

import pandas as pd

from .db import connect, create_label_view
from .dq import POPULATION
from .settings import Settings, load

KEEP = ("ddl_case_id, year, state_code, dist_code, court_no, date_of_filing, date_of_decision, label_24m, label_12m, "
        "duration_days, event_by_t_end, disp_group, dq_x04, dq_x09")


def id_hash(ids: pd.Series) -> str:
    """Fingerprint of a set of case IDs, order-independent. Logged with every run to prove rows are identical."""
    h = hashlib.sha256()
    for i in sorted(ids):
        h.update(i.encode())
        h.update(b"\n")
    return h.hexdigest()[:16]


def run(s: Settings) -> dict:
    s.ensure_dirs()
    t0 = time.time()
    con = connect(s)
    create_label_view(con, s)
    population = con.execute(f"SELECT count(*) FROM case_label WHERE {POPULATION}").fetchone()[0]
    fraction = min(1.0, s.sample_size / population)
    out = s.sample_path
    con.execute(f"""
        COPY (
            WITH pop AS (
                SELECT {KEEP}, md5_number(ddl_case_id || ':{s.seed}')::DOUBLE / 3.402823669209385e38 AS u
                FROM case_label WHERE {POPULATION}
            ), strata AS (
                SELECT state_code, year, count(*) AS n, round(count(*) * {fraction})::BIGINT AS take
                FROM pop GROUP BY ALL
            ), candidates AS (
                -- Over-draw slightly, then keep exactly `take` per stratum, lowest u first.
                SELECT p.*, s.take FROM pop p JOIN strata s USING (state_code, year)
                WHERE p.u < least(1.0, {fraction} * 1.1 + 50.0 / s.n)
            ), ranked AS (
                SELECT *, row_number() OVER (PARTITION BY state_code, year ORDER BY u, ddl_case_id) AS rk FROM candidates
            )
            SELECT * EXCLUDE (take, rk) FROM ranked WHERE rk <= take ORDER BY ddl_case_id
        ) TO '{out.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """)
    strata = con.execute(f"""
        WITH pop AS (SELECT state_code, year, count(*) AS population FROM case_label WHERE {POPULATION} GROUP BY ALL),
             smp AS (SELECT state_code, year, count(*) AS sampled FROM read_parquet('{out.as_posix()}') GROUP BY ALL)
        SELECT p.state_code, p.year, p.population, coalesce(m.sampled, 0) AS sampled,
               round(p.population * {fraction})::BIGINT AS target
        FROM pop p LEFT JOIN smp m USING (state_code, year) ORDER BY 1, 2
    """).df()
    ids = con.execute(f"SELECT ddl_case_id FROM read_parquet('{out.as_posix()}')").df()["ddl_case_id"]
    con.close()
    short = strata[strata["sampled"] != strata["target"]]
    if len(short):
        raise SystemExit(f"{len(short)} strata missed their target size:\n{short.to_string()}")
    strata.to_csv(s.reports / "sample_strata.csv", index=False)
    info = {"population": int(population), "sampled": int(len(ids)), "fraction": fraction, "seed": s.seed,
            "strata": int(len(strata)), "id_hash": id_hash(ids), "seconds": round(time.time() - t0, 1)}
    (s.reports / "sample_summary.json").write_text(json.dumps(info, indent=1))
    print(f"sample: {info}", flush=True)
    return info


if __name__ == "__main__":
    run(load())
