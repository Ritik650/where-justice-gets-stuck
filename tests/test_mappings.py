"""Standardisation rules, using labels copied from the real key tables."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import mappings as M  # noqa: E402


@pytest.mark.parametrize("label", ["IPC", "I.P.C.", "Indian Penal Code", "The Indian Penal Code", "I.P.C(Police)", "ipc"])
def test_plan_examples_all_map_to_ipc(label):
    assert M.map_act(label)[0] == "Indian Penal Code"


@pytest.mark.parametrize("label,expected", [
    ("Cr. P.C.  \\", "Code of Criminal Procedure"),
    ("CodeofCivilProcedure", "Code of Civil Procedure"),
    ("CODE OF CIVIL PROCEDURE, 1908 (HB)", "Code of Civil Procedure"),
    ("Motor Vehicle Act  \\", "Motor Vehicles Act"),
    ("MotorVehiclesAct", "Motor Vehicles Act"),
    ("NEGOTIABLE INSTRUMENTS ACT, 1881", "Negotiable Instruments Act"),
    ("Negotiable Instrument Act", "Negotiable Instruments Act"),
    ("GUJARAT (BOMBAY) PROHIBITION ACT, 1949", "State Prohibition Acts"),
    ("Protection of Women from Domestic Violence Act", "Protection of Women from Domestic Violence Act"),
    ("Dowry Prohibition Act", "Dowry Prohibition Act"),  # must not fall into the liquor prohibition rule
    ("Abkari Act", "State Excise / Abkari Acts"),
    ("KP Act", "Police Acts"),
    ("RPC", "Ranbir Penal Code (J&K)"),
    # Regression: a loose "nact$" once sent every name ending in "-ion act" to the NI Act.
    ("Land Acquisition Act", "Land Acquisition Act"),
    ("Consumer Protection Act", "Consumer Protection Act"),
    ("Prevention of Corruption Act", "Prevention of Corruption Act"),
    ("Bombay Prohibition Act, 1949", "State Prohibition Acts"),
    ("Prohibition of Child Marriage Act", "Child Marriage Act"),
    ("N.I. Act", "Negotiable Instruments Act"),
    ("NI ACT", "Negotiable Instruments Act"),
    ("138 N.I.Act", "Negotiable Instruments Act"),
    ("U/S 138 of N.I Act", "Negotiable Instruments Act"),
    # Regression: a section reference at the start once hid a real act name.
    ("u/sec 372 Indian Succession Act", "Succession Acts"),
    ("U/sec. 29 Rule 24ii Kar. Shops and Com. Est. Act", "Labour Laws"),
    # Regression: names that merely contain a keyword.
    ("Juvenile Justice (Care and Protection of Children) Act", "Juvenile Justice Act"),
    ("Life Insurance Corporation Act", "Other / unmapped"),
    ("Indecent Representation Of Women (Prohibition) Act", "Other / unmapped"),
    ("THE RAJASTHAN PROHIBITION OF SMOKING AND NON SMOKERS HEALTH PROTECTION ACT.", "Tobacco Control Act (COTPA)"),
    # Regression: a loose "rent" matched words such as "parent" and "current".
    ("Rent Control Act", "Rent Control / Tenancy Acts"),
    ("Maintenance and Welfare of Parents and Senior Citizens Act", "Maintenance and Welfare of Parents Act"),
])
def test_act_variants(label, expected):
    assert M.map_act(label)[0] == expected


@pytest.mark.parametrize("label", [None, "", ".", "'", "''", "U/s", "U/Sec", "Under", "Under Section", "Sec.", "ALL"])
def test_labels_that_are_not_act_names(label):
    assert M.map_act(label)[0] == M.ACT_BLANK


@pytest.mark.parametrize("label", ["Absorbed Areas (Laws) Act", "Acquired Territories (Merger) Act"])
def test_implausible_acts_are_flagged_not_forced(label):
    assert M.map_act(label)[0] == M.ACT_IMPLAUSIBLE_NAME


def test_unknown_acts_stay_unmapped():
    assert M.map_act("Some Unheard Of Act 1999")[0] == M.ACT_OTHER


@pytest.mark.parametrize("label,expected", [
    ("evidence", "5 Evidence"),
    ("Evidence", "5 Evidence"),
    ("argument", "6 Arguments"),
    ("summons", "2 Summons / notice / service"),
    ("notice_unready", "2 Summons / notice / service"),
    ("notice (unready)", "2 Summons / notice / service"),
    ("n.b.w._unready", "2 Summons / notice / service"),
    ("appereance", "3 Appearance of parties"),
    ("appearance of accused/ surety", "3 Appearance of parties"),
    ("framing of charge or  plea", "4 Pleadings / charge"),
    ("written statement", "4 Pleadings / charge"),
    ("judgement", "7 Judgment / orders"),
    ("referred to lokadalat", "9 Lok Adalat / settlement"),
    ("not heard cases", M.STAGE_NONE),
    ("no sitting notified", M.STAGE_NONE),
    ("", M.STAGE_NONE),
    (None, M.STAGE_NONE),
])
def test_stages(label, expected):
    assert M.map_stage(label) == expected


def test_every_stage_rule_is_in_the_display_order():
    assert {name for name, _ in M.STAGE_RULES} <= set(M.STAGE_ORDER)


@pytest.mark.parametrize("label,expected", [
    ("bail application", "Bail"),
    ("cri.bail appln.", "Bail"),
    ("original suit", "Civil suit"),
    ("o.s.", "Civil suit"),
    ("m.v.c.", "Motor accident claim"),
    ("mcop", "Motor accident claim"),
    ("nact", "Cheque bounce (NI Act)"),
    ("sc nia", "Cheque bounce (NI Act)"),
    ("exe", "Execution"),
    ("reg dkst", "Execution"),
    ("c.c.", "Criminal trial (magistrate)"),
    ("criminal case", "Criminal trial (magistrate)"),
])
def test_case_types(label, expected):
    assert M.map_type(label) == expected


@pytest.mark.parametrize("label,expected", [
    ("transferred", "Transferred / committed"),
    ("committed", "Transferred / committed"),
    ("disposed", "Generic 'disposed'"),
    ("acquitted", "Merits"),
    ("referred to lok adalat", "Settled / ADR"),
    ("disposition var missing", "Missing"),
    (None, "Missing"),
])
def test_dispositions(label, expected):
    assert M.map_disposition(label) == expected
