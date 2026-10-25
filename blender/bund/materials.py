"""Procedural PBR materials (no image textures needed).

All patterns are driven by the mesh UVs, which are in metres (see util.py),
so brick courses, paving joints and stone blocks have real-world sizes.
Window glass faces carry 0..1 UVs plus a per-face "rnd" attribute that the
window shaders use to vary interiors, blinds and lit rooms.
"""
import bpy

MATS = {}


def lin(c):
    """sRGB (0-255 tuple or hex string) -> linear RGBA."""
    if isinstance(c, str):
        c = c.lstrip("#")
        c = tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    out = []
    for v in c[:3]:
        v = v / 255.0 if max(c[:3]) > 1.0 else v
        out.append(v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4)
    return (*out, 1.0)


def mix_rgb(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3)) + (1.0,)


class NB:
    """Tiny node-tree builder."""

    def __init__(self, mat):
        if hasattr(mat, "use_nodes") and not mat.use_nodes:
            mat.use_nodes = True
        self.nt = mat.node_tree
        self.nt.nodes.clear()
        self.x = 0
        self.out = self.nt.nodes.new("ShaderNodeOutputMaterial")
        self.out.location = (1200, 0)

    PROPS = {"operation", "data_type", "blend_type", "noise_dimensions", "attribute_name",
             "wave_type", "bands_direction", "rings_direction", "voronoi_dimensions", "feature",
             "distance", "interpolation_type", "noise_type", "gradient_type", "attribute_type",
             "vector_type", "clamp_type"}

    def n(self, typ, **kw):
        node = self.nt.nodes.new(typ)
        node.location = (self.x, -len(self.nt.nodes) * 40)
        self.x = (self.x + 180) % 1000
        for k, v in kw.items():
            if k in self.PROPS:
                setattr(node, k, v)
            else:
                self.set(node, k, v)
        return node

    @staticmethod
    def sock(node, key, out=False):
        socks = node.outputs if out else node.inputs
        if isinstance(key, int):
            return socks[key]
        cands = [s for s in socks if s.name == key]
        en = [s for s in cands if getattr(s, "enabled", True)]
        if en:
            return en[0]
        if cands:
            return cands[0]
        alias = {"Factor": "Fac", "Fac": "Factor"}
        if key in alias:
            return NB.sock(node, alias[key], out)
        raise KeyError(f"{node.bl_idname} has no socket {key}")

    def set(self, node, key, value):
        s = self.sock(node, key)
        s.default_value = value

    def link(self, a, b):
        self.nt.links.new(a, b)

    def o(self, node, key=0):
        return self.sock(node, key, out=True)

    def i(self, node, key):
        return self.sock(node, key)

    # convenience -------------------------------------------------------
    def uv(self):
        return self.o(self.n("ShaderNodeTexCoord"), "UV")

    def pos(self):
        return self.o(self.n("ShaderNodeNewGeometry"), "Position")

    def obj_rand(self):
        return self.o(self.n("ShaderNodeObjectInfo"), "Random")

    def attr(self, name):
        a = self.n("ShaderNodeAttribute", attribute_name=name)
        return self.o(a, "Factor") if any(s.name == "Factor" for s in a.outputs) else self.o(a, "Fac")

    def math(self, op, a, b=None, c=None, clamp=False):
        m = self.n("ShaderNodeMath", operation=op)
        m.use_clamp = clamp
        for idx, v in enumerate((a, b, c)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                m.inputs[idx].default_value = v
            else:
                self.link(v, m.inputs[idx])
        return m.outputs[0]

    def vmath(self, op, a, b=None, scale=None):
        m = self.n("ShaderNodeVectorMath", operation=op)
        for idx, v in enumerate((a, b)):
            if v is None:
                continue
            if isinstance(v, (tuple, list)):
                m.inputs[idx].default_value = v
            else:
                self.link(v, m.inputs[idx])
        if scale is not None:
            m.inputs[3].default_value = scale
        return m.outputs[0]

    def noise(self, vec, scale, detail=4.0, rough=0.55, dist=0.0, dims="3D", out="Factor"):
        t = self.n("ShaderNodeTexNoise", noise_dimensions=dims)
        self.set(t, "Scale", scale)
        self.set(t, "Detail", detail)
        self.set(t, "Roughness", rough)
        self.set(t, "Distortion", dist)
        if vec is not None:
            self.link(vec, t.inputs[0])
        return t.outputs[0] if out == "Factor" else t.outputs[1]

    def voronoi(self, vec, scale, out="Distance", feature="F1"):
        t = self.n("ShaderNodeTexVoronoi", feature=feature)
        self.set(t, "Scale", scale)
        if vec is not None:
            self.link(vec, t.inputs[0])
        return self.o(t, out)

    def ramp(self, fac, stops):
        r = self.n("ShaderNodeValToRGB")
        el = r.color_ramp.elements
        while len(el) > len(stops):
            el.remove(el[-1])
        while len(el) < len(stops):
            el.new(0.5)
        for e, (pos, col) in zip(el, stops):
            e.position = pos
            e.color = col if len(col) == 4 else (*col, 1.0)
        self.link(fac, r.inputs[0])
        return r.outputs[0]

    def mix(self, fac, a, b, blend="MIX"):
        m = self.n("ShaderNodeMix", data_type="RGBA", blend_type=blend)
        ins = [s for s in m.inputs if getattr(s, "enabled", True)]
        f, A, B = ins[0], ins[1], ins[2]
        for sock, v in ((f, fac), (A, a), (B, b)):
            if isinstance(v, (int, float)):
                sock.default_value = (v, v, v, 1.0) if sock.type == "RGBA" else v
            elif isinstance(v, tuple):
                sock.default_value = v
            else:
                self.link(v, sock)
        return [s for s in m.outputs if getattr(s, "enabled", True)][0]

    def bump(self, height, strength=0.2, distance=0.02, normal=None):
        b = self.n("ShaderNodeBump")
        self.set(b, "Strength", strength)
        self.set(b, "Distance", distance)
        self.link(height, self.i(b, "Height"))
        if normal is not None:
            self.link(normal, self.i(b, "Normal"))
        return b.outputs[0]

    def bsdf(self, color, rough=0.6, metal=0.0, normal=None, spec=0.5, **kw):
        p = self.n("ShaderNodeBsdfPrincipled")
        for k, v in (("Base Color", color), ("Roughness", rough), ("Metallic", metal),
                     ("Normal", normal), ("Specular IOR Level", spec)):
            if v is None:
                continue
            if isinstance(v, (int, float, tuple)):
                self.set(p, k, v)
            else:
                self.link(v, self.i(p, k))
        for k, v in kw.items():
            k = k.replace("_", " ")
            if isinstance(v, (int, float, tuple)):
                self.set(p, k, v)
            else:
                self.link(v, self.i(p, k))
        return p.outputs[0]

    def output(self, shader, displacement=None):
        self.link(shader, self.out.inputs[0])

    def grime(self, col, uv, base_rgb, amount=0.55, splash=0.3, distance=0.9):
        """Darken crevices (ambient occlusion) and the splash zone near the ground."""
        ao = self.n("ShaderNodeAmbientOcclusion")
        try:
            ao.samples = 6
        except Exception:
            pass
        self.set(ao, "Distance", distance)
        occl = self.math("POWER", self.math("SUBTRACT", 1.0, self.o(ao, "AO"), clamp=True), 1.3)
        dark = mix_rgb(base_rgb, (0.02, 0.02, 0.018), 0.55)
        col = self.mix(self.math("MULTIPLY", occl, amount), col, dark)
        sep = self.n("ShaderNodeSeparateXYZ")
        self.link(uv, sep.inputs[0])
        # walls carry metres of height in uv.y; ground faces use world y (large) -> no effect
        zf = self.math("SUBTRACT", 1.0, self.math("DIVIDE", self.o(sep, "Y"), 1.4), clamp=True)
        nz = self.n("ShaderNodeNewGeometry")
        sepn = self.n("ShaderNodeSeparateXYZ")
        self.link(self.o(nz, "Normal"), sepn.inputs[0])
        wallmask = self.math("LESS_THAN", self.math("ABSOLUTE", self.o(sepn, "Z")), 0.5)
        col = self.mix(self.math("MULTIPLY", self.math("MULTIPLY", zf, wallmask), splash), col,
                       mix_rgb(base_rgb, (0.03, 0.028, 0.02), 0.6))
        return col


def _tidal(nb, col, rough, uv, base, high):
    """Wet, algae-stained band below the high-water mark (wall uv.y is absolute z)."""
    sep = nb.n("ShaderNodeSeparateXYZ")
    nb.link(uv, sep.inputs[0])
    edge = nb.math("ADD", high, nb.math("MULTIPLY", nb.noise(uv, 0.7, 3), 0.5))
    f = nb.math("DIVIDE", nb.math("SUBTRACT", edge, nb.o(sep, "Y")), 0.35)
    f = nb.math("MINIMUM", nb.math("MAXIMUM", f, 0.0), 1.0)
    wet = nb.mix(nb.math("MULTIPLY", nb.noise(uv, 1.3, 3), 0.8), mix_rgb(base, lin((34, 38, 26)), 0.82),
                 mix_rgb(base, lin((58, 56, 40)), 0.7))
    col = nb.mix(f, col, wet)
    rough = nb.mix(f, rough, 0.32) if not isinstance(rough, (int, float)) else nb.mix(f, (rough,) * 3 + (1.0,), (0.32, 0.32, 0.32, 1.0))
    return col, rough


def new_mat(name):
    m = bpy.data.materials.get(name)
    if m is None:
        m = bpy.data.materials.new(name)
    MATS[name] = m
    return m


# --------------------------------------------------------------------------
# building materials
# --------------------------------------------------------------------------

def stone(name, rgb, var=0.12, rough=0.62, block=(1.1, 0.48), joint=0.006, streaks=0.18,
          rustic=False, speckle=0.06, tidal=None):
    """Ashlar facade stone (granite / sandstone) with weathering streaks."""
    m = new_mat(name)
    nb = NB(m)
    uv = nb.uv()
    base = lin(rgb)
    dark = mix_rgb(base, (0.05, 0.05, 0.05), 0.35)
    light = mix_rgb(base, (1, 1, 1), 0.12)
    n1 = nb.noise(uv, 0.35, 3, 0.5)
    col = nb.mix(n1, light, dark)
    col = nb.mix(nb.math("MULTIPLY", nb.noise(uv, 1.7, 2), var * 3), col, dark)
    # granite speckle
    sp = nb.noise(uv, 140.0, 1, 0.5)
    spm = nb.math("GREATER_THAN", sp, 0.62)
    col = nb.mix(nb.math("MULTIPLY", spm, speckle * 4), col, (0.03, 0.03, 0.03, 1))
    # vertical rain streaks: noise stretched along Z (uv.y)
    sep = nb.n("ShaderNodeSeparateXYZ")
    nb.link(uv, sep.inputs[0])
    st_vec = nb.n("ShaderNodeCombineXYZ")
    nb.link(nb.math("MULTIPLY", nb.o(sep, "X"), 2.2), st_vec.inputs[0])
    nb.link(nb.math("MULTIPLY", nb.o(sep, "Y"), 0.08), st_vec.inputs[1])
    st = nb.noise(st_vec.outputs[0], 1.0, 3, 0.6)
    st = nb.math("POWER", nb.math("SUBTRACT", 1.0, st, clamp=True), 3.0)
    col = nb.mix(nb.math("MULTIPLY", st, streaks * 3), col, mix_rgb(base, (0.02, 0.02, 0.018), 0.6))
    # ashlar blocks
    br = nb.n("ShaderNodeTexBrick")
    nb.set(br, "Scale", 1.0)
    nb.set(br, "Brick Width", block[0])
    nb.set(br, "Row Height", block[1])
    nb.set(br, "Mortar Size", joint if not rustic else 0.035)
    nb.set(br, "Mortar Smooth", 0.3)
    nb.set(br, "Bias", 0.0)
    nb.set(br, "Color1", (1, 1, 1, 1))
    nb.set(br, "Color2", (0.86, 0.86, 0.86, 1))
    nb.set(br, "Mortar", (0, 0, 0, 1))
    nb.link(uv, br.inputs[0])
    bcol = br.outputs[0]
    col = nb.mix(0.10, col, bcol, blend="MULTIPLY")
    joint_mask = nb.math("SUBTRACT", 1.0, br.outputs[1])
    col = nb.mix(nb.math("MULTIPLY", br.outputs[1], 0.35), col, dark)
    h = nb.math("ADD", nb.math("MULTIPLY", joint_mask, 1.0 if not rustic else 3.0),
                nb.math("MULTIPLY", nb.noise(uv, 9.0, 4), 0.25))
    nrm = nb.bump(h, 0.35 if not rustic else 0.9, 0.01 if not rustic else 0.03)
    r = nb.math("ADD", rough, nb.math("MULTIPLY", st, 0.12))
    col = nb.grime(col, uv, base)
    if tidal is not None:
        col, r = _tidal(nb, col, r, uv, base, tidal)
    nb.output(nb.bsdf(col, r, normal=nrm, spec=0.35))
    return m


def plaster(name, rgb, var=0.08, rough=0.8, streaks=0.25):
    m = new_mat(name)
    nb = NB(m)
    uv = nb.uv()
    base = lin(rgb)
    dark = mix_rgb(base, (0.06, 0.055, 0.05), 0.4)
    col = nb.mix(nb.math("MULTIPLY", nb.noise(uv, 0.6, 4, 0.6), var * 4), base, dark)
    sep = nb.n("ShaderNodeSeparateXYZ")
    nb.link(uv, sep.inputs[0])
    sv = nb.n("ShaderNodeCombineXYZ")
    nb.link(nb.math("MULTIPLY", nb.o(sep, "X"), 1.5), sv.inputs[0])
    nb.link(nb.math("MULTIPLY", nb.o(sep, "Y"), 0.1), sv.inputs[1])
    st = nb.math("POWER", nb.math("SUBTRACT", 1.0, nb.noise(sv.outputs[0], 1.0, 3), clamp=True), 3.0)
    col = nb.mix(nb.math("MULTIPLY", st, streaks * 3), col, mix_rgb(base, (0.03, 0.03, 0.03), 0.55))
    nrm = nb.bump(nb.noise(uv, 25.0, 5, 0.7), 0.12, 0.005)
    col = nb.grime(col, uv, base)
    nb.output(nb.bsdf(col, rough, normal=nrm, spec=0.3))
    return m


def brick(name, rgb1, rgb2, mortar=(185, 180, 170), bw=0.24, bh=0.065, band=None, band_rgb=None,
          streaks=0.2, rough=0.85):
    """Brick facade. band=(period, height) adds stone string courses (e.g. 汇中饭店)."""
    m = new_mat(name)
    nb = NB(m)
    uv = nb.uv()
    br = nb.n("ShaderNodeTexBrick")
    nb.set(br, "Scale", 1.0)
    nb.set(br, "Brick Width", bw)
    nb.set(br, "Row Height", bh)
    nb.set(br, "Mortar Size", 0.009)
    nb.set(br, "Mortar Smooth", 0.2)
    nb.set(br, "Bias", 0.0)
    nb.set(br, "Color1", lin(rgb1))
    nb.set(br, "Color2", lin(rgb2))
    nb.set(br, "Mortar", lin(mortar))
    nb.link(uv, br.inputs[0])
    col = br.outputs[0]
    var = nb.noise(uv, 3.0, 3)
    col = nb.mix(nb.math("MULTIPLY", var, 0.25), col, mix_rgb(lin(rgb1), (0.02, 0.02, 0.02), 0.5))
    sep = nb.n("ShaderNodeSeparateXYZ")
    nb.link(uv, sep.inputs[0])
    sv = nb.n("ShaderNodeCombineXYZ")
    nb.link(nb.math("MULTIPLY", nb.o(sep, "X"), 1.8), sv.inputs[0])
    nb.link(nb.math("MULTIPLY", nb.o(sep, "Y"), 0.09), sv.inputs[1])
    st = nb.math("POWER", nb.math("SUBTRACT", 1.0, nb.noise(sv.outputs[0], 1.0, 3), clamp=True), 3.0)
    col = nb.mix(nb.math("MULTIPLY", st, streaks * 3), col, (0.02, 0.018, 0.016, 1))
    h = nb.math("SUBTRACT", 1.0, br.outputs[1])
    if band:
        period, bhgt = band
        y = nb.o(sep, "Y")
        fr = nb.math("FRACT", nb.math("DIVIDE", y, period))
        bm = nb.math("LESS_THAN", fr, bhgt / period)
        bandcol = lin(band_rgb or (215, 205, 190))
        bandcol = nb.mix(nb.math("MULTIPLY", st, 0.6), bandcol, mix_rgb(bandcol, (0.05, 0.05, 0.05), 0.5))
        col = nb.mix(bm, col, bandcol)
        h = nb.mix(bm, h, 0.6)
    nrm = nb.bump(h, 0.5, 0.008)
    col = nb.grime(col, uv, lin(rgb1), amount=0.45)
    nb.output(nb.bsdf(col, rough, normal=nrm, spec=0.3))
    return m


def roof_tiles(name, rgb, rough=0.7, glazed=False, pitch=0.25):
    m = new_mat(name)
    nb = NB(m)
    uv = nb.uv()
    sep = nb.n("ShaderNodeSeparateXYZ")
    nb.link(uv, sep.inputs[0])
    # rows of tiles along one axis, round ridges along the other
    u = nb.o(sep, "X")
    v = nb.o(sep, "Y")
    wav = nb.math("SINE", nb.math("MULTIPLY", u, 6.2831 / pitch))
    rows = nb.math("FRACT", nb.math("DIVIDE", v, 0.32))
    h = nb.math("ADD", nb.math("MULTIPLY", wav, 0.5), nb.math("MULTIPLY", rows, 0.4))
    base = lin(rgb)
    col = nb.mix(nb.math("MULTIPLY", nb.noise(uv, 1.2, 3), 0.6), base, mix_rgb(base, (0, 0, 0), 0.45))
    col = nb.mix(nb.math("MULTIPLY", nb.math("LESS_THAN", rows, 0.08), 0.5), col, (0.01, 0.01, 0.01, 1))
    nrm = nb.bump(h, 0.6, 0.02)
    nb.output(nb.bsdf(col, 0.25 if glazed else rough, normal=nrm, spec=0.7 if glazed else 0.35,
                      Coat_Weight=0.5 if glazed else 0.0))
    return m


def copper_patina(name="copper_patina"):
    m = new_mat(name)
    nb = NB(m)
    uv = nb.uv()
    n1 = nb.noise(uv, 0.8, 5, 0.6)
    col = nb.ramp(n1, [(0.25, lin((70, 120, 100))), (0.5, lin((95, 150, 125))), (0.8, lin((60, 95, 80)))])
    sep = nb.n("ShaderNodeSeparateXYZ")
    nb.link(uv, sep.inputs[0])
    seams = nb.math("LESS_THAN", nb.math("FRACT", nb.math("DIVIDE", nb.o(sep, "X"), 0.6)), 0.04)
    col = nb.mix(nb.math("MULTIPLY", seams, 0.4), col, (0.02, 0.05, 0.04, 1))
    nrm = nb.bump(nb.math("ADD", seams, nb.math("MULTIPLY", n1, 0.3)), 0.4, 0.01)
    nb.output(nb.bsdf(col, 0.55, metal=0.15, normal=nrm))
    return m


def window_glass(name, frame_rgb=(235, 232, 225), panes=(2, 3), tint=(30, 36, 40), modern=False):
    """Window with frames and mullions drawn from 0..1 face UVs."""
    m = new_mat(name)
    nb = NB(m)
    uv = nb.uv()
    sep = nb.n("ShaderNodeSeparateXYZ")
    nb.link(uv, sep.inputs[0])
    u, v = nb.o(sep, "X"), nb.o(sep, "Y")
    rnd = nb.attr("rnd")
    fw = 0.055

    def band(x, w):
        # 1 where x is within w of 0 or 1
        return nb.math("MAXIMUM", nb.math("LESS_THAN", x, w), nb.math("GREATER_THAN", x, 1 - w))

    frame = nb.math("MAXIMUM", band(u, fw), band(v, fw * 0.8))
    if panes[0] > 1:
        mu = nb.math("FRACT", nb.math("MULTIPLY", u, panes[0]))
        frame = nb.math("MAXIMUM", frame, band(mu, 0.025 * panes[0]))
    if panes[1] > 1:
        mv = nb.math("FRACT", nb.math("MULTIPLY", v, panes[1]))
        frame = nb.math("MAXIMUM", frame, band(mv, 0.018 * panes[1]))
    # interior: dark room, curtains (lower part), blinds; some rooms lit
    dark = lin((18, 18, 20))
    curtain = lin((150, 135, 110))
    blind = lin((190, 188, 180))
    inter = nb.mix(nb.math("GREATER_THAN", rnd, 0.72), dark, curtain)
    blinds = nb.math("LESS_THAN", nb.math("FRACT", nb.math("MULTIPLY", v, 28.0)), 0.5)
    bl = nb.math("MULTIPLY", nb.math("GREATER_THAN", rnd, 0.88), nb.math("GREATER_THAN", v, 0.35))
    inter = nb.mix(bl, inter, nb.mix(blinds, blind, mix_rgb(blind, (0, 0, 0), 0.3)))
    # half-closed curtains only cover the top part of some windows
    halfc = nb.math("MULTIPLY", nb.math("LESS_THAN", rnd, 0.18), nb.math("GREATER_THAN", v, 0.55))
    inter = nb.mix(halfc, inter, curtain)
    inter = nb.mix(0.5, inter, lin(tint), blend="MULTIPLY") if modern else inter
    fcol = lin(frame_rgb)
    col = nb.mix(frame, inter, fcol)
    rough = nb.mix(frame, 0.04, 0.5)
    spec = nb.math("ADD", nb.math("MULTIPLY", nb.math("SUBTRACT", 1.0, frame), 0.6), 0.4)
    nrm = nb.bump(frame, 0.6, 0.01)
    # no two panes sit exactly in plane: a random tilt of a degree or two per
    # window makes the reflected sky vary from window to window
    r2 = nb.math("FRACT", nb.math("MULTIPLY", rnd, 7.31))
    tilt = nb.math("ADD", nb.math("MULTIPLY", nb.math("SUBTRACT", rnd, 0.5), u),
                   nb.math("MULTIPLY", nb.math("SUBTRACT", r2, 0.5), v))
    nrm = nb.bump(tilt, 1.0, 0.07, normal=nrm)
    nb.output(nb.bsdf(col, rough, normal=nrm, spec=spec, Coat_Weight=nb.math("SUBTRACT", 1.0, frame)))
    return m


def curtain_wall(name, glass=(60, 80, 95), mullion=(150, 155, 160), spandrel=(70, 75, 80),
                 module=1.5, floor=3.8, reflect=0.9):
    """Glass curtain wall for modern towers, mullion grid in metres."""
    m = new_mat(name)
    nb = NB(m)
    uv = nb.uv()
    sep = nb.n("ShaderNodeSeparateXYZ")
    nb.link(uv, sep.inputs[0])
    u, v = nb.o(sep, "X"), nb.o(sep, "Y")
    fu = nb.math("FRACT", nb.math("DIVIDE", u, module))
    fv = nb.math("FRACT", nb.math("DIVIDE", v, floor))
    mul = nb.math("MAXIMUM", nb.math("LESS_THAN", fu, 0.05), nb.math("GREATER_THAN", fu, 0.95))
    span = nb.math("LESS_THAN", fv, 0.22)
    tr = nb.math("LESS_THAN", nb.math("ABSOLUTE", nb.math("SUBTRACT", fv, 0.24)), 0.012)
    frame = nb.math("MAXIMUM", mul, tr)
    orand = nb.obj_rand()
    # per-panel tint variation (slightly different reflectivity panel to panel)
    cell = nb.n("ShaderNodeCombineXYZ")
    nb.link(nb.math("FLOOR", nb.math("DIVIDE", u, module)), cell.inputs[0])
    nb.link(nb.math("FLOOR", nb.math("DIVIDE", v, floor)), cell.inputs[1])
    nb.link(orand, cell.inputs[2])
    wn = nb.n("ShaderNodeTexWhiteNoise")
    nb.link(cell.outputs[0], wn.inputs[0])
    pv = wn.outputs[0]
    g = lin(glass)
    gcol = nb.mix(nb.math("MULTIPLY", pv, 0.5), g, mix_rgb(g, (0, 0, 0), 0.5))
    lit = nb.math("GREATER_THAN", pv, 0.93)
    gcol = nb.mix(nb.math("MULTIPLY", lit, 0.6), gcol, lin((200, 190, 160)))
    col = nb.mix(span, gcol, lin(spandrel))
    col = nb.mix(frame, col, lin(mullion))
    rough = nb.mix(nb.math("MAXIMUM", frame, span), nb.math("ADD", 0.02, nb.math("MULTIPLY", pv, 0.06)), 0.45)
    metal = nb.mix(frame, 0.0, 0.8)
    # slightly warped panels ("oil canning"): per-panel tilt breaks up reflections
    pv2 = nb.math("FRACT", nb.math("MULTIPLY", pv, 13.7))
    tilt = nb.math("ADD", nb.math("MULTIPLY", nb.math("SUBTRACT", pv, 0.5), fu),
                   nb.math("MULTIPLY", nb.math("SUBTRACT", pv2, 0.5), fv))
    nrm = nb.bump(tilt, 1.0, 0.08)
    nb.output(nb.bsdf(col, rough, metal=metal, spec=reflect, normal=nrm))
    return m


def punched_facade(name, wall=(190, 185, 175), glass=(40, 48, 55), bay=3.2, win_w=1.7,
                   floor=3.4, win_h=1.9, sill=0.9, ground=4.5):
    """Flat wall with painted-on windows: used for distant / backdrop buildings."""
    m = new_mat(name)
    nb = NB(m)
    uv = nb.uv()
    sep = nb.n("ShaderNodeSeparateXYZ")
    nb.link(uv, sep.inputs[0])
    u, v = nb.o(sep, "X"), nb.o(sep, "Y")
    orand = nb.obj_rand()
    fu = nb.math("FRACT", nb.math("DIVIDE", u, bay))
    vv = nb.math("SUBTRACT", v, ground)
    fv = nb.math("FRACT", nb.math("DIVIDE", vv, floor))
    wu = nb.math("LESS_THAN", nb.math("ABSOLUTE", nb.math("SUBTRACT", fu, 0.5)), win_w / bay / 2)
    wv = nb.math("MULTIPLY", nb.math("GREATER_THAN", fv, sill / floor),
                 nb.math("LESS_THAN", fv, (sill + win_h) / floor))
    win = nb.math("MULTIPLY", nb.math("MULTIPLY", wu, wv), nb.math("GREATER_THAN", vv, 0.0))
    wall_c = lin(wall)
    wcol = nb.mix(nb.math("MULTIPLY", nb.noise(uv, 0.3, 3), 0.5), wall_c, mix_rgb(wall_c, (0, 0, 0), 0.35))
    wcol = nb.mix(nb.math("MULTIPLY", orand, 0.4), wcol, mix_rgb(wall_c, (0.6, 0.5, 0.4), 0.4))
    cell = nb.n("ShaderNodeCombineXYZ")
    nb.link(nb.math("FLOOR", nb.math("DIVIDE", u, bay)), cell.inputs[0])
    nb.link(nb.math("FLOOR", nb.math("DIVIDE", vv, floor)), cell.inputs[1])
    nb.link(orand, cell.inputs[2])
    wn = nb.n("ShaderNodeTexWhiteNoise")
    nb.link(cell.outputs[0], wn.inputs[0])
    gl = nb.mix(nb.math("MULTIPLY", wn.outputs[0], 0.7), lin(glass), lin((120, 115, 100)))
    col = nb.mix(win, wcol, gl)
    rough = nb.mix(win, 0.8, 0.08)
    nrm = nb.bump(win, -0.4, 0.05)
    nb.output(nb.bsdf(col, rough, normal=nrm, spec=nb.mix(win, 0.3, 0.7)))
    return m


# --------------------------------------------------------------------------
# ground materials
# --------------------------------------------------------------------------

def asphalt(name="asphalt", rgb=(52, 52, 54)):
    m = new_mat(name)
    nb = NB(m)
    uv = nb.uv()
    base = lin(rgb)
    n1 = nb.noise(uv, 0.08, 4, 0.6)
    col = nb.ramp(n1, [(0.35, mix_rgb(base, (0.0, 0.0, 0.0), 0.25)), (0.65, mix_rgb(base, (1, 1, 1), 0.08))])
    agg = nb.noise(uv, 180.0, 2, 0.5)
    col = nb.mix(nb.math("MULTIPLY", nb.math("GREATER_THAN", agg, 0.68), 0.5), col, mix_rgb(base, (1, 1, 1), 0.25))
    patch = nb.noise(uv, 0.03, 2, 0.4)
    col = nb.mix(nb.math("MULTIPLY", nb.math("GREATER_THAN", patch, 0.62), 0.5), col,
                 mix_rgb(base, (0, 0, 0), 0.35))
    nrm = nb.bump(nb.noise(uv, 90.0, 3, 0.6), 0.25, 0.004)
    rough = nb.math("ADD", 0.82, nb.math("MULTIPLY", n1, 0.12))
    nb.output(nb.bsdf(col, rough, normal=nrm, spec=0.4))
    return m


def paint(name, rgb):
    m = new_mat(name)
    nb = NB(m)
    uv = nb.uv()
    base = lin(rgb)
    wear = nb.noise(uv, 1.5, 4, 0.6)
    col = nb.mix(nb.math("MULTIPLY", nb.math("GREATER_THAN", wear, 0.6), 0.45), base, lin((80, 80, 80)))
    nrm = nb.bump(nb.noise(uv, 60.0, 2), 0.2, 0.003)
    nb.output(nb.bsdf(col, 0.55, normal=nrm, spec=0.5))
    return m


def paving(name, rgb, tile=(0.6, 0.3), var=0.12, joint=0.006, rough=0.7, rgb2=None):
    m = new_mat(name)
    nb = NB(m)
    uv = nb.uv()
    base = lin(rgb)
    alt = lin(rgb2) if rgb2 else mix_rgb(base, (0, 0, 0), 0.15)
    br = nb.n("ShaderNodeTexBrick")
    nb.set(br, "Scale", 1.0)
    nb.set(br, "Brick Width", tile[0])
    nb.set(br, "Row Height", tile[1])
    nb.set(br, "Mortar Size", joint)
    nb.set(br, "Bias", 0.0)
    nb.set(br, "Color1", base)
    nb.set(br, "Color2", alt)
    nb.set(br, "Mortar", mix_rgb(base, (0, 0, 0), 0.5))
    nb.link(uv, br.inputs[0])
    col = br.outputs[0]
    dirt = nb.noise(uv, 0.25, 4, 0.6)
    col = nb.mix(nb.math("MULTIPLY", dirt, var * 3), col, mix_rgb(base, (0.02, 0.02, 0.02), 0.5))
    sp = nb.noise(uv, 120.0, 1)
    col = nb.mix(nb.math("MULTIPLY", nb.math("GREATER_THAN", sp, 0.66), 0.3), col, (0.02, 0.02, 0.02, 1))
    h = nb.math("ADD", nb.math("SUBTRACT", 1.0, br.outputs[1]), nb.math("MULTIPLY", nb.noise(uv, 30.0, 3), 0.15))
    nrm = nb.bump(h, 0.4, 0.006)
    nb.output(nb.bsdf(col, rough, normal=nrm, spec=0.4))
    return m


def grass(name="grass", rgb=(78, 112, 48)):
    m = new_mat(name)
    nb = NB(m)
    uv = nb.uv()
    n1 = nb.noise(uv, 0.15, 4, 0.6)
    n2 = nb.noise(uv, 2.0, 3, 0.6)
    base = lin(rgb)
    col = nb.ramp(n1, [(0.3, mix_rgb(base, (0.02, 0.05, 0.0), 0.35)), (0.55, base),
                       (0.8, mix_rgb(base, lin((150, 150, 70)), 0.35))])
    col = nb.mix(nb.math("MULTIPLY", n2, 0.3), col, mix_rgb(base, (0, 0, 0), 0.4))
    blades = nb.noise(uv, 300.0, 1)
    col = nb.mix(nb.math("MULTIPLY", blades, 0.25), col, mix_rgb(base, (1, 1, 0.6), 0.3))
    nrm = nb.bump(nb.math("ADD", blades, nb.math("MULTIPLY", n2, 0.5)), 0.5, 0.01)
    nb.output(nb.bsdf(col, 0.92, normal=nrm, spec=0.25, Sheen_Weight=0.3))
    return m


def water(name="water_huangpu"):
    """Huangpu River: turbid, sediment-laden brown-grey water.

    Bump only (no displacement): a long swell from ship wakes, wind chop in
    distorted bands roughly across the flow, and fine ripples. Enough slope
    variance that reflections break up into short streaks like on the real
    river, which is never mirror-calm with the constant boat traffic.
    """
    m = new_mat(name)
    nb = NB(m)
    uv = nb.uv()
    w1 = nb.noise(nb.vmath("MULTIPLY", uv, (0.035, 0.07, 1.0)), 1.0, 3, 0.5)
    wv = nb.n("ShaderNodeTexWave", wave_type="BANDS", bands_direction="DIAGONAL")
    nb.set(wv, "Scale", 0.22)
    nb.set(wv, "Distortion", 9.0)
    nb.set(wv, "Detail", 3.0)
    nb.set(wv, "Detail Scale", 1.4)
    nb.set(wv, "Detail Roughness", 0.55)
    nb.link(uv, nb.i(wv, "Vector"))
    w2 = nb.noise(nb.vmath("MULTIPLY", uv, (0.5, 0.9, 1.0)), 1.0, 4, 0.6)
    w3 = nb.noise(uv, 2.6, 3, 0.55)
    w4 = nb.noise(uv, 9.0, 2, 0.5)
    h = nb.math("ADD", nb.math("MULTIPLY", w1, 0.9), nb.math("MULTIPLY", nb.o(wv, "Factor"), 0.32))
    h = nb.math("ADD", h, nb.math("MULTIPLY", w2, 0.55))
    h = nb.math("ADD", h, nb.math("ADD", nb.math("MULTIPLY", w3, 0.28), nb.math("MULTIPLY", w4, 0.1)))
    nrm = nb.bump(h, 0.62, 0.32)
    # silt-laden water: khaki brown, patches of slightly greener water
    base = lin((80, 74, 54))
    col = nb.mix(nb.math("MULTIPLY", nb.noise(uv, 0.006, 2), 0.7), base, lin((66, 70, 52)))
    rough = nb.math("ADD", 0.035, nb.math("MULTIPLY", nb.noise(uv, 0.05, 2), 0.09))
    nb.output(nb.bsdf(col, rough, normal=nrm, spec=0.5, IOR=1.333))
    return m


def concrete(name, rgb=(150, 148, 142), rough=0.85, stain=0.3, tidal=None):
    m = new_mat(name)
    nb = NB(m)
    uv = nb.uv()
    base = lin(rgb)
    col = nb.mix(nb.math("MULTIPLY", nb.noise(uv, 0.4, 4, 0.6), 0.6), base, mix_rgb(base, (0, 0, 0), 0.3))
    sep = nb.n("ShaderNodeSeparateXYZ")
    nb.link(uv, sep.inputs[0])
    sv = nb.n("ShaderNodeCombineXYZ")
    nb.link(nb.math("MULTIPLY", nb.o(sep, "X"), 2.0), sv.inputs[0])
    nb.link(nb.math("MULTIPLY", nb.o(sep, "Y"), 0.1), sv.inputs[1])
    st = nb.math("POWER", nb.math("SUBTRACT", 1.0, nb.noise(sv.outputs[0], 1.0, 3), clamp=True), 3.0)
    col = nb.mix(nb.math("MULTIPLY", st, stain * 3), col, mix_rgb(base, (0.02, 0.02, 0.02), 0.6))
    nrm = nb.bump(nb.noise(uv, 40.0, 4, 0.7), 0.15, 0.004)
    col = nb.grime(col, uv, base, amount=0.4, splash=0.2)
    if tidal is not None:
        col, rough = _tidal(nb, col, rough, uv, base, tidal)
    nb.output(nb.bsdf(col, rough, normal=nrm, spec=0.35))
    return m


def simple(name, rgb, rough=0.5, metal=0.0, spec=0.5, emission=None, strength=0.0, alpha=None, **kw):
    m = new_mat(name)
    nb = NB(m)
    extra = dict(kw)
    if emission is not None:
        extra["Emission_Color"] = lin(emission)
        extra["Emission_Strength"] = strength
    nb.output(nb.bsdf(lin(rgb), rough, metal=metal, spec=spec, **extra))
    return m


def painted_metal(name, rgb, rough=0.45, metal=0.3):
    m = new_mat(name)
    nb = NB(m)
    uv = nb.uv()
    base = lin(rgb)
    col = nb.mix(nb.math("MULTIPLY", nb.noise(uv, 3.0, 3), 0.4), base, mix_rgb(base, (0, 0, 0), 0.3))
    r = nb.math("ADD", rough, nb.math("MULTIPLY", nb.noise(uv, 8.0, 2), 0.2))
    nb.output(nb.bsdf(col, r, metal=metal, spec=0.5))
    return m


def bark(name, rgb1, rgb2, mottled=False):
    m = new_mat(name)
    nb = NB(m)
    pos = nb.pos()
    if mottled:
        v = nb.voronoi(pos, 7.0, "Distance")
        col = nb.ramp(v, [(0.2, lin(rgb1)), (0.45, lin(rgb2)), (0.7, lin((120, 125, 95)))])
    else:
        sep = nb.n("ShaderNodeSeparateXYZ")
        nb.link(pos, sep.inputs[0])
        sv = nb.n("ShaderNodeCombineXYZ")
        nb.link(nb.math("MULTIPLY", nb.o(sep, "X"), 6.0), sv.inputs[0])
        nb.link(nb.math("MULTIPLY", nb.o(sep, "Y"), 6.0), sv.inputs[1])
        nb.link(nb.math("MULTIPLY", nb.o(sep, "Z"), 0.8), sv.inputs[2])
        n = nb.noise(sv.outputs[0], 3.0, 4, 0.6)
        col = nb.ramp(n, [(0.3, lin(rgb1)), (0.7, lin(rgb2))])
    nrm = nb.bump(nb.noise(pos, 20.0, 4, 0.6), 0.6, 0.02)
    nb.output(nb.bsdf(col, 0.85, normal=nrm, spec=0.3))
    return m


def foliage(name, rgb, rgb2=None, translucency=0.35, rough=0.55):
    m = new_mat(name)
    nb = NB(m)
    rnd = nb.attr("rnd")
    base = lin(rgb)
    alt = lin(rgb2) if rgb2 else mix_rgb(base, lin((160, 170, 60)), 0.4)
    orand = nb.obj_rand()
    t = nb.math("FRACT", nb.math("ADD", rnd, orand))
    col = nb.ramp(t, [(0.0, mix_rgb(base, (0, 0, 0), 0.25)), (0.55, base), (1.0, alt)])
    p = nb.bsdf(col, rough, spec=0.45)
    tr = nb.n("ShaderNodeBsdfTranslucent")
    nb.link(nb.mix(0.5, col, lin((140, 170, 40))), tr.inputs[0])
    ms = nb.n("ShaderNodeMixShader")
    ms.inputs[0].default_value = translucency
    nb.link(p, ms.inputs[1])
    nb.link(tr.outputs[0], ms.inputs[2])
    nb.output(ms.outputs[0])
    return m


def emissive(name, rgb, strength):
    m = new_mat(name)
    nb = NB(m)
    e = nb.n("ShaderNodeEmission")
    nb.set(e, "Color", lin(rgb))
    nb.set(e, "Strength", strength)
    nb.output(e.outputs[0])
    return m


# --------------------------------------------------------------------------

def build_all():
    # facade stones: Suzhou granite / artificial stone tones seen on the Bund
    stone("granite_light", (196, 190, 176))
    stone("granite_warm", (190, 176, 152), var=0.14)
    stone("granite_golden", (200, 182, 148), var=0.12)
    stone("granite_white", (214, 210, 200), var=0.1, streaks=0.22)
    stone("granite_grey", (160, 158, 152))
    stone("granite_dark", (120, 116, 110), rough=0.5)
    stone("rustic_light", (186, 180, 166), rustic=True, block=(1.4, 0.62))
    stone("rustic_warm", (176, 164, 142), rustic=True, block=(1.4, 0.62))
    stone("rustic_golden", (190, 172, 140), rustic=True, block=(1.4, 0.62))
    stone("rustic_white", (204, 200, 190), rustic=True, block=(1.4, 0.62))
    stone("rustic_grey", (150, 148, 142), rustic=True, block=(1.4, 0.62))
    stone("trim_light", (222, 218, 206), var=0.06, block=(2.0, 0.6), joint=0.003, streaks=0.12)
    plaster("stucco_cream", (222, 210, 182))
    plaster("stucco_white", (232, 228, 218))
    plaster("stucco_grey", (176, 174, 168))
    plaster("stucco_ochre", (206, 176, 132))
    plaster("stucco_pink", (210, 180, 165))
    brick("brick_red", (150, 66, 48), (128, 54, 40))
    brick("brick_red_banded", (156, 70, 50), (132, 56, 42), band=(1.25, 0.32), band_rgb=(222, 214, 198))
    brick("brick_brown", (120, 82, 58), (104, 72, 52), mortar=(150, 140, 125))
    brick("brick_grey", (112, 112, 108), (92, 94, 92), mortar=(170, 168, 160))
    brick("brick_grey_red", (110, 110, 106), (96, 96, 94), band=(1.6, 0.26), band_rgb=(150, 68, 50))
    brick("brick_cream", (196, 176, 140), (180, 160, 126), mortar=(200, 195, 185))
    roof_tiles("roof_tile_red", (150, 70, 50))
    roof_tiles("roof_tile_grey", (72, 72, 74))
    roof_tiles("roof_slate", (70, 74, 82), rough=0.5, pitch=0.3)
    roof_tiles("glazed_tile_blue", (40, 92, 110), glazed=True, pitch=0.22)
    roof_tiles("glazed_tile_green", (50, 105, 70), glazed=True, pitch=0.22)
    copper_patina()
    concrete("roof_flat", (128, 126, 120), rough=0.9, stain=0.4)
    concrete("concrete", (158, 156, 150))
    concrete("concrete_dark", (110, 108, 104))
    concrete("concrete_white", (210, 210, 205), stain=0.2)
    # river walls: dark tidal band up to about mean high water (water plane at z=-1.8)
    stone("bank_granite", (160, 158, 152), tidal=-0.5)
    concrete("bank_concrete", (150, 148, 142), tidal=-0.5)
    window_glass("window_hist_white", (232, 228, 218), panes=(2, 3))
    window_glass("window_hist_dark", (40, 46, 42), panes=(2, 3))
    window_glass("window_hist_green", (52, 76, 60), panes=(2, 4))
    window_glass("window_shop", (30, 30, 32), panes=(3, 1), modern=True)
    window_glass("window_modern", (170, 172, 175), panes=(2, 1), modern=True, tint=(60, 80, 95))
    window_glass("window_lane", (110, 60, 40), panes=(2, 2))
    curtain_wall("curtain_blue", glass=(58, 86, 110))
    curtain_wall("curtain_green", glass=(62, 92, 86))
    curtain_wall("curtain_grey", glass=(70, 76, 82), mullion=(180, 182, 185))
    curtain_wall("curtain_silver", glass=(110, 120, 130), mullion=(200, 202, 205), module=1.2, floor=4.2)
    curtain_wall("curtain_gold", glass=(120, 100, 60), mullion=(150, 130, 90), spandrel=(110, 95, 70))
    punched_facade("facade_tile_white", wall=(210, 206, 196))
    punched_facade("facade_tile_beige", wall=(196, 180, 152))
    punched_facade("facade_tile_grey", wall=(150, 150, 148))
    punched_facade("facade_tile_pink", wall=(196, 168, 156))
    punched_facade("facade_hist_dist", wall=(180, 170, 150), bay=3.8, win_w=1.5, win_h=2.4, floor=4.0,
                   sill=0.9, ground=5.0)
    # ground
    asphalt("asphalt")
    asphalt("asphalt_old", (64, 63, 62))
    paint("paint_white", (235, 235, 230))
    paint("paint_yellow", (230, 180, 40))
    paving("paving_sidewalk", (150, 148, 142), tile=(0.6, 0.3))
    paving("paving_plaza", (176, 170, 158), tile=(1.2, 0.6), rgb2=(166, 160, 148), var=0.16)
    paving("paving_deck", (170, 163, 150), tile=(0.9, 0.6), rgb2=(160, 153, 140), var=0.16)
    paving("paving_red", (140, 92, 76), tile=(0.2, 0.1), var=0.1)
    paving("curb_granite", (175, 172, 165), tile=(1.0, 0.3), joint=0.004, rough=0.55)
    grass("grass")
    grass("grass_park", (70, 104, 44))
    simple("soil", (70, 56, 42), rough=0.95, spec=0.2)
    water("water_huangpu")
    simple("riverbed", (120, 120, 112), rough=1.0)
    # metals & misc
    painted_metal("metal_dark", (36, 40, 38))
    painted_metal("metal_black", (20, 20, 22), rough=0.4)
    painted_metal("metal_grey", (130, 134, 136), metal=0.6, rough=0.35)
    painted_metal("metal_green", (40, 70, 55))
    painted_metal("steel_bridge", (128, 132, 132), metal=0.35, rough=0.45)
    simple("steel_stainless", (190, 192, 195), rough=0.25, metal=1.0)
    simple("bronze", (110, 80, 50), rough=0.4, metal=1.0)
    simple("bronze_red", (150, 82, 56), rough=0.32, metal=1.0)
    simple("gold", (210, 170, 80), rough=0.3, metal=1.0)
    simple("glass_clear", (200, 210, 215), rough=0.02, spec=0.5, Transmission_Weight=1.0)
    simple("glass_dark", (20, 24, 28), rough=0.05, spec=0.7)
    simple("glass_globe", (150, 160, 175), rough=0.05, metal=0.6, spec=0.8)
    simple("pearl_pink", (200, 70, 120), rough=0.18, metal=0.55, spec=0.8)
    simple("pearl_silver", (190, 192, 200), rough=0.22, metal=0.8)
    simple("lamp_glass", (245, 240, 225), rough=0.3, spec=0.5, emission=(255, 235, 200), strength=0.0)
    simple("signal_housing", (25, 25, 25), rough=0.5)
    emissive("signal_red", (255, 40, 20), 6.0)
    emissive("signal_green", (40, 255, 120), 6.0)
    simple("signal_off", (60, 60, 55), rough=0.2)
    simple("sign_blue", (20, 70, 160), rough=0.4)
    simple("sign_red", (150, 25, 25), rough=0.4)
    simple("sign_gold", (190, 150, 70), rough=0.3, metal=0.8)
    simple("sign_black", (22, 22, 24), rough=0.35)
    simple("sign_green", (25, 90, 60), rough=0.4)
    simple("sign_cream", (220, 205, 170), rough=0.5)
    simple("awning_red", (130, 30, 28), rough=0.8)
    simple("awning_green", (30, 70, 50), rough=0.8)
    simple("sign_white", (230, 230, 230), rough=0.4)
    simple("canopy_glass", (190, 200, 205), rough=0.1, spec=0.6, alpha=None)
    simple("flag_red", (200, 20, 25), rough=0.7)
    simple("bench_wood", (120, 82, 50), rough=0.7)
    simple("rubber", (25, 25, 25), rough=0.9)
    bark("bark_plane", (150, 150, 130), (95, 98, 80), mottled=True)
    bark("bark_camphor", (70, 60, 50), (45, 40, 34))
    bark("bark_ginkgo", (90, 82, 70), (60, 55, 46))
    foliage("leaf_plane", (70, 100, 40), (120, 140, 50))
    foliage("leaf_camphor", (45, 80, 35), (90, 120, 45), rough=0.4)
    foliage("leaf_ginkgo", (120, 140, 50), (170, 170, 60))
    foliage("hedge", (50, 85, 38), (80, 110, 45), translucency=0.2)
    foliage("flowers", (170, 60, 70), (220, 180, 70), translucency=0.2)
    return MATS
