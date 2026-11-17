"""A fixture build reproduces the recorded results, and its report is complete.

CI runs `make all PROFILE=fixture` before the tests; locally this skips until that has run. After a deliberate change
that moves the numbers, record them again with `python -m src.ml.golden --write` and commit the file.
"""
import json

import pytest

from src.ml.golden import EXACT, EXPECTED, TOLERANCE, current
from src.ml.settings import load

FIXTURE = load("fixture")
built = pytest.mark.skipif(not FIXTURE.results_path.exists(), reason="fixture not built; run `make all PROFILE=fixture`")


@built
def test_fixture_build_matches_the_recorded_results():
    want = json.loads(EXPECTED.read_text())
    got = current()
    for key, value in want.items():
        if key in EXACT:
            assert got[key] == value, f"{key}: {got[key]} != {value}"
        else:
            assert abs(got[key] - value) <= TOLERANCE, f"{key}: {got[key]} vs {value}"


@built
def test_fixture_report_has_every_section_and_figure():
    text = (FIXTURE.reports / "ml_poc_report.md").read_text(encoding="utf8")
    for heading in ["## Question", "## The answer", "## Data", "## Label", "## Features", "## Splits", "## Models",
                    "## Results", "## Slices", "## Error analysis", "## Findings", "## Limitations", "## Next steps"]:
        assert heading in text, heading
    for name in ["test_auc", "auc_gap", "calibration", "class_balance", "importance", "seen_vs_unseen", "state_slices"]:
        assert (FIXTURE.figures_dir / f"{name}.png").exists(), name


@built
def test_every_logged_run_has_versions_and_runtime():
    import pandas as pd
    exp = pd.read_csv(FIXTURE.experiments_path)
    assert {"final", "grid", "experiment", "evaluation"} <= set(exp["stage"])
    for column in ["run_id", "feature_version", "split_version", "config_hash", "runtime_s", "params"]:
        assert exp[column].notna().all(), column
    grid = exp[exp["stage"] == "grid"]
    assert grid["test_auc"].isna().all(), "grid candidates must never be scored on the test set"


@built
def test_whatif_scores_every_court_on_a_case_mix_and_checks_itself():
    import pandas as pd
    wi = pd.read_parquet(FIXTURE.mart / "ml_whatif.parquet")
    assert len(wi) and wi["p_model"].between(0, 1).all()
    assert set(wi["case_mix"]) <= {"state", "national"}
    floor = FIXTURE.cfg["whatif"]["observed_min_cases"]
    assert wi.loc[wi["test_cases"] < floor, ["observed_rate", "mean_p_actual_cases"]].isna().all().all(), "small groups stay unpublished"
    check = json.loads(FIXTURE.results_path.read_text())["whatif_check"]
    assert check["groups"] == int((wi["test_cases"] >= floor).sum())
