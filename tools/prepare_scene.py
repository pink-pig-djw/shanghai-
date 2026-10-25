"""Turn the raw Overture/OSM extracts into a Blender-ready scene description.

Reads  data/raw/*.geojson   (written by tools/fetch_overture.py)
       data/landmarks.json  (hand-curated historic building list)
Writes data/scene.json      (local metres: +X east, +Y north, origin at
                             121.4875E 31.2390N on the Bund promenade)

Everything that needs geometry processing (road surfaces, lane markings,
zebra crossings, kerbs, promenade deck, tree and lamp placement, building
footprints) happens here with shapely, so the Blender side only has to turn
ready-made polygons and polylines into meshes.

Usage: python tools/prepare_scene.py
"""
import argparse
import json
import math
import os
import random
from collections import defaultdict

import numpy as np
import pyproj
import shapely
from shapely.geometry import (LineString, MultiLineString, Point, Polygon,
                              box, shape)
from shapely.geometry.polygon import orient
from shapely.ops import linemerge, nearest_points, substring, unary_union

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
LON0, LAT0 = 121.4875, 31.2390

SCENE = box(-600, -1250, 2450, 1000)     # ground plane extent
CORE = box(-530, -600, 250, 950)         # full detail: Bund, 外滩源 block, Hongkou bank
ROADS = box(-600, -1250, 2450, 1000)     # area covered by road data
PUXI_BUND = box(-320, -600, 140, 660)    # used to pick the Puxi bank of the Huangpu

# vertical datum (metres, road surface = 0)
Z_WATER = -1.8      # mid-tide Huangpu level
Z_PAVE = 0.15       # kerb height
Z_GREEN = 0.30
Z_DECK = 1.80       # Bund promenade on top of the flood wall
PARAPET = 1.10      # flood wall parapet above deck -> top ~= +6.9 m Wusong datum
DECK_WIDTH = 15.0   # "观景大道宽约15米"
LEVEL_H = 6.5       # height per OSM level for viaducts

_TM = pyproj.Transformer.from_crs(
    "EPSG:4326",
    f"+proj=tmerc +lat_0={LAT0} +lon_0={LON0} +k=1 +x_0=0 +y_0=0 +ellps=WGS84 +units=m",
    always_xy=True)

rng = random.Random(1843)  # year the Bund was laid out; keeps placement deterministic


# --------------------------------------------------------------------------
# geometry helpers
# --------------------------------------------------------------------------

def proj(g):
    return shapely.transform(g, lambda c: np.column_stack(_TM.transform(c[:, 0], c[:, 1])))


def load(name):
    path = os.path.join(ROOT, "data", "raw", name + ".geojson")
    with open(path, encoding="utf-8") as fh:
        for f in json.load(fh)["features"]:
            yield proj(shape(f["geometry"])), f["properties"]


def polys(g):
    if g is None or g.is_empty:
        return []
    if g.geom_type == "Polygon":
        return [g]
    if hasattr(g, "geoms"):
        out = []
        for p in g.geoms:
            out += polys(p)
        return out
    return []


def lines(g):
    if g is None or g.is_empty:
        return []
    if g.geom_type == "LineString":
        return [g]
    if g.geom_type == "LinearRing":
        return [LineString(g.coords)]
    if hasattr(g, "geoms"):
        out = []
        for p in g.geoms:
            out += lines(p)
        return out
    return []


def clean(g, min_area=0.5):
    if g is None or g.is_empty:
        return Polygon()
    g = shapely.make_valid(g)
    ps = [p for p in polys(g) if p.area >= min_area]
    return unary_union(ps) if ps else Polygon()


def R(v):
    return round(float(v), 2)


def exp_poly(p, simplify=0.05, min_hole=0.3):
    p = p.simplify(simplify, preserve_topology=True)
    if p.is_empty or p.geom_type != "Polygon":
        return None
    p = orient(p, 1.0)
    ext = [[R(x), R(y)] for x, y in list(p.exterior.coords)[:-1]]
    if len(ext) < 3:
        return None
    holes = []
    for r in p.interiors:
        if Polygon(r).area >= min_hole:
            holes.append([[R(x), R(y)] for x, y in list(r.coords)[:-1]])
    return {"ext": ext, "holes": holes}


def exp_geom(g, min_area=0.3, simplify=0.05):
    out = []
    for p in polys(g):
        if p.area >= min_area:
            e = exp_poly(p, simplify)
            if e:
                out.append(e)
    return out


def exp_line(l, z=None):
    if z is None:
        return [[R(x), R(y)] for x, y in l.coords]
    return [[R(x), R(y), R(zz)] for (x, y), zz in zip(l.coords, z)]


def heading_at(line, s, ds=1.0):
    a = line.interpolate(max(0.0, s - ds))
    b = line.interpolate(min(line.length, s + ds))
    return math.atan2(b.y - a.y, b.x - a.x)


def offset_pt(line, s, d):
    """Point at arc length s, shifted d metres to the LEFT of the line."""
    p = line.interpolate(s)
    h = heading_at(line, s)
    return Point(p.x - d * math.sin(h), p.y + d * math.cos(h)), h


def offset_line(line, d):
    """Offset to the left (d>0) or right (d<0) keeping the direction."""
    if abs(d) < 1e-6:
        return line
    o = line.offset_curve(d, join_style="round", quad_segs=4)
    ls = lines(o)
    if not ls:
        return None
    return max(ls, key=lambda l: l.length)


def dashes(line, on, off, phase=0.0):
    out = []
    L = line.length
    s = -phase
    while s < L:
        a, b = max(s, 0.0), min(s + on, L)
        if b - a > 0.25:
            out.append(substring(line, a, b))
        s += on + off
    return out


def poisson(poly, spacing, rnd, max_pts=100000, tries=30):
    """Bridson-style dart throwing inside a polygon."""
    if poly.is_empty:
        return []
    minx, miny, maxx, maxy = poly.bounds
    cell = spacing / math.sqrt(2)
    grid = {}
    pts = []
    prep = shapely.prepared.prep(poly)
    n_try = int(poly.area / (spacing * spacing) * tries) + 10
    for _ in range(n_try):
        x = rnd.uniform(minx, maxx)
        y = rnd.uniform(miny, maxy)
        gx, gy = int((x - minx) / cell), int((y - miny) / cell)
        ok = True
        for ix in range(gx - 2, gx + 3):
            for iy in range(gy - 2, gy + 3):
                q = grid.get((ix, iy))
                if q and (q[0] - x) ** 2 + (q[1] - y) ** 2 < spacing * spacing:
                    ok = False
                    break
            if not ok:
                break
        if ok and prep.contains(Point(x, y)):
            grid[(gx, gy)] = (x, y)
            pts.append((x, y))
            if len(pts) >= max_pts:
                break
    return pts


_BUF = {}


def pbuf(key, geom, d):
    """Prepared, cached buffer of a geometry (buffering big unions is slow)."""
    k = (key, d)
    if k not in _BUF:
        g = geom if d == 0 else geom.buffer(d)
        _BUF[k] = shapely.prepared.prep(g)
    return _BUF[k]


# --------------------------------------------------------------------------
# roads
# --------------------------------------------------------------------------

DRIVE = {"motorway", "trunk", "primary", "secondary", "tertiary", "residential",
         "unclassified", "living_street", "service"}

# (lanes when two-way, lanes when one-way)
CLASS_LANES = {"motorway": (6, 3), "trunk": (4, 2), "primary": (4, 3), "secondary": (4, 3),
               "tertiary": (2, 2), "residential": (2, 2), "unclassified": (2, 1),
               "living_street": (1, 1), "service": (1, 1)}
# Lane counts for named roads. 中山东一路's surface road was cut from 11 lanes
# to 4 in the 2010 renovation (China Daily, 2010-03-28), through traffic uses
# the Bund Tunnel below; the rest are estimates from carriageway geometry.
NAME_LANES = {
    "中山东一路": (4, 2), "中山东二路": (6, 3), "延安东路": (8, 4), "北京东路": (4, 2),
    "四川中路": (2, 2), "福州路": (2, 2), "广东路": (2, 2), "九江路": (2, 2), "汉口路": (2, 2),
    "滇池路": (2, 1), "外白渡桥": (4, 2), "南苏州路": (2, 2), "北苏州路": (2, 1),
    "大名路": (4, 2), "黄浦路": (2, 1), "圆明园路": (2, 1), "虎丘路": (2, 1), "香港路": (2, 1),
    "金陵东路": (4, 2), "人民路": (4, 3), "新开河路": (4, 2), "河南中路": (4, 3),
    "江西中路": (2, 2), "延安高架路": (6, 3),
}
PEDESTRIAN_WIDTH = {"南京东路": 18.0, "圆明园路": 10.0, "香港路": 9.0, "沙市一路": 7.0,
                    "沙市二路": 7.0, "安平街": 6.0, "福民街": 6.0, "滨江大道": 8.0}
DUAL_ROADS = ["中山东一路", "中山东二路"]


def is_oneway(p):
    for r in p.get("access_restrictions") or []:
        w = r.get("when") or {}
        if r.get("access_type") == "denied" and w.get("heading") == "backward" and not w.get("mode") \
                and not w.get("vehicle"):
            return True
    return False


def split_levels(line, p):
    cuts = {0.0, 1.0}
    rules = []
    for r in p.get("level_rules") or []:
        b = r.get("between") or [0.0, 1.0]
        cuts.update(b)
        rules.append(("level", r.get("value", 0) or 0, b))
    for r in p.get("road_flags") or []:
        b = r.get("between") or [0.0, 1.0]
        cuts.update(b)
        for v in r.get("values") or []:
            rules.append(("flag", v, b))
    cuts = sorted(c for c in cuts if 0.0 <= c <= 1.0)
    out = []
    for a, b in zip(cuts[:-1], cuts[1:]):
        if b - a < 1e-6:
            continue
        m = 0.5 * (a + b)
        level, flags = 0, set()
        for kind, v, (s, e) in rules:
            if s <= m <= e:
                if kind == "level":
                    level = v
                else:
                    flags.add(v)
        sub = substring(line, a, b, normalized=True)
        if sub.length >= 0.3:
            out.append({"line": sub, "level": level, "flags": flags, "a": a, "b": b})
    # merge neighbours with identical level and flags
    merged = []
    for pc in out:
        if merged and merged[-1]["level"] == pc["level"] and merged[-1]["flags"] == pc["flags"]:
            m = merged[-1]
            m["line"] = linemerge([m["line"], pc["line"]]) if True else m["line"]
            if m["line"].geom_type != "LineString":
                m["line"] = max(lines(m["line"]), key=lambda l: l.length)
            m["b"] = pc["b"]
        else:
            merged.append(pc)
    return merged


def road_profile(name, cls, oneway, flags):
    two, one = CLASS_LANES.get(cls, (2, 1))
    if name in NAME_LANES:
        two, one = NAME_LANES[name]
    lanes = one if oneway else two
    lw = 3.5 if (cls in ("motorway", "trunk", "primary") or name == "中山东一路") else 3.25
    if cls in ("residential", "unclassified"):
        lw = 3.0
    marks = cls not in ("service", "living_street")
    if cls == "service":
        lw = 4.0 if oneway else 5.0
        lanes = 1
    if "is_link" in flags:
        lanes = max(1, min(lanes, 1 if oneway else 2))
    width = lanes * lw + 0.5
    return {"lanes": lanes, "lw": lw, "width": width, "marks": marks}


class Road:
    def __init__(self, line, name, cls, oneway, level, flags, prof, seg_id, a, b):
        self.line, self.name, self.cls, self.oneway = line, name, cls, oneway
        self.level, self.flags, self.prof, self.seg_id = level, flags, prof, seg_id
        self.a, self.b = a, b
        self.dual = False

    @property
    def width(self):
        return self.prof["width"]


def build_dual(name, roads, median_cfg):
    """Replace a road's two one-way carriageways by a regular dual carriageway.

    Returns (new_roads, median_axis_lines). The midline follows the average of
    the OSM carriageway centrelines; carriageways are re-derived as offsets so
    that lanes, kerbs and the median stay parallel.
    """
    mine = [r for r in roads if r.name == name and r.level == 0 and r.oneway]
    if len(mine) < 2:
        return roads, []
    # split by heading relative to the dominant road axis
    allc = unary_union([r.line for r in mine])
    minx, miny, maxx, maxy = allc.bounds
    axis = (maxx - minx, maxy - miny)
    n = math.hypot(*axis)
    axis = (axis[0] / n, axis[1] / n)

    def fwd(r):
        c0, c1 = r.line.coords[0], r.line.coords[-1]
        return (c1[0] - c0[0]) * axis[0] + (c1[1] - c0[1]) * axis[1] >= 0

    A = [r for r in mine if fwd(r)]
    B = [r for r in mine if not fwd(r)]
    if not A or not B:
        return roads, []
    la = linemerge(unary_union([r.line for r in A]))
    lb = unary_union([r.line for r in B])
    prof = mine[0].prof
    W = prof["width"]
    step = 2.0
    runs, cur = [], []
    for base in lines(la):
        nstep = int(base.length // step)
        for i in range(nstep + 1):
            pa = base.interpolate(min(i * step, base.length))
            pb = nearest_points(pa, lb)[1]
            d = pa.distance(pb)
            if median_cfg["dmin"] <= d <= median_cfg["dmax"]:
                cur.append(((pa.x + pb.x) / 2, (pa.y + pb.y) / 2, d))
            elif cur:
                runs.append(cur)
                cur = []
        if cur:
            runs.append(cur)
            cur = []
    new_roads = [r for r in roads if not (r.name == name and r.level == 0 and r.oneway)]
    medians = []
    kept_original = []
    corridor_polys = []
    for run in runs:
        if len(run) < 15:
            continue
        xy = np.array([(x, y) for x, y, _ in run])
        dd = np.array([d for _, _, d in run])
        k = 7
        ker = np.ones(k) / k
        xs = np.convolve(np.pad(xy[:, 0], k // 2, mode="edge"), ker, mode="valid")
        ys = np.convolve(np.pad(xy[:, 1], k // 2, mode="edge"), ker, mode="valid")
        mid = LineString(np.column_stack([xs, ys])).simplify(0.15)
        if mid.length < 30:
            continue
        sep = float(np.median(dd))
        m = float(np.clip(sep - W, median_cfg["min"], median_cfg["max"]))
        off = m / 2 + W / 2
        # carriageway travelling along the midline direction keeps right
        right = offset_line(mid, -off)
        left = offset_line(mid, off)
        if right is None or left is None:
            continue
        left = LineString(list(left.coords)[::-1])
        for ln in (right, left):
            new_roads.append(Road(ln, name, mine[0].cls, True, 0, set(), prof, "dual", 0, 1))
            new_roads[-1].dual = True
        medians.append({"axis": mid, "width": m})
        corridor_polys.append(mid.buffer(off + W / 2 + 1.0, cap_style="flat"))
    corridor = unary_union(corridor_polys) if corridor_polys else Polygon()
    # keep the parts of the original carriageways outside the regularised corridor
    for r in mine:
        rest = r.line.difference(corridor)
        for ln in lines(rest):
            if ln.length > 3:
                kept_original.append(Road(ln, r.name, r.cls, True, 0, r.flags, r.prof, r.seg_id, r.a, r.b))
    return new_roads + kept_original, medians


# --------------------------------------------------------------------------
# main processing
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "scene.json"))
    args = ap.parse_args()

    scene = {"origin": {"lon": LON0, "lat": LAT0, "crs": "tmerc"},
             "levels": {"water": Z_WATER, "pave": Z_PAVE, "green": Z_GREEN, "deck": Z_DECK,
                        "parapet": PARAPET},
             "extent": list(SCENE.bounds), "core": list(CORE.bounds)}

    # ---------------- water & land ----------------
    water_parts = []
    for g, p in load("water"):
        if p.get("subtype") in ("river", "water", "canal") and g.geom_type in ("Polygon", "MultiPolygon"):
            gi = g.intersection(SCENE)
            if not gi.is_empty and gi.area > 500:
                water_parts.append(gi)
    water = clean(unary_union(water_parts), 50)
    land = clean(SCENE.difference(water), 20)
    huangpu = max(polys(water), key=lambda p: p.area)
    print("water area %.0f m2, land %.0f m2" % (water.area, land.area))

    # ---------------- buildings (needed early for clipping) ----------------
    bld_raw = []
    for g, p in load("building"):
        g = clean(g, 2.0)
        if g.is_empty or not g.intersects(SCENE):
            continue
        bld_raw.append((g, p))
    parts_by_bid = defaultdict(list)
    for g, p in load("building_part"):
        g = clean(g, 1.0)
        if not g.is_empty and g.intersects(SCENE):
            parts_by_bid[p.get("building_id")].append((g, p))
    footprints = unary_union([g for g, _ in bld_raw])

    # ---------------- roads ----------------
    roads, ped_ways, crosswalk_lines, steps_lines = [], [], [], []
    for g, p in load("segment"):
        if p.get("subtype") != "road":
            continue
        cls = p.get("class")
        name = (p.get("names") or {}).get("primary") or ""
        for ln in lines(g):
            if not ln.intersects(ROADS.buffer(50)):
                continue
            if cls == "footway" and p.get("subclass") == "crosswalk":
                crosswalk_lines.append(ln)
                continue
            if cls == "steps":
                steps_lines.append(ln)
                continue
            if cls == "pedestrian":
                ped_ways.append((ln, name))
                continue
            if cls not in DRIVE:
                continue
            if p.get("subclass") in ("driveway", "parking_aisle"):
                continue
            ow = is_oneway(p)
            for pc in split_levels(ln, p):
                prof = road_profile(name, cls, ow, pc["flags"])
                roads.append(Road(pc["line"], name, cls, ow, pc["level"], pc["flags"], prof,
                                  p.get("id"), pc["a"], pc["b"]))
    print("road pieces:", len(roads))

    roads, medians = build_dual("中山东一路", roads, {"dmin": 4.0, "dmax": 30.0, "min": 1.5, "max": 5.0})
    roads, med2 = build_dual("中山东二路", roads, {"dmin": 4.0, "dmax": 30.0, "min": 1.5, "max": 5.0})
    medians += med2
    print("medians:", len(medians), [round(m["axis"].length) for m in medians])

    surface = [r for r in roads if r.level == 0 and "is_tunnel" not in r.flags]
    elevated = [r for r in roads if r.level > 0]
    tunnels = [r for r in roads if r.level < 0 or "is_tunnel" in r.flags]

    # ---------- bridges over water vs viaducts ----------
    bridges, viaducts = [], []
    for r in elevated:
        over_water = r.line.intersection(water).length > 0.25 * r.line.length
        (bridges if over_water else viaducts).append(r)

    # ---------- ramps: level transitions inside a segment ----------
    by_seg = defaultdict(list)
    for r in roads:
        if r.seg_id not in (None, "dual"):
            by_seg[r.seg_id].append(r)
    ramps = []   # (road, z_start, z_end)
    for sid, rs in by_seg.items():
        rs.sort(key=lambda r: r.a)
        for i, r in enumerate(rs):
            if r.level != 0 or "is_tunnel" in r.flags:
                continue
            prev_l = rs[i - 1].level if i > 0 else 0
            next_l = rs[i + 1].level if i + 1 < len(rs) else 0
            if prev_l != 0 or next_l != 0:
                ramps.append((r, prev_l, next_l))

    # ---------- carriageway polygons ----------
    def cpoly(r, extra=0.0):
        return r.line.buffer(r.width / 2 + extra, cap_style="flat", join_style="round", quad_segs=6)

    trench_items = []
    trench_area = []
    ramp_area_up = []
    ramp_set = set()
    for r, l0, l1 in ramps:
        L = r.line.length
        z0 = 0.0
        prof_pts = []
        n = max(2, int(L // 3) + 1)
        for i in range(n + 1):
            s = L * i / n
            z = 0.0
            if l0 < 0:
                T = min(L, 75.0)
                if s < T:
                    z = -6.0 * (1 - s / T)
            if l1 < 0:
                T = min(L, 75.0)
                if s > L - T:
                    z = -6.0 * (1 - (L - s) / T)
            if l0 > 0:
                T = min(L, 110.0)
                if s < T:
                    z = max(z, LEVEL_H * l0 * (1 - s / T))
            if l1 > 0:
                T = min(L, 110.0)
                if s > L - T:
                    z = max(z, LEVEL_H * l1 * (1 - (L - s) / T))
            prof_pts.append((s, z))
        if l0 < 0 or l1 < 0:
            # the part of the ramp that is below ground becomes a trench
            below = [(s, z) for s, z in prof_pts if z < -0.4]
            if below:
                s0, s1 = below[0][0], below[-1][0]
                sub = substring(r.line, max(0, s0 - 3), min(L, s1 + 3))
                trench_area.append(sub.buffer(r.width / 2 + 0.6, cap_style="flat"))
                trench_items.append({"road": r, "profile": prof_pts})
                ramp_set.add(id(r))
        if l0 > 0 or l1 > 0:
            trench_items.append({"road": r, "profile": prof_pts, "up": True})
            above = [(s, z) for s, z in prof_pts if z > 0.4]
            if above:
                s0, s1 = above[0][0], above[-1][0]
                ramp_area_up.append(substring(r.line, max(0, s0), min(L, s1)).buffer(r.width / 2, cap_style="flat"))
                ramp_set.add(id(r))
    trench_area = clean(unary_union(trench_area)) if trench_area else Polygon()

    road_raw = unary_union([cpoly(r) for r in surface if r.line.intersects(ROADS)])
    road_area = road_raw.buffer(2.5, join_style="round").buffer(-2.5, join_style="round")
    road_area = clean(road_area.intersection(land).difference(trench_area), 2.0)

    # islands enclosed by road (traffic islands / green medians)
    islands = []
    for p in polys(road_area):
        for hole in p.interiors:
            hp = Polygon(hole)
            if 15 < hp.area < 6000 and hp.intersection(footprints).area < 0.05 * hp.area:
                islands.append(hp)
    islands = clean(unary_union(islands)) if islands else Polygon()

    ped_area = unary_union([ln.buffer(PEDESTRIAN_WIDTH.get(nm, 6.0) / 2, cap_style="flat")
                            for ln, nm in ped_ways if nm in PEDESTRIAN_WIDTH]) if ped_ways else Polygon()
    ped_area = clean(ped_area.intersection(land).difference(road_area).difference(footprints), 2.0)

    # ---------------- junctions ----------------
    ends = []
    for i, r in enumerate(surface):
        for c in (r.line.coords[0], r.line.coords[-1]):
            ends.append((c[0], c[1], i))
    # cluster endpoints
    clusters = []
    for x, y, i in ends:
        for cl in clusters:
            if (cl["x"] - x) ** 2 + (cl["y"] - y) ** 2 < 2.5 ** 2:
                cl["ids"].add(i)
                break
        else:
            clusters.append({"x": x, "y": y, "ids": {i}})
    junction_pts = []
    for cl in clusters:
        names = {surface[i].name for i in cl["ids"]}
        if len(cl["ids"]) >= 3 or (len(cl["ids"]) == 2 and len(names) == 2):
            w = max(surface[i].width for i in cl["ids"])
            junction_pts.append((cl["x"], cl["y"], w))
    # crossings of different roads without shared nodes (e.g. regularised dual carriageways)
    sidx = shapely.STRtree([r.line for r in surface])
    for i, r in enumerate(surface):
        for j in sidx.query(r.line):
            if j <= i or surface[j].name == r.name:
                continue
            inter = r.line.intersection(surface[j].line)
            for pt in ([inter] if inter.geom_type == "Point" else
                       [g for g in getattr(inter, "geoms", []) if g.geom_type == "Point"]):
                junction_pts.append((pt.x, pt.y, max(r.width, surface[j].width)))
    jz = [Point(x, y).buffer(w / 2 + 3.0) for x, y, w in junction_pts]
    junction_zone = unary_union(jz) if jz else Polygon()
    junction_zone = junction_zone.intersection(road_area.buffer(0.5))
    print("junctions:", len(junction_pts))

    # ---------------- signals ----------------
    signal_pts, crossing_pts, bus_stops, infra = [], [], [], []
    for g, p in load("infrastructure"):
        cls = p.get("class")
        if g.geom_type == "Point":
            if cls == "traffic_signals":
                signal_pts.append(g)
            elif cls == "crossing":
                crossing_pts.append(g)
            elif cls == "bus_stop":
                bus_stops.append((g, (p.get("names") or {}).get("primary")))
        infra.append((g, p))

    # ---------------- crosswalks ----------------
    median_poly = Polygon()
    med_polys = []
    for m in medians:
        med_polys.append(m["axis"].buffer(m["width"] / 2, cap_style="flat"))
    median_poly = clean(unary_union(med_polys)) if med_polys else Polygon()

    zebra_axes = []   # (LineString across road, width)
    for ln in crosswalk_lines:
        inter = ln.intersection(road_area.buffer(0.3))
        for piece in lines(inter):
            if piece.length > 3.0:
                zebra_axes.append(piece)
    for pt in crossing_pts:
        if not road_area.buffer(0.5).contains(pt):
            continue
        if any(ax.distance(pt) < 7.0 for ax in zebra_axes):
            continue
        near = [r for r in surface if r.line.distance(pt) < 6.0]
        if not near:
            continue
        r = min(near, key=lambda r: r.line.distance(pt))
        s = r.line.project(pt)
        h = heading_at(r.line, s)
        L = r.width + 6
        a = Point(pt.x - L / 2 * math.sin(h), pt.y + L / 2 * math.cos(h))
        b = Point(pt.x + L / 2 * math.sin(h), pt.y - L / 2 * math.cos(h))
        inter = LineString([a, b]).intersection(road_area.buffer(0.3))
        for piece in lines(inter):
            if piece.length > 3.0 and piece.distance(pt) < 1.0:
                zebra_axes.append(piece)

    ZW = 5.0  # zebra width along the road
    big_crossing = {"中山东一路": 7.0}
    zebras, zebra_zone_parts, stop_lines, arrows = [], [], [], []
    bar_w, gap = 0.45, 0.60
    for ax in zebra_axes:
        # width: wider on the Bund
        near_roads = [r for r in surface if r.line.intersects(ax.buffer(1))]
        zw = max([big_crossing.get(r.name, ZW) for r in near_roads] + [ZW])
        mid = ax.interpolate(0.5, normalized=True)
        h = math.atan2(ax.coords[-1][1] - ax.coords[0][1], ax.coords[-1][0] - ax.coords[0][0])
        ux, uy = math.cos(h), math.sin(h)          # across the road
        vx, vy = -uy, ux                           # along the road
        zone = ax.buffer(zw / 2, cap_style="flat")
        zebra_zone_parts.append(zone)
        L = ax.length
        nbar = int((L + gap) // (bar_w + gap))
        start = (L - (nbar * (bar_w + gap) - gap)) / 2
        bars = []
        for k in range(nbar):
            s0 = start + k * (bar_w + gap)
            p0 = ax.interpolate(s0)
            p1 = ax.interpolate(s0 + bar_w)
            q = Polygon([(p0.x - vx * zw / 2, p0.y - vy * zw / 2), (p1.x - vx * zw / 2, p1.y - vy * zw / 2),
                         (p1.x + vx * zw / 2, p1.y + vy * zw / 2), (p0.x + vx * zw / 2, p0.y + vy * zw / 2)])
            q = q.intersection(road_area).difference(median_poly)
            for pp in polys(q):
                if pp.area > 0.2:
                    bars.append(pp)
        zebras += bars
        # stop lines + arrows for each carriageway crossing this zebra
        for r in near_roads:
            if not r.prof["marks"] or r.prof["lanes"] < 1:
                continue
            ip = r.line.intersection(ax)
            if ip.is_empty:
                ip = nearest_points(r.line, mid)[0]
            if ip.geom_type != "Point":
                ip = ip.centroid
            s = r.line.project(ip)
            dirs = [1] if r.oneway else [1, -1]
            for dsign in dirs:
                s_stop = s - dsign * (zw / 2 + 1.2)
                if not (0 <= s_stop <= r.line.length):
                    continue
                c = r.line.interpolate(s_stop)
                hh = heading_at(r.line, s_stop) + (0 if dsign > 0 else math.pi)
                nx, ny = -math.sin(hh), math.cos(hh)   # left normal of travel direction
                W = r.prof["lanes"] * r.prof["lw"]
                if r.oneway:
                    d0, d1 = -W / 2, W / 2
                else:
                    d0, d1 = -W / 2, -0.15
                p0 = (c.x + nx * d0, c.y + ny * d0)
                p1 = (c.x + nx * d1, c.y + ny * d1)
                tx, ty = math.cos(hh) * 0.2, math.sin(hh) * 0.2
                sl = Polygon([(p0[0] - tx, p0[1] - ty), (p1[0] - tx, p1[1] - ty),
                              (p1[0] + tx, p1[1] + ty), (p0[0] + tx, p0[1] + ty)])
                sl = sl.intersection(road_area)
                if not sl.is_empty and sl.area > 0.3:
                    stop_lines.append(sl)
                # guide arrows 7 m and 30 m before the stop line
                lanes_here = r.prof["lanes"] if r.oneway else max(1, r.prof["lanes"] // 2)
                for back in (7.0, 30.0):
                    s_ar = s_stop - dsign * back
                    if not (0 <= s_ar <= r.line.length):
                        continue
                    ca = r.line.interpolate(s_ar)
                    ha = heading_at(r.line, s_ar) + (0 if dsign > 0 else math.pi)
                    nxa, nya = -math.sin(ha), math.cos(ha)
                    for k in range(lanes_here):
                        if r.oneway:
                            d = -W / 2 + (k + 0.5) * r.prof["lw"]
                        else:
                            d = -(k + 0.5) * r.prof["lw"]
                        # k counts from the right kerb for two-way, from the left for one-way
                        if r.oneway:
                            pos_from_left = k
                        else:
                            pos_from_left = lanes_here - 1 - k
                        if lanes_here == 1:
                            typ = "straight"
                        elif pos_from_left == 0:
                            typ = "left" if lanes_here >= 3 else "straight_left"
                        elif pos_from_left == lanes_here - 1:
                            typ = "straight_right"
                        else:
                            typ = "straight"
                        px, py = ca.x + nxa * d, ca.y + nya * d
                        if road_area.contains(Point(px, py)) and not junction_zone.contains(Point(px, py)):
                            arrows.append({"pos": [R(px), R(py)], "h": round(ha, 4), "type": typ})
    zebra_zone = unary_union(zebra_zone_parts) if zebra_zone_parts else Polygon()
    print("zebras bars:", len(zebras), "stop lines:", len(stop_lines), "arrows:", len(arrows))

    # ---------------- lane markings ----------------
    no_mark = unary_union([junction_zone, zebra_zone.buffer(0.8), trench_area]).buffer(0)
    approach = unary_union([junction_zone.buffer(30.0), zebra_zone.buffer(30.0)]).difference(no_mark)
    marks = []

    def add_mark(ln, w, color, dash=None):
        if ln is None or ln.is_empty:
            return
        ln = ln.intersection(road_area.buffer(-0.05))
        for piece in lines(ln):
            piece = piece.difference(no_mark)
            for pc in lines(piece):
                if pc.length < 0.4:
                    continue
                if dash:
                    solid = pc.intersection(approach)
                    dashed = pc.difference(approach)
                    for s in lines(solid):
                        if s.length > 0.4:
                            marks.append({"pts": exp_line(s.simplify(0.05)), "w": w, "c": color})
                    for d in lines(dashed):
                        for dd in dashes(d, dash[0], dash[1]):
                            marks.append({"pts": exp_line(dd.simplify(0.05)), "w": w, "c": color})
                else:
                    marks.append({"pts": exp_line(pc.simplify(0.05)), "w": w, "c": color})

    for r in surface + bridges:
        if not r.prof["marks"] or not r.line.intersects(ROADS):
            continue
        if id(r) in ramp_set:
            continue
        n, lw = r.prof["lanes"], r.prof["lw"]
        W = n * lw
        dash = (2.0, 4.0)
        major = r.cls in ("primary", "secondary", "trunk", "motorway")
        if r.oneway:
            for k in range(1, n):
                add_mark(offset_line(r.line, -W / 2 + k * lw), 0.15, "w", dash)
            if r.dual:
                add_mark(offset_line(r.line, W / 2 - 0.1), 0.15, "y")      # median side: yellow
                add_mark(offset_line(r.line, -W / 2 + 0.1), 0.15, "w")     # kerb side
            elif major:
                add_mark(offset_line(r.line, W / 2 - 0.1), 0.15, "w")
                add_mark(offset_line(r.line, -W / 2 + 0.1), 0.15, "w")
        else:
            half = n // 2
            if n >= 4:
                add_mark(offset_line(r.line, 0.15), 0.15, "y")
                add_mark(offset_line(r.line, -0.15), 0.15, "y")
            elif n >= 2:
                add_mark(r.line, 0.15, "y", None if major else (4.0, 4.0))
            for k in range(1, half):
                add_mark(offset_line(r.line, k * lw), 0.15, "w", dash)
                add_mark(offset_line(r.line, -k * lw), 0.15, "w", dash)
            if major and n >= 2:
                add_mark(offset_line(r.line, W / 2 - 0.1), 0.15, "w")
                add_mark(offset_line(r.line, -W / 2 + 0.1), 0.15, "w")
    print("marking polylines:", len(marks))

    # ---------------- medians (raised, with planters) ----------------
    med_out = []
    for m in medians:
        poly = m["axis"].buffer(m["width"] / 2, cap_style="flat")
        poly = poly.difference(junction_zone.buffer(1.0)).difference(zebra_zone.buffer(0.6))
        poly = poly.intersection(road_area)
        for pp in polys(poly):
            if pp.area > 4 and pp.length > 10:
                pp = pp.buffer(-0.01).buffer(0.01)
                med_out += exp_geom(pp, 1.0, 0.03)
    median_area = unary_union([Polygon(m["ext"]) for m in med_out]) if med_out else Polygon()

    # ---------------- green areas ----------------
    green_parts, wood_parts, tree_rows = [], [], []
    for g, p in load("land_use"):
        if g.area > 2e6:
            continue
        if p.get("class") in ("grass", "garden", "village_green", "flowerbed"):
            green_parts.append(g)
    for g, p in load("land"):
        if g.area > 2e6:
            continue
        cls = p.get("class")
        if cls in ("forest", "wood", "grass", "scrub", "shrubbery"):
            green_parts.append(g)
            if cls in ("forest", "wood"):
                wood_parts.append(g)
        elif cls == "tree_row":
            tree_rows += lines(g)
    green = clean(unary_union(green_parts)).intersection(land)
    green = clean(green.difference(road_area.buffer(0.3)).difference(footprints.buffer(0.3))
                  .difference(ped_area).difference(trench_area), 3.0)
    green = clean(unary_union([green, islands.buffer(-0.4)]), 3.0)
    wood = clean(unary_union(wood_parts)).intersection(green)

    # ---------------- Bund promenade (flood wall deck) ----------------
    bank = lines(huangpu.exterior.intersection(PUXI_BUND))
    bank = [b for b in bank if b.length > 40]
    deck = Polygon()
    if bank:
        bank_u = unary_union(bank)
        bank_line = linemerge(bank_u) if bank_u.geom_type == "MultiLineString" else bank_u
        deck = unary_union([b.buffer(DECK_WIDTH, cap_style="flat") for b in lines(bank_line)])
        deck = deck.intersection(land).difference(road_area.buffer(4.0)).difference(footprints.buffer(0.5))
        deck = clean(deck.buffer(-0.5).buffer(0.5), 20.0)
        # keep only pieces touching the river
        deck = clean(unary_union([p for p in polys(deck) if p.distance(huangpu) < 1.0]), 20.0)
    green = clean(green.difference(deck), 3.0)
    wood = clean(wood.difference(deck), 3.0)
    print("deck area %.0f, green %.0f, wood %.0f" % (deck.area, green.area, wood.area))

    # ---------------- pavement ----------------
    pave = land.difference(road_area).difference(green).difference(deck).difference(trench_area)
    pave = pave.difference(median_area)
    pave = clean(pave, 0.5)

    def zat(x, y):
        pt = Point(x, y)
        if pbuf('deck', deck, 0).contains(pt):
            return Z_DECK
        if pbuf('green', green, 0).contains(pt):
            return Z_GREEN
        if pbuf('road', road_area, 0).contains(pt):
            return 0.0
        return Z_PAVE

    # ---------------- water edges: flood walls & parapets ----------------
    edges = []
    for p in polys(land):
        for ring in [p.exterior] + list(p.interiors):
            seg = LineString(ring.coords).intersection(water.buffer(0.5))
            for ln in lines(linemerge(seg) if seg.geom_type == "MultiLineString" else seg):
                if ln.length < 2:
                    continue
                # split into deck / non-deck parts
                on_deck = ln.intersection(deck.buffer(1.0))
                off_deck = ln.difference(deck.buffer(1.0))
                for a in lines(on_deck):
                    if a.length > 1:
                        edges.append({"pts": exp_line(a.simplify(0.2)), "top": Z_DECK, "parapet": PARAPET,
                                      "style": "bund"})
                for a in lines(off_deck):
                    if a.length > 1:
                        edges.append({"pts": exp_line(a.simplify(0.2)), "top": Z_PAVE, "parapet": 1.0,
                                      "style": "plain"})
    # deck inland edge -> retaining wall
    deck_walls = []
    for p in polys(deck):
        ln = LineString(p.exterior.coords).difference(water.buffer(1.0))
        for a in lines(ln):
            if a.length > 1:
                deck_walls.append(exp_line(a.simplify(0.1)))

    # stairs from the plaza up to the deck
    stairs = []
    deck_edge = unary_union([LineString(p.exterior.coords) for p in polys(deck)]).difference(water.buffer(1.5))
    cand = []
    for st in steps_lines:
        if st.distance(deck) < 3 and st.length > 1:
            ip = st.intersection(deck_edge.buffer(2.0))
            if not ip.is_empty:
                cand.append(ip.centroid)
    for ln in lines(deck_edge):
        n = int(ln.length // 55)
        for k in range(n):
            pt = ln.interpolate((k + 0.5) * ln.length / max(n, 1))
            if all(pt.distance(c) > 35 for c in cand):
                cand.append(pt)
    for c in cand:
        q = nearest_points(deck_edge, c)[0]
        # direction pointing into the deck (uphill)
        inside = None
        for ang in range(0, 360, 10):
            a = math.radians(ang)
            t = Point(q.x + 1.5 * math.cos(a), q.y + 1.5 * math.sin(a))
            if deck.contains(t):
                inside = a if inside is None else inside
        if inside is None:
            continue
        # refine: average of directions that hit the deck
        hits = [math.radians(a) for a in range(0, 360, 5)
                if deck.contains(Point(q.x + 1.5 * math.cos(math.radians(a)), q.y + 1.5 * math.sin(math.radians(a))))]
        if not hits:
            continue
        hx = sum(math.cos(a) for a in hits)
        hy = sum(math.sin(a) for a in hits)
        ang = math.atan2(hy, hx)
        foot = Point(q.x - 4.5 * math.cos(ang), q.y - 4.5 * math.sin(ang))
        if road_area.buffer(1.0).contains(foot) or footprints.contains(foot):
            continue
        stairs.append({"pos": [R(q.x), R(q.y)], "h": round(ang, 4), "width": 6.0, "rise": Z_DECK - Z_PAVE})
    print("stairs:", len(stairs))

    # ---------------- trees ----------------
    trees = []
    occupied = []

    def tree_ok(x, y, clearance=2.0):
        pt = Point(x, y)
        if not pbuf('land', land, 0).contains(pt) or pbuf('road', road_area, 0.6).contains(pt):
            return False
        if pbuf('fp', footprints, clearance).contains(pt) or pbuf('deck', deck, -0.5).contains(pt):
            return False
        if pbuf('trench', trench_area, 1.0).contains(pt) or pbuf('ped', ped_area, -1.0).contains(pt):
            return False
        return True

    for tr in tree_rows:
        n = max(1, int(tr.length // 7.0))
        for k in range(n + 1):
            pt = tr.interpolate(k * tr.length / max(n, 1))
            if tree_ok(pt.x, pt.y, 1.5):
                trees.append([R(pt.x), R(pt.y), R(zat(pt.x, pt.y)), "plane", round(rng.uniform(0.85, 1.15), 2),
                              round(rng.uniform(0, 6.283), 2)])
    for x, y in poisson(wood, 8.0, rng):
        if tree_ok(x, y, 3.0):
            typ = "camphor" if rng.random() < 0.7 else "plane"
            trees.append([R(x), R(y), R(zat(x, y)), typ, round(rng.uniform(0.8, 1.25), 2),
                          round(rng.uniform(0, 6.283), 2)])
    sparse = green.difference(wood.buffer(4.0))
    for x, y in poisson(sparse, 13.0, rng):
        if rng.random() < 0.45 and tree_ok(x, y, 3.0):
            typ = rng.choice(["camphor", "plane", "ginkgo"])
            trees.append([R(x), R(y), R(zat(x, y)), typ, round(rng.uniform(0.7, 1.1), 2),
                          round(rng.uniform(0, 6.283), 2)])
    # street trees (plane trees) on side streets, not on the Bund frontage itself
    for r in surface:
        if r.name in ("中山东一路", "中山东二路", "延安东路", "外白渡桥") or r.cls in ("service",):
            continue
        if not r.line.within(CORE.buffer(0)) or r.line.length < 20:
            continue
        L = r.line.length
        n = int(L // 8.5)
        for side in (-1, 1):
            for k in range(1, n):
                s = k * L / n
                pt, h = offset_pt(r.line, s, side * (r.width / 2 + 1.1))
                if pbuf('jz', junction_zone, 6.0).contains(pt) or pbuf('zz', zebra_zone, 3.0).contains(pt):
                    continue
                if pbuf('green', green, 0).contains(pt) or not pbuf('pave', pave, 0).contains(pt):
                    continue
                if tree_ok(pt.x, pt.y, 2.2) and all((pt.x - t[0]) ** 2 + (pt.y - t[1]) ** 2 > 36 for t in trees[-40:]):
                    trees.append([R(pt.x), R(pt.y), R(Z_PAVE), "plane", round(rng.uniform(0.75, 1.0), 2),
                                  round(rng.uniform(0, 6.283), 2)])
    print("trees:", len(trees))

    # ---------------- street furniture ----------------
    lamps = []
    for r in surface:
        if not r.line.intersects(CORE) or r.cls == "service" or r.line.length < 15:
            continue
        spacing = 32.0 if r.name == "中山东一路" else 30.0
        L = r.line.length
        n = max(1, int(L // spacing))
        sides = (-1,) if r.dual else (-1, 1)
        for k in range(n):
            s = (k + 0.5) * L / n
            for side in sides:
                if not r.dual and (k % 2) != (0 if side < 0 else 1):
                    continue
                pt, h = offset_pt(r.line, s, side * (r.width / 2 + 0.7))
                if not CORE.contains(pt) or not pbuf('pave', pave, -0.2).contains(pt):
                    continue
                if pbuf('jz', junction_zone, 3.0).contains(pt) or pbuf('fp', footprints, 0.8).contains(pt):
                    continue
                face = h + (math.pi / 2 if side < 0 else -math.pi / 2)
                lamps.append({"pos": [R(pt.x), R(pt.y)], "z": R(Z_PAVE), "h": round(face, 3),
                              "type": "bund" if r.name == "中山东一路" else "street"})
    for e in edges:
        if e["style"] != "bund":
            continue
        ln = LineString(e["pts"])
        n = int(ln.length // 24)
        for k in range(n):
            s = (k + 0.5) * ln.length / max(n, 1)
            for d in (1.4, -1.4):
                pt, h = offset_pt(ln, s, d)
                if pbuf('deck', deck, -0.3).contains(pt):
                    lamps.append({"pos": [R(pt.x), R(pt.y)], "z": R(Z_DECK), "h": round(h, 3), "type": "promenade"})
                    break
    print("lamps:", len(lamps))

    # stone bollards along the riverside kerb of 中山东一路 and manhole covers in the lanes
    bollards, manholes = [], []
    for r in surface:
        if not r.line.intersects(CORE):
            continue
        L = r.line.length
        if r.name == "中山东一路" and r.dual:
            n = int(L // 2.4)
            for k in range(n):
                s_ = k * L / max(n, 1)
                pt, h = offset_pt(r.line, s_, -(r.width / 2 + 0.45))
                if math.sin(h) < 0.2:
                    continue          # only the northbound (river-side) carriageway
                if not CORE.contains(pt) or pbuf('jz', junction_zone, 3.0).contains(pt) or \
                        pbuf('zz', zebra_zone, 1.5).contains(pt) or not pbuf('pave', pave, -0.1).contains(pt):
                    continue
                if pbuf('fp', footprints, 3.0).contains(pt):
                    continue          # building side: no bollards in front of the doors
                bollards.append([R(pt.x), R(pt.y)])
        if r.prof["marks"]:
            k = 0
            s_ = rng.uniform(5, 25)
            while s_ < L:
                lane = rng.randrange(max(1, r.prof["lanes"]))
                d = -r.prof["lanes"] * r.prof["lw"] / 2 + (lane + 0.5) * r.prof["lw"] + rng.uniform(-0.6, 0.6)
                pt, h = offset_pt(r.line, s_, d)
                if CORE.contains(pt) and pbuf('road', road_area, -0.3).contains(pt):
                    manholes.append([R(pt.x), R(pt.y), round(h, 2), rng.choice([0, 0, 1])])
                s_ += rng.uniform(18, 45)

    # signal poles: one per signal node and direction of travel
    signals = []
    for sp in signal_pts:
        if not CORE.contains(sp):
            continue
        near = [r for r in surface if r.line.distance(sp) < 8.0 and r.prof["marks"]]
        if not near:
            continue
        r = min(near, key=lambda r: r.line.distance(sp))
        s = r.line.project(sp)
        for dsign in ([1] if r.oneway else [1, -1]):
            s2 = s - dsign * 3.0
            if not (0 <= s2 <= r.line.length):
                continue
            c = r.line.interpolate(s2)
            hh = heading_at(r.line, s2) + (0 if dsign > 0 else math.pi)
            d = r.width / 2 + 0.9
            px, py = c.x + math.sin(hh) * d, c.y - math.cos(hh) * d   # right-hand kerb
            if any((px - q["pos"][0]) ** 2 + (py - q["pos"][1]) ** 2 < 25 for q in signals):
                continue
            arm = (r.width if r.oneway else r.width / 2) + 0.5
            signals.append({"pos": [R(px), R(py)], "z": R(zat(px, py)), "h": round(hh, 4),
                            "arm": R(min(arm, 11.0))})
    print("signal poles:", len(signals))

    shelters = []
    for g, nm in bus_stops:
        if not CORE.contains(g):
            continue
        near = [r for r in surface if r.line.distance(g) < 25 and r.cls != "service"]
        if not near:
            continue
        r = min(near, key=lambda r: r.line.distance(g))
        s = r.line.project(g)
        c = r.line.interpolate(s)
        h = heading_at(r.line, s)
        side = 1 if ((g.x - c.x) * -math.sin(h) + (g.y - c.y) * math.cos(h)) > 0 else -1
        pt, _ = offset_pt(r.line, s, side * (r.width / 2 + 1.6))
        if pbuf('fp', footprints, 1.0).contains(pt) or pbuf('road', road_area, 0).contains(pt):
            continue
        face = h + (math.pi / 2 if side > 0 else -math.pi / 2)
        shelters.append({"pos": [R(pt.x), R(pt.y)], "z": R(zat(pt.x, pt.y)), "h": round(face, 3), "name": nm})

    # ---------------- buildings ----------------
    with open(os.path.join(ROOT, "data", "landmarks.json"), encoding="utf-8") as fh:
        lm_spec = json.load(fh)["landmarks"]
    named = defaultdict(list)
    for idx, (g, p) in enumerate(bld_raw):
        nm = (p.get("names") or {}).get("primary")
        if nm:
            named[nm].append(idx)
    lm_of = {}
    lm_geom = {}
    for spec in lm_spec:
        m = spec["match"]
        cands = []
        if "name" in m:
            cands = named.get(m["name"], [])
            if "box" in m:
                bx = box(*m["box"])
                cands = [i for i in cands if bld_raw[i][0].centroid.within(bx)]
        elif "point" in m:
            pt = Point(*m["point"])
            if "all_within" in m:
                cands = [i for i, (g, _) in enumerate(bld_raw) if g.distance(pt) < m["all_within"]]
            else:
                cands = sorted(range(len(bld_raw)), key=lambda i: bld_raw[i][0].distance(pt))[:1]
                cands = [i for i in cands if bld_raw[i][0].distance(pt) < 15]
        if not cands:
            print("  !! landmark not matched:", spec["key"])
            continue
        main = max(cands, key=lambda i: bld_raw[i][0].area)
        group = set(cands) if "all_within" in m else {main}
        if spec.get("merge_radius"):
            c = bld_raw[main][0]
            for i, (g, p) in enumerate(bld_raw):
                if g.area < 120 and g.distance(c) < 1.0 and g.centroid.distance(c.centroid) < spec["merge_radius"]:
                    group.add(i)
        for i in group:
            lm_of[i] = spec["key"]
        lm_geom[spec["key"]] = clean(unary_union([bld_raw[i][0] for i in group]).buffer(0.05).buffer(-0.05))

    # party walls: edges that touch a neighbouring footprint get no windows
    fp_list = [g for g, _ in bld_raw]
    fp_tree = shapely.STRtree(fp_list)

    def party_flags(poly, self_geom):
        flags = []
        cs = list(orient(poly, 1.0).exterior.coords)
        for (x0, y0), (x1, y1) in zip(cs[:-1], cs[1:]):
            L = math.hypot(x1 - x0, y1 - y0)
            if L < 0.05:
                flags.append(0)
                continue
            nx, ny = (y1 - y0) / L, -(x1 - x0) / L      # outward for CCW rings
            hits = 0
            for t in (0.2, 0.5, 0.8):
                q = Point(x0 + (x1 - x0) * t + nx * 0.8, y0 + (y1 - y0) * t + ny * 0.8)
                for j in fp_tree.query(q):
                    og = fp_list[j]
                    if og is not self_geom and og.contains(q):
                        hits += 1
                        break
            flags.append(1 if hits >= 2 else 0)
        return flags

    with open(os.path.join(ROOT, "data", "building_overrides.json"), encoding="utf-8") as fh:
        overrides = json.load(fh)["overrides"]
    ov_of = {}
    for ov in overrides:
        m = ov["match"]
        if "name" in m:
            for i in named.get(m["name"], []):
                ov_of[i] = ov
        else:
            pt = Point(*m["point"])
            i = min(range(len(bld_raw)), key=lambda k: bld_raw[k][0].distance(pt))
            if bld_raw[i][0].distance(pt) < 12:
                ov_of[i] = ov

    kiosk_parts = [g for g, p in load("land_use") if p.get("class") in ("pedestrian", "plaza") and g.area < 2e6]
    plaza_kiosk = clean(unary_union(kiosk_parts)) if kiosk_parts else Polygon()

    buildings = []
    done_lm = set()
    for idx, (g, p) in enumerate(bld_raw):
        key = lm_of.get(idx)
        if key:
            if key in done_lm:
                continue
            done_lm.add(key)
            g = lm_geom[key]
        c = g.centroid
        name = (p.get("names") or {}).get("primary")
        floors = p.get("num_floors")
        height = p.get("height")
        min_h = p.get("min_height") or 0.0
        region = "core" if CORE.contains(c) else ("pudong" if c.x > 0 else "puxi_back")
        if c.x > 900 or c.y < -700:
            region = "far"
        # Pudong front row (riverside) gets full facades, the rest massing
        if region == "pudong" and c.x > 700:
            region = "far"
        lane_house = False
        if height is None:
            if floors:
                fh = 3.5 if (floors >= 10 or c.x > 150) else 4.0
                height = floors * fh + (1.0 if floors < 10 else 2.0)
            else:
                a = g.area
                floors = 2 if a < 120 else (3 if a < 300 else 5)
                height = floors * 3.8 + 0.8
        if floors is None:
            floors = max(1, int(round(height / (3.5 if height > 40 else 4.0))))
        if key:
            spec = next(sp for sp in lm_spec if sp["key"] == key)
            height = spec.get("height", height)
            floors = spec.get("floors", floors) or floors
        ov = ov_of.get(idx)
        if ov:
            floors = ov.get("floors", floors)
            if ov.get("height"):
                height = ov["height"]
            elif ov.get("floors"):
                height = ov["floors"] * (3.5 if ov["floors"] >= 10 else 4.0) + 1.0
        if floors <= 3 and g.area < 900 and region in ("core", "puxi_back") and not key:
            lane_house = True
        parts = []
        if p.get("has_parts") and p.get("id") in parts_by_bid:
            for pg, pp in parts_by_bid[p["id"]]:
                ph = pp.get("height")
                pf = pp.get("num_floors")
                if ph is None and pf:
                    ph = pf * 3.6 + 1.0
                if ph is None:
                    ph = height
                parts.append({"poly": exp_geom(pg, 0.5, 0.05),
                              "h": R(ph), "min_h": R(pp.get("min_height") or 0.0),
                              "roof": pp.get("roof_shape"), "roof_h": pp.get("roof_height"),
                              "color": pp.get("facade_color"), "roof_color": pp.get("roof_color"),
                              "material": pp.get("facade_material")})
        style = None
        if not key and floors <= 3 and region == "core" and (
                pbuf("deck", deck, 1.0).contains(c) or pbuf("plaza_kiosk", plaza_kiosk, 0).contains(c)):
            style = "kiosk"
        style = style or ("landmark" if key else ("lane" if lane_house else
                                                  ("modern" if (floors >= 10 or c.x > 150 or (p.get("class") in ("retail",) and floors > 6))
                                                   else "historic")))
        if ov and ov.get("style"):
            style = "override"
        bpolys = exp_geom(g, 1.0, 0.08)
        for bp in bpolys:
            bp["party"] = party_flags(Polygon(bp["ext"]), bld_raw[idx][0] if not key else None)
        buildings.append({
            "id": p.get("id")[:12], "name": name, "landmark": key, "region": region, "style": style,
            "poly": bpolys, "h": R(height), "min_h": R(min_h), "floors": int(floors),
            "roof": p.get("roof_shape"), "class": p.get("class"),
            "facade_color": p.get("facade_color"), "roof_color": p.get("roof_color"),
            "parts": parts,
            "base_z": R(zat(c.x, c.y)) if region == "core" else 0.0,
            "ov": {k: v for k, v in (ov or {}).items() if k not in ("match", "towers")} or None,
        })
        # towers standing on an OSM podium (e.g. Hyatt on the Bund)
        for t in (ov or {}).get("towers", []):
            rect = g.minimum_rotated_rectangle
            cs = list(rect.exterior.coords)[:4]
            e1 = math.dist(cs[0], cs[1]); e2 = math.dist(cs[1], cs[2])
            if e1 >= e2:
                a0, a1, b0 = cs[0], cs[1], cs[2]
            else:
                a0, a1, b0 = cs[1], cs[2], cs[3]
            L = math.dist(a0, a1)
            ux, uy = (a1[0] - a0[0]) / L, (a1[1] - a0[1]) / L
            W = math.dist(a1, b0)
            vx, vy = (b0[0] - a1[0]) / W, (b0[1] - a1[1]) / W
            f0, f1 = (0.06, 0.06 + t["frac"]) if t["end"] == 0 else (0.94 - t["frac"], 0.94)
            q = [(a0[0] + ux * L * f + vx * W * w, a0[1] + uy * L * f + vy * W * w)
                 for f, w in ((f0, 0.18), (f1, 0.18), (f1, 0.82), (f0, 0.82))]
            tp = orient(Polygon(q), 1.0).intersection(g)
            buildings.append({
                "id": (p.get("id") or "x")[:10] + f"t{t['end']}", "name": (name or "") + " 塔楼", "landmark": None,
                "region": region, "style": "override", "poly": exp_geom(tp, 1.0, 0.05), "h": R(t["height"]),
                "min_h": 0.0, "floors": t["floors"], "roof": None, "class": None, "facade_color": None,
                "roof_color": None, "parts": [], "base_z": R(zat(c.x, c.y)) if region == "core" else 0.0,
                "ov": {"style": "modern_glass", "material": "curtain_blue"},
            })
            for bp in buildings[-1]["poly"]:
                bp["party"] = [0] * len(bp["ext"])
    print("buildings:", len(buildings), "landmarks matched:", len(done_lm))

    # ---------------- bridges ----------------
    bridge_out = []
    for g, p in infra:
        if p.get("class") == "bridge" and g.geom_type in ("Polygon", "MultiPolygon"):
            nm = (p.get("names") or {}).get("primary")
            rect = g.minimum_rotated_rectangle
            cs = list(rect.exterior.coords)[:4]
            e1 = math.dist(cs[0], cs[1])
            e2 = math.dist(cs[1], cs[2])
            if e1 > e2:
                a, b = cs[0], cs[1]
                wdt, ln = e2, e1
                off = ((cs[2][0] - cs[1][0]) / 2, (cs[2][1] - cs[1][1]) / 2)
            else:
                a, b = cs[1], cs[2]
                wdt, ln = e1, e2
                off = ((cs[0][0] - cs[1][0]) / 2, (cs[0][1] - cs[1][1]) / 2)
            axis = [[R(a[0] + off[0]), R(a[1] + off[1])], [R(b[0] + off[0]), R(b[1] + off[1])]]
            bridge_out.append({"name": nm, "poly": exp_geom(g, 1.0, 0.05), "axis": axis,
                               "length": R(ln), "width": R(wdt)})

    def road_out(r, zprof=None):
        d = {"pts": exp_line(r.line.simplify(0.1)), "name": r.name, "class": r.cls,
             "lanes": r.prof["lanes"], "lw": r.prof["lw"], "width": R(r.width), "oneway": r.oneway,
             "level": r.level}
        return d

    viaduct_out = []
    for r in viaducts:
        if r.line.intersects(ROADS):
            d = road_out(r)
            d["z"] = R(LEVEL_H * r.level)
            viaduct_out.append(d)
    bridge_roads = [road_out(r) for r in bridges]

    ramps_out = []
    for t in trench_items:
        r = t["road"]
        L = r.line.length
        pts, zs = [], []
        for s, z in t["profile"]:
            q = r.line.interpolate(s)
            pts.append((q.x, q.y))
            zs.append(z)
        ramps_out.append({"pts": [[R(x), R(y), R(z)] for (x, y), z in zip(pts, zs)],
                          "width": R(r.width), "up": bool(t.get("up")), "name": r.name})

    # ---------------- pedestrian plaza polygons for paving variation ----------------
    plazas = []
    for g, p in load("land_use"):
        if p.get("class") in ("pedestrian", "plaza") and g.area < 2e6:
            plazas.append(g)
    plaza_full = clean(unary_union(plazas + [ped_area]))
    planters = []
    for pp in polys(plaza_full):
        for hole in pp.interiors:
            hp = Polygon(hole)
            if 20 < hp.area < 2500 and hp.intersection(footprints).area < 1.0 and \
                    hp.intersection(road_area).area < 1.0 and hp.within(pave.buffer(0.5)):
                planters.append(hp.buffer(-0.3))
    planters = clean(unary_union(planters), 10.0) if planters else Polygon()
    plaza = clean(plaza_full.intersection(pave), 5.0)
    for x, y in poisson(planters.buffer(-0.9), 6.5, rng):
        trees.append([R(x), R(y), R(Z_PAVE + 0.45), "plane", round(rng.uniform(0.7, 0.95), 2),
                      round(rng.uniform(0, 6.283), 2)])

    # ---------------- piers ----------------
    piers = []
    for g, p in infra:
        if p.get("class") == "pier":
            if g.geom_type in ("Polygon", "MultiPolygon"):
                piers += exp_geom(g.intersection(SCENE), 5.0)
            else:
                for ln in lines(g):
                    if ln.intersects(SCENE):
                        piers += exp_geom(ln.buffer(2.5, cap_style="flat").intersection(water), 5.0)

    # ---------------- ferry routes (东金线 Jinling Rd <-> Dongchang Rd) ----------------
    ferries = []
    for g, p in load("segment"):
        if p.get("subtype") == "water":
            nm = (p.get("names") or {}).get("primary") or ""
            for ln in lines(g):
                if ln.within(SCENE.buffer(300)) and ln.length < 5000:
                    ferries.append({"name": nm, "pts": exp_line(ln.simplify(1.0))})
    terminals = []
    for g, p in infra:
        if p.get("class") == "ferry_terminal":
            c = g.centroid
            if SCENE.contains(c):
                terminals.append({"name": (p.get("names") or {}).get("primary"), "pos": [R(c.x), R(c.y)]})

    # ---------------- points of interest used for statues etc. ----------------
    pois = []
    for g, p in infra:
        if g.geom_type == "Point" and p.get("class") in ("artwork", "viewpoint", "fountain"):
            pois.append({"pos": [R(g.x), R(g.y)], "class": p.get("class"),
                         "name": (p.get("names") or {}).get("primary")})

    scene.update({
        "water": exp_geom(water, 50, 0.2),
        "land": exp_geom(land, 20, 0.1),
        "road_area": exp_geom(road_area, 1.0, 0.03),
        "pavement": exp_geom(clean(pave.difference(plaza), 0.5), 0.5, 0.03),
        "plaza": exp_geom(plaza, 5.0, 0.05),
        "planters": exp_geom(planters, 5.0, 0.05),
        "pedestrian_streets": exp_geom(ped_area, 2.0, 0.05),
        "green": exp_geom(green, 3.0, 0.05),
        "wood": exp_geom(wood, 3.0, 0.1),
        "deck": exp_geom(deck, 10.0, 0.05),
        "deck_walls": deck_walls,
        "water_edges": edges,
        "medians": med_out,
        "trench_area": exp_geom(trench_area, 1.0, 0.05),
        "markings": marks,
        "zebras": exp_geom(unary_union(zebras), 0.1, 0.01) if zebras else [],
        "stop_lines": exp_geom(unary_union(stop_lines), 0.1, 0.01) if stop_lines else [],
        "arrows": arrows,
        "roads": [road_out(r) for r in surface if r.line.intersects(ROADS)],
        "bridge_roads": bridge_roads,
        "viaducts": viaduct_out,
        "ramps": ramps_out,
        "bridges": bridge_out,
        "stairs": stairs,
        "trees": trees,
        "lamps": lamps,
        "signals": signals,
        "shelters": shelters,
        "bollards": bollards,
        "manholes": manholes,
        "buildings": buildings,
        "piers": piers,
        "pois": pois,
        "ferry_routes": ferries,
        "ferry_terminals": terminals,
    })
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(scene, fh, ensure_ascii=False, separators=(",", ":"))
    print("wrote", args.out, "%.1f MB" % (os.path.getsize(args.out) / 1e6))


if __name__ == "__main__":
    main()
