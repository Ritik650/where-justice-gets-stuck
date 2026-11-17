"""Build the always-on static copy of the dashboard for GitHub Pages, in site/.

The Streamlit app on Community Cloud sleeps when nobody has opened it for a while. This copy is plain files, so it is
always up. It reads the same data/mart tables and draws every chart with the same definitions (pipeline/charts.py),
exported as Vega-Lite specs that the browser renders with vega-embed, so the two cannot drift apart. The page shell
and components come from the project's Stitch designs (docs/design/stitch_design_tokens.md); pipeline/site_template
holds them.

    python -I pipeline/build_site.py      writes site/ (git-ignored); publish it to the gh-pages branch

Interactivity is kept where it is cheap without a server: question tabs, metric and group switches between prebuilt
charts, a state picker, filters and search on the data-quality tables, the backlog scenario and the model's what-if.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import charts as C  # noqa: E402
from common import LIVE_DASHBOARD, MART, OUTPUTS, REPOSITORY, ROOT  # noqa: E402
from samples import short_samples  # noqa: E402

SITE = ROOT / "site"
TEMPLATE = Path(__file__).resolve().parent / "site_template"
DIMENSIONS = ["Completeness", "Validity", "Consistency", "Uniqueness", "Linkage"]
NJDG_NAME = {"Daman and Diu": "The Dadra and Nagar Haveli and Daman and Diu",
             "Dadra and Nagar Haveli": "The Dadra and Nagar Haveli and Daman and Diu"}
SOURCES = (
    "Sources: Development Data Lab eCourts data (CC BY-NC-SA 4.0, non-commercial); NJDG via Lok Sabha Unstarred Question 3371, "
    "7 Aug 2026; Census 2011; DataMeet district boundaries (CC BY 4.0). Gender is predicted from names by DDL's model."
)


def table(name: str) -> pd.DataFrame:
    return pd.read_parquet(MART / f"{name}.parquet")


def plain(value):
    """numpy scalars, NaN and timestamps to JSON values."""
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return str(value)[:10]
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and value != value:
        return None
    return value


def records(df: pd.DataFrame, columns: list[str] | None = None) -> list[dict]:
    d = df[columns] if columns else df
    return [plain(r) for r in d.to_dict("records")]


def write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plain(obj), separators=(",", ":"), ensure_ascii=False), encoding="utf8")


def spec(chart, description: str) -> dict:
    """A chart in the dashboard's shared style, as a Vega-Lite spec. The description is the chart's text alternative."""
    out = C.styled(chart).to_dict()
    out["description"] = description
    return out


def save(name: str, chart, description: str) -> None:
    write(SITE / "specs" / f"{name}.json", spec(chart, description))


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def findings_page(F: dict) -> None:
    # Q5: the map for each metric, the ranked table and the flagged districts.
    d = table("q5_districts")
    shown = d.copy()
    shown.loc[shown["suspect_closure_records"], "low_volume"] = True  # drawn as no data
    for metric in C.METRICS:
        save(f"q5_{slug(metric)}", C.district_map(shown, metric, None),
             f"Map of districts in India shaded by {metric.lower()}. The ranked table beside it gives the same figures.")
    ranked = d[~d["low_volume"] & ~d["suspect_closure_records"]].dropna(subset=["km_median_days"])
    cols = ["district", "state", "km_median_days", "clearance_rate", "closed_2y_adjusted"]
    flagged = d[d["suspect_closure_records"]].sort_values(["state", "district"])
    write(SITE / "data" / "q5.json", {
        "slowest": records(ranked.sort_values("km_median_days", ascending=False).head(12), cols),
        "fastest": records(ranked.sort_values("km_median_days").head(12), cols),
        "flagged": records(flagged, ["district", "state", "total_cases", "bail_closed_2y", "closed_2y_raw"]),
    })

    # Q1: stages, nationally and by case family.
    q = table("q1_stage")[["stage", "stuck_cases"]]
    fam = table("q1_stage_family")
    for name, frame, note in (("all", q, "All cases, India."),
                              ("criminal", fam[fam["family"] == "Criminal"].groupby("stage", as_index=False)["stuck_cases"].sum(), "Criminal cases, India."),
                              ("civil", fam[fam["family"] == "Civil"].groupby("stage", as_index=False)["stuck_cases"].sum(), "Civil cases, India.")):
        frame = frame.assign(share=frame["stuck_cases"] / frame["stuck_cases"].sum())
        save(f"q1_{name}", C.stage_bars(frame, height=340), f"{note} Cases with no decision date, by the purpose of their last listed hearing.")

    # Q2: survival curves for three comparisons with the dashboard's default groups, and the closure sensitivity.
    s, c = table("q2_km_summary"), table("q2_km_curves")
    defaults = {"Case category": ["Civil suit", "Cheque bounce (NI Act)", "Criminal trial (magistrate)"],
                "State": ["Bihar", "Maharashtra", "Karnataka"], "Filing year": ["2010", "2014", "2017"]}
    tables = {}
    summary_cols = ["grp", "n", "km_median_days", "naive_median_days", "open_after_1y", "open_after_3y", "open_after_5y"]
    for dim, chosen in defaults.items():
        curves = pd.concat([c[c["dimension"] == "All cases"], c[(c["dimension"] == dim) & (c["grp"].isin(chosen))]])
        save(f"q2_{slug(dim)}", C.survival_lines(curves, ["All cases"] + chosen),
             "Kaplan-Meier curves. Cases still open count until 31 Dec 2018 and then leave the risk set, so they are never dropped.")
        tbl = pd.concat([s[s["dimension"] == "All cases"], s[(s["dimension"] == dim) & (s["grp"].isin(chosen))]])
        tables[slug(dim)] = records(tbl, summary_cols)
    sens = table("q2_sensitivity_transfer_curves")
    save("q2_closed", C.survival_lines(sens, sens["grp"].unique().tolist(), highlight="All closures"),
         "A transfer moves a file without resolving the dispute. Counting transferred cases as still open raises the curve.")
    tables["closed"] = records(table("q2_sensitivity_transfer"), ["grp", "n", "closed", "km_median_days", "open_after_1y", "open_after_3y", "open_after_5y"])
    write(SITE / "data" / "q2.json", tables)

    # Q3: laws.
    acts = table("q3_acts")
    save("q3_acts", C.act_bubbles(acts), "Named acts with at least 1 lakh cases. Up and right is both common and slow; a larger bubble means more open cases.")
    write(SITE / "data" / "q3.json", {
        "acts": records(acts.sort_values("open_at_cutoff", ascending=False),
                        ["act_canonical", "act_family", "n", "open_at_cutoff", "share_of_open", "km_median_days", "naive_median_days"]),
        "sections": records(table("q3_sections").head(40), ["act_canonical", "section_norm", "n", "open_at_cutoff", "naive_median_days"]),
    })

    # Q4: judge transfers.
    pairs, tenure = table("q4_pairs"), table("q4_tenure_pairs")
    pairs = pairs[pairs["case_category"].isin(C.TRIAL_CATEGORIES)]
    tenure = tenure[tenure["case_category"].isin(C.TRIAL_CATEGORIES)]
    save("q4_judges", C.judge_boxes(pairs, width="container"),
         f"{len(pairs):,} matched groups of trials in the same district, case type and filing year. Boxes show the middle half, lines the 5th to 95th percentile.")
    save("q4_tenure", C.tenure_boxes(tenure, width="container"),
         f"{len(tenure):,} matched groups of trials, closed and open alike. White line and label: case-weighted average.")
    write(SITE / "data" / "q4.json", {"pairs": len(pairs), "tenure": len(tenure), "rows": [
        {"type": k, "stays": v["stays"], "leaves": v["leaves"], "gap": v["gap"] * 100} for k, v in F["q4_tenure_by_category"].items()]})

    # Q6: women in court.
    w = table("q6_women_state")
    national = w.groupby("role", as_index=False)[["classified", "women", "total"]].sum()
    national["women_share"] = national["women"] / national["classified"]
    national["classified_share"] = national["classified"] / national["total"]
    save("q6_roles", C.women_roles(national), "Share of women among cases with a classifiable name. The classifiable share differs widely by role.")
    save("q6_trend", C.women_trend(table("q6_women_year")), "By filing year. Early years have fewer records.")
    for role in ["Petitioner", "Defendant", "Petitioner's advocate", "Defendant's advocate"]:
        save(f"q6_{slug(role)}", C.women_stacks(w, role, height=640), "States with at least 20,000 cases, sorted by women's share of classified names.")
    write(SITE / "data" / "q6.json", records(national, ["role", "women_share", "classified_share"]))

    # Q7: backlog, with a template for the scenario line the page redraws.
    q7 = table("q7_backlog")
    save("q7_backlog", C.backlog_bars(q7), "2026 pendency (NJDG) divided by 2016-18 disposals (DDL). States with under 20,000 pending cases are left out.")
    save("q7_scenario", C.scenario_line(pd.DataFrame({"year": range(21), "pending": [0.0] * 21})), "Pending cases under the chosen scenario.")
    usable = q7[q7["in_ddl"]].sort_values("pending_total", ascending=False)
    write(SITE / "data" / "q7.json", {
        "states": records(usable, ["njdg_state", "pending_total", "filed_per_year", "closed_per_year"]),
        "table": records(q7.sort_values("years_of_disposals_njdg_stock", ascending=False),
                         ["njdg_state", "pending_total", "pending_over_10y", "pending_5_to_10y", "filed_per_year", "closed_per_year",
                          "clearance_rate", "years_of_disposals_njdg_stock", "never_clears"]),
    })

    # Q8: outcomes.
    o = table("q8_outcomes")
    save("q8_case_type", C.outcome_stacks(o[o["dimension"] == "Case category"], height=max(280, 22 * o[o["dimension"] == "Case category"]["grp"].nunique())),
         "Closed cases only, sorted by share decided on merits.")
    large = s.query("dimension == 'State' and n >= 200000")["grp"]
    by_state = o[(o["dimension"] == "State") & (o["grp"].isin(large))]
    save("q8_state", C.outcome_stacks(by_state, height=max(280, 22 * by_state["grp"].nunique())), "Closed cases only, states with at least 2 lakh cases.")
    v = table("q8_verdicts")
    write(SITE / "data" / "q8.json", {
        "national": records(o[o["dimension"] == "All cases"].sort_values("share", ascending=False), ["outcome", "closed_cases", "share", "median_days"]),
        "verdicts": records(v[v["dimension"] != "State"].sort_values("closed_cases", ascending=False), ["grp", "closed_cases", "verdict_share", "conviction_share"]),
    })

    # Q9 and Q10.
    h = table("q9_first_hearing")
    states = h[(h["dimension"] == "State") & (h["n"] >= 20_000)]
    save("q9_states", C.first_hearing_bars(states, height=max(420, 20 * len(states))), "States with at least 20,000 cases that have a usable first-hearing date.")
    write(SITE / "data" / "q9.json", records(h[h["dimension"] == "Case category"].sort_values("median_days", ascending=False),
                                              ["grp", "median_days", "p90_days", "within_30_days"]))
    m = table("model_hazard_ratios")
    for group, name, text in (("State", "state", "Hazard ratios with 95% intervals, compared with Maharashtra."),
                              ("Case type", "case_type", "Compared with magistrate trials, with state and filing year held constant."),
                              ("People involved", "people", "Associations: a named advocate often marks a contested case.")):
        save(f"q10_{name}", C.hazard_forest(m[m["group"] == group]), text)


def state_pages(F: dict) -> None:
    summary, curves, q7 = table("q2_km_summary"), table("q2_km_curves"), table("q7_backlog")
    districts, acts, outcomes, scores = table("q5_districts"), table("state_acts"), table("q8_outcomes"), table("dq_state_scores")
    stages_all = table("q1_stage_state")
    overall = summary[summary["dimension"] == "All cases"].iloc[0]
    nat = q7.dropna(subset=["pending_total"])
    nat_old = (nat["pending_over_10y"].sum() + nat["pending_5_to_10y"].sum()) / nat["pending_total"].sum()
    national_scores = {dim: float((scores[dim] * scores["cases"]).sum() / scores["cases"].sum()) for dim in DIMENSIONS}
    names = sorted(summary[summary["dimension"] == "State"]["grp"].dropna().unique())
    index = []
    for state in names:
        row = summary[(summary["dimension"] == "State") & (summary["grp"] == state)].iloc[0]
        njdg = NJDG_NAME.get(state, state)
        flows = q7[q7["njdg_state"] == njdg]
        has_njdg = len(flows) == 1 and pd.notna(flows.iloc[0]["pending_total"])
        f7 = flows.iloc[0] if has_njdg else None
        wanted = pd.concat([curves[curves["dimension"] == "All cases"], curves[(curves["dimension"] == "State") & (curves["grp"] == state)]])
        stage = stages_all[stages_all["state"] == state].groupby("stage", as_index=False)["stuck_cases"].sum()
        both = pd.concat([outcomes[(outcomes["dimension"] == "State") & (outcomes["grp"] == state)], outcomes[outcomes["dimension"] == "All cases"]])
        flagged = districts[(districts["state"] == state) & districts["suspect_closure_records"]]
        mine = scores[scores["state"] == state]
        page = {
            "state": state, "njdg_name": njdg,
            "kpis": {
                "filed": row["n"], "filed_india": overall["n"], "median": row["km_median_days"], "median_india": overall["km_median_days"],
                "open5": row["open_after_5y"], "open5_india": overall["open_after_5y"],
                "pending": f7["pending_total"] if has_njdg else None, "pending_india": F["njdg_total"],
                "old_share": (f7["pending_over_10y"] + f7["pending_5_to_10y"]) / f7["pending_total"] if has_njdg else None, "old_share_india": nat_old,
                "years": f7["years_of_disposals_njdg_stock"] if has_njdg else None, "years_india": F["q7_national_years"],
            },
            "flagged": sorted(flagged["district"].tolist()), "excl_median": F["q5_state_excl_flagged"].get(state),
            "survival": spec(C.survival_lines(wanted, ["All cases", state], height=280), f"Kaplan-Meier curves for {state}, with all cases in India for comparison."),
            "stages": spec(C.stage_bars(stage.assign(share=stage["stuck_cases"] / stage["stuck_cases"].sum()), height=280),
                           f"Cases with no decision date in {state}, by the purpose of their last listed hearing.") if len(stage) else None,
            "outcomes": spec(C.outcome_stacks(both, height=190), f"How closed cases ended in {state}, with all cases in India for comparison."),
            "districts": records(districts[(districts["state"] == state) & ~districts["low_volume"] & ~districts["suspect_closure_records"]]
                                 .sort_values("km_median_days", ascending=False),
                                 ["district", "km_median_days", "clearance_rate", "closed_2y_adjusted", "filed_per_lakh_year"]),
            "acts": records(acts[acts["state"] == state].sort_values("open_at_cutoff", ascending=False), ["act_canonical", "n", "open_at_cutoff"]),
            "quality": [{"dimension": dim, "state": float(mine.iloc[0][dim]) if len(mine) else None, "india": national_scores[dim]} for dim in DIMENSIONS],
        }
        write(SITE / "data" / "states" / f"{slug(state)}.json", page)
        index.append({"state": state, "slug": slug(state)})
    write(SITE / "data" / "states" / "index.json", index)


def quality_page(F: dict) -> None:
    scores = table("dq_state_scores")
    save("dq_heat", C.quality_heat(scores, DIMENSIONS), "Heat table of data-quality scores by state and dimension, best overall at the top.")
    save("dq_lines", C.quality_lines(table("dq_year_scores"), DIMENSIONS), "National scores for cases filed in each year.")
    save("dq_coverage", C.coverage_heat(table("coverage_state_year")), "Filings in each year as a share of the state's 2018 filings.")
    save("dq_share", C.share_scatter(table("coverage_vs_njdg")), "Each state's share of open cases in DDL against its share of NJDG's 2026 pendency.")
    save("dq_cliff", C.decisions_cliff(table("coverage_decisions_by_month")), "Decisions recorded per month around the analysis cut-off.")
    rules = pd.read_csv(MART / "dq_rules.csv")
    sql = {}
    for block in re.split(r"(?m)^(?=-- id: )", (ROOT / "sql" / "dq_rules.sql").read_text(encoding="utf8"))[1:]:
        rid = re.search(r"(?m)^-- id: (\S+)", block).group(1)
        sql[rid] = "\n".join(line for line in block.splitlines() if not line.startswith("--")).strip()
    rules["sql"] = rules["rule_id"].map(sql)
    issues = pd.read_csv(MART / "issue_log.csv", dtype=str, keep_default_na=False)
    issues = issues.assign(source="Rule " + issues["rule_id"], evidence=issues["sample_records"].map(short_samples)).rename(columns={"title": "issue"})
    analyst = pd.read_csv(ROOT / "docs" / "analyst_issues.csv", dtype=str, keep_default_na=False).assign(source="Analyst review").rename(columns={"title": "issue"})
    log = pd.concat([analyst, issues], ignore_index=True)
    write(SITE / "data" / "quality.json", {
        "rules": records(rules, ["rule_id", "title", "dimension", "severity", "status", "failures", "failure_rate", "treatment", "sql"]),
        "issues": records(log, ["issue_id", "source", "issue", "severity", "status", "evidence", "treatment"]),
        "national": {dim: float((scores[dim] * scores["cases"]).sum() / scores["cases"].sum()) for dim in DIMENSIONS},
    })


def model_page() -> None:
    summary_path = MART / "ml_summary.json"
    if not summary_path.exists():
        return
    summary = json.loads(summary_path.read_text())
    metrics = table("ml_metrics")
    curve = table("ml_calibration")
    curve = curve[curve["key"] == "m2_cal"]
    axis = alt.Scale(domain=[0, 1])
    diagonal = alt.Chart(pd.DataFrame({"a": [0, 1], "b": [0, 1]})).mark_line(color=C.MUTED, strokeWidth=0.75).encode(
        x=alt.X("a:Q", scale=axis), y=alt.Y("b:Q", scale=axis))
    x = alt.X("mean_predicted:Q", title="Predicted chance of a decision within 24 months", scale=axis, axis=alt.Axis(format=".0%"))
    y = alt.Y("observed_rate:Q", title="Observed share", scale=axis, axis=alt.Axis(format=".0%"))
    tip = [alt.Tooltip("mean_predicted:Q", title="Mean predicted", format=".1%"), alt.Tooltip("observed_rate:Q", title="Observed", format=".1%"),
           alt.Tooltip("n:Q", title="Cases", format=",.0f")]
    line = alt.Chart(curve).mark_line(color=C.ACCENT, strokeWidth=2).encode(x=x, y=y)
    dots = alt.Chart(curve).mark_point(filled=True, size=60, color=C.ACCENT, opacity=1, stroke=C.PANEL, strokeWidth=1.5).encode(x=x, y=y, tooltip=tip)
    save("model_calibration", (diagonal + line + dots).properties(width="container", height=260),
         f"Ten groups of {summary['test_year']} test cases by predicted chance. Points on the grey diagonal are well calibrated.")
    # A template for the what-if bars; the page fills in the four values for the chosen court and case type.
    values = pd.DataFrame({"what": ["Model (M2)", "Court's history (B1)"], "value": [0.5, 0.5], "focus": ["model", "context"]})
    yy = alt.Y("what:N", sort=None, title=None, axis=alt.Axis(ticks=False, domain=False, grid=False, labelLimit=260))
    xx = alt.X("value:Q", title="Chance of a decision within 24 months", scale=alt.Scale(domain=[0, 1]), axis=alt.Axis(format=".0%", tickCount=5))
    bar = alt.Chart(values).mark_bar(cornerRadiusEnd=4, height=14).encode(
        x=xx, y=yy, color=alt.Color("focus:N", scale=alt.Scale(domain=["model", "context"], range=[C.ACCENT, C.CONTEXT]), legend=None),
        tooltip=[alt.Tooltip("what:N", title="Estimate"), alt.Tooltip("value:Q", title="Chance", format=".1%")])
    text = alt.Chart(values).mark_text(align="left", dx=5, font=C.FONT, fontSize=10, color=C.BODY).encode(x=xx, y=yy, text=alt.Text("value:Q", format=".0%"))
    save("model_whatif", (bar + text).properties(width="container", height=120), "Chance of a decision within 24 months for the chosen court and case type, by estimate.")
    order = ["b0", "b1", "b2", "m1", "m2_cal", "m3"]
    write(SITE / "data" / "model.json", {
        "summary": summary,
        "metrics": records(metrics.set_index("key").loc[[k for k in order if k in set(metrics["key"])]].reset_index(),
                           ["key", "model", "roc_auc_seen", "pr_auc_seen", "brier_seen", "roc_auc_unseen"]),
        "headline": {k: records(metrics[metrics["key"] == k])[0] for k in ("m2", "b1", "m2_cal")},
        "slices": records(table("ml_slices").query("rankable"), ["dimension", "slice", "n", "positive_rate", "auc_m2", "auc_b1", "auc_gap"]),
    })
    # The what-if, nested state > district > court > case type, with short keys to keep the file small. Each case type
    # holds [model, B1, B2, observed share, test cases, model average on those cases, 1 if scored on the state's own mix].
    w = table("ml_whatif")
    tree: dict = {}

    def share(v) -> float | None:
        return None if pd.isna(v) else round(float(v), 4)

    for r in w.itertuples():
        court = tree.setdefault(r.state_name, {}).setdefault(r.district_name, {}).setdefault(r.court, {
            "name": re.sub(r"\s+", " ", re.sub(r"^[\d\W_]+", "", str(r.court_name or ""))).strip() or "Court",
            "level": r.court_level, "types": {}})
        court["types"][r.case_type] = [share(r.p_model), share(r.p_b1), share(r.p_b2), share(r.observed_rate), int(r.test_cases),
                                       share(r.mean_p_actual_cases), int(r.case_mix == "state")]
    write(SITE / "data" / "whatif.json", tree)


def build() -> None:
    if SITE.exists():
        shutil.rmtree(SITE)
    shutil.copytree(TEMPLATE, SITE)
    fx = json.loads((MART / "findings.json").read_text())
    F, text = fx["figures"], fx["text"]
    scores = table("dq_state_scores")
    write(SITE / "data" / "summary.json", {
        "figures": F, "text": text, "sources": SOURCES, "live": LIVE_DASHBOARD, "repository": REPOSITORY,
        "quality": {dim: float((scores[dim] * scores["cases"]).sum() / scores["cases"].sum()) for dim in DIMENSIONS},
    })
    findings_page(F)
    state_pages(F)
    quality_page(F)
    model_page()
    write(SITE / "data" / "methods.json", {"markdown": (ROOT / "docs" / "methods.md").read_text(encoding="utf8")})
    (SITE / "downloads").mkdir(exist_ok=True)
    for name in ("where_justice_gets_stuck_brief.pdf", "data_quality_scorecard.xlsx"):
        if (OUTPUTS / name).exists():
            shutil.copy2(OUTPUTS / name, SITE / "downloads" / name)
    (SITE / ".nojekyll").write_text("")  # serve files as they are; nothing here needs Jekyll
    size = sum(p.stat().st_size for p in SITE.rglob("*") if p.is_file())
    print(f"site: {sum(1 for p in SITE.rglob('*') if p.is_file())} files, {size / 1e6:.1f} MB -> {SITE}", flush=True)


if __name__ == "__main__":
    build()
