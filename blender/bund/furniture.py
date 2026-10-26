"""Street furniture and small landscape elements, placed from the scene data.

  flower beds   granite planters planted for late October: chrysanthemums
                (yellow, white, purple, pink), scarlet sage (一串红) spikes and
                orange marigolds around a clipped shrub
  benches       slatted timber on black cast-iron frames, and granite blocks
                with timber tops
  steps         granite entrance steps in front of the historic buildings
  street items  Shanghai sorting bins (2019 rules: recyclable / residual /
                kitchen / hazardous), China Post pillar boxes, fire hydrants,
                utility cabinets, brown tourist signposts and map boards,
                large planter pots with clipped shrubs

Placement is rule based (rows along the promenade, rest areas on plazas, items
along kerbs, benches facing lawns); it is plausible, not surveyed.
Prototypes are generated once and instanced; with web=True everything is
merged into plain meshes with flower masses instead of single blooms.
"""
import math
import random
import zlib

from mathutils import Vector

from . import util as U
from .vegetation import LEAF_OVATE, _leaf

FLOWER_SCHEMES = [
    # (centre, inner ring, outer ring) materials
    ("flower_yellow", "flower_red", "flower_purple"),
    ("flower_white", "flower_yellow", "flower_red"),
    ("flower_orange", "flower_purple", "flower_yellow"),
    ("flower_pink", "flower_white", "flower_orange"),
]


# --------------------------------------------------------------------------
# prototypes
# --------------------------------------------------------------------------

def _bloom(mb, c, r, mat, rnd, kind):
    mb.cur = {"rnd": rnd.random()}
    if kind == "spike":            # scarlet sage: a tapering red spike
        U.cylinder(mb, c, r * 0.55, r * 4.5, 6, mat, r_top=0.004, smooth=True)
    elif kind == "disc":           # petunia / pansy: flat open flower
        pts = []
        for k in range(10):
            a = 2 * math.pi * k / 10
            rr = r * (1.0 if k % 2 == 0 else 0.62)
            pts.append((c[0] + math.cos(a) * rr, c[1] + math.sin(a) * rr, c[2] + rnd.uniform(-0.004, 0.004)))
        mb.face(pts, mat)
    else:                          # chrysanthemum / marigold pompom
        U.sphere(mb, c, r, 7, 4, mat, z_min=-0.15, smooth=True, scale_z=0.75)
    mb.cur = {}


def _plant_area(mb, rnd, inside, area, mat, kind, z, density=260, h=(0.18, 0.34), r=(0.025, 0.04)):
    """Fill an area (inside(x, y) -> bool, area in m2) with blooms over leaves."""
    n = int(area * density)
    x0, y0, x1, y1 = inside.bounds
    placed = 0
    for _ in range(n * 3):
        if placed >= n:
            break
        x, y = rnd.uniform(x0, x1), rnd.uniform(y0, y1)
        if not inside(x, y):
            continue
        hh = rnd.uniform(*h)
        _bloom(mb, (x, y, z + hh), rnd.uniform(*r), mat, rnd, kind)
        if placed % 2 == 0:       # foliage under the flowers
            nrm = Vector((rnd.gauss(0, 0.5), rnd.gauss(0, 0.5), 1.0)).normalized()
            _leaf(mb, Vector((x + rnd.gauss(0, 0.03), y + rnd.gauss(0, 0.03), z + hh * rnd.uniform(0.4, 0.9))),
                  nrm, Vector((rnd.gauss(0, 1), rnd.gauss(0, 1), 0.2)), 0.07, LEAF_OVATE, "leaf_flowerbed", rnd, 0.15)
        placed += 1


class _Disc:
    def __init__(self, r0, r1):
        self.r0, self.r1 = r0, r1
        self.bounds = (-r1, -r1, r1, r1)

    def __call__(self, x, y):
        d = math.hypot(x, y)
        return self.r0 <= d <= self.r1


class _Rect:
    def __init__(self, x0, y0, x1, y1):
        self.bounds = (x0, y0, x1, y1)

    def __call__(self, x, y):
        return self.bounds[0] <= x <= self.bounds[2] and self.bounds[1] <= y <= self.bounds[3]


def flowerbed_round(seed, R=2.2, web=False):
    """Raised round bed: granite kerb, three rings of flowers around a shrub."""
    rnd = random.Random(seed)
    mb = U.MeshBuilder()
    H = 0.45
    U.lathe(mb, (0, 0, 0), [(R, 0.0), (R, H), (R - 0.28, H), (R - 0.28, H - 0.06)], 40, "granite_light", smooth=False)
    U.fill(mb, [(math.cos(a) * (R - 0.27), math.sin(a) * (R - 0.27)) for a in
                (2 * math.pi * k / 40 for k in range(40))], [], H - 0.05, "soil")
    c, inner, outer = FLOWER_SCHEMES[seed % len(FLOWER_SCHEMES)]
    z = H - 0.05
    if web:
        # the same three rings of colour as the planted bed, as a low dome
        for prof, m in (([(R - 0.3, 0.0), (R - 0.35, 0.22), (R * 0.72, 0.26)], outer),
                        ([(R * 0.72, 0.26), (R * 0.42, 0.29)], inner),
                        ([(R * 0.42, 0.29), (R * 0.2, 0.3), (0.0, 0.3)], c)):
            U.lathe(mb, (0, 0, z), prof, 24, m, smooth=True, cap_top=False)
        U.sphere(mb, (0, 0, z + 0.65), 0.55, 12, 8, "hedge", z_min=-0.4)
        return mb
    rr = R - 0.32
    _plant_area(mb, rnd, _Disc(rr * 0.72, rr), math.pi * (rr ** 2 - (rr * 0.72) ** 2), outer, "pompom", z)
    _plant_area(mb, rnd, _Disc(rr * 0.42, rr * 0.72), math.pi * ((rr * 0.72) ** 2 - (rr * 0.42) ** 2), inner,
                "spike" if inner == "flower_red" else "pompom", z, h=(0.25, 0.4))
    _plant_area(mb, rnd, _Disc(0.55, rr * 0.42), math.pi * ((rr * 0.42) ** 2 - 0.55 ** 2), c, "pompom", z,
                h=(0.3, 0.45))
    # clipped shrub in the middle
    for k in range(700):
        th = rnd.uniform(0, 2 * math.pi)
        zc = rnd.uniform(-0.2, 1.0)
        q = math.sqrt(max(0.0, 1 - zc * zc))
        d = Vector((math.cos(th) * q, math.sin(th) * q, zc))
        p = Vector((d.x * 0.55, d.y * 0.55, z + 0.62 + d.z * 0.5))
        _leaf(mb, p, d, Vector((rnd.gauss(0, 1), rnd.gauss(0, 1), 0.3)), 0.07, LEAF_OVATE, "hedge", rnd, 0.15)
    U.sphere(mb, (0, 0, z + 0.62), 0.46, 10, 6, "hedge_inner", z_min=-0.5)
    return mb


def flowerbed_rect(seed, L=5.0, W=1.3, web=False):
    """Long raised bed along the promenade: two bands of colour."""
    rnd = random.Random(seed)
    mb = U.MeshBuilder()
    H = 0.5
    t = 0.22
    U.box(mb, -L / 2, -W / 2, 0, L / 2, W / 2, H, "granite_light", faces=("-x", "+x", "-y", "+y"))
    U.box(mb, -L / 2, -W / 2, H - 0.04, L / 2, -W / 2 + t, H, "granite_light", faces=("+z",))
    U.box(mb, -L / 2, W / 2 - t, H - 0.04, L / 2, W / 2, H, "granite_light", faces=("+z",))
    U.box(mb, -L / 2, -W / 2 + t, H - 0.04, -L / 2 + t, W / 2 - t, H, "granite_light", faces=("+z",))
    U.box(mb, L / 2 - t, -W / 2 + t, H - 0.04, L / 2, W / 2 - t, H, "granite_light", faces=("+z",))
    z = H - 0.06
    U.fill(mb, [(-L / 2 + t, -W / 2 + t), (L / 2 - t, -W / 2 + t), (L / 2 - t, W / 2 - t), (-L / 2 + t, W / 2 - t)],
           [], z, "soil")
    a, b, _ = FLOWER_SCHEMES[(seed + 1) % len(FLOWER_SCHEMES)]
    x0, x1, y0, y1 = -L / 2 + t + 0.02, L / 2 - t - 0.02, -W / 2 + t + 0.02, W / 2 - t - 0.02
    ym = (y0 + y1) / 2
    if web:
        U.box(mb, x0, y0, z, x1, ym, z + 0.25, a)
        U.box(mb, x0, ym, z, x1, y1, z + 0.32, b)
        return mb
    _plant_area(mb, rnd, _Rect(x0, y0, x1, ym), (x1 - x0) * (ym - y0), a, "pompom", z)
    _plant_area(mb, rnd, _Rect(x0, ym, x1, y1), (x1 - x0) * (y1 - ym), b,
                "spike" if b == "flower_red" else "pompom", z, h=(0.25, 0.4))
    return mb


def planter_pot(seed, web=False):
    """Large granite pot with a clipped ball shrub (plazas, promenade)."""
    rnd = random.Random(seed)
    mb = U.MeshBuilder()
    U.lathe(mb, (0, 0, 0), [(0.42, 0.0), (0.5, 0.08), (0.62, 0.7), (0.66, 0.78), (0.58, 0.78), (0.56, 0.72)],
            28, "granite_grey", smooth=True)
    U.fill(mb, [(math.cos(a) * 0.57, math.sin(a) * 0.57) for a in (2 * math.pi * k / 28 for k in range(28))], [],
           0.72, "soil")
    if web:
        U.sphere(mb, (0, 0, 1.25), 0.55, 12, 8, "hedge", z_min=-0.6)
        return mb
    U.sphere(mb, (0, 0, 1.25), 0.48, 10, 6, "hedge_inner", z_min=-0.6)
    for _ in range(900):
        th = rnd.uniform(0, 2 * math.pi)
        zc = rnd.uniform(-0.55, 1.0)
        q = math.sqrt(max(0.0, 1 - zc * zc))
        d = Vector((math.cos(th) * q, math.sin(th) * q, zc))
        p = Vector((d.x * 0.56, d.y * 0.56, 1.25 + d.z * 0.56))
        _leaf(mb, p, d, Vector((rnd.gauss(0, 1), rnd.gauss(0, 1), 0.3)), 0.065, LEAF_OVATE, "hedge", rnd, 0.15)
    return mb


def bench_classic():
    """1.8 m bench: timber slats on two black cast-iron frames, with backrest and arms."""
    mb = U.MeshBuilder()
    L = 1.8
    for x in (-L / 2 + 0.12, L / 2 - 0.12):
        U.box(mb, x - 0.03, -0.26, 0.0, x + 0.03, -0.2, 0.43, "metal_black")      # front leg
        U.box(mb, x - 0.03, 0.18, 0.0, x + 0.03, 0.24, 0.43, "metal_black")       # back leg
        U.box(mb, x - 0.03, -0.27, 0.40, x + 0.03, 0.25, 0.44, "metal_black")     # seat rail
        U.box(mb, x - 0.03, 0.2, 0.43, x + 0.03, 0.27, 0.86, "metal_black")       # back post
        U.box(mb, x - 0.03, -0.27, 0.6, x + 0.03, 0.22, 0.64, "metal_black")      # arm
        U.box(mb, x - 0.03, -0.27, 0.43, x + 0.03, -0.23, 0.62, "metal_black")
    for k in range(5):
        y = -0.24 + k * 0.095
        U.box(mb, -L / 2, y, 0.44, L / 2, y + 0.075, 0.47, "bench_wood")
    for k in range(3):
        z = 0.54 + k * 0.1
        U.box(mb, -L / 2 + 0.02, 0.24 + k * 0.012, z, L / 2 - 0.02, 0.27 + k * 0.012, z + 0.075, "bench_wood")
    return mb


def bench_block():
    """Granite block bench with a timber top (promenade, plazas)."""
    mb = U.MeshBuilder()
    U.box(mb, -1.0, -0.27, 0.0, 1.0, 0.27, 0.38, "granite_grey")
    for k in range(6):
        y = -0.26 + k * 0.088
        U.box(mb, -1.0, y, 0.38, 1.0, y + 0.075, 0.44, "bench_wood")
    return mb


def bins_sorting():
    """Twin litter bins: blue recyclables, black residual waste (Shanghai street standard)."""
    mb = U.MeshBuilder()
    for x, lid in ((-0.26, "bin_blue"), (0.26, "bin_black")):
        U.box(mb, x - 0.24, -0.2, 0.0, x + 0.24, 0.2, 0.86, "steel_stainless")
        U.box(mb, x - 0.25, -0.21, 0.86, x + 0.25, 0.21, 0.96, lid)
        U.box(mb, x - 0.18, -0.205, 0.55, x + 0.18, -0.2, 0.75, lid)               # label panel
        U.box(mb, x - 0.14, -0.215, 0.88, x + 0.14, -0.205, 0.93, "rubber")        # slot
    return mb


def bins_four():
    """Four-stream sorting station (recyclable, hazardous, kitchen, residual) on plazas."""
    mb = U.MeshBuilder()
    for i, lid in enumerate(("bin_blue", "bin_red", "bin_brown", "bin_black")):
        x = -0.75 + i * 0.5
        U.box(mb, x - 0.22, -0.25, 0.0, x + 0.22, 0.25, 0.95, lid)
        U.box(mb, x - 0.23, -0.26, 0.95, x + 0.23, 0.26, 1.02, "rubber")
    U.box(mb, -1.05, 0.26, 0.0, 1.05, 0.3, 1.9, "metal_dark")                      # back screen
    U.box(mb, -1.1, -0.45, 1.9, 1.1, 0.32, 1.96, "metal_dark")                     # canopy
    return mb


def post_box():
    """China Post pillar box, green."""
    mb = U.MeshBuilder()
    U.box(mb, -0.22, -0.18, 0.0, 0.22, 0.18, 0.12, "concrete")
    U.box(mb, -0.25, -0.2, 0.12, 0.25, 0.2, 1.15, "post_green")
    U.box(mb, -0.27, -0.22, 1.15, 0.27, 0.22, 1.22, "post_green")
    U.box(mb, -0.15, -0.205, 0.95, 0.15, -0.2, 1.0, "rubber")                      # slot
    U.box(mb, -0.18, -0.21, 0.55, 0.18, -0.2, 0.8, "sign_gold")                    # emblem panel
    return mb


def hydrant():
    """Above-ground fire hydrant, red."""
    mb = U.MeshBuilder()
    U.cylinder(mb, (0, 0, 0), 0.13, 0.12, 12, "hydrant_red")
    U.cylinder(mb, (0, 0, 0.12), 0.1, 0.55, 12, "hydrant_red")
    U.sphere(mb, (0, 0, 0.67), 0.11, 12, 6, "hydrant_red", z_min=0.0)
    for a in (0, math.pi):
        mb_c = (math.cos(a) * 0.1, math.sin(a) * 0.1, 0.48)
        U.box(mb, -0.04, -0.04, -0.04, 0.04, 0.04, 0.04, "hydrant_red", origin=(mb_c[0], mb_c[1], mb_c[2]))
    return mb


def utility_cabinet():
    mb = U.MeshBuilder()
    U.box(mb, -0.55, -0.22, 0.0, 0.55, 0.22, 0.15, "concrete")
    U.box(mb, -0.5, -0.2, 0.15, 0.5, 0.2, 1.45, "cabinet_grey")
    U.box(mb, -0.53, -0.23, 1.45, 0.53, 0.23, 1.5, "cabinet_grey")
    U.box(mb, -0.02, -0.205, 0.3, 0.02, -0.2, 1.35, "metal_dark")                  # door seam
    return mb


def signpost():
    """Brown bilingual tourist signpost with three finger boards."""
    mb = U.MeshBuilder()
    U.cylinder(mb, (0, 0, 0), 0.05, 3.0, 10, "metal_dark")
    for k, (z, a) in enumerate(((2.55, 0.3), (2.2, 2.4), (1.85, 4.2))):
        c, s = math.cos(a), math.sin(a)
        U.box(mb, 0.06, -0.025, z, 0.95, 0.025, z + 0.24, "sign_brown", origin=(0, 0, 0), h=a)
        U.box(mb, 0.15, -0.03, z + 0.05, 0.85, 0.03, z + 0.08, "sign_white", origin=(0, 0, 0), h=a)
    return mb


def map_board():
    mb = U.MeshBuilder()
    for x in (-0.75, 0.75):
        U.box(mb, x - 0.04, -0.04, 0.0, x + 0.04, 0.04, 2.1, "metal_dark")
    U.box(mb, -0.8, -0.05, 0.9, 0.8, 0.03, 2.05, "sign_brown")
    U.box(mb, -0.7, -0.06, 1.0, 0.7, -0.05, 1.95, "sign_cream")
    return mb


def steps_block(width, n=3, rise=0.15, tread=0.36, mat="granite_grey"):
    """Entrance steps, building face along +y at y=0, steps descend towards -y."""
    mb = U.MeshBuilder()
    for k in range(n):
        y0 = -tread * (n - k)
        z1 = rise * (k + 1)
        U.box(mb, -width / 2, y0, 0.0, width / 2, 0.0, z1, mat)
    # cheek blocks
    for x in (-width / 2 - 0.35, width / 2):
        U.box(mb, x, -tread * n, 0.0, x + 0.35, 0.0, rise * n + 0.1, "granite_light")
    return mb


# --------------------------------------------------------------------------
# placement
# --------------------------------------------------------------------------

class _Grid:
    """Point obstacles in a hash grid."""

    def __init__(self, cell=8.0):
        self.cell = cell
        self.g = {}

    def add(self, x, y, r):
        k = (int(x // self.cell), int(y // self.cell))
        self.g.setdefault(k, []).append((x, y, r))

    def free(self, x, y, r):
        cx, cy = int(x // self.cell), int(y // self.cell)
        for i in (-1, 0, 1):
            for j in (-1, 0, 1):
                for (px, py, pr) in self.g.get((cx + i, cy + j), ()):
                    if math.hypot(px - x, py - y) < r + pr:
                        return False
        return True


class _Polys:
    """Point-in-polygon lookup with bounding boxes."""

    def __init__(self, polys):
        self.items = []
        for p in polys:
            xs = [q[0] for q in p["ext"]]
            ys = [q[1] for q in p["ext"]]
            self.items.append(((min(xs), min(ys), max(xs), max(ys)), p))

    def find(self, x, y):
        for (x0, y0, x1, y1), p in self.items:
            if x0 <= x <= x1 and y0 <= y <= y1 and U.in_poly(x, y, p):
                return p
        return None


def _in_core(sc, x, y, pad=0.0):
    c = sc["core"]
    return c[0] - pad <= x <= c[2] + pad and c[1] - pad <= y <= c[3] + pad


def build_all(sc, mats, root, web=False):
    col = U.coll("Street_Furniture_Flowers", root)
    rnd = random.Random(2010)
    L = sc["levels"]
    zp, zd = L["pave"], L["deck"]
    protos = {
        "bed_round": [flowerbed_round(10 + v, R=rnd.uniform(1.8, 2.5), web=web) for v in range(4)],
        "bed_rect": [flowerbed_rect(20 + v, web=web) for v in range(3)],
        "pot": [planter_pot(30 + v, web=web) for v in range(2)],
        "bench": [bench_classic()],
        "bench_block": [bench_block()],
        "bins": [bins_sorting()],
        "bins4": [bins_four()],
        "post": [post_box()],
        "hydrant": [hydrant()],
        "cabinet": [utility_cabinet()],
        "sign": [signpost()],
        "board": [map_board()],
    }
    lib = None
    srcs = {}
    if not web:
        lib = U.coll("_Library_Furniture", root)
        for key, lst in protos.items():
            srcs[key] = []
            for i, mb in enumerate(lst):
                c = U.coll(f"_furn_{key}_{i}", lib)
                U.add_obj(f"furn_{key}_{i}", mb.build(f"furn_{key}_{i}", mats), c)
                srcs[key].append(c)
        U.hide_collection(lib)
    # web: one merged mesh per 300 m cell, so the browser can cull distant furniture
    cells = {}

    def cell_mb(x, y):
        return cells.setdefault((int(math.floor(x / 300.0)), int(math.floor(y / 300.0))), U.MeshBuilder())

    counts = {}

    def put(key, x, y, z, h, variant=None):
        lst = protos[key]
        i = variant if variant is not None else rnd.randrange(len(lst))
        counts[key] = counts.get(key, 0) + 1
        if web:
            proto = lst[i % len(lst)]
            merged = cell_mb(x, y)
            c, s = math.cos(h), math.sin(h)
            off = len(merged.v)
            merged.v.extend((x + px * c - py * s, y + px * s + py * c, z + pz) for px, py, pz in proto.v)
            remap = [merged.mat(n) for n in proto.mats]
            for f in proto.f:
                merged.f.append(tuple(k + off for k in f))
            merged.uv.extend(proto.uv)
            merged.m.extend(remap[k] for k in proto.m)
            merged.sm.extend(proto.sm)
        else:
            U.add_instance(f"furn_{key}_{counts[key]}", srcs[key][i % len(lst)], col, (x, y, z), h)

    # obstacles: trees, lamps, signals, shelters, bollards, statues
    obs = _Grid()
    for x, y, *_ in sc.get("trees", []):
        obs.add(x, y, 1.2)
    for l in sc.get("lamps", []):
        obs.add(l["pos"][0], l["pos"][1], 0.6)
    for s in sc.get("signals", []):
        obs.add(s["pos"][0], s["pos"][1], 0.8)
    for s in sc.get("shelters", []):
        obs.add(s["pos"][0], s["pos"][1], 4.0)
    for x, y in sc.get("bollards", []):
        obs.add(x, y, 0.4)
    for p in sc.get("pois", []):
        obs.add(p["pos"][0], p["pos"][1], 4.0)
    from .props import _plaza_point
    cy_ = _plaza_point(sc, 213.0)
    obs.add(cy_[0], cy_[1], 4.5)                                   # 陈毅像
    deck = _Polys(sc.get("deck", []))
    plazas = _Polys(sc.get("plaza", []))
    roads = _Polys(sc.get("road_area", []))
    greens = _Polys(sc.get("green", []))
    blds = _Polys([{"ext": poly["ext"]} for b in sc["buildings"] if b["region"] == "core" for poly in b["poly"]])

    def open_ground(x, y):
        return not roads.find(x, y) and not greens.find(x, y) and not blds.find(x, y)

    # 1. Bund promenade (flood wall deck): benches facing the river, flower beds and
    #    planter pots along the inland side, bins in between
    for e in sc.get("water_edges", []):
        if e["style"] != "bund":
            continue
        pts = e["pts"]
        Lp = U.polyline_length(pts)
        s = 6.0
        k = 0
        while s < Lp - 6.0:
            p, hd = U.point_along(pts, s)
            for side in (1, -1):
                nx, ny = -math.sin(hd) * side, math.cos(hd) * side      # candidate inland normal
                tx, ty = p[0] + nx * 3.0, p[1] + ny * 3.0
                if deck.find(tx, ty):
                    break
            else:
                s += 12.0
                continue
            face_river = math.atan2(-ny, -nx) + math.pi / 2          # bench front (-y) towards the river
            ux, uy = math.cos(hd), math.sin(hd)                       # along the promenade
            for shift in (0.0, 3.0, -3.0):
                bx, by = p[0] + nx * 2.3 + ux * shift, p[1] + ny * 2.3 + uy * shift
                if obs.free(bx, by, 1.1) and deck.find(bx, by):
                    put("bench" if k % 3 else "bench_block", bx, by, zd, face_river)
                    obs.add(bx, by, 1.1)
                    break
            # inland side: planter pot, bench, flower bed, bench ... facing the river
            ix, iy = p[0] + nx * 11.8, p[1] + ny * 11.8
            if deck.find(ix, iy) and deck.find(p[0] + nx * 12.8, p[1] + ny * 12.8):
                kind = ("pot", "bench", "bed_rect", "bench")[k % 4]
                rad = {"pot": 1.0, "bench": 1.1, "bed_rect": 2.8}[kind]
                if obs.free(ix, iy, rad):
                    put(kind, ix, iy, zd, face_river if kind == "bench" else (hd if kind == "bed_rect" else 0.0))
                    obs.add(ix, iy, rad)
            if k % 5 == 3:
                gx, gy = p[0] + nx * 2.4 + ux * 4.5, p[1] + ny * 2.4 + uy * 4.5
                if obs.free(gx, gy, 0.6) and deck.find(gx, gy):
                    put("bins", gx, gy, zd, face_river)
                    obs.add(gx, gy, 0.7)
            s += 12.0
            k += 1

    # 2. plazas: rest areas (round flower bed with benches around it), planters, a bin station
    for pg in sc.get("plaza", []):
        ext = pg["ext"]
        xs = [q[0] for q in ext]
        ys = [q[1] for q in ext]
        if not _in_core(sc, sum(xs) / len(xs), sum(ys) / len(ys), 60):
            continue
        area = abs(U.signed_area(ext))
        if area < 900:
            continue
        step = 18.0
        n_here = 0
        y = min(ys) + step / 2
        row = 0
        while y < max(ys):
            x = min(xs) + step / 2 + (step / 2 if row % 2 else 0)
            while x < max(xs):
                jx, jy = x + rnd.uniform(-3, 3), y + rnd.uniform(-3, 3)
                if (U.in_poly(jx, jy, pg) and U.dist_to_ring(jx, jy, ext) > 3.0 and obs.free(jx, jy, 3.5)
                        and not blds.find(jx, jy)):
                    v = rnd.randrange(4)
                    if n_here % 3 == 2:
                        put("pot", jx, jy, zp, 0.0)
                        obs.add(jx, jy, 1.2)
                    else:
                        put("bed_round", jx, jy, zp, rnd.uniform(0, 6.28), v)
                        obs.add(jx, jy, 3.2)
                        a0 = rnd.uniform(0, 2 * math.pi)
                        for j in range(3):
                            a = a0 + j * 2 * math.pi / 3
                            bx, by = jx + math.cos(a) * 4.3, jy + math.sin(a) * 4.3
                            if U.in_poly(bx, by, pg) and obs.free(bx, by, 1.0):
                                # bench back to the outside, facing the bed
                                put("bench", bx, by, zp, a - math.pi / 2)
                                obs.add(bx, by, 1.1)
                    n_here += 1
                x += step
            y += step * 0.866
            row += 1
        if n_here:
            for _ in range(20):
                bx, by = rnd.uniform(min(xs), max(xs)), rnd.uniform(min(ys), max(ys))
                if U.in_poly(bx, by, pg) and U.dist_to_ring(bx, by, ext) < 3.0 and obs.free(bx, by, 1.5):
                    put("bins4", bx, by, zp, rnd.choice((0, math.pi / 2, math.pi, -math.pi / 2)))
                    obs.add(bx, by, 1.5)
                    break

    # 3. along the kerbs of core streets: bins, hydrants, cabinets, post boxes
    j = 0
    for r in sc.get("roads", []):
        if r.get("level", 0) != 0 or r["class"] in ("motorway", "trunk", "service", "footway", "path"):
            continue
        pts = [tuple(q) for q in r["pts"]]
        Lr = U.polyline_length(pts)
        if Lr < 30:
            continue
        s = 15.0
        while s < Lr - 10:
            p, hd = U.point_along(pts, s)
            if not _in_core(sc, p[0], p[1]):
                s += 40.0
                continue
            for side in (1, -1):
                off = r["width"] / 2 + 0.9
                x, y = p[0] - math.sin(hd) * off * side, p[1] + math.cos(hd) * off * side
                if not open_ground(x, y) or deck.find(x, y) or not obs.free(x, y, 1.0):
                    continue
                face = hd + (0.0 if side > 0 else math.pi)              # front (-y) towards the road
                kind = ("bins", "hydrant", "bins", "cabinet", "bins", "bins", "hydrant", "bins", "cabinet",
                        "bins", "bins", "hydrant", "bins", "cabinet", "bins", "bins", "hydrant", "post")[j % 18]
                if kind == "cabinet":
                    x2, y2 = p[0] - math.sin(hd) * (off + 1.4) * side, p[1] + math.cos(hd) * (off + 1.4) * side
                    if open_ground(x2, y2):
                        x, y = x2, y2
                put(kind, x, y, zp, face)
                obs.add(x, y, 0.9)
                j += 1
            s += 42.0

    # 4. benches facing the lawns in parks and gardens
    for g in sc.get("green", []):
        ext = g["ext"]
        if not _in_core(sc, ext[0][0], ext[0][1]) or abs(U.signed_area(ext)) < 250:
            continue
        ring = U.ccw(ext)
        Lg = U.polyline_length(ring + [ring[0]])
        s = 8.0
        while s < Lg - 4:
            p, hd = U.point_along(ring + [ring[0]], s)
            # CCW ring: outward normal is to the right of the direction of travel
            ox, oy = math.sin(hd), -math.cos(hd)
            x, y = p[0] + ox * 1.4, p[1] + oy * 1.4
            if open_ground(x, y) and obs.free(x, y, 1.3) and not deck.find(x, y):
                put("bench", x, y, zp, math.atan2(oy, ox) - math.pi / 2)    # front (-y) faces the lawn
                obs.add(x, y, 1.2)
            s += 22.0

    # 5. signposts and map boards at the promenade stairs
    for i, st in enumerate(sc.get("stairs", [])):
        x, y = st["pos"]
        h = st.get("h", 0.0)
        for d in (4.5, -4.5):
            sx, sy = x + math.cos(h) * d, y + math.sin(h) * d
            if open_ground(sx, sy) and obs.free(sx, sy, 1.0):
                # the stairs join street and promenade: stand on whichever surface is here
                put("sign" if i % 2 == 0 else "board", sx, sy, zd if deck.find(sx, sy) else zp, h)
                obs.add(sx, sy, 1.0)
                break

    # 6. granite entrance steps at the historic buildings (landmarks, researched, historic)
    n_steps = 0
    for b in sc["buildings"]:
        if b["region"] != "core" or not (b.get("landmark") or b.get("style") in ("historic", "override")):
            continue
        if not b.get("landmark") and zlib.crc32(b["id"].encode()) % 10 >= 5:
            continue
        for poly in b["poly"][:1]:
            ring = U.ccw(poly["ext"])
            best = None
            for i in range(len(ring)):
                a, c = ring[i], ring[(i + 1) % len(ring)]
                Le = math.dist(a, c)
                if Le < 8:
                    continue
                mx, my = (a[0] + c[0]) / 2, (a[1] + c[1]) / 2
                ex, ey = (c[1] - a[1]) / Le, -(c[0] - a[0]) / Le          # outward (right of CCW edge)
                tx, ty = mx + ex * 2.0, my + ey * 2.0
                if not open_ground(tx, ty) or deck.find(tx, ty):
                    continue
                score = Le + (25.0 if ex > 0.5 else 0.0)                   # prefer the river front
                if best is None or score > best[0]:
                    best = (score, mx, my, math.atan2(ey, ex), Le)
            if best:
                _, mx, my, ang, Le = best
                w = max(2.4, min(7.0, 0.3 * Le))
                stp = steps_block(w, n=3 if b.get("landmark") else 2)
                h = ang + math.pi / 2                                       # local -y -> outward
                if web:
                    cell_mb(mx, my).extend(_transformed(stp, mx, my, zp, h))
                else:
                    U.add_obj(f"Entrance_Steps_{n_steps}", stp.build(f"steps_{n_steps}", mats), col,
                              loc=(mx, my, zp)).rotation_euler = (0, 0, h)
                n_steps += 1
    for (cx, cy), mb in cells.items():
        if len(mb):
            U.add_obj(f"Street_Furniture_{cx}_{cy}", mb.build(f"street_furniture_{cx}_{cy}", mats), col)
    print(f"[furniture] {counts}, entrance steps {n_steps}")


def _transformed(mb, x, y, z, h):
    out = U.MeshBuilder()
    c, s = math.cos(h), math.sin(h)
    out.v = [(x + px * c - py * s, y + px * s + py * c, z + pz) for px, py, pz in mb.v]
    out.f, out.uv, out.m, out.sm, out.mats, out._mi = list(mb.f), list(mb.uv), list(mb.m), list(mb.sm), list(mb.mats), dict(mb._mi)
    return out
