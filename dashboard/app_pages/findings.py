"""The findings: the plan's seven questions plus three more."""
import pandas as pd
import streamlit as st
from shared import DIMENSIONS, OUTPUTS, SOURCES, C, finding_block, findings, national_score, show, table

FX = findings()
F, TEXT = FX["figures"], FX["text"]

QUESTIONS = {
    "District map": "q5",
    "Where cases get stuck": "q1",
    "How long justice takes": "q2",
    "Which laws clog the system": "q3",
    "Do judge transfers slow cases": "q4",
    "Women in court": "q6",
    "When the backlog clears": "q7",
    "How cases end": "q8",
    "First hearing": "q9",
    "What drives delay": "q10",
}

st.title("Where Justice Gets Stuck")
st.markdown(
    f"Where and why Indian lower courts are delayed, from {F['total_rows'] / 1e6:.1f} million cases filed 2010-2018 "
    "(Development Data Lab)."
)
st.caption("Case data ends in 2018. 2026 figures are NJDG context. Nothing here describes current court performance.")

with st.container(horizontal=True):
    st.metric("Cases analysed", f"{F['total_rows'] / 1e6:.1f}M", help="Every case filed 2010-2018 in the DDL eCourts data.", border=True)
    st.metric("Open at end of 2018", f"{F['open_at_cutoff'] / 1e7:.2f} crore",
              help="Filed 2010-2018 and undecided on 31 Dec 2018. Older cases are not in the data.", border=True)
    st.metric("Median time to close", f"{F['q2_km_median']:,.0f} days",
              help=f"Kaplan-Meier, with open cases counted. Closed cases alone give {F['q2_naive_median']:,.0f} days.", border=True)
    st.metric("Pending in 2026 (NJDG)", f"{F['njdg_total'] / 1e7:.2f} crore",
              help="District and subordinate courts on 30 Jul 2026. Lok Sabha Q.3371, Annexure II.", border=True)

picked = st.segmented_control("Question", list(QUESTIONS), default="District map", label_visibility="collapsed", key="question")
key = QUESTIONS.get(picked, "q5")
st.subheader(TEXT[key]["question"])

if key == "q5":
    d = table("q5_districts").copy()
    ranked = d[~d["low_volume"] & ~d["suspect_closure_records"]].copy()
    states = sorted(d["state"].dropna().unique())
    left, right = st.columns([3, 2], gap="large")
    with left:
        with st.container(horizontal=True, vertical_alignment="bottom"):
            metric = st.selectbox("Metric", list(C.METRICS), key="map_metric")
            state = st.selectbox("State", ["All India"] + states, key="map_state")
        chosen = None if state == "All India" else state
        show_map = d.copy()
        show_map.loc[show_map["suspect_closure_records"], "low_volume"] = True  # shaded as no data
        show(C.district_map(show_map, metric, chosen), "Districts on 2011 boundaries. Grey means no usable data: no DDL rows, too few cases, or incomplete closure "
             "records. Boundaries: DataMeet (CC BY 4.0), for display only and not an official map.",
             f"Map of districts in {state} shaded by {metric.lower()}. The ranked table beside it gives the same figures.")
    with right:
        finding_block(TEXT["q5"])
        order = st.segmented_control("Ranking", ["Slowest", "Fastest"], default="Slowest", key="map_order", label_visibility="collapsed") or "Slowest"
        view = ranked if chosen is None else ranked[ranked["state"] == chosen]
        view = view.dropna(subset=["km_median_days"]).sort_values("km_median_days", ascending=order == "Fastest").head(12)
        st.dataframe(
            view[["district", "state", "km_median_days", "clearance_rate", "closed_2y_adjusted"]],
            hide_index=True, alt=f"{order} districts by median days to close",
            column_config={
                "district": "District (2011)",
                "state": "State",
                "km_median_days": st.column_config.NumberColumn("Median days", format="%,d"),
                "clearance_rate": st.column_config.NumberColumn("Clearance", format="percent", help="Closed ÷ filed, 2016-18. Below 100% the backlog grows."),
                "closed_2y_adjusted": st.column_config.NumberColumn("Closed in 2y", format="percent", help="Adjusted to the national mix of case types."),
            },
        )
        flagged = d[d["suspect_closure_records"]].sort_values(["state", "district"])
        if len(flagged):
            with st.expander(f"{len(flagged)} districts left off for incomplete closure records"):
                st.dataframe(flagged[["district", "state", "total_cases", "bail_closed_2y", "closed_2y_raw"]], hide_index=True, alt="Districts with incomplete closure records", column_config={
                    "district": "District (2011)", "state": "State", "total_cases": st.column_config.NumberColumn("Cases", format="%,d"),
                    "bail_closed_2y": st.column_config.NumberColumn("Bail closed in 2y", format="percent"),
                    "closed_2y_raw": st.column_config.NumberColumn("All closed in 2y", format="percent"),
                })

elif key == "q1":
    finding_block(TEXT["q1"])
    with st.container(horizontal=True, vertical_alignment="bottom"):
        family = st.segmented_control("Case family", ["All", "Criminal", "Civil"], default="All", key="q1_family") or "All"
        state = st.selectbox("State", ["All India"] + sorted(table("q1_stage_state")["state"].dropna().unique()), key="q1_state")
    if state != "All India":
        q = table("q1_stage_state")
        q = q[q["state"] == state].groupby("stage", as_index=False)["stuck_cases"].sum()
        note = f"{state}, all case families."
    elif family != "All":
        q = table("q1_stage_family")
        q = q[q["family"] == family].groupby("stage", as_index=False)["stuck_cases"].sum()
        note = f"{family} cases, India."
    else:
        q = table("q1_stage")[["stage", "stuck_cases"]]
        note = "All cases, India."
    q = q.assign(share=q["stuck_cases"] / q["stuck_cases"].sum())
    show(C.stage_bars(q, height=340), f"{note} Cases with no decision date, by the purpose of their last listed hearing.")

elif key == "q2":
    finding_block(TEXT["q2"])
    s = table("q2_km_summary")
    c = table("q2_km_curves")
    labels = {"Case type": "Case category", "State": "State", "Filing year": "Filing year"}
    dim_label = st.segmented_control("Compare by", list(labels) + ["What counts as closed"], default="Case type", key="q2_dim") or "Case type"
    if dim_label == "What counts as closed":
        curves = table("q2_sensitivity_transfer_curves")
        names = curves["grp"].unique().tolist()
        show(C.survival_lines(curves, names, highlight="All closures"), "A transfer moves a file without resolving the dispute. Counting transferred cases as still open raises the curve.")
        st.dataframe(table("q2_sensitivity_transfer")[["grp", "n", "closed", "km_median_days", "open_after_1y", "open_after_3y", "open_after_5y"]], hide_index=True,
                     alt="Survival summary under each definition of closure", column_config={
            "grp": "Definition", "n": st.column_config.NumberColumn("Cases", format="%,d"), "closed": st.column_config.NumberColumn("Closed", format="%,d"),
            "km_median_days": st.column_config.NumberColumn("Median days", format="%,d"),
            "open_after_1y": st.column_config.NumberColumn("Open after 1y", format="percent"),
            "open_after_3y": st.column_config.NumberColumn("Open after 3y", format="percent"),
            "open_after_5y": st.column_config.NumberColumn("Open after 5y", format="percent"),
        })
    else:
        dim = labels[dim_label]
        options = sorted(s[s["dimension"] == dim]["grp"].dropna().unique())
        defaults = {
            "Case category": ["Civil suit", "Cheque bounce (NI Act)", "Criminal trial (magistrate)"],
            "State": ["Bihar", "Maharashtra", "Karnataka"],
            "Filing year": ["2010", "2014", "2017"],
        }[dim]
        chosen = st.multiselect("Groups (up to three, plus all cases)", options, default=defaults, max_selections=3, key=f"q2_groups_{dim}")
        # A group keeps its colour while it stays selected, so changing the selection never repaints the others.
        slots = st.session_state.setdefault(f"q2_slots_{dim}", {})
        for g in list(slots):
            if g not in chosen:
                del slots[g]
        for g in chosen:
            if g not in slots:
                slots[g] = next(i for i in range(3) if i not in slots.values())
        curves = pd.concat([c[c["dimension"] == "All cases"], c[(c["dimension"] == dim) & (c["grp"].isin(chosen))]])
        show(C.survival_lines(curves, ["All cases"] + chosen, slots=slots), "Kaplan-Meier curves. Cases still open count until 31 Dec 2018 and then leave the risk set, so they are never dropped. "
             "A line stops where follow-up stops.")
        tbl = pd.concat([s[s["dimension"] == "All cases"], s[(s["dimension"] == dim) & (s["grp"].isin(chosen))]])
        st.dataframe(tbl[["grp", "n", "km_median_days", "naive_median_days", "open_after_1y", "open_after_3y", "open_after_5y"]], hide_index=True,
                     alt="Median days and share still open, by group", column_config={
            "grp": "Group", "n": st.column_config.NumberColumn("Cases", format="%,d"),
            "km_median_days": st.column_config.NumberColumn("Median days, open counted", format="%,d"),
            "naive_median_days": st.column_config.NumberColumn("Median days, closed only", format="%,d"),
            "open_after_1y": st.column_config.NumberColumn("Open after 1y", format="percent"),
            "open_after_3y": st.column_config.NumberColumn("Open after 3y", format="percent"),
            "open_after_5y": st.column_config.NumberColumn("Open after 5y", format="percent"),
        })

elif key == "q3":
    finding_block(TEXT["q3"])
    acts = table("q3_acts")
    show(C.act_bubbles(acts), "Named acts with at least 1 lakh cases. Up and right is both common and slow; a larger bubble means more open cases.")
    st.markdown("**Testing the Section 138 claim**")
    with st.container(horizontal=True):
        st.metric("NI Act, open end-2018 (DDL)", f"{F['q3_ni_open'] / 1e5:.1f} lakh", help="Filed 2010-2018, identified by act.", border=True)
        st.metric("Same, adding case-type labels", f"{F['q3_ni_open_widest'] / 1e5:.1f} lakh", help="Also counts cases whose type label says NI Act.", border=True)
        st.metric("Supreme Court, end-2019", f"{F['q3_sc_benchmark'] / 1e5:.1f} lakh", help="In Re: Expeditious Trial of Cases under s.138, 16 Apr 2021. Includes filings before 2010 and during 2019.", border=True)
        st.metric("eCourtsIndia index, Oct 2026", f"{F['q3_blog_benchmark'] / 1e5:.0f} lakh+", help="A full-text count that includes appeals and revisions, so it is not comparable.", border=True)
    st.caption("DDL is a floor: it leaves out older cases, and act records are thin for early years. The figures differ in date and scope, so read them as an order of magnitude.")
    view = st.segmented_control("Table", ["Acts", "Largest sections"], default="Acts", key="q3_table", label_visibility="collapsed") or "Acts"
    if view == "Acts":
        st.dataframe(acts.sort_values("open_at_cutoff", ascending=False)[["act_canonical", "act_family", "n", "open_at_cutoff", "share_of_open", "km_median_days", "naive_median_days"]], hide_index=True,
                     alt="Cases, open cases and median days by act", column_config={
            "act_canonical": "Act", "act_family": "Family", "n": st.column_config.NumberColumn("Cases", format="%,d"),
            "open_at_cutoff": st.column_config.NumberColumn("Open end-2018", format="%,d"),
            "share_of_open": st.column_config.NumberColumn("Share of open", format="percent"),
            "km_median_days": st.column_config.NumberColumn("Median days, open counted", format="%,d"),
            "naive_median_days": st.column_config.NumberColumn("Median days, closed only", format="%,d"),
        })
    else:
        st.dataframe(table("q3_sections").head(40), hide_index=True, alt="Largest sections by case volume", column_config={
            "act_canonical": "Act", "section_norm": "Section", "n": st.column_config.NumberColumn("Cases", format="%,d"),
            "open_at_cutoff": st.column_config.NumberColumn("Open end-2018", format="%,d"),
            "naive_median_days": st.column_config.NumberColumn("Median days, closed only", format="%,d"),
        })
        st.caption("Sections come from free text: each label is read as its first number, so a case filed under several sections counts once, under the first.")

elif key == "q4":
    finding_block(TEXT["q4"])
    pairs, tenure = table("q4_pairs"), table("q4_tenure_pairs")
    pairs = pairs[pairs["case_category"].isin(C.TRIAL_CATEGORIES)]
    tenure = tenure[tenure["case_category"].isin(C.TRIAL_CATEGORIES)]
    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("**The plain comparison looks damning**")
        show(C.judge_boxes(pairs, width="container"), f"{len(pairs):,} matched groups of trials in the same district, case type and filing year. Boxes show the middle half, lines the 5th to 95th percentile. Biased: a slow case has more time in which to see a transfer.")
    with right:
        st.markdown("**The fairer test shows a modest effect**")
        show(C.tenure_boxes(tenure, width="container"), f"{len(tenure):,} matched groups of trials, closed and open alike. White line and label: case-weighted average. The judge's time left at filing cannot be caused by the case being slow.")
    rows = pd.DataFrame([{"Case type": k, "Judge stays 2+ years": v["stays"], "Judge leaves within 6 months": v["leaves"], "Gap (points)": v["gap"] * 100}
                         for k, v in F["q4_tenure_by_category"].items()]).sort_values("Gap (points)")
    st.dataframe(rows, hide_index=True, alt="Share closed within two years, by how long the judge had left", column_config={
        "Judge stays 2+ years": st.column_config.NumberColumn(format="percent"),
        "Judge leaves within 6 months": st.column_config.NumberColumn(format="percent"),
        "Gap (points)": st.column_config.NumberColumn(format="%+.1f"),
    })
    st.caption(f"Share of cases closed within two years, in case types with at least 100 matched groups. For scale, a judge stays a median of {F['q4_tenure_median_days']:,.0f} days in one post.")

elif key == "q6":
    finding_block(TEXT["q6"])
    w = table("q6_women_state")
    national = w.groupby("role", as_index=False)[["classified", "women", "total"]].sum()
    national["women_share"] = national["women"] / national["classified"]
    left, right = st.columns([2, 3], gap="large")
    with left:
        show(C.women_roles(national), "Share of women among cases with a classifiable name. The classifiable share differs widely by role.")
        st.dataframe(national.assign(classified_share=national["classified"] / national["total"])[["role", "women_share", "classified_share"]], hide_index=True,
                     alt="Women's share and classifiable share by role", column_config={
            "role": "Role", "women_share": st.column_config.NumberColumn("Women", format="percent"),
            "classified_share": st.column_config.NumberColumn("Names classifiable", format="percent"),
        })
        show(C.women_trend(table("q6_women_year")), "By filing year. Early years have fewer records, and the 2018 rise among petitioners' advocates may reflect changes in how names were entered.")
    with right:
        role = st.segmented_control("Role", ["Petitioner", "Defendant", "Petitioner's advocate", "Defendant's advocate"], default="Petitioner's advocate", key="q6_role") or "Petitioner's advocate"
        show(C.women_stacks(w, role, height=640), "States with at least 20,000 cases, sorted by women's share of classified names.")

elif key == "q7":
    finding_block(TEXT["q7"])
    q7 = table("q7_backlog")
    show(C.backlog_bars(q7), "2026 pendency (NJDG) divided by 2016-18 disposals (DDL). States with under 20,000 pending cases are left out of the chart.")

    st.markdown("**Try a scenario**")
    st.caption("Starts from NJDG's July 2026 pendency and each state's 2016-18 flows. A scenario to explore, not a forecast.")
    usable = q7[q7["in_ddl"]].sort_values("pending_total", ascending=False)
    controls, outcome = st.columns([2, 3], gap="large")
    with controls:
        state = st.selectbox("State", usable["njdg_state"].tolist(), index=usable["njdg_state"].tolist().index("Bihar"), key="scenario_state")
        extra = st.slider("Change in disposals per year", -20, 100, 25, step=5, format="%d%%", key="scenario_disposals")
        filings = st.slider("Change in filings per year", -50, 50, 0, step=5, format="%d%%", key="scenario_filings")
    row = usable[usable["njdg_state"] == state].iloc[0]
    stock, filed, closed = float(row["pending_total"]), float(row["filed_per_year"]) * (1 + filings / 100), float(row["closed_per_year"]) * (1 + extra / 100)
    net = closed - filed
    horizon = list(range(0, 21))
    projection = pd.DataFrame({"year": horizon, "pending": [max(0.0, stock - net * y) for y in horizon]})
    needed = (filed + stock / 10) / float(row["closed_per_year"]) - 1
    with outcome:
        with st.container(horizontal=True):
            st.metric("Years to clear", f"{stock / net:,.1f}" if net > 0 else "Never", help="Pending cases divided by disposals minus filings.", border=True)
            st.metric("Pending after 10 years", f"{max(0.0, stock - net * 10) / 1e5:,.1f} lakh", border=True)
            st.metric("Disposals rise to clear in 10 years", f"{needed:+.0%}", help="Against 2016-18 disposals, at the filings chosen here.", border=True)
        show(C.scenario_line(projection), f"{state}: pending cases under this scenario.")
    st.dataframe(q7.sort_values("years_of_disposals_njdg_stock", ascending=False)[
        ["njdg_state", "pending_total", "pending_over_10y", "pending_5_to_10y", "filed_per_year", "closed_per_year", "clearance_rate", "years_of_disposals_njdg_stock", "never_clears"]],
        hide_index=True, alt="Pendency, flows and years of disposals by state", column_config={
            "njdg_state": "State", "pending_total": st.column_config.NumberColumn("Pending, 2026", format="%,d"),
            "pending_over_10y": st.column_config.NumberColumn("Over 10 years", format="%,d"),
            "pending_5_to_10y": st.column_config.NumberColumn("5-10 years", format="%,d"),
            "filed_per_year": st.column_config.NumberColumn("Filed per year", format="%,d"),
            "closed_per_year": st.column_config.NumberColumn("Closed per year", format="%,d"),
            "clearance_rate": st.column_config.NumberColumn("Clearance", format="percent"),
            "years_of_disposals_njdg_stock": st.column_config.NumberColumn("Years of disposals", format="%.1f"),
            "never_clears": st.column_config.CheckboxColumn("Filings outran disposals"),
        })

elif key == "q8":
    finding_block(TEXT["q8"])
    o = table("q8_outcomes")
    dim_label = st.segmented_control("Compare by", ["Case type", "State"], default="Case type", key="q8_dim") or "Case type"
    dim = {"Case type": "Case category", "State": "State"}[dim_label]
    view = o[o["dimension"] == dim]
    if dim == "State":
        large = table("q2_km_summary").query("dimension == 'State' and n >= 200000")["grp"]
        view = view[view["grp"].isin(large)]
    show(C.outcome_stacks(view, height=max(280, 22 * view["grp"].nunique())), "Closed cases only, sorted by share decided on merits. 'Vague or missing' covers labels such as 'disposed', which do not say how a case ended.")
    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("**How long each ending takes**")
        national = o[o["dimension"] == "All cases"].sort_values("share", ascending=False)
        st.dataframe(national[["outcome", "closed_cases", "share", "median_days"]], hide_index=True, alt="Closed cases and median days by outcome", column_config={
            "outcome": "Outcome", "closed_cases": st.column_config.NumberColumn("Closed cases", format="%,d"),
            "share": st.column_config.NumberColumn("Share", format="percent"), "median_days": st.column_config.NumberColumn("Median days, closed only", format="%,d"),
        })
        st.caption("Closed cases only, so these medians understate how long cases take. Use them to compare endings with each other.")
    with right:
        st.markdown("**Verdicts in criminal cases**")
        v = table("q8_verdicts")
        v = v[v["dimension"] != "State"].sort_values("closed_cases", ascending=False)
        st.dataframe(v[["grp", "closed_cases", "verdict_share", "conviction_share"]], hide_index=True, alt="Share of criminal closures with a verdict, and conviction share", column_config={
            "grp": "Case type", "closed_cases": st.column_config.NumberColumn("Closed", format="%,d"),
            "verdict_share": st.column_config.NumberColumn("Closed with a verdict", format="percent", help="Conviction or acquittal, among all closures."),
            "conviction_share": st.column_config.NumberColumn("Convicted, of verdicts", format="percent", help="Includes guilty pleas and fines. Not a measure of guilt or of court quality."),
        })

elif key == "q9":
    finding_block(TEXT["q9"])
    h = table("q9_first_hearing")
    left, right = st.columns(2, gap="large")
    with left:
        states = h[(h["dimension"] == "State") & (h["n"] >= 20_000)]
        show(C.first_hearing_bars(states, height=max(420, 20 * len(states))), "States with at least 20,000 cases that have a usable first-hearing date.")
    with right:
        st.markdown("**By case type**")
        st.dataframe(h[h["dimension"] == "Case category"].sort_values("median_days", ascending=False)[["grp", "median_days", "p90_days", "within_30_days"]], hide_index=True, alt="Days to first hearing by case type", column_config={
            "grp": "Case type", "median_days": st.column_config.NumberColumn("Median days", format="%,d"),
            "p90_days": st.column_config.NumberColumn("90th percentile", format="%,d"),
            "within_30_days": st.column_config.NumberColumn("Within 30 days", format="percent"),
        })

elif key == "q10":
    finding_block(TEXT["q10"])
    m = table("model_hazard_ratios")
    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("**By state, compared with Maharashtra**")
        show(C.hazard_forest(m[m["group"] == "State"]), "Hazard ratios with 95% intervals. Right of the line, a case closes faster than a comparable case in Maharashtra; left, slower.")
    with right:
        st.markdown("**By case type, compared with magistrate trials**")
        show(C.hazard_forest(m[m["group"] == "Case type"]), "Bail and traffic matters close far faster than a magistrate trial, even with state and filing year held constant.")
        st.markdown("**People involved**")
        show(C.hazard_forest(m[m["group"] == "People involved"]), "A named advocate often marks a contested case, so these are associations and say nothing about whether having a lawyer causes delay.")

# ------------------------------------------------------------------ how to read, quality, sources
st.divider()
left, right = st.columns([3, 2], gap="large")
with left:
    st.markdown("**How to read this**")
    st.markdown(
        f"""
- **Open means undecided on 31 Dec 2018.** Recorded decisions fall by about 90% in early 2019 because only some courts were collected again, so one shared cut-off keeps courts comparable.
- **Early years are thin.** Rows per year rise {F['cov_growth']:.1f}x from 2010 to 2018 as records went digital. Flow rates use 2016-18 only.
- **Older cases are missing.** Only cases filed from 2010 appear, so backlogs and disposals are both understated.
- **Two independent checks support the picture.** DDL's open cases by state track NJDG's 2026 pendency shares (correlation {F['cov_corr']:.2f}), and states slow here also hold NJDG's oldest cases (rank correlation {F['cov_age_spearman']:.2f}, {F['cov_age_states']} large states).
- **These are associations.** Nothing here proves why a court is slow.
"""
    )
with right:
    st.markdown("**Data quality**")
    scores = table("dq_state_scores")
    st.caption(f"{F.get('dq_rules', 0)} rules. Case-weighted average across states. A low score means hard-to-use records, not a poor court.")
    for row in (DIMENSIONS[:2], [DIMENSIONS[2], DIMENSIONS[4]]):
        for column, dim in zip(st.columns(2), row):
            column.metric(dim, f"{national_score(scores, dim):.1%}", border=True)
    st.page_link("app_pages/data_quality.py", label="Open the data-quality explorer", icon=":material/rule:")
    with st.container(horizontal=True):
        book = OUTPUTS / "data_quality_scorecard.xlsx"
        if book.exists():
            st.download_button("Data-quality scorecard (Excel)", book.read_bytes(), file_name=book.name, icon=":material/table:",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        brief = OUTPUTS / "where_justice_gets_stuck_brief.pdf"
        if brief.exists():
            st.download_button("Two-page brief (PDF)", brief.read_bytes(), file_name=brief.name, icon=":material/description:", mime="application/pdf")

st.caption(SOURCES)
