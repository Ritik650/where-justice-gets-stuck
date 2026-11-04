"""Where Justice Gets Stuck: the dashboard.

Layout and design tokens come from the Stitch designs recorded in docs/design/stitch_design_tokens.md. The app reads
only the small aggregate tables in data/mart, so it runs without the row-level data.

Run from the project root:  streamlit run dashboard/app.py --server.address 127.0.0.1
"""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

st.set_page_config(page_title="Where Justice Gets Stuck", page_icon=":material/balance:", layout="wide")

page = st.navigation(
    [
        st.Page("app_pages/findings.py", title="Findings", icon=":material/insights:", default=True),
        st.Page("app_pages/state_profile.py", title="State profile", icon=":material/location_on:"),
        st.Page("app_pages/data_quality.py", title="Data quality", icon=":material/rule:"),
        st.Page("app_pages/methods.py", title="Methods", icon=":material/menu_book:"),
    ],
    position="top",
)
page.run()
