"""One state at a glance, each figure beside the national one. Layout from the Stitch State Profile screen."""
import pandas as pd
import streamlit as st
from shared import DIMENSIONS, NJDG_NAME, SOURCES, C, findings, national_score, show, table

F = findings()["figures"]
summary = table("q2_km_summary")
states = sorted(summary[summary["dimension"] == "State"]["grp"].dropna().unique())

st.title("State profile")
state = st.selectbox("State", states, index=states.index("Bihar"), key="profile_state")

row = summary[(summary["dimension"] == "State") & (summary["grp"] == state)].iloc[0]
overall = summary[summary["dimension"] == "All cases"].iloc[0]
q7 = table("q7_backlog")
njdg_name = NJDG_NAME.get(state, state)
flows = q7[q7["njdg_state"] == njdg_name]
in_njdg = len(flows) == 1 and pd.notna(flows.iloc[0]["pending_total"])
national_years = F["q7_national_years"]

districts = table("q5_districts")
flagged = districts[(districts["state"] == state) & districts["suspect_closure_records"]]
if len(flagged):
    excl = F["q5_state_excl_flagged"].get(state)
    extra = f" Without them, the median falls to {excl:,.0f} days." if excl else ""
    st.info(f"{', '.join(sorted(flagged['district']))} appear to have incomplete closure records, which raises this state's median.{extra}",
            title=f"{len(flagged)} districts need care", icon=":material/warning:")
if njdg_name != state:
    st.caption(f"NJDG reports {state} together with its neighbouring territory, so 2026 figures below are for both.")


def card(column, label: str, value: str, national: str, help_text: str | None = None) -> None:
    column.metric(label, value, delta=f"India: {national}", delta_color="off", delta_arrow="off", help=help_text, border=True)


top = st.columns(3)
card(top[0], "Cases filed, 2010-18", f"{row['n'] / 1e5:,.1f} lakh", f"{overall['n'] / 1e7:,.2f} crore")
card(top[1], "Median days to close", f"{row['km_median_days']:,.0f}" if pd.notna(row["km_median_days"]) else "Not reached", f"{overall['km_median_days']:,.0f}", "Kaplan-Meier, with open cases counted.")
card(top[2], "Still open after 5 years", f"{row['open_after_5y']:.0%}" if pd.notna(row["open_after_5y"]) else "No data", f"{overall['open_after_5y']:.0%}")
bottom = st.columns(3)
if in_njdg:
    f7 = flows.iloc[0]
    old_share = (f7["pending_over_10y"] + f7["pending_5_to_10y"]) / f7["pending_total"]
    nat = q7.dropna(subset=["pending_total"])
    nat_old = (nat["pending_over_10y"].sum() + nat["pending_5_to_10y"].sum()) / nat["pending_total"].sum()
    card(bottom[0], "Pending, Jul 2026", f"{f7['pending_total'] / 1e5:,.1f} lakh", f"{F['njdg_total'] / 1e7:.2f} crore", "NJDG, Lok Sabha Q.3371.")
    card(bottom[1], "Pending 5+ years, 2026", f"{old_share:.0%}", f"{nat_old:.0%}", "NJDG. The source's two age bands added together.")
    card(bottom[2], "Years of disposals to clear", f"{f7['years_of_disposals_njdg_stock']:.1f}", f"{national_years:.1f}", "2026 pendency divided by 2016-18 disposals, if filings stopped.")
else:
    bottom[0].info("NJDG's 2026 table has no separate row for this state.")

left, right = st.columns(2, gap="large")
with left:
    st.subheader("How long cases take")
    curves = table("q2_km_curves")
    wanted = pd.concat([curves[curves["dimension"] == "All cases"], curves[(curves["dimension"] == "State") & (curves["grp"] == state)]])
    show(C.survival_lines(wanted, ["All cases", state], height=280), "Kaplan-Meier curves, with all cases in India for comparison.")
with right:
    st.subheader("Where open cases sit")
    stages = table("q1_stage_state")
    stages = stages[stages["state"] == state].groupby("stage", as_index=False)["stuck_cases"].sum()
    if stages.empty:
        st.info("No never-closed cases are recorded for this state.")
    else:
        stages = stages.assign(share=stages["stuck_cases"] / stages["stuck_cases"].sum())
        show(C.stage_bars(stages, height=280), "Cases with no decision date, by the purpose of their last listed hearing.")

left, right = st.columns(2, gap="large")
with left:
    st.subheader("Districts")
    d = districts[(districts["state"] == state) & ~districts["low_volume"] & ~districts["suspect_closure_records"]].sort_values("km_median_days", ascending=False)
    if d.empty:
        st.info("No district in this state has enough cases to rank.")
    else:
        st.dataframe(d[["district", "km_median_days", "clearance_rate", "closed_2y_adjusted", "filed_per_lakh_year"]], hide_index=True, alt=f"Districts in {state}, slowest first", column_config={
            "district": "District (2011)", "km_median_days": st.column_config.NumberColumn("Median days", format="%,d"),
            "clearance_rate": st.column_config.NumberColumn("Clearance", format="percent", help="Closed ÷ filed, 2016-18."),
            "closed_2y_adjusted": st.column_config.NumberColumn("Closed in 2y", format="percent", help="Adjusted to the national mix of case types."),
            "filed_per_lakh_year": st.column_config.NumberColumn("Filed per lakh, per year", format="%,d"),
        })
with right:
    st.subheader("Largest open caseloads, by act")
    acts = table("state_acts")
    st.dataframe(acts[acts["state"] == state].sort_values("open_at_cutoff", ascending=False)[["act_canonical", "n", "open_at_cutoff"]], hide_index=True, alt=f"Acts with the most open cases in {state}", column_config={
        "act_canonical": "Act", "n": st.column_config.NumberColumn("Cases", format="%,d"), "open_at_cutoff": st.column_config.NumberColumn("Open end-2018", format="%,d"),
    })

left, right = st.columns(2, gap="large")
with left:
    st.subheader("How cases end")
    o = table("q8_outcomes")
    both = pd.concat([o[(o["dimension"] == "State") & (o["grp"] == state)], o[o["dimension"] == "All cases"]])
    show(C.outcome_stacks(both, height=190), "Closed cases only, with all cases in India for comparison.")
with right:
    st.subheader("Data quality")
    scores = table("dq_state_scores")
    mine = scores[scores["state"] == state]
    if len(mine):
        rows = pd.DataFrame([{"Dimension": dim, state: mine.iloc[0][dim], "India": national_score(scores, dim)} for dim in DIMENSIONS])
        st.dataframe(rows, hide_index=True, alt=f"Data-quality scores for {state} and India", column_config={
            state: st.column_config.NumberColumn(format="percent"), "India": st.column_config.NumberColumn(format="percent"),
        })
        st.caption("A low score means hard-to-use records, not a poor court.")

st.caption(SOURCES)
