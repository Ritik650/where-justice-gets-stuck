"""The fast weighted AUC behind the bootstrap matches scikit-learn, and the threshold arithmetic is right."""
import numpy as np
from sklearn.metrics import roc_auc_score

from src.ml.metrics import RankedScores, binary_metrics, bootstrap_auc_gap, calibration_table, delay_flags_at, threshold_for_share


def data(n=5000, seed=0):
    rng = np.random.default_rng(seed)
    y = rng.integers(0, 2, n)
    score = np.round(rng.random(n) + 0.3 * y, 2)  # rounding creates many ties
    return y, score, rng


def test_weighted_auc_matches_sklearn_with_ties_and_weights():
    y, score, rng = data()
    w = rng.integers(0, 4, len(y)).astype(float)
    r = RankedScores(y, score)
    assert abs(r.auc() - roc_auc_score(y, score)) < 1e-12
    assert abs(r.auc(w) - roc_auc_score(y, score, sample_weight=w)) < 1e-12


def test_bootstrap_is_repeatable_and_paired():
    y, score, rng = data()
    other = score + rng.normal(0, 0.3, len(y))
    a = bootstrap_auc_gap(y, score, other, 200, seed=5)
    b = bootstrap_auc_gap(y, score, other, 200, seed=5)
    assert a["ci_low"] == b["ci_low"] and a["ci_high"] == b["ci_high"]
    assert a["ci_low"] < a["gap"] < a["ci_high"]
    assert abs(a["gap"] - (roc_auc_score(y, score) - roc_auc_score(y, other))) < 1e-12


def test_resampling_clusters_widens_the_interval_when_clusters_differ():
    rng = np.random.default_rng(1)
    clusters = np.repeat(np.arange(60), 100)
    effect = rng.normal(0, 1.0, 60)[clusters]  # how much better model a is varies by cluster
    y = rng.integers(0, 2, len(clusters))
    a = y + rng.normal(0, 1, len(y)) * np.exp(-effect)
    b = y + rng.normal(0, 1, len(y))
    case = bootstrap_auc_gap(y, a, b, 300, seed=2)
    court = bootstrap_auc_gap(y, a, b, 300, seed=2, clusters=clusters)
    assert court["ci_high"] - court["ci_low"] > case["ci_high"] - case["ci_low"]


def test_delay_flags_by_hand():
    y = np.array([0, 0, 1, 1, 0, 1])
    p = np.array([0.1, 0.4, 0.45, 0.8, 0.7, 0.9])
    m = delay_flags_at(y, p, 0.5)  # flags the first three; two of them were delayed
    assert m["flagged"] == 3 and m["true_positives"] == 2
    assert abs(m["precision_delay"] - 2 / 3) < 1e-12
    assert abs(m["recall_delay"] - 2 / 3) < 1e-12


def test_calibration_bins_cover_every_row_and_capacity_cut_flags_its_share():
    y, score, _ = data()
    p = np.clip(score / score.max(), 0, 1)
    table = calibration_table(y, p, bins=10)
    assert sum(r["n"] for r in table) == len(y)
    cut = threshold_for_share(p, 0.2)
    assert abs((p < cut).mean() - 0.2) < 0.02
    assert 0 <= binary_metrics(y, p)["ece"] <= 1
