"""Static figures for reports/ml_poc_report.md, in the project's chart style (docs/design/stitch_design_tokens.md).

Colour rules: one series is drawn in the accent; several series use the validated categorical slots in fixed order,
always with a legend and direct labels; context is grey. Every figure has a table beside it in the report.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

INK, BODY, MUTED, HAIRLINE, PANEL = "#18181B", "#27272A", "#71717A", "#E5E3DF", "#FFFFFF"
ACCENT, CONTEXT = "#1E40AF", "#C9C7C1"
SLOTS = ["#2a78d6", "#eb6834", "#1baf7a"]  # checked with the colour-vision validator; the third needs labels

# The design's typeface is Inter. Use the first installed font from this list, so a machine without Inter falls back
# quietly instead of logging a warning for every label.
_INSTALLED = {f.name for f in matplotlib.font_manager.fontManager.ttflist}
FAMILY = next((f for f in ("Inter", "Segoe UI", "Helvetica", "Arial", "DejaVu Sans") if f in _INSTALLED), "sans-serif")

plt.rcParams.update({
    "font.family": FAMILY, "font.size": 9, "axes.edgecolor": HAIRLINE,
    "axes.labelcolor": MUTED, "axes.titlecolor": INK, "axes.titleweight": "bold", "axes.titlesize": 11, "axes.titlelocation": "left",
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.grid": True, "grid.color": HAIRLINE, "grid.linewidth": 0.75,
    "axes.spines.top": False, "axes.spines.right": False, "figure.facecolor": PANEL, "axes.facecolor": PANEL,
    "legend.frameon": False, "savefig.dpi": 160, "savefig.bbox": "tight",
})


def _save(fig, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)
    return path.name


def class_balance(by_year: pd.DataFrame, path: Path) -> str:
    """Share decided within 24 months, by filing year: one series, so one colour and no legend."""
    fig, ax = plt.subplots(figsize=(6.4, 2.8))
    ax.plot(by_year["filing_year"], by_year["rate_24m"], color=ACCENT, linewidth=2, marker="o", markersize=5)
    for x, y in zip(by_year["filing_year"], by_year["rate_24m"]):
        ax.annotate(f"{y:.0%}", (x, y), textcoords="offset points", xytext=(0, 7), ha="center", color=BODY, fontsize=8)
    ax.set_ylim(0, 1)
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
    ax.set_xlabel("Filing year")
    ax.set_ylabel("Decided within 24 months")
    ax.grid(axis="x", visible=False)
    ax.set_title("Later filings are decided faster: early digital records lean to long cases", fontsize=10)
    return _save(fig, path)


def model_auc(table: pd.DataFrame, path: Path, focus: str = "M2 LightGBM") -> str:
    """Test ROC-AUC per model: the chosen model in the accent, the rest as context."""
    d = table.sort_values("roc_auc")
    fig, ax = plt.subplots(figsize=(6.4, 0.42 * len(d) + 0.9))
    colours = [ACCENT if m == focus else CONTEXT for m in d["model"]]
    ax.barh(d["model"], d["roc_auc"], height=0.55, color=colours)
    for i, v in enumerate(d["roc_auc"]):
        ax.text(v + 0.005, i, f"{v:.3f}", va="center", color=BODY, fontsize=8)
    ax.set_xlim(0.45, max(1.0, float(d["roc_auc"].max()) + 0.05))
    ax.set_xlabel("ROC-AUC on the 2016 test filings (0.5 = no better than chance)")
    ax.grid(axis="y", visible=False)
    ax.set_title("Test ROC-AUC by model", fontsize=10)
    return _save(fig, path)


def gap_intervals(gaps: dict, path: Path) -> str:
    """The AUC gain of M2 over B1, with 95% intervals from two resampling schemes. One axis, one colour."""
    rows = [("Resampling cases", gaps["m2_vs_b1_case"]), ("Resampling courts", gaps["m2_vs_b1_court"])]
    fig, ax = plt.subplots(figsize=(6.4, 1.9))
    for i, (label, g) in enumerate(rows):
        ax.plot([g["ci_low"], g["ci_high"]], [i, i], color=ACCENT, linewidth=2, solid_capstyle="round")
        ax.plot(g["gap"], i, "o", color=ACCENT, markersize=8, markeredgecolor=PANEL, markeredgewidth=2)
        ax.text(g["ci_high"], i + 0.22, f"{g['gap']:+.3f}  ({g['ci_low']:+.3f} to {g['ci_high']:+.3f})", ha="right", color=BODY, fontsize=8)
    ax.axvline(0, color=MUTED, linewidth=0.75)
    ax.set_yticks(range(len(rows)), [r[0] for r in rows])
    ax.set_ylim(-0.6, len(rows) - 0.3)
    lo = min(0.0, min(g["ci_low"] for _, g in rows)) - 0.005
    ax.set_xlim(lo, max(g["ci_high"] for _, g in rows) + 0.01)
    ax.set_xlabel("ROC-AUC of M2 minus ROC-AUC of B1 (the court's own history)")
    ax.grid(axis="y", visible=False)
    ax.set_title("What the model adds over court history, with 95% bootstrap intervals", fontsize=10)
    return _save(fig, path)


def calibration(curves: pd.DataFrame, path: Path) -> str:
    """Reliability diagram: raw and recalibrated M2 against the diagonal. Two series: legend plus direct labels."""
    fig, ax = plt.subplots(figsize=(4.6, 4.2))
    ax.plot([0, 1], [0, 1], color=MUTED, linewidth=0.75, label="Perfect calibration")
    # Each curve is labelled beside its third point, the as-trained one above-left and the recalibrated one
    # below-right, so neither label meets a line; the reference diagonal is named in the legend.
    for slot, (key, label) in enumerate((("m2", "M2 as trained"), ("m2_cal", "M2 after isotonic recalibration"))):
        d = curves[curves["key"] == key].reset_index(drop=True)
        ax.plot(d["mean_predicted"], d["observed_rate"], color=SLOTS[slot], linewidth=2, marker="o", markersize=5,
                markeredgecolor=PANEL, markeredgewidth=1.5, label=label)
        anchor = d.iloc[min(2, len(d) - 1)]
        ax.annotate("as trained" if slot == 0 else "recalibrated", (anchor["mean_predicted"], anchor["observed_rate"]),
                    textcoords="offset points", xytext=(-8, 9) if slot == 0 else (12, -20), ha="right" if slot == 0 else "left",
                    color=BODY, fontsize=8)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xlabel("Mean predicted chance of a decision within 24 months")
    ax.set_ylabel("Observed share decided within 24 months")
    ax.legend(loc="lower right", fontsize=8)
    ax.set_title("Calibration on the 2016 test filings", fontsize=10)
    return _save(fig, path)


def importance(imp: pd.DataFrame, path: Path, top: int = 12) -> str:
    d = imp.head(top).iloc[::-1]
    fig, ax = plt.subplots(figsize=(6.4, 0.32 * len(d) + 0.9))
    ax.barh(d["feature"], d["auc_drop"], height=0.55, color=ACCENT)
    for i, (v, sd) in enumerate(zip(d["auc_drop"], d["auc_drop_sd"])):
        ax.text(v + float(d["auc_drop"].max()) * 0.01, i, f"{v:.3f}", va="center", color=BODY, fontsize=8)
    ax.set_xlabel("Drop in test ROC-AUC when the feature is shuffled")
    ax.grid(axis="y", visible=False)
    ax.set_title("Permutation importance (M2, test filings)", fontsize=10)
    return _save(fig, path)


def seen_unseen(both: pd.DataFrame, path: Path, keys: list[str]) -> str:
    """ROC-AUC on seen and unseen courts: two series, slots 1 and 2, legend and labels."""
    d = both.set_index("key").loc[keys].reset_index()
    y = np.arange(len(d))
    fig, ax = plt.subplots(figsize=(6.4, 0.5 * len(d) + 1.0))
    for slot, (col, label) in enumerate((("roc_auc_seen", "Courts seen in training"), ("roc_auc_unseen", "Courts held out entirely"))):
        ax.plot(d[col], y, "o", color=SLOTS[slot], markersize=8, markeredgecolor=PANEL, markeredgewidth=2, label=label, zorder=3)
    for i, r in d.iterrows():
        ax.plot([r["roc_auc_seen"], r["roc_auc_unseen"]], [i, i], color=CONTEXT, linewidth=2, zorder=2)
        ax.text(max(r["roc_auc_seen"], r["roc_auc_unseen"]) + 0.006, i, f"{r['roc_auc_seen']:.3f} / {r['roc_auc_unseen']:.3f}",
                va="center", color=BODY, fontsize=8)
    ax.set_yticks(y, d["model"])
    ax.set_xlabel("ROC-AUC on 2016 filings")
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2, fontsize=8)
    ax.grid(axis="y", visible=False)
    ax.set_xlim(min(d["roc_auc_seen"].min(), d["roc_auc_unseen"].min()) - 0.03, max(d["roc_auc_seen"].max(), d["roc_auc_unseen"].max()) + 0.07)
    return _save(fig, path)


def state_slices(sl: pd.DataFrame, path: Path, top: int = 20) -> str:
    """ROC-AUC of M2 and B1 within each large state: two series with a legend; the axis carries the values."""
    d = sl[(sl["dimension"] == "State") & sl["rankable"]].nlargest(top, "n").sort_values("auc_m2")
    y = np.arange(len(d))
    fig, ax = plt.subplots(figsize=(6.4, 0.27 * len(d) + 1.1))
    for i, r in enumerate(d.itertuples()):
        ax.plot([r.auc_b1, r.auc_m2], [i, i], color=CONTEXT, linewidth=2, zorder=2)
    ax.plot(d["auc_m2"], y, "o", color=SLOTS[0], markersize=7, markeredgecolor=PANEL, markeredgewidth=1.5, label="M2 LightGBM", zorder=3)
    ax.plot(d["auc_b1"], y, "o", color=SLOTS[1], markersize=7, markeredgecolor=PANEL, markeredgewidth=1.5, label="B1 court history", zorder=3)
    ax.set_yticks(y, d["slice"])
    ax.set_xlabel("ROC-AUC within the state (2016 test filings)")
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2, fontsize=8)
    ax.grid(axis="y", visible=False)
    return _save(fig, path)
