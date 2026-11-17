"""Step `make data`: make sure the profile's source Parquet exists.

full     Reuses data/parquet when it is already built. Otherwise downloads the DDL archive (5.1 GB stream) if
         data/raw is empty, then runs pipeline/load.py and pipeline/standardize.py, the existing project's loaders.
fixture  Generates the synthetic fixture (src/ml/fixture.py) in a few seconds.
"""
from __future__ import annotations

import subprocess
import sys

from .settings import ROOT, Settings, load

NEEDED = ["cases", "acts_sections.parquet", "keys/section_key.parquet", "keys/cases_court_key.parquet",
          "maps/map_type.parquet", "maps/map_act.parquet", "maps/map_disp.parquet", "maps/map_purpose.parquet",
          "maps/dim_district.parquet", "maps/dim_state.parquet"]


def missing(s: Settings) -> list[str]:
    return [p for p in NEEDED if not (s.source / p).exists()]


def pipeline_step(name: str) -> None:
    print(f"running pipeline/{name}.py", flush=True)
    subprocess.run([sys.executable, "-I", "-u", "-X", "utf8", str(ROOT / "pipeline" / f"{name}.py")], cwd=ROOT, check=True)


def run(s: Settings) -> None:
    if s.profile == "fixture":
        from .fixture import generate
        info = generate(s.source)
        print(f"fixture: {info['cases']:,} simulated cases in {info['courts']} courts", flush=True)
        return
    gaps = missing(s)
    if not gaps:
        print(f"source data present in {s.source}", flush=True)
        return
    if any(p in gaps for p in ("cases", "acts_sections.parquet", "keys/section_key.parquet", "keys/cases_court_key.parquet")):
        if not (ROOT / "data" / "raw" / "ddl" / "manifest.json").exists():
            pipeline_step("download_ddl")
        pipeline_step("load")
    pipeline_step("standardize")
    still = missing(s)
    if still:
        raise SystemExit(f"still missing after the pipeline ran: {still}")


if __name__ == "__main__":
    run(load())
