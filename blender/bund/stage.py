"""World sky, sun, haze, cameras and render settings."""
import math

import bpy
from mathutils import Vector

from . import util as U

# Morning light: the Bund facades face east, so they are sunlit before noon.
# Golden early-morning light: in late October the sun rises in the ESE over Lujiazui
# and lights the east-facing Bund facades warmly (~07:40, elevation 19 deg).
SUN_ELEVATION = 19.0   # degrees
SUN_AZIMUTH = 114.0    # degrees clockwise from north


def _sun_vector():
    el = math.radians(SUN_ELEVATION)
    az = math.radians(SUN_AZIMUTH)
    # direction from the ground towards the sun (+Y north, +X east)
    return Vector((math.sin(az) * math.cos(el), math.cos(az) * math.cos(el), math.sin(el)))


def world(haze=True):
    sc = bpy.context.scene
    w = bpy.data.worlds.get("Bund_Sky") or bpy.data.worlds.new("Bund_Sky")
    sc.world = w
    if hasattr(w, "use_nodes") and not w.use_nodes:
        w.use_nodes = True
    nt = w.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg = nt.nodes.new("ShaderNodeBackground")
    sky = nt.nodes.new("ShaderNodeTexSky")
    types = [e.identifier for e in sky.bl_rna.properties["sky_type"].enum_items]
    for t in ("MULTIPLE_SCATTERING", "NISHITA", "HOSEK_WILKIE"):
        if t in types:
            sky.sky_type = t
            break
    sky.sun_disc = False
    sky.sun_elevation = math.radians(SUN_ELEVATION)
    # Blender's sky: rotation 0 puts the sun on +Y (north) and turns clockwise
    # (calibrated with an equirectangular render), i.e. rotation == azimuth.
    sky.sun_rotation = math.radians(SUN_AZIMUTH)
    for attr, val in (("altitude", 20.0), ("air_density", 1.0), ("aerosol_density", 1.3),
                      ("dust_density", 1.3), ("ozone_density", 1.0)):
        if hasattr(sky, attr):
            setattr(sky, attr, val)
    # sun disc off: the sun lamp below provides direct light with clean shadows
    bg.inputs["Strength"].default_value = 0.05
    # thin high clouds: noise projected on a plane above the camera, faded towards the horizon
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Generated"], sep.inputs[0])
    def mnode(op, a, b=None):
        m = nt.nodes.new("ShaderNodeMath")
        m.operation = op
        for i, v in enumerate((a, b)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                m.inputs[i].default_value = v
            else:
                nt.links.new(v, m.inputs[i])
        return m.outputs[0]
    zc = mnode("MAXIMUM", sep.outputs["Z"], 0.02)
    cx = mnode("DIVIDE", sep.outputs["X"], zc)
    cy = mnode("DIVIDE", sep.outputs["Y"], zc)
    comb = nt.nodes.new("ShaderNodeCombineXYZ")
    nt.links.new(cx, comb.inputs[0])
    nt.links.new(cy, comb.inputs[1])
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 0.9
    noise.inputs["Detail"].default_value = 7.0
    noise.inputs["Roughness"].default_value = 0.62
    nt.links.new(comb.outputs[0], noise.inputs["Vector"])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.52
    ramp.color_ramp.elements[1].position = 0.78
    nt.links.new(noise.outputs[0], ramp.inputs[0])
    fade = mnode("MULTIPLY", mnode("MINIMUM", mnode("MULTIPLY", sep.outputs["Z"], 4.0), 1.0), 0.55)
    fade = mnode("MAXIMUM", fade, 0.0)
    cover = mnode("MULTIPLY", ramp.outputs[0], fade)
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    ins = [s_ for s_ in mix.inputs if getattr(s_, "enabled", True)]
    nt.links.new(cover, ins[0])
    nt.links.new(sky.outputs[0], ins[1])
    cl = nt.nodes.new("ShaderNodeMix")
    cl.data_type = "RGBA"
    cins = [s_ for s_ in cl.inputs if getattr(s_, "enabled", True)]
    cins[0].default_value = 0.6
    nt.links.new(sky.outputs[0], cins[1])
    cins[2].default_value = (14.0, 13.6, 13.0, 1.0)   # sunlit cloud, in sky-texture units
    nt.links.new([o for o in cl.outputs if getattr(o, "enabled", True)][0], ins[2])
    nt.links.new([o for o in mix.outputs if getattr(o, "enabled", True)][0], bg.inputs[0])
    nt.links.new(bg.outputs[0], out.inputs["Surface"])
    if haze:
        _haze_volume()
    # sun lamp aligned with the sky
    sun = bpy.data.objects.get("Sun")
    if sun is None:
        ld = bpy.data.lights.new("Sun", "SUN")
        sun = bpy.data.objects.new("Sun", ld)
        U.coll("Stage").objects.link(sun)
    sun.data.energy = 4.3
    sun.data.angle = math.radians(0.53)
    sun.data.color = (1.0, 0.80, 0.60)   # low morning sun through the city haze
    d = _sun_vector()
    sun.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
    return w


def _haze_volume(density=0.00011, radius=30000.0, top=700.0, n=128):
    """Aerial perspective: a finite low-density volume over the city.

    A cylinder rather than a box, so the haze path length to the edge is the
    same in every direction (a box shows its far corners as bright stripes).
    (A world volume would absorb the sun lamp entirely in Cycles.)
    """
    ob = bpy.data.objects.get("Atmosphere_Haze")
    if ob is None:
        me = bpy.data.meshes.new("Atmosphere_Haze")
        cx, cy, z0 = 400.0, 0.0, -1.0
        v = []
        for z in (z0, top):
            for i in range(n):
                a = 2 * math.pi * i / n
                v.append((cx + radius * math.cos(a), cy + radius * math.sin(a), z))
        f = [tuple(range(n - 1, -1, -1)), tuple(range(n, 2 * n))]
        f += [(i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)]
        me.from_pydata(v, [], f)
        ob = bpy.data.objects.new("Atmosphere_Haze", me)
        U.coll("Stage").objects.link(ob)
        m = bpy.data.materials.get("haze_volume") or bpy.data.materials.new("haze_volume")
        if hasattr(m, "use_nodes") and not m.use_nodes:
            m.use_nodes = True
        nt = m.node_tree
        nt.nodes.clear()
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        vol = nt.nodes.new("ShaderNodeVolumePrincipled")
        vol.inputs["Density"].default_value = density
        # city haze: near-neutral, mildly forward scattering (a strongly forward
        # phase makes the far haze look dark away from the sun)
        vol.inputs["Color"].default_value = (0.86, 0.88, 0.92, 1)
        vol.inputs["Anisotropy"].default_value = 0.3
        nt.links.new(vol.outputs[0], out.inputs["Volume"])
        me.materials.append(m)
        ob.visible_shadow = True
    return ob


def _deck_x(sc, y):
    """Middle of the promenade deck at a given y (for eye-level cameras)."""
    best = None
    for p in sc.get("deck", []):
        xs = []
        ring = p["ext"]
        n = len(ring)
        for i in range(n):
            (x0, y0), (x1, y1) = ring[i], ring[(i + 1) % n]
            if (y0 - y) * (y1 - y) <= 0 and y0 != y1:
                xs.append(x0 + (y - y0) * (x1 - x0) / (y1 - y0))
        if len(xs) >= 2:
            xs.sort()
            best = (xs[0] + xs[-1]) / 2
    return best if best is not None else -100.0


def _bund_x(sc, y):
    """Centre line of 中山东一路 at a given y."""
    xs = []
    for r in sc.get("roads", []):
        if r["name"] != "中山东一路":
            continue
        for x, yy in r["pts"]:
            if abs(yy - y) < 12:
                xs.append(x)
    return sum(xs) / len(xs) if xs else -160.0


def camera_specs(sc):
    eye = sc["levels"]["deck"] + 1.65
    return {
        # name: (location, target, lens_mm)
        "CAM_01_River_Postcard": ((175, -10, 14), (-185, 70, 24), 26),
        "CAM_02_Aerial_Overview": ((520, -760, 360), (-150, 120, 0), 30),
        "CAM_03_Promenade_North": ((_deck_x(sc, -130), -130, eye), (-150, 160, 16), 24),
        "CAM_04_Waibaidu_Bridge": ((_deck_x(sc, 560) - 4, 560, eye), (-215, 745, 14), 26),
        "CAM_05_Street_Zhongshan_E1": ((_bund_x(sc, -210), -210, 1.7), (_bund_x(sc, 40) - 6, 40, 10), 24),
        "CAM_06_Customs_HSBC": ((_deck_x(sc, -70), -70, eye), (-200, -70, 24), 22),
        "CAM_07_Pudong_From_Bund": ((_deck_x(sc, 162) - 3.5, 162, eye), (900, -150, 150), 28),
        "CAM_08_Nanjing_Road_Junction": ((-140, 320, 45), (-195, 205, 5), 26),
        "CAM_10_Aerial_North": ((200, 1050, 260), (-170, 80, 0), 30),
        # the classic view of the Bund from the Pudong riverside (滨江大道), morning sun on the facades
        "CAM_11_From_Pudong_Classic": ((324, 40, 4.2), (-190, 70, 26), 45),
        "CAM_12_From_Pudong_Wide": ((345, -120, 40), (-170, 160, 12), 26),
        # eye level on the riverside plaza opposite HSBC: flower bed and benches, the
        # Bund road with its hedge median, HSBC and the Customs House behind
        "CAM_13_Plaza_Flowerbeds": ((-121, -84.5, 1.6), (-210, -79, 8.5), 28),
    }


def cameras(sc):
    cc = U.coll("Cameras")
    made = {}
    for name, (loc, tgt, lens) in camera_specs(sc).items():
        cd = bpy.data.cameras.new(name)
        cd.lens = lens
        cd.clip_start = 0.3
        # the horizon ring reaches 80 km; a nearer clip would show the dark
        # below-horizon sky as a band along the skyline
        cd.clip_end = 100000
        cd.sensor_width = 36
        ob = bpy.data.objects.new(name, cd)
        cc.objects.link(ob)
        ob.location = loc
        d = Vector(tgt) - Vector(loc)
        ob.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
        made[name] = ob
    # orthographic plan of the traffic network
    cd = bpy.data.cameras.new("CAM_09_TopDown_Traffic")
    cd.type = "ORTHO"
    cd.ortho_scale = 1200
    cd.clip_end = 5000
    ob = bpy.data.objects.new("CAM_09_TopDown_Traffic", cd)
    cc.objects.link(ob)
    ob.location = (0, 170, 1500)
    ob.rotation_euler = (0, 0, 0)
    made["CAM_09_TopDown_Traffic"] = ob
    bpy.context.scene.camera = made["CAM_01_River_Postcard"]
    return made


def render_settings(samples=128, res=(1920, 1080)):
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    cy = sc.cycles
    cy.device = "CPU"
    cy.samples = samples
    cy.use_adaptive_sampling = True
    cy.adaptive_threshold = 0.02
    cy.use_denoising = True
    try:
        cy.denoiser = "OPENIMAGEDENOISE"
    except TypeError:
        pass
    cy.max_bounces = 8
    cy.diffuse_bounces = 3
    cy.glossy_bounces = 3
    cy.transmission_bounces = 4
    cy.transparent_max_bounces = 8
    cy.volume_bounces = 1
    cy.sample_clamp_indirect = 8.0
    cy.caustics_reflective = False
    cy.caustics_refractive = False
    if hasattr(cy, "volume_step_rate"):
        cy.volume_step_rate = 8.0
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = "PNG"
    sc.render.film_transparent = False
    vs = sc.view_settings
    try:
        vs.view_transform = "AgX"           # Blender 4.0+
    except TypeError:
        vs.view_transform = "Filmic"
    # looks are a dynamic enum (bl_rna lists only 'None'), so just try the names
    for lk in ("AgX - Medium High Contrast", "Medium High Contrast", "AgX - Base Contrast"):
        try:
            vs.look = lk
            break
        except TypeError:
            continue
    vs.exposure = -0.25    # keeps sunlit stone in the mid-tones, so facades keep their colour
    sc.unit_settings.system = "METRIC"


def post_process(bloom=0.06, vignette=0.2, dispersion=0.0035):
    """Camera-like finishing in the compositor: a faint glow around highlights,
    a touch of lateral chromatic aberration and a gentle vignette."""
    sc = bpy.context.scene
    ng = bpy.data.node_groups.get("Bund_Post") or bpy.data.node_groups.new("Bund_Post", "CompositorNodeTree")
    ng.nodes.clear()
    if not [s for s in ng.interface.items_tree if getattr(s, "in_out", "") == "OUTPUT"]:
        ng.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    new, link = ng.nodes.new, ng.links.new

    def math_node(op, a, b, c=None):
        m = new("ShaderNodeMath")
        m.operation = op
        for i, v in enumerate((a, b, c)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                m.inputs[i].default_value = v
            else:
                link(v, m.inputs[i])
        return m.outputs[0]

    rl = new("CompositorNodeRLayers")
    gl = new("CompositorNodeGlare")
    gl.inputs["Type"].default_value = "Fog Glow"
    gl.inputs["Quality"].default_value = "High"
    gl.inputs["Threshold"].default_value = 1.2
    gl.inputs["Strength"].default_value = bloom
    link(rl.outputs["Image"], gl.inputs["Image"])
    ld = new("CompositorNodeLensdist")
    ld.inputs["Distortion"].default_value = 0.0
    ld.inputs["Dispersion"].default_value = dispersion
    link(gl.outputs["Image"], ld.inputs["Image"])
    # vignette: soft ellipse, multiplied in
    em = new("CompositorNodeEllipseMask")
    em.inputs["Operation"].default_value = "Multiply"
    em.inputs["Size"].default_value = (0.92, 0.92)
    link(rl.outputs["Alpha"], em.inputs["Mask"])
    bl = new("CompositorNodeBlur")
    r = 0.22 * max(sc.render.resolution_x, sc.render.resolution_y) * sc.render.resolution_percentage / 100
    bl.inputs["Size"].default_value = (r, r)
    link(em.outputs[0], bl.inputs["Image"])
    k = math_node("MULTIPLY_ADD", bl.outputs[0], vignette, 1.0 - vignette)
    mx = new("ShaderNodeMix")
    mx.data_type = "RGBA"
    mx.blend_type = "MULTIPLY"
    ins = [i for i in mx.inputs if i.enabled]
    ins[0].default_value = 1.0
    link(ld.outputs["Image"], ins[1])
    link(k, ins[2])
    out = new("NodeGroupOutput")
    link([o for o in mx.outputs if o.enabled][0], out.inputs[0])
    sc.compositing_node_group = ng
    sc.render.use_compositing = True
    if hasattr(sc.render, "compositor_device"):
        sc.render.compositor_device = "CPU"   # headless: no GPU context for the compositor
    return ng
