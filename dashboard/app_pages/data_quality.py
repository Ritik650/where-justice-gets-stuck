"""The data-quality work, explorable. Layout from the Stitch Data Quality screen."""
import pandas as pd
import streamlit as st
from shared import DIMENSIONS, OUTPUTS, SOURCES, C, csv, findings, rule_sql, short_samples, show, table

F = findings()["figures"]

st.title("Data quality")
st.markdown(
    f"{F.get('dq_rules', 0)} rules ran over all {F['total_rows'] / 1e6:.1f} million cases, and {F.get('dq_failed', 0)} found failures. "
    "A low score means the records are hard to use. It says nothing about how well a court performs."
)
view = st.segmented_control("View", ["Scorecard", "Rules", "Issue log", "Coverage"], default="Scorecard", key="dq_view", label_visibility="collapsed") or "Scorecard"

if view == "Scorecard":
    scores = table("dq_state_scores")
    left, right = st.columns([3, 2], gap="large")
    with left:
        show(C.quality_heat(scores, DIMENSIONS), "Scores by state and dimension, best overall at the top. Each score is 100% minus the severity-weighted failure rate of that dimension's rules.",
             "Heat table of data-quality scores by state and dimension. The same figures are in the Excel scorecard.")
    with right:
        st.markdown("**Quality by filing year**")
        show(C.quality_lines(table("dq_year_scores"), DIMENSIONS), "National scores for cases filed in each year. Linkage rises sharply from 2014 because act records are thin before then.")
        book = OUTPUTS / "data_quality_scorecard.xlsx"
        if book.exists():
            st.download_button("Download the Excel scorecard", book.read_bytes(), file_name=book.name, icon=":material/table:",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            st.caption("Its scores are live formulas, so changing a severity weight recalculates every score.")

elif view == "Rules":
    rules = csv("data/mart/dq_rules.csv").assign(
        failures=lambda d: pd.to_numeric(d["failures"]), failure_rate=lambda d: pd.to_numeric(d["failure_rate"]))
    with st.container(horizontal=True, vertical_alignment="bottom"):
        dimension = st.pills("Dimension", sorted(rules["dimension"].unique()), selection_mode="multi", key="rules_dimension")
        severity = st.pills("Severity", ["High", "Medium", "Low", "Info"], selection_mode="multi", key="rules_severity")
        only_failed = st.toggle("Only rules that found failures", key="rules_failed")
    shown = rules
    if dimension:
        shown = shown[shown["dimension"].isin(dimension)]
    if severity:
        shown = shown[shown["severity"].isin(severity)]
    if only_failed:
        shown = shown[shown["failures"] > 0]
    st.dataframe(shown[["rule_id", "title", "dimension", "severity", "status", "failures", "failure_rate", "treatment"]], hide_index=True, alt="Data-quality rules and their national results", column_config={
        "rule_id": "Rule", "title": st.column_config.TextColumn("What fails", width="large"), "dimension": "Dimension", "severity": "Severity", "status": "Status",
        "failures": st.column_config.NumberColumn("Failures", format="%,d"), "failure_rate": st.column_config.NumberColumn("Rate", format="percent"),
        "treatment": st.column_config.TextColumn("Treatment", width="large"),
    })
    pick = st.selectbox("See a rule's SQL", shown["rule_id"] + "  " + shown["title"], key="rules_sql") if len(shown) else None
    if pick:
        st.code(rule_sql()[pick.split()[0]], language="sql")

elif view == "Issue log":
    rules = csv("data/mart/issue_log.csv").assign(source=lambda d: "Rule " + d["rule_id"])
    rules = rules.assign(evidence=rules["sample_records"].map(short_samples)).rename(columns={"title": "issue"})
    analyst = csv("docs/analyst_issues.csv").assign(source="Analyst review", failures="", failure_rate="", worst_state_code="")
    analyst = analyst.rename(columns={"title": "issue"})
    log = pd.concat([analyst, rules], ignore_index=True)
    with st.container(horizontal=True, vertical_alignment="bottom"):
        search = st.text_input("Search issues", placeholder="for example, bail or 138", key="issue_search")
        severity = st.pills("Severity", ["High", "Medium", "Low", "Info"], selection_mode="multi", key="issue_severity")
        status = st.pills("Status", ["Open", "Mitigated", "Accepted"], selection_mode="multi", key="issue_status")
    if search:
        mask = log[["issue", "evidence", "treatment"]].apply(lambda col: col.str.contains(search, case=False, regex=False)).any(axis=1)
        log = log[mask]
    if severity:
        log = log[log["severity"].isin(severity)]
    if status:
        log = log[log["status"].isin(status)]
    st.dataframe(log[["issue_id", "source", "issue", "severity", "status", "evidence", "treatment"]], hide_index=True, height=620, alt="Issue log", column_config={
        "issue_id": "ID", "source": "Source", "issue": st.column_config.TextColumn("Issue", width="medium"), "severity": "Severity", "status": "Status",
        "evidence": st.column_config.TextColumn("Evidence or samples", width="large"), "treatment": st.column_config.TextColumn("Treatment", width="large"),
    })
    st.caption(f"{len(log)} issues shown. Samples use DDL's case ID only, and the linkable eCourts number was dropped at load.")

else:
    left, right = st.columns([3, 2], gap="large")
    with left:
        st.markdown("**How complete each state's records are**")
        show(C.coverage_heat(table("coverage_state_year")), f"Filings in each year as a share of the state's 2018 filings. Rows per year grow {F['cov_growth']:.1f} times nationally as records went digital, which is why flow rates use 2016-18 only.")
    with right:
        st.markdown("**DDL against NJDG**")
        show(C.share_scatter(table("coverage_vs_njdg")), f"Each state's share of open cases in DDL against its share of NJDG's 2026 pendency (correlation {F['cov_corr']:.2f}). Points on the line have the same share in both.")
        st.markdown("**Why every result uses one cut-off**")
        show(C.decisions_cliff(table("coverage_decisions_by_month")), "Recorded decisions fall by about 90% in early 2019 because only some courts were collected again later.")
        st.caption(f"No separate DDL data: {', '.join(F['q7_not_in_ddl'])}. Puducherry and Lakshadweep appear only as districts under Tamil Nadu and Kerala.")

st.caption(SOURCES)
