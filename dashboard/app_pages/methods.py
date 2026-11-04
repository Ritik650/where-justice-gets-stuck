"""How the analysis works, rendered from docs/methods.md so the page and the file cannot disagree."""
import streamlit as st
from shared import OUTPUTS, ROOT, SOURCES

text = (ROOT / "docs" / "methods.md").read_text(encoding="utf8")
left, right = st.columns([3, 1], gap="large")
with left:
    st.markdown(text)
with right:
    st.markdown("**Downloads**")
    brief = OUTPUTS / "where_justice_gets_stuck_brief.pdf"
    if brief.exists():
        st.download_button("Two-page brief", brief.read_bytes(), file_name=brief.name, icon=":material/description:", mime="application/pdf", width="stretch")
    book = OUTPUTS / "data_quality_scorecard.xlsx"
    if book.exists():
        st.download_button("Excel scorecard", book.read_bytes(), file_name=book.name, icon=":material/table:",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")
    mapping = ROOT / "data" / "mart" / "map_act.csv"
    if mapping.exists():
        st.download_button("Act-name mapping", mapping.read_bytes(), file_name=mapping.name, icon=":material/rule:", mime="text/csv", width="stretch")
    st.caption("The Act-name mapping lists every raw label and the act it was mapped to.")
st.caption(SOURCES)
