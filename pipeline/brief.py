"""Step 7: export the charts as PNG and build the two-page brief.

Every number and sentence comes from data/mart/findings.json, and every chart from pipeline/charts.py, so the
brief cannot disagree with the dashboard.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import vl_convert as vlc
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

sys.path.insert(0, str(Path(__file__).resolve().parent))
import charts as C  # noqa: E402
from common import CHARTS, MART, OUTPUTS  # noqa: E402

INK = HexColor(C.INK)
MUTED = HexColor(C.MUTED)
HAIR = HexColor(C.HAIRLINE)
ACCENT = HexColor(C.ACCENT)
SCALE = 3


def read(name: str) -> pd.DataFrame:
    return pd.read_parquet(MART / f"{name}.parquet")


def save_png(chart, name: str, scale: int = SCALE) -> Path:
    CHARTS.mkdir(parents=True, exist_ok=True)
    path = CHARTS / f"{name}.png"
    path.write_bytes(vlc.vegalite_to_png(C.styled(chart).to_json(), scale=scale))
    return path


def export_charts(figures: dict) -> dict[str, tuple[Path, float]]:
    """Each entry gives the file and its width-to-height ratio. Sizes are in px at 96 per inch of panel."""
    q1 = read("q1_stage")
    curves = read("q2_km_curves")
    acts = read("q3_acts")
    pairs, tenure = read("q4_pairs"), read("q4_tenure_pairs")
    districts = read("q5_districts").copy()
    districts.loc[districts["suspect_closure_records"], "low_volume"] = True
    women = read("q6_women_state")
    q7 = read("q7_backlog")
    monthly = read("coverage_decisions_by_month")

    groups = ["All cases", "Civil suit", "Cheque bounce (NI Act)", "Criminal trial (magistrate)"]
    wanted = curves[((curves["dimension"] == "All cases") | (curves["dimension"] == "Case category")) & curves["grp"].isin(groups)]
    out = {}

    def add(name, chart, w, h):
        out[name] = (save_png(chart, name), w, h)

    add("q1_stages", C.stage_bars(q1, width=250, height=205), 340, 250)
    add("q2_survival", C.survival_lines(wanted, groups, width=300, height=180), 340, 250)
    add("q3_laws", C.act_bubbles(acts, width=300, height=215), 340, 280)
    trial_pairs = pairs[pairs["case_category"].isin(C.TRIAL_CATEGORIES)]
    trial_tenure = tenure[tenure["case_category"].isin(C.TRIAL_CATEGORIES)]
    add("q4_judges", (C.judge_boxes(trial_pairs, width=120, height=175) | C.tenure_boxes(trial_tenure, width=120, height=175)), 340, 230)
    add("q5_map", C.district_map(districts, "Median years to close", width=330, height=350), 340, 350)
    add("q6_women", C.women_stacks(women, "Petitioner's advocate", width=240, height=205, top_n=14), 340, 255)
    add("q7_backlog", C.backlog_bars(q7, width=230, height=215, top_n=14), 340, 265)
    add("coverage_cliff", C.decisions_cliff(monthly, width=660, height=105), 720, 135)
    # Not in the two-page brief, but used by the README and the shareable page.
    outcomes = read("q8_outcomes")
    add("q8_outcomes", C.outcome_stacks(outcomes[outcomes["dimension"] == "Case category"], width=250, height=250), 340, 330)
    hearing = read("q9_first_hearing")
    add("q9_first_hearing", C.first_hearing_bars(hearing[(hearing["dimension"] == "State") & (hearing["n"] >= 200_000)], width=240, height=330), 340, 370)
    model = read("model_hazard_ratios")
    add("q10_model", C.hazard_forest(model[model["group"] == "State"], width=220, height=380), 340, 420)
    return out


def styles() -> dict[str, ParagraphStyle]:
    base = dict(fontName="Helvetica", textColor=INK, alignment=TA_LEFT)
    return {
        "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=19, leading=22, textColor=INK),
        "sub": ParagraphStyle("sub", fontSize=8.8, leading=11.5, textColor=MUTED, fontName="Helvetica"),
        "lead": ParagraphStyle("lead", fontSize=9.2, leading=12.4, **base),
        "kpi_num": ParagraphStyle("kpi_num", fontName="Helvetica-Bold", fontSize=13.5, leading=15, textColor=INK),
        "kpi_label": ParagraphStyle("kpi_label", fontName="Helvetica", fontSize=7, leading=8.6, textColor=MUTED),
        "tag": ParagraphStyle("tag", fontName="Helvetica-Bold", fontSize=7.5, leading=9.5, textColor=ACCENT),
        "head": ParagraphStyle("head", fontName="Helvetica-Bold", fontSize=9.4, leading=11.4, textColor=INK),
        "body": ParagraphStyle("body", fontSize=8.3, leading=10.6, **base),
        "care": ParagraphStyle("care", fontName="Helvetica", fontSize=7.2, leading=9, textColor=MUTED),
        "small": ParagraphStyle("small", fontName="Helvetica", fontSize=6.7, leading=8.4, textColor=MUTED),
    }


def panel(st, tag: str, text: dict, chart: tuple[Path, float, float], width: float, chart_h: float):
    path, w, h = chart
    ratio = w / h
    img_w = min(width, chart_h * ratio)
    img = Image(str(path), width=img_w, height=img_w / ratio)
    return [
        Paragraph(tag, st["tag"]),
        Paragraph(text["question"], st["head"]),
        Spacer(1, 2),
        img,
        Spacer(1, 2),
        Paragraph(text["finding"], st["body"]),
        Spacer(1, 1.5),
        Paragraph(f"<b>Read with care:</b> {text['caveat']}", st["care"]),
    ]


def build(figures: dict, text: dict, charts: dict) -> Path:
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    path = OUTPUTS / "where_justice_gets_stuck_brief.pdf"
    margin = 0.42 * inch
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=margin, rightMargin=margin, topMargin=0.36 * inch,
                            bottomMargin=0.32 * inch, title="Where Justice Gets Stuck", author="Ritik Yadav",
                            subject="Findings from 81 million Indian lower-court cases")
    st = styles()
    full = A4[0] - 2 * margin
    gap = 0.2 * inch
    col = (full - gap) / 2
    f = figures

    story = [
        Paragraph("Where Justice Gets Stuck", st["title"]),
        Spacer(1, 2),
        Paragraph(f"Findings from {f['total_rows'] / 1e6:.1f} million Indian lower-court cases filed 2010-2018, with 2026 pendency for context. "
                  "Ritik Yadav, November 2026.", st["sub"]),
        Spacer(1, 5),
        Paragraph(
            f"India's district and subordinate courts held {f['njdg_total'] / 1e7:.2f} crore pending cases in July 2026, up from {f['njdg_2025'] / 1e7:.2f} crore in 2025. "
            f"This project asks where and why those cases stall. The headline is a measurement point: the usual average, taken from closed cases, "
            f"understates delay {f['q2_ratio']:.1f} times, because the slowest cases are the ones still open. "
            f"In June 2026, {f['judges_working']:,} judicial officers were working against {f['judges_sanctioned']:,} sanctioned posts, and in this data a judge stays a median "
            f"{f['q4_tenure_median_days']:,.0f} days in one post, less than the median case takes to close. "
            "Case-level data ends in 2018, so these findings describe that period rather than courts today.", st["lead"]),
        Spacer(1, 5),
    ]
    kpis = [
        (f"{f['total_rows'] / 1e6:.1f}M", "cases analysed, 2010-2018"),
        (f"{f['open_at_cutoff'] / 1e7:.2f} crore", "still open at the end of 2018"),
        (f"{f['q2_km_median']:,.0f} days", f"median to close, open cases counted (closed cases alone: {f['q2_naive_median']:,.0f})"),
        (f"{f['q2_open_5y']:.0%}", "of cases still open after five years"),
    ]
    kpi_table = Table([[[Paragraph(n, st["kpi_num"]), Paragraph(l, st["kpi_label"])] for n, l in kpis]], colWidths=[full / 4] * 4)
    kpi_table.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, 0), 0.75, INK), ("LINEBELOW", (0, 0), (-1, 0), 0.5, HAIR),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story += [kpi_table, Spacer(1, 7)]

    grid_style = TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (0, -1), gap),
        ("RIGHTPADDING", (1, 0), (1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ])
    col_widths = [col + gap, col]
    page1 = Table([
        [panel(st, "Finding 1", text["q2"], charts["q2_survival"], col, 1.95 * inch),
         panel(st, "Finding 2", text["q1"], charts["q1_stages"], col, 1.95 * inch)],
        [panel(st, "Finding 3", text["q5"], charts["q5_map"], col, 3.3 * inch),
         panel(st, "Finding 4", text["q3"], charts["q3_laws"], col, 2.7 * inch)],
    ], colWidths=col_widths)
    page1.setStyle(grid_style)
    story += [page1, PageBreak()]

    page2 = Table([
        [panel(st, "Finding 5", text["q4"], charts["q4_judges"], col, 2.15 * inch),
         panel(st, "Also tested", text["q7"], charts["q7_backlog"], col, 2.35 * inch)],
        [panel(st, "Also tested", text["q6"], charts["q6_women"], col, 2.3 * inch),
         quality_block(st, f, col)],
    ], colWidths=col_widths)
    page2.setStyle(grid_style)
    story.append(page2)
    path_cliff, w_cliff, h_cliff = charts["coverage_cliff"]
    story += [
        Paragraph("Why every result uses one cut-off: decisions recorded per month fall sharply after January 2019", st["head"]),
        Spacer(1, 2),
        Image(str(path_cliff), width=full, height=full * h_cliff / w_cliff),
        Spacer(1, 5),
        Paragraph("<b>Sources.</b> Development Data Lab eCourts data (CC BY-NC-SA 4.0, non-commercial); NJDG via Lok Sabha Unstarred Question 3371, answered 7 Aug 2026; "
                  "In Re: Expeditious Trial of Cases under Section 138 NI Act (Supreme Court, 16 Apr 2021); Census 2011; DataMeet boundaries (CC BY 4.0, display only, not an official map). "
                  "Delay's cost is estimated at 0.5-1.5% of GDP (eCourtsIndia blog, citing DAKSH); there is no official figure.", st["small"]),
    ]
    doc.build(story)
    return path


def quality_block(st, f: dict, width: float):
    rows = [
        Paragraph("How far to trust this", st["tag"]),
        Paragraph("Data quality and method", st["head"]),
        Spacer(1, 3),
        Paragraph(
            f"<b>{f.get('dq_rules', 0)} data-quality rules</b> ran on every case; {f.get('dq_failed', 0)} found failures, each logged with severity, samples and treatment. "
            f"<b>{f.get('act_variants_standardized', 0):,} of {f.get('act_variants_total', 0):,} raw act labels</b> were standardised into {f.get('canonical_acts', 0)} acts.",
            st["body"]),
        Spacer(1, 3),
        Paragraph(
            "<b>One cut-off.</b> Recorded decisions fall by about 90% in early 2019 because only some courts were collected again later. "
            "Every case is treated as open on 31 Dec 2018 unless decided by then, so no court gains from later collection.", st["body"]),
        Spacer(1, 3),
        Paragraph(
            f"<b>Coverage.</b> Rows per year grow {f['cov_growth']:.1f}x from 2010 to 2018 as records went digital, so flow rates use 2016-18 only. "
            f"Cases filed before 2010 are absent, so backlogs and disposals are understated. Five states and UTs have no separate data. "
            f"Two independent checks support the picture: DDL's open cases by state track NJDG's 2026 pendency shares (correlation {f['cov_corr']:.2f}), and states slow here also hold "
            f"NJDG's oldest cases (rank correlation {f['cov_age_spearman']:.2f}, {f['cov_age_states']} large states).", st["body"]),
        Spacer(1, 3),
        Paragraph(
            "<b>Survival analysis.</b> Open cases count towards delay until the cut-off, using Kaplan-Meier curves computed in SQL over all rows and tested against the lifelines library.",
            st["body"]),
        Spacer(1, 3),
        Paragraph("<b>Limits.</b> These are associations. Stage and act come from free-text labels, gender from a name-based model, and population from 2011.", st["body"]),
    ]
    return rows


def run() -> Path:
    data = json.loads((MART / "findings.json").read_text())
    charts = export_charts(data["figures"])
    path = build(data["figures"], data["text"], charts)
    print("wrote", path, flush=True)
    return path


if __name__ == "__main__":
    run()
