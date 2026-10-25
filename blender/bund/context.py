"""Surrounding city ring (real OSM footprints, massing only) for wide shots."""
import json
import math
import os
import random

from . import util as U
from .facade import gable_roof, roof_stuff

FACADES = ["facade_tile_white", "facade_tile_beige", "facade_tile_grey", "facade_tile_pink", "facade_hist_dist"]
TOWERS = ["curtain_blue", "curtain_grey", "curtain_green", "facade_tile_white"]
# low-rise lane houses (里弄 / 石库门) and old shophouses: brick walls, tiled pitched roofs
LOW_WALLS = ["brick_grey", "brick_grey", "brick_grey_red", "brick_red", "stucco_grey", "facade_hist_dist"]


def _rect_frame(ring):
    """(fill ratio of the bounding rectangle along the longest edge, short side)."""
    best = max(range(len(ring)), key=lambda i: math.dist(ring[i], ring[(i + 1) % len(ring)]))
    a, b = ring[best], ring[(best + 1) % len(ring)]
    hd = math.atan2(b[1] - a[1], b[0] - a[0])
    c, s = math.cos(-hd), math.sin(-hd)
    us = [(p[0] - a[0]) * c - (p[1] - a[1]) * s for p in ring]
    vs = [(p[0] - a[0]) * s + (p[1] - a[1]) * c for p in ring]
    w, d = max(us) - min(us), max(vs) - min(vs)
    return abs(U.signed_area(ring)) / max(w * d, 1e-6), min(w, d)


def build_all(mats, root, path=None):
    path = path or os.path.join(os.path.dirname(__file__), "..", "..", "data", "context.json")
    if not os.path.exists(path):
        print("[context] no data/context.json, skipped")
        return
    with open(path, encoding="utf-8") as fh:
        cx = json.load(fh)
    col = U.coll("Context_City_Ring", root)
    mb = U.MeshBuilder()
    for p in cx["land"]:
        U.fill(mb, p["ext"], p.get("holes", []), 0.0, "paving_sidewalk")
    for p in cx["parks"]:
        U.fill(mb, p["ext"], p.get("holes", []), 0.05, "grass_park")
    for r in cx["roads"]:
        U.ribbon(mb, [tuple(q) for q in r["p"]], r["w"], 0.03, "asphalt_old")
    for p in cx["water"]:
        U.fill(mb, p["ext"], p.get("holes", []), -1.8, "water_huangpu")
    U.add_obj("Context_Ground_Water_Roads", mb.build("context_ground", mats), col)
    rnd = random.Random(31)
    groups = {}
    for b in cx["buildings"]:
        ring = U.ccw(b["e"])
        if len(ring) < 3:
            continue
        h = b["h"]
        area = abs(U.signed_area(ring))
        bld = {"bld": 0.01 + 0.98 * rnd.random()}
        if h <= 16.0 and 20.0 < area < 1500.0:
            fill, short = _rect_frame(ring)
            if fill > 0.8 and short < 16.0:
                wall = rnd.choice(LOW_WALLS)
                mb = groups.setdefault(wall, U.MeshBuilder())
                mb.cur = bld
                U.walls(mb, ring, -0.3, h, wall)
                U.fill(mb, ring, [], h, "roof_flat")
                roof = "roof_tile_grey" if rnd.random() < 0.72 else "roof_tile_red"
                gable_roof(mb, ring, h, min(3.0, short * 0.38), roof, wall)
                continue
        mat = rnd.choice(TOWERS) if h > 45 else rnd.choice(FACADES)
        mb = groups.setdefault(mat, U.MeshBuilder())
        mb.cur = bld
        U.walls(mb, ring, -0.3, h, mat)
        U.fill(mb, ring, [], h, "roof_flat")
        if h > 18.0 and area > 150.0:
            roof_stuff(mb, ring, h, rnd, per_area=400.0, max_n=3, shed=0.3)
        elif area > 120.0:
            roof_stuff(mb, ring, h, rnd, per_area=600.0, max_n=1, shed=0.35)
    for mat, mb in groups.items():
        U.add_obj(f"Context_Buildings_{mat}", mb.build(f"ctx_{mat}", mats), col)
    print(f"[context] {len(cx['buildings'])} buildings")
    if cx.get("far"):
        _far_ring(cx["far"], mats, col, rnd)


def _far_ring(far, mats, col, rnd):
    """Horizon: a procedural city carpet to 80 km (it fades into the haze), the
    real high-rises and the real river beyond the context ring."""
    mb = U.MeshBuilder()
    R = 80000.0
    U.fill(mb, [(-R, -R), (R, -R), (R, R), (-R, R)], [], -2.5, "far_city")
    for p in far.get("water", []):
        U.fill(mb, p["ext"], p.get("holes", []), -2.3, "water_huangpu")
    U.add_obj("Far_City_Carpet_Water", mb.build("far_ground", mats), col)
    mb = U.MeshBuilder()
    for b in far.get("towers", []):
        ring = U.ccw(b["e"])
        if len(ring) < 3:
            continue
        h = b["h"]
        mb.cur = {"bld": 0.01 + 0.98 * rnd.random()}
        mat = rnd.choice(TOWERS + ["facade_tile_beige", "facade_tile_grey"])
        U.walls(mb, ring, -2.5, h, mat)
        U.fill(mb, ring, [], h, "roof_flat")
    mb.cur = {}
    if len(mb):
        U.add_obj("Far_HighRises", mb.build("far_towers", mats), col)
    print(f"[context] far ring: {len(far.get('towers', []))} high-rises")
