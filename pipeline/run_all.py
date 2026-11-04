"""Run the whole project in order.

    python -I pipeline/run_all.py                       everything, on all 81M rows (about 10 minutes after download)
    python -I pipeline/run_all.py --skip-download       when data/raw already holds the archives
    python -I pipeline/run_all.py --pilot 01,08         a trial on two states, written to separate folders

State codes are DDL's: 01 Maharashtra, 08 Bihar, 13 Uttar Pradesh, and so on (see cases_state_key).
Pilot output goes to data/parquet_pilot, data/mart_pilot and outputs_pilot, and never touches the real deliverables.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STEPS = ["load", "standardize", "analysis", "model", "quality", "export_maps", "findings", "scorecard", "recalc_excel", "brief", "write_readme"]


def step(name: str, *args: str, env: dict | None = None) -> None:
    print(f"\n=== {name} ===", flush=True)
    t0 = time.time()
    subprocess.run([sys.executable, "-I", "-u", "-X", "utf8", str(ROOT / "pipeline" / f"{name}.py"), *args], cwd=ROOT, env=env, check=True)
    print(f"--- {name}: {time.time() - t0:.0f}s", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pilot", metavar="STATES", help="comma-separated DDL state codes for a trial run")
    ap.add_argument("--skip-download", action="store_true")
    a = ap.parse_args()
    env = dict(os.environ)
    if a.pilot:
        env["WJGS_SCOPE"] = "pilot"
    # Parquet holds everything the later steps need, so the raw archives are only fetched when it is missing.
    have_parquet = (ROOT / "data" / "parquet" / "cases").exists() and not a.pilot
    have_raw = (ROOT / "data" / "raw" / "ddl" / "manifest.json").exists()
    if not a.skip_download and not have_parquet and not have_raw:
        step("download_ddl")
    for name in STEPS:
        extra = ["--states", a.pilot] if a.pilot and name == "load" else []
        step(name, *extra, env=env)
    print("\nDone. To open the dashboard: streamlit run dashboard/app.py --server.address 127.0.0.1", flush=True)


if __name__ == "__main__":
    main()
