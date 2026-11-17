"""`make clean-ml`: delete the profile's row-level ML files (sample, features, splits, predictions, models).

Only the profile's `work` folder is removed, and only if it sits inside data/. Reports and source data are kept.
"""
from __future__ import annotations

import shutil

from .settings import ROOT, load


def run() -> None:
    s = load()
    work = s.work.resolve()
    data = (ROOT / "data").resolve()
    if data not in work.parents:
        raise SystemExit(f"refusing to delete {work}: not inside {data}")
    if work.exists():
        shutil.rmtree(work)
        print(f"removed {work}", flush=True)
    else:
        print(f"nothing to remove at {work}", flush=True)


if __name__ == "__main__":
    run()
