"""Waibaidu Bridge (外白渡桥), other bridges, viaducts and tunnel ramps.

Waibaidu Bridge (1907/08): two-span camelback steel truss, total length
104.9 m, width 18.4 m, longest span 52.16 m, one pier in Suzhou Creek
(Wikipedia). Pedestrian walkways run outside the trusses.
"""
import math

from . import util as U


def _frame(axis):
    (x0, y0), (x1, y1) = axis
    L = math.hypot(x1 - x0, y1 - y0)
    h = math.atan2(y1 - y0, x1 - x0)
    return (x0, y0), h, L


def _beam(mb, p0, p1, w, d, mat):
    """Rectangular steel member between two 3D points."""
    dx, dy, dz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
    L = math.sqrt(dx * dx + dy * dy + dz * dz)
    if L < 1e-4:
        return
    ux, uy, uz = dx / L, dy / L, dz / L
    # pick a side vector perpendicular to the member
    if abs(uz) < 0.95:
        sx, sy, sz = -uy, ux, 0.0
    else:
        sx, sy, sz = 1.0, 0.0, 0.0
    sl = math.sqrt(sx * sx + sy * sy + sz * sz)
    sx, sy, sz = sx / sl, sy / sl, sz / sl
    tx, ty, tz = uy * sz - uz * sy, uz * sx - ux * sz, ux * sy - uy * sx
    corners = []
    for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        corners.append((sx * a * w / 2 + tx * b * d / 2, sy * a * w / 2 + ty * b * d / 2, sz * a * w / 2 + tz * b * d / 2))
    r0 = [(p0[0] + c[0], p0[1] + c[1], p0[2] + c[2]) for c in corners]
    r1 = [(p1[0] + c[0], p1[1] + c[1], p1[2] + c[2]) for c in corners]
    for i in range(4):
        j = (i + 1) % 4
        mb.face([r0[i], r0[j], r1[j], r1[i]], mat)
    mb.face(r0[::-1], mat)
    mb.face(r1, mat)


def waibaidu(mb, br, deck_z=0.4):
    (ox, oy), h, L = _frame(br["axis"])
    W = max(17.0, min(19.0, br["width"]))

    def P(x, y, z):
        return U.xform((x, y, z), (ox, oy, 0), h)

    steel = "steel_bridge"
    # deck: carriageway between trusses, walkways outside
    ty = 5.9            # truss plane offset from the axis
    U.box(mb, -2.0, -W / 2, deck_z - 1.2, L + 2.0, W / 2, deck_z - 0.15, steel, origin=(ox, oy, 0), h=h)
    U.box(mb, -2.0, -ty + 0.3, deck_z - 0.15, L + 2.0, ty - 0.3, deck_z, "asphalt", origin=(ox, oy, 0), h=h)
    for s in (-1, 1):
        y0, y1 = sorted((s * (ty + 0.4), s * (W / 2)))
        U.box(mb, -2.0, y0, deck_z - 0.15, L + 2.0, y1, deck_z + 0.18, "paving_deck", origin=(ox, oy, 0), h=h)
    # lane markings on the bridge (2 lanes each way, double yellow centre)
    for yy in (-0.12, 0.12):
        a, b = P(0, yy, deck_z + 0.01), P(L, yy, deck_z + 0.01)
        U.ribbon(mb, [a[:2], b[:2]], 0.15, deck_z + 0.012, "paint_yellow")
    for yy in (-2.8, 2.8):
        n = int(L // 6)
        for k in range(n):
            a, b = P(k * 6, yy, 0), P(k * 6 + 2, yy, 0)
            U.ribbon(mb, [a[:2], b[:2]], 0.15, deck_z + 0.012, "paint_white")
    # cross girders under the deck
    for k in range(int(L // 3) + 1):
        x = k * 3.0
        _beam(mb, P(x, -W / 2, deck_z - 1.3), P(x, W / 2, deck_z - 1.3), 0.35, 0.6, steel)
    # two camelback spans
    span = L / 2
    n = 8
    h_end, h_mid = 4.2, 8.6
    for sp in range(2):
        x0 = sp * span
        nodes_b = []
        nodes_t = []
        for i in range(n + 1):
            x = x0 + span * i / n
            ht = h_end + (h_mid - h_end) * math.sin(math.pi * i / n) ** 0.8
            nodes_b.append((x, deck_z))
            nodes_t.append((x, deck_z + ht))
        for s in (-1, 1):
            yy = s * ty
            # bottom chord
            for i in range(n):
                _beam(mb, P(nodes_b[i][0], yy, nodes_b[i][1]), P(nodes_b[i + 1][0], yy, nodes_b[i + 1][1]), 0.55, 0.7, steel)
            # top chord (end posts inclined)
            _beam(mb, P(nodes_b[0][0], yy, nodes_b[0][1]), P(nodes_t[1][0], yy, nodes_t[1][1]), 0.55, 0.6, steel)
            _beam(mb, P(nodes_b[n][0], yy, nodes_b[n][1]), P(nodes_t[n - 1][0], yy, nodes_t[n - 1][1]), 0.55, 0.6, steel)
            for i in range(1, n - 1):
                _beam(mb, P(nodes_t[i][0], yy, nodes_t[i][1]), P(nodes_t[i + 1][0], yy, nodes_t[i + 1][1]), 0.55, 0.6, steel)
            # verticals and Pratt diagonals
            for i in range(1, n):
                _beam(mb, P(nodes_b[i][0], yy, nodes_b[i][1]), P(nodes_t[i][0], yy, nodes_t[i][1]), 0.32, 0.35, steel)
            for i in range(1, n - 1):
                if i < n / 2:
                    a, b = nodes_t[i], nodes_b[i + 1]
                else:
                    a, b = nodes_b[i], nodes_t[i + 1]
                _beam(mb, P(a[0], yy, a[1]), P(b[0], yy, b[1]), 0.28, 0.3, steel)
            # walkway railing outside the truss
            ry = s * (W / 2 - 0.1)
            a, b = P(x0 - (2.0 if sp == 0 else 0), ry, deck_z + 1.25), P(x0 + span + (2.0 if sp == 1 else 0), ry, deck_z + 1.25)
            U.wall_strip(mb, [a[:2], b[:2]], deck_z + 1.15, deck_z + 1.25, 0.08, steel)
            U.wall_strip(mb, [a[:2], b[:2]], deck_z + 0.18, deck_z + 0.35, 0.08, steel)
            for k in range(int(span // 1.5) + 1):
                p = P(x0 + k * 1.5, ry, 0)
                U.box(mb, -0.03, -0.03, deck_z + 0.18, 0.03, 0.03, deck_z + 1.2, steel, origin=(p[0], p[1], 0), h=h)
        # overhead cross bracing between the trusses
        for i in range(1, n):
            zt = nodes_t[i][1]
            _beam(mb, P(nodes_t[i][0], -ty, zt), P(nodes_t[i][0], ty, zt), 0.3, 0.45, steel)
            if 1 <= i < n - 1:
                _beam(mb, P(nodes_t[i][0], -ty, zt), P(nodes_t[i + 1][0], ty, nodes_t[i + 1][1]), 0.18, 0.18, steel)
                _beam(mb, P(nodes_t[i][0], ty, zt), P(nodes_t[i + 1][0], -ty, nodes_t[i + 1][1]), 0.18, 0.18, steel)
        # portal knee braces
        for i in (1, n - 1):
            zt = nodes_t[i][1]
            for s in (-1, 1):
                _beam(mb, P(nodes_t[i][0], s * ty, zt - 1.6), P(nodes_t[i][0], s * (ty - 1.6), zt), 0.22, 0.22, steel)
    # central pier and abutments
    U.box(mb, L / 2 - 2.2, -W / 2 - 1.0, -7.0, L / 2 + 2.2, W / 2 + 1.0, deck_z - 1.2, "concrete", origin=(ox, oy, 0), h=h)
    U.lathe(mb, P(L / 2, -W / 2 - 1.0, -7.0), [(2.2, 0), (2.2, 7.0 + deck_z - 1.2)], 12, "concrete", smooth=False)
    U.lathe(mb, P(L / 2, W / 2 + 1.0, -7.0), [(2.2, 0), (2.2, 7.0 + deck_z - 1.2)], 12, "concrete", smooth=False)
    for x in (-1.5, L + 1.5):
        U.box(mb, x - 2.5, -W / 2 - 0.5, -7.0, x + 2.5, W / 2 + 0.5, deck_z - 0.15, "granite_grey", origin=(ox, oy, 0), h=h)
    # bridge lamps on the walkways
    for x in (2.0, L / 2 - 4, L / 2 + 4, L - 2.0):
        for s in (-1, 1):
            p = P(x, s * (W / 2 - 0.35), deck_z + 0.18)
            U.cylinder(mb, p, 0.07, 4.2, 8, "metal_dark")
            U.sphere(mb, (p[0], p[1], p[2] + 4.45), 0.28, 10, 6, "lamp_glass")


def simple_bridge(mb, road, deck_z=0.6):
    pts = [tuple(p) for p in road["pts"]]
    w = road["width"] + 4.0
    U.ribbon(mb, pts, w, deck_z, "asphalt")
    U.ribbon(mb, pts, w + 0.2, deck_z - 1.0, "concrete")
    for s in (-1, 1):
        side = [_off(pts, i, s * (w / 2)) for i in range(len(pts))]
        U.wall_strip(mb, side, deck_z - 1.0, deck_z + 1.1, 0.4, "concrete", "concrete_white")


def _off(pts, i, d):
    nrm = U.polyline_normals(pts)
    (nx, ny), sc = nrm[i]
    return (pts[i][0] + nx * d, pts[i][1] + ny * d)


def viaduct(mb, v):
    pts = [tuple(p) for p in v["pts"]]
    z = v["z"]
    w = v["width"] + 1.0
    U.ribbon(mb, pts, w, z, "asphalt")
    U.ribbon(mb, [(p[0], p[1]) for p in pts], w - 1.0, z - 1.8, "concrete")
    for s in (-1, 1):
        side = [_off(pts, i, s * (w / 2 - 0.2)) for i in range(len(pts))]
        U.wall_strip(mb, side, z - 1.8, z + 1.05, 0.45, "concrete", "concrete_white")
    L = U.polyline_length(pts)
    n = max(1, int(L // 28))
    for k in range(n + 1):
        p, hd = U.point_along(pts, L * k / n)
        U.box(mb, -0.9, -0.9, 0, 0.9, 0.9, z - 1.8, "concrete", origin=(p[0], p[1], 0), h=hd)
        U.box(mb, -1.2, -w / 2 + 0.6, z - 2.6, 1.2, w / 2 - 0.6, z - 1.8, "concrete", origin=(p[0], p[1], 0), h=hd)


def ramp(mb, r):
    pts = [tuple(p) for p in r["pts"]]
    w = r["width"]
    if len(pts) < 2:
        return
    U.ribbon(mb, pts, w, None, "asphalt")
    zs = [p[2] for p in pts]
    if not r.get("up"):
        # trench walls up to street level + parapet
        for s in (-1, 1):
            side = [(_off(pts, i, s * (w / 2 + 0.2))) + (pts[i][2],) for i in range(len(pts))]
            ok = [p for p in side]
            U.wall_strip(mb, [(p[0], p[1]) for p in ok], lambda p: -7.0, lambda p: 1.15, 0.4, "concrete", "concrete_white")
        # portal frame where the trench is deepest
        k = min(range(len(zs)), key=lambda i: zs[i])
        if zs[k] < -4.5:
            p = pts[k]
            j = k + 1 if k + 1 < len(pts) else k - 1
            hd = math.atan2(pts[j][1] - p[1], pts[j][0] - p[0])
            U.box(mb, -0.8, -w / 2 - 0.4, p[2] + 4.8, 0.8, w / 2 + 0.4, 1.15, "concrete", origin=(p[0], p[1], 0), h=hd)
    else:
        for s in (-1, 1):
            side = [_off(pts, i, s * (w / 2 + 0.2)) for i in range(len(pts))]
            zz = dict(zip(side, zs))
            U.wall_strip(mb, side, lambda p: -0.3, lambda p: zz.get(p, 0) + 1.05, 0.4, "concrete", "concrete_white")


def build_all(sc, mats, root):
    col = U.coll("Bridges_Viaducts", root)
    mb = U.MeshBuilder()
    wbd = [b for b in sc.get("bridges", []) if b.get("name") == "外白渡桥"]
    if wbd:
        waibaidu(mb, wbd[0])
        U.add_obj("Waibaidu_Bridge_外白渡桥", mb.build("waibaidu", mats), col)
    mb = U.MeshBuilder()
    for r in sc.get("bridge_roads", []):
        if r["name"] == "外白渡桥":
            continue
        simple_bridge(mb, r)
    for v in sc.get("viaducts", []):
        viaduct(mb, v)
    for r in sc.get("ramps", []):
        ramp(mb, r)
    if len(mb):
        U.add_obj("Viaducts_Ramps_Bridges", mb.build("viaducts", mats), col)
