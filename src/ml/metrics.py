"""Metrics, including a weighted AUC fast enough for 1,000 bootstrap resamples of half a million cases.

A bootstrap resample is the original rows with integer weights (how many times each row was drawn), so the scores
are sorted once and every resample costs two bincounts and a cumulative sum.
"""
from __future__ import annotations

import numpy as np
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score

EPS = 1e-6


class RankedScores:
    """Scores grouped by distinct value, so a weighted AUC needs no sorting."""

    def __init__(self, y: np.ndarray, score: np.ndarray):
        self.y = np.asarray(y, dtype=np.float64)
        values, self.group = np.unique(np.asarray(score, dtype=np.float64), return_inverse=True)
        self.n_groups = len(values)

    def auc(self, weights: np.ndarray | None = None) -> float:
        w = np.ones_like(self.y) if weights is None else np.asarray(weights, dtype=np.float64)
        pos = np.bincount(self.group, weights=w * self.y, minlength=self.n_groups)
        neg = np.bincount(self.group, weights=w * (1.0 - self.y), minlength=self.n_groups)
        total_pos, total_neg = pos.sum(), neg.sum()
        if total_pos == 0 or total_neg == 0:
            return float("nan")
        neg_below = np.cumsum(neg) - neg
        # A tie between a positive and a negative counts as half a correct ordering, as in roc_auc_score.
        return float((pos * (neg_below + 0.5 * neg)).sum() / (total_pos * total_neg))


def binary_metrics(y: np.ndarray, p: np.ndarray) -> dict:
    """Ranking, precision-recall and probability metrics for scores in [0, 1]."""
    y = np.asarray(y).astype(int)
    p = np.clip(np.asarray(p, dtype=np.float64), EPS, 1 - EPS)
    if len(np.unique(y)) < 2:
        return {"n": int(len(y)), "positive_rate": float(y.mean()) if len(y) else float("nan")}
    return {
        "n": int(len(y)),
        "positive_rate": float(y.mean()),
        "roc_auc": float(roc_auc_score(y, p)),
        "pr_auc": float(average_precision_score(y, p)),
        # The class a registry would act on: cases not decided within the window.
        "pr_auc_delay": float(average_precision_score(1 - y, 1 - p)),
        "brier": float(brier_score_loss(y, p)),
        "log_loss": float(log_loss(y, p, labels=[0, 1])),
        "ece": expected_calibration_error(y, p),
    }


def calibration_table(y: np.ndarray, p: np.ndarray, bins: int = 10) -> list[dict]:
    """Mean prediction against the observed rate in equal-count bins of the prediction."""
    y = np.asarray(y).astype(float)
    p = np.asarray(p, dtype=np.float64)
    order = np.argsort(p, kind="stable")
    rows = []
    for i, idx in enumerate(np.array_split(order, bins)):
        if len(idx) == 0:
            continue
        rows.append({"bin": i + 1, "n": int(len(idx)), "mean_predicted": float(p[idx].mean()),
                     "observed_rate": float(y[idx].mean()), "low": float(p[idx].min()), "high": float(p[idx].max())})
    return rows


def expected_calibration_error(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    table = calibration_table(y, p, bins)
    n = sum(r["n"] for r in table)
    return float(sum(r["n"] * abs(r["mean_predicted"] - r["observed_rate"]) for r in table) / n)


def delay_flags_at(y: np.ndarray, p: np.ndarray, threshold: float) -> dict:
    """Flag a case as at risk of delay when its chance of a decision within the window is below `threshold`.

    Precision and recall are for the delay class: of flagged cases, the share that did overrun; of cases that
    overran, the share that were flagged.
    """
    y = np.asarray(y).astype(int)
    flagged = np.asarray(p) < threshold
    delayed = y == 0
    tp = int((flagged & delayed).sum())
    return {
        "threshold": float(threshold),
        "flagged_share": float(flagged.mean()),
        "precision_delay": tp / int(flagged.sum()) if flagged.any() else float("nan"),
        "recall_delay": tp / int(delayed.sum()) if delayed.any() else float("nan"),
        "flagged": int(flagged.sum()),
        "true_positives": tp,
    }


def threshold_for_share(p: np.ndarray, share: float) -> float:
    """The probability below which `share` of cases fall: flagging below it reviews that share of filings."""
    return float(np.quantile(np.asarray(p, dtype=np.float64), share))


def bootstrap_auc_gap(y: np.ndarray, score_a: np.ndarray, score_b: np.ndarray, resamples: int, seed: int,
                      clusters: np.ndarray | None = None) -> dict:
    """Paired bootstrap of AUC(a) - AUC(b) on the same resamples.

    With `clusters` (for example a court ID per row), whole clusters are resampled, which respects the correlation
    between cases heard by the same court and gives a wider, more honest interval than resampling cases.
    """
    ra, rb = RankedScores(y, score_a), RankedScores(y, score_b)
    rng = np.random.default_rng(seed)
    n = len(y)
    if clusters is not None:
        _, cluster_idx = np.unique(clusters, return_inverse=True)
        n_clusters = int(cluster_idx.max()) + 1
    gaps, aucs_a, aucs_b = np.empty(resamples), np.empty(resamples), np.empty(resamples)
    for i in range(resamples):
        if clusters is None:
            w = np.bincount(rng.integers(0, n, n), minlength=n).astype(np.float64)
        else:
            counts = np.bincount(rng.integers(0, n_clusters, n_clusters), minlength=n_clusters)
            w = counts[cluster_idx].astype(np.float64)
        aucs_a[i], aucs_b[i] = ra.auc(w), rb.auc(w)
        gaps[i] = aucs_a[i] - aucs_b[i]
    point_a, point_b = ra.auc(), rb.auc()
    lo, hi = np.nanpercentile(gaps, [2.5, 97.5])
    return {
        "auc_a": point_a, "auc_b": point_b, "gap": point_a - point_b,
        "ci_low": float(lo), "ci_high": float(hi), "resamples": int(resamples),
        "share_gap_positive": float(np.mean(gaps > 0)),
        "gaps": gaps,
    }


def slice_auc(y: np.ndarray, p: np.ndarray) -> float:
    y = np.asarray(y)
    if len(np.unique(y)) < 2:
        return float("nan")
    return float(roc_auc_score(y, p))
