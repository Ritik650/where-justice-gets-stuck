"""The sample is exactly stratified and repeatable; the splits are disjoint, temporal, hold out whole courts, and repeat."""
import dataclasses

import pandas as pd
import pytest
from ml_helpers import settings_in

from src.ml import features as F
from src.ml import sample, split
from src.ml.fixture import generate

SAMPLE = 12_000  # about a third of the fixture's population, so the draw is a real draw


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("split")
    s = settings_in(tmp, sample_size=SAMPLE)
    generate(s.source)
    info = sample.run(s)
    F.run(s)
    split.run(s)
    return s, info


def frames(s):
    sp = pd.read_parquet(s.splits_path)
    feats = pd.read_parquet(s.features_path, columns=["ddl_case_id", "court", "filing_year"])
    return feats.merge(sp, on="ddl_case_id")


def test_sample_is_exactly_stratified(built):
    s, info = built
    strata = pd.read_csv(s.reports / "sample_strata.csv")
    assert (strata["sampled"] == strata["target"]).all()
    assert abs(info["sampled"] - SAMPLE) <= len(strata)  # per-stratum rounding only


def test_sample_repeats_and_changes_with_the_seed(built, tmp_path):
    s, info = built
    again = dataclasses.replace(s, work=tmp_path / "again", reports=tmp_path / "again_reports")
    assert sample.run(again)["id_hash"] == info["id_hash"]
    cfg = {**s.cfg, "seed": s.seed + 1}
    other = dataclasses.replace(s, cfg=cfg, work=tmp_path / "other", reports=tmp_path / "other_reports")
    assert sample.run(other)["id_hash"] != info["id_hash"]


def test_every_sampled_case_is_in_exactly_one_split(built):
    s, _ = built
    sp = pd.read_parquet(s.splits_path)
    ids = pd.read_parquet(s.sample_path, columns=["ddl_case_id"])["ddl_case_id"]
    assert sp["ddl_case_id"].is_unique
    assert set(sp["ddl_case_id"]) == set(ids)


def test_splits_follow_filing_years(built):
    s, _ = built
    d = frames(s)
    sp = s.cfg["split"]
    years = d.groupby("split")["filing_year"].agg(["min", "max"])
    assert years.loc["train", "min"] >= sp["train_years"][0] and years.loc["train", "max"] <= sp["train_years"][1]
    assert (years.loc["valid"] == sp["valid_year"]).all()
    assert (years.loc["test"] == sp["test_year"]).all()
    assert (years.loc["test_unseen"] == sp["test_year"]).all()


def test_held_out_courts_never_reach_training(built):
    s, _ = built
    d = frames(s)
    held = set(d.loc[d["split"].isin(["test_unseen", "unused_unseen_court"]), "court"])
    seen = set(d.loc[d["split"].isin(["train", "valid", "test"]), "court"])
    assert held and held.isdisjoint(seen)
    share = len(held) / (len(held) + len(seen))
    assert abs(share - s.cfg["split"]["unseen_court_share"]) < 0.05


def test_split_assignment_ignores_row_order(built):
    s, _ = built
    feats = pd.read_parquet(s.features_path, columns=["ddl_case_id", "court", "filing_year", "label_24m"])
    a = split.assign(feats, s)
    b = split.assign(feats.sample(frac=1, random_state=3), s)
    assert a.sort_index().equals(b.sort_index())
