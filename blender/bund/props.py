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


def _bull():
    """外滩金融牛 (Bund Bull), stylised."""
    mb = U.MeshBuilder()
    U.box(mb, -1.6, -1.0, 0, 1.6, 1.0, 0.5, "granite_dark")
    U.sphere(mb, (0, 0, 1.9), 1.0, 16, 10, "bronze", scale_z=0.75)
    U.lathe(mb, (0, 0, 1.4), [(0.0, 0), (0.9, 0.2), (1.0, 0.6), (0.85, 1.0), (0.0, 1.1)], 14, "bronze",
            scale_xy=(2.0, 0.85))
    U.sphere(mb, (1.9, 0, 1.6), 0.45, 12, 8, "bronze")
    for s in (-1, 1):
        U.cylinder(mb, (2.0, s * 0.3, 1.9), 0.07, 0.6, 6, "bronze", r_top=0.02)
        for x in (-1.1, 1.1):
            U.cylinder(mb, (x, s * 0.45, 0.5), 0.15, 1.1, 8, "bronze", r_top=0.12)
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
    # benches along the promenade
    rnd = random.Random(3)
    n = 0
    for e in sc.get("water_edges", []):
        if e["style"] != "bund":
            continue
        pts = e["pts"]
        L = U.polyline_length(pts)
        for k in range(int(L // 30)):
            p, hd = U.point_along(pts, (k + 0.3) * 30)
            for d in (4.5, -4.5):
                x, y = p[0] - math.sin(hd) * d, p[1] + math.cos(hd) * d
                if any(U.in_poly(x, y, dp) for dp in sc.get("deck", [])):
                    U.add_instance(f"bench_{n}", srcs["bench"], col, (x, y, sc["levels"]["deck"]), hd)
                    n += 1
                    break
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
            ob.rotation_euler = (0, 0, math.radians(200))
    print(f"[props] lamps {len(sc.get('lamps', []))}, signals {len(sc.get('signals', []))}, benches {n}")


def _plaza_point(sc, y):
    """Point on the riverside plaza between the Bund road and the deck at height y."""
    from .stage import _deck_x, _bund_x
    xd = _deck_x(sc, y)
    xr = _bund_x(sc, y)
    x = xr + (xd - xr) * 0.45
    return (x, y, sc["levels"]["pave"])
