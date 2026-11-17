"""The static copy of the dashboard builds from the committed tables, and every file the page asks for exists."""
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
MART = ROOT / "data" / "mart"

pytestmark = pytest.mark.skipif(not (MART / "findings.json").exists(), reason="mart not built")


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    import build_site
    out = tmp_path_factory.mktemp("site") / "site"
    original = build_site.SITE
    build_site.SITE = out
    try:
        build_site.build()
    finally:
        build_site.SITE = original
    return out


def test_every_spec_is_vega_lite_with_data_and_a_description(site):
    specs = sorted((site / "specs").glob("*.json"))
    assert len(specs) >= 30
    for path in specs:
        spec = json.loads(path.read_text(encoding="utf8"))
        assert "vega-lite" in spec["$schema"], path.name
        # Data sits at the top, or inside each layer (the map's layers carry their own geometry).
        layers = spec.get("layer", [])
        assert spec.get("datasets") or spec.get("data") or any(layer.get("data") for layer in layers), path.name
        assert spec.get("description"), path.name


def test_every_file_the_page_requests_exists(site):
    script = (site / "app.js").read_text(encoding="utf8")
    static = set(re.findall(r'"((?:specs|data|downloads)/[\w./-]+\.(?:json|pdf|xlsx))"', script))
    assert static, "the page should request data files"
    missing = [p for p in static if not (site / p).exists()]
    assert not missing, missing


def test_state_pages_cover_every_state(site):
    index = json.loads((site / "data" / "states" / "index.json").read_text(encoding="utf8"))
    assert len(index) >= 25
    for entry in index:
        page = json.loads((site / "data" / "states" / f"{entry['slug']}.json").read_text(encoding="utf8"))
        assert page["state"] == entry["state"]
        assert page["survival"]["datasets"]


@pytest.mark.skipif(not (MART / "ml_summary.json").exists(), reason="model tables not built")
def test_what_if_tree_holds_four_scores_and_a_count(site):
    tree = json.loads((site / "data" / "whatif.json").read_text(encoding="utf8"))
    state = next(iter(tree.values()))
    court = next(iter(next(iter(state.values())).values()))
    scores = next(iter(court["types"].values()))
    assert len(scores) == 5 and 0 <= scores[0] <= 1 and isinstance(scores[4], int)
