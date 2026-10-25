"""Street furniture: lamps, traffic signals, bus shelters, benches, statues."""
import math
import random

from . import util as U


def _lamp_bund():
    """Ornamental cast-iron lamp post (Zhongshan E1 Rd), ~9 m, two lanterns."""
    mb = U.MeshBuilder()
    m = "metal_dark"
    U.lathe(mb, (0, 0, 0), [(0.38, 0), (0.38, 0.25), (0.3, 0.35), (0.3, 0.9), (0.22, 1.1), (0.2, 1.3)], 12, m, smooth=False)
    U.lathe(mb, (0, 0, 1.3), [(0.14, 0), (0.1, 6.6), (0.13, 6.8), (0.09, 7.0)], 10, m)
    for s in (-1, 1):
        U.cylinder(mb, (0, 0, 7.15), 0.05, 0.1, 6, m)
        U.box(mb, -0.04, -0.04, 0, s * 1.1, 0.04, 0.08, m, origin=(0, 0, 7.2))
        x = s * 1.1
        U.cylinder(mb, (x, 0, 6.65), 0.04, 0.55, 6, m)
        U.lathe(mb, (x, 0, 6.2), [(0.0, 0), (0.16, 0.05), (0.26, 0.3), (0.26, 0.45), (0.0, 0.5)], 12, "lamp_glass")
        U.lathe(mb, (x, 0, 6.68), [(0.3, 0), (0.06, 0.25)], 10, m)
    U.lathe(mb, (0, 0, 7.0), [(0.0, 0), (0.22, 0.05), (0.3, 0.4), (0.3, 0.6), (0.0, 0.7)], 12, "lamp_glass")
    U.lathe(mb, (0, 0, 7.7), [(0.34, 0), (0.05, 0.4), (0.02, 0.7)], 10, m)
    return mb


def _lamp_promenade():
    mb = U.MeshBuilder()
    m = "metal_dark"
    U.lathe(mb, (0, 0, 0), [(0.25, 0), (0.25, 0.2), (0.18, 0.3), (0.12, 0.9), (0.08, 3.6), (0.11, 3.75)], 10, m)
    U.lathe(mb, (0, 0, 3.75), [(0.12, 0), (0.24, 0.15), (0.24, 0.65), (0.12, 0.75)], 8, "lamp_glass", smooth=False)
    U.lathe(mb, (0, 0, 4.5), [(0.32, 0), (0.05, 0.3), (0.02, 0.5)], 8, m)
    return mb


def _lamp_street():
    mb = U.MeshBuilder()
    U.cylinder(mb, (0, 0, 0), 0.11, 8.5, 8, "metal_grey", r_top=0.07)
    U.box(mb, 0, -0.04, 8.2, 1.8, 0.04, 8.3, "metal_grey")
    U.box(mb, 1.4, -0.15, 8.05, 2.3, 0.15, 8.25, "metal_grey")
    U.box(mb, 1.45, -0.12, 8.02, 2.25, 0.12, 8.05, "lamp_glass")
    return mb


def _signal_head(mb, x, y, z, h):
    """Three-aspect vehicle signal (red lit) facing -X in the pole frame."""
    U.box(mb, -0.15, -0.2, -1.0, 0.15, 0.2, 0.0, "signal_housing", origin=(x, y, z), h=h)
    for k, mat in enumerate(("signal_red", "signal_off", "signal_off")):
        zc = z - 0.18 - k * 0.32
        p = U.xform((-0.16, 0, 0), (x, y, zc), h)
        U.lathe(mb, (p[0], p[1], zc - 0.12), [(0.0, 0), (0.12, 0.01), (0.12, 0.23), (0.0, 0.24)], 8, mat,
                scale_xy=(0.25, 1.0))
        # visor
        U.box(mb, -0.32, -0.13, 0.12, -0.15, 0.13, 0.14, "signal_housing", origin=(x, y, zc), h=h)


def _signal_pole(arm):
    """L-shaped signal pole; travel direction = +X, pole on the right kerb (y<0 side handled by rotation)."""
    mb = U.MeshBuilder()
    U.cylinder(mb, (0, 0, 0), 0.16, 6.8, 10, "metal_grey", r_top=0.12)
    U.box(mb, -0.3, -0.3, 0, 0.3, 0.3, 0.25, "concrete")
    # arm reaches over the road to the left of travel (+Y)
    U.box(mb, -0.07, 0, 6.2, 0.07, arm, 6.34, "metal_grey")
    U.box(mb, -0.05, 0, 5.4, 0.05, 1.5, 5.5, "metal_grey")
    for k in range(max(1, int(arm // 3.5))):
        y = arm - 0.6 - k * 3.4
        if y < 1.0:
            break
        _signal_head(mb, 0.0, y, 6.15, 0.0)
    # pedestrian signal + street sign on the pole
    U.box(mb, -0.2, -0.12, 2.3, 0.0, 0.12, 2.9, "signal_housing")
    U.box(mb, -0.02, 0.15, 3.3, 0.02, 1.25, 3.75, "sign_blue")
    return mb


def _shelter():
    mb = U.MeshBuilder()
    for x in (-2.2, 2.2):
        U.box(mb, x - 0.05, -0.05, 0, x + 0.05, 0.05, 2.6, "metal_grey")
        U.box(mb, x - 0.05, 1.35, 0, x + 0.05, 1.45, 2.6, "metal_grey")
    U.box(mb, -2.6, -0.4, 2.6, 2.6, 1.8, 2.72, "canopy_glass")
    U.box(mb, -2.2, 1.38, 0.3, 2.2, 1.42, 2.4, "glass_clear")
    U.box(mb, 1.0, 1.3, 0.2, 2.1, 1.38, 2.2, "sign_white")
    U.box(mb, -1.8, 0.9, 0.45, 0.8, 1.3, 0.5, "metal_grey")
    return mb


def _bench():
    mb = U.MeshBuilder()
    U.box(mb, -0.9, -0.25, 0.0, -0.75, 0.25, 0.42, "granite_grey")
    U.box(mb, 0.75, -0.25, 0.0, 0.9, 0.25, 0.42, "granite_grey")
    for k in range(4):
        U.box(mb, -1.0, -0.24 + k * 0.125, 0.42, 1.0, -0.15 + k * 0.125, 0.46, "bench_wood")
    return mb


def _statue_chen_yi():
    """Bronze statue on a granite pedestal (陈毅广场)."""
    mb = U.MeshBuilder()
    U.box(mb, -1.6, -1.6, 0, 1.6, 1.6, 0.6, "granite_grey")
    U.box(mb, -1.2, -1.2, 0.6, 1.2, 1.2, 3.6, "granite_dark")
    U.box(mb, -1.35, -1.35, 3.6, 1.35, 1.35, 3.8, "granite_grey")
    z = 3.8
    for s in (-1, 1):
        U.cylinder(mb, (s * 0.22, 0, z), 0.2, 2.2, 10, "bronze", r_top=0.17)
    U.cylinder(mb, (0, 0, z + 1.4), 0.62, 2.0, 14, "bronze", r_top=0.5)   # long coat
    U.cylinder(mb, (0, 0, z + 3.4), 0.5, 0.5, 12, "bronze", r_top=0.32)
    U.sphere(mb, (0, 0, z + 4.2), 0.3, 12, 8, "bronze")
    for s in (-1, 1):
        U.cylinder(mb, (s * 0.55, 0.05, z + 2.4), 0.13, 1.4, 8, "bronze", r_top=0.11)
    return mb


def _tube_path(mb, pts, radii, mat, n=10, cap=True):
    """Tapered tube along a 3D polyline (horns, tail, legs)."""
    from mathutils import Vector
    P = [Vector(p) for p in pts]
    rings = []
    for i, p in enumerate(P):
        t = (P[min(i + 1, len(P) - 1)] - P[max(i - 1, 0)]).normalized()
        ref = Vector((0, 0, 1)) if abs(t.z) < 0.9 else Vector((1, 0, 0))
        u = t.cross(ref).normalized()
        v = t.cross(u)
        r = radii[i]
        rings.append([tuple(p + (u * math.cos(2 * math.pi * k / n) + v * math.sin(2 * math.pi * k / n)) * r)
                      for k in range(n)])
    for a, b in zip(rings[:-1], rings[1:]):
        for k in range(n):
            j = (k + 1) % n
            mb.face([a[k], a[j], b[j], b[k]], mat, smooth=True)
    if cap:
        mb.face(rings[0][::-1], mat, smooth=True)
        mb.face(rings[-1], mat, smooth=True)


def _bull():
    """外滩金融牛 (Bund Bull, 2010, Arturo Di Modica), ~5.2 m long and 3.2 m tall:
    charging pose with the head lowered, horns forward and the tail whipped up.
    Head along +X. Proportions are an approximation."""
    mb = U.MeshBuilder()
    U.box(mb, -2.9, -1.1, 0, 2.9, 1.1, 0.35, "granite_dark")
    z0 = 0.35
    # body: elliptical sections along x (x, centre z, half width, half height)
    secs = [(-2.25, 1.62, 0.20, 0.30), (-2.15, 1.62, 0.42, 0.52), (-1.8, 1.60, 0.58, 0.66),
            (-1.2, 1.56, 0.66, 0.72), (-0.4, 1.56, 0.72, 0.78), (0.4, 1.66, 0.78, 0.88),
            (0.95, 1.74, 0.76, 0.92), (1.45, 1.58, 0.62, 0.78), (1.85, 1.30, 0.46, 0.56),
            (2.15, 1.02, 0.34, 0.40), (2.45, 0.84, 0.25, 0.27), (2.62, 0.76, 0.17, 0.17),
            (2.68, 0.74, 0.06, 0.06)]
    n = 18
    rings = []
    for x, zc, ry, rz in secs:
        ring = []
        for k in range(n):
            a = 2 * math.pi * k / n
            # flatter belly, rounder back
            rr = rz * (0.92 if math.sin(a) < 0 else 1.0)
            ring.append((x, ry * math.cos(a), z0 + zc + rr * math.sin(a)))
        rings.append(ring)
    for a_, b_ in zip(rings[:-1], rings[1:]):
        for k in range(n):
            j = (k + 1) % n
            mb.face([a_[k], a_[j], b_[j], b_[k]], "bronze_red", smooth=True)
    mb.face(rings[0][::-1], "bronze_red", smooth=True)
    mb.face(rings[-1], "bronze_red", smooth=True)
    # legs: front pair braced forward, hind pair pushing back
    for s in (-1, 1):
        _tube_path(mb, [(1.05, s * 0.38, z0 + 1.35), (1.35, s * 0.42, z0 + 0.75), (1.55, s * 0.40, z0 + 0.32),
                        (1.75, s * 0.40, z0 + 0.04)], [0.26, 0.16, 0.11, 0.12], "bronze_red")
        _tube_path(mb, [(-1.65, s * 0.42, z0 + 1.35), (-1.95, s * 0.44, z0 + 0.85), (-2.3, s * 0.40, z0 + 0.42),
                        (-2.55, s * 0.40, z0 + 0.04)], [0.32, 0.18, 0.11, 0.12], "bronze_red")
        # horns: out, forward and up
        _tube_path(mb, [(2.10, s * 0.24, z0 + 1.24), (2.25, s * 0.55, z0 + 1.32), (2.50, s * 0.74, z0 + 1.52),
                        (2.78, s * 0.70, z0 + 1.78)], [0.09, 0.075, 0.05, 0.015], "bronze_red", n=8)
        # ears
        _tube_path(mb, [(2.0, s * 0.30, z0 + 1.18), (1.96, s * 0.50, z0 + 1.14)], [0.07, 0.03], "bronze_red", n=6)
    # tail whipped up in an S curve
    _tube_path(mb, [(-2.2, 0, z0 + 1.85), (-2.45, 0, z0 + 2.15), (-2.35, 0.05, z0 + 2.55), (-2.0, 0.08, z0 + 2.75),
                    (-1.75, 0.05, z0 + 2.62)], [0.08, 0.06, 0.05, 0.05, 0.09], "bronze_red", n=8)
    return mb


def build_all(sc, mats, root):
    lib = U.coll("_Library_Props", root)
    col = U.coll("Street_Furniture", root)
    srcs = {}
    for name, fn in (("bund", _lamp_bund), ("promenade", _lamp_promenade), ("street", _lamp_street),
                     ("shelter", _shelter), ("bench", _bench)):
        c = U.coll(f"_prop_{name}", lib)
        U.add_obj(f"prop_{name}", fn().build(f"prop_{name}", mats), c)
        srcs[name] = c
    # signal poles: a few arm lengths
    arms = {}
    for a in (4, 6, 8, 10, 12):
        c = U.coll(f"_signal_{a}", lib)
        U.add_obj(f"signal_{a}", _signal_pole(a).build(f"signal_{a}", mats), c)
        arms[a] = c
    U.hide_collection(lib)
    for k, l in enumerate(sc.get("lamps", [])):
        U.add_instance(f"lamp_{k}", srcs.get(l["type"], srcs["street"]), col, (l["pos"][0], l["pos"][1], l["z"]), l["h"])
    for k, s in enumerate(sc.get("signals", [])):
        a = min(arms, key=lambda v: abs(v - s["arm"]))
        # pole frame: +X = travel direction, arm towards +Y (left, over the lanes)
        U.add_instance(f"signal_{k}", arms[a], col, (s["pos"][0], s["pos"][1], s["z"]), s["h"])
    for k, s in enumerate(sc.get("shelters", [])):
        U.add_instance(f"shelter_{k}", srcs["shelter"], col, (s["pos"][0], s["pos"][1], s["z"]), s["h"] + math.pi)
    # stone bollards and manhole covers (one mesh each, small)
    mb = U.MeshBuilder()
    zp = sc["levels"]["pave"]
    for x, y in sc.get("bollards", []):
        U.lathe(mb, (x, y, zp), [(0.17, 0), (0.17, 0.62), (0.12, 0.72), (0.0, 0.78)], 10, "granite_grey")
    for x, y, h, sq in sc.get("manholes", []):
        if sq:
            U.box(mb, -0.4, -0.4, 0.0, 0.4, 0.4, 0.016, "metal_black", origin=(x, y, 0), h=h)
        else:
            U.lathe(mb, (x, y, 0.0), [(0.36, 0.0), (0.36, 0.016)], 16, "metal_black", smooth=False)
    if len(mb):
        U.add_obj("Bollards_Manholes", mb.build("bollards", mats), col)
    # statues
    mb = U.MeshBuilder()
    st = _statue_chen_yi()
    bull = _bull()
    obj = U.add_obj("Statue_ChenYi_陈毅像", st.build("chen_yi", mats), col)
    obj.location = _plaza_point(sc, 213.0)
    obj.rotation_euler = (0, 0, math.pi)
    for p in sc.get("pois", []):
        if p.get("name") == "外滩牛":
            ob = U.add_obj("Bund_Bull_外滩牛", bull.build("bull", mats), col)
            ob.location = (p["pos"][0], p["pos"][1], sc["levels"]["pave"])
            # in profile against the Pudong skyline in most photos: head to the south (approximate)
            ob.rotation_euler = (0, 0, math.radians(265))
    print(f"[props] lamps {len(sc.get('lamps', []))}, signals {len(sc.get('signals', []))}")


def _plaza_point(sc, y):
    """Point on the riverside plaza between the Bund road and the deck at height y."""
    from .stage import _deck_x, _bund_x
    xd = _deck_x(sc, y)
    xr = _bund_x(sc, y)
    x = xr + (xd - xr) * 0.45
    return (x, y, sc["levels"]["pave"])
