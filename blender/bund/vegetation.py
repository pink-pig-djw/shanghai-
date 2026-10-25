"""Procedural trees, instanced across the scene.

Species used on the Bund and in Huangpu Park / 外滩源:
  plane   悬铃木 (London plane) - Shanghai's street tree, pollarded fork,
          broad crown, mottled bark
  camphor 香樟 - dense evergreen dome, dark bark (city tree of Shanghai)
  ginkgo  银杏 - upright conical crown
A few variants per species are generated once and instanced (collection
instances), so thousands of trees cost little memory.
"""
import math
import random
import zlib

from mathutils import Matrix, Vector

from . import util as U

SPECIES = {
    #          height, trunk_r, fork_h, crown_r, levels, children, spread, up_bias, leaf, bark, leaf_size, leaves_per_tip
    "plane": dict(h=14.0, r=0.32, fork=3.2, crown=5.5, levels=4, kids=(3, 4), spread=38, up=0.35,
                  leaf="leaf_plane", bark="bark_plane", leaf_size=0.34, tips=34),
    "camphor": dict(h=11.0, r=0.30, fork=2.4, crown=5.0, levels=4, kids=(3, 4), spread=46, up=0.15,
                    leaf="leaf_camphor", bark="bark_camphor", leaf_size=0.22, tips=55),
    "ginkgo": dict(h=13.0, r=0.24, fork=2.2, crown=2.8, levels=4, kids=(2, 3), spread=28, up=0.6,
                   leaf="leaf_ginkgo", bark="bark_ginkgo", leaf_size=0.2, tips=40),
}
VARIANTS = 4


def _orth(v):
    a = Vector((0, 0, 1)) if abs(v.z) < 0.9 else Vector((1, 0, 0))
    u = v.cross(a).normalized()
    w = v.cross(u).normalized()
    return u, w


def _limb(mb, p0, p1, r0, r1, mat, n=7):
    d = p1 - p0
    if d.length < 1e-4:
        return
    u, w = _orth(d.normalized())
    ring0, ring1 = [], []
    for k in range(n):
        a = 2 * math.pi * k / n
        o = u * math.cos(a) + w * math.sin(a)
        ring0.append(tuple(p0 + o * r0))
        ring1.append(tuple(p1 + o * r1))
    for k in range(n):
        j = (k + 1) % n
        mb.face([ring0[k], ring0[j], ring1[j], ring1[k]], mat, smooth=True)


def _leaf(mb, c, normal, size, mat, rnd):
    u, w = _orth(normal)
    ang = rnd.uniform(0, 2 * math.pi)
    ux = u * math.cos(ang) + w * math.sin(ang)
    wx = u.cross(normal).normalized() if False else (normal.cross(ux)).normalized()
    s = size * rnd.uniform(0.75, 1.25)
    # simple lobed leaf outline (6 points)
    pts = [(0.0, -0.5), (0.35, -0.15), (0.42, 0.2), (0.0, 0.5), (-0.42, 0.2), (-0.35, -0.15)]
    cos = [tuple(c + ux * (x * s) + wx * (y * s)) for x, y in pts]
    mb.face(cos, mat, uvs=[(x + 0.5, y + 0.5) for x, y in pts], attrs={"rnd": rnd.random()})


def make_tree(kind, seed):
    sp = SPECIES[kind]
    rnd = random.Random(seed)
    mb = U.MeshBuilder()
    H = sp["h"]
    trunk_top = Vector((rnd.uniform(-0.2, 0.2), rnd.uniform(-0.2, 0.2), sp["fork"]))
    _limb(mb, Vector((0, 0, -0.2)), trunk_top, sp["r"] * 1.15, sp["r"], sp["bark"], 9)
    tips = []

    def grow(p, d, length, r, level):
        # slight curvature: two segments
        mid = p + d * length * 0.5 + Vector((rnd.uniform(-1, 1), rnd.uniform(-1, 1), rnd.uniform(-0.2, 0.4))) * length * 0.08
        end = p + d * length
        _limb(mb, p, mid, r, r * 0.85, sp["bark"], 6 if level < 2 else 4)
        _limb(mb, mid, end, r * 0.85, r * 0.7, sp["bark"], 6 if level < 2 else 4)
        if level >= sp["levels"]:
            tips.append((end, d))
            return
        nk = rnd.randint(*sp["kids"])
        for k in range(nk):
            az = 2 * math.pi * (k + rnd.random() * 0.6) / nk
            spread = math.radians(sp["spread"] * rnd.uniform(0.7, 1.2))
            u, w = _orth(d)
            nd = (d * math.cos(spread) + (u * math.cos(az) + w * math.sin(az)) * math.sin(spread))
            nd = (nd + Vector((0, 0, sp["up"] * 0.5))).normalized()
            grow(end, nd, length * rnd.uniform(0.62, 0.78), r * 0.62, level + 1)

    # main limbs from the fork (pollarded plane trees: 3-4 limbs)
    nl = rnd.randint(3, 4) if kind != "ginkgo" else 1
    first = (H - sp["fork"]) * (0.42 if kind != "ginkgo" else 0.55)
    for k in range(nl):
        az = 2 * math.pi * (k + rnd.random() * 0.5) / nl
        tilt = math.radians(30 if kind == "plane" else (38 if kind == "camphor" else 5))
        d = Vector((math.cos(az) * math.sin(tilt), math.sin(az) * math.sin(tilt), math.cos(tilt))).normalized()
        grow(trunk_top, d, first, sp["r"] * 0.7, 1)
    if kind == "ginkgo":
        # extra side branches up the leader
        for k in range(10):
            z = sp["fork"] + (H - sp["fork"]) * (0.1 + 0.8 * k / 10)
            az = rnd.uniform(0, 2 * math.pi)
            p = Vector((0, 0, z))
            d = Vector((math.cos(az), math.sin(az), 0.55)).normalized()
            grow(p, d, sp["crown"] * (1.0 - 0.7 * k / 10), sp["r"] * 0.3, 3)
    # leaves around branch tips
    crown_c = Vector((0, 0, sp["fork"] + (H - sp["fork"]) * 0.55))
    for (p, d) in tips:
        n = sp["tips"]
        for _ in range(n):
            off = Vector((rnd.gauss(0, 0.55), rnd.gauss(0, 0.55), rnd.gauss(0, 0.4)))
            c = p + off + d * rnd.uniform(0, 0.6)
            out = (c - crown_c)
            nrm = (out.normalized() * 0.6 + Vector((rnd.uniform(-1, 1), rnd.uniform(-1, 1), rnd.uniform(-0.3, 1)))).normalized()
            _leaf(mb, c, nrm, sp["leaf_size"], sp["leaf"], rnd)
    return mb


def make_shrub(seed, r=0.7):
    rnd = random.Random(seed)
    mb = U.MeshBuilder()
    for _ in range(180):
        c = Vector((rnd.gauss(0, r * 0.5), rnd.gauss(0, r * 0.5), abs(rnd.gauss(r * 0.5, r * 0.3))))
        nrm = Vector((rnd.uniform(-1, 1), rnd.uniform(-1, 1), rnd.uniform(0, 1))).normalized()
        _leaf(mb, c, nrm, 0.16, "hedge", rnd)
    return mb


def build_all(sc, mats, root):
    lib = U.coll("_Library_Trees", root)
    col = U.coll("Trees_Vegetation", root)
    variants = {}
    for kind in SPECIES:
        for v in range(VARIANTS):
            c = U.coll(f"_tree_{kind}_{v}", lib)
            mb = make_tree(kind, zlib.crc32(f"{kind}{v}".encode()))
            U.add_obj(f"tree_{kind}_{v}", mb.build(f"tree_{kind}_{v}", mats), c)
            variants.setdefault(kind, []).append(c)
    shrubs = []
    for v in range(3):
        c = U.coll(f"_shrub_{v}", lib)
        U.add_obj(f"shrub_{v}", make_shrub(100 + v).build(f"shrub_{v}", mats), c)
        shrubs.append(c)
    U.hide_collection(lib)
    n = 0
    for x, y, z, kind, scale, rot in sc.get("trees", []):
        vs = variants.get(kind) or variants["plane"]
        src = vs[zlib.crc32(f"{x:.1f}{y:.1f}".encode()) % len(vs)]
        U.add_instance(f"tree_{n}", src, col, (x, y, z), rot, scale)
        n += 1
    # shrubs along green edges in the core area
    rnd = random.Random(7)
    core = sc["core"]
    m = 0
    for g in sc.get("green", []):
        ext = g["ext"]
        if not any(core[0] <= x <= core[2] and core[1] <= y <= core[3] for x, y in ext[:3]):
            continue
        L = U.polyline_length(ext + [ext[0]])
        k = int(L // 9)
        for i in range(k):
            p, hd = U.point_along(ext + [ext[0]], (i + rnd.random() * 0.5) * L / max(k, 1))
            # step inside the lawn
            ix, iy = p[0] - math.sin(hd) * 1.2, p[1] + math.cos(hd) * 1.2
            if U.in_poly(ix, iy, g):
                U.add_instance(f"shrub_{m}", shrubs[m % 3], col, (ix, iy, sc["levels"]["green"]), rnd.uniform(0, 6.28),
                               rnd.uniform(0.8, 1.6))
                m += 1
    print(f"[vegetation] {n} trees, {m} shrubs")
