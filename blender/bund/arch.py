"""Classical architecture elements used by the landmark builders.

Coordinates along a facade are expressed in a local frame of a wall edge:
s = metres along the edge from point a, d = metres in front of the wall
(outward), z = height. `Edge.P(s, z, d)` converts to world space.
"""
import math

from . import util as U


class Edge:
    def __init__(self, a, b):
        self.a, self.b = a, b
        dx, dy = b[0] - a[0], b[1] - a[1]
        self.L = math.hypot(dx, dy)
        self.t = (dx / self.L, dy / self.L)
        self.n = (self.t[1], -self.t[0])          # outward for CCW rings
        self.h = math.atan2(dy, dx)

    def P(self, s, z, d=0.0):
        return (self.a[0] + self.t[0] * s + self.n[0] * d,
                self.a[1] + self.t[1] * s + self.n[1] * d, z)

    def box(self, mb, s0, s1, z0, z1, d0, d1, mat, faces="all"):
        """Axis-aligned box in the edge frame."""
        pts = [self.P(s, z, d) for z in (z0, z1) for d in (d0, d1) for s in (s0, s1)]
        # indices: z0:(d0:s0,s1),(d1:s0,s1) ; z1: ...
        p = {}
        k = 0
        for zi in (0, 1):
            for di in (0, 1):
                for si in (0, 1):
                    p[(si, di, zi)] = pts[k]
                    k += 1
        F = {
            "front": [(0, 1, 0), (1, 1, 0), (1, 1, 1), (0, 1, 1)],
            "back": [(1, 0, 0), (0, 0, 0), (0, 0, 1), (1, 0, 1)],
            "left": [(0, 0, 0), (0, 1, 0), (0, 1, 1), (0, 0, 1)],
            "right": [(1, 1, 0), (1, 0, 0), (1, 0, 1), (1, 1, 1)],
            "top": [(0, 0, 1), (0, 1, 1), (1, 1, 1), (1, 0, 1)],
            "bottom": [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)],
        }
        for name, idx in F.items():
            if faces != "all" and name not in faces:
                continue
            mb.face([p[i] for i in idx], mat)


# --------------------------------------------------------------------------
# openings
# --------------------------------------------------------------------------

def band_wall(mb, e, z0, z1, cols, zb, zt, depth, mat_wall, mat_glass, rnd, arch=False,
              mat_reveal=None, s_from=0.0, s_to=None, uv_off=0.0, glass_attr=True):
    """Wall strip z0..z1 along edge e with a row of openings.

    cols: [(s0, s1)] opening extents; zb/zt: opening bottom/top. With arch=True
    the top of each opening is a semicircle reaching zt.
    """
    s_to = e.L if s_to is None else s_to
    mat_reveal = mat_reveal or mat_wall
    xs = [s_from]
    for s0, s1 in cols:
        xs += [s0, s1]
    xs.append(s_to)
    if arch:
        # springline per opening (use the widest opening for the row)
        r = max((s1 - s0) / 2 for s0, s1 in cols) if cols else 0
        zs_ = max(zb + 0.2, zt - r)
        zs = [z0, zb, zs_, zt, z1]
    else:
        zs = [z0, zb, zt, z1]
    win_rows = {1} if not arch else {1, 2}
    for i in range(len(xs) - 1):
        xa, xb = xs[i], xs[i + 1]
        if xb - xa < 1e-4:
            continue
        is_col = (i % 2 == 1)
        for j in range(len(zs) - 1):
            za, zz = zs[j], zs[j + 1]
            if zz - za < 1e-4:
                continue
            if not (is_col and j in win_rows):
                mb.face([e.P(xa, za), e.P(xb, za), e.P(xb, zz), e.P(xa, zz)], mat_wall,
                        uvs=[(uv_off + xa, za), (uv_off + xb, za), (uv_off + xb, zz), (uv_off + xa, zz)])
                continue
            d = -depth
            if arch and j == 2:
                _arch_cell(mb, e, xa, xb, za, zz, d, mat_wall, mat_glass, mat_reveal, rnd, uv_off)
                continue
            mb.face([e.P(xa, za, d), e.P(xa, zz, d), e.P(xa, zz), e.P(xa, za)], mat_reveal)
            mb.face([e.P(xb, zz), e.P(xb, zz, d), e.P(xb, za, d), e.P(xb, za)], mat_reveal)
            if not arch:
                mb.face([e.P(xa, zz, d), e.P(xb, zz, d), e.P(xb, zz), e.P(xa, zz)], mat_reveal)
            mb.face([e.P(xb, za), e.P(xb, za, d), e.P(xa, za, d), e.P(xa, za)], mat_reveal)
            vb, vt = (0.0, 1.0) if not arch else (0.0, (zz - za) / max(zt - za, 1e-3))
            mb.face([e.P(xa, za, d), e.P(xb, za, d), e.P(xb, zz, d), e.P(xa, zz, d)], mat_glass,
                    uvs=[(0, vb), (1, vb), (1, vt), (0, vt)], attrs={"rnd": rnd.random()} if glass_attr else None)


def _arch_cell(mb, e, xa, xb, zs, ztop, d, mat_wall, mat_glass, mat_reveal, rnd, uv_off, seg=8):
    xc = (xa + xb) / 2
    r = (xb - xa) / 2
    rz = ztop - zs
    arc = []
    for k in range(seg + 1):
        a = math.pi * k / seg          # 0 -> right, pi -> left
        arc.append((xc + r * math.cos(a), zs + rz * math.sin(a)))
    # spandrels (wall)
    left = [(xa, zs)] + [p for p in arc[::-1] if p[0] <= xc + 1e-6][1:] + [(xa, ztop)]
    right = [(xb, zs), (xb, ztop)] + [p for p in arc[::-1] if p[0] >= xc - 1e-6][::-1][:-1]
    # left polygon must go CCW in (s,z): (xa,zs) -> arc up to apex -> (xa,ztop)
    lp = [(xa, zs)] + [p for p in arc if p[0] <= xc + 1e-9][::-1][1:]
    lp = [(xa, zs)] + [arc[k] for k in range(seg, seg // 2 - 1, -1)][1:] + [(xa, ztop)]
    mb.face([e.P(s, z) for s, z in lp], mat_wall)
    rp = [(xb, zs), (xb, ztop)] + [arc[k] for k in range(seg // 2, -1, -1)][:-1]
    rp = [(xb, zs), (xb, ztop)] + [arc[k] for k in range(seg // 2, 0, -1)]
    mb.face([e.P(s, z) for s, z in rp], mat_wall)
    # reveal along the arc
    for k in range(seg):
        s0, z0 = arc[k]
        s1, z1 = arc[k + 1]
        mb.face([e.P(s1, z1), e.P(s0, z0), e.P(s0, z0, d), e.P(s1, z1, d)], mat_reveal)
    # glass (fan)
    vt = 1.0
    cos = [e.P(s, z, d) for s, z in arc]
    uvs = [((s - xa) / (xb - xa), 0.75 + 0.25 * (z - zs) / max(rz, 1e-3)) for s, z in arc]
    mb.face(cos[::-1], mat_glass, uvs=uvs[::-1], attrs={"rnd": rnd.random()})


def surround(mb, e, s0, s1, zb, zt, mat, w=0.18, out=0.10, head="flat", arch=False, keystone=True,
             sill=True):
    """Window architrave + optional head (flat cornice, triangular or segmental pediment)."""
    e.box(mb, s0 - w, s0, zb, zt if not arch else zt - (s1 - s0) / 2, 0, out, mat)
    e.box(mb, s1, s1 + w, zb, zt if not arch else zt - (s1 - s0) / 2, 0, out, mat)
    if arch:
        r = (s1 - s0) / 2
        xc = (s0 + s1) / 2
        zs = zt - r
        seg = 8
        for k in range(seg):
            a0 = math.pi * k / seg
            a1 = math.pi * (k + 1) / seg
            pa = [(xc + r * math.cos(a0), zs + r * math.sin(a0)), (xc + (r + w) * math.cos(a0), zs + (r + w) * math.sin(a0)),
                  (xc + (r + w) * math.cos(a1), zs + (r + w) * math.sin(a1)), (xc + r * math.cos(a1), zs + r * math.sin(a1))]
            mb.face([e.P(s, z, out) for s, z in pa[::-1]], mat)
            mb.face([e.P(pa[1][0], pa[1][1], 0), e.P(pa[2][0], pa[2][1], 0),
                     e.P(pa[2][0], pa[2][1], out), e.P(pa[1][0], pa[1][1], out)][::-1], mat)
        if keystone:
            e.box(mb, xc - 0.22, xc + 0.22, zt - 0.1, zt + w + 0.25, 0, out + 0.06, mat)
    else:
        e.box(mb, s0 - w, s1 + w, zt, zt + w, 0, out, mat)
        if head == "cornice":
            e.box(mb, s0 - w - 0.12, s1 + w + 0.12, zt + w, zt + w + 0.16, 0, out + 0.14, mat)
        elif head in ("pediment", "segment"):
            pediment(mb, e, s0 - w - 0.12, s1 + w + 0.12, zt + w, (s1 - s0) * (0.28 if head == "pediment" else 0.2),
                     out + 0.12, mat, segmental=(head == "segment"))
    if sill:
        e.box(mb, s0 - w - 0.08, s1 + w + 0.08, zb - 0.14, zb, 0, out + 0.08, mat)


def pediment(mb, e, s0, s1, z, h, out, mat, segmental=False, tympanum=None, d0=0.0):
    """Triangular (or segmental) pediment projecting `out` from the wall."""
    xc = (s0 + s1) / 2
    w = s1 - s0
    if segmental:
        n = 8
        prof = []
        R = (w * w / 4 + h * h) / (2 * h)
        zc = z + h - R
        a0 = math.asin(min(1.0, (w / 2) / R))
        for k in range(n + 1):
            a = -a0 + 2 * a0 * k / n
            prof.append((xc + R * math.sin(a), zc + R * math.cos(a)))
    else:
        prof = [(s0, z), (xc, z + h), (s1, z)]
        prof = [prof[0], prof[1], prof[2]]
    # front face
    front = [(s0, z)] + prof[1:-1] + [(s1, z)] if not segmental else [(s0, z)] + prof + [(s1, z)]
    if segmental:
        front = [(s0, z), (s1, z)] + prof[::-1]
    else:
        front = [(s0, z), (s1, z), (xc, z + h)]
    mb.face([e.P(s, zz, d0 + out) for s, zz in front], tympanum or mat)
    # raking tops
    pts = prof if segmental else [(s0, z), (xc, z + h), (s1, z)]
    for (sa, za), (sb, zb) in zip(pts[:-1], pts[1:]):
        mb.face([e.P(sa, za, d0), e.P(sa, za, d0 + out + 0.12), e.P(sb, zb, d0 + out + 0.12), e.P(sb, zb, d0)], mat)
    # raking cornice lip
    for (sa, za), (sb, zb) in zip(pts[:-1], pts[1:]):
        mb.face([e.P(sb, zb - 0.14, d0 + out + 0.12), e.P(sb, zb, d0 + out + 0.12),
                 e.P(sa, za, d0 + out + 0.12), e.P(sa, za - 0.14, d0 + out + 0.12)][::-1], mat)
    # bottom (horizontal cornice)
    e.box(mb, s0 - 0.1, s1 + 0.1, z - 0.22, z, d0, d0 + out + 0.16, mat)


# --------------------------------------------------------------------------
# orders
# --------------------------------------------------------------------------

def column(mb, x, y, z0, h, r, mat, order="ionic", n=14, plinth=True):
    """Free-standing classical column (plinth, base, shaft with entasis, capital)."""
    zc = z0
    if plinth:
        U.box(mb, -1.35 * r, -1.35 * r, 0, 1.35 * r, 1.35 * r, 0.35 * r, mat, origin=(x, y, zc))
        zc += 0.35 * r
    base_h = 0.5 * r
    U.lathe(mb, (x, y, zc), [(1.25 * r, 0), (1.25 * r, 0.12 * r), (1.12 * r, 0.25 * r), (1.15 * r, 0.32 * r),
                             (1.02 * r, base_h)], n, mat, cap_top=False)
    zc += base_h
    cap_h = {"doric": 0.55 * r, "ionic": 0.75 * r, "corinthian": 1.9 * r}[order]
    shaft_h = h - (zc - z0) - cap_h
    prof = []
    for k in range(7):
        t = k / 6
        rr = r * (1.0 - 0.14 * max(0, t - 0.33) / 0.67)
        prof.append((rr, shaft_h * t))
    U.lathe(mb, (x, y, zc), prof, n, mat, cap_top=False)
    zc += shaft_h
    rt = r * 0.86
    if order == "doric":
        U.lathe(mb, (x, y, zc), [(rt, 0), (rt * 1.05, 0.06 * r), (1.3 * r, 0.3 * r)], n, mat, cap_top=False)
        U.box(mb, -1.38 * r, -1.38 * r, 0.3 * r, 1.38 * r, 1.38 * r, cap_h, mat, origin=(x, y, zc))
    elif order == "ionic":
        U.lathe(mb, (x, y, zc), [(rt, 0), (rt * 1.1, 0.12 * r), (rt * 1.1, 0.2 * r)], n, mat, cap_top=False)
        U.box(mb, -1.25 * r, -1.25 * r, 0.2 * r, 1.25 * r, 1.25 * r, 0.42 * r, mat, origin=(x, y, zc))
        # volutes
        for sx in (-1, 1):
            U.lathe(mb, (x + sx * 1.15 * r, y, zc + 0.05 * r), [(0.0, 0.0), (0.32 * r, 0.02 * r), (0.32 * r, 0.35 * r), (0.0, 0.37 * r)],
                    8, mat, smooth=True)
        U.box(mb, -1.4 * r, -1.4 * r, 0.42 * r, 1.4 * r, 1.4 * r, cap_h, mat, origin=(x, y, zc))
    else:
        U.lathe(mb, (x, y, zc), [(rt, 0), (rt * 1.05, 0.3 * r), (rt * 1.25, 1.1 * r), (rt * 1.45, 1.55 * r),
                                 (rt * 1.5, 1.6 * r)], n, mat, cap_top=True)
        # acanthus leaves suggestion: small boxes around the bell
        for k in range(8):
            a = 2 * math.pi * k / 8
            lx, ly = x + math.cos(a) * rt * 1.12, y + math.sin(a) * rt * 1.12
            U.box(mb, -0.16 * r, -0.16 * r, 0.25 * r, 0.16 * r, 0.16 * r, 0.95 * r, mat, origin=(lx, ly, zc), h=a)
        U.box(mb, -1.45 * r, -1.45 * r, 1.6 * r, 1.45 * r, 1.45 * r, cap_h, mat, origin=(x, y, zc))


def colonnade(mb, e, s_list, z0, h, r, d, mat, order="ionic"):
    for s in s_list:
        p = e.P(s, 0, d)
        column(mb, p[0], p[1], z0, h, r, mat, order)


def pilaster(mb, e, s, z0, h, w, out, mat, order="ionic"):
    e.box(mb, s - w / 2 - 0.06, s + w / 2 + 0.06, z0, z0 + 0.45, 0, out + 0.06, mat)
    e.box(mb, s - w / 2, s + w / 2, z0 + 0.45, z0 + h - 0.6, 0, out, mat)
    e.box(mb, s - w / 2 - 0.08, s + w / 2 + 0.08, z0 + h - 0.6, z0 + h, 0, out + 0.08, mat)


def entablature(mb, e, s0, s1, z, mat, h=1.6, out=0.35, d0=0.0):
    """Architrave, frieze and cornice along part of a facade."""
    e.box(mb, s0, s1, z, z + h * 0.35, d0, d0 + out * 0.4, mat)
    e.box(mb, s0, s1, z + h * 0.35, z + h * 0.7, d0, d0 + out * 0.3, mat)
    e.box(mb, s0 - 0.1, s1 + 0.1, z + h * 0.7, z + h * 0.82, d0, d0 + out * 0.8, mat)
    e.box(mb, s0 - 0.2, s1 + 0.2, z + h * 0.82, z + h, d0, d0 + out * 1.3, mat)


def balustrade(mb, e, s0, s1, z, mat, h=1.0, d0=0.0, step=0.42, pier_every=3.6):
    """Rail, balusters and piers along part of a facade top."""
    if s1 - s0 < 0.8:
        return
    e.box(mb, s0, s1, z, z + 0.18, d0 - 0.25, d0 + 0.05, mat)
    e.box(mb, s0, s1, z + h - 0.16, z + h, d0 - 0.28, d0 + 0.08, mat)
    n = int((s1 - s0) // step)
    np_ = max(1, int(round((s1 - s0) / pier_every)))
    piers = [s0 + (s1 - s0) * k / np_ for k in range(np_ + 1)]
    for k in range(n):
        s = s0 + (k + 0.5) * (s1 - s0) / n
        if any(abs(s - p) < 0.3 for p in piers):
            continue
        p = e.P(s, 0, d0 - 0.1)
        U.lathe(mb, (p[0], p[1], z + 0.18), [(0.07, 0), (0.1, 0.12), (0.06, 0.28), (0.11, 0.48), (0.07, 0.62),
                                             (0.08, h - 0.34)], 6, mat, cap_top=False, smooth=True)
    for pz in piers:
        e.box(mb, pz - 0.22, pz + 0.22, z, z + h + 0.08, d0 - 0.3, d0 + 0.1, mat)


# --------------------------------------------------------------------------
# domes, turrets
# --------------------------------------------------------------------------

def dome(mb, cx, cy, z, R, mat_dome, mat_drum, drum_h=None, lantern=True, n=32, profile="hemi",
         drum_cols=0, mat_col=None):
    """Drum + dome + lantern."""
    drum_h = R * 0.6 if drum_h is None else drum_h
    if drum_h > 0:
        U.lathe(mb, (cx, cy, z), [(R * 1.06, 0), (R * 1.06, 0.35), (R, 0.45), (R, drum_h - 0.5), (R * 1.08, drum_h - 0.3),
                                  (R * 1.08, drum_h)], n, mat_drum, smooth=False)
        if drum_cols:
            for k in range(drum_cols):
                a = 2 * math.pi * (k + 0.5) / drum_cols
                column(mb, cx + math.cos(a) * R * 1.12, cy + math.sin(a) * R * 1.12, z + 0.45, drum_h - 0.9,
                       R * 0.045, mat_col or mat_drum, "corinthian", n=8, plinth=False)
    z2 = z + drum_h
    prof = []
    m = 12
    for k in range(m + 1):
        a = (math.pi / 2) * k / m
        if profile == "hemi":
            prof.append((R * math.cos(a), R * math.sin(a)))
        elif profile == "tall":
            prof.append((R * math.cos(a), R * 1.35 * math.sin(a)))
        else:  # onion-ish baroque
            t = k / m
            rr = R * (1.0 + 0.12 * math.sin(math.pi * t * 0.8)) * math.cos(a) ** 0.9
            prof.append((rr, R * 1.5 * math.sin(a)))
    top_r = 0.18 * R if lantern else 0.0
    prof = [(max(rr, top_r), zz) for rr, zz in prof]
    U.lathe(mb, (cx, cy, z2), prof, n, mat_dome, smooth=True, cap_top=not lantern)
    ztop = z2 + prof[-1][1]
    if lantern:
        lr = 0.2 * R
        U.lathe(mb, (cx, cy, ztop), [(lr, 0), (lr, 0.55 * R * 0.6), (lr * 1.2, 0.6 * R * 0.6), (lr * 0.95, 0.62 * R * 0.6)],
                12, mat_drum, smooth=False)
        z3 = ztop + 0.62 * R * 0.6
        U.lathe(mb, (cx, cy, z3), [(lr * 0.95, 0), (lr * 0.6, lr * 0.5), (0.05, lr * 1.0), (0.0, lr * 1.6)], 12,
                mat_dome, smooth=True)
        ztop = z3 + lr * 1.6
    return ztop


def cupola(mb, cx, cy, z, w, h, mat, mat_dome, cols=6, order="ionic", round_=True):
    """Small open turret: podium, ring of columns, entablature, dome."""
    pod = 0.6
    U.lathe(mb, (cx, cy, z), [(w * 0.62, 0), (w * 0.62, pod)], 16, mat, smooth=False)
    r_col = w * 0.05
    hc = h * 0.55
    for k in range(cols):
        a = 2 * math.pi * k / cols
        column(mb, cx + math.cos(a) * w * 0.48, cy + math.sin(a) * w * 0.48, z + pod, hc, r_col, mat, order, n=8,
               plinth=False)
    U.lathe(mb, (cx, cy, z + pod), [(w * 0.3, 0), (w * 0.3, hc)], 12, "window_hist_dark", smooth=False)
    ze = z + pod + hc
    U.lathe(mb, (cx, cy, ze), [(w * 0.58, 0), (w * 0.62, 0.35), (w * 0.62, 0.55)], 16, mat, smooth=False)
    return dome(mb, cx, cy, ze + 0.55, w * 0.5, mat_dome, mat, drum_h=0.0, lantern=True, n=20,
                profile="tall")


def flagpole(mb, x, y, z, h, mat_pole="steel_stainless", flag=True):
    U.cylinder(mb, (x, y, z), 0.09, h, 8, mat_pole, r_top=0.05)
    U.sphere(mb, (x, y, z + h), 0.14, 8, 4, "gold")
    if flag:
        fx = 0.0
        w, hh = 2.4, 1.6
        pts = []
        for k in range(7):
            t = k / 6
            pts.append((x + 0.1 + w * t, y + 0.25 * math.sin(t * 3.0), z + h - 0.3 - hh, z + h - 0.3))
        for (x0, y0, za, zb), (x1, y1, _, _) in zip(pts[:-1], pts[1:]):
            mb.face([(x0, y0, za), (x1, y1, za), (x1, y1, zb), (x0, y0, zb)], "flag_red")
            mb.face([(x0, y0, zb), (x1, y1, zb), (x1, y1, za), (x0, y0, za)], "flag_red")


def mansard(mb, ring, z, h, inset, mat_roof, mat_top="roof_flat", dormer_step=0.0, mat_dormer=None,
            mat_glass="window_hist_dark", rnd=None):
    """Steep mansard roof: outer ring at z, inner ring at z+h inset by `inset`."""
    inner = U.offset_ring(ring, inset)
    n = len(ring)
    for i in range(n):
        j = (i + 1) % n
        mb.face([(ring[i][0], ring[i][1], z), (ring[j][0], ring[j][1], z),
                 (inner[j][0], inner[j][1], z + h), (inner[i][0], inner[i][1], z + h)], mat_roof)
        if dormer_step > 0:
            e = Edge(ring[i], ring[j])
            if e.L < 3:
                continue
            k = int(e.L // dormer_step)
            for m_ in range(k):
                s = (m_ + 0.5) * e.L / k
                dw, dh = 1.2, min(h * 0.75, 2.0)
                d_in = -inset * 0.25
                # dormer: small box with a little pediment
                e.box(mb, s - dw / 2 - 0.15, s + dw / 2 + 0.15, z + 0.2, z + 0.2 + dh, d_in - 1.0, d_in + 0.2,
                      mat_dormer or mat_roof)
                band_face = [e.P(s - dw / 2, z + 0.45, d_in + 0.21), e.P(s + dw / 2, z + 0.45, d_in + 0.21),
                             e.P(s + dw / 2, z + dh, d_in + 0.21), e.P(s - dw / 2, z + dh, d_in + 0.21)]
                mb.face(band_face[::-1], mat_glass, uvs=[(0, 0), (0, 1), (1, 1), (1, 0)],
                        attrs={"rnd": rnd.random() if rnd else 0.5})
                pediment(mb, e, s - dw / 2 - 0.25, s + dw / 2 + 0.25, z + 0.2 + dh, 0.5, 0.15,
                         mat_dormer or mat_roof, d0=d_in)
    U.fill(mb, inner, [], z + h, mat_top)


def hip_roof(mb, ring, z, h, mat_roof, overhang=0.4):
    """Hip roof over the minimum-area rectangle of the ring."""
    best = None
    pts = ring
    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        hd = math.atan2(b[1] - a[1], b[0] - a[0])
        c, s = math.cos(-hd), math.sin(-hd)
        loc = [((p[0]) * c - (p[1]) * s, (p[0]) * s + (p[1]) * c) for p in pts]
        u0, u1 = min(p[0] for p in loc), max(p[0] for p in loc)
        v0, v1 = min(p[1] for p in loc), max(p[1] for p in loc)
        area = (u1 - u0) * (v1 - v0)
        if best is None or area < best[0]:
            best = (area, hd, u0, u1, v0, v1)
    _, hd, u0, u1, v0, v1 = best
    u0 -= overhang
    u1 += overhang
    v0 -= overhang
    v1 += overhang
    if (u1 - u0) < (v1 - v0):
        hd += math.pi / 2
        u0, u1, v0, v1 = v0, v1, -u1, -u0
    W = lambda u, v, zz: U.xform((u, v, zz), (0, 0, 0), hd)
    vm = (v0 + v1) / 2
    hw = (v1 - v0) / 2
    r0, r1 = u0 + hw, u1 - hw
    if r1 < r0:
        r0 = r1 = (u0 + u1) / 2
    mb.face([W(u0, v0, z), W(u1, v0, z), W(r1, vm, z + h), W(r0, vm, z + h)], mat_roof)
    mb.face([W(u1, v1, z), W(u0, v1, z), W(r0, vm, z + h), W(r1, vm, z + h)], mat_roof)
    mb.face([W(u0, v1, z), W(u0, v0, z), W(r0, vm, z + h)], mat_roof)
    mb.face([W(u1, v0, z), W(u1, v1, z), W(r1, vm, z + h)], mat_roof)
    mb.face([W(u0, v0, z), W(u0, v1, z), W(u1, v1, z), W(u1, v0, z)][::-1], mat_roof)
    return hd, (u0, u1, v0, v1)


def pyramid_roof(mb, ring, z, h, mat, overhang=0.0, eave_curve=0.0):
    """Pyramid over a ring (used by Sassoon House & Bank of China)."""
    cx, cy = U.centroid(ring)
    outer = U.offset_ring(ring, -overhang) if overhang else ring
    n = len(outer)
    apex = (cx, cy, z + h)
    for i in range(n):
        j = (i + 1) % n
        a = (outer[i][0], outer[i][1], z - (eave_curve if overhang else 0))
        b = (outer[j][0], outer[j][1], z - (eave_curve if overhang else 0))
        if eave_curve > 0:
            # two-step slope: flatter eaves, steeper upper part (Chinese roof)
            mi = (outer[i][0] * 0.7 + cx * 0.3, outer[i][1] * 0.7 + cy * 0.3, z + h * 0.18)
            mj = (outer[j][0] * 0.7 + cx * 0.3, outer[j][1] * 0.7 + cy * 0.3, z + h * 0.18)
            mb.face([a, b, mj, mi], mat)
            mb.face([mi, mj, apex], mat)
        else:
            mb.face([a, b, apex], mat)
    if overhang:
        mb.face([(p[0], p[1], z - eave_curve) for p in outer][::-1], mat)
