"""Step 1: stream the DDL archives into typed Parquet.

Case files are extracted one at a time, converted and deleted, so the 15 GB of uncompressed CSV never
sits on disk at once. `cino` is dropped on purpose: it links a row back to a named eCourts record, and
none of this analysis needs that.

Usage:
    python -I -u pipeline/load.py                     # everything
    python -I -u pipeline/load.py --states 01,08      # with WJGS_SCOPE=pilot, a trial on two states
"""
from __future__ import annotations

import argparse
import json
import sys
import tarfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import PARQUET, RAW, TMP, connect  # noqa: E402

CHUNK = 1 << 20
CASE_DATES = ["date_of_filing", "date_of_decision", "date_first_list", "date_last_list", "date_next_list"]
GENDERS = ["female_defendant", "female_petitioner", "female_adv_def", "female_adv_pet"]
KEY_TABLES = {
    "disp_name_key", "type_name_key", "purpose_name_key", "act_key", "section_key",
    "cases_state_key", "cases_district_key", "cases_court_key", "judge_case_merge_key",
}


def stream_member(tf: tarfile.TarFile, member: tarfile.TarInfo, dest: Path) -> int:
    """Extract one tar member and return its data-row count (newlines minus the header)."""
    src = tf.extractfile(member)
    lines = 0
    with open(dest, "wb") as out:
        while chunk := src.read(CHUNK):
            lines += chunk.count(b"\n")
            out.write(chunk)
    return lines - 1


def parquet_info(con, out: Path) -> dict:
    rows = con.execute(f"SELECT count(*) FROM read_parquet('{out.as_posix()}')").fetchone()[0]
    return {"parquet_rows": rows, "parquet_bytes": out.stat().st_size}


def load_cases(con, csv: Path, year: str, states: list[str] | None) -> dict:
    where = f"WHERE state_code IN ({','.join(repr(s) for s in states)})" if states else ""
    # DDL labels some gender columns ("0 male", "-9998 unclear") and leaves others as bare codes.
    genders = ",\n".join(f"TRY_CAST(regexp_extract({c}, '^-?[0-9]+') AS SMALLINT) AS {c}" for c in GENDERS)
    dates = ",\n".join(f"TRY_CAST({c} AS DATE) AS {c}" for c in CASE_DATES)
    bad = " + ".join(
        f"(CASE WHEN {c} IS NOT NULL AND trim({c}) <> '' AND TRY_CAST({c} AS DATE) IS NULL THEN 1 ELSE 0 END)"
        for c in CASE_DATES
    )
    out = PARQUET / "cases" / f"cases_{year}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"""
        COPY (
            SELECT ddl_case_id,
                   TRY_CAST(year AS SMALLINT) AS year,
                   state_code, dist_code, court_no,
                   NULLIF(trim(judge_position), '') AS judge_position,
                   {genders},
                   TRY_CAST(type_name AS INTEGER) AS type_name,
                   TRY_CAST(purpose_name AS INTEGER) AS purpose_name,
                   TRY_CAST(disp_name AS INTEGER) AS disp_name,
                   {dates},
                   ({bad})::TINYINT AS date_parse_failures
            FROM read_csv('{csv.as_posix()}', header=true, all_varchar=true, delim=',', quote='"',
                          parallel=true)
            {where}
        ) TO '{out.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 1000000)
    """)
    return parquet_info(con, out)


def load_plain(con, csv: Path, name: str) -> dict:
    out = PARQUET / "keys" / f"{name}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"""
        COPY (SELECT * FROM read_csv('{csv.as_posix()}', header=true, all_varchar=true, delim=',', quote='"'))
        TO '{out.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """)
    return parquet_info(con, out)


def load_acts(con, csv: Path) -> dict:
    out = PARQUET / "acts_sections.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"""
        COPY (
            SELECT ddl_case_id,
                   TRY_CAST(act AS INTEGER) AS act,
                   TRY_CAST(section AS BIGINT) AS section,
                   bailable_ipc,
                   TRY_CAST(number_sections_ipc AS SMALLINT) AS number_sections_ipc,
                   TRY_CAST(criminal AS TINYINT) AS criminal
            FROM read_csv('{csv.as_posix()}', header=true, all_varchar=true, delim=',', quote='"', parallel=true)
        ) TO '{out.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 1000000)
    """)
    return parquet_info(con, out)


def table_for(name: str) -> str | None:
    stem = Path(name).name.split(".")[0]
    if stem.startswith("cases_") and stem[6:].isdigit():
        return "cases"
    if stem == "acts_sections":
        return "acts"
    if stem in KEY_TABLES or stem == "judges_clean":
        return "plain"
    return None


def output_for(stem: str, kind: str) -> Path:
    if kind == "cases":
        return PARQUET / "cases" / f"{stem}.parquet"
    if kind == "acts":
        return PARQUET / "acts_sections.parquet"
    return PARQUET / "keys" / f"{stem}.parquet"


def run(states: list[str] | None, years: list[str] | None, raw: Path) -> None:
    con = connect()
    TMP.mkdir(parents=True, exist_ok=True)
    PARQUET.mkdir(parents=True, exist_ok=True)
    audit_path = PARQUET / "load_audit.json"
    audit = json.loads(audit_path.read_text()) if audit_path.exists() else {}
    archives = sorted(raw.rglob("*.tar.gz")) + sorted(raw.rglob("*.tar.gz.part"))
    print("sources:", [str(a.relative_to(raw)) for a in archives], flush=True)

    for arc in archives:
        # Reading a tar.gz means decompressing all of it, so skip one whose tables are already built.
        cases_done = arc.name.startswith("cases") and not years and all(
            (PARQUET / "cases" / f"cases_{y}.parquet").exists() for y in range(2010, 2019))
        keys_done = arc.name.startswith("keys") and all((PARQUET / "keys" / f"{k}.parquet").exists() for k in KEY_TABLES)
        if cases_done or keys_done:
            print("already loaded", arc.name, flush=True)
            continue
        print("reading", arc.name, flush=True)
        with tarfile.open(arc, "r|gz") as tf:
            try:
                for m in tf:
                    kind = table_for(m.name)
                    if not m.isfile() or not kind or not m.name.lower().endswith(".csv"):
                        continue
                    stem = Path(m.name).name.split(".")[0]
                    if kind == "cases" and years and stem[6:] not in years:
                        continue
                    if output_for(stem, kind).exists():
                        print("  already loaded", stem, flush=True)
                        continue
                    tmp = TMP / Path(m.name).name
                    t0 = time.time()
                    src_rows = stream_member(tf, m, tmp)
                    if kind == "cases":
                        info = load_cases(con, tmp, stem[6:], states)
                    elif kind == "acts":
                        info = load_acts(con, tmp)
                    else:
                        info = load_plain(con, tmp, stem)
                    tmp.unlink()
                    info |= {"csv_rows": src_rows, "seconds": round(time.time() - t0, 1), "states": states}
                    audit[stem] = info
                    audit_path.write_text(json.dumps(audit, indent=1))
                    print(f"  {stem}: {info['parquet_rows']:,} of {src_rows:,} rows, "
                          f"{info['parquet_bytes'] / 1e6:,.0f} MB, {info['seconds']}s", flush=True)
            except (EOFError, tarfile.ReadError):
                print("  archive still downloading; stopped at the last complete member", flush=True)
    print("audit:", audit_path, flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--states", help="comma-separated DDL state codes, e.g. 01,08")
    ap.add_argument("--years", help="comma-separated years, e.g. 2010,2011")
    ap.add_argument("--raw", type=Path, default=RAW)
    a = ap.parse_args()
    run(a.states.split(",") if a.states else None, a.years.split(",") if a.years else None, a.raw)
