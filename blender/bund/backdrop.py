"""Lujiazui skyline across the river (backdrop, lower detail).

The four supertall landmarks get procedural models with their documented
heights (Oriental Pearl Tower 468 m, Shanghai Tower 632 m, SWFC 492 m,
Jin Mao 420.5 m); positions come from OSM building parts. Every other
building with OSM parts is extruded part by part.
"""
import math
import random
import zlib

from . import util as U
from .facade import CURTAINS, FAR_FACADES, parapet


def _part_rings(b):
    for p in b.get("parts", []):
        for poly in p["poly"]:
            yield p, poly


def _bbox_center(b):
    xs, ys = [], []
    for p in b["poly"]:
        for x, y in p["ext"]:
            xs.append(x)
            ys.append(y)
    return (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2


def _max_h(b):
    hs = [p["h"] for p in b.get("parts", [])] + [b["h"]]
    return max(hs)


def oriental_pearl(mb, cx, cy):
    """东方明珠电视塔 (1994), 468 m."""
    col = "concrete_white"
    # three vertical columns (d=9 m) up to the upper sphere
    for k in range(3):
        a = math.radians(90 + 120 * k)
        x, y = cx + math.cos(a) * 7.5, cy + math.sin(a) * 7.5
        U.cylinder(mb, (x, y, 0), 4.5, 296, 16, col)
    # three inclined legs (d=7 m) to the lower sphere
    for k in range(3):
        a = math.radians(30 + 120 * k)
        x0, y0 = cx + math.cos(a) * 44, cy + math.sin(a) * 44
        x1, y1 = cx + math.cos(a) * 11, cy + math.sin(a) * 11
        _tube(mb, (x0, y0, 0), (x1, y1, 72), 3.5, col)
        U.sphere(mb, (x0, y0, 6), 6.5, 16, 8, "pearl_pink")      # base spheres
    # lower sphere (d=50 m) with silver bands
    _pearl(mb, cx, cy, 93, 25)
    # five small spheres between the big ones
    for k, zz in enumerate((150, 172, 194, 216, 238)):
        a = math.radians(90 + 72 * k)
        U.sphere(mb, (cx + math.cos(a) * 9.5, cy + math.sin(a) * 9.5, zz), 5.5, 16, 8, "pearl_pink")
    # upper sphere (d=45 m)
    _pearl(mb, cx, cy, 272, 22.5)
    # shaft to the space module
    U.cylinder(mb, (cx, cy, 294), 4.2, 44, 16, col)
    _pearl(mb, cx, cy, 343, 7.5)
    # antenna mast
    U.cylinder(mb, (cx, cy, 350), 2.6, 60, 12, "pearl_silver", r_top=1.6)
    U.cylinder(mb, (cx, cy, 410), 1.6, 58, 8, "metal_grey", r_top=0.35)
    for zz in (360, 380, 400):
        U.lathe(mb, (cx, cy, zz), [(3.6, 0), (3.6, 1.2)], 12, "pearl_silver", smooth=False)


def _pearl(mb, cx, cy, zc, R):
    U.sphere(mb, (cx, cy, zc), R, 40, 24, "pearl_pink")
    for dz in (-0.35, 0.0, 0.35):
        rr = R * math.sqrt(max(0, 1 - dz * dz)) * 1.01
        U.lathe(mb, (cx, cy, zc + dz * R - 0.6), [(rr, 0), (rr, 1.2)], 40, "pearl_silver", smooth=True)


def _tube(mb, p0, p1, r, mat, n=12):
    dx, dy, dz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
    L = math.sqrt(dx * dx + dy * dy + dz * dz)
    ux, uy, uz = dx / L, dy / L, dz / L
    sx, sy, sz = -uy, ux, 0
    sl = math.hypot(sx, sy) or 1
    sx, sy = sx / sl, sy / sl
    tx, ty, tz = uy * sz - uz * sy, uz * sx - ux * sz, ux * sy - uy * sx
    r0, r1 = [], []
    for k in range(n):
        a = 2 * math.pi * k / n
        ox = (sx * math.cos(a) + tx * math.sin(a)) * r
        oy = (sy * math.cos(a) + ty * math.sin(a)) * r
        oz = (sz * math.cos(a) + tz * math.sin(a)) * r
        r0.append((p0[0] + ox, p0[1] + oy, p0[2] + oz))
        r1.append((p1[0] + ox, p1[1] + oy, p1[2] + oz))
    for k in range(n):
        j = (k + 1) % n
        mb.face([r0[k], r0[j], r1[j], r1[k]], mat, smooth=True)


def _section(shape, s, rot, cx, cy, z):
    return [(cx + (x * math.cos(rot) - y * math.sin(rot)) * s, cy + (x * math.sin(rot) + y * math.cos(rot)) * s, z)
            for x, y in shape]


def _loft(mb, sections, mat, cap=True, smooth=False):
    n = len(sections[0])
    for a, b in zip(sections[:-1], sections[1:]):
        for k in range(n):
            j = (k + 1) % n
            mb.face([a[k], a[j], b[j], b[k]], mat, smooth=smooth)
    if cap:
        mb.face(sections[-1], "roof_flat")


def shanghai_tower(mb, cx, cy):
    """上海中心大厦 (2015), 632 m: twisting, tapering, notched triangle."""
    shape = []
    R = 41.0
    for k in range(60):
        a = 2 * math.pi * k / 60
        # rounded triangle: radius modulated with 3-fold symmetry
        r = R * (1.0 + 0.10 * math.cos(3 * a))
        # notch at one corner (the vertical V-groove)
        da = (a - 0.0 + math.pi) % (2 * math.pi) - math.pi
        if abs(da) < 0.12:
            r *= 0.82 + 0.18 * abs(da) / 0.12
        shape.append((r * math.cos(a), r * math.sin(a)))
    sections = []
    H = 580.0
    for k in range(59):
        t = k / 58
        z = H * t
        s = 1.0 - 0.45 * t ** 0.9
        sections.append(_section(shape, s, math.radians(120) * t, cx, cy, z))
    _loft(mb, sections, "curtain_silver", cap=False, smooth=True)
    # sloped crown up to 632 m
    top = sections[-1]
    cxx = sum(p[0] for p in top) / len(top)
    cyy = sum(p[1] for p in top) / len(top)
    crown = []
    for x, y, z in top:
        lift = 52.0 * (0.5 + 0.5 * ((x - cxx) * 0.7 + (y - cyy) * 0.7) / 25.0)
        crown.append((x, y, z + max(10.0, lift)))
    _loft(mb, [top, crown], "metal_grey", cap=False)
    mb.face(crown, "metal_grey")
    # inner tower (seen through the skin) + zone bands
    for zz in range(0, int(H), 66):
        ring = _section(shape, (1.0 - 0.45 * (zz / H) ** 0.9) * 1.004, math.radians(120) * zz / H, cx, cy, zz)
        U.ribbon(mb, [(p[0], p[1]) for p in ring], 1.2, zz + 0.5, "metal_grey", closed=True)


def swfc(mb, cx, cy, h0=0.0):
    """上海环球金融中心 (2008), 492 m, with the trapezoid aperture."""
    S = 29.0       # half side of the square base
    H = 492.0
    rot = math.radians(45 - 12)   # diagonal orientation of the tower on site
    sections = []
    for k in range(40):
        t = k / 39
        z = H * 0.9 * t
        # opposite corners cut by arcs: distance of the cut from the centre
        d = S * math.sqrt(2) * (1 - t) + 6.0 * t
        pts = [(-S, -S), (S, -S), (S, S), (-S, S)]
        poly = _cut_square(S, d)
        sections.append(_section(poly, 1.0, rot, cx, cy, z))
    _loft(mb, sections, "curtain_blue", cap=False)
    top = sections[-1]
    ztop = H * 0.9
    # aperture: two legs and a bridge on top
    poly = _cut_square(S, 6.0)
    for side in (-1, 1):
        leg = [(x, y) for x, y in poly]
        leg = [(x, y * 0.5 + side * S * 0.5) if True else (x, y) for x, y in leg]
        bot = _section(leg, 1.0, rot, cx, cy, ztop)
        topr = _section(leg, 1.0, rot, cx, cy, H - 6)
        _loft(mb, [bot, topr], "curtain_blue", cap=False)
    beam = _section(poly, 1.0, rot, cx, cy, H - 6)
    beam2 = _section(poly, 1.0, rot, cx, cy, H)
    _loft(mb, [beam, beam2], "metal_grey", cap=True)
    mb.face(top, "roof_flat")


def _cut_square(S, d):
    """Square of half-side S with the +x+y and -x-y corners cut at distance d from the centre."""
    pts = []
    corners = [(S, -S), (S, S), (-S, S), (-S, -S)]
    out = []
    for (x0, y0), (x1, y1) in zip(corners, corners[1:] + corners[:1]):
        out.append((x0, y0))
    # clip against the lines x + y <= d*sqrt2 and x + y >= -d*sqrt2
    poly = corners
    for sgn in (1, -1):
        res = []
        n = len(poly)
        for i in range(n):
            p, q = poly[i], poly[(i + 1) % n]
            fp = sgn * (p[0] + p[1]) - d * math.sqrt(2)
            fq = sgn * (q[0] + q[1]) - d * math.sqrt(2)
            if fp <= 0:
                res.append(p)
            if (fp < 0) != (fq < 0) and fp != fq:
                t = fp / (fp - fq)
                res.append((p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t))
        poly = res
    return poly


def jin_mao(mb, cx, cy):
    """金茂大厦 (1999), 420.5 m: tiered pagoda form, octagonal plan."""
    oct_ = []
    for k in range(16):
        a = 2 * math.pi * k / 16 + math.pi / 16
        r = 1.0 if k % 2 == 0 else 0.94
        oct_.append((r * math.cos(a), r * math.sin(a)))
    z = 0.0
    half = 27.0
    tiers = [(80, 1.0), (40, 0.94), (35, 0.89), (30, 0.84), (27, 0.79), (24, 0.74), (22, 0.70), (20, 0.66),
             (18, 0.62), (16, 0.58), (14, 0.54), (12, 0.5)]
    for h, s in tiers:
        a = _section(oct_, half * s, 0.0, cx, cy, z)
        b = _section(oct_, half * s, 0.0, cx, cy, z + h)
        _loft(mb, [a, b], "curtain_grey", cap=False)
        ledge = _section(oct_, half * s * 1.04, 0.0, cx, cy, z + h)
        _loft(mb, [b, ledge], "metal_grey", cap=False)
        ledge2 = _section(oct_, half * s * 1.04, 0.0, cx, cy, z + h + 0.8)
        _loft(mb, [ledge, ledge2], "metal_grey", cap=False)
        z += h
    # crown and spire
    top = _section(oct_, half * 0.5 * 1.04, 0.0, cx, cy, z + 0.8)
    mb.face(top, "roof_flat")
    U.lathe(mb, (cx, cy, z + 0.8), [(half * 0.42, 0), (half * 0.3, 18), (half * 0.18, 30), (2.0, 42)], 16,
            "metal_grey", smooth=False)
    U.cylinder(mb, (cx, cy, z + 42), 1.6, 420.5 - (z + 42), 8, "metal_grey", r_top=0.3)


SPECIAL = {
    # building_part ids from Overture (prefix) -> builder
    "712993ca": ("oriental_pearl", oriental_pearl),
    "a7a88991": ("shanghai_tower", shanghai_tower),
    "119c8e0e": ("swfc", swfc),
    "cb5b6f14": ("jin_mao", jin_mao),
}


def build_all(sc, mats, root):
    col = U.coll("Backdrop_Lujiazui_Pudong", root)
    mb = U.MeshBuilder()
    special = U.MeshBuilder()
    done = set()
    for b in sc["buildings"]:
        if not b.get("parts") or b["region"] not in ("far", "pudong"):
            continue
        rnd = random.Random(zlib.crc32(b["id"].encode()))
        key = b["id"][:8]
        if key in SPECIAL and key not in done:
            done.add(key)
            # use the centre of the tallest part
            best = max(b["parts"], key=lambda p: p["h"])
            xs = [x for poly in best["poly"] for x, _ in poly["ext"]]
            ys = [y for poly in best["poly"] for _, y in poly["ext"]]
            cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
            if key == "712993ca":
                cx, cy = _bbox_center(b)
            SPECIAL[key][1](special, cx, cy)
            continue
        mat = rnd.choice(CURTAINS) if _max_h(b) > 50 else rnd.choice(FAR_FACADES)
        built_parts = 0
        for p, poly in _part_rings(b):
            ext = U.ccw(poly["ext"])
            if abs(U.signed_area(ext)) < 4:
                continue
            z0 = p.get("min_h") or 0.0
            z1 = p["h"]
            if p.get("roof") == "dome":
                cx, cy = U.centroid(ext)
                R = math.sqrt(abs(U.signed_area(ext)) / math.pi)
                zc = max(z0, b["h"]) + R * 0.35
                U.sphere(mb, (cx, cy, zc), R, 40, 24, "glass_globe", z_min=-0.6, z_max=1.0)
                built_parts += 1
                continue
            if z1 <= z0 + 0.5:
                continue
            pm = mat
            if p.get("material") == "glass":
                pm = rnd.choice(CURTAINS)
            U.walls(mb, ext, z0, z1, pm)
            U.fill(mb, ext, [], z1, "roof_flat")
            built_parts += 1
        # podium / parent outline if the parts do not cover it
        if built_parts == 0 or b["h"] > 0:
            for poly in b["poly"]:
                ext = U.ccw(poly["ext"])
                top = min(b["h"], 24.0) if built_parts else b["h"]
                U.walls(mb, ext, -0.3, top, rnd.choice(FAR_FACADES))
                U.fill(mb, ext, poly.get("holes", []), top, "roof_flat")
    U.add_obj("Lujiazui_Towers", mb.build("lujiazui", mats), col)
    U.add_obj("Lujiazui_Landmarks_Pearl_ShanghaiTower_SWFC_JinMao", special.build("lujiazui_lm", mats), col)
