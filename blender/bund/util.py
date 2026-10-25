"""Mesh building helpers.

Everything is accumulated into MeshBuilder objects (plain Python lists) and
turned into a single bpy mesh at the end, which is far faster than creating
thousands of small objects. UVs are in metres: horizontal faces use world XY,
vertical faces use (distance along the wall, Z); materials scale from there.
"""
import math

import bmesh
import bpy
from mathutils import Matrix, Vector
from mathutils.geometry import tessellate_polygon


# --------------------------------------------------------------------------
# collections / objects
# --------------------------------------------------------------------------

def coll(name, parent=None):
    c = bpy.data.collections.get(name)
    if c is None:
        c = bpy.data.collections.new(name)
        (parent or bpy.context.scene.collection).children.link(c)
    return c


def add_obj(name, data, collection, loc=(0, 0, 0)):
    o = bpy.data.objects.new(name, data)
    o.location = loc
    collection.objects.link(o)
    return o


def add_instance(name, src_coll, collection, loc, rot_z=0.0, scale=1.0):
    e = bpy.data.objects.new(name, None)
    e.instance_type = "COLLECTION"
    e.instance_collection = src_coll
    e.location = loc
    e.rotation_euler = (0, 0, rot_z)
    if isinstance(scale, (int, float)):
        e.scale = (scale, scale, scale)
    else:
        e.scale = scale
    collection.objects.link(e)
    e.empty_display_size = 0.5
    return e


def hide_collection(c):
    """Exclude a collection from the view layer (used for instance sources)."""
    def walk(lc):
        if lc.collection == c:
            lc.exclude = True
            return True
        return any(walk(ch) for ch in lc.children)
    walk(bpy.context.view_layer.layer_collection)


# --------------------------------------------------------------------------
# 2D polygon helpers
# --------------------------------------------------------------------------

def signed_area(ring):
    a = 0.0
    n = len(ring)
    for i in range(n):
        x0, y0 = ring[i][0], ring[i][1]
        x1, y1 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        a += x0 * y1 - x1 * y0
    return a / 2


def ccw(ring):
    return ring if signed_area(ring) > 0 else ring[::-1]


def centroid(ring):
    a = signed_area(ring)
    if abs(a) < 1e-9:
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        return sum(xs) / len(xs), sum(ys) / len(ys)
    cx = cy = 0.0
    n = len(ring)
    for i in range(n):
        x0, y0 = ring[i][0], ring[i][1]
        x1, y1 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        c = x0 * y1 - x1 * y0
        cx += (x0 + x1) * c
        cy += (y0 + y1) * c
    return cx / (6 * a), cy / (6 * a)


def pip(x, y, ring):
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def in_poly(x, y, poly):
    if not pip(x, y, poly["ext"]):
        return False
    return not any(pip(x, y, h) for h in poly.get("holes", []))


def dist_to_ring(x, y, ring):
    best = 1e18
    n = len(ring)
    for i in range(n):
        x0, y0 = ring[i][0], ring[i][1]
        x1, y1 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        dx, dy = x1 - x0, y1 - y0
        L2 = dx * dx + dy * dy
        t = 0 if L2 < 1e-12 else max(0, min(1, ((x - x0) * dx + (y - y0) * dy) / L2))
        px, py = x0 + t * dx, y0 + t * dy
        best = min(best, (x - px) ** 2 + (y - py) ** 2)
    return math.sqrt(best)


def offset_ring(ring, d, max_miter=3.0):
    """Offset a CCW ring; d>0 moves inward. Simple miter offset."""
    n = len(ring)
    out = []
    for i in range(n):
        p0 = ring[i - 1]
        p1 = ring[i]
        p2 = ring[(i + 1) % n]
        e1 = (p1[0] - p0[0], p1[1] - p0[1])
        e2 = (p2[0] - p1[0], p2[1] - p1[1])
        l1 = math.hypot(*e1) or 1e-9
        l2 = math.hypot(*e2) or 1e-9
        n1 = (-e1[1] / l1, e1[0] / l1)   # left normal = inward for CCW
        n2 = (-e2[1] / l2, e2[0] / l2)
        bx, by = n1[0] + n2[0], n1[1] + n2[1]
        bl = math.hypot(bx, by)
        if bl < 1e-6:
            bx, by = n1
            s = d
        else:
            bx, by = bx / bl, by / bl
            cos_half = bx * n1[0] + by * n1[1]
            s = d / max(cos_half, 1.0 / max_miter)
        out.append((p1[0] + bx * s, p1[1] + by * s))
    return out


def polyline_normals(pts, closed=False):
    """Miter normals (left side) and miter scale for each vertex."""
    n = len(pts)
    res = []
    for i in range(n):
        if closed:
            p0, p1, p2 = pts[i - 1], pts[i], pts[(i + 1) % n]
        else:
            p0 = pts[i - 1] if i > 0 else None
            p1 = pts[i]
            p2 = pts[i + 1] if i < n - 1 else None
        ns = []
        for a, b in ((p0, p1), (p1, p2)):
            if a is None or b is None:
                continue
            dx, dy = b[0] - a[0], b[1] - a[1]
            L = math.hypot(dx, dy)
            if L > 1e-9:
                ns.append((-dy / L, dx / L))
        if not ns:
            res.append(((0.0, 1.0), 1.0))
            continue
        if len(ns) == 1:
            res.append((ns[0], 1.0))
            continue
        bx, by = ns[0][0] + ns[1][0], ns[0][1] + ns[1][1]
        bl = math.hypot(bx, by)
        if bl < 1e-6:
            res.append((ns[0], 1.0))
            continue
        bx, by = bx / bl, by / bl
        c = bx * ns[0][0] + by * ns[0][1]
        res.append(((bx, by), 1.0 / max(c, 0.35)))
    return res


def resample(pts, step):
    out = [tuple(pts[0])]
    for a, b in zip(pts[:-1], pts[1:]):
        L = math.dist(a[:2], b[:2])
        n = max(1, int(L // step))
        for k in range(1, n + 1):
            t = k / n
            out.append(tuple(a[i] + (b[i] - a[i]) * t for i in range(len(a))))
    return out


def polyline_length(pts):
    return sum(math.dist(a[:2], b[:2]) for a, b in zip(pts[:-1], pts[1:]))


def point_along(pts, s):
    """Point and heading at arc length s along a polyline."""
    acc = 0.0
    for a, b in zip(pts[:-1], pts[1:]):
        L = math.dist(a[:2], b[:2])
        if acc + L >= s or b is pts[-1]:
            t = 0 if L < 1e-9 else (s - acc) / L
            t = max(0.0, min(1.0, t))
            p = tuple(a[i] + (b[i] - a[i]) * t for i in range(len(a)))
            return p, math.atan2(b[1] - a[1], b[0] - a[0])
        acc += L
    a, b = pts[-2], pts[-1]
    return tuple(b), math.atan2(b[1] - a[1], b[0] - a[0])


# --------------------------------------------------------------------------
# mesh builder
# --------------------------------------------------------------------------

def _auto_uv(cos):
    """Metre UVs: world XY for flat faces, (along, z) for walls."""
    if len(cos) < 3:
        return [(0, 0)] * len(cos)
    # Newell normal
    nx = ny = nz = 0.0
    n = len(cos)
    for i in range(n):
        x0, y0, z0 = cos[i]
        x1, y1, z1 = cos[(i + 1) % n]
        nx += (y0 - y1) * (z0 + z1)
        ny += (z0 - z1) * (x0 + x1)
        nz += (x0 - x1) * (y0 + y1)
    L = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
    nx, ny, nz = nx / L, ny / L, nz / L
    if abs(nz) > 0.7:
        return [(c[0], c[1]) for c in cos]
    hl = math.hypot(nx, ny) or 1.0
    tx, ty = -ny / hl, nx / hl
    return [(c[0] * tx + c[1] * ty, c[2]) for c in cos]


class MeshBuilder:
    def __init__(self):
        self.v = []
        self.f = []
        self.uv = []
        self.m = []
        self.sm = []
        self.mats = []
        self._mi = {}
        self.fattr = {}

    def mat(self, name):
        i = self._mi.get(name)
        if i is None:
            i = len(self.mats)
            self.mats.append(name)
            self._mi[name] = i
        return i

    def face(self, cos, mat, uvs=None, smooth=False, attrs=None):
        if len(cos) < 3:
            return
        base = len(self.v)
        self.v.extend(cos)
        self.f.append(tuple(range(base, base + len(cos))))
        self.uv.append(uvs if uvs is not None else _auto_uv(cos))
        self.m.append(self.mat(mat))
        self.sm.append(smooth)
        if attrs or self.fattr:
            for k in set(self.fattr) | set(attrs or {}):
                lst = self.fattr.setdefault(k, [0.0] * (len(self.f) - 1))
                lst.append((attrs or {}).get(k, 0.0))

    def shared(self, cos):
        """Add vertices and return their indices (for connected surfaces)."""
        base = len(self.v)
        self.v.extend(cos)
        return list(range(base, base + len(cos)))

    def face_idx(self, idx, mat, uvs=None, smooth=False, attrs=None):
        cos = [self.v[i] for i in idx]
        self.f.append(tuple(idx))
        self.uv.append(uvs if uvs is not None else _auto_uv(cos))
        self.m.append(self.mat(mat))
        self.sm.append(smooth)
        if attrs or self.fattr:
            for k in set(self.fattr) | set(attrs or {}):
                lst = self.fattr.setdefault(k, [0.0] * (len(self.f) - 1))
                lst.append((attrs or {}).get(k, 0.0))

    def extend(self, other):
        off = len(self.v)
        self.v.extend(other.v)
        remap = [self.mat(n) for n in other.mats]
        nf0 = len(self.f)
        for fc in other.f:
            self.f.append(tuple(i + off for i in fc))
        self.uv.extend(other.uv)
        self.m.extend(remap[i] for i in other.m)
        self.sm.extend(other.sm)
        for k in set(self.fattr) | set(other.fattr):
            a = self.fattr.setdefault(k, [0.0] * nf0)
            b = other.fattr.get(k, [0.0] * len(other.f))
            a.extend(b)

    def __len__(self):
        return len(self.f)

    def build(self, name, materials):
        me = bpy.data.meshes.new(name)
        if not self.f:
            return me
        me.from_pydata(self.v, [], self.f)
        for n in self.mats:
            me.materials.append(materials.get(n))
        nl = sum(len(fc) for fc in self.f)
        uvl = me.uv_layers.new(name="UVMap")
        flat = [0.0] * (nl * 2)
        k = 0
        for uvs in self.uv:
            for u, v in uvs:
                flat[k] = u
                flat[k + 1] = v
                k += 2
        uvl.data.foreach_set("uv", flat)
        me.polygons.foreach_set("material_index", self.m)
        me.polygons.foreach_set("use_smooth", self.sm)
        for k_, vals in self.fattr.items():
            if len(vals) < len(self.f):
                vals = vals + [0.0] * (len(self.f) - len(vals))
            a = me.attributes.new(k_, "FLOAT", "FACE")
            a.data.foreach_set("value", vals)
        me.validate(clean_customdata=False)
        me.update()
        return me


# --------------------------------------------------------------------------
# primitives (all write into a MeshBuilder)
# --------------------------------------------------------------------------

def xform(p, origin=(0, 0, 0), h=0.0):
    c, s = math.cos(h), math.sin(h)
    return (origin[0] + p[0] * c - p[1] * s, origin[1] + p[0] * s + p[1] * c, origin[2] + p[2])


def fill(mb, ext, holes, z, mat, flip=False, uv=None, attrs=None):
    """Triangulated flat polygon (with holes) at height z (or per-vertex z)."""
    loops = [ext] + list(holes or [])
    vec = []
    for lp in loops:
        vec.append([Vector((p[0], p[1], 0.0)) for p in lp])
    try:
        tris = tessellate_polygon(vec)
    except Exception:
        return
    pts = [p for lp in loops for p in lp]
    zf = (lambda p: p[2]) if (len(pts[0]) > 2 and z is None) else (lambda p: z)
    for t in tris:
        a, b, c = (pts[i] for i in t)
        cos = [(a[0], a[1], zf(a)), (b[0], b[1], zf(b)), (c[0], c[1], zf(c))]
        # tessellate_polygon returns clockwise triangles; make them face up
        area = (cos[1][0] - cos[0][0]) * (cos[2][1] - cos[0][1]) - (cos[2][0] - cos[0][0]) * (cos[1][1] - cos[0][1])
        if (area < 0) != flip:
            cos = cos[::-1]
        mb.face(cos, mat, uvs=[(q[0] * (uv or 1), q[1] * (uv or 1)) for q in cos] if uv else None, attrs=attrs)


def walls(mb, ring, z0, z1, mat, closed=True, outward=True):
    n = len(ring)
    rng_ = range(n) if closed else range(n - 1)
    acc = 0.0
    for i in rng_:
        a = ring[i]
        b = ring[(i + 1) % n]
        L = math.dist(a[:2], b[:2])
        if L < 1e-4:
            continue
        cos = [(a[0], a[1], z0), (b[0], b[1], z0), (b[0], b[1], z1), (a[0], a[1], z1)]
        if not outward:
            cos = cos[::-1]
        uvs = [(acc, z0), (acc + L, z0), (acc + L, z1), (acc, z1)]
        if not outward:
            uvs = uvs[::-1]
        mb.face(cos, mat, uvs=uvs)
        acc += L


def prism(mb, ext, holes, z0, z1, mat_side, mat_top, mat_bottom=None):
    ext = ccw(ext)
    walls(mb, ext, z0, z1, mat_side)
    for h in holes or []:
        h = ccw(h)[::-1]
        walls(mb, h, z0, z1, mat_side)
    if mat_top:
        fill(mb, ext, holes, z1, mat_top)
    if mat_bottom:
        fill(mb, ext, holes, z0, mat_bottom, flip=True)


def box(mb, x0, y0, z0, x1, y1, z1, mat, origin=None, h=0.0, faces="all", mat_top=None):
    pts = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
           (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    if origin is not None:
        pts = [xform(p, origin, h) for p in pts]
    F = {"-z": (0, 3, 2, 1), "+z": (4, 5, 6, 7), "-y": (0, 1, 5, 4), "+x": (1, 2, 6, 5),
         "+y": (2, 3, 7, 6), "-x": (3, 0, 4, 7)}
    for k, idx in F.items():
        if faces != "all" and k not in faces:
            continue
        mb.face([pts[i] for i in idx], mat_top if (mat_top and k == "+z") else mat)


def oriented_box(mb, center, size, h, mat, mat_top=None):
    sx, sy, sz = size
    box(mb, -sx / 2, -sy / 2, 0, sx / 2, sy / 2, sz, mat, origin=center, h=h, mat_top=mat_top)


def lathe(mb, center, profile, n, mat, h0=0.0, smooth=True, cap_top=True, cap_bottom=False, scale_xy=(1.0, 1.0)):
    """Surface of revolution. profile: list of (radius, z) from bottom to top."""
    cx, cy, cz = center
    rings = []
    for r, z in profile:
        ring = []
        for k in range(n):
            a = h0 + 2 * math.pi * k / n
            ring.append((cx + r * math.cos(a) * scale_xy[0], cy + r * math.sin(a) * scale_xy[1], cz + z))
        rings.append(ring)
    for j in range(len(rings) - 1):
        r0, r1 = rings[j], rings[j + 1]
        vstart = j / (len(rings) - 1)
        for k in range(n):
            k2 = (k + 1) % n
            cos = [r0[k], r0[k2], r1[k2], r1[k]]
            if profile[j][0] < 1e-6:
                cos = [r0[k], r1[k2], r1[k]]
            elif profile[j + 1][0] < 1e-6:
                cos = [r0[k], r0[k2], r1[k]]
            uvs = None
            mb.face(cos, mat, uvs=uvs, smooth=smooth)
    if cap_top and profile[-1][0] > 1e-6:
        mb.face(rings[-1], mat)
    if cap_bottom and profile[0][0] > 1e-6:
        mb.face(rings[0][::-1], mat)


def cylinder(mb, base, r, height, n, mat, r_top=None, smooth=True, cap_top=True, cap_bottom=False):
    rt = r if r_top is None else r_top
    lathe(mb, base, [(r, 0.0), (rt, height)], n, mat, smooth=smooth, cap_top=cap_top, cap_bottom=cap_bottom)


def sphere(mb, center, r, n_u, n_v, mat, z_min=-1.0, z_max=1.0, smooth=True, scale_z=1.0):
    prof = []
    a0 = math.asin(max(-1, min(1, z_min)))
    a1 = math.asin(max(-1, min(1, z_max)))
    for j in range(n_v + 1):
        a = a0 + (a1 - a0) * j / n_v
        prof.append((r * math.cos(a), r * math.sin(a) * scale_z))
    lathe(mb, center, prof, n_u, mat, smooth=smooth, cap_top=False, cap_bottom=False)


def ribbon(mb, pts, w, z, mat, closed=False, uv_along=True, attrs=None):
    """Flat strip of width w centred on a polyline."""
    if len(pts) < 2:
        return
    nrm = polyline_normals(pts, closed)
    left, right = [], []
    for p, ((nx, ny), sc) in zip(pts, nrm):
        sc = min(sc, 3.0)
        zz = p[2] if (z is None and len(p) > 2) else z
        left.append((p[0] + nx * w / 2 * sc, p[1] + ny * w / 2 * sc, zz))
        right.append((p[0] - nx * w / 2 * sc, p[1] - ny * w / 2 * sc, zz))
    n = len(pts)
    acc = 0.0
    seg = range(n) if closed else range(n - 1)
    for i in seg:
        j = (i + 1) % n
        L = math.dist(pts[i][:2], pts[j][:2])
        cos = [right[i], right[j], left[j], left[i]]
        uvs = [(acc, 0), (acc + L, 0), (acc + L, w), (acc, w)] if uv_along else None
        mb.face(cos, mat, uvs=uvs, attrs=attrs)
        acc += L


def sweep(mb, pts, profile, mat, closed=False, z_base=0.0, cap=True, uv_scale=1.0):
    """Sweep a 2D profile [(offset_left, z), ...] along a polyline.

    offset is measured to the LEFT of the path direction (outward for a CW
    path, inward for a CCW one). Each consecutive profile pair becomes a strip.
    """
    if len(pts) < 2 or len(profile) < 2:
        return
    nrm = polyline_normals(pts, closed)
    rows = []
    for (o, z) in profile:
        row = []
        for p, ((nx, ny), sc) in zip(pts, nrm):
            sc = min(sc, 3.0)
            zb = p[2] if len(p) > 2 else z_base
            row.append((p[0] + nx * o * sc, p[1] + ny * o * sc, zb + z))
        rows.append(row)
    n = len(pts)
    seg = list(range(n)) if closed else list(range(n - 1))
    for j in range(len(rows) - 1):
        r0, r1 = rows[j], rows[j + 1]
        acc = 0.0
        for i in seg:
            k = (i + 1) % n
            L = math.dist(pts[i][:2], pts[k][:2])
            cos = [r0[i], r0[k], r1[k], r1[i]]
            # keep faces pointing outward (profile listed bottom -> top, left side)
            mb.face(cos[::-1], mat)
            acc += L
    if cap and not closed:
        for row_i, rows_end in ((0, 0), (n - 1, n - 1)):
            ring = [rows[j][row_i] for j in range(len(rows))]
            if row_i == 0:
                mb.face(ring, mat)
            else:
                mb.face(ring[::-1], mat)


def wall_strip(mb, pts, z0, z1, t, mat, mat_top=None, closed=False, center=True):
    """A wall of thickness t following a polyline (z0/z1 may be callables of the point)."""
    if len(pts) < 2:
        return
    nrm = polyline_normals(pts, closed)
    L_, R_ = [], []
    for p, ((nx, ny), sc) in zip(pts, nrm):
        sc = min(sc, 3.0)
        a = t / 2 if center else t
        b = t / 2 if center else 0.0
        L_.append((p[0] + nx * a * sc, p[1] + ny * a * sc))
        R_.append((p[0] - nx * b * sc, p[1] - ny * b * sc))
    zz0 = [z0(p) if callable(z0) else z0 for p in pts]
    zz1 = [z1(p) if callable(z1) else z1 for p in pts]
    n = len(pts)
    seg = range(n) if closed else range(n - 1)
    for i in seg:
        j = (i + 1) % n
        # left face
        mb.face([(L_[j][0], L_[j][1], zz0[j]), (L_[i][0], L_[i][1], zz0[i]),
                 (L_[i][0], L_[i][1], zz1[i]), (L_[j][0], L_[j][1], zz1[j])], mat)
        # right face
        mb.face([(R_[i][0], R_[i][1], zz0[i]), (R_[j][0], R_[j][1], zz0[j]),
                 (R_[j][0], R_[j][1], zz1[j]), (R_[i][0], R_[i][1], zz1[i])], mat)
        # top
        mb.face([(R_[i][0], R_[i][1], zz1[i]), (R_[j][0], R_[j][1], zz1[j]),
                 (L_[j][0], L_[j][1], zz1[j]), (L_[i][0], L_[i][1], zz1[i])], mat_top or mat)
    if not closed:
        for i, sgn in ((0, 1), (n - 1, -1)):
            cos = [(R_[i][0], R_[i][1], zz0[i]), (L_[i][0], L_[i][1], zz0[i]),
                   (L_[i][0], L_[i][1], zz1[i]), (R_[i][0], R_[i][1], zz1[i])]
            mb.face(cos if sgn < 0 else cos[::-1], mat)


def weld_all(min_verts=500, dist=0.0005, sharp_angle=35.0):
    """Merge coincident vertices (MeshBuilder writes one vertex per face corner).

    Shrinks the .blend roughly by a third; sharp edges are re-derived from
    the face angle so smooth domes/columns still shade correctly.
    """
    n0 = n1 = 0
    for me in bpy.data.meshes:
        if me.users == 0 or me.library is not None or len(me.vertices) < min_verts:
            continue
        n0 += len(me.vertices)
        bm = bmesh.new()
        bm.from_mesh(me)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=dist)
        bm.to_mesh(me)
        bm.free()
        if hasattr(me, "set_sharp_from_angle"):
            me.set_sharp_from_angle(angle=math.radians(sharp_angle))
        n1 += len(me.vertices)
    return n0, n1
