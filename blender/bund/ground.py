"""Terrain: river, banks, roads, pavements, kerbs, greens, promenade, markings."""
import math

from . import util as U

Z_BED = -7.0


def _polys(lst):
    for p in lst:
        yield p["ext"], p.get("holes", [])


def build(sc, mats, col):
    L = sc["levels"]
    zw, zp, zg, zd, par = L["water"], L["pave"], L["green"], L["deck"], L["parapet"]
    objs = []

    # ---------------- water + riverbed ----------------
    mb = U.MeshBuilder()
    for ext, holes in _polys(sc["water"]):
        U.fill(mb, ext, holes, zw, "water_huangpu")
    objs.append(U.add_obj("Water_Huangpu_SuzhouCreek", mb.build("water", mats), col))
    mb = U.MeshBuilder()
    x0, y0, x1, y1 = sc["extent"]
    U.fill(mb, [(x0 - 3000, y0 - 3000), (x1 + 3000, y0 - 3000), (x1 + 3000, y1 + 3000), (x0 - 3000, y1 + 3000)],
           [], Z_BED, "riverbed")
    objs.append(U.add_obj("Riverbed", mb.build("riverbed", mats), col))

    # ---------------- roads ----------------
    mb = U.MeshBuilder()
    for ext, holes in _polys(sc["road_area"]):
        U.fill(mb, ext, holes, 0.0, "asphalt")
        # skirt so the road edge never shows a gap against kerbs
        U.walls(mb, U.ccw(ext), -0.4, 0.0, "concrete_dark")
    objs.append(U.add_obj("Road_Surface", mb.build("road_surface", mats), col))

    # ---------------- pavements, plazas, kerbs ----------------
    mb = U.MeshBuilder()
    for ext, holes in _polys(sc["pavement"]):
        U.prism(mb, ext, holes, -0.4, zp, "curb_granite", "paving_sidewalk")
    for ext, holes in _polys(sc["plaza"]):
        U.prism(mb, ext, holes, -0.4, zp + 0.004, "curb_granite", "paving_plaza")
    objs.append(U.add_obj("Pavement_Sidewalks_Plazas", mb.build("pavement", mats), col))

    # ---------------- greens, medians, planters ----------------
    mb = U.MeshBuilder()
    for ext, holes in _polys(sc["green"]):
        U.prism(mb, ext, holes, -0.4, zg, "curb_granite", "grass")
    for ext, holes in _polys(sc.get("wood", [])):
        U.fill(mb, ext, holes, zg + 0.005, "grass_park")
    for ext, holes in _polys(sc["medians"]):
        U.prism(mb, ext, holes, -0.2, 0.28, "curb_granite", "hedge")
    for ext, holes in _polys(sc.get("planters", [])):
        U.prism(mb, ext, holes, 0.0, zp + 0.5, "granite_grey", "soil")
        inner = U.offset_ring(U.ccw(ext), 0.35)
        U.fill(mb, inner, [], zp + 0.52, "grass")
    objs.append(U.add_obj("Greens_Medians_Planters", mb.build("greens", mats), col))

    # ---------------- Bund promenade deck (flood wall top) ----------------
    mb = U.MeshBuilder()
    for ext, holes in _polys(sc["deck"]):
        U.prism(mb, ext, holes, -0.4, zd, "granite_grey", "paving_deck")
    stairs = sc.get("stairs", [])
    for st in stairs:
        _stair(mb, st, zp, zd)
    # inland edge: low granite wall + railing, open where stairs arrive
    for pts in sc.get("deck_walls", []):
        for run in _split_runs(pts, [s["pos"] for s in stairs], 3.6):
            if U.polyline_length(run) < 1.0:
                continue
            U.wall_strip(mb, run, zd, zd + 0.55, 0.35, "granite_light", "trim_light")
            _railing(mb, run, zd + 0.55, 0.55, "metal_dark", post_step=2.0)
    objs.append(U.add_obj("Bund_Promenade_Deck", mb.build("deck", mats), col))

    # ---------------- river banks, flood walls, parapets ----------------
    mb = U.MeshBuilder()
    water_polys = sc["water"]
    for e in sc["water_edges"]:
        pts = e["pts"]
        if len(pts) < 2:
            continue
        side = _water_side(pts, water_polys)          # +1: water on the left
        top = e["top"]
        bank = "bank_granite" if e["style"] == "bund" else "bank_concrete"
        # vertical bank wall facing the water
        _bank_wall(mb, pts, Z_BED, top, side, bank)
        # parapet set back onto the land side
        inland = [_shift(pts, i, -side * 0.35) for i in range(len(pts))]
        if e["style"] == "bund":
            U.wall_strip(mb, inland, top - 0.05, top + e["parapet"], 0.55, "granite_light", "trim_light")
            # projecting coping
            U.wall_strip(mb, inland, top + e["parapet"] - 0.12, top + e["parapet"] + 0.02, 0.72, "trim_light")
        else:
            U.wall_strip(mb, inland, top - 0.05, top + e["parapet"], 0.35, "concrete", "concrete_white")
        # mooring bollards / water-level band
        U.wall_strip(mb, [_shift(pts, i, side * 0.02) for i in range(len(pts))], zw - 0.6, zw + 0.25, 0.06,
                     "concrete_dark")
    objs.append(U.add_obj("River_Banks_Floodwalls", mb.build("banks", mats), col))

    # ---------------- piers / pontoons ----------------
    mb = U.MeshBuilder()
    for ext, holes in _polys(sc.get("piers", [])):
        U.prism(mb, ext, holes, zw - 0.8, zw + 0.9, "concrete_dark", "concrete")
    if len(mb):
        objs.append(U.add_obj("Ferry_Piers", mb.build("piers", mats), col))

    # ---------------- road markings ----------------
    mb = U.MeshBuilder()
    zm = 0.012
    for m in sc["markings"]:
        mat = "paint_yellow" if m["c"] == "y" else "paint_white"
        U.ribbon(mb, m["pts"], m["w"], zm, mat)
    for ext, holes in _polys(sc["zebras"]):
        U.fill(mb, ext, holes, zm, "paint_white")
    for ext, holes in _polys(sc["stop_lines"]):
        U.fill(mb, ext, holes, zm, "paint_white")
    for ar in sc.get("arrows", []):
        _arrow(mb, ar, zm)
    objs.append(U.add_obj("Road_Markings", mb.build("markings", mats), col))
    return objs


# --------------------------------------------------------------------------

def _shift(pts, i, d):
    nrm = U.polyline_normals(pts)
    (nx, ny), sc = nrm[i]
    sc = min(sc, 2.5)
    return (pts[i][0] + nx * d * sc, pts[i][1] + ny * d * sc)


def _water_side(pts, water_polys):
    mid = len(pts) // 2
    i = max(0, min(len(pts) - 2, mid))
    a, b = pts[i], pts[i + 1]
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = math.hypot(dx, dy) or 1
    mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    lx, ly = mx - dy / L * 2.0, my + dx / L * 2.0
    for p in water_polys:
        if U.in_poly(lx, ly, p):
            return 1
    return -1


def _bank_wall(mb, pts, z0, z1, side, mat):
    n = len(pts)
    acc = 0.0
    for i in range(n - 1):
        a, b = pts[i], pts[i + 1]
        Ls = math.dist(a, b)
        if Ls < 1e-3:
            continue
        cos = [(a[0], a[1], z0), (b[0], b[1], z0), (b[0], b[1], z1), (a[0], a[1], z1)]
        # face towards the water side
        if side < 0:
            pass
        else:
            cos = cos[::-1]
        mb.face(cos, mat)
        acc += Ls


def _split_runs(pts, cuts, r):
    """Split a polyline into runs that stay farther than r from any cut point."""
    dense = U.resample(pts, 0.5)
    runs, cur = [], []
    for p in dense:
        near = any((p[0] - c[0]) ** 2 + (p[1] - c[1]) ** 2 < r * r for c in cuts)
        if near:
            if len(cur) > 1:
                runs.append(cur)
            cur = []
        else:
            cur.append(p)
    if len(cur) > 1:
        runs.append(cur)
    # thin them out again
    out = []
    for run in runs:
        keep = [run[0]]
        for p in run[1:-1]:
            if math.dist(p, keep[-1]) > 2.0:
                keep.append(p)
        keep.append(run[-1])
        out.append(keep)
    return out


def _railing(mb, pts, z, h, mat, post_step=1.8, bar=0.04):
    """Simple metal railing: top rail, bottom rail and posts."""
    U.wall_strip(mb, pts, z + h - 0.06, z + h, 0.07, mat)
    U.wall_strip(mb, pts, z + 0.08, z + 0.12, 0.04, mat)
    L = U.polyline_length(pts)
    n = max(1, int(L // post_step))
    for k in range(n + 1):
        p, hd = U.point_along(pts, L * k / n)
        U.box(mb, -bar, -bar, 0, bar, bar, h, mat, origin=(p[0], p[1], z), h=hd)


def _stair(mb, st, z_low, z_high):
    """Flight of steps from the plaza up to the deck edge at st['pos']."""
    x, y = st["pos"]
    h = st["h"]                 # points into the deck (uphill)
    w = st["width"]
    rise = z_high - z_low
    n = max(4, int(round(rise / 0.14)))
    tread = 0.34
    run = n * tread
    dz = rise / n
    ox, oy = x - math.cos(h) * run, y - math.sin(h) * run
    for k in range(n):
        # step k: from distance k*tread to run, top at z_low + (k+1)*dz
        U.box(mb, k * tread, -w / 2, z_low - 0.05, run + 0.05, w / 2, z_low + (k + 1) * dz,
              "curb_granite", origin=(ox, oy, 0), h=h)
    # cheek walls
    for s in (-1, 1):
        yy = s * (w / 2 + 0.25)
        cos_in = [(0, yy - 0.25, z_low), (run, yy - 0.25, z_low), (run, yy - 0.25, z_high + 0.55),
                  (0, yy - 0.25, z_low + 0.55)]
        cos_out = [(0, yy + 0.25, z_low), (run, yy + 0.25, z_low), (run, yy + 0.25, z_high + 0.55),
                   (0, yy + 0.25, z_low + 0.55)]
        cin = [U.xform(p, (ox, oy, 0), h) for p in cos_in]
        cout = [U.xform(p, (ox, oy, 0), h) for p in cos_out]
        mb.face(cin[::-1] if s > 0 else cin, "granite_light")
        mb.face(cout if s > 0 else cout[::-1], "granite_light")
        mb.face([cin[3], cin[2], cout[2], cout[3]] if s < 0 else [cout[3], cout[2], cin[2], cin[3]], "trim_light")
        mb.face([cin[0], cin[3], cout[3], cout[0]] if s < 0 else [cout[0], cout[3], cin[3], cin[0]], "granite_light")


ARROWS = {
    # outlines in metres, x forward, y left; 4.5 m long Chinese guide arrows
    "straight": [(0, -0.15), (3.0, -0.15), (3.0, -0.45), (4.5, 0), (3.0, 0.45), (3.0, 0.15), (0, 0.15)],
    "left": [(0, -0.15), (2.4, -0.15), (2.4, 0.9), (2.1, 0.9), (2.9, 1.5), (3.7, 0.9), (2.7, 0.9), (2.7, 0.0),
             (2.7, 0.15), (2.7, -0.15), (2.7, 0.15), (0, 0.15)],
}


def _arrow_shapes(typ):
    st = ARROWS["straight"]
    shapes = []
    if "straight" in typ:
        shapes.append(st)
    if typ == "left" or typ.endswith("left"):
        shapes.append([(0.4, 0.15), (2.0, 0.15), (2.0, 0.85), (1.7, 0.85), (2.25, 1.45), (2.8, 0.85),
                       (2.3, 0.85), (2.3, -0.15 if typ == "left" else 0.15), (0.4, -0.15 if typ == "left" else 0.15)])
        if typ == "left":
            shapes.append([(0, -0.15), (0.4, -0.15), (0.4, 0.15), (0, 0.15)])
    if typ.endswith("right"):
        shapes.append([(0.4, -0.15), (2.0, -0.15), (2.0, -0.85), (1.7, -0.85), (2.25, -1.45), (2.8, -0.85),
                       (2.3, -0.85), (2.3, 0.15), (0.4, 0.15)][::-1])
    return shapes


def _arrow(mb, ar, z):
    x, y = ar["pos"]
    h = ar["h"]
    for shp in _arrow_shapes(ar["type"]):
        ring = [U.xform((px - 2.25, py, 0), (x, y, 0), h)[:2] for px, py in shp]
        U.fill(mb, U.ccw(ring), [], z, "paint_white")
