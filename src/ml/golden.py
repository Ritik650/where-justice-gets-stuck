"""The numbers a fixture build must reproduce, and how to record them after a deliberate change.

    python -m src.ml.golden          print the current fixture build's numbers
    python -m src.ml.golden --write  save them to tests/fixtures/fixture_expected.json (commit the file)

tests/test_ml_reproduce.py compares a fresh `make all PROFILE=fixture` with that file: fingerprints must match
exactly (same sample, same splits, same features), and model metrics within a small tolerance, because LightGBM and
lifelines can differ in the last digits between operating systems.
"""
from __future__ import annotations

import argparse
import json

import pandas as pd

from .settings import ROOT, load

EXPECTED = ROOT / "tests" / "fixtures" / "fixture_expected.json"
EXACT = ["sample_id_hash", "split_version", "feature_version", "population", "sampled"]
TOLERANCE = 0.01


def current() -> dict:
    s = load("fixture")
    res = json.loads(s.results_path.read_text())
    sample = json.loads((s.reports / "sample_summary.json").read_text())
    audit = pd.read_csv(s.reports / "label_audit.csv")
    out = {
        "sample_id_hash": sample["id_hash"], "split_version": res["split_version"], "feature_version": res["feature_version"],
        "population": int(audit["rows"].iloc[-1]), "sampled": int(sample["sampled"]),
    }
    for key in ("b0", "b1", "b2", "m1", "m2", "m3"):
        out[f"test_auc_{key}"] = round(res["test"][key]["roc_auc"], 4)
    out["test_brier_m2_cal"] = round(res["test"]["m2_cal"]["brier"], 4)
    out["auc_gap_m2_vs_b1"] = round(res["gaps"]["m2_vs_b1_case"]["gap"], 4)
    out["unseen_auc_m2"] = round(res["test_unseen"]["m2"]["roc_auc"], 4)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true")
    values = current()
    if ap.parse_args().write:
        EXPECTED.parent.mkdir(parents=True, exist_ok=True)
        EXPECTED.write_text(json.dumps(values, indent=1) + "\n")
        print(f"wrote {EXPECTED}", flush=True)
    print(json.dumps(values, indent=1), flush=True)


if __name__ == "__main__":
    main()
