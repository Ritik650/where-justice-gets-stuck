"""One definition of every chart, used by the dashboard and exported to PNG for the brief.

Colour follows docs/design/stitch_design_tokens.md. Categorical colours were checked with a colour-vision
validator: the first three pass on all pairs, and the fourth is only used with direct labels.
"""
from __future__ import annotations

import json
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
GEO = ROOT / "data" / "geo"

INK = "#18181B"
BODY = "#27272A"
MUTED = "#71717A"
HAIRLINE = "#E5E3DF"
PANEL = "#FFFFFF"
ACCENT = "#1E40AF"
CONTEXT = "#C9C7C1"
NO_DATA = "#EFEDE8"
MAP_NO_DATA = "#D5D3CD"
CATEGORICAL = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
SEQUENTIAL = ["#DBEAFE", "#9EC5F4", "#5598E7", "#256ABF", "#1E40AF", "#0D366B"]
DIVERGING = ["#B3261E", "#E08A82", "#F0EFEC", "#86B6EF", "#1E40AF"]
FONT = "Inter, Arial, sans-serif"

alt.data_transformers.disable_max_rows()

STAGE_SHORT = {
    "1 Admission / first hearing": "Admission / first hearing",
    "2 Summons / notice / service": "Summons, notice, service",
    "3 Appearance of parties": "Appearance of parties",
    "4 Pleadings / charge": "Pleadings or charge",
    "5 Evidence": "Evidence",
    "6 Arguments": "Arguments",
    "7 Judgment / orders": "Judgment or orders",
    "8 Interim / miscellaneous": "Interim or miscellaneous",
    "9 Lok Adalat / settlement": "Lok Adalat or settlement",
    "10 Unspecified hearing": "Unspecified hearing",
    "11 Not a stage / blank": "Blank or not a stage",
}
STAGE_DISPLAY_ORDER = list(STAGE_SHORT.values())
GETTING_TO_COURT = {"Admission / first hearing", "Summons, notice, service", "Appearance of parties"}
TRIAL_CATEGORIES = ["Criminal trial (magistrate)", "Sessions trial"]


def lakh(n: float) -> str:
    return f"{n / 100_000:,.1f} lakh"


def styled(chart: alt.TopLevelMixin, title: str | None = None, subtitle: str | None = None):
    """Apply the shared look. Titles state the finding, so they are passed in by the caller."""
    if title:
        chart = chart.properties(title=alt.TitleParams(
            text=title, subtitle=subtitle or "", anchor="start", font=FONT, fontSize=14, fontWeight=600, color=INK,
            subtitleFont=FONT, subtitleFontSize=11, subtitleColor=MUTED, offset=10,
        ))
    return (
        chart.configure(background=PANEL, font=FONT)
        .configure_view(stroke=None)
        .configure_axis(
            labelFont=FONT, titleFont=FONT, labelColor=MUTED, titleColor=MUTED, labelFontSize=10, titleFontSize=10,
            titleFontWeight=400, gridColor=HAIRLINE, domainColor=HAIRLINE, tickColor=HAIRLINE, gridWidth=0.75,
        )
        .configure_legend(labelFont=FONT, titleFont=FONT, labelColor=BODY, titleColor=MUTED, labelFontSize=10,
                          titleFontSize=10, titleFontWeight=400, symbolStrokeWidth=2)
    )


def stage_bars(q1: pd.DataFrame, width="container", height=300):
    d = q1.assign(stage_short=q1["stage"].map(STAGE_SHORT))
    d["group"] = np.where(d["stage_short"].isin(GETTING_TO_COURT), "Getting parties to court", "Other stages")
    d["label"] = [f"{lakh(n)}  ({s:.0%})" for n, s in zip(d["stuck_cases"], d["share"])]
    y = alt.Y("stage_short:N", sort=STAGE_DISPLAY_ORDER, title=None, axis=alt.Axis(labelLimit=180, ticks=False, domain=False, grid=False))
    x = alt.X("stuck_cases:Q", title="Cases that never closed", axis=alt.Axis(format="~s", grid=True, tickCount=5),
              scale=alt.Scale(domainMax=float(d["stuck_cases"].max()) * 1.32))
    bars = alt.Chart(d).mark_bar(cornerRadiusEnd=4, height=14).encode(
        x=x, y=y,
        color=alt.Color("group:N", title=None, scale=alt.Scale(domain=["Getting parties to court", "Other stages"], range=[ACCENT, CONTEXT]),
                        legend=alt.Legend(orient="bottom", direction="horizontal")),
        tooltip=[alt.Tooltip("stage_short:N", title="Stage"), alt.Tooltip("stuck_cases:Q", title="Cases", format=",.0f"),
                 alt.Tooltip("share:Q", title="Share", format=".1%")],
    )
    labels = alt.Chart(d).mark_text(align="left", dx=5, font=FONT, fontSize=10, color=BODY).encode(x=x, y=y, text="label:N")
    return (bars + labels).properties(width=width, height=height)


def survival_lines(curves: pd.DataFrame, groups: list[str], width="container", height=300, highlight="All cases", slots: dict | None = None):
    """Curves for the named groups. `slots` pins each group to a colour, so filtering never repaints a line."""
    d = curves[curves["grp"].isin(groups)].dropna(subset=["share_open"]).copy()
    d["years"] = d["days"] / 365.25
    ordered = [g for g in groups if g != highlight]
    domain = ([highlight] if highlight in groups else []) + ordered
    slots = slots or {g: i for i, g in enumerate(ordered)}
    colours = ([INK] if highlight in groups else []) + [CATEGORICAL[slots[g]] for g in ordered]
    x = alt.X("years:Q", title="Years since filing", scale=alt.Scale(domain=[0, 9.2], nice=False), axis=alt.Axis(tickCount=9, grid=False))
    y = alt.Y("share_open:Q", title="Share of cases still open", scale=alt.Scale(domain=[0, 1]), axis=alt.Axis(format=".0%", tickCount=5))
    colour = alt.Color("grp:N", title=None, scale=alt.Scale(domain=domain, range=colours), legend=alt.Legend(orient="bottom", direction="horizontal", columns=3, labelLimit=220))
    lines = alt.Chart(d).mark_line(strokeWidth=2).encode(x=x, y=y, color=colour)
    hit = alt.selection_point(fields=["days"], nearest=True, on="pointerover", empty=False, clear="pointerout")
    dots = alt.Chart(d).mark_point(size=40, filled=True, opacity=0).encode(
        x=x, y=y, color=alt.Color("grp:N", scale=alt.Scale(domain=domain, range=colours), legend=None),
        opacity=alt.condition(hit, alt.value(1), alt.value(0)),
        tooltip=[alt.Tooltip("grp:N", title="Group"), alt.Tooltip("years:Q", title="Years since filing", format=".1f"),
                 alt.Tooltip("share_open:Q", title="Still open", format=".1%")],
    ).add_params(hit)
    half = alt.Chart(pd.DataFrame({"y": [0.5]})).mark_rule(color=MUTED, strokeWidth=0.75).encode(y="y:Q")
    half_text = alt.Chart(pd.DataFrame({"y": [0.5], "x": [9.2], "t": ["half still open"]})).mark_text(
        align="right", baseline="bottom", dy=-3, font=FONT, fontSize=10, color=MUTED).encode(x="x:Q", y="y:Q", text="t:N")
    return (half + half_text + lines + dots).properties(width=width, height=height)


HIDE_FROM_BUBBLES = {"No act record", "Blank or unusable label", "Other / unmapped", "Implausible act (likely dropdown default)"}


def act_bubbles(acts: pd.DataFrame, width="container", height=340, min_cases=100_000):
    d = acts[~acts["act_canonical"].isin(HIDE_FROM_BUBBLES) & (acts["n"] >= min_cases)].dropna(subset=["km_median_days"]).copy()
    d["years_median"] = d["km_median_days"] / 365.25
    d["short"] = d["act_canonical"].str.replace(" Act", "", regex=False).str.replace("Protection of Women from Domestic Violence", "Domestic Violence", regex=False) \
        .str.replace("Narcotic Drugs and Psychotropic Substances", "NDPS", regex=False)
    x = alt.X("n:Q", title="Cases filed 2010-2018 (log scale)", scale=alt.Scale(type="log", nice=False, domain=[80_000, 40_000_000]), axis=alt.Axis(format="~s", values=[100_000, 1_000_000, 10_000_000]))
    y = alt.Y("years_median:Q", title="Median years to close, open cases counted", scale=alt.Scale(zero=True))
    points = alt.Chart(d).mark_circle(color=ACCENT, opacity=0.65, stroke=PANEL, strokeWidth=1).encode(
        x=x, y=y, size=alt.Size("open_at_cutoff:Q", title="Open at end of 2018", scale=alt.Scale(range=[20, 1400]), legend=alt.Legend(orient="bottom", direction="horizontal", format="~s")),
        tooltip=[alt.Tooltip("act_canonical:N", title="Act"), alt.Tooltip("n:Q", title="Cases", format=",.0f"),
                 alt.Tooltip("open_at_cutoff:Q", title="Open at end of 2018", format=",.0f"),
                 alt.Tooltip("years_median:Q", title="Median years", format=".1f")],
    )
    # Labelled by hand: these acts crowd each other, and an unplaced label would land on its neighbour.
    placed = {
        "Indian Penal Code": ("Indian Penal Code", "center", 0, 27),
        "Code of Civil Procedure": ("Code of Civil Procedure", "center", 0, -24),
        "Negotiable Instruments Act": ("Negotiable Instruments", "center", -6, -18),
        "Motor Vehicles Act": ("Motor Vehicles and CrPC", "center", 0, -15),
        "State Prohibition Acts": ("State Prohibition", "center", 0, -10),
        "Specific Relief Act": ("Specific Relief", "left", 8, -5),
        "Arms Act": ("Arms", "right", -7, 3),
        "Forest / Wildlife Acts": ("Forest and wildlife", "left", 7, 0),
    }
    layers = [points]
    for act, (text, align, dx, dy) in placed.items():
        row = d[d["act_canonical"] == act]
        if len(row):
            layers.append(alt.Chart(row.assign(tag=text)).mark_text(align=align, dx=dx, dy=dy, font=FONT, fontSize=10, color=BODY).encode(x=x, y=y, text="tag:N"))
    return alt.layer(*layers).properties(width=width, height=height)


def judge_boxes(pairs: pd.DataFrame, width=210, height=280):
    """Paired boxes: each observation is one district x case type x filing year, seen both ways."""
    rows = []
    for label, col in (("Same judge|throughout", "median_same"), ("Judge|changed", "median_changed")):
        v = pairs[col].dropna() / 365.25
        q1, med, q3 = np.percentile(v, [25, 50, 75])
        low, high = np.percentile(v, [5, 95])
        rows.append({"group": label, "low": low, "q1": q1, "median": med, "q3": q3, "high": high, "n": len(v)})
    d = pd.DataFrame(rows)
    order = ["Same judge|throughout", "Judge|changed"]
    x = alt.X("group:N", sort=order, title=None, axis=alt.Axis(labelAngle=0, ticks=False, grid=False, labelExpr="split(datum.label, '|')"))
    scale = alt.Scale(domain=[0, float(d["high"].max()) * 1.05])
    whisker = alt.Chart(d).mark_rule(color=MUTED, strokeWidth=1).encode(
        x=x, y=alt.Y("low:Q", title="Median years to close, per group", scale=scale), y2="high:Q")
    box = alt.Chart(d).mark_bar(size=32, color=ACCENT, opacity=0.8).encode(
        x=x, y=alt.Y("q1:Q", scale=scale), y2="q3:Q",
        tooltip=[alt.Tooltip("group:N", title="Group"), alt.Tooltip("median:Q", title="Median of medians (years)", format=".2f"),
                 alt.Tooltip("q1:Q", title="25th percentile", format=".2f"), alt.Tooltip("q3:Q", title="75th percentile", format=".2f"),
                 alt.Tooltip("n:Q", title="Paired groups", format=",.0f")],
    )
    tick = alt.Chart(d).mark_tick(color=PANEL, thickness=2, size=32).encode(x=x, y=alt.Y("median:Q", scale=scale))
    text = alt.Chart(d).mark_text(align="left", dx=18, font=FONT, fontSize=10, color=BODY, fontWeight=600).encode(
        x=x, y=alt.Y("median:Q", scale=scale), text=alt.Text("median:Q", format=".1f"))
    return (whisker + box + tick + text).properties(width=width, height=height)


def tenure_boxes(tenure: pd.DataFrame, width=210, height=280):
    """The fairer test: share closed within two years, by how long the filing judge had left."""
    rows = []
    for label, col, weight in (("Judge stays|2+ years", "closed_2y_stays", "n_stays"), ("Judge leaves|within 6 months", "closed_2y_leaves", "n_leaves")):
        v = tenure[col].dropna()
        q1, q3 = np.percentile(v, [25, 75])
        low, high = np.percentile(v, [5, 95])
        # One set of weights for both groups, so the gap between the labels equals the gap in the text.
        weighted = float(np.average(tenure[col], weights=tenure["n_stays"] + tenure["n_leaves"]))
        rows.append({"group": label, "low": low, "q1": q1, "weighted": weighted, "q3": q3, "high": high})
    d = pd.DataFrame(rows)
    order = ["Judge stays|2+ years", "Judge leaves|within 6 months"]
    x = alt.X("group:N", sort=order, title=None, axis=alt.Axis(labelAngle=0, ticks=False, grid=False, labelExpr="split(datum.label, '|')"))
    scale = alt.Scale(domain=[0, 1])
    whisker = alt.Chart(d).mark_rule(color=MUTED, strokeWidth=1).encode(
        x=x, y=alt.Y("low:Q", title="Share closed within two years", scale=scale, axis=alt.Axis(format=".0%")), y2="high:Q")
    box = alt.Chart(d).mark_bar(size=32, color=ACCENT, opacity=0.8).encode(
        x=x, y=alt.Y("q1:Q", scale=scale), y2="q3:Q",
        tooltip=[alt.Tooltip("group:N", title="Filing judge"), alt.Tooltip("weighted:Q", title="Closed within 2 years, case-weighted", format=".1%")],
    )
    tick = alt.Chart(d).mark_tick(color=PANEL, thickness=2, size=32).encode(x=x, y=alt.Y("weighted:Q", scale=scale))
    text = alt.Chart(d).mark_text(align="left", dx=18, font=FONT, fontSize=10, color=BODY, fontWeight=600).encode(
        x=x, y=alt.Y("weighted:Q", scale=scale), text=alt.Text("weighted:Q", format=".0%"))
    return (whisker + box + tick + text).properties(width=width, height=height)


def load_geo(name: str = "india_districts_2011.geojson") -> dict:
    return json.loads((GEO / name).read_text())


METRICS = {
    "Median years to close": dict(column="median_years", fmt=".1f", kind="sequential", legend="Median years"),
    "Clearance rate, 2016-18": dict(column="clearance_rate", fmt=".0%", kind="diverging", legend="Closed / filed"),
    "New cases per lakh people, per year": dict(column="filed_per_lakh_year", fmt=",.0f", kind="sequential", legend="Per lakh, per year"),
    "Closed within 2 years, mix-adjusted": dict(column="closed_2y_adjusted", fmt=".0%", kind="sequential_reverse", legend="Share closed"),
}


def district_map(districts: pd.DataFrame, metric: str, state: str | None = None, width="container", height=560):
    spec = METRICS[metric]
    d = districts.copy()
    d["median_years"] = d["km_median_days"] / 365.25
    column = spec["column"]
    by_id = d.set_index("unit_id")
    districts_geo = load_geo()
    features = []
    for f in districts_geo["features"]:
        uid = f["properties"]["unit_id"]
        props = dict(f["properties"])
        if uid in by_id.index:
            row = by_id.loc[uid]
            value = row[column]
            props["value"] = None if pd.isna(value) or row["low_volume"] else float(value)
            props["cases"] = int(row["total_cases"])
            props["state_ddl"] = row["state"]
            props["reason"] = "Too few cases or incomplete closure records" if row["low_volume"] else "This measure is not reached in the data"
        else:
            props["value"] = None
            props["cases"] = 0
            props["state_ddl"] = None
            props["reason"] = "No cases in the DDL data"
        if state and props.get("state_ddl") != state:
            continue
        features.append({"type": "Feature", "properties": props, "geometry": f["geometry"]})
    with_value = [f for f in features if f["properties"]["value"] is not None]
    without_value = [f for f in features if f["properties"]["value"] is None]

    values = pd.Series([f["properties"]["value"] for f in with_value], dtype=float)
    if spec["kind"] == "diverging":
        # Interpolated in RGB so the scale runs blue to red through grey, with no green on the way.
        scale = alt.Scale(domain=[0.6, 0.8, 1.0, 1.1, 1.2], range=DIVERGING, clamp=True, interpolate="rgb")
    elif spec["kind"] == "sequential_reverse":
        scale = alt.Scale(domain=[float(values.quantile(0.02)), float(values.quantile(0.98))], range=list(reversed(SEQUENTIAL)), clamp=True, interpolate="rgb")
    else:
        scale = alt.Scale(domain=[float(values.quantile(0.02)), float(values.quantile(0.98))], range=SEQUENTIAL, clamp=True, interpolate="rgb")

    # Two layers, so a district with no value can never pick up a colour from the scale and read as "fast".
    missing = alt.Chart(alt.Data(values=without_value)).mark_geoshape(fill=MAP_NO_DATA, stroke=PANEL, strokeWidth=0.25).encode(
        tooltip=[alt.Tooltip("properties.name:N", title="District (2011)"), alt.Tooltip("properties.state:N", title="State"),
                 alt.Tooltip("properties.reason:N", title="Not shown because")],
    ).project("mercator")
    shaded = alt.Chart(alt.Data(values=with_value)).mark_geoshape(stroke=PANEL, strokeWidth=0.25).encode(
        # The Arabian Sea is empty on the national map. A zoomed state fills its frame, so the legend moves outside.
        color=alt.Color("properties.value:Q", scale=scale, title=spec["legend"],
                        legend=alt.Legend(orient="right" if state else "bottom-left", direction="vertical", format=spec["fmt"], gradientLength=85, gradientThickness=10)),
        tooltip=[alt.Tooltip("properties.name:N", title="District (2011)"), alt.Tooltip("properties.state:N", title="State"),
                 alt.Tooltip("properties.value:Q", title=metric, format=spec["fmt"]), alt.Tooltip("properties.cases:Q", title="Cases filed 2010-18", format=",.0f")],
    ).project("mercator")
    layers = ([missing] if without_value else []) + [shaded]
    if not state:
        outline = load_geo("india_states_2011.geojson")
        layers.append(alt.Chart(alt.Data(values=outline["features"])).mark_geoshape(filled=False, stroke=MUTED, strokeWidth=0.5).project("mercator"))
    return alt.layer(*layers).properties(width=width, height=height)


def women_stacks(women: pd.DataFrame, role: str, width="container", height=620, top_n: int | None = None):
    """Share of women, men and names the model could not classify, in each state, for one role."""
    d = women[women["role"] == role].copy()
    d = d[d["total"] >= 20_000]
    if top_n:
        d = d.nlargest(top_n, "total")
    d["Women"] = d["women"] / d["total"]
    d["Men"] = (d["classified"] - d["women"]) / d["total"]
    d["Name not classifiable"] = 1 - d["classified"] / d["total"]
    order = d.sort_values("women_share", ascending=False)["grp"].tolist()
    long = d.melt(id_vars=["grp", "women_share"], value_vars=["Women", "Men", "Name not classifiable"], var_name="group", value_name="share")
    bars = alt.Chart(long).mark_bar(height=11, stroke=PANEL, strokeWidth=1).encode(
        x=alt.X("share:Q", stack="zero", title="Share of all cases", axis=alt.Axis(format=".0%", tickCount=5), scale=alt.Scale(domain=[0, 1])),
        y=alt.Y("grp:N", sort=order, title=None, axis=alt.Axis(ticks=False, domain=False, grid=False, labelLimit=170)),
        color=alt.Color("group:N", title=None, sort=["Women", "Men", "Name not classifiable"],
                        scale=alt.Scale(domain=["Women", "Men", "Name not classifiable"], range=[ACCENT, CONTEXT, NO_DATA]),
                        legend=alt.Legend(orient="top", direction="horizontal")),
        order=alt.Order("order:Q"),
        tooltip=[alt.Tooltip("grp:N", title="State"), alt.Tooltip("group:N", title="Group"), alt.Tooltip("share:Q", title="Share of all cases", format=".1%"),
                 alt.Tooltip("women_share:Q", title="Women, of classified names", format=".1%")],
    ).transform_calculate(order="datum.group === 'Women' ? 0 : (datum.group === 'Men' ? 1 : 2)")
    return bars.properties(width=width, height=height)


def women_roles(women_all: pd.DataFrame, width="container", height=180):
    """National share of women in each courtroom role, from classified names."""
    x = alt.X("women_share:Q", title="Women, as a share of classified names", axis=alt.Axis(format=".0%", tickCount=5), scale=alt.Scale(domain=[0, float(women_all["women_share"].max()) * 1.25]))
    y = alt.Y("role:N", sort="-x", title=None, axis=alt.Axis(ticks=False, domain=False, grid=False, labelLimit=170))
    bars = alt.Chart(women_all).mark_bar(cornerRadiusEnd=4, height=16, color=ACCENT).encode(x=x, y=y)
    text = alt.Chart(women_all).mark_text(align="left", dx=5, font=FONT, fontSize=10, color=BODY).encode(x=x, y=y, text=alt.Text("women_share:Q", format=".1%"))
    return (bars + text).properties(width=width, height=height)


def backlog_bars(q7: pd.DataFrame, width="container", height=620, top_n: int | None = None):
    d = q7[q7["in_ddl"] & q7["pending_total"].notna() & (q7["pending_total"] >= 20_000)].copy()
    if top_n:
        d = d.nlargest(top_n, "years_of_disposals_njdg_stock")
    d["status"] = np.where(d["clearance_rate"] < 1, "Filings outran recorded disposals", "Disposals kept up")
    d["label"] = [f"{y:.1f} yrs" for y in d["years_of_disposals_njdg_stock"]]
    order = d.sort_values("years_of_disposals_njdg_stock", ascending=False)["njdg_state"].tolist()
    x = alt.X("years_of_disposals_njdg_stock:Q", title="Years of disposals needed to clear the 2026 backlog, if filings stopped",
              scale=alt.Scale(domainMax=float(d["years_of_disposals_njdg_stock"].max()) * 1.12), axis=alt.Axis(tickCount=6))
    y = alt.Y("njdg_state:N", sort=order, title=None, axis=alt.Axis(ticks=False, domain=False, grid=False, labelLimit=170))
    bars = alt.Chart(d).mark_bar(cornerRadiusEnd=4, height=11).encode(
        x=x, y=y,
        color=alt.Color("status:N", title=None, scale=alt.Scale(domain=["Filings outran recorded disposals", "Disposals kept up"], range=[ACCENT, CONTEXT]),
                        legend=alt.Legend(orient="bottom", direction="horizontal", labelLimit=260)),
        tooltip=[alt.Tooltip("njdg_state:N", title="State"), alt.Tooltip("pending_total:Q", title="Pending, 30 Jul 2026", format=",.0f"),
                 alt.Tooltip("closed_per_year:Q", title="Disposals per year, 2016-18", format=",.0f"), alt.Tooltip("filed_per_year:Q", title="Filings per year, 2016-18", format=",.0f"),
                 alt.Tooltip("clearance_rate:Q", title="Clearance rate", format=".0%"), alt.Tooltip("years_of_disposals_njdg_stock:Q", title="Years of disposals", format=".1f")],
    )
    labels = alt.Chart(d).mark_text(align="left", dx=4, font=FONT, fontSize=9, color=BODY).encode(x=x, y=y, text="label:N")
    return (bars + labels).properties(width=width, height=height)


def decisions_cliff(monthly: pd.DataFrame, cutoff: str = "2018-12", width="container", height=220):
    d = monthly.copy()
    d["date"] = pd.to_datetime(d["month"] + "-01")
    x = alt.X("date:T", title=None, axis=alt.Axis(format="%Y", tickCount="year", grid=False))
    y = alt.Y("decisions:Q", title="Decisions recorded per month", axis=alt.Axis(format="~s", tickCount=5))
    line = alt.Chart(d).mark_line(color=ACCENT, strokeWidth=2).encode(
        x=x, y=y, tooltip=[alt.Tooltip("date:T", title="Month", format="%b %Y"), alt.Tooltip("decisions:Q", title="Decisions", format=",.0f")])
    points = alt.Chart(d).mark_point(size=30, filled=True, color=ACCENT, opacity=0).encode(
        x=x, y=y, tooltip=[alt.Tooltip("date:T", title="Month", format="%b %Y"), alt.Tooltip("decisions:Q", title="Decisions", format=",.0f")])
    mark = pd.DataFrame({"date": [pd.Timestamp("2018-12-31")], "t": ["Analysis cut-off, 31 Dec 2018"]})
    rule = alt.Chart(mark).mark_rule(color=MUTED, strokeWidth=0.75).encode(x="date:T")
    label = alt.Chart(mark).mark_text(align="left", dx=5, y=8, font=FONT, fontSize=10, color=MUTED).encode(x="date:T", text="t:N")
    return (line + points + rule + label).properties(width=width, height=height)


OUTCOME_ORDER = ["Decided on merits", "Plea or admission", "Settled or Lok Adalat", "Withdrawn or lapsed",
                 "Transferred or committed", "Vague or missing label"]
OUTCOME_COLOURS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", CONTEXT]


def outcome_stacks(table: pd.DataFrame, width="container", height=360):
    """How closed cases ended, as shares of each group. The order on the page is the order in the legend."""
    d = table.copy()
    merits = d[d["outcome"] == "Decided on merits"].set_index("grp")["share"]
    order = merits.sort_values(ascending=False).index.tolist()
    d["rank"] = d["outcome"].map({name: i for i, name in enumerate(OUTCOME_ORDER)})
    bars = alt.Chart(d).mark_bar(height=13, stroke=PANEL, strokeWidth=1).encode(
        x=alt.X("share:Q", stack="zero", title="Share of closed cases", axis=alt.Axis(format=".0%", tickCount=5), scale=alt.Scale(domain=[0, 1])),
        y=alt.Y("grp:N", sort=order, title=None, axis=alt.Axis(ticks=False, domain=False, grid=False, labelLimit=190)),
        color=alt.Color("outcome:N", title=None, sort=OUTCOME_ORDER, scale=alt.Scale(domain=OUTCOME_ORDER, range=OUTCOME_COLOURS),
                        legend=alt.Legend(orient="top", direction="horizontal", columns=3, labelLimit=200)),
        order=alt.Order("rank:Q"),
        tooltip=[alt.Tooltip("grp:N", title="Group"), alt.Tooltip("outcome:N", title="Outcome"), alt.Tooltip("share:Q", title="Share", format=".1%"),
                 alt.Tooltip("closed_cases:Q", title="Closed cases", format=",.0f"), alt.Tooltip("median_days:Q", title="Median days, closed only", format=",.0f")],
    )
    return bars.properties(width=width, height=height)


def first_hearing_bars(d: pd.DataFrame, width="container", height=560, label_col="grp"):
    data = d.sort_values("median_days", ascending=False)
    order = data[label_col].tolist()
    data = data.assign(label=[f"{v:,.0f} day{'' if v == 1 else 's'}" for v in data["median_days"]])
    x = alt.X("median_days:Q", title="Median days from filing to first hearing", axis=alt.Axis(tickCount=6),
              scale=alt.Scale(domainMax=float(data["median_days"].max()) * 1.18))
    y = alt.Y(f"{label_col}:N", sort=order, title=None, axis=alt.Axis(ticks=False, domain=False, grid=False, labelLimit=190))
    bars = alt.Chart(data).mark_bar(cornerRadiusEnd=4, height=11, color=ACCENT).encode(
        x=x, y=y, tooltip=[alt.Tooltip(f"{label_col}:N", title="Group"), alt.Tooltip("median_days:Q", title="Median days", format=",.0f"),
                           alt.Tooltip("p90_days:Q", title="90th percentile, days", format=",.0f"), alt.Tooltip("within_30_days:Q", title="Heard within 30 days", format=".0%"),
                           alt.Tooltip("n:Q", title="Cases", format=",.0f")])
    labels = alt.Chart(data).mark_text(align="left", dx=4, font=FONT, fontSize=9, color=BODY).encode(x=x, y=y, text="label:N")
    return (bars + labels).properties(width=width, height=height)


def hazard_forest(table: pd.DataFrame, width="container", height=None):
    """Hazard ratios on a log scale: right of the line closes faster than the reference group, left closes slower."""
    d = table.sort_values("hazard_ratio", ascending=False).copy()
    order = d["level"].tolist()
    low, high = float(d["ci_low"].min()), float(d["ci_high"].max())
    scale = alt.Scale(type="log", domain=[low * 0.9, high * 1.1], nice=False)
    axis = alt.Axis(values=[0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50], format="~g")
    title = "How fast a case closes, relative to the reference (log scale)"
    y = alt.Y("level:N", sort=order, title=None, axis=alt.Axis(ticks=False, domain=False, grid=False, labelLimit=210))
    tip = [alt.Tooltip("level:N", title="Group"), alt.Tooltip("hazard_ratio:Q", title="Hazard ratio", format=".2f"),
           alt.Tooltip("ci_low:Q", title="95% interval, low", format=".2f"), alt.Tooltip("ci_high:Q", title="95% interval, high", format=".2f")]
    rule = alt.Chart(pd.DataFrame({"x": [1.0]})).mark_rule(color=MUTED, strokeWidth=1).encode(x=alt.X("x:Q", scale=scale, title=title, axis=axis))
    span = alt.Chart(d).mark_rule(color=ACCENT, strokeWidth=1.5).encode(x=alt.X("ci_low:Q", scale=scale, title=title, axis=axis), x2="ci_high:Q", y=y, tooltip=tip)
    dots = alt.Chart(d).mark_point(filled=True, size=46, color=ACCENT, opacity=1, stroke=PANEL, strokeWidth=1).encode(
        x=alt.X("hazard_ratio:Q", scale=scale, title=title, axis=axis), y=y, tooltip=tip)
    return (rule + span + dots).properties(width=width, height=height or max(120, 21 * len(d)))


def quality_heat(scores: pd.DataFrame, dimensions: list[str], width="container", height=None):
    """A heat table of quality scores. Darker cells are better; the score is printed in each."""
    long = scores.melt(id_vars=["state", "cases"], value_vars=dimensions + ["Overall"], var_name="dimension", value_name="score")
    order = scores.sort_values("Overall", ascending=False)["state"].tolist()
    x = alt.X("dimension:N", sort=dimensions + ["Overall"], title=None, axis=alt.Axis(orient="top", ticks=False, domain=False, labelAngle=0, labelColor=BODY))
    y = alt.Y("state:N", sort=order, title=None, axis=alt.Axis(ticks=False, domain=False, labelLimit=190, labelColor=BODY))
    rect = alt.Chart(long).mark_rect(stroke=PANEL, strokeWidth=1).encode(
        x=x, y=y, color=alt.Color("score:Q", title="Score", scale=alt.Scale(range=["#FBE9E7", "#FFFFFF", "#DBEAFE", "#86B6EF"], interpolate="rgb", domain=[0.8, 0.88, 0.95, 1.0], clamp=True), legend=None),
        tooltip=[alt.Tooltip("state:N", title="State"), alt.Tooltip("dimension:N", title="Dimension"), alt.Tooltip("score:Q", title="Score", format=".1%")])
    text = alt.Chart(long).mark_text(font=FONT, fontSize=10, color=INK).encode(x=x, y=y, text=alt.Text("score:Q", format=".1%"))
    return (rect + text).properties(width=width, height=height or 21 * len(order))


def quality_lines(by_year: pd.DataFrame, dimensions: list[str], width="container", height=260):
    x = alt.X("year:O", title="Filing year", axis=alt.Axis(labelAngle=0, grid=False))
    y = alt.Y("score:Q", title="Quality score", axis=alt.Axis(format=".0%", tickCount=5), scale=alt.Scale(zero=False))
    palette = CATEGORICAL + ["#e87ba4"]
    colour = alt.Color("dimension:N", title=None, sort=dimensions, scale=alt.Scale(domain=dimensions, range=palette[:len(dimensions)]),
                       legend=alt.Legend(orient="bottom", direction="horizontal", columns=3))
    line = alt.Chart(by_year).mark_line(strokeWidth=2).encode(x=x, y=y, color=colour)
    dots = alt.Chart(by_year).mark_point(filled=True, size=45, stroke=PANEL, strokeWidth=1, opacity=1).encode(
        x=x, y=y, color=colour, tooltip=[alt.Tooltip("year:O", title="Filing year"), alt.Tooltip("dimension:N", title="Dimension"), alt.Tooltip("score:Q", title="Score", format=".1%")])
    return (line + dots).properties(width=width, height=height)


def coverage_heat(state_year: pd.DataFrame, width="container", height=None):
    """Filings in each year as a share of the state's 2018 filings. A pale left edge means thin early records."""
    d = state_year.copy()
    latest = d[d["year"] == 2018].set_index("state")["filed"]
    d["relative"] = d["filed"] / d["state"].map(latest)
    first = d[d["year"] == 2010].set_index("state")["relative"].sort_values(ascending=False)
    x = alt.X("year:O", title=None, axis=alt.Axis(orient="top", ticks=False, domain=False, labelAngle=0, labelColor=BODY))
    y = alt.Y("state:N", sort=first.index.tolist(), title=None, axis=alt.Axis(ticks=False, domain=False, labelLimit=190, labelColor=BODY))
    rect = alt.Chart(d).mark_rect(stroke=PANEL, strokeWidth=1).encode(
        x=x, y=y, color=alt.Color("relative:Q", title="Share of the state's 2018 filings", scale=alt.Scale(range=SEQUENTIAL[:5], interpolate="rgb", domain=[0, 1], clamp=True),
                                  legend=alt.Legend(orient="bottom", direction="horizontal", format=".0%", gradientLength=200, gradientThickness=10)),
        tooltip=[alt.Tooltip("state:N", title="State"), alt.Tooltip("year:O", title="Filing year"), alt.Tooltip("filed:Q", title="Cases", format=",.0f"), alt.Tooltip("relative:Q", title="Share of 2018", format=".0%")])
    return rect.properties(width=width, height=height or 20 * d["state"].nunique())


def share_scatter(comparison: pd.DataFrame, width="container", height=360):
    """Each state's share of open cases in DDL against its share of NJDG's 2026 pendency."""
    d = comparison[comparison["status"] == "Both"].copy()
    top = float(max(d["ddl_open_share"].max(), d["njdg_pending_share"].max())) * 1.08
    scale = alt.Scale(domain=[0, top], nice=False)
    x = alt.X("njdg_pending_share:Q", title="Share of NJDG pending cases, Jul 2026", scale=scale, axis=alt.Axis(format=".0%", tickCount=6))
    y = alt.Y("ddl_open_share:Q", title="Share of DDL open cases, end of 2018", scale=scale, axis=alt.Axis(format=".0%", tickCount=6))
    diagonal = alt.Chart(pd.DataFrame({"a": [0, top], "b": [0, top]})).mark_line(color=MUTED, strokeWidth=0.75).encode(x=alt.X("a:Q", scale=scale), y=alt.Y("b:Q", scale=scale))
    dots = alt.Chart(d).mark_circle(size=60, color=ACCENT, opacity=0.75, stroke=PANEL, strokeWidth=1).encode(
        x=x, y=y, tooltip=[alt.Tooltip("njdg_state:N", title="State"), alt.Tooltip("ddl_open_share:Q", title="DDL share", format=".1%"), alt.Tooltip("njdg_pending_share:Q", title="NJDG share", format=".1%")])
    labels = alt.Chart(d.nlargest(4, "njdg_pending_share")).mark_text(align="left", dx=8, font=FONT, fontSize=10, color=BODY).encode(x=x, y=y, text="njdg_state:N")
    return (diagonal + dots + labels).properties(width=width, height=height)


def scenario_line(projection: pd.DataFrame, width="container", height=240):
    x = alt.X("year:Q", title="Years from 2026", axis=alt.Axis(tickCount=11, grid=False, format="d"))
    y = alt.Y("pending:Q", title="Pending cases", axis=alt.Axis(format="~s", tickCount=5), scale=alt.Scale(zero=True))
    line = alt.Chart(projection).mark_line(color=ACCENT, strokeWidth=2).encode(x=x, y=y)
    dots = alt.Chart(projection).mark_point(filled=True, size=30, color=ACCENT, opacity=0.01).encode(
        x=x, y=y, tooltip=[alt.Tooltip("year:Q", title="Years from 2026"), alt.Tooltip("pending:Q", title="Pending cases", format=",.0f")])
    return (line + dots).properties(width=width, height=height)


def women_trend(by_year: pd.DataFrame, width="container", height=240):
    roles = ["Petitioner", "Defendant", "Petitioner's advocate", "Defendant's advocate"]
    x = alt.X("grp:O", title="Filing year", axis=alt.Axis(labelAngle=0, grid=False))
    y = alt.Y("women_share:Q", title="Women, of classified names", axis=alt.Axis(format=".0%", tickCount=5), scale=alt.Scale(zero=True))
    colour = alt.Color("role:N", title=None, sort=roles, scale=alt.Scale(domain=roles, range=CATEGORICAL), legend=alt.Legend(orient="bottom", direction="horizontal", columns=2, labelLimit=180))
    line = alt.Chart(by_year).mark_line(strokeWidth=2).encode(x=x, y=y, color=colour)
    dots = alt.Chart(by_year).mark_point(filled=True, size=40, stroke=PANEL, strokeWidth=1, opacity=1).encode(
        x=x, y=y, color=colour, tooltip=[alt.Tooltip("grp:O", title="Filing year"), alt.Tooltip("role:N", title="Role"), alt.Tooltip("women_share:Q", title="Women", format=".1%")])
    return (line + dots).properties(width=width, height=height)
