"""Turn the mart tables into the numbers and sentences used by the dashboard, the brief and the README.

Nothing downstream types a figure by hand: change the data and every sentence changes with it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import MART  # noqa: E402

NJDG_TOTAL = 49_911_920  # Lok Sabha Q.3371, Annexure II, as on 30 Jul 2026
NJDG_NATIONAL_JUL28 = 49_916_653  # NJDG figure as on 28 Jul 2026, reported by Kashmir Life
NJDG_2025 = 47_657_328  # NJDG figure for 2025, same report
JUDGES_SANCTIONED = 30_825  # judicial officers, sanctioned strength on 30 Jun 2026, Lok Sabha Q.3371
JUDGES_WORKING = 21_411  # judicial officers, working strength on the same date and from the same reply
PRETRIAL = ("1 Admission / first hearing", "2 Summons / notice / service", "3 Appearance of parties")


def read(name: str, mart: Path) -> pd.DataFrame:
    return pd.read_parquet(mart / f"{name}.parquet")


def crore(n: float) -> str:
    return f"{n / 1e7:.2f} crore"


def lakh(n: float) -> str:
    return f"{n / 1e5:.1f} lakh"


def yrs(days: float) -> str:
    return f"{days / 365.25:.1f} years"


def days(value: float) -> str:
    """A median that a group never reaches is not a number, so it reads as such in a sentence."""
    return "not reached" if pd.isna(value) else f"{value:,.0f}"


def compute(mart: Path = MART) -> dict:
    h = read("headline", mart).iloc[0].to_dict()
    f: dict = {k: int(v) for k, v in h.items()}

    # Q1
    q1 = read("q1_stage", mart)
    fam = read("q1_stage_family", mart)
    f["q1_stuck"] = int(q1["stuck_cases"].sum())
    top = q1.sort_values("stuck_cases", ascending=False).iloc[0]
    f["q1_top_stage"] = top["stage"].split(" ", 1)[1]
    f["q1_top_share"] = float(top["share"])
    pre = q1[q1["stage"].isin(PRETRIAL)]
    f["q1_pretrial_share"] = float(pre["share"].sum())
    f["q1_pretrial_cases"] = int(pre["stuck_cases"].sum())
    for family in ("Criminal", "Civil"):
        g = fam[fam["family"] == family]
        f[f"q1_pretrial_share_{family.lower()}"] = float(g[g["stage"].isin(PRETRIAL)]["stuck_cases"].sum() / g["stuck_cases"].sum())
    f["q1_blank_share"] = float(q1[q1["stage"].str.startswith("11 ")]["share"].sum())

    # Q2
    s = read("q2_km_summary", mart)
    a = s[s["dimension"] == "All cases"].iloc[0]
    f["q2_km_median"] = float(a["km_median_days"])
    f["q2_naive_median"] = float(a["naive_median_days"])
    f["q2_ratio"] = f["q2_km_median"] / f["q2_naive_median"]
    f["q2_open_1y"] = float(a["open_after_1y"])
    f["q2_open_3y"] = float(a["open_after_3y"])
    f["q2_open_5y"] = float(a["open_after_5y"])
    cat = s[s["dimension"] == "Case category"].set_index("grp")
    f["q2_categories"] = {k: float(v) for k, v in cat["km_median_days"].items()}
    state = s[s["dimension"] == "State"]
    big = state[state["n"] >= 500_000].sort_values("km_median_days")
    f["q2_slowest_state"] = big.iloc[-1]["grp"]
    f["q2_slowest_state_km"] = float(big.iloc[-1]["km_median_days"])
    f["q2_slowest_state_naive"] = float(big.iloc[-1]["naive_median_days"])
    f["q2_fastest_state"] = big.iloc[0]["grp"]
    f["q2_fastest_state_km"] = float(big.iloc[0]["km_median_days"])
    year = s[s["dimension"] == "Filing year"].set_index("grp")
    f["q2_cohort_2010"] = float(year.loc["2010", "km_median_days"])
    f["q2_cohort_2018"] = float(year.loc["2018", "km_median_days"])
    sens = read("q2_sensitivity_transfer", mart).set_index("grp")
    f["q2_no_transfer_median"] = float(sens.loc["Transfers not counted as closure", "km_median_days"])

    # Q3
    acts = read("q3_acts", mart)
    t = read("q3_section_138_test", mart).iloc[0].to_dict()
    named = acts[~acts["act_canonical"].isin(["No act record", "Blank or unusable label", "Other / unmapped", "Implausible act (likely dropdown default)"])]
    top_open = named.sort_values("open_at_cutoff", ascending=False).head(3)
    f["q3_top_open"] = [{"act": r.act_canonical, "open": int(r.open_at_cutoff), "share": float(r.share_of_open)} for r in top_open.itertuples()]
    slow = named[named["n"] >= 200_000].dropna(subset=["km_median_days"]).sort_values("km_median_days", ascending=False).head(3)
    f["q3_slowest"] = [{"act": r.act_canonical, "km_median_days": float(r.km_median_days), "n": int(r.n)} for r in slow.itertuples()]
    f["q3_no_act_share"] = float(acts[acts["act_canonical"] == "No act record"]["share_of_cases"].sum())
    f["act_named_share"] = float(named["n"].sum() / acts[acts["act_canonical"] != "No act record"]["n"].sum())
    f["q3_ni_open"] = int(t["ni_open_at_cutoff"])
    f["q3_ni_open_widest"] = int(t["ni_open_act_or_type"])
    f["q3_ni_section_138_open"] = int(t["ni_open_section_138"])
    f["q3_ni_cases"] = int(t["ni_cases"])
    f["q3_ni_share_of_open"] = float(t["ni_open_at_cutoff"] / t["all_open_at_cutoff"])
    f["q3_sc_benchmark"] = int(t["supreme_court_benchmark"])
    f["q3_blog_benchmark"] = int(t["blog_benchmark"])
    f["q3_ni_km"] = float(acts[acts["act_canonical"] == "Negotiable Instruments Act"]["km_median_days"].iloc[0])

    # Q4
    o = read("q4_overall", mart).set_index("changed")
    f["q4_same_median"] = float(o.loc[False, "median_days"])
    f["q4_changed_median"] = float(o.loc[True, "median_days"])
    f["q4_same_n"] = int(o.loc[False, "n"])
    f["q4_changed_n"] = int(o.loc[True, "n"])
    p = read("q4_pairs", mart)
    f["q4_pairs"] = len(p)
    f["q4_pair_gap"] = float(p["gap_days"].median())
    f["q4_pairs_slower"] = float((p["gap_days"] > 0).mean())
    trials = p[p["case_category"].isin(["Criminal trial (magistrate)", "Sessions trial"])]
    f["q4_trial_pair_gap"] = float(trials["gap_days"].median())
    ten = read("q4_tenure_pairs", mart)
    f["q4_tenure_strata"] = len(ten)
    f["q4_tenure_cases"] = int(ten["n_leaves"].sum() + ten["n_stays"].sum())
    w = ten["n_leaves"] + ten["n_stays"]
    f["q4_tenure_gap"] = float(np.average(ten["gap"], weights=w))
    f["q4_tenure_by_category"] = {}
    for name, g in ten.groupby("case_category"):
        if len(g) >= 100:
            f["q4_tenure_by_category"][name] = {
                # One set of weights throughout, so stays minus leaves equals the gap.
                "gap": float(np.average(g["gap"], weights=g["n_leaves"] + g["n_stays"])),
                "stays": float(np.average(g["closed_2y_stays"], weights=g["n_leaves"] + g["n_stays"])),
                "leaves": float(np.average(g["closed_2y_leaves"], weights=g["n_leaves"] + g["n_stays"])),
            }

    # Q5
    u = read("q5_districts", mart)
    f["q5_units"] = len(u)
    flagged = u[u["suspect_closure_records"]]
    f["q5_flagged"] = len(flagged)
    f["q5_flagged_names"] = sorted(f"{r.district} ({r.state})" for r in flagged.itertuples())
    f["q5_flagged_by_state"] = flagged["state"].value_counts().to_dict()
    v = u[~u["low_volume"] & ~u["suspect_closure_records"]].copy()
    f["q5_ranked_units"] = len(v)
    k = v.dropna(subset=["km_median_days"])
    f["q5_p10"] = float(k["km_median_days"].quantile(0.1))
    f["q5_p90"] = float(k["km_median_days"].quantile(0.9))
    f["q5_spread"] = f["q5_p90"] / f["q5_p10"]
    f["q5_clearing"] = int((v["clearance_rate"] >= 1).sum())
    adj = v.dropna(subset=["closed_2y_adjusted"])
    within = adj.groupby("state")["closed_2y_adjusted"].transform(lambda x: x - x.mean())
    f["q5_between_state_share"] = float(1 - within.var() / adj["closed_2y_adjusted"].var())
    big_states = adj.groupby("state")["closed_2y_adjusted"].agg(["count", "min", "max"])
    big_states = big_states[big_states["count"] >= 15]
    big_states["spread"] = big_states["max"] - big_states["min"]
    if len(big_states):
        widest = big_states.sort_values("spread", ascending=False).iloc[0]
        f["q5_widest_state"] = widest.name
        f["q5_widest_low"] = float(widest["min"])
        f["q5_widest_high"] = float(widest["max"])
    slowest = k.sort_values("km_median_days", ascending=False).iloc[0]
    fastest = k.sort_values("km_median_days").iloc[0]
    f["q5_slowest"] = {"district": slowest["district"], "state": slowest["state"], "km_median_days": float(slowest["km_median_days"])}
    f["q5_fastest"] = {"district": fastest["district"], "state": fastest["state"], "km_median_days": float(fastest["km_median_days"])}
    try:
        excl = read("q5_state_excluding_flagged", mart).set_index("grp")
        f["q5_state_excl_flagged"] = {k2: float(v2) for k2, v2 in excl["km_median_days"].items()}
    except FileNotFoundError:
        f["q5_state_excl_flagged"] = {}

    # Q6
    wm = read("q6_women_state", mart)
    n = wm.groupby("role")[["total", "classified", "women"]].sum()
    n["share"] = n["women"] / n["classified"]
    n["classified_share"] = n["classified"] / n["total"]
    f["q6_roles"] = {k2: {"share": float(r.share), "classified": float(r.classified_share)} for k2, r in n.iterrows()}
    adv = n.loc[["Petitioner's advocate", "Defendant's advocate"]]
    f["q6_advocates_share"] = float(adv["women"].sum() / adv["classified"].sum())
    wc = read("q6_women_category", mart)
    fam_pet = wc[(wc["grp"] == "Family / matrimonial") & (wc["role"] == "Petitioner")]
    f["q6_family_petitioner"] = float(fam_pet["women_share"].iloc[0])

    # Q7
    q7 = read("q7_backlog", mart)
    d = q7[q7["in_ddl"]]
    f["q7_national_clearance"] = float(d["closed_per_year"].sum() / d["filed_per_year"].sum())
    f["q7_states_in_ddl"] = len(d)
    f["q7_never"] = int(d["never_clears"].sum())
    f["q7_clearing_states"] = sorted(d.loc[~d["never_clears"], "njdg_state"].tolist())
    f["q7_national_years"] = float(d["pending_total"].sum() / d["closed_per_year"].sum())
    big = d[d["pending_total"] >= 100_000].sort_values("years_of_disposals_njdg_stock", ascending=False)
    f["q7_top"] = [{"state": r.njdg_state, "years": float(r.years_of_disposals_njdg_stock)} for r in big.head(3).itertuples()]
    f["q7_bottom"] = [{"state": r.njdg_state, "years": float(r.years_of_disposals_njdg_stock)} for r in big.tail(2).itertuples()]
    f["q7_not_in_ddl"] = sorted(q7.loc[~q7["in_ddl"], "njdg_state"].tolist())

    # Judge postings, how cases end, first hearing, and the model
    tenure_table = read("q4_judge_tenure", mart)
    f["q4_tenure_median_days"] = float(tenure_table[tenure_table["dimension"] == "All India"]["km_median_days"].iloc[0])
    f["judges_sanctioned"] = JUDGES_SANCTIONED
    f["judges_working"] = JUDGES_WORKING
    f["judges_vacant_share"] = 1 - JUDGES_WORKING / JUDGES_SANCTIONED

    out = read("q8_outcomes", mart)
    overall = out[out["dimension"] == "All cases"].set_index("outcome")["share"]
    f["q8_shares"] = {k: float(v) for k, v in overall.items()}
    ni = out[(out["dimension"] == "Case category") & (out["grp"] == "Cheque bounce (NI Act)")].set_index("outcome")["share"]
    f["q8_ni_merits"] = float(ni.get("Decided on merits", 0))
    f["q8_ni_settled_or_withdrawn"] = float(ni.get("Settled or Lok Adalat", 0) + ni.get("Withdrawn or lapsed", 0))
    ver = read("q8_verdicts", mart)
    f["q8_verdict_share"] = float(ver[ver["dimension"] == "All criminal"]["verdict_share"].iloc[0])
    by_state = ver[(ver["dimension"] == "State") & (ver["closed_cases"] >= 100_000)].sort_values("verdict_share")
    f["q8_verdict_low"] = {"state": by_state.iloc[0]["grp"], "share": float(by_state.iloc[0]["verdict_share"])}
    f["q8_verdict_high"] = {"state": by_state.iloc[-1]["grp"], "share": float(by_state.iloc[-1]["verdict_share"])}

    hearing = read("q9_first_hearing", mart)
    h_all = hearing[hearing["dimension"] == "All cases"].iloc[0]
    f["q9_median"] = float(h_all["median_days"])
    f["q9_p90"] = float(h_all["p90_days"])
    f["q9_unusable_share"] = float(1 - h_all["n"] / f["usable_rows"])
    h_states = hearing[(hearing["dimension"] == "State") & (hearing["n"] >= 200_000)].sort_values("median_days")
    f["q9_fast"] = {"state": h_states.iloc[0]["grp"], "days": float(h_states.iloc[0]["median_days"])}
    f["q9_slow"] = {"state": h_states.iloc[-1]["grp"], "days": float(h_states.iloc[-1]["median_days"])}

    if (mart / "model_summary.json").exists():
        model = read("model_hazard_ratios", mart)
        info = json.loads((mart / "model_summary.json").read_text())
        ratios = model[model["group"] == "State"]
        ratios = ratios[ratios["level"] != "Smaller states and UTs"].sort_values("hazard_ratio")
        people = model[model["group"] == "People involved"].set_index("level")["hazard_ratio"]
        kinds = model[model["group"] == "Case type"].set_index("level")["hazard_ratio"]
        f["q10_rows"] = info["rows"]
        f["q10_concordance"] = info["concordance"]
        f["q10_shift"] = info["median_shift_between_samples"]
        f["q10_slow"] = [{"state": r.level, "ratio": float(r.hazard_ratio)} for r in ratios.head(2).itertuples()]
        f["q10_fast"] = {"state": ratios.iloc[-1]["level"], "ratio": float(ratios.iloc[-1]["hazard_ratio"])}
        f["q10_state_spread"] = f["q10_fast"]["ratio"] / f["q10_slow"][0]["ratio"]
        f["q10_bail"] = float(kinds["Bail"])
        f["q10_def_advocate"] = float(people["Defendant's advocate named"])
        f["q10_woman_petitioner"] = float(people["Petitioner is a woman"])

    # Coverage and quality
    c = read("coverage_vs_njdg", mart)
    both = c[c["status"] == "Both"]
    f["cov_corr"] = float(both[["ddl_open_share", "njdg_pending_share"]].corr().iloc[0, 1])
    sy = read("coverage_state_year", mart).groupby("year")["filed"].sum()
    f["cov_2010"] = int(sy.loc[2010])
    f["cov_2018"] = int(sy.loc[2018])
    f["cov_growth"] = f["cov_2018"] / f["cov_2010"]
    age = read("coverage_age_check", mart)
    age = age[age["n"] >= 200_000]
    f["cov_age_spearman"] = float(age[["old_share", "km_median_days"]].corr(method="spearman").iloc[0, 1])
    f["cov_age_states"] = len(age)
    f["njdg_total"] = NJDG_TOTAL
    f["njdg_jul28"] = NJDG_NATIONAL_JUL28
    f["njdg_2025"] = NJDG_2025
    if (mart / "dq_rules.csv").exists():
        rules = pd.read_csv(mart / "dq_rules.csv")
        f["dq_rules"] = len(rules)
        f["dq_failed"] = int((rules["failures"] > 0).sum())
        f["dq_passed"] = int((rules["failures"] == 0).sum())
    if (mart / "mapping_stats.csv").exists():
        f |= {k2: int(v2) for k2, v2 in pd.read_csv(mart / "mapping_stats.csv").iloc[0].items()}
    return f


def sentences(f: dict) -> dict:
    """One finding and one caveat per question, in plain language."""
    cat = f["q2_categories"]
    tenure = f["q4_tenure_by_category"]
    trial = tenure.get("Criminal trial (magistrate)", {"gap": float("nan")})  # a pilot may have too few matched groups
    sessions = tenure.get("Sessions trial", {"gap": float("nan")})
    top_open = f["q3_top_open"]
    slow = f["q3_slowest"]
    flagged_states = ", ".join(f"{v} in {k}" for k, v in f["q5_flagged_by_state"].items())
    excl = f["q5_state_excl_flagged"].get(f["q2_slowest_state"])
    bihar_note = (f" Without its flagged districts, {f['q2_slowest_state']}'s median falls to {yrs(excl)}." if excl and not np.isnan(excl) else "")
    named = [f"{x['state']} ({x['years']:.1f})" for x in f["q7_top"]]
    leaders = ", ".join(named[:-1]) + (" and " if len(named) > 1 else "") + named[-1]
    return {
        "q1": {
            "question": "Where do cases get stuck?",
            "finding": (
                f"{f['q1_pretrial_share']:.0%} of cases that never closed ({lakh(f['q1_pretrial_cases'])}) were last listed for admission, summons, notice or "
                f"appearance: the steps that get parties to court. Evidence is the largest single stage at {f['q1_top_share']:.0%}. "
                f"Criminal cases sit in those early steps more often than civil ones ({f['q1_pretrial_share_criminal']:.0%} against {f['q1_pretrial_share_civil']:.0%})."
            ),
            "caveat": (f"Stage comes from the free-text purpose of the last listing, which is not always the furthest point a case reached: an appearance can recur mid-trial. "
                       f"{f['q1_blank_share']:.0%} of labels say nothing about the stage and get their own bar."),
        },
        "q2": {
            "question": "How long does justice take?",
            "finding": (
                f"Half of all cases take more than {f['q2_km_median']:,.0f} days to close once open cases are counted. Closed cases alone "
                f"say {f['q2_naive_median']:,.0f} days, which understates it {f['q2_ratio']:.1f} times. {f['q2_open_5y']:.0%} of cases are "
                f"still open after five years. Civil suits take a median of {cat['Civil suit']:,.0f} days, while bail takes {cat['Bail']:,.0f}."
            ),
            "caveat": (f"Older filings look slower ({days(f['q2_cohort_2010'])} days for 2010 against {days(f['q2_cohort_2018'])} for 2018), probably because "
                       f"early digital records lean towards long-running cases. Not counting transfers as closures raises the median to {f['q2_no_transfer_median']:,.0f} days."),
        },
        "q3": {
            "question": "Which laws clog the system?",
            "finding": (
                f"The {top_open[0]['act']} holds the most open cases ({lakh(top_open[0]['open'])}), followed by the {top_open[1]['act']} ({lakh(top_open[1]['open'])}). "
                f"Among large groups, {slow[0]['act']} cases are slowest at a median {yrs(slow[0]['km_median_days'])}. "
                f"Section 138 (cheque bounce) is the largest single section by volume, with {lakh(f['q3_ni_open'])} NI Act cases filed 2010-2018 still open at the end of 2018 "
                f"({f['q3_ni_share_of_open']:.0%} of all open cases). That fits the Supreme Court's {lakh(f['q3_sc_benchmark'])} for end-2019, which also counts older cases, but this data alone cannot confirm it."
            ),
            "caveat": (f"{f['q3_no_act_share']:.0%} of cases have no act record, mostly early filings, so act volumes are undercounts. "
                       f"Counting cases by type label too raises the NI Act figure to {lakh(f['q3_ni_open_widest'])}."),
        },
        "q4": {
            "question": "Do judge transfers slow cases?",
            "finding": (
                f"Much less than it first appears. Cases that changed judges took a median {f['q4_changed_median']:,.0f} days against {f['q4_same_median']:,.0f}, and matched trials still differ by "
                f"{f['q4_trial_pair_gap']:,.0f} days, but slow cases simply have more time to see a transfer. A fairer test uses what a slow case cannot influence: how long the judge had left at filing. "
                f"With a judge about to leave, the share closed within two years was {abs(trial['gap']) * 100:.1f} points lower in magistrate trials and {abs(sessions['gap']) * 100:.1f} points lower in sessions trials."
            ),
            "caveat": ("A real but modest effect, within matched district, case type and year groups. Judge links cover only cases DDL flags as criminal, "
                       "and tenure ends can still cluster with other changes in a court, so this is an association rather than proof of cause."),
        },
        "q5": {
            "question": "Does your district decide your speed of justice?",
            "finding": (
                f"Yes: a slow district (90th percentile) takes {f['q5_spread']:.1f} times as long as a fast one (10th percentile), {f['q5_p90']:,.0f} days against {f['q5_p10']:,.0f}. "
                f"States explain {f['q5_between_state_share']:.0%} of the variation after adjusting for case mix, so districts matter but states matter more. "
                f"Only {f['q5_clearing']} of {f['q5_ranked_units']} districts disposed of as many cases as were filed in 2016-18."
            ),
            "caveat": (f"{f['q5_flagged']} districts ({flagged_states}) are left off because even bail appears not to close there, which suggests missing closure records rather than slow courts."
                       f"{bihar_note} Per-lakh figures use 2011 population, and court complexes serve people from outside their district."),
        },
        "q6": {
            "question": "How visible are women in court?",
            "finding": (
                f"Women are {f['q6_roles']['Petitioner']['share']:.0%} of named petitioners and {f['q6_roles']['Defendant']['share']:.0%} of defendants, but only about "
                f"{f['q6_advocates_share']:.0%} of advocates. Family cases are the exception among litigants, with women as {f['q6_family_petitioner']:.0%} of petitioners."
            ),
            "caveat": (f"Gender is predicted from names and counts cases, not people, so one busy advocate counts many times. Only {f['q6_roles']['Defendant' + chr(39) + 's advocate']['classified']:.0%} of "
                       f"defendants' advocates and {f['q6_roles']['Petitioner' + chr(39) + 's advocate']['classified']:.0%} of petitioners' advocates have a classifiable name."),
        },
        "q7": {
            "question": "When would the backlog clear?",
            "finding": (
                f"On 2016-18 flows, it would not: filings outran recorded disposals in {f['q7_never']} of {f['q7_states_in_ddl']} states. Even if filings stopped, the 2026 backlog equals "
                f"{f['q7_national_years']:.1f} years of disposals nationally, led by {leaders}."
            ),
            "caveat": ("This is a scenario and not a forecast. It applies 2016-18 flows to 2026 pendency, and DDL omits disposals of pre-2010 cases, so 'never clears' is overstated. "
                       "The ranking between states is sturdier than any single figure."),
        },
        "q8": {
            "question": "How do cases end?",
            "finding": (
                f"Only {f['q8_shares']['Decided on merits']:.0%} of closures are decided on the merits. {f['q8_shares']['Vague or missing label']:.0%} carry a label too vague to say how the case ended, "
                f"{f['q8_shares']['Settled or Lok Adalat']:.0%} are settled or sent to Lok Adalat, and {f['q8_shares']['Withdrawn or lapsed']:.0%} are withdrawn or lapse. "
                f"Cheque-bounce cases stand out: only {f['q8_ni_merits']:.0%} end on the merits, while {f['q8_ni_settled_or_withdrawn']:.0%} are settled or withdrawn."
            ),
            "caveat": (f"Outcome labels are too uneven to compare states: {f['q8_verdict_high']['share']:.0%} of criminal closures in {f['q8_verdict_high']['state']} record a conviction or acquittal, "
                       f"against {f['q8_verdict_low']['share']:.0%} in {f['q8_verdict_low']['state']}. So verdicts are shown by case type and never ranked by state."),
        },
        "q9": {
            "question": "How long until the first hearing?",
            "finding": (
                f"Half of cases get a first hearing within {f['q9_median']:,.0f} days, but one in ten waits more than {f['q9_p90']:,.0f} days. Among large states the median runs from "
                f"{f['q9_fast']['days']:,.0f} day{'' if f['q9_fast']['days'] == 1 else 's'} in {f['q9_fast']['state']} to {f['q9_slow']['days']:,.0f} days in {f['q9_slow']['state']}."
            ),
            "caveat": (f"This uses the recorded first-listing date, which can be a routine listing and not a substantive hearing. "
                       f"{f['q9_unusable_share']:.0%} of cases have no usable date and are left out."),
        },
        "q10": {
            "question": "What drives delay?",
            "finding": (
                f"Case mix does not explain the gaps between states. With case type, filing year and the people involved held constant, a case closes at {f['q10_slow'][0]['ratio']:.2f} times the rate of a comparable "
                f"Maharashtra case in {f['q10_slow'][0]['state']} and {f['q10_slow'][1]['ratio']:.2f} in {f['q10_slow'][1]['state']}, against {f['q10_fast']['ratio']:.2f} in {f['q10_fast']['state']}: "
                f"a {f['q10_state_spread']:.1f}-fold gap. Cases with a named defendant's advocate close {1 - f['q10_def_advocate']:.0%} more slowly, and those with a woman petitioner {1 - f['q10_woman_petitioner']:.0%} more slowly."
            ),
            "caveat": (f"A Cox model on a random sample of {f['q10_rows'] / 1e5:.0f} lakh cases, with a concordance of {f['q10_concordance']:.2f}; a second sample moved the ratios by a median of {f['q10_shift']:.1%}. "
                       "A ratio averages over time, and the data has no judge numbers or caseload per judge. These are associations: a named advocate often marks a contested case."),
        },
    }


def run(mart: Path = MART) -> dict:
    f = compute(mart)
    text = sentences(f)
    (mart / "findings.json").write_text(json.dumps({"figures": f, "text": text}, indent=1, default=str))
    print("wrote", mart / "findings.json")
    return {"figures": f, "text": text}


if __name__ == "__main__":
    out = run()
    for key, val in out["text"].items():
        print(f"\n[{key}] {val['question']}\n  {val['finding']}\n  Caveat: {val['caveat']}")
