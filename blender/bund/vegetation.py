"""Vegetation: species trees, shrubs, clipped hedges and lawn grass.

Species on the Bund, in Huangpu Park and 外滩源:
  plane   悬铃木 (London plane, Platanus x acerifolia): Shanghai's street tree,
          pollarded fork, broad crown, palmate 3-5 lobed leaves, mottled bark;
          by late October the first leaves turn yellow-brown
  camphor 香樟 (Cinnamomum camphora): dense, glossy evergreen, small ovate leaves
  ginkgo  银杏: upright crown, fan-shaped leaves, turning yellow from November
Clipped shrubs: 红叶石楠 (Photinia x fraseri, red new growth) and 海桐
(Pittosporum), the usual hedges of Shanghai road medians and park edges.

Leaves are real polygons with species outlines (folded along the midrib) on
short twigs at the branch tips. A few variants per species are generated once
and instanced, so ~2000 trees cost little memory. Lawns in the core area get
grass blades and the median hedges a leafy surface, both scattered with
geometry nodes as instances (cheap to render, never realized).
"""
import math
import random
import zlib

import bpy
from mathutils import Vector

from . import util as U

# leaf outlines, petiole at the bottom (y = -0.5 .. 0.56), counter-clockwise
LEAF_PLANE = [(0.0, -0.42), (0.28, -0.32), (0.52, 0.0), (0.24, 0.05), (0.38, 0.34), (0.12, 0.22), (0.0, 0.56),
              (-0.12, 0.22), (-0.38, 0.34), (-0.24, 0.05), (-0.52, 0.0), (-0.28, -0.32)]
LEAF_OVATE = [(0.0, -0.5), (0.2, -0.3), (0.23, 0.02), (0.15, 0.32), (0.0, 0.55), (-0.15, 0.32), (-0.23, 0.02),
              (-0.2, -0.3)]
LEAF_FAN = [(0.0, -0.42), (0.42, 0.18), (0.3, 0.4), (0.06, 0.44), (0.0, 0.32), (-0.06, 0.44), (-0.3, 0.4),
            (-0.42, 0.18)]

SPECIES = {
    # h: height, r: trunk radius, fork: crown base, crown: radius, levels/kids/spread/up: branching,
    # leaf_size: m, leaves: per tree, twigs: per leaf site, outline: leaf polygon
    "plane": dict(h=14.0, r=0.32, fork=3.2, crown=5.5, levels=4, kids=(3, 4), spread=38, up=0.35,
                  leaf="leaf_plane", bark="bark_plane", leaf_size=0.2, leaves=42000, twigs=(2, 4),
                  outline=LEAF_PLANE, fold=0.12, site=0.42, leafy=2),
    "camphor": dict(h=11.0, r=0.30, fork=2.4, crown=5.0, levels=4, kids=(3, 4), spread=40, up=0.22,
                    leaf="leaf_camphor", bark="bark_camphor", leaf_size=0.11, leaves=92000, twigs=(4, 6),
                    outline=LEAF_OVATE, fold=0.18, site=0.3, leafy=3),
    "ginkgo": dict(h=13.0, r=0.24, fork=2.2, crown=2.8, levels=4, kids=(2, 3), spread=28, up=0.6,
                   leaf="leaf_ginkgo", bark="bark_ginkgo", leaf_size=0.075, leaves=36000, twigs=(3, 5),
                   outline=LEAF_FAN, fold=0.05, site=0.35, leafy=2),
}
VARIANTS = 3


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


def _leaf(mb, base, normal, tip_dir, size, outline, mat, rnd, fold=0.12):
    """One leaf polygon: petiole at `base`, blade along `tip_dir`, facing `normal`,
    folded along the midrib. UVs are leaf space (0..1, midrib at u = 0.5)."""
    t = (tip_dir - normal * tip_dir.dot(normal))
    if t.length < 1e-6:
        t, _ = _orth(normal)
    t.normalize()
    side = normal.cross(t)
    s = size * rnd.uniform(0.7, 1.3)
    c = base + t * (0.5 * s)
    cos = [tuple(c + side * (x * s) + t * (y * s) + normal * (abs(x) * fold * s)) for x, y in outline]
    mb.face(cos, mat, uvs=[(x + 0.5, y + 0.5) for x, y in outline], attrs={"rnd": rnd.random()})


def make_tree(kind, seed):
    sp = SPECIES[kind]
    rnd = random.Random(seed)
    mb = U.MeshBuilder()
    H = sp["h"]
    trunk_top = Vector((rnd.uniform(-0.2, 0.2), rnd.uniform(-0.2, 0.2), sp["fork"]))
    # trunk with a little root flare
    _limb(mb, Vector((0, 0, -0.2)), Vector((0, 0, 0.35)), sp["r"] * 1.45, sp["r"] * 1.12, sp["bark"], 16)
    _limb(mb, Vector((0, 0, 0.35)), trunk_top, sp["r"] * 1.12, sp["r"], sp["bark"], 16)
    sites = []   # leaf-bearing points: along the two finest branch orders and at the tips

    def grow(p, d, length, r, level):
        mid = p + d * length * 0.5 + Vector((rnd.uniform(-1, 1), rnd.uniform(-1, 1), rnd.uniform(-0.2, 0.4))) * length * 0.08
        end = p + d * length
        _limb(mb, p, mid, r, r * 0.85, sp["bark"], 10 if level < 2 else 5)
        _limb(mb, mid, end, r * 0.85, r * 0.7, sp["bark"], 10 if level < 2 else 5)
        if level >= sp["levels"] - sp["leafy"] + 1 or (kind == "ginkgo" and level == 1):
            nseg = max(1, int(length / sp["site"]))
            for i in range(nseg):
                f = 0.25 + 0.75 * (i + rnd.random()) / nseg
                q = (p.lerp(mid, f * 2) if f < 0.5 else mid.lerp(end, f * 2 - 1))
                sites.append((q, d, r * (1 - 0.3 * f)))
        if level >= sp["levels"]:
            sites.append((end, d, r * 0.7))
            sites.append((end, d, r * 0.7))
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
    first = (H - sp["fork"]) * (0.42 if kind != "ginkgo" else 0.5)
    for k in range(nl):
        az = 2 * math.pi * (k + rnd.random() * 0.5) / nl
        tilt = math.radians(30 if kind == "plane" else (38 if kind == "camphor" else 5))
        d = Vector((math.cos(az) * math.sin(tilt), math.sin(az) * math.sin(tilt), math.cos(tilt))).normalized()
        grow(trunk_top, d, first, sp["r"] * 0.7, 1)
    if kind == "ginkgo":
        for k in range(16):
            z = sp["fork"] + (H - sp["fork"]) * (0.05 + 0.9 * k / 16)
            az = rnd.uniform(0, 2 * math.pi)
            p = Vector((0, 0, z))
            d = Vector((math.cos(az), math.sin(az), 0.5)).normalized()
            grow(p, d, sp["crown"] * (1.05 - 0.75 * k / 16), sp["r"] * 0.3, 3)
    _foliate(mb, sp, sites, rnd, Vector((0, 0, sp["fork"] + (H - sp["fork"]) * 0.55)))
    return mb


def _foliate(mb, sp, sites, rnd, crown_c):
    """Short twigs at every leaf site, leaves alternating along each twig."""
    up = Vector((0, 0, 1))
    counts = [rnd.randint(*sp["twigs"]) for _ in sites]
    per_twig = max(3, sp["leaves"] // max(1, sum(counts)))
    for (p, d, r), nt in zip(sites, counts):
        for _ in range(nt):
            td = (d * 0.6 + Vector((rnd.gauss(0, 0.75), rnd.gauss(0, 0.75), rnd.gauss(0.1, 0.5)))).normalized()
            L = rnd.uniform(0.25, 0.6)
            start = p + Vector((rnd.gauss(0, 0.06), rnd.gauss(0, 0.06), rnd.gauss(0, 0.05)))
            end = start + td * L + Vector((0, 0, -0.06 * L))      # twigs sag under the leaves
            _limb(mb, start, end, max(0.005, r * 0.3), 0.003, sp["bark"], 3)
            out = (start - crown_c)
            out = out.normalized() if out.length > 1e-3 else up
            su, sw = _orth(td)
            k_leaves = max(2, int(per_twig * rnd.uniform(0.6, 1.4)))
            for k in range(k_leaves):
                f = (k + 0.5) / k_leaves
                at = start.lerp(end, f)
                side = 1 if k % 2 == 0 else -1
                lat = (su * side + sw * rnd.uniform(-0.7, 0.7)).normalized()
                # leaves face the light: up and out from the crown, with scatter
                nrm = (up * 0.7 + out * 0.6 + Vector((rnd.gauss(0, 0.5), rnd.gauss(0, 0.5), rnd.gauss(0, 0.3))))
                nrm = nrm.normalized()
                tip = (lat * 0.8 + td * 0.6 + Vector((0, 0, -0.3))).normalized()
                base = at + lat * rnd.uniform(0.02, 0.07)
                _leaf(mb, base, nrm, tip, sp["leaf_size"], sp["outline"], sp["leaf"], rnd, sp["fold"])


def make_shrub(seed, r=0.7, mat="hedge", red=0.0):
    """Rounded bush: a dark core with small leaves over an ellipsoid surface."""
    rnd = random.Random(seed)
    mb = U.MeshBuilder()
    rx, ry, rz = r * rnd.uniform(0.9, 1.15), r * rnd.uniform(0.9, 1.15), r * rnd.uniform(0.7, 0.9)
    U.sphere(mb, (0, 0, rz * 0.85), 1.0, 10, 6, "hedge_inner", z_min=-0.3, scale_z=1.0)
    # scale the core sphere to the bush shape
    for i in range(len(mb.v)):
        x, y, z = mb.v[i]
        mb.v[i] = (x * rx * 0.88, y * ry * 0.88, rz * 0.85 + (z - rz * 0.85) * rz * 0.88)
    n = int(2600 * r * r)
    for _ in range(n):
        th = rnd.uniform(0, 2 * math.pi)
        zc = rnd.uniform(-0.25, 1.0)
        rr = math.sqrt(max(0.0, 1 - zc * zc))
        dirv = Vector((math.cos(th) * rr, math.sin(th) * rr, zc))
        k = rnd.uniform(0.86, 1.04)
        c = Vector((dirv.x * rx * k, dirv.y * ry * k, rz * 0.85 + dirv.z * rz * k))
        nrm = (dirv + Vector((rnd.gauss(0, 0.35), rnd.gauss(0, 0.35), rnd.gauss(0.2, 0.3)))).normalized()
        tipd = Vector((rnd.gauss(0, 1), rnd.gauss(0, 1), rnd.gauss(0.3, 0.6)))
        m = "leaf_photinia_red" if (red and zc > 0.35 and rnd.random() < red) else mat
        _leaf(mb, c, nrm, tipd, rnd.uniform(0.06, 0.09), LEAF_OVATE, m, rnd, 0.15)
    return mb


def make_leaf_cluster(seed, mat, n=16, radius=0.14, size=0.07):
    """A sprig of small leaves facing +Z (scattered on hedge surfaces)."""
    rnd = random.Random(seed)
    mb = U.MeshBuilder()
    for _ in range(n):
        a = rnd.uniform(0, 2 * math.pi)
        rr = radius * math.sqrt(rnd.random())
        c = Vector((math.cos(a) * rr, math.sin(a) * rr, rnd.uniform(-0.03, 0.04)))
        nrm = Vector((rnd.gauss(0, 0.45), rnd.gauss(0, 0.45), 1.0)).normalized()
        tipd = Vector((math.cos(a), math.sin(a), rnd.uniform(-0.2, 0.5)))
        _leaf(mb, c, nrm, tipd, size, LEAF_OVATE, mat, rnd, 0.15)
    return mb


def make_grass_patch(seed, n=1300, radius=0.62):
    """A disc of lawn grass blades (city park lawn, mown ~10 cm); about one in
    ten blades is already dry and yellow in late October (see grass_blade)."""
    rnd = random.Random(seed)
    mb = U.MeshBuilder()
    for _ in range(n):
        a = rnd.uniform(0, 2 * math.pi)
        rr = radius * math.sqrt(rnd.random()) * rnd.uniform(0.8, 1.0)
        x, y = math.cos(a) * rr, math.sin(a) * rr
        th = rnd.uniform(0, math.pi)
        h = rnd.uniform(0.05, 0.13) if rnd.random() < 0.9 else rnd.uniform(0.13, 0.2)
        w = rnd.uniform(0.0035, 0.006)
        la = rnd.uniform(0, 2 * math.pi)
        lean = h * rnd.uniform(0.1, 0.55)
        cx, cy = math.cos(th) * w / 2, math.sin(th) * w / 2
        lx, ly = math.cos(la), math.sin(la)
        zt = h * (1 - 0.25 * (lean / h) ** 2)
        b0, b1 = (x - cx, y - cy, 0.0), (x + cx, y + cy, 0.0)
        mx, my, mz = x + lx * lean * 0.3, y + ly * lean * 0.3, zt * 0.55
        m0, m1 = (mx - cx * 0.8, my - cy * 0.8, mz), (mx + cx * 0.8, my + cy * 0.8, mz)
        tip = (x + lx * lean, y + ly * lean, zt)
        r_ = rnd.random()
        mb.face([b0, b1, m1, m0], "grass_blade", uvs=[(0, 0), (1, 0), (1, 0.55), (0, 0.55)], attrs={"rnd": r_})
        mb.face([m0, m1, tip], "grass_blade", uvs=[(0, 0.55), (1, 0.55), (0.5, 1.0)], attrs={"rnd": r_})
    return mb


# --------------------------------------------------------------------------
# geometry-nodes scatter (instances only, never realized)
# --------------------------------------------------------------------------

def scatter_group(name, align_to_normal, min_normal_z=-1.0):
    """Node group: Poisson-scatter instances of a collection over the mesh.
    Inputs: Collection, Distance (min spacing), Density (max), Seed,
    Scale Min/Max, Tilt (radians of random tilt)."""
    ng = bpy.data.node_groups.get(name)
    if ng is not None:
        return ng
    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
    sk = {}
    for nm, typ, io in (("Geometry", "NodeSocketGeometry", "INPUT"), ("Collection", "NodeSocketCollection", "INPUT"),
                        ("Distance", "NodeSocketFloat", "INPUT"), ("Density", "NodeSocketFloat", "INPUT"),
                        ("Seed", "NodeSocketInt", "INPUT"), ("Scale Min", "NodeSocketFloat", "INPUT"),
                        ("Scale Max", "NodeSocketFloat", "INPUT"), ("Tilt", "NodeSocketFloat", "INPUT"),
                        ("Geometry", "NodeSocketGeometry", "OUTPUT")):
        sk[(nm, io)] = ng.interface.new_socket(name=nm, in_out=io, socket_type=typ)
    N, L = ng.nodes.new, ng.links.new
    gi, go = N("NodeGroupInput"), N("NodeGroupOutput")

    def out(node, name):
        return next(o for o in node.outputs if o.name == name and o.enabled)

    def inp(node, name, k=0):
        return [i for i in node.inputs if i.name == name and i.enabled][k]

    dist = N("GeometryNodeDistributePointsOnFaces")
    dist.distribute_method = "POISSON"
    L(out(gi, "Geometry"), inp(dist, "Mesh"))
    L(out(gi, "Distance"), inp(dist, "Distance Min"))
    L(out(gi, "Density"), inp(dist, "Density Max"))
    L(out(gi, "Seed"), inp(dist, "Seed"))
    if min_normal_z > -1.0:
        nrm = N("GeometryNodeInputNormal")
        sep = N("ShaderNodeSeparateXYZ")
        L(nrm.outputs[0], sep.inputs[0])
        cmp_ = N("FunctionNodeCompare")
        cmp_.data_type = "FLOAT"
        cmp_.operation = "GREATER_THAN"
        L(sep.outputs[2], inp(cmp_, "A"))
        inp(cmp_, "B").default_value = min_normal_z
        L(out(cmp_, "Result"), inp(dist, "Selection"))
    # random rotation: tilt about X/Y, full spin about Z
    rv = N("FunctionNodeRandomValue")
    rv.data_type = "FLOAT_VECTOR"
    neg = N("ShaderNodeMath")
    neg.operation = "MULTIPLY"
    L(out(gi, "Tilt"), neg.inputs[0])
    neg.inputs[1].default_value = -1.0
    cmin, cmax = N("ShaderNodeCombineXYZ"), N("ShaderNodeCombineXYZ")
    L(neg.outputs[0], cmin.inputs[0])
    L(neg.outputs[0], cmin.inputs[1])
    L(out(gi, "Tilt"), cmax.inputs[0])
    L(out(gi, "Tilt"), cmax.inputs[1])
    cmax.inputs[2].default_value = 2 * math.pi
    L(cmin.outputs[0], inp(rv, "Min"))
    L(cmax.outputs[0], inp(rv, "Max"))
    L(out(gi, "Seed"), inp(rv, "Seed"))
    e2r = N("FunctionNodeEulerToRotation")
    L(out(rv, "Value"), e2r.inputs[0])
    rot = out(e2r, "Rotation")
    if align_to_normal:
        comb = N("FunctionNodeRotateRotation")
        L(out(dist, "Rotation"), inp(comb, "Rotation"))
        L(rot, inp(comb, "Rotate By"))
        comb.rotation_space = "LOCAL"
        rot = out(comb, "Rotation")
    rs = N("FunctionNodeRandomValue")
    rs.data_type = "FLOAT"
    L(out(gi, "Scale Min"), inp(rs, "Min"))
    L(out(gi, "Scale Max"), inp(rs, "Max"))
    seed2 = N("ShaderNodeMath")
    seed2.operation = "ADD"
    L(out(gi, "Seed"), seed2.inputs[0])
    seed2.inputs[1].default_value = 17
    L(seed2.outputs[0], inp(rs, "Seed"))
    ci = N("GeometryNodeCollectionInfo")
    ci.transform_space = "ORIGINAL"
    L(out(gi, "Collection"), inp(ci, "Collection"))
    inp(ci, "Separate Children").default_value = True
    inp(ci, "Reset Children").default_value = True
    pick = N("FunctionNodeRandomValue")
    pick.data_type = "INT"
    inp(pick, "Min", 0).default_value = 0
    inp(pick, "Max", 0).default_value = 99
    L(seed2.outputs[0], inp(pick, "Seed"))
    iop = N("GeometryNodeInstanceOnPoints")
    L(out(dist, "Points"), inp(iop, "Points"))
    L(out(ci, "Instances"), inp(iop, "Instance"))
    inp(iop, "Pick Instance").default_value = True
    L(out(pick, "Value"), inp(iop, "Instance Index"))
    L(rot, inp(iop, "Rotation"))
    L(out(rs, "Value"), inp(iop, "Scale"))
    join = N("GeometryNodeJoinGeometry")
    L(out(gi, "Geometry"), join.inputs[0])
    L(out(iop, "Instances"), join.inputs[0])
    L(join.outputs[0], go.inputs[0])
    ng["_sockets"] = {f"{k[0]}|{k[1]}": v.identifier for k, v in sk.items()}
    return ng


def _set_input(mod, ident, value):
    """Geometry-nodes modifier input: Blender 5.x API, else the 3.x/4.x ID property."""
    props = getattr(mod, "properties", None)
    if props is not None and hasattr(props, "inputs"):
        getattr(props.inputs, ident).value = value
    else:
        mod[ident] = value


def add_scatter(ob, group, coll, distance, density, seed=1, scale=(0.85, 1.2), tilt=0.15):
    mod = ob.modifiers.new("Scatter_" + coll.name.strip("_"), "NODES")
    mod.node_group = group
    ids = dict(group["_sockets"])
    for key, val in (("Collection", coll), ("Distance", float(distance)), ("Density", float(density)),
                     ("Seed", int(seed)), ("Scale Min", float(scale[0])), ("Scale Max", float(scale[1])),
                     ("Tilt", float(tilt))):
        _set_input(mod, ids[key + "|INPUT"], val)
    return mod


# --------------------------------------------------------------------------

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
    for v in range(4):
        c = U.coll(f"_shrub_{v}", lib)
        mb = make_shrub(100 + v, r=0.75, mat="hedge", red=0.55 if v % 2 else 0.0)
        U.add_obj(f"shrub_{v}", mb.build(f"shrub_{v}", mats), c)
        shrubs.append(c)
    # scatter sources: grass patches and hedge sprigs
    grass_c = U.coll("_grass_patches", lib)
    for v in range(4):
        U.add_obj(f"grass_patch_{v}", make_grass_patch(500 + v).build(f"grass_patch_{v}", mats), grass_c)
    sprig_c = U.coll("_hedge_sprigs", lib)
    for v in range(5):
        mat = "leaf_photinia_red" if v == 4 else "hedge"
        U.add_obj(f"hedge_sprig_{v}", make_leaf_cluster(700 + v, mat).build(f"hedge_sprig_{v}", mats), sprig_c)
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
        k = int(L // 7)
        for i in range(k):
            p, hd = U.point_along(ext + [ext[0]], (i + rnd.random() * 0.5) * L / max(k, 1))
            ix, iy = p[0] - math.sin(hd) * 1.2, p[1] + math.cos(hd) * 1.2
            if U.in_poly(ix, iy, g):
                U.add_instance(f"shrub_{m}", shrubs[m % len(shrubs)], col, (ix, iy, sc["levels"]["green"]),
                               rnd.uniform(0, 6.28), rnd.uniform(0.8, 1.5))
                m += 1
    # lawn grass and leafy hedges (geometry nodes instances)
    lawn = bpy.data.objects.get("Lawns_Core")
    if lawn is not None:
        g = scatter_group("Bund_Scatter_Upright", align_to_normal=False, min_normal_z=0.5)
        # Poisson disk: candidates at 25/m2 thinned to >= 0.48 m apart (~3.5 patches/m2,
        # each a 0.62 m disc of ~1300 blades, so the discs overlap and close the lawn)
        add_scatter(lawn, g, grass_c, distance=0.48, density=25.0, seed=3, scale=(0.85, 1.25), tilt=0.12)
    hedges = bpy.data.objects.get("Median_Hedges")
    if hedges is not None:
        g = scatter_group("Bund_Scatter_Surface", align_to_normal=True)
        add_scatter(hedges, g, sprig_c, distance=0.15, density=160.0, seed=5, scale=(0.8, 1.3), tilt=0.5)
    print(f"[vegetation] {n} trees, {m} shrubs, lawn grass {'on' if lawn else 'off'}, "
          f"hedges {'on' if hedges else 'off'}")
