"""Historic Bund buildings (万国建筑博览群).

Footprints come from OpenStreetMap; heights/floors from data/landmarks.json.
Facade compositions are reconstructions from public photos and descriptions
(base / order / attic, windows, domes, towers). The generic classical builder
handles most banks and offices; buildings with a unique silhouette (Custom
House clock tower, Sassoon House pyramid, Bank of China roof, Broadway
Mansions, signal tower, memorial) have their own functions.
"""
import math
import random
import zlib

from . import arch as A
from . import util as U
from .facade import _band, cornice, parapet


# --------------------------------------------------------------------------
# footprint analysis
# --------------------------------------------------------------------------

def simplify_ring(ring, party, ang_tol=9.0, min_len=0.8):
    """Drop nearly collinear vertices / tiny edges; carry party-wall flags."""
    pts = list(ring)
    flags = list(party) if party and len(party) == len(ring) else [0] * len(ring)
    changed = True
    while changed and len(pts) > 4:
        changed = False
        n = len(pts)
        for i in range(n):
            p0, p1, p2 = pts[i - 1], pts[i], pts[(i + 1) % n]
            a1 = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
            a2 = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
            turn = abs((a2 - a1 + math.pi) % (2 * math.pi) - math.pi)
            short = math.dist(p0, p1) < min_len or math.dist(p1, p2) < min_len
            if math.degrees(turn) < ang_tol or (short and math.degrees(turn) < 40):
                # merge edge (i-1 -> i) and (i -> i+1)
                f = 1 if (flags[i - 1] and flags[i]) else (flags[i - 1] if math.dist(p0, p1) > math.dist(p1, p2) else flags[i])
                del pts[i]
                flags[i - 1] = f
                del flags[i]
                changed = True
                break
    return pts, flags


class Ctx:
    def __init__(self, b, spec, sc, mb, rnd):
        self.b, self.spec, self.sc, self.mb, self.rnd = b, spec, sc, mb, rnd
        poly = max(b["poly"], key=lambda p: abs(U.signed_area(p["ext"])))
        self.poly = poly
        ring = U.ccw(poly["ext"])
        party = poly.get("party") or [0] * len(ring)
        if U.signed_area(poly["ext"]) < 0:
            party = party[::-1]
        self.ring, self.party = simplify_ring(ring, party)
        self.holes = [U.ccw(h)[::-1] for h in poly.get("holes", [])]
        self.z = b.get("base_z", 0.15) or 0.15
        self.cx, self.cy = U.centroid(self.ring)
        self.front_dir = self._front_dir()
        self.kinds = self._classify()

    def _front_dir(self):
        best = None
        for e in self.sc["water_edges"]:
            for p in e["pts"]:
                d = (p[0] - self.cx) ** 2 + (p[1] - self.cy) ** 2
                if best is None or d < best[0]:
                    best = (d, p)
        dx, dy = best[1][0] - self.cx, best[1][1] - self.cy
        L = math.hypot(dx, dy) or 1
        return dx / L, dy / L

    def _classify(self):
        kinds = []
        n = len(self.ring)
        dots = []
        for i in range(n):
            e = A.Edge(self.ring[i], self.ring[(i + 1) % n]) if math.dist(self.ring[i], self.ring[(i + 1) % n]) > 1e-3 else None
            dots.append((e.n[0] * self.front_dir[0] + e.n[1] * self.front_dir[1]) if e else -2)
        best = max(range(n), key=lambda i: dots[i] * min(1.0, math.dist(self.ring[i], self.ring[(i + 1) % n]) / 8.0))
        for i in range(n):
            if self.party[i]:
                kinds.append("party")
            elif i == best or (dots[i] > 0.75 and math.dist(self.ring[i], self.ring[(i + 1) % n]) > 6):
                kinds.append("front")
            elif dots[i] > -0.6:
                kinds.append("side")
            else:
                kinds.append("back")
        return kinds

    def edges(self):
        n = len(self.ring)
        for i in range(n):
            a, b = self.ring[i], self.ring[(i + 1) % n]
            if math.dist(a, b) < 0.3:
                continue
            yield i, A.Edge(a, b), self.kinds[i]

    def main_front(self):
        fr = [(e.L, e) for i, e, k in self.edges() if k == "front"]
        return max(fr, key=lambda t: t[0])[1] if fr else None


# --------------------------------------------------------------------------
# bays
# --------------------------------------------------------------------------

def bays_for(L, target, odd=True, margin=0.9):
    usable = L - 2 * margin
    if usable < 2.0:
        return []
    n = max(1, int(round(usable / target)))
    if odd and n % 2 == 0:
        n = n + 1 if abs(usable / (n + 1) - target) < abs(usable / max(n - 1, 1) - target) else max(1, n - 1)
    pitch = usable / n
    return [margin + pitch * (k + 0.5) for k in range(n)], pitch


def win_cols(centres, w):
    return [(c - w / 2, c + w / 2) for c in centres]


# --------------------------------------------------------------------------
# generic classical builder
# --------------------------------------------------------------------------

DEFAULT_WIN = {"type": "rect", "w": 1.45, "h": 0.6, "head": "flat", "surround": True}


def classical(c, spec):
    mb, rnd, z = c.mb, c.rnd, c.z
    mats = spec["mats"]
    wall, base, trim = mats["wall"], mats.get("base", mats["wall"]), mats.get("trim", "trim_light")
    glass = mats.get("glass", "window_hist_white")
    floors = spec["floors"]
    zs = [z]
    for h in floors:
        zs.append(zs[-1] + h)
    Hc = zs[-1]
    nbase = spec.get("base", 1)
    wins = spec.get("win", [])
    order = spec.get("order")
    depth = spec.get("depth", 0.35)
    bay_t = spec.get("bay", 4.0)
    for i, e, kind in c.edges():
        if kind == "party":
            mb.face([e.P(0, z - 0.3), e.P(e.L, z - 0.3), e.P(e.L, Hc), e.P(0, Hc)], wall)
            continue
        front = kind == "front"
        if e.L < 3.0:
            mb.face([e.P(0, z - 0.3), e.P(e.L, z - 0.3), e.P(e.L, Hc), e.P(0, Hc)], wall)
            continue
        lay = bays_for(e.L, bay_t if front else bay_t * 1.05, odd=front)
        if not lay:
            mb.face([e.P(0, z - 0.3), e.P(e.L, z - 0.3), e.P(e.L, Hc), e.P(0, Hc)], wall)
            continue
        centres, pitch = lay
        mid = len(centres) // 2
        # footing below grade
        mb.face([e.P(0, z - 0.3), e.P(e.L, z - 0.3), e.P(e.L, z), e.P(0, z)], base)
        for f in range(len(floors)):
            z0, z1 = zs[f], zs[f + 1]
            ws = dict(DEFAULT_WIN)
            if f < len(wins) and wins[f]:
                ws.update(wins[f])
            if not front and kind == "back":
                ws.update({"head": "flat", "surround": False})
            mat_w = base if f < nbase else wall
            if ws["type"] == "none":
                mb.face([e.P(0, z0), e.P(e.L, z0), e.P(e.L, z1), e.P(0, z1)], mat_w)
                continue
            w = min(ws["w"], pitch * 0.62)
            fh = z1 - z0
            if ws["type"] == "square":
                zb, zt = z0 + fh * 0.22, z0 + fh * 0.22 + min(w, fh * 0.6)
            else:
                zb = z0 + (0.25 if f == 0 and ws.get("shop") else min(1.0, fh * 0.2))
                zt = min(zb + fh * ws["h"] + (0.6 if ws["type"] == "arch" else 0.0), z1 - 0.45)
            cols = win_cols(centres, w)
            # main entrance on the front
            if front and f == 0 and spec.get("door", True):
                dw = min(pitch * 0.7, ws.get("door_w", 2.6))
                cols[mid] = (centres[mid] - dw / 2, centres[mid] + dw / 2)
            arch = ws["type"] == "arch"
            A.band_wall(mb, e, z0, z1, cols, zb, zt, depth, mat_w, glass if not (front and f == 0 and ws.get("shop")) else "window_shop",
                        rnd, arch=arch, uv_off=0.0)
            if ws.get("surround") and (front or kind == "side"):
                head = ws.get("head", "flat")
                for k, (s0, s1) in enumerate(cols):
                    hd = head
                    if head == "alt":
                        hd = "pediment" if k % 2 == 0 else "segment"
                    A.surround(mb, e, s0, s1, zb, zt, trim if mat_w != trim else wall, w=0.16, out=0.09,
                               head=hd, arch=arch, keystone=arch, sill=f > 0)
        # string course above the base
        if nbase > 0 and nbase < len(floors):
            e.box(mb, -0.02, e.L + 0.02, zs[nbase] - 0.05, zs[nbase] + 0.35, 0, 0.18, trim)
        # giant order on the front
        if order and (front or (kind == "side" and order.get("sides"))):
            _giant_order(c, e, centres, pitch, zs, order, trim, front)
    # main cornice & top
    ring = c.ring
    cornice(mb, ring, Hc - 0.9, trim, scale=spec.get("cornice", 1.1))
    top = Hc
    attic = spec.get("attic")
    if attic:
        # attic storey set back slightly, small square windows
        ar = U.offset_ring(ring, attic.get("setback", 0.4))
        az = top
        for i in range(len(ar)):
            e = A.Edge(ar[i], ar[(i + 1) % len(ar)])
            if e.L < 0.3:
                continue
            kind = c.kinds[i] if i < len(c.kinds) else "side"
            if kind == "party" or e.L < 3:
                mb.face([e.P(0, az), e.P(e.L, az), e.P(e.L, az + attic["h"]), e.P(0, az + attic["h"])], wall)
                continue
            lay = bays_for(e.L, bay_t, odd=kind == "front")
            if not lay:
                mb.face([e.P(0, az), e.P(e.L, az), e.P(e.L, az + attic["h"]), e.P(0, az + attic["h"])], wall)
                continue
            cen, pitch = lay
            ww = min(1.1, pitch * 0.5)
            A.band_wall(mb, e, az, az + attic["h"], win_cols(cen, ww), az + attic["h"] * 0.25,
                        az + attic["h"] * 0.25 + min(ww, attic["h"] * 0.55), 0.25, wall, glass, rnd)
        U.fill(mb, ar, [], az + attic["h"], "roof_flat")
        _band(mb, ar, az + attic["h"] - 0.35, 0.35, 0.25, trim)
        top = az + attic["h"]
        ring_top = ar
    else:
        U.fill(mb, ring, c.holes, top, "roof_flat")
        ring_top = ring
    # balustrade / parapet
    if spec.get("balustrade", True):
        for i in range(len(ring_top)):
            e = A.Edge(ring_top[i], ring_top[(i + 1) % len(ring_top)])
            if e.L < 1.0 or c.kinds[i % len(c.kinds)] == "party":
                continue
            A.balustrade(mb, e, 0.3, e.L - 0.3, top, trim, h=1.0, d0=-0.15)
    elif spec.get("parapet", True):
        parapet(mb, ring_top, top, 0.9, 0.35, wall, trim)
    # roof forms
    roof = spec.get("roof", "flat")
    if roof == "mansard":
        A.mansard(mb, U.offset_ring(ring_top, 0.6), top, spec.get("mansard_h", 3.5), 2.2, "roof_slate",
                  dormer_step=4.0, mat_dormer=trim, rnd=rnd)
    elif roof == "hip":
        A.hip_roof(mb, ring_top, top, spec.get("roof_h", 4.0), mats.get("roof", "roof_tile_red"))
    # central crown on the main front
    e = c.main_front()
    if e is not None:
        _crown(c, e, spec, top, Hc, trim, wall)
    return top


def _giant_order(c, e, centres, pitch, zs, order, trim, front):
    mb = c.mb
    f0, f1 = order["floors"]
    z0, z1 = zs[f0], zs[min(f1 + 1, len(zs) - 1)]
    h = z1 - z0
    zone = order.get("zone", "all")
    n = len(centres)
    mid = n // 2
    if zone == "center":
        k = order.get("bays", max(1, n // 3))
        lo, hi = max(0, mid - k // 2), min(n - 1, mid + k // 2)
    elif zone == "ends":
        lo, hi = 0, n - 1
    else:
        lo, hi = 0, n - 1
    # positions between bays
    pos = []
    for k in range(lo, hi + 2):
        s = centres[0] - pitch / 2 + k * pitch
        if 0.5 < s < e.L - 0.5:
            pos.append(s)
    if zone == "ends":
        pos = pos[:2] + pos[-2:]
    kind = order.get("kind", "pilaster")
    style = order.get("style", "ionic")
    if kind == "column":
        r = min(0.55, h / 20.0, pitch * 0.14)
        if order.get("paired"):
            pp = []
            for s in pos:
                pp += [s - r * 1.4, s + r * 1.4]
            pos = pp
        A.colonnade(mb, e, pos, z0, h, r, r * 1.8 + 0.2, trim, style)
        d_ent = r * 1.8 + 0.2 + r * 1.2
        A.entablature(mb, e, pos[0] - r * 1.5, pos[-1] + r * 1.5, z1, trim, h=1.4, out=d_ent)
        # soffit over the loggia
        e.box(mb, pos[0] - r * 1.5, pos[-1] + r * 1.5, z1 - 0.05, z1, 0, d_ent, trim)
    else:
        w = min(0.85, pitch * 0.18)
        for s in pos:
            A.pilaster(mb, e, s, z0, h, w, 0.22, trim, style)
        A.entablature(mb, e, pos[0] - w, pos[-1] + w, z1, trim, h=1.2, out=0.4)


def _crown(c, e, spec, top, Hc, trim, wall):
    mb = c.mb
    cr = spec.get("crown") or {}
    mid = e.L / 2
    if cr.get("pediment"):
        w = cr.get("pediment_w", min(e.L * 0.35, 14))
        A.pediment(mb, e, mid - w / 2, mid + w / 2, top + (1.0 if spec.get("balustrade", True) else 0.9),
                   cr.get("pediment_h", w * 0.22), 0.5, trim, segmental=cr.get("segmental", False))
    if cr.get("attic_center"):
        w, h = cr["attic_center"]
        e.box(mb, mid - w / 2, mid + w / 2, top, top + h, -4.0, 0.15, wall)
        e.box(mb, mid - w / 2 - 0.2, mid + w / 2 + 0.2, top + h - 0.4, top + h, -4.2, 0.4, trim)
        if cr.get("attic_pediment"):
            A.pediment(mb, e, mid - w / 2, mid + w / 2, top + h, w * 0.18, 0.4, trim,
                       segmental=cr.get("segmental", False))
    if cr.get("cupolas"):
        w, h = cr["cupolas"]
        inset = cr.get("cupola_inset", w * 0.8)
        for s in (inset, e.L - inset):
            p = e.P(s, 0, -w * 0.75)
            A.cupola(mb, p[0], p[1], top + 0.2, w, h, trim, cr.get("dome_mat", "roof_slate"))
    if cr.get("corner_tower"):
        side, w, h = cr["corner_tower"]
        spots = {"start": [w * 0.6], "end": [e.L - w * 0.6], "both": [w * 0.6, e.L - w * 0.6]}[side]
        for s in spots:
            p = e.P(s, 0, -w * 0.6)
            U.box(mb, -w / 2, -w / 2, 0, w / 2, w / 2, h, wall, origin=(p[0], p[1], top), h=e.h)
            ez = top + h
            U.box(mb, -w / 2 - 0.3, -w / 2 - 0.3, 0, w / 2 + 0.3, w / 2 + 0.3, 0.5, trim, origin=(p[0], p[1], ez), h=e.h)
            A.cupola(mb, p[0], p[1], ez + 0.5, w * 0.9, w * 1.5, trim, cr.get("dome_mat", "roof_slate"))
    if cr.get("end_domes"):
        # solid domes on square drums at both ends of the front (大北电报公司)
        R, drum = cr["end_domes"]
        for s in (R * 1.2, e.L - R * 1.2):
            p = e.P(s, 0, -R * 1.2)
            U.box(mb, -R * 1.1, -R * 1.1, 0, R * 1.1, R * 1.1, drum, wall, origin=(p[0], p[1], top), h=e.h)
            U.box(mb, -R * 1.2, -R * 1.2, drum - 0.4, R * 1.2, R * 1.2, drum, trim, origin=(p[0], p[1], top), h=e.h)
            A.dome(mb, p[0], p[1], top + drum, R, cr.get("dome_mat", "metal_black"), trim, drum_h=0.0,
                   lantern=True, profile="onion", n=24)
    if cr.get("front_gables"):
        n_g = cr["front_gables"]
        for k in range(n_g):
            sm = e.L * (k + 0.5) / n_g
            w = min(6.0, e.L / n_g * 0.8)
            mb.face([e.P(sm - w / 2, top), e.P(sm + w / 2, top), e.P(sm, top + w * 0.55)], wall)
            e.box(mb, sm - 0.5, sm + 0.5, top + 0.6, top + 0.6 + w * 0.25, -0.05, 0.02, c.spec.get("glass", "window_hist_white") if False else "window_hist_white")
            for sgn in (-1, 1):
                p0 = (sm + sgn * w / 2, top)
                p1 = (sm, top + w * 0.55)
                mb.face([e.P(p0[0], p0[1], 0.2), e.P(p1[0], p1[1], 0.2), e.P(p1[0], p1[1], -3.0),
                         e.P(p0[0], p0[1], -3.0)][::(1 if sgn < 0 else -1)], cr.get("gable_roof", "roof_tile_red"))
    if cr.get("hex_pavilion"):
        w, h = cr["hex_pavilion"]
        cx, cy = c.cx, c.cy
        U.lathe(mb, (cx, cy, top), [(w * 0.6, 0), (w * 0.6, h)], 6, wall, smooth=False)
        U.lathe(mb, (cx, cy, top + h), [(w * 0.68, 0), (w * 0.68, 0.4)], 6, trim, smooth=False)
        U.lathe(mb, (cx, cy, top + h + 0.4), [(w * 0.7, 0), (w * 0.35, h * 0.45), (0.0, h * 0.85)], 6,
                cr.get("dome_mat", "roof_tile_red"), smooth=False)
    if cr.get("dome"):
        R, drum = cr["dome"]
        p = e.P(mid, 0, -cr.get("dome_back", R + 4))
        A.dome(mb, p[0], p[1], top, R, cr.get("dome_mat", "granite_light"), trim, drum_h=drum, lantern=True,
               drum_cols=cr.get("drum_cols", 0), mat_col=trim)
    if cr.get("flag"):
        p = e.P(mid, 0, -2.0)
        A.flagpole(mb, p[0], p[1], top + (cr.get("flag_z", 0.0)), 8.0)


# --------------------------------------------------------------------------
# specs for the generic builder
# --------------------------------------------------------------------------

def _floors(H, n, gf=5.6, top_extra=0.0):
    rest = max(1, n - 1)
    fh = (H - gf - top_extra) / rest
    return [gf] + [fh] * rest


GRANITE = {"wall": "granite_light", "base": "rustic_light", "trim": "trim_light", "glass": "window_hist_white"}
WARM = {"wall": "granite_warm", "base": "rustic_warm", "trim": "trim_light", "glass": "window_hist_dark"}
WHITE = {"wall": "granite_white", "base": "rustic_white", "trim": "trim_light", "glass": "window_hist_white"}

SPECS = {
    "bund1_mcbain": dict(
        mats=GRANITE, floors=_floors(31.0, 7, 5.8), base=2, bay=3.9,
        win=[{"type": "arch", "w": 1.9, "h": 0.55, "shop": False}, {"type": "rect", "h": 0.55},
             {"head": "alt"}, {"head": "cornice"}, {"head": "flat"}, {"head": "cornice"}, {"type": "square"}],
        order=dict(kind="column", floors=(2, 4), zone="center", bays=3, style="ionic", paired=True),
        attic=dict(h=3.4, setback=0.3), crown=dict(pediment=True, segmental=True, pediment_w=11, flag=False)),
    "bund2_shanghai_club": dict(
        mats=WHITE, floors=_floors(26.5, 5, 5.6), base=2, bay=4.0,
        win=[{"type": "arch", "w": 1.9, "h": 0.6}, {"type": "rect", "h": 0.5}, {"head": "pediment"},
             {"head": "cornice"}, {"type": "square"}],
        order=dict(kind="column", floors=(2, 3), zone="center", bays=5, style="ionic"),
        attic=dict(h=3.6, setback=0.5), crown=dict(cupolas=(4.6, 6.5), cupola_inset=3.2, dome_mat="roof_slate")),
    "bund3_union": dict(
        mats=GRANITE, floors=_floors(26.0, 5, 5.6), base=2, bay=3.8,
        win=[{"type": "arch", "w": 1.8}, {"type": "rect", "h": 0.5}, {"head": "cornice"}, {}, {}],
        order=dict(kind="pilaster", floors=(2, 4), zone="all"),
        attic=dict(h=3.4), crown=dict(corner_tower=("end", 6.0, 6.5), dome_mat="roof_slate")),
    "bund5_nisshin": dict(
        mats=WARM, floors=_floors(24.0, 5, 5.4), base=1, bay=3.6,
        win=[{"type": "arch", "w": 1.9}, {}, {}, {}, {"head": "cornice"}],
        order=dict(kind="pilaster", floors=(1, 3), zone="center", bays=5),
        attic=dict(h=3.0), balustrade=False),
    "bund7_great_northern": dict(
        mats={"wall": "stucco_white", "base": "rustic_white", "trim": "trim_light", "glass": "window_hist_dark"},
        floors=_floors(19.5, 4, 5.4), base=1, bay=3.6,
        win=[{"type": "arch", "w": 1.8}, {"head": "pediment"}, {"head": "segment"}, {"type": "rect", "h": 0.5}],
        order=dict(kind="column", floors=(1, 3), zone="all", style="corinthian"),
        crown=dict(end_domes=(3.2, 2.2), dome_mat="metal_black")),
    "bund9_china_merchants": dict(
        mats={"wall": "brick_red_banded", "base": "brick_red_banded", "trim": "trim_light",
              "glass": "window_hist_white"},
        floors=[5.4, 5.0, 4.8], base=0, bay=3.5,
        win=[{"type": "arch", "w": 1.6}, {"type": "arch", "w": 1.4}, {"type": "arch", "w": 1.4}],
        order=dict(kind="column", floors=(1, 2), zone="all", style="ionic"),
        balustrade=True, crown=dict(pediment=True, pediment_w=9)),
    "bund12_hsbc": dict(
        mats=GRANITE, floors=[6.0, 3.6, 5.0, 4.6, 4.6], base=2, bay=4.3,
        win=[{"type": "arch", "w": 2.0, "h": 0.62}, {"type": "rect", "w": 1.5, "h": 0.5},
             {"head": "alt"}, {"head": "cornice"}, {"head": "flat"}],
        order=dict(kind="column", floors=(2, 4), zone="center", bays=5, style="ionic"),
        attic=dict(h=3.2, setback=0.4),
        crown=dict(attic_center=(24.0, 3.6), attic_pediment=True, dome=(11.5, 6.5), dome_back=13.0,
                   dome_mat="granite_grey", drum_cols=16, flag=True, flag_z=3.6)),
    "bund14_bank_of_communications": None,  # art deco builder
    "bund15_russo_chinese": dict(
        mats=WHITE, floors=[6.2, 5.8, 5.2], base=1, bay=4.0,
        win=[{"type": "arch", "w": 1.9}, {"head": "pediment", "h": 0.62}, {"head": "cornice"}],
        order=dict(kind="column", floors=(1, 1), zone="all", style="ionic", paired=True),
        attic=dict(h=2.6), crown=dict(pediment=False)),
    "bund15b_annex": dict(
        mats=WHITE, floors=_floors(17.0, 4, 5.0), base=1, bay=3.8, win=[{"type": "arch"}, {}, {}, {}],
        balustrade=True),
    "bund16_bank_of_taiwan": dict(
        mats=GRANITE, floors=[6.0, 5.6, 5.4, 4.0], base=1, bay=4.2,
        win=[{"type": "rect", "w": 1.9, "h": 0.6}, {"h": 0.62}, {"h": 0.6}, {"type": "square"}],
        order=dict(kind="column", floors=(1, 2), zone="center", bays=3, style="corinthian")),
    "bund17_ncdn": dict(
        mats=GRANITE, floors=_floors(34.5, 9, 5.6), base=2, bay=3.6,
        win=[{"type": "arch", "w": 1.8}, {"type": "arch", "w": 1.4}, {}, {}, {}, {"head": "cornice"},
             {}, {"type": "rect", "h": 0.62}, {"type": "rect", "h": 0.62}],
        order=dict(kind="column", floors=(7, 8), zone="all", style="ionic"),
        attic=None, crown=dict(corner_tower=("both", 5.0, 4.4), flag=True)),
    "bund18_chartered": dict(
        mats=GRANITE, floors=[6.0, 4.8, 4.8, 4.8, 4.4], base=1, bay=4.0,
        win=[{"type": "arch", "w": 2.0}, {"head": "pediment"}, {"head": "cornice"}, {}, {"type": "square"}],
        order=dict(kind="column", floors=(1, 3), zone="center", bays=1, style="ionic"),
        attic=dict(h=3.0)),
    "bund24_yokohama": dict(
        mats=GRANITE, floors=_floors(28.5, 6, 5.8), base=2, bay=4.0,
        win=[{"type": "arch", "w": 2.0}, {"type": "rect", "h": 0.5}, {"head": "cornice"}, {}, {},
             {"type": "square"}],
        order=dict(kind="column", floors=(2, 4), zone="center", bays=3, style="ionic"),
        attic=dict(h=3.4), crown=dict(flag=True)),
    "bund26_yangtze": dict(
        mats=GRANITE, floors=_floors(26.0, 6, 5.4), base=2, bay=3.6,
        win=[{"type": "arch", "w": 1.8}, {}, {"head": "pediment"}, {"head": "cornice"}, {}, {"h": 0.62}],
        order=dict(kind="column", floors=(5, 5), zone="center", bays=3, style="ionic", paired=True),
        roof="mansard", mansard_h=3.8, balustrade=False),
    "bund27_jardine": dict(
        mats=GRANITE, floors=_floors(28.5, 6, 5.8), base=2, bay=4.0,
        win=[{"type": "arch", "w": 2.0}, {"type": "arch", "w": 1.6}, {"head": "alt"}, {"head": "cornice"},
             {}, {"type": "square"}],
        order=dict(kind="column", floors=(2, 4), zone="center", bays=3, style="corinthian"),
        attic=dict(h=3.4), crown=dict(flag=True)),
    "bund28_glen_line": dict(
        mats=GRANITE, floors=_floors(28.5, 7, 5.6), base=2, bay=3.7,
        win=[{"type": "arch", "w": 1.8}, {}, {"head": "cornice"}, {}, {}, {}, {"type": "square"}],
        order=dict(kind="column", floors=(0, 0), zone="center", bays=1, style="doric", paired=True),
        attic=dict(h=3.4), crown=dict(corner_tower=("start", 5.0, 6.5))),
    "bund29_indochine": dict(
        mats=GRANITE, floors=[6.4, 5.8, 5.4], base=1, bay=4.0,
        win=[{"type": "arch", "w": 2.0}, {"head": "pediment", "h": 0.62}, {"head": "cornice"}],
        order=dict(kind="column", floors=(1, 2), zone="center", bays=1, style="ionic"),
        attic=dict(h=2.6), crown=dict(pediment=True, segmental=True, pediment_w=10)),
    "astor_house": dict(
        mats={"wall": "brick_grey", "base": "rustic_grey", "trim": "trim_light", "glass": "window_hist_white"},
        floors=_floors(24.5, 6, 5.0), base=1, bay=3.6,
        win=[{"type": "arch", "w": 1.8}, {"head": "cornice"}, {"head": "cornice"}, {}, {}, {}],
        balustrade=True),
    "russian_consulate": dict(
        mats={"wall": "stucco_grey", "base": "rustic_grey", "trim": "trim_light", "glass": "window_hist_white",
              "roof": "roof_tile_red"},
        floors=_floors(16.0, 4, 4.6), base=1, bay=3.6,
        win=[{"type": "arch", "w": 1.6}, {"head": "pediment"}, {}, {"type": "square"}],
        balustrade=False, roof="hip", roof_h=5.0, crown=dict(hex_pavilion=(4.2, 4.0), dome_mat="roof_tile_red")),
}


# --------------------------------------------------------------------------
# custom builders
# --------------------------------------------------------------------------

def vertical_piers(c, H, floors_n, gf, mat, mat_spandrel, glass, pier_w=0.55, pier_out=0.3, bay=2.8,
                   rnd=None, kinds_skip=("party",), ring=None, z=None, cap=True, base_mat=None):
    """Art Deco facade: continuous piers with recessed windows + spandrels."""
    mb = c.mb
    rnd = rnd or c.rnd
    ring = ring or c.ring
    z = c.z if z is None else z
    fh = (H - gf) / max(1, floors_n - 1)
    for i in range(len(ring)):
        a, b = ring[i], ring[(i + 1) % len(ring)]
        if math.dist(a, b) < 0.3:
            continue
        e = A.Edge(a, b)
        kind = c.kinds[i] if (ring is c.ring and i < len(c.kinds)) else "side"
        if kind in kinds_skip or e.L < 2.5:
            mb.face([e.P(0, z - 0.3), e.P(e.L, z - 0.3), e.P(e.L, z + H), e.P(0, z + H)], mat)
            continue
        lay = bays_for(e.L, bay, odd=False, margin=0.6)
        if not lay:
            mb.face([e.P(0, z - 0.3), e.P(e.L, z - 0.3), e.P(e.L, z + H), e.P(0, z + H)], mat)
            continue
        cen, pitch = lay
        w = pitch - pier_w
        cols = win_cols(cen, w)
        # ground floor: large openings
        A.band_wall(mb, e, z - 0.3, z + gf, win_cols(cen, w * 0.95), z + 0.3, z + gf - 0.9, 0.4,
                    base_mat or mat, "window_shop", rnd)
        for f in range(floors_n - 1):
            z0 = z + gf + f * fh
            z1 = z0 + fh
            A.band_wall(mb, e, z0, z1, cols, z0 + fh * 0.28, z1 - 0.15, 0.32, mat, glass, rnd)
            # spandrel panels (slightly recessed, darker)
            for s0, s1 in cols:
                e.box(mb, s0, s1, z0 - 0.15, z0 + fh * 0.28, -0.2, -0.05, mat_spandrel, faces=("front",))
        for k in range(len(cen) + 1):
            s = cen[0] - pitch / 2 + k * pitch if k < len(cen) else cen[-1] + pitch / 2
            s = min(max(s, pier_w / 2), e.L - pier_w / 2)
            e.box(mb, s - pier_w / 2, s + pier_w / 2, z + gf, z + H + (0.6 if cap else 0), 0, pier_out, mat)
        e.box(mb, -0.05, e.L + 0.05, z + gf - 0.2, z + gf + 0.3, 0, pier_out + 0.1, mat)


def customs(c):
    """江海关大楼: 8-storey east block, Doric portico, clock tower."""
    mb, z = c.mb, c.z
    spec = dict(mats=GRANITE, floors=[5.4, 4.6, 4.6, 4.3, 4.3, 4.3, 4.3, 4.2], base=3, bay=3.6,
                win=[{"type": "rect", "w": 1.6, "h": 0.6}, {"h": 0.5}, {"h": 0.5}, {}, {}, {}, {}, {"type": "square"}],
                order=dict(kind="column", floors=(0, 2), zone="center", bays=3, style="doric"),
                balustrade=False, cornice=1.0)
    top = classical(c, spec)
    e = c.main_front()
    # clock tower centred on the east front, set back from the facade
    tw = min(13.5, e.L * 0.36)
    pc = e.P(e.L / 2, 0, -(tw / 2 + 1.2))
    hd = e.h
    tz = top
    stages = [  # (height, width scale, kind)
        (12.0, 1.0, "shaft"),
        (9.0, 0.96, "clock"),
        (6.5, 0.86, "belfry"),
        (4.5, 0.7, "step"),
        (3.5, 0.5, "step"),
    ]
    wmat, trim = "granite_light", "trim_light"
    for h, sc_, kind in stages:
        w = tw * sc_
        ring = [U.xform((x, y, 0), (pc[0], pc[1], 0), hd)[:2] for x, y in
                ((-w / 2, -w / 2), (w / 2, -w / 2), (w / 2, w / 2), (-w / 2, w / 2))]
        for i in range(4):
            ee = A.Edge(ring[i], ring[(i + 1) % 4])
            if kind == "shaft":
                cols = [(ee.L / 2 - 2.6, ee.L / 2 - 1.2), (ee.L / 2 + 1.2, ee.L / 2 + 2.6)]
                A.band_wall(mb, ee, tz, tz + h, cols, tz + 1.5, tz + h - 1.5, 0.4, wmat, "window_hist_dark", c.rnd)
                ee.box(mb, -0.3, 0.9, tz, tz + h, 0, 0.4, wmat)
                ee.box(mb, ee.L - 0.9, ee.L + 0.3, tz, tz + h, 0, 0.4, wmat)
            elif kind == "clock":
                mb.face([ee.P(0, tz), ee.P(ee.L, tz), ee.P(ee.L, tz + h), ee.P(0, tz + h)], wmat)
                _clock_face(mb, ee, tz + h * 0.52, 2.7)
                ee.box(mb, -0.3, 0.8, tz, tz + h, 0, 0.35, wmat)
                ee.box(mb, ee.L - 0.8, ee.L + 0.3, tz, tz + h, 0, 0.35, wmat)
            elif kind == "belfry":
                cols = [(ee.L / 2 - 2.4, ee.L / 2 - 0.8), (ee.L / 2 + 0.8, ee.L / 2 + 2.4)]
                A.band_wall(mb, ee, tz, tz + h, cols, tz + 0.8, tz + h - 0.8, 0.6, wmat, "window_hist_dark", c.rnd,
                            arch=True)
            else:
                mb.face([ee.P(0, tz), ee.P(ee.L, tz), ee.P(ee.L, tz + h), ee.P(0, tz + h)], wmat)
        _band(mb, ring, tz + h - 0.45, 0.45, 0.35, trim)
        U.fill(mb, ring, [], tz + h, "roof_flat")
        tz += h
    # stepped cap and finial up to the documented 79.2 m
    target = c.z + c.spec.get("tower_top", 79.2) - 0.15
    cap_h = max(1.0, target - tz - 3.0)
    U.lathe(mb, (pc[0], pc[1], tz), [(tw * 0.18, 0), (tw * 0.14, cap_h * 0.6), (0.4, cap_h), (0.0, cap_h + 0.2)],
            4, "granite_light", h0=hd + math.pi / 4, smooth=False)
    A.flagpole(mb, pc[0], pc[1], tz + cap_h, max(2.0, target - tz - cap_h), flag=True)


def _clock_face(mb, e, zc, r):
    """Big clock dial (the Custom House clock is the largest in Asia)."""
    s = e.L / 2
    n = 32
    rim = []
    for k in range(n):
        a = 2 * math.pi * k / n
        rim.append((s + r * math.cos(a), zc + r * math.sin(a)))
    mb.face([e.P(x, y, 0.12) for x, y in rim], "concrete_white")
    for k in range(n):
        a0 = 2 * math.pi * k / n
        a1 = 2 * math.pi * (k + 1) / n
        mb.face([e.P(s + r * math.cos(a0), zc + r * math.sin(a0), 0.0), e.P(s + r * math.cos(a1), zc + r * math.sin(a1), 0.0),
                 e.P(s + r * math.cos(a1), zc + r * math.sin(a1), 0.2), e.P(s + r * math.cos(a0), zc + r * math.sin(a0), 0.2)][::-1],
                "gold")
    for k in range(12):
        a = 2 * math.pi * k / 12
        x, y = s + (r - 0.35) * math.cos(a), zc + (r - 0.35) * math.sin(a)
        e.box(mb, x - 0.08, x + 0.08, y - 0.25, y + 0.25, 0.12, 0.16, "metal_black")
    # hands at ~09:30
    for ang, ln, w in ((math.radians(90 - 285), r * 0.62, 0.14), (math.radians(90 - 180), r * 0.85, 0.09)):
        x1, y1 = s + ln * math.cos(ang), zc + ln * math.sin(ang)
        nx, ny = -math.sin(ang) * w, math.cos(ang) * w
        mb.face([e.P(s + nx, zc + ny, 0.2), e.P(s - nx, zc - ny, 0.2), e.P(x1 - nx, y1 - ny, 0.2), e.P(x1 + nx, y1 + ny, 0.2)],
                "metal_black")


def sassoon(c):
    """沙逊大厦: 10-storey block, 13-storey east tower, 19 m green copper pyramid (77 m)."""
    mb, z = c.mb, c.z
    H_main = 40.0
    vertical_piers(c, H_main, 10, 6.0, "granite_warm", "granite_grey", "window_hist_dark", bay=2.9)
    U.fill(mb, c.ring, c.holes, z + H_main, "roof_flat")
    _band(mb, c.ring, z + H_main - 0.6, 0.6, 0.35, "trim_light")
    parapet(mb, c.ring, z + H_main, 1.2, 0.4, "granite_warm", "trim_light")
    for h in c.holes:
        U.walls(mb, h, z, z + H_main, "granite_warm")
    # tower at the east end (Bund frontage)
    e = c.main_front()
    tw = min(19.0, e.L * 0.5)
    td = 18.0
    s0 = e.L / 2 - tw / 2
    hd = e.h
    ring = [e.P(s0, 0, 0)[:2], e.P(s0, 0, -td)[:2], e.P(s0 + tw, 0, -td)[:2], e.P(s0 + tw, 0, 0)[:2]]
    ring = U.ccw(ring)
    t_top = 57.0
    kinds_backup = c.kinds
    c.kinds = ["side"] * 4
    vertical_piers(c, t_top - H_main, 4, 0.01, "granite_warm", "granite_grey", "window_hist_dark", bay=2.6,
                   ring=ring, z=z + H_main, cap=False)
    c.kinds = kinds_backup
    _band(mb, ring, z + t_top - 0.8, 0.8, 0.45, "trim_light")
    U.fill(mb, ring, [], z + t_top, "roof_flat")
    # stepped base of the pyramid then the copper pyramid
    inner = U.offset_ring(ring, 0.5)
    U.walls(mb, inner, z + t_top, z + t_top + 1.0, "granite_warm")
    A.pyramid_roof(mb, inner, z + t_top + 1.0, 19.0, "copper_patina")
    cx, cy = U.centroid(inner)
    U.cylinder(mb, (cx, cy, z + t_top + 19.5), 0.08, 1.5, 6, "copper_patina")


def boc(c):
    """中国银行大楼: 15 floors (227 ft), golden granite, blue glazed Chinese pyramid roof."""
    mb, z = c.mb, c.z
    H = 56.0
    vertical_piers(c, H, 14, 6.5, "granite_golden", "granite_warm", "window_hist_dark", bay=2.6, pier_w=0.7)
    _band(mb, c.ring, z + H - 0.6, 0.6, 0.3, "granite_golden")
    U.fill(mb, c.ring, c.holes, z + H, "roof_flat")
    # stepped crown: two setbacks with Chinese lattice frieze
    r1 = U.offset_ring(c.ring, 1.4)
    c.kinds, kb = ["side"] * len(r1), c.kinds
    vertical_piers(c, 4.2, 2, 0.01, "granite_golden", "granite_warm", "window_hist_dark", bay=2.4, ring=r1,
                   z=z + H, cap=False)
    c.kinds = kb
    U.fill(mb, r1, [], z + H + 4.2, "roof_flat")
    # glazed pyramid roof with eaves (overhang) up to 69.2 m
    top_target = c.z + 69.2 - 0.15
    roof_h = top_target - (z + H + 4.2) - 0.8
    A.pyramid_roof(mb, r1, z + H + 4.2, roof_h, "glazed_tile_blue", overhang=1.6, eave_curve=0.5)
    cx, cy = U.centroid(r1)
    U.lathe(mb, (cx, cy, z + H + 4.2 + roof_h - 0.2), [(0.5, 0), (0.6, 0.4), (0.25, 0.8), (0.0, 1.2)], 8,
            "granite_golden")
    # bracket band (dougong) under the eaves
    _band(mb, r1, z + H + 3.4, 0.8, 0.9, "granite_warm")


def artdeco(c, H, floors, mat="granite_light", center_rise=6.0, flag=True, base_mat=None):
    """交通银行 / 半岛酒店: vertical piers with a raised centre."""
    mb, z = c.mb, c.z
    vertical_piers(c, H, floors, 6.0, mat, "granite_grey", "window_hist_dark", bay=2.8, base_mat=base_mat)
    U.fill(mb, c.ring, c.holes, z + H, "roof_flat")
    parapet(mb, c.ring, z + H, 1.0, 0.4, mat, "trim_light")
    e = c.main_front()
    if e is not None and center_rise > 0:
        w = min(12.0, e.L * 0.4)
        s0 = e.L / 2 - w / 2
        ring = U.ccw([e.P(s0, 0, 0)[:2], e.P(s0, 0, -10)[:2], e.P(s0 + w, 0, -10)[:2], e.P(s0 + w, 0, 0)[:2]])
        c.kinds, kb = ["side"] * 4, c.kinds
        vertical_piers(c, center_rise, 2, 0.01, mat, "granite_grey", "window_hist_dark", bay=2.4, ring=ring,
                       z=z + H, cap=True)
        c.kinds = kb
        U.fill(mb, ring, [], z + H + center_rise + 0.6, "roof_flat")
        if flag:
            cx, cy = U.centroid(ring)
            A.flagpole(mb, cx, cy, z + H + center_rise + 0.6, 7.0)


def peninsula(c):
    """半岛酒店 (2009): 10-storey Bund facade stepping back to 15 floors."""
    mb, z = c.mb, c.z
    H1 = 38.0
    vertical_piers(c, H1, 10, 6.2, "granite_warm", "granite_grey", "window_hist_dark", bay=2.8)
    U.fill(mb, c.ring, c.holes, z + H1, "paving_deck")
    ring = U.offset_ring(c.ring, 4.0)
    for k, (dz, ins) in enumerate(((3.6, 4.0), (3.6, 7.0), (3.6, 10.0), (3.6, 12.5), (3.6, 15.0))):
        r = U.offset_ring(c.ring, ins)
        if abs(U.signed_area(r)) < 60 or U.signed_area(r) <= 0:
            break
        zb = z + H1 + 3.6 * k
        kb = c.kinds
        c.kinds = ["side"] * len(r)
        vertical_piers(c, dz, 2, 0.01, "granite_warm", "granite_grey", "window_modern", bay=2.6, ring=r, z=zb,
                       cap=False)
        c.kinds = kb
        U.fill(mb, r, [], zb + dz, "paving_deck")
        parapet(mb, r, zb + dz, 1.1, 0.25, "granite_warm", "trim_light")
    A.flagpole(mb, c.cx, c.cy, z + 62.0 - 6.0, 6.0, flag=False)


def broadway(c):
    """上海大厦 (Broadway Mansions, 1934): stepped brick Art Deco, 78 m."""
    mb, z = c.mb, c.z
    tiers = [(0.0, 41.0), (3.5, 52.0), (7.0, 62.0), (10.5, 70.0), (14.0, 76.5)]
    prev = 0.0
    for k, (ins, ztop) in enumerate(tiers):
        r = c.ring if ins == 0 else U.offset_ring(c.ring, ins)
        if U.signed_area(r) < 40:
            break
        h = ztop - prev
        kb = c.kinds
        if ins > 0:
            c.kinds = ["side"] * len(r)
        vertical_piers(c, h, max(2, int(h / 3.4)), 5.6 if k == 0 else 0.01, "brick_brown", "brick_brown",
                       "window_hist_white", bay=2.5, pier_w=0.6, ring=r, z=z + prev, cap=False)
        c.kinds = kb
        U.fill(mb, r, [], z + ztop, "roof_flat")
        _band(mb, r, z + ztop - 0.5, 0.5, 0.25, "brick_cream")
        prev = ztop
    U.cylinder(mb, (c.cx, c.cy, z + prev), 0.1, 2.5, 6, "metal_grey")


def gothic_bank(c):
    """中国通商银行 (外滩6号, 1897): Gothic revival, steep roof with gables."""
    mb, z = c.mb, c.z
    floors = [5.0, 4.4, 4.4]
    spec = dict(mats={"wall": "granite_white", "base": "rustic_white", "trim": "trim_light",
                      "glass": "window_hist_dark"},
                floors=floors, base=1, bay=3.4,
                win=[{"type": "arch", "w": 1.6}, {"type": "arch", "w": 1.3}, {"type": "arch", "w": 1.2}],
                balustrade=False, cornice=0.7)
    top = classical(c, spec)
    # steep roof
    hd, (u0, u1, v0, v1) = A.hip_roof(mb, c.ring, top, 7.5, "roof_slate", overhang=0.3)
    e = c.main_front()
    if e:
        n_g = 5
        for k in range(n_g):
            s = e.L * (k + 0.5) / n_g
            w = min(5.2, e.L / n_g * 0.92)
            # front gable with a pointed window
            pts = [e.P(s - w / 2, top), e.P(s + w / 2, top), e.P(s, top + 6.0)]
            mb.face(pts, "granite_white")
            U.cylinder(mb, e.P(s, top + 6.0, 0.1), 0.18, 1.6, 6, "trim_light", r_top=0.02)
            e.box(mb, s - 0.8, s + 0.8, top + 0.6, top + 3.6, 0.0, 0.1, "window_hist_dark")
            for sgn in (-1, 1):
                p0 = (s + sgn * w / 2, top)
                p1 = (s, top + 6.0)
                mb.face([e.P(p0[0], p0[1], 0.15), e.P(p1[0], p1[1], 0.15), e.P(p1[0], p1[1], -4.0),
                         e.P(p0[0], p0[1], -4.0)][::(1 if sgn < 0 else -1)], "roof_slate")


def palace_hotel(c):
    """汇中饭店 (1908): red brick with white bands, rooftop pavilions."""
    spec = dict(mats={"wall": "brick_red_banded", "base": "rustic_white", "trim": "trim_light",
                      "glass": "window_hist_white"},
                floors=_floors(27.5, 6, 5.5), base=1, bay=3.6,
                win=[{"type": "arch", "w": 1.9}, {"head": "cornice"}, {"head": "cornice"}, {}, {}, {"type": "arch", "w": 1.3}],
                balustrade=True, crown=dict(cupolas=(4.0, 6.0), cupola_inset=2.5, dome_mat="roof_tile_red"))
    classical(c, spec)


def consulate(c):
    """原英国领事馆 (1873): two-storey arcaded verandas, hipped roof."""
    mb, z = c.mb, c.z
    spec = dict(mats={"wall": "stucco_cream", "base": "stucco_cream", "trim": "trim_light",
                      "glass": "window_hist_dark"},
                floors=[5.2, 5.0], base=0, bay=3.3,
                win=[{"type": "arch", "w": 2.2, "h": 0.6, "surround": True}, {"type": "arch", "w": 2.0, "h": 0.6}],
                balustrade=False, cornice=0.7, door=True)
    top = classical(c, spec)
    A.hip_roof(mb, c.ring, top, 4.5, "roof_tile_red", overhang=0.8)


def signal_tower(c):
    """外滩信号台 (Gutzlaff Signal Tower, 1907): 36.8 m round tower, mast to 49.8 m."""
    mb, z = c.mb, c.z
    # base pavilion from the footprint
    U.prism(mb, c.ring, [], z - 0.3, z + 7.5, "brick_red_banded", "roof_flat")
    cornice(mb, c.ring, z + 6.8, "trim_light", 0.6)
    cx, cy = c.cx, c.cy
    r = 2.7
    H = 36.8
    U.lathe(mb, (cx, cy, z), [(r * 1.25, 0), (r * 1.25, 4.0), (r, 4.6)], 20, "granite_grey", smooth=False)
    U.cylinder(mb, (cx, cy, z + 4.6), r, H - 9.0, 24, "brick_red_banded", r_top=r * 0.9, smooth=True)
    zt = z + H - 4.4
    U.lathe(mb, (cx, cy, zt), [(r * 0.9, 0), (r * 1.55, 0.6), (r * 1.55, 0.9), (r * 0.95, 1.0)], 24, "trim_light", smooth=False)
    # gallery railing
    for k in range(24):
        a = 2 * math.pi * k / 24
        U.box(mb, -0.03, -0.03, 0, 0.03, 0.03, 1.0, "metal_dark", origin=(cx + math.cos(a) * r * 1.5, cy + math.sin(a) * r * 1.5, zt + 1.0))
    U.lathe(mb, (cx, cy, zt + 1.0), [(r * 1.5, 0.95), (r * 1.52, 1.05)], 24, "metal_dark", cap_top=False)
    U.cylinder(mb, (cx, cy, zt + 1.0), r * 0.75, 3.4, 16, "trim_light")
    U.lathe(mb, (cx, cy, zt + 4.4), [(r * 0.85, 0), (r * 0.3, 1.2), (0.0, 1.6)], 16, "copper_patina")
    # signal mast with yard
    mz = zt + 5.6
    U.cylinder(mb, (cx, cy, mz), 0.16, 49.8 - (mz - z), 8, "metal_dark", r_top=0.07)
    for yz, yl in ((mz + 6.0, 6.0), (mz + 9.5, 4.0)):
        U.box(mb, -yl / 2, -0.06, -0.06, yl / 2, 0.06, 0.06, "metal_dark", origin=(cx, cy, yz))


def monument(c):
    """人民英雄纪念塔 (1994): three 24 m shafts leaning together like rifles."""
    mb, z = c.mb, c.z
    cx, cy = c.cx, c.cy
    pts = []
    for p in c.b["poly"]:
        pts += p["ext"]
    H = 24.0
    # three shafts based on the tri-radial footprint
    for k in range(3):
        a = math.radians(90 + 120 * k)
        bx, by = cx + math.cos(a) * 6.5, cy + math.sin(a) * 6.5
        tx, ty = cx + math.cos(a) * 0.9, cy + math.sin(a) * 0.9
        w0, w1 = 2.6, 0.9
        d0, d1 = 1.6, 0.6
        ux, uy = math.cos(a + math.pi / 2), math.sin(a + math.pi / 2)
        rx, ry = math.cos(a), math.sin(a)
        bot = [(bx + ux * w0 / 2 + rx * d0 / 2, by + uy * w0 / 2 + ry * d0 / 2, z),
               (bx - ux * w0 / 2 + rx * d0 / 2, by - uy * w0 / 2 + ry * d0 / 2, z),
               (bx - ux * w0 / 2 - rx * d0 / 2, by - uy * w0 / 2 - ry * d0 / 2, z),
               (bx + ux * w0 / 2 - rx * d0 / 2, by + uy * w0 / 2 - ry * d0 / 2, z)]
        top = [(tx + ux * w1 / 2 + rx * d1 / 2, ty + uy * w1 / 2 + ry * d1 / 2, z + H),
               (tx - ux * w1 / 2 + rx * d1 / 2, ty - uy * w1 / 2 + ry * d1 / 2, z + H),
               (tx - ux * w1 / 2 - rx * d1 / 2, ty - uy * w1 / 2 - ry * d1 / 2, z + H),
               (tx + ux * w1 / 2 - rx * d1 / 2, ty + uy * w1 / 2 - ry * d1 / 2, z + H - 1.2)]
        for i in range(4):
            j = (i + 1) % 4
            mb.face([bot[i], bot[j], top[j], top[i]][::-1], "concrete_white")
        mb.face(top, "concrete_white")
    # stepped circular podium
    for k, (r, h) in enumerate(((11.0, 0.5), (9.0, 1.0), (7.5, 1.5))):
        U.cylinder(mb, (cx, cy, z - 0.3), r, h + 0.3, 40, "granite_light", smooth=False)


# --------------------------------------------------------------------------
# researched non-landmark buildings (data/building_overrides.json)
# --------------------------------------------------------------------------

RUSTIC_FOR = {"granite_light": "rustic_light", "granite_warm": "rustic_warm", "granite_grey": "rustic_grey",
              "granite_golden": "rustic_golden", "granite_white": "rustic_white", "stucco_cream": "rustic_warm",
              "stucco_white": "rustic_white", "stucco_grey": "rustic_grey", "brick_red": "rustic_warm",
              "brick_brown": "rustic_grey"}


def ov_classical(c):
    b = c.b
    ov = b.get("ov") or {}
    wall = ov.get("material", "granite_light")
    n = max(2, b["floors"])
    H = b["h"] - 1.2
    spec = dict(mats={"wall": wall, "base": RUSTIC_FOR.get(wall, wall), "trim": "trim_light",
                      "glass": c.rnd.choice(["window_hist_white", "window_hist_dark"])},
                floors=_floors(H, n, 5.2 if n > 2 else 4.6), base=1, bay=c.rnd.uniform(3.5, 4.1),
                win=[{"type": "arch" if c.rnd.random() < 0.5 else "rect", "w": 1.8}] + [{"head": "cornice"}] * 2 + [{}] * 8,
                order=dict(kind="pilaster", floors=(1, n - 1), zone="all") if c.rnd.random() < 0.5 and n > 3 else None,
                balustrade=c.rnd.random() < 0.4)
    classical(c, spec)


def ov_queen_anne(c):
    b = c.b
    n = max(2, b["floors"])
    H = b["h"] - 1.0
    spec = dict(mats={"wall": "brick_red_banded", "base": "brick_red_banded", "trim": "trim_light",
                      "glass": "window_hist_white", "roof": "roof_tile_grey"},
                floors=_floors(H, n, 4.8), base=0, bay=3.3,
                win=[{"type": "arch", "w": 1.6}, {"head": "cornice"}, {"head": "pediment"}] + [{}] * 6,
                balustrade=False, parapet=False, cornice=0.7, roof="hip", roof_h=4.0,
                crown=dict(front_gables=2, gable_roof="roof_tile_grey"))
    classical(c, spec)


def ov_artdeco(c, brick):
    mb, z = c.mb, c.z
    b = c.b
    ov = b.get("ov") or {}
    mat = ov.get("material", "brick_brown" if brick else "granite_light")
    n = max(3, b["floors"])
    H = b["h"] - 1.0
    sb = ov.get("setback_floor")
    if sb and sb < n:
        fh = (H - 5.4) / (n - 1)
        H1 = 5.4 + fh * (sb - 1)
        vertical_piers(c, H1, sb, 5.4, mat, mat, "window_hist_white" if brick else "window_hist_dark", bay=2.6)
        U.fill(mb, c.ring, c.holes, z + H1, "roof_flat")
        parapet(mb, c.ring, z + H1, 1.1, 0.3, mat, "trim_light")
        r = U.offset_ring(c.ring, 3.0)
        if U.signed_area(r) > 40:
            kb = c.kinds
            c.kinds = ["side"] * len(r)
            vertical_piers(c, H - H1, n - sb, 0.01, mat, mat, "window_hist_dark", bay=2.4, ring=r, z=z + H1, cap=True)
            c.kinds = kb
            U.fill(mb, r, [], z + H + 0.6, "roof_flat")
        return
    vertical_piers(c, H, n, 5.4, mat, mat, "window_hist_white" if brick else "window_hist_dark", bay=2.6)
    U.fill(mb, c.ring, c.holes, z + H + 0.6, "roof_flat")
    parapet(mb, c.ring, z + H + 0.6, 1.0, 0.3, mat, "trim_light")
    # stepped central crown typical of Hudec's towers
    e = c.main_front()
    if e is not None and e.L > 10:
        w = min(10.0, e.L * 0.4)
        e.box(mb, e.L / 2 - w / 2, e.L / 2 + w / 2, z + H + 0.6, z + H + 4.2, -3.0, 0.3, mat)
        e.box(mb, e.L / 2 - w / 4, e.L / 2 + w / 4, z + H + 4.2, z + H + 6.6, -2.4, 0.3, mat)


def ov_church(c):
    """新天安堂 (Union Church, 1886): Gothic revival brick, bell tower with spire."""
    mb, z = c.mb, c.z
    ov = c.b.get("ov") or {}
    spec = dict(mats={"wall": "brick_grey_red", "base": "brick_grey_red", "trim": "trim_light",
                      "glass": "window_hist_dark", "roof": "roof_slate"},
                floors=[8.5], base=0, bay=3.4, win=[{"type": "arch", "w": 1.3, "h": 0.72}],
                balustrade=False, parapet=False, cornice=0.45, roof="hip", roof_h=6.5, door=True)
    classical(c, spec)
    e = c.main_front()
    if e is None:
        return
    tw = 5.0
    p = e.P(tw * 0.6, 0, -tw * 0.5)
    U.box(mb, -tw / 2, -tw / 2, -0.3, tw / 2, tw / 2, 19.0, "brick_grey_red", origin=(p[0], p[1], z), h=e.h)
    for k in range(4):
        hd = e.h + k * math.pi / 2
        q = U.xform((0, -tw / 2 - 0.01, 0), (p[0], p[1], 0), hd)
        U.box(mb, -0.5, -0.05, 14.0, 0.5, 0.0, 17.5, "window_hist_dark", origin=(q[0], q[1], z), h=hd)
    U.box(mb, -tw / 2 - 0.3, -tw / 2 - 0.3, 19.0, tw / 2 + 0.3, tw / 2 + 0.3, 19.6, "trim_light", origin=(p[0], p[1], z), h=e.h)
    spire = ov.get("spire", 33.0)
    U.lathe(mb, (p[0], p[1], z + 19.6), [(tw * 0.55, 0), (0.05, spire - 19.6 - 0.15)], 8, "roof_slate",
            h0=e.h + math.pi / 8, smooth=False)


def ov_modern_glass(c):
    mb, z = c.mb, c.z
    b = c.b
    ov = b.get("ov") or {}
    mat = ov.get("material", "curtain_blue")
    H = b["h"]
    U.walls(mb, c.ring, z - 0.3, z + H, mat)
    for h in c.holes:
        U.walls(mb, h, z - 0.3, z + H, mat)
    U.fill(mb, c.ring, c.holes, z + H, "roof_flat")
    parapet(mb, c.ring, z + H, 1.6, 0.3, "metal_grey", "metal_grey")
    from .facade import roof_stuff
    roof_stuff(mb, c.ring, z + H, c.rnd, big=True)


OVERRIDE = {"classical": ov_classical, "queen_anne": ov_queen_anne, "artdeco_brick": lambda c: ov_artdeco(c, True),
            "artdeco_stone": lambda c: ov_artdeco(c, False), "church": ov_church, "modern_glass": ov_modern_glass}


CUSTOM = {
    "bund13_customs": customs,
    "bund20_sassoon": sassoon,
    "bund23_boc": boc,
    "bund14_bank_of_communications": lambda c: artdeco(c, 28.0, 6, "stucco_white", 7.4, base_mat="granite_dark"),
    "bund32_peninsula": peninsula,
    "broadway_mansions": broadway,
    "bund6_commercial_bank": gothic_bank,
    "bund19_palace": palace_hotel,
    "bund33_consulate": consulate,
    "gutzlaff_tower": signal_tower,
    "heroes_monument": monument,
}


def build_all(sc, mats, root, quick=False):
    import json
    import os
    col = U.coll("Landmarks_Historic_Bund", root)
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "..", "..", "data", "landmarks.json"), encoding="utf-8") as fh:
        meta = {d["key"]: d for d in json.load(fh)["landmarks"]}
    n = 0
    for b in sc["buildings"]:
        key = b.get("landmark")
        if not key:
            continue
        rnd = random.Random(zlib.crc32(key.encode()))
        mb = U.MeshBuilder()
        c = Ctx(b, meta.get(key, {}), sc, mb, rnd)
        c.spec = meta.get(key, {})
        try:
            if key in CUSTOM:
                CUSTOM[key](c)
            elif SPECS.get(key):
                classical(c, SPECS[key])
            else:
                classical(c, dict(mats=GRANITE, floors=_floors(b["h"] - 3.0, max(2, b["floors"]), 5.4), base=1))
        except Exception as ex:  # keep the build going, report the culprit
            import traceback
            traceback.print_exc()
            print("[landmarks] failed", key, ex)
            continue
        name = f"LM_{meta.get(key, {}).get('no', '')}_{key}"
        U.add_obj(name, mb.build(name, mats), col)
        n += 1
    print(f"[landmarks] built {n}")
    # researched non-landmark buildings
    col2 = U.coll("Buildings_Researched_外滩源", root)
    mb = U.MeshBuilder()
    m = 0
    for b in sc["buildings"]:
        if b.get("style") != "override":
            continue
        st = (b.get("ov") or {}).get("style", "classical")
        rnd = random.Random(zlib.crc32(b["id"].encode()))
        c = Ctx(b, {}, sc, mb, rnd)
        try:
            OVERRIDE.get(st, ov_classical)(c)
            m += 1
        except Exception as ex:
            import traceback
            traceback.print_exc()
            print("[landmarks] override failed", b.get("name"), ex)
    if len(mb):
        U.add_obj("Buildings_Researched", mb.build("researched", mats), col2)
    print(f"[landmarks] researched buildings: {m}")
