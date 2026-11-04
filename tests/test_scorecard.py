"""The workbook's Excel formulas must agree with an independent calculation of the same scores in pandas."""
from pathlib import Path

import openpyxl
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
BOOK = ROOT / "outputs" / "data_quality_scorecard.xlsx"
SCORES = ROOT / "data" / "mart" / "dq_state_scores.parquet"

pytestmark = pytest.mark.skipif(not (BOOK.exists() and SCORES.exists()), reason="scorecard not built")


@pytest.fixture(scope="module")
def workbook():
    return openpyxl.load_workbook(BOOK, data_only=True)


def test_no_formula_errors_and_values_are_cached(workbook):
    for ws in workbook.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                assert not (isinstance(cell.value, str) and cell.value.startswith("#")), f"{ws.title}!{cell.coordinate} = {cell.value}"
    assert workbook["Scorecard"]["C5"].value is not None, "recalculate in Excel first so formula values are cached"


def test_excel_scores_match_pandas(workbook):
    ws = workbook["Scorecard"]
    header = [c.value for c in ws[4]]
    expected = pd.read_parquet(SCORES).set_index("state")
    checked = 0
    for row in ws.iter_rows(min_row=5, values_only=True):
        state = row[0]
        if state in expected.index:
            for name in ("Completeness", "Validity", "Consistency", "Uniqueness", "Linkage", "Overall"):
                assert row[header.index(name)] == pytest.approx(expected.loc[state, name], abs=1e-9), f"{state} {name}"
            checked += 1
    assert checked == len(expected)


def test_every_issue_has_evidence_severity_and_status(workbook):
    ws = workbook["Issue log"]
    header = [c.value for c in ws[4]]
    for row in ws.iter_rows(min_row=5, values_only=True):
        name = row[header.index("ID")]
        assert row[header.index("Severity")], name
        assert row[header.index("Status")], name
        assert row[header.index("Evidence or sample records")], f"{name} has no samples or evidence"


def test_rule_totals_match_the_rule_table(workbook):
    ws = workbook["Rules"]
    table = pd.read_csv(ROOT / "data" / "mart" / "dq_rules.csv").set_index("rule_id")
    for row in ws.iter_rows(min_row=5, values_only=True):
        if row[0] in table.index:
            assert row[6] == table.loc[row[0], "failures"], row[0]
