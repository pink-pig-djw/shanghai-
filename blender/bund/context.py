"""Surrounding city ring (real OSM footprints, massing only) for wide shots."""
import json
import os
import random

from . import util as U

FACADES = ["facade_tile_white", "facade_tile_beige", "facade_tile_grey", "facade_tile_pink", "facade_hist_dist"]
TOWERS = ["curtain_blue", "curtain_grey", "curtain_green", "facade_tile_white"]


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
        mat = rnd.choice(TOWERS) if h > 45 else rnd.choice(FACADES)
        mb = groups.setdefault(mat, U.MeshBuilder())
        U.walls(mb, ring, -0.3, h, mat)
        U.fill(mb, ring, [], h, "roof_flat")
    for mat, mb in groups.items():
        U.add_obj(f"Context_Buildings_{mat}", mb.build(f"ctx_{mat}", mats), col)
    print(f"[context] {len(cx['buildings'])} buildings")
