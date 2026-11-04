"""Step 5: build the Excel data-quality scorecard.

Scores are live formulas over the raw counts in the Failures and Checked sheets, so a reviewer can trace any
score to its rules, or change a severity weight on the Read me sheet and watch every score move.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import xlsxwriter
from xlsxwriter.utility import xl_col_to_name, xl_rowcol_to_cell

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import MART, OUTPUTS, PARQUET, ROOT, SQL  # noqa: E402
from quality import parse_rules  # noqa: E402
from samples import short_samples  # noqa: E402
from standardize import ANALYSIS_CUTOFF  # noqa: E402

FONT = "Arial"
INK = "#1A1A1A"
MUTED = "#52514E"
HEAD_FILL = "#F0EFEC"
ACCENT = "#1C5CAB"
DIMENSIONS = ["Completeness", "Validity", "Consistency", "Uniqueness", "Linkage"]


def load_inputs():
    rules = parse_rules(SQL / "dq_rules.sql")
    results = pd.read_parquet(MART / "dq_results.parquet")
    states = pd.read_parquet(PARQUET / "maps" / "dim_state.parquet").sort_values("state_name")
    base = pd.read_parquet(MART / "coverage_state_year.parquet")
    return rules, results, states, base


def state_scores(weights: dict[str, int] | None = None) -> pd.DataFrame:
    """The Scorecard sheet's calculation in pandas, used by the dashboard and to check the Excel formulas."""
    weights = weights or {"High": 3, "Medium": 2, "Low": 1, "Info": 0}
    rules, results, states, base = load_inputs()
    totals = base.groupby("state")["filed"].sum()
    grouped = results.groupby(["state_code", "rule_id"])[["failures", "checked"]].sum()
    rows = []
    for code, name in states[["state_code", "state_name"]].itertuples(index=False):
        row = {"state": name, "cases": int(totals.get(name, 0))}
        for dim in DIMENSIONS:
            members = [r for r in rules if r.dimension == dim]
            weighted = sum(weights[r.severity] * (grouped.loc[(code, r.id), "failures"] / grouped.loc[(code, r.id), "checked"]
                                                  if (code, r.id) in grouped.index and grouped.loc[(code, r.id), "checked"] else 0.0)
                           for r in members)
            total_weight = sum(weights[r.severity] for r in members)
            row[dim] = 1 - weighted / total_weight
        row["Overall"] = sum(row[d] for d in DIMENSIONS) / len(DIMENSIONS)
        rows.append(row)
    out = pd.DataFrame(rows)
    out.to_parquet(MART / "dq_state_scores.parquet", index=False)

    # The same calculation by filing year. Rules with no year, such as those on the judge table, are left out.
    by_year = results.dropna(subset=["year"]).groupby(["year", "rule_id"])[["failures", "checked"]].sum()
    year_rows = []
    for year in sorted(by_year.index.get_level_values("year").unique()):
        for dim in DIMENSIONS:
            members = [r for r in rules if r.dimension == dim and (year, r.id) in by_year.index]
            total = sum(weights[r.severity] for r in members)
            if total:
                failed = sum(weights[r.severity] * by_year.loc[(year, r.id), "failures"] / by_year.loc[(year, r.id), "checked"]
                             for r in members if by_year.loc[(year, r.id), "checked"])
                year_rows.append({"year": int(year), "dimension": dim, "score": 1 - failed / total})
    pd.DataFrame(year_rows).to_parquet(MART / "dq_year_scores.parquet", index=False)
    return out


def run() -> Path:
    state_scores()
    rules, results, states, base = load_inputs()
    rule_ids = [r.id for r in rules]
    issue_log = pd.read_csv(MART / "issue_log.csv", dtype={"worst_state_code": str})
    analyst = pd.read_csv(ROOT / "docs" / "analyst_issues.csv")
    state_rows = states[["state_code", "state_name"]].to_records(index=False).tolist()
    code_to_name = dict(state_rows)
    totals = base.groupby("state")["filed"].sum().to_dict()

    failures = results.groupby(["state_code", "rule_id"])["failures"].sum()
    checked = results.groupby(["state_code", "rule_id"])["checked"].sum()

    OUTPUTS.mkdir(parents=True, exist_ok=True)
    path = OUTPUTS / "data_quality_scorecard.xlsx"
    wb = xlsxwriter.Workbook(path)
    wb.formats[0].set_font_name(FONT)
    wb.formats[0].set_font_size(10)

    def fmt(**kw):
        return wb.add_format({"font_name": FONT, "font_size": 10, "font_color": INK, "valign": "top", **kw})

    title = fmt(bold=True, font_size=16)
    sub = fmt(font_color=MUTED)
    wrap = fmt(text_wrap=True)
    head = fmt(bold=True, bg_color=HEAD_FILL, bottom=1, text_wrap=True, valign="vcenter")
    head_num = fmt(bold=True, bg_color=HEAD_FILL, bottom=1, text_wrap=True, align="right", valign="vcenter")
    text = fmt()
    bold = fmt(bold=True)
    integer = fmt(num_format="#,##0")
    pct = fmt(num_format="0.0%")
    pct2 = fmt(num_format="0.00%")
    ratio = fmt(num_format="0.00")
    pts = fmt(num_format="+0.0;-0.0;0.0")
    input_cell = fmt(font_color="#0000FF", align="center", bg_color="#FFF9DB")
    total_label = fmt(bold=True, top=1)
    total_pct = fmt(bold=True, top=1, num_format="0.0%")
    total_int = fmt(bold=True, top=1, num_format="#,##0")

    readme = wb.add_worksheet("Read me")
    score = wb.add_worksheet("Scorecard")
    rules_ws = wb.add_worksheet("Rules")
    log = wb.add_worksheet("Issue log")
    cover = wb.add_worksheet("Coverage")
    acts = wb.add_worksheet("Act mapping")
    rates = wb.add_worksheet("Rates")
    fail_ws = wb.add_worksheet("Failures")
    check_ws = wb.add_worksheet("Checked")

    # ------------------------------------------------------------------ raw counts
    first_row = 5  # zero-based row of the first state on the matrix sheets
    first_col = 2
    last_col = first_col + len(rule_ids) - 1
    last_row = first_row + len(state_rows) - 1

    def matrix_sheet(ws, heading: str, values) -> None:
        ws.write(0, 0, heading, title)
        ws.write(1, 0, "Raw counts from sql/dq_rules.sql, by state, all filing years. Do not edit.", sub)
        ws.write(4, 0, "Code", head)
        ws.write(4, 1, "State", head)
        for j, rid in enumerate(rule_ids):
            ws.write(4, first_col + j, rid, head_num)
        for i, (code, name) in enumerate(state_rows):
            ws.write(first_row + i, 0, code, text)
            ws.write(first_row + i, 1, name, text)
            for j, rid in enumerate(rule_ids):
                ws.write_number(first_row + i, first_col + j, float(values(code, name, rid)), integer)
        ws.set_column(0, 0, 6)
        ws.set_column(1, 1, 24)
        ws.set_column(first_col, last_col, 11)
        ws.freeze_panes(first_row, first_col)

    def fail_value(code, _name, rid):
        return failures.get((code, rid), 0)

    def check_value(code, name, rid):
        # A clean rule returns no rows from its SELECT, so fall back to the state's case count.
        value = checked.get((code, rid), 0)
        return value if value else totals.get(name, 0)

    matrix_sheet(fail_ws, "Failures per rule and state", fail_value)
    matrix_sheet(check_ws, "Rows checked per rule and state", check_value)

    # ------------------------------------------------------------------ rule catalogue
    rules_ws.write(0, 0, "Rule catalogue", title)
    rules_ws.write(1, 0, f"{len(rules)} rules. Failure counts sum the Failures sheet; each rule's SQL is in sql/dq_rules.sql.", sub)
    columns = ["Rule", "What fails", "Dimension", "Severity", "Weight", "Status", "Failures", "Checked", "Failure rate", "Treatment"]
    for j, c in enumerate(columns):
        rules_ws.write(3, j, c, head_num if c in ("Weight", "Failures", "Checked", "Failure rate") else head)
    for i, r in enumerate(rules):
        row = 4 + i
        fail_col = xl_col_to_name(first_col + i)
        rules_ws.write(row, 0, r.id, text)
        rules_ws.write(row, 1, r.title, wrap)
        rules_ws.write(row, 2, r.dimension, text)
        rules_ws.write(row, 3, r.severity, text)
        rules_ws.write_formula(row, 4, f"=INDEX('Read me'!$B$12:$B$15,MATCH(D{row + 1},'Read me'!$A$12:$A$15,0))", text)
        rules_ws.write(row, 5, r.status, text)
        rules_ws.write_formula(row, 6, f"=SUM(Failures!{fail_col}{first_row + 1}:{fail_col}{last_row + 1})", integer)
        rules_ws.write_formula(row, 7, f"=SUM(Checked!{fail_col}{first_row + 1}:{fail_col}{last_row + 1})", integer)
        rules_ws.write_formula(row, 8, f"=IF(H{row + 1}=0,0,G{row + 1}/H{row + 1})", pct2)
        rules_ws.write(row, 9, r.treatment, wrap)
    rules_ws.set_column(0, 0, 7)
    rules_ws.set_column(1, 1, 52)
    rules_ws.set_column(2, 3, 13)
    rules_ws.set_column(4, 4, 8)
    rules_ws.set_column(5, 5, 11)
    rules_ws.set_column(6, 7, 13)
    rules_ws.set_column(8, 8, 10)
    rules_ws.set_column(9, 9, 80)
    rules_ws.freeze_panes(4, 1)
    rules_ws.autofilter(3, 0, 3 + len(rules), len(columns) - 1)

    # ------------------------------------------------------------------ rates
    rates.write(0, 0, "Failure rates per rule and state", title)
    rates.write(1, 0, "Failures divided by Checked. Rows 3 and 4 carry each rule's dimension and weight for the Scorecard formulas.", sub)
    rates.write(2, 1, "Dimension", bold)
    rates.write(3, 1, "Weight", bold)
    rates.write(4, 0, "Code", head)
    rates.write(4, 1, "State", head)
    for j, r in enumerate(rules):
        col = first_col + j
        rates.write_formula(2, col, f"=Rules!C{5 + j}", text)
        rates.write_formula(3, col, f"=Rules!E{5 + j}", text)
        rates.write(4, col, r.id, head_num)
    for i, (code, name) in enumerate(state_rows):
        rates.write(first_row + i, 0, code, text)
        rates.write(first_row + i, 1, name, text)
        for j in range(len(rules)):
            cell_f = xl_rowcol_to_cell(first_row + i, first_col + j)
            rates.write_formula(first_row + i, first_col + j, f"=IF(Checked!{cell_f}=0,0,Failures!{cell_f}/Checked!{cell_f})", pct2)
    rates.set_column(0, 0, 6)
    rates.set_column(1, 1, 24)
    rates.set_column(first_col, last_col, 11)
    rates.freeze_panes(first_row, first_col)

    # ------------------------------------------------------------------ scorecard
    start, end = xl_col_to_name(first_col), xl_col_to_name(last_col)
    score.write(0, 0, "Data-quality scorecard by state", title)
    score.write(1, 0, "DDL eCourts cases filed 2010-2018. 100% means no rule in that dimension failed. See Read me for the method.", sub)
    header = ["State", "Cases"] + DIMENSIONS + ["Overall", "Rank"]
    for j, c in enumerate(header):
        score.write(3, j, c, head if j == 0 else head_num)
    s_first = 4
    s_last = s_first + len(state_rows) - 1
    for i, (code, name) in enumerate(state_rows):
        row = s_first + i
        rate_row = first_row + i + 1
        score.write(row, 0, name, text)
        score.write_number(row, 1, float(totals.get(name, 0)), integer)
        for j, d in enumerate(DIMENSIONS):
            col = 2 + j
            head_cell = xl_rowcol_to_cell(3, col, row_abs=True)
            mask = f"(Rates!${start}$3:${end}$3={head_cell})"
            weights = f"Rates!${start}$4:${end}$4"
            this_rates = f"Rates!${start}{rate_row}:${end}{rate_row}"
            score.write_formula(row, col, f"=1-SUMPRODUCT({mask}*{weights}*{this_rates})/SUMPRODUCT({mask}*{weights})", pct)
        first_dim, last_dim = xl_rowcol_to_cell(row, 2), xl_rowcol_to_cell(row, 2 + len(DIMENSIONS) - 1)
        overall_col = 2 + len(DIMENSIONS)
        score.write_formula(row, overall_col, f"=AVERAGE({first_dim}:{last_dim})", pct)
        col_letter = xl_col_to_name(overall_col)
        score.write_formula(row, overall_col + 1, f"=RANK({col_letter}{row + 1},${col_letter}${s_first + 1}:${col_letter}${s_last + 1})", text)
    total_row = s_last + 1
    score.write(total_row, 0, "All states (case-weighted)", total_label)
    score.write_formula(total_row, 1, f"=SUM(B{s_first + 1}:B{s_last + 1})", total_int)
    for j in range(len(DIMENSIONS) + 1):
        col = xl_col_to_name(2 + j)
        score.write_formula(total_row, 2 + j,
                            f"=SUMPRODUCT($B{s_first + 1}:$B{s_last + 1},{col}{s_first + 1}:{col}{s_last + 1})/$B{total_row + 1}", total_pct)
    score.write_blank(total_row, 2 + len(DIMENSIONS) + 1, None, total_label)
    score.conditional_format(s_first, 2, s_last, 2 + len(DIMENSIONS), {
        "type": "3_color_scale", "min_color": "#F0B8B8", "mid_color": "#F7F6F3", "max_color": "#9EC5F4",
        "min_type": "percentile", "min_value": 5, "mid_type": "percentile", "mid_value": 50,
        "max_type": "percentile", "max_value": 95,
    })
    score.set_column(0, 0, 28)
    score.set_column(1, 1, 13)
    score.set_column(2, 2 + len(DIMENSIONS) + 1, 13)
    score.freeze_panes(4, 1)
    score.set_row(3, 28)
    overall = xl_col_to_name(2 + len(DIMENSIONS))
    chart = wb.add_chart({"type": "bar"})
    chart.add_series({
        "name": "Overall score",
        "categories": f"=Scorecard!$A${s_first + 1}:$A${s_last + 1}",
        "values": f"=Scorecard!${overall}${s_first + 1}:${overall}${s_last + 1}",
        "fill": {"color": ACCENT}, "gap": 40,
    })
    chart.set_title({"name": "Overall data-quality score by state (scores are close: see the dimension columns)", "name_font": {"name": FONT, "size": 11, "bold": True}})
    chart.set_legend({"none": True})
    chart.set_y_axis({"reverse": True, "num_font": {"name": FONT, "size": 8}})
    # Bars need a zero baseline. State scores are close, and the chart should show that.
    chart.set_x_axis({"min": 0, "max": 1, "num_format": "0%", "major_gridlines": {"visible": True, "line": {"color": "#E5E4E0"}}, "num_font": {"name": FONT, "size": 8}})
    chart.set_size({"width": 520, "height": 640})
    score.insert_chart(3, 2 + len(DIMENSIONS) + 3, chart)

    # ------------------------------------------------------------------ issue log
    log.write(0, 0, "Issue log", title)
    log.write(1, 0, "Every rule that failed, plus anomalies found by hand. Sample records use DDL's case ID only, with no names.", sub)
    log_cols = ["ID", "Source", "Issue", "Dimension", "Severity", "Status", "Rows affected", "Share of checked", "Worst state", "Evidence or sample records", "Treatment"]
    for j, c in enumerate(log_cols):
        log.write(3, j, c, head_num if c in ("Rows affected", "Share of checked") else head)
    order = {"High": 0, "Medium": 1, "Low": 2, "Info": 3}
    issue_log = issue_log.assign(o=issue_log["severity"].map(order)).sort_values(["o", "failures"], ascending=[True, False])
    row = 4
    for r in issue_log.itertuples():
        log.write(row, 0, r.issue_id, text)
        log.write(row, 1, f"Rule {r.rule_id}", text)
        log.write(row, 2, r.title, wrap)
        log.write(row, 3, r.dimension, text)
        log.write(row, 4, r.severity, text)
        log.write(row, 5, r.status, text)
        log.write_number(row, 6, float(r.failures), integer)
        log.write_number(row, 7, float(r.failure_rate), pct2)
        log.write(row, 8, code_to_name.get(r.worst_state_code, ""), text)
        log.write(row, 9, short_samples(r.sample_records), wrap)
        log.write(row, 10, r.treatment, wrap)
        row += 1
    for r in analyst.itertuples():
        log.write(row, 0, r.issue_id, text)
        log.write(row, 1, "Analyst review", text)
        log.write(row, 2, r.title, wrap)
        log.write(row, 3, r.dimension, text)
        log.write(row, 4, r.severity, text)
        log.write(row, 5, r.status, text)
        log.write(row, 9, r.evidence, wrap)
        log.write(row, 10, r.treatment, wrap)
        row += 1
    log.set_column(0, 0, 8)
    log.set_column(1, 1, 14)
    log.set_column(2, 2, 42)
    log.set_column(3, 5, 12)
    log.set_column(6, 6, 13)
    log.set_column(7, 7, 10)
    log.set_column(8, 8, 18)
    log.set_column(9, 9, 72)
    log.set_column(10, 10, 62)
    log.freeze_panes(4, 3)
    log.autofilter(3, 0, row - 1, len(log_cols) - 1)

    # ------------------------------------------------------------------ coverage
    cover.write(0, 0, "Coverage", title)
    cover.write(1, 0, "How complete DDL is by state and filing year, and how its open cases compare with NJDG's 2026 pendency.", sub)
    pivot = base.pivot_table(index="state", columns="year", values="filed", aggfunc="sum").fillna(0).sort_index()
    years = list(pivot.columns)
    cover.write(3, 0, "Cases filed per year (DDL)", bold)
    cover.write(4, 0, "State", head)
    for j, y in enumerate(years):
        cover.write(4, 1 + j, str(int(y)), head_num)
    ratio_col = 1 + len(years)
    cover.write(4, ratio_col, "2018 vs 2010 (x)", head_num)
    for i, (state, vals) in enumerate(pivot.iterrows()):
        cover.write(5 + i, 0, state, text)
        for j, y in enumerate(years):
            cover.write_number(5 + i, 1 + j, float(vals[y]), integer)
        a = xl_rowcol_to_cell(5 + i, 1)
        b = xl_rowcol_to_cell(5 + i, len(years))
        cover.write_formula(5 + i, ratio_col, f'=IF({a}=0,"n/a",{b}/{a})', ratio)
    t = 5 + len(pivot)
    cover.write(t, 0, "All states", total_label)
    for j in range(len(years)):
        col = xl_col_to_name(1 + j)
        cover.write_formula(t, 1 + j, f"=SUM({col}6:{col}{t})", total_int)
    a, b = xl_rowcol_to_cell(t, 1), xl_rowcol_to_cell(t, len(years))
    cover.write_formula(t, ratio_col, f"={b}/{a}", fmt(bold=True, top=1, num_format="0.00"))

    comp = pd.read_parquet(MART / "coverage_vs_njdg.parquet").sort_values("njdg_state")
    c0 = t + 3
    cover.write(c0 - 1, 0, f"Open cases in DDL at {ANALYSIS_CUTOFF} vs NJDG pending at 30 Jul 2026 (different dates, so compare shares, not counts)", bold)
    for j, c in enumerate(["State", "DDL open", "NJDG pending", "DDL share", "NJDG share", "Gap (points)", "Status"]):
        cover.write(c0, j, c, head if j in (0, 6) else head_num)
    n = len(comp)
    for i, r in enumerate(comp.itertuples()):
        row = c0 + 1 + i
        excel = row + 1
        cover.write(row, 0, r.njdg_state, text)
        if pd.notna(r.ddl_open):
            cover.write_number(row, 1, float(r.ddl_open), integer)
        if pd.notna(r.pending_total):
            cover.write_number(row, 2, float(r.pending_total), integer)
        cover.write_formula(row, 3, f'=IF(B{excel}="",0,B{excel}/SUM($B${c0 + 2}:$B${c0 + 1 + n}))', pct)
        cover.write_formula(row, 4, f'=IF(C{excel}="",0,C{excel}/SUM($C${c0 + 2}:$C${c0 + 1 + n}))', pct)
        cover.write_formula(row, 5, f"=(D{excel}-E{excel})*100", pts)
        cover.write(row, 6, r.status, text)
    cover.set_column(0, 0, 40)
    cover.set_column(1, ratio_col, 12)
    cover.freeze_panes(5, 1)

    # ------------------------------------------------------------------ act mapping
    m = pd.read_parquet(PARQUET / "maps" / "map_act.parquet")
    q3 = pd.read_parquet(MART / "q3_acts.parquet")
    variants = m.groupby("act_canonical").size().rename("variants")
    examples = (m.sort_values("declared_count", ascending=False).groupby("act_canonical")["act_s"]
                .apply(lambda s: " | ".join(str(x).strip() for x in s.head(4))).rename("examples"))
    table = q3[["act_canonical", "act_family", "n"]].merge(variants, how="left", left_on="act_canonical", right_index=True)
    table = table.merge(examples, how="left", left_on="act_canonical", right_index=True).sort_values("n", ascending=False)
    acts.write(0, 0, "Act-name standardisation", title)
    acts.write(1, 0, "Raw labels rolled up to canonical acts. Every label and its mapping is in data/mart/map_act.csv.", sub)
    for j, c in enumerate(["Canonical act", "Family", "Raw label variants", "Cases", "Share of cases", "Largest raw labels"]):
        acts.write(3, j, c, head_num if c in ("Raw label variants", "Cases", "Share of cases") else head)
    a_first = 4
    for i, r in enumerate(table.itertuples()):
        row = a_first + i
        acts.write(row, 0, r.act_canonical, text)
        acts.write(row, 1, r.act_family, text)
        acts.write_number(row, 2, 0 if pd.isna(r.variants) else float(r.variants), integer)
        acts.write_number(row, 3, float(r.n), integer)
        acts.write_formula(row, 4, f"=D{row + 1}/SUM($D${a_first + 1}:$D${a_first + len(table)})", pct)
        acts.write(row, 5, "" if pd.isna(r.examples) else r.examples, text)
    last = a_first + len(table)
    acts.write(last, 0, "Total", total_label)
    acts.write_blank(last, 1, None, total_label)
    acts.write_formula(last, 2, f"=SUM(C{a_first + 1}:C{last})", total_int)
    acts.write_formula(last, 3, f"=SUM(D{a_first + 1}:D{last})", total_int)
    acts.write_formula(last, 4, f"=SUM(E{a_first + 1}:E{last})", total_pct)
    acts.set_column(0, 0, 48)
    acts.set_column(1, 1, 24)
    acts.set_column(2, 3, 14)
    acts.set_column(4, 4, 10)
    acts.set_column(5, 5, 110)
    acts.freeze_panes(4, 1)

    # ------------------------------------------------------------------ read me
    readme.write(0, 0, "Where Justice Gets Stuck: data-quality scorecard", title)
    readme.write(1, 0, "Source: Development Data Lab eCourts data (CC BY-NC-SA 4.0). Lower-court cases filed 2010-2018.", sub)
    readme.write(3, 0, "How the score works", bold)
    lines = [
        "Each rule measures a failure rate in each state: failures divided by rows checked.",
        "A dimension's score is 100% minus the weighted average failure rate of its rules, using the severity weights below.",
        "Overall is the plain average of the five dimensions. The All states row weights each state by its cases.",
        "A low score means the records are hard to use. It says nothing about how well the courts perform.",
    ]
    for i, line in enumerate(lines):
        readme.write(4 + i, 0, line, text)
    readme.write(10, 0, "Severity", head)
    readme.write(10, 1, "Weight", head)
    for i, (sev, w) in enumerate([("High", 3), ("Medium", 2), ("Low", 1), ("Info", 0)]):
        readme.write(11 + i, 0, sev, text)
        readme.write_number(11 + i, 1, w, input_cell)
    readme.write(15, 0, "Weights are judgement calls and can be edited (blue cells). Every score recalculates. Info rules are reported but not scored.", sub)
    readme.write(17, 0, "Sheets", bold)
    guide = [
        ("Scorecard", "Scores by state and dimension."),
        ("Rules", "Every rule, with national failure rate and how failing rows are treated."),
        ("Issue log", "Every failure and anomaly with severity, sample records and status."),
        ("Coverage", "Cases per state and year, and DDL against NJDG."),
        ("Act mapping", "Raw act-name variants rolled up to canonical acts."),
        ("Rates, Failures, Checked", "The raw counts and rates behind the scores."),
    ]
    for i, (name, desc) in enumerate(guide):
        readme.write(18 + i, 0, name, text)
        readme.write(18 + i, 1, desc, text)
    readme.write(25, 0, "Status values", bold)
    for i, (name, desc) in enumerate([
        ("Mitigated", "The pipeline handles the failing rows."),
        ("Accepted", "A known limit, documented and reported."),
        ("Open", "Needs a decision or a better source."),
    ]):
        readme.write(26 + i, 0, name, text)
        readme.write(26 + i, 1, desc, text)
    readme.set_column(0, 0, 24)
    readme.set_column(1, 1, 90)
    score.activate()
    wb.close()
    print("wrote", path, flush=True)
    return path


if __name__ == "__main__":
    run()
