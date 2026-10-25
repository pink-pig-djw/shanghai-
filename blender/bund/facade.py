"""Generic building generator.

Each OSM footprint is extruded to its height and dressed according to its
style:
  historic : 1900-1940s masonry blocks (stone/brick/stucco), tall ground
             floor, recessed vertical windows with sills, string courses,
             main cornice and parapet
  modern   : post-1980 buildings, punched windows in tile/stone or glass
             curtain walls, rooftop plant
  lane     : 2-3 storey Shikumen / lane houses, grey brick, pitched roofs
Distant buildings (region far / puxi_back) get painted-on windows instead of
geometry to keep the polygon count reasonable.
"""
import math
import random
import zlib

from . import util as U
from . import arch as A

HIST_MATS = [("granite_light", "rustic_light", "trim_light"),
             ("granite_warm", "rustic_warm", "trim_light"),
             ("granite_grey", "rustic_grey", "trim_light"),
             ("granite_golden", "rustic_golden", "trim_light"),
             ("stucco_cream", "rustic_warm", "trim_light"),
             ("stucco_grey", "rustic_grey", "trim_light"),
             ("stucco_ochre", "rustic_warm", "trim_light"),
             ("stucco_pink", "rustic_warm", "trim_light"),
             ("brick_red", "rustic_warm", "trim_light"),
             ("brick_brown", "rustic_grey", "trim_light"),
             ("brick_grey_red", "rustic_grey", "trim_light"),
             ("brick_cream", "rustic_light", "trim_light"),
             ("brick_red_banded", "rustic_white", "trim_light")]
HIST_WEIGHTS = [12, 10, 7, 6, 7, 5, 5, 3, 9, 7, 5, 4, 2]
MODERN_WALL = ["concrete_white", "granite_grey", "granite_light", "stucco_white", "stucco_grey",
               "granite_dark", "concrete", "stucco_pink"]
CURTAINS = ["curtain_blue", "curtain_green", "curtain_grey", "curtain_silver", "curtain_gold"]
FAR_FACADES = ["facade_tile_white", "facade_tile_beige", "facade_tile_grey", "facade_tile_pink"]


class Facade:
    """Per-building facade parameters."""

    def __init__(self, rnd, style, height, floors):
        self.style = style
        self.rnd = rnd
        if style == "historic":
            wall, rustic, trim = rnd.choices(HIST_MATS, HIST_WEIGHTS)[0]
            self.wall, self.base, self.trim = wall, rustic, trim
            self.gf = rnd.uniform(4.6, 5.6)
            self.bay = rnd.uniform(3.2, 4.2)
            self.win_w = rnd.uniform(1.3, 1.6)
            self.win_h_frac = rnd.uniform(0.55, 0.62)
            self.sill = 0.95
            self.window = rnd.choice(["window_hist_white", "window_hist_white", "window_hist_dark",
                                      "window_hist_green"])
            self.cornice = True
            self.string_courses = rnd.random() < 0.75
            self.parapet_h = rnd.uniform(0.8, 1.4)
            self.shop = rnd.random() < 0.5
            self.depth = 0.32
            self.pilasters = rnd.random() < 0.4
            self.arched_gf = (not self.shop) and rnd.random() < 0.6
        elif style == "lane":
            self.wall = rnd.choice(["brick_grey", "brick_grey", "brick_grey_red", "stucco_grey", "brick_red"])
            self.base = self.wall
            self.trim = "trim_light"
            self.gf = 3.6
            self.bay = rnd.uniform(3.0, 3.6)
            self.win_w = 1.1
            self.win_h_frac = 0.55
            self.sill = 0.9
            self.window = "window_lane"
            self.cornice = False
            self.string_courses = False
            self.parapet_h = 0.0
            self.shop = False
            self.depth = 0.2
        elif style == "kiosk":
            # small modern pavilions on the promenade (toilets, kiosks, tunnel entrance)
            self.wall = "curtain_grey"
            self.base = "granite_grey"
            self.trim = "concrete_white"
            self.gf = height
            self.bay = 2.0
            self.win_w = 1.7
            self.win_h_frac = 0.8
            self.sill = 0.2
            self.window = "window_modern"
            self.cornice = False
            self.string_courses = False
            self.parapet_h = 0.0
            self.shop = True
            self.depth = 0.08
        else:  # modern
            self.curtain = height > 45 and rnd.random() < 0.6
            self.wall = rnd.choice(CURTAINS) if self.curtain else rnd.choice(MODERN_WALL)
            self.base = "granite_dark" if rnd.random() < 0.5 else self.wall
            self.trim = "concrete_white"
            self.gf = rnd.uniform(4.5, 5.5)
            self.bay = rnd.uniform(2.8, 3.6)
            self.win_w = self.bay * rnd.uniform(0.5, 0.7)
            self.win_h_frac = rnd.uniform(0.5, 0.65)
            self.sill = 0.9
            self.window = "window_modern"
            self.cornice = False
            self.string_courses = False
            self.parapet_h = rnd.uniform(0.6, 1.2)
            self.shop = True
            self.depth = 0.18
        self.floors = max(1, floors)
        top = height - (self.parapet_h if self.parapet_h else 0)
        self.top = max(self.gf + 2.5, top)
        n_up = max(0, self.floors - 1)
        self.fh = (self.top - self.gf) / n_up if n_up else 0.0
        if n_up and self.fh < 2.8:
            # inconsistent data (too many floors): drop floors
            n_up = max(1, int((self.top - self.gf) / 3.2))
            self.fh = (self.top - self.gf) / n_up
            self.floors = n_up + 1
        if n_up and self.fh > 6.0:
            n_up = int(math.ceil((self.top - self.gf) / 4.5))
            self.fh = (self.top - self.gf) / n_up
            self.floors = n_up + 1


def _edge_frame(a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = math.hypot(dx, dy)
    tx, ty = dx / L, dy / L
    nx, ny = ty, -tx            # outward for CCW rings
    return L, (tx, ty), (nx, ny)


def window_wall(mb, a, b, z0, z1, rows, cols, depth, mat_wall, mat_glass, mat_reveal, rnd,
                sill_mat=None, frame_out=0.0, arch=False, uv_off=0.0):
    """One wall rectangle with a grid of recessed windows.

    rows: list of (zb, zt) window bottoms/tops; cols: list of (s0, s1) along
    the wall (metres from a). Wall pieces between windows are separate quads,
    window openings get four reveal faces and a glass face at `depth`.
    """
    L, (tx, ty), (nx, ny) = _edge_frame(a, b)

    def P(s, z, d=0.0):
        return (a[0] + tx * s - nx * d, a[1] + ty * s - ny * d, z)

    xs = [0.0]
    for s0, s1 in cols:
        xs += [s0, s1]
    xs.append(L)
    zs = [z0]
    for zb, zt in rows:
        zs += [zb, zt]
    zs.append(z1)
    win_x = set(range(1, len(xs) - 1, 2))   # column index i is a window column if i odd
    win_z = set(range(1, len(zs) - 1, 2))
    for i in range(len(xs) - 1):
        xa, xb = xs[i], xs[i + 1]
        if xb - xa < 1e-4:
            continue
        for j in range(len(zs) - 1):
            za, zb = zs[j], zs[j + 1]
            if zb - za < 1e-4:
                continue
            uvs = [(uv_off + xa, za), (uv_off + xb, za), (uv_off + xb, zb), (uv_off + xa, zb)]
            if i in win_x and j in win_z:
                d = depth
                # reveals (inward facing)
                mb.face([P(xa, za, d), P(xa, zb, d), P(xa, zb), P(xa, za)], mat_reveal)
                mb.face([P(xb, zb), P(xb, zb, d), P(xb, za, d), P(xb, za)], mat_reveal)
                mb.face([P(xa, zb, d), P(xb, zb, d), P(xb, zb), P(xa, zb)], mat_reveal)
                mb.face([P(xb, za), P(xb, za, d), P(xa, za, d), P(xa, za)], sill_mat or mat_reveal)
                mb.face([P(xa, za, d), P(xb, za, d), P(xb, zb, d), P(xa, zb, d)], mat_glass,
                        uvs=[(0, 0), (1, 0), (1, 1), (0, 1)], attrs={"rnd": rnd.random()})
            else:
                mb.face([P(xa, za), P(xb, za), P(xb, zb), P(xa, zb)], mat_wall, uvs=uvs)


def _band(mb, ring, z, h, out, mat):
    """Horizontal projecting band (string course / cornice) around a ring."""
    outer = U.offset_ring(ring, -out)
    pts_b = [(p[0], p[1], z) for p in outer]
    U.walls(mb, outer, z, z + h, mat)
    # soffit and top
    n = len(ring)
    for i in range(n):
        j = (i + 1) % n
        mb.face([(ring[i][0], ring[i][1], z), (ring[j][0], ring[j][1], z),
                 (outer[j][0], outer[j][1], z), (outer[i][0], outer[i][1], z)], mat)
        mb.face([(outer[i][0], outer[i][1], z + h), (outer[j][0], outer[j][1], z + h),
                 (ring[j][0], ring[j][1], z + h), (ring[i][0], ring[i][1], z + h)], mat)


def cornice(mb, ring, z, mat, scale=1.0):
    """Classical stepped cornice: fascia, corona, cymatium."""
    s = scale
    _band(mb, ring, z, 0.25 * s, 0.12 * s, mat)
    _band(mb, ring, z + 0.25 * s, 0.18 * s, 0.32 * s, mat)
    _band(mb, ring, z + 0.43 * s, 0.30 * s, 0.55 * s, mat)
    _band(mb, ring, z + 0.73 * s, 0.10 * s, 0.42 * s, mat)


def parapet(mb, ring, z, h, t, mat, mat_top):
    inner = U.offset_ring(ring, t)
    U.walls(mb, ring, z, z + h, mat)
    U.walls(mb, inner[::-1], z, z + h, mat)
    n = len(ring)
    for i in range(n):
        j = (i + 1) % n
        mb.face([(ring[i][0], ring[i][1], z + h), (ring[j][0], ring[j][1], z + h),
                 (inner[j][0], inner[j][1], z + h), (inner[i][0], inner[i][1], z + h)], mat_top)


def bay_layout(L, bay, win_w, margin=0.6):
    """Evenly spaced windows along a wall of length L."""
    if L < win_w + 2 * margin:
        return []
    n = max(1, int(round((L - 2 * margin) / bay)))
    n = min(n, int((L - 2 * margin) // (win_w + 0.45)))
    if n < 1:
        return []
    pitch = (L - 2 * margin) / n
    cols = []
    for k in range(n):
        c = margin + pitch * (k + 0.5)
        cols.append((c - win_w / 2, c + win_w / 2))
    return cols


def roof_stuff(mb, ring, z, rnd, big=False, per_area=120.0, max_n=8):
    """Rooftop plant: stair/lift housing, AC units, water tanks."""
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    area = abs(U.signed_area(ring))
    n = int(min(max_n, area / per_area)) + (1 if big else 0)
    placed = 0
    for _ in range(n * 6):
        if placed >= n:
            break
        w = rnd.uniform(1.5, 4.5) if placed else rnd.uniform(3.5, 6.0)
        d = rnd.uniform(1.5, 4.0) if placed else rnd.uniform(3.0, 5.0)
        h = rnd.uniform(0.8, 2.0) if placed else rnd.uniform(2.6, 3.4)
        cx, cy = rnd.uniform(x0, x1), rnd.uniform(y0, y1)
        hd = math.atan2(ring[1][1] - ring[0][1], ring[1][0] - ring[0][0])
        corners = [U.xform((sx * w / 2, sy * d / 2, 0), (cx, cy, 0), hd) for sx in (-1, 1) for sy in (-1, 1)]
        if not all(U.pip(c[0], c[1], ring) and U.dist_to_ring(c[0], c[1], ring) > 1.0 for c in corners):
            continue
        mat = "concrete" if placed == 0 else rnd.choice(["metal_grey", "concrete", "concrete_white"])
        U.box(mb, -w / 2, -d / 2, 0, w / 2, d / 2, h, mat, origin=(cx, cy, z), h=hd)
        placed += 1


def gable_roof(mb, ring, z, pitch_h, mat_roof, mat_wall):
    """Gable roof over the minimum bounding rectangle (lane houses)."""
    # principal direction = longest edge
    best = max(range(len(ring)), key=lambda i: math.dist(ring[i], ring[(i + 1) % len(ring)]))
    a, b = ring[best], ring[(best + 1) % len(ring)]
    hd = math.atan2(b[1] - a[1], b[0] - a[0])
    c, s = math.cos(-hd), math.sin(-hd)
    loc = [((p[0] - a[0]) * c - (p[1] - a[1]) * s, (p[0] - a[0]) * s + (p[1] - a[1]) * c) for p in ring]
    u0, u1 = min(p[0] for p in loc) - 0.3, max(p[0] for p in loc) + 0.3
    v0, v1 = min(p[1] for p in loc) - 0.3, max(p[1] for p in loc) + 0.3
    vm = (v0 + v1) / 2
    ph = min(pitch_h, (v1 - v0) * 0.45)

    def W(u, v, zz):
        return U.xform((u, v, zz), (a[0], a[1], 0), hd)

    mb.face([W(u0, v0, z), W(u1, v0, z), W(u1, vm, z + ph), W(u0, vm, z + ph)], mat_roof)
    mb.face([W(u1, v1, z), W(u0, v1, z), W(u0, vm, z + ph), W(u1, vm, z + ph)], mat_roof)
    mb.face([W(u0, v1, z), W(u0, v0, z), W(u0, vm, z + ph)], mat_wall)
    mb.face([W(u1, v0, z), W(u1, v1, z), W(u1, vm, z + ph)], mat_wall)


def build_detailed(mb, poly, party, b, f, rnd):
    """Full-geometry building for the core area."""
    ext = U.ccw(poly["ext"])
    z0 = -0.3
    zb = b.get("base_z", 0.15)
    if party is None or len(party) != len(ext):
        party = [0] * len(ext)
    if U.signed_area(poly["ext"]) < 0:
        party = party[::-1]
    rings = [(ext, party)] + [(U.ccw(h)[::-1], [0] * len(h)) for h in poly.get("holes", [])]
    top = zb + f.top
    for ring, pflags in rings:
        n = len(ring)
        acc = 0.0
        for i in range(n):
            a, bb = ring[i], ring[(i + 1) % n]
            L = math.dist(a, bb)
            if L < 0.05:
                continue
            is_party = bool(pflags[i]) if i < len(pflags) else False
            if is_party or L < 2.2:
                # blank wall
                mb.face([(a[0], a[1], z0), (bb[0], bb[1], z0), (bb[0], bb[1], top), (a[0], a[1], top)],
                        f.wall, uvs=[(acc, z0), (acc + L, z0), (acc + L, top), (acc, top)])
                acc += L
                continue
            # ground floor
            gcols = bay_layout(L, f.bay * (1.0 if f.style != "modern" else 1.3),
                               f.win_w * (1.5 if f.shop else 1.0), 0.5)
            if f.shop and f.style != "lane":
                grows = [(zb + 0.25, zb + f.gf - 0.8)]
                gmat = "window_shop"
            else:
                grows = [(zb + 0.9, zb + 0.9 + f.gf * 0.55)]
                gmat = f.window
            if getattr(f, "arched_gf", False) and gcols:
                A.band_wall(mb, A.Edge(a, bb), z0, zb + f.gf, gcols, zb + 0.6, zb + f.gf - 0.45,
                            f.depth + 0.05, f.base, f.window, rnd, arch=True)
            else:
                window_wall(mb, a, bb, z0, zb + f.gf, grows if gcols else [], gcols, f.depth + 0.05,
                            f.base, gmat, f.base, rnd, uv_off=acc)
                # shop fascia signs and the odd awning on street-facing ground floors
                if f.shop and gcols and f.style in ("historic", "modern") and L > 4 and not getattr(f, "web", False):
                    _, (tx, ty), (nx, ny) = _edge_frame(a, bb)
                    hd = math.atan2(ty, tx)
                    smat = rnd.choice(["sign_black", "sign_black", "sign_gold", "sign_cream", "sign_red",
                                       "sign_green", "sign_blue"])
                    zs_ = zb + f.gf - 0.72
                    for (s0, s1) in gcols:
                        if rnd.random() < 0.7:
                            p0 = (a[0] + tx * (s0 - 0.1), a[1] + ty * (s0 - 0.1))
                            U.box(mb, 0, -0.14, 0, (s1 - s0) + 0.2, 0, 0.55, smat, origin=(p0[0], p0[1], zs_), h=hd)
                    if rnd.random() < 0.25:
                        amat = rnd.choice(["awning_red", "awning_green", "sign_black"])
                        for (s0, s1) in gcols:
                            p0 = (a[0] + tx * (s0 - 0.15), a[1] + ty * (s0 - 0.15))
                            q0 = U.xform((0, 0, zs_ - 0.15), (p0[0], p0[1], 0), hd)
                            q1 = U.xform(((s1 - s0) + 0.3, 0, zs_ - 0.15), (p0[0], p0[1], 0), hd)
                            q2 = U.xform(((s1 - s0) + 0.3, -1.1, zs_ - 0.75), (p0[0], p0[1], 0), hd)
                            q3 = U.xform((0, -1.1, zs_ - 0.75), (p0[0], p0[1], 0), hd)
                            mb.face([q0, q1, q2, q3], amat)
                            mb.face([q3, q2, q1, q0], amat)
            # upper floors
            if f.floors > 1:
                cols = bay_layout(L, f.bay, f.win_w, 0.6)
                rows = []
                for k in range(f.floors - 1):
                    fz = zb + f.gf + k * f.fh
                    wh = f.fh * f.win_h_frac
                    rows.append((fz + f.sill, min(fz + f.sill + wh, fz + f.fh - 0.35)))
                window_wall(mb, a, bb, zb + f.gf, top, rows if cols else [], cols, f.depth,
                            f.wall, f.window, f.wall, rnd, sill_mat=f.trim if f.style == "historic" else None,
                            uv_off=acc)
                # window sills / lintels for historic buildings
                if f.style == "historic" and cols and not getattr(f, "web", False):
                    _, (tx, ty), (nx, ny) = _edge_frame(a, bb)
                    for (zb_, zt_) in rows:
                        for (s0, s1) in cols:
                            for zz, hh, outd in ((zb_ - 0.12, 0.12, 0.12), (zt_, 0.18, 0.08)):
                                p0 = (a[0] + tx * (s0 - 0.12), a[1] + ty * (s0 - 0.12))
                                hd = math.atan2(ty, tx)
                                U.box(mb, 0, -outd, 0, (s1 - s0) + 0.24, 0, hh, f.trim,
                                      origin=(p0[0], p0[1], zz), h=hd)
                # wall-mounted air-conditioner units (a fixture of Shanghai facades)
                p_ac = {"modern": 0.3, "lane": 0.45, "historic": 0.08}.get(f.style, 0.0)
                if p_ac and cols and not getattr(f, "web", False):
                    _, (tx, ty), (nx, ny) = _edge_frame(a, bb)
                    hd = math.atan2(ty, tx)
                    for (zb_, zt_) in rows:
                        for (s0, s1) in cols:
                            if rnd.random() > p_ac:
                                continue
                            side = s1 + 0.25 if rnd.random() < 0.5 else s0 - 1.1
                            if side < 0.2 or side + 0.85 > L - 0.2:
                                continue
                            pa = (a[0] + tx * side, a[1] + ty * side)
                            zz = zb_ - 0.15 if rnd.random() < 0.6 else zb_ + 0.1
                            U.box(mb, 0, -0.34, 0, 0.82, 0, 0.55, rnd.choice(["concrete_white", "concrete_white", "metal_grey"]),
                                  origin=(pa[0], pa[1], zz), h=hd)
                            U.box(mb, 0.05, -0.36, -0.06, 0.77, -0.02, 0.0, "metal_dark", origin=(pa[0], pa[1], zz), h=hd)
                if getattr(f, "pilasters", False) and len(cols) >= 2:
                    e = A.Edge(a, bb)
                    zp = zb + f.gf
                    for (s0, s1), (t0, t1) in zip(cols[:-1], cols[1:]):
                        A.pilaster(mb, e, (s1 + t0) / 2, zp, top - zp - 0.9, 0.5, 0.14, f.trim)
            acc += L
        # roof slab
    if f.style == "lane":
        fill_top = zb + f.top
        U.fill(mb, ext, poly.get("holes", []), fill_top, "roof_flat")
        if len(ext) <= 6 and abs(U.signed_area(ext)) < 600:
            gable_roof(mb, ext, fill_top, 2.2, "roof_tile_grey", f.wall)
        return
    if f.style == "kiosk":
        over = U.offset_ring(ext, -0.8)
        U.prism(mb, over, [], top, top + 0.35, "concrete_white", "roof_flat")
        return
    U.fill(mb, ext, poly.get("holes", []), top, "roof_flat")
    if f.string_courses and f.floors > 2:
        _band(mb, ext, zb + f.gf - 0.05, 0.3, 0.12, f.trim)
    if f.cornice:
        cornice(mb, ext, top - 0.85, f.trim, scale=1.0)
    if f.parapet_h > 0 and abs(U.signed_area(ext)) > 30:
        parapet(mb, ext, top, f.parapet_h, 0.3, f.wall, f.trim)
    roof_stuff(mb, ext, top, rnd, big=f.style == "modern")


def build_massing(mb, poly, b, rnd, wall_mat, roof_mat="roof_flat"):
    """Lightweight building: walls with painted windows + flat roof."""
    ext = U.ccw(poly["ext"])
    z0 = b.get("min_h", 0.0) or -0.3
    top = b["h"] + (b.get("base_z") or 0.0)
    U.walls(mb, ext, z0, top, wall_mat)
    for h in poly.get("holes", []):
        U.walls(mb, U.ccw(h)[::-1], z0, top, wall_mat)
    U.fill(mb, ext, poly.get("holes", []), top, roof_mat)
    area = abs(U.signed_area(ext))
    if area > 200 and top < 120:
        parapet(mb, ext, top, 1.0, 0.3, wall_mat, "concrete_white")
    if area > 90:
        roof_stuff(mb, ext, top, rnd, per_area=220.0, max_n=5)


def build_all(sc, mats, root, quick=False, web=False):
    col_core = U.coll("Buildings_Bund_Core", root)
    col_back = U.coll("Buildings_Background", root)
    rnd = random.Random(1929)
    groups = {}
    count = 0
    for b in sc["buildings"]:
        if b.get("landmark") or b.get("style") == "override":
            continue
        reg = b["region"]
        if b.get("parts") and reg in ("far", "pudong"):
            continue  # handled by backdrop (building parts with heights)
        brnd = random.Random(zlib.crc32(b["id"].encode()))
        detailed = reg == "core" and not quick
        key = "core" if reg == "core" else ("pudong" if reg == "pudong" else "back")
        mb = groups.setdefault(key, U.MeshBuilder())
        for poly in b["poly"]:
            if detailed or (reg == "pudong" and b["style"] != "modern" and not quick):
                h = min(b["h"], 5.5) if b["style"] == "kiosk" else b["h"]
                f = Facade(brnd, b["style"], h, b["floors"] if b["style"] != "kiosk" else 1)
                f.web = web
                build_detailed(mb, poly, poly.get("party"), b, f, brnd)
            else:
                if b["style"] == "modern":
                    wall = brnd.choice(CURTAINS) if b["h"] > 50 and brnd.random() < 0.6 else brnd.choice(FAR_FACADES)
                else:
                    wall = "facade_hist_dist"
                build_massing(mb, poly, b, brnd, wall)
            count += 1
        # flush big groups into separate objects to keep meshes manageable
        if len(mb) > 400000:
            name = f"Buildings_{key}_{len([o for o in col_core.objects]) + len(col_back.objects)}"
            U.add_obj(name, mb.build(name, mats), col_core if key == "core" else col_back)
            groups[key] = U.MeshBuilder()
    for key, mb in groups.items():
        if len(mb):
            name = f"Buildings_{key}"
            U.add_obj(name, mb.build(name, mats), col_core if key == "core" else col_back)
    print(f"[facade] {count} footprints")
