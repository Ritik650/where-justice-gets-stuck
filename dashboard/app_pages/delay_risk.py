"""The delay-risk model: how well it predicts, how it was tested, and a what-if for one court.

Layout from the Stitch "Delay risk model" screen (docs/design/stitch_design_tokens.md). Like every page, it reads only
data/mart: the model's metrics, calibration, slices and a what-if table scored in advance, so no case rows and no model
file are needed here.
"""
import json
import re

import altair as alt
import pandas as pd
import streamlit as st
from shared import MART, SOURCES, C, show, table

REPOSITORY = "https://github.com/Ritik650/where-justice-gets-stuck/blob/main"


def chance(p: float) -> str:
    """A probability as a reader would say it; the extremes are not shown as a certain 0% or 100%."""
    return "over 99%" if p >= 0.995 else "under 1%" if p < 0.005 else f"{p:.0%}"


def court_label(name, court: str, level: str) -> str:
    """DDL's court names carry serial numbers and stray spaces; the court number keeps two same-named courts apart."""
    clean = re.sub(r"\s+", " ", re.sub(r"^[\d\W_]+", "", str(name or ""))).strip() or "Court"
    return f"{clean} ({level}, no. {court.rsplit('-', 1)[-1]})"

st.title("Delay risk model")
st.markdown("Predicts, on the day a case is filed, whether it will be decided within 24 months, and measures how much "
            "that adds over each court's own history.")

if not (MART / "ml_summary.json").exists():
    st.info("Run `make all` to build the model's tables.", title="No model results yet", icon=":material/info:")
    st.stop()

summary = json.loads((MART / "ml_summary.json").read_text())
metrics = table("ml_metrics").set_index("key")
gap = summary["gaps"]["m2_vs_b1_court"]
year = summary["test_year"]

st.info(f"A proof of concept on {summary['sample']['sampled'] / 1e5:,.0f} lakh cases filed 2010-{year}, for research only. "
        "It must never be used to decide anything about an individual case, litigant or judge. "
        f"[Full report]({REPOSITORY}/reports/ml_poc_report.md) | [Model card]({REPOSITORY}/docs/model_card.md)",
        title="Research only", icon=":material/info:")

cards = st.columns(4)
m2, b1 = metrics.loc["m2"], metrics.loc["b1"]
cards[0].metric(f"Test ROC-AUC, {year} filings", f"{m2['roc_auc_seen']:.3f}", delta=f"Brier score {metrics.loc['m2_cal', 'brier_seen']:.3f}, calibrated",
                delta_color="off", delta_arrow="off", border=True, help="LightGBM (M2). 0.5 is chance; 1.0 ranks every case correctly.")
cards[1].metric("Court history alone (B1)", f"{b1['roc_auc_seen']:.3f}", delta="Court's disposal rate last year",
                delta_color="off", delta_arrow="off", border=True, help="Each court's decisions last year over its workload last year.")
cards[2].metric("Gain over court history", f"{gap['gap']:+.3f}", delta=f"95% interval {gap['ci_low']:+.3f} to {gap['ci_high']:+.3f}",
                delta_color="off", delta_arrow="off", border=True, help="1,000 bootstrap resamples of whole courts.")
cards[3].metric("Courts never seen in training", f"{m2['roc_auc_unseen']:.3f}", delta=f"{summary['rows']['test_unseen']:,} cases",
                delta_color="off", delta_arrow="off", border=True, help="Ten percent of courts were held out of training entirely.")

left, right = st.columns([3, 2], gap="large")
with left:
    st.subheader("Model comparison")
    order = ["b0", "b1", "b2", "m1", "m2_cal", "m3"]
    comparison = metrics.loc[[k for k in order if k in metrics.index], ["model", "roc_auc_seen", "pr_auc_seen", "brier_seen", "roc_auc_unseen"]]
    st.dataframe(comparison, hide_index=True, alt=f"Test metrics for each model on {year} filings", column_config={
        "model": "Model",
        "roc_auc_seen": st.column_config.NumberColumn("ROC-AUC", format="%.3f", help="How well cases are ranked."),
        "pr_auc_seen": st.column_config.NumberColumn("PR-AUC", format="%.3f"),
        "brier_seen": st.column_config.NumberColumn("Brier score", format="%.3f", help="Lower is better. B1 and B2 are calibrated first."),
        "roc_auc_unseen": st.column_config.NumberColumn("Unseen courts", format="%.3f", help="ROC-AUC on courts held out of training."),
    })
    court_wins = summary["court_only_auc"] >= summary["case_only_auc"]
    st.caption(f"Court features alone reach {summary['court_only_auc']:.3f}; case features alone {summary['case_only_auc']:.3f}. "
               + ("More of what predicts delay is where a case is filed than what it is." if court_wins
                  else "More of what predicts delay is what a case is than where it is filed."))
with right:
    st.subheader("Calibration")
    curve = table("ml_calibration")
    curve = curve[curve["key"] == "m2_cal"]
    axis = alt.Scale(domain=[0, 1])
    diagonal = alt.Chart(pd.DataFrame({"a": [0, 1], "b": [0, 1]})).mark_line(color=C.MUTED, strokeWidth=0.75).encode(
        x=alt.X("a:Q", scale=axis), y=alt.Y("b:Q", scale=axis))
    tip = [alt.Tooltip("mean_predicted:Q", title="Mean predicted", format=".1%"), alt.Tooltip("observed_rate:Q", title="Observed", format=".1%"),
           alt.Tooltip("n:Q", title="Cases", format=",.0f")]
    x = alt.X("mean_predicted:Q", title="Predicted chance of a decision within 24 months", scale=axis, axis=alt.Axis(format=".0%"))
    y = alt.Y("observed_rate:Q", title="Observed share", scale=axis, axis=alt.Axis(format=".0%"))
    line = alt.Chart(curve).mark_line(color=C.ACCENT, strokeWidth=2).encode(x=x, y=y)
    dots = alt.Chart(curve).mark_point(filled=True, size=60, color=C.ACCENT, opacity=1, stroke=C.PANEL, strokeWidth=1.5).encode(x=x, y=y, tooltip=tip)
    show((diagonal + line + dots).properties(height=260),
         f"Ten groups of {year} test cases by predicted chance. Points on the grey diagonal are well calibrated.")

st.subheader("What-if: a case filed in one court")
whatif = table("ml_whatif")
pick = st.columns(4)
states = sorted(whatif["state_name"].dropna().unique())
state = pick[0].selectbox("State", states, index=states.index("Maharashtra") if "Maharashtra" in states else 0, key="wi_state")
in_state = whatif[whatif["state_name"] == state]
districts = sorted(in_state["district_name"].dropna().unique())
district = pick[1].selectbox("District", districts, key="wi_district")
in_district = in_state[in_state["district_name"] == district]
courts = pd.Series({r.court: court_label(r.court_name, r.court, r.court_level)
                    for r in in_district.drop_duplicates("court").itertuples()}).sort_values()
court = pick[2].selectbox("Court", courts.index.tolist(), format_func=lambda c: courts[c], key="wi_court")
in_court = in_district[in_district["court"] == court]
types = sorted(in_court["case_type"].unique())
# Bail closes in days almost everywhere, so a magistrate trial or a civil suit is the more telling default.
preferred = next((t for t in ("Criminal trial (magistrate)", "Civil suit") if t in types), types[0])
case_type = pick[3].selectbox("Case type", types, index=types.index(preferred), key="wi_type")
row = in_court[in_court["case_type"] == case_type].iloc[0]

mix = summary["whatif"]
first, last = mix["train_years"]
source = (f"{mix['cases']} {state} cases of this type filed {first}-{last}" if row["case_mix"] == "state"
          else f"{mix['cases']} cases of this type filed {first}-{last} across India ({state} has too few of its own)")

result, bars = st.columns([1, 2], gap="large")
with result:
    st.metric("Chance of a decision within 24 months", chance(row["p_model"]), border=True,
              delta=f"Model (M2), filed July {year}", delta_color="off", delta_arrow="off")
    # What this court's real cases of the type did, published only when there are enough of them to compare.
    if pd.notna(row["observed_rate"]):
        st.caption(f"This court's {year} cases of this type: {row['test_cases']:,} cases, {row['observed_rate']:.0%} decided "
                   f"within 24 months, model average {row['mean_p_actual_cases']:.0%}.")
    elif row["test_cases"]:
        st.caption(f"This court's {year} cases of this type: {row['test_cases']:,}, too few to compare "
                   f"(at least {mix['observed_min_cases']} are needed).")
    else:
        st.caption(f"This court has no {year} cases of this type in the sample to compare with.")
with bars:
    observed = (f"Observed in the {year} sample ({row['test_cases']:,} cases)" if pd.notna(row["observed_rate"]) else None)
    values = pd.DataFrame([
        {"what": "Model (M2)", "value": row["p_model"], "focus": "model"},
        {"what": "Court's history (B1)", "value": row["p_b1"], "focus": "context"},
        {"what": "Court's history for this case type (B2)", "value": row["p_b2"], "focus": "context"},
    ] + ([{"what": observed, "value": row["observed_rate"], "focus": "context"}] if observed else []))
    y = alt.Y("what:N", sort=None, title=None, axis=alt.Axis(ticks=False, domain=False, grid=False, labelLimit=260))
    x = alt.X("value:Q", title="Chance of a decision within 24 months", scale=alt.Scale(domain=[0, 1]), axis=alt.Axis(format=".0%", tickCount=5))
    bar = alt.Chart(values).mark_bar(cornerRadiusEnd=4, height=14).encode(
        x=x, y=y, color=alt.Color("focus:N", scale=alt.Scale(domain=["model", "context"], range=[C.ACCENT, C.CONTEXT]), legend=None),
        tooltip=[alt.Tooltip("what:N", title="Estimate"), alt.Tooltip("value:Q", title="Chance", format=".1%")])
    text = alt.Chart(values).mark_text(align="left", dx=5, font=C.FONT, fontSize=10, color=C.BODY).encode(x=x, y=y, text=alt.Text("value:Q", format=".0%"))
    show((bar + text).properties(height=34 * len(values) + 30),
         f"Model: the average chance over {source}, each with its own act, section and parties, as if filed in this court in "
         f"July {year} with the court's history as of the end of {year - 1}. B1 and B2 are disposal rates mapped onto the same "
         "chance with 2015 data.",
         alt_text=f"Chance of a decision within 24 months for a {case_type} case in the chosen court, by estimate")

st.subheader("Where the model is weakest")
slices = table("ml_slices")
dimension = st.segmented_control("Slice by", ["State", "Case type", "Court level"], default="State", key="slice_dim") or "State"
shown = slices[(slices["dimension"] == dimension) & slices["rankable"]].sort_values("auc_m2")
st.dataframe(shown[["slice", "n", "positive_rate", "auc_m2", "auc_b1", "auc_gap"]], hide_index=True,
             alt=f"Model and court-history ROC-AUC by {dimension.lower()}, weakest first", column_config={
                 "slice": dimension, "n": st.column_config.NumberColumn("Test cases", format="%,d"),
                 "positive_rate": st.column_config.NumberColumn("Decided within 24 months", format="percent"),
                 "auc_m2": st.column_config.NumberColumn("Model ROC-AUC", format="%.3f"),
                 "auc_b1": st.column_config.NumberColumn("Court history ROC-AUC", format="%.3f"),
                 "auc_gap": st.column_config.NumberColumn("Gain", format="%+.3f"),
             })
st.caption(f"Slices with at least 1,000 test cases and 100 of each outcome, weakest first. Run `{summary['m2_run_id']}`, "
           f"evaluation `{summary['evaluation_run_id']}` in reports/experiments.csv, from commit `{summary['git_commit']}`. {SOURCES}")
