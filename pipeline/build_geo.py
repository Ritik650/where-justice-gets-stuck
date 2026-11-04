"""Turn DataMeet's Census 2011 district shapefile into small GeoJSON files for the dashboard map.

The output is committed, so running the dashboard needs neither pyshp nor shapely.
Boundaries: DataMeet India community, CC BY 4.0. For display only; this is not an official map.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import requests
import shapefile
from shapely import set_precision
from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import EXTERNAL, ROOT  # noqa: E402
from standardize import CENSUS_UNIT_MERGE  # noqa: E402

OUT = ROOT / "data" / "geo"
SOURCE = "https://raw.githubusercontent.com/datameet/maps/master/Districts/Census_2011"
TOLERANCE = 0.012  # degrees, about 1.3 km: invisible at national zoom, and it cuts the file by about 95%
MIN_AREA = 1e-5  # square degrees, about 0.1 sq km: slivers left over after snapping
STATE_MIN_AREA = 2e-3  # about 25 sq km: state outlines skip tiny islands, which otherwise ink over the delta coasts


def prepared(geom, tolerance: float, min_area: float = MIN_AREA) -> dict:
    """Simplify, snap to 3 decimals, drop slivers, then wind every ring clockwise, in that order.

    D3 treats a counter-clockwise ring as everything except the polygon, so one reversed sliver floods the whole
    map. Winding has to come last, because rounding can collapse or flip a very small ring.
    """
    snapped = set_precision(geom.simplify(tolerance, preserve_topology=True), 0.001)
    parts = [p for p in (snapped.geoms if hasattr(snapped, "geoms") else [snapped])
             if isinstance(p, Polygon) and p.area > min_area]
    if not parts:  # a very small territory: keep its largest original part instead of losing it
        largest = max(geom.geoms, key=lambda p: p.area) if hasattr(geom, "geoms") else geom
        parts = [set_precision(largest, 0.001).envelope]
    wound = [orient(p, sign=-1.0) for p in parts]
    return mapping(wound[0] if len(wound) == 1 else MultiPolygon(wound))


def fetch_source() -> None:
    """The 10 MB source shapefile is not committed, so fetch it from DataMeet when it is missing."""
    for ext in ("shp", "dbf", "shx"):
        path = EXTERNAL / f"2011_Dist.{ext}"
        if not path.exists():
            reply = requests.get(f"{SOURCE}/2011_Dist.{ext}", timeout=120)
            reply.raise_for_status()
            path.write_bytes(reply.content)


def run() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fetch_source()
    reader = shapefile.Reader(str(EXTERNAL / "2011_Dist.shp"))
    units: dict[int, list] = {}
    names: dict[int, tuple[str, str]] = {}
    states: dict[str, list] = {}
    skipped = []
    for sr in reader.iterShapeRecords():
        code, name, state = sr.record["censuscode"], sr.record["DISTRICT"], sr.record["ST_NM"]
        geom = shape(sr.shape.__geo_interface__).buffer(0)
        states.setdefault(state, []).append(geom)
        if not code:
            skipped.append((name, state))
            continue
        unit = CENSUS_UNIT_MERGE.get(code, code)
        units.setdefault(unit, []).append(geom)
        if code == unit:
            names[unit] = (name, state)
    print("polygons without a census code:", skipped)

    features = []
    for unit, parts in sorted(units.items()):
        features.append({
            "type": "Feature", "id": unit,
            "properties": {"unit_id": unit, "name": names[unit][0], "state": names[unit][1]},
            "geometry": prepared(unary_union(parts), TOLERANCE),
        })
    path = OUT / "india_districts_2011.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}, separators=(",", ":")))
    print(f"{path.name}: {len(features)} units, {path.stat().st_size / 1e6:.2f} MB")

    state_features = []
    for state, parts in sorted(states.items()):
        state_features.append({"type": "Feature", "properties": {"state": state}, "geometry": prepared(unary_union(parts), TOLERANCE * 2, STATE_MIN_AREA)})
    path = OUT / "india_states_2011.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": state_features}, separators=(",", ":")))
    print(f"{path.name}: {len(state_features)} states, {path.stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    run()
