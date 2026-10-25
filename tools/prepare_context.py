"""Surrounding city ring for wide shots: massing only.

Reads data/raw/*_context.geojson (tools/fetch_overture.py --context) and writes
data/context.json with building footprints + heights, river polygons, land,
major roads and parks outside the detailed scene box; plus, if fetched with
--far, the high-rises and water of an ~18 km horizon ring.
"""
import json
import os

import shapely
from shapely.geometry import Point, box
from shapely.ops import unary_union

import prepare_scene as ps

CONTEXT = box(-3000, -3100, 4400, 3550)


def load_ctx(name, suffix="_context"):
    path = os.path.join(ps.ROOT, "data", "raw", name + suffix + ".geojson")
    with open(path, encoding="utf-8") as fh:
        for f in json.load(fh)["features"]:
            yield ps.proj(shapely.geometry.shape(f["geometry"])), f["properties"]


def far_ring():
    """High-rises (>= 45 m / 15 floors) and water out to ~18 km, outside CONTEXT
    (tools/fetch_overture.py --far). Returns None if the data was not fetched."""
    if not os.path.exists(os.path.join(ps.ROOT, "data", "raw", "building_far.geojson")):
        return None
    towers = []
    for g, p in load_ctx("building", "_far"):
        if g.is_empty or CONTEXT.contains(g.centroid):
            continue
        h = p.get("height") or ((p.get("num_floors") or 15) * 3.2 + 2.0)
        for poly in ps.polys(g.simplify(1.5)):
            if poly.area < 60:
                continue
            e = ps.exp_poly(poly, 1.0)
            if e:
                towers.append({"e": e["ext"], "h": round(float(h), 1)})
    water = []
    for g, p in load_ctx("water", "_far"):
        if g.geom_type in ("Polygon", "MultiPolygon") and p.get("subtype") in ("river", "water", "canal", "lake", "reservoir"):
            gi = g.buffer(0).difference(CONTEXT)
            if not gi.is_empty and gi.area > 20000:
                water.append(gi.simplify(4.0))
    water = unary_union(water) if water else None
    return {"towers": towers, "water": ps.exp_geom(water, 20000, 4.0) if water is not None else []}


def main():
    inner = ps.SCENE
    # water: wide river polygons (the scene keeps its own detailed water)
    water = []
    for g, p in load_ctx("water"):
        if p.get("subtype") in ("river", "water", "canal") and g.geom_type in ("Polygon", "MultiPolygon"):
            gi = g.intersection(CONTEXT)
            if not gi.is_empty and gi.area > 2000:
                water.append(gi)
    water = ps.clean(unary_union(water), 500)
    land = ps.clean(CONTEXT.difference(water).difference(inner), 200)
    water_out = ps.clean(water.difference(inner), 200)
    blds = []
    for g, p in load_ctx("building"):
        g = ps.clean(g, 15.0)
        if g.is_empty:
            continue
        c = g.centroid
        if inner.buffer(-5).contains(c) or not CONTEXT.contains(c) or water.contains(c):
            continue
        h = p.get("height")
        fl = p.get("num_floors")
        if h is None:
            if fl:
                h = fl * 3.2 + 1.0
            else:
                a = g.area
                h = 7.0 if a < 150 else (10.5 if a < 600 else (16.0 if a < 2500 else 22.0))
        for poly in ps.polys(g):
            e = ps.exp_poly(poly, 0.6)
            if e:
                blds.append({"e": e["ext"], "h": round(float(h), 1)})
    roads = []
    width = {"motorway": 24, "trunk": 22, "primary": 18, "secondary": 14, "tertiary": 10}
    for g, p in load_ctx("segment"):
        for ln in ps.lines(g):
            ln = ln.difference(inner)
            for piece in ps.lines(ln):
                if piece.length > 10 and piece.intersects(CONTEXT):
                    roads.append({"p": ps.exp_line(piece.simplify(1.5)), "w": width.get(p.get("class"), 10)})
    parks = []
    for g, p in load_ctx("land_use"):
        gi = g.intersection(CONTEXT).difference(inner).difference(water)
        parks += ps.exp_geom(gi, 200, 1.0)
    out = {"bounds": list(CONTEXT.bounds), "water": ps.exp_geom(water_out, 500, 1.0),
           "land": ps.exp_geom(land, 200, 0.5), "buildings": blds, "roads": roads, "parks": parks,
           "attribution": "Overture Maps Foundation / © OpenStreetMap contributors (ODbL)"}
    far = far_ring()
    if far:
        out["far"] = far
        print(f"far ring: {len(far['towers'])} high-rises, {len(far['water'])} water polygons")
    path = os.path.join(ps.ROOT, "data", "context.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"context: {len(blds)} buildings, {len(roads)} roads, {len(parks)} parks, "
          f"{os.path.getsize(path) / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
