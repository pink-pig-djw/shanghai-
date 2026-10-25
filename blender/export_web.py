"""Export the Bund model for the first-person web walkthrough (web/).

    python blender/export_web.py            (bpy wheel)
    blender -b -P blender/export_web.py

Builds the same scene as build_bund.py in a lighter "web" mode (no window
sills/lintels, no instanced trees/props - the browser instances those
itself), exports one GLB per collection and compresses them with gltfpack
(meshopt). Also writes web/assets/world.json with the data the browser
needs for collisions, trees, lamps, the ferry route and teleports.
"""
import json
import math
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import bpy  # noqa: E402
import numpy as np  # noqa: E402
from mathutils import Vector  # noqa: E402

from bund import util as U  # noqa: E402
from bund import materials, ground, facade, landmarks, bridge, backdrop, context, furniture  # noqa: E402

OUT = os.path.join(ROOT, "web", "assets")


def export_collection(coll_name, path):
    bpy.ops.object.select_all(action="DESELECT")
    col = bpy.data.collections.get(coll_name)
    if col is None:
        return False
    objs = [o for o in col.all_objects if o.type == "MESH"]
    if not objs:
        return False
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=True, export_apply=True,
                              export_texcoords=True, export_normals=True, export_materials="EXPORT",
                              export_vertex_color="NAME", export_vertex_color_name="Col",
                              export_yup=True, export_extras=False, export_cameras=False, export_lights=False)
    return True


# --------------------------------------------------------------------------
# per-building colour, baked to vertex colours for the browser
# --------------------------------------------------------------------------
def _lin(c):
    c = np.asarray(c, dtype=np.float64) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


# base colours of these materials in web/app.js (MATDEF), sRGB
WEB_BASE = {"facade_tile_white": (210, 206, 196), "facade_tile_beige": (196, 180, 152),
            "facade_tile_grey": (150, 150, 148), "facade_tile_pink": (196, 168, 156),
            "facade_hist_dist": (180, 170, 150), "roof_flat": (128, 126, 120)}
# the same palettes the Blender shaders pick from with the 'bld' attribute (materials.build_all)
PALETTES = {
    "facade_tile_white": [(206, 203, 196), (212, 200, 172), (186, 186, 183), (214, 202, 162), (196, 201, 206), (200, 192, 180)],
    "facade_tile_beige": [(190, 170, 140), (168, 148, 118), (202, 182, 150), (158, 128, 102), (184, 160, 128), (176, 166, 150)],
    "facade_tile_grey": [(150, 150, 148), (124, 124, 124), (170, 168, 162), (108, 110, 114), (140, 135, 128), (160, 156, 150)],
    "facade_tile_pink": [(196, 160, 145), (180, 130, 110), (204, 172, 152), (160, 110, 95), (150, 92, 76), (188, 150, 120)],
    "facade_hist_dist": [(176, 166, 146), (150, 140, 124), (160, 116, 92), (186, 176, 156), (138, 128, 118), (170, 150, 120), (122, 112, 104)],
    "roof_flat": [(128, 126, 120), (92, 90, 88), (150, 146, 136), (72, 72, 74), (120, 108, 94), (138, 140, 136)],
}
# stone / render / brick: darker-warmer to lighter-cooler building by building (cf. NB.bld_tint)
TINT_POS = np.array([0.0, 0.55, 1.0])
TINT_RGB = np.array([(0.78, 0.73, 0.66), (0.92, 0.91, 0.89), (0.99, 1.0, 1.0)])
CURTAIN_POS = np.array([0.0, 0.3, 0.6, 1.0])
CURTAIN_RGB = np.array([(1.0, 1.0, 1.0), (0.66, 0.66, 0.68), (0.88, 0.9, 0.9), (0.62, 0.76, 0.76)])
TINTED = ("granite_", "rustic_", "stucco_", "brick_", "trim_", "concrete", "bank_")


def _colour_for(base, v):
    """(n, 3) linear multipliers for faces of material `base` with bld values v."""
    if base in PALETTES:
        pal = PALETTES[base]
        idx = np.minimum((v * len(pal)).astype(int), len(pal) - 1)
        return np.minimum(_lin(np.array(pal))[idx] / _lin(WEB_BASE[base]), 1.0)
    if base.startswith("curtain_"):
        return np.stack([np.interp(v, CURTAIN_POS, CURTAIN_RGB[:, k]) for k in range(3)], axis=1)
    if base.startswith(TINTED):
        return np.stack([np.interp(v, TINT_POS, TINT_RGB[:, k]) for k in range(3)], axis=1)
    return None


def bake_building_colours(coll_names):
    """Write a 'Col' corner colour on every exported mesh: white, except faces whose
    material varies by building in the Blender shaders (bld attribute)."""
    n_obj = 0
    for cn in coll_names:
        coll = bpy.data.collections.get(cn)
        if coll is None:
            continue
        for ob in coll.all_objects:
            if ob.type != "MESH" or not len(ob.data.polygons):
                continue
            me = ob.data
            nf = len(me.polygons)
            bld = np.zeros(nf, dtype=np.float32)
            a = me.attributes.get("bld")
            if a is not None and a.domain == "FACE":
                a.data.foreach_get("value", bld)
            mi = np.zeros(nf, dtype=np.int32)
            me.polygons.foreach_get("material_index", mi)
            col = np.ones((nf, 3), dtype=np.float32)
            for idx, m in enumerate(me.materials):
                if m is None:
                    continue
                sel = (mi == idx) & (bld > 0)
                if not sel.any():
                    continue
                c = _colour_for(m.name.split(".")[0], bld[sel])
                if c is not None:
                    col[sel] = c
            ls = np.zeros(nf, dtype=np.int32)
            lt = np.zeros(nf, dtype=np.int32)
            me.polygons.foreach_get("loop_start", ls)
            me.polygons.foreach_get("loop_total", lt)
            rgba = np.ones((len(me.loops), 4), dtype=np.float32)
            face_of_loop = np.repeat(np.arange(nf), lt)
            loop_idx = np.concatenate([np.arange(s, s + t) for s, t in zip(ls, lt)]) if nf else np.zeros(0, int)
            rgba[loop_idx, :3] = col[face_of_loop]
            attr = me.color_attributes.get("Col") or me.color_attributes.new("Col", "FLOAT_COLOR", "CORNER")
            attr.data.foreach_set("color", rgba.ravel())
            me.color_attributes.active_color = attr
            n_obj += 1
    return n_obj


# merge cell size per collection (m); 0 = merge by material only. Small cells keep
# frustum culling useful near the player, one cell per material keeps draw calls low.
MERGE_CELL = {
    "Ground_Roads_Water": 600, "Buildings_Bund_Core": 0, "Buildings_Background": 0,
    "Landmarks_Historic_Bund": 400, "Bridges_Viaducts": 0, "Backdrop_Lujiazui_Pudong": 0,
    "Context_City_Ring": 0, "Street_Furniture_Flowers": 300,
}


def merge_by_material(coll_name, cell):
    """Separate every mesh by material and join the parts per material (and per
    grid cell of their centres): hundreds of objects x materials become a few
    dozen draw calls in the browser."""
    coll = bpy.data.collections.get(coll_name)
    if coll is None:
        return 0
    objs = [o for o in coll.all_objects if o.type == "MESH" and len(o.data.polygons)]
    if not objs:
        return 0
    view = bpy.context.view_layer
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    view.objects.active = objs[0]
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.separate(type="MATERIAL")
    bpy.ops.object.mode_set(mode="OBJECT")
    groups = {}
    for o in [o for o in coll.all_objects if o.type == "MESH" and len(o.data.polygons)]:
        me = o.data
        mat = me.materials[me.polygons[0].material_index] if me.materials else None
        key = (mat.name if mat else "",)
        if cell:
            c = o.matrix_world @ (sum((Vector(b) for b in o.bound_box), Vector()) / 8)
            key += (int(math.floor(c.x / cell)), int(math.floor(c.y / cell)))
        groups.setdefault(key, []).append(o)
    for key, lst in groups.items():
        if len(lst) > 1:
            bpy.ops.object.select_all(action="DESELECT")
            for o in lst:
                o.select_set(True)
            view.objects.active = lst[0]
            bpy.ops.object.join()
        name = coll_name + "_" + "_".join(str(k) for k in key)
        lst[0].name = name
        lst[0].data.name = name
    return len(groups)


def gltfpack(src, dst):
    """Weld vertices, quantize positions (KHR_mesh_quantization, decoded natively by
    three.js - no WebAssembly needed) and gzip. UVs stay float: they are in metres."""
    exe = os.environ.get("GLTFPACK", "gltfpack")
    tmp = dst + ".tmp.glb"
    cmd = [exe, "-i", src, "-o", tmp, "-km", "-kn", "-vp", "16", "-vtf", "-vn", "8"]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        os.remove(src)
    except Exception as ex:  # keep the uncompressed file if gltfpack is missing
        print("[web] gltfpack failed:", ex)
        os.replace(src, tmp)
    import gzip
    with open(tmp, "rb") as fi, gzip.open(dst, "wb", compresslevel=9) as fo:
        fo.write(fi.read())
    os.remove(tmp)


def window_variants(mats):
    """Give each window face one of four interior variants (dark, curtains, blinds,
    lit) via material slots named <window_mat>_v0.._v3, so the browser can vary them."""
    import zlib
    for ob in bpy.data.objects:
        if ob.type != "MESH":
            continue
        me = ob.data
        names = [m.name if m else "" for m in me.materials]
        if not any(n.startswith("window_") for n in names):
            continue
        slot_of = {}
        for n in names:
            if n.startswith("window_"):
                for v in range(4):
                    vn = f"{n}_v{v}"
                    if vn not in bpy.data.materials:
                        bpy.data.materials.new(vn)
                    if vn not in [m.name for m in me.materials if m]:
                        me.materials.append(bpy.data.materials[vn])
        names = [m.name if m else "" for m in me.materials]
        idx = {n: i for i, n in enumerate(names)}
        mi = [0] * len(me.polygons)
        me.polygons.foreach_get("material_index", mi)
        cen = [0.0] * (len(me.polygons) * 3)
        me.polygons.foreach_get("center", cen)
        for k, m in enumerate(mi):
            n = names[m]
            if n.startswith("window_") and "_v" not in n:
                h = zlib.crc32(f"{cen[3*k]:.1f},{cen[3*k+1]:.1f},{cen[3*k+2]:.1f}".encode())
                v = (0, 0, 0, 1, 1, 2, 3)[h % 7]
                mi[k] = idx[f"{n}_v{v}"]
        me.polygons.foreach_set("material_index", mi)
        me.update()


def world_json(sc):
    """Compact data for the browser (local metres, Blender axes: x east, y north, z up)."""
    def r(v):
        return round(v, 2)

    blds = []
    for b in sc["buildings"]:
        for p in b["poly"]:
            blds.append({"e": [[r(x), r(y)] for x, y in p["ext"]], "h": b["h"],
                         "n": b.get("name") or "", "lm": b.get("landmark") or ""})
    lm_meta = json.load(open(os.path.join(ROOT, "data", "landmarks.json"), encoding="utf-8"))["landmarks"]
    labels = []
    for b in sc["buildings"]:
        if b.get("landmark"):
            m = next((d for d in lm_meta if d["key"] == b["landmark"]), None)
            if m:
                ext = b["poly"][0]["ext"]
                cx, cy = U.centroid(ext)
                labels.append({"key": m["key"], "no": m["no"], "zh": m["zh"], "en": m["en"], "year": m["year"],
                               "pos": [r(cx), r(cy)], "h": m.get("height")})
    from bund.stage import _deck_x, _bund_x
    teleports = [
        {"name": "外滩观景平台 · 海关大楼", "pos": [_deck_x(sc, -60), -60], "z": sc["levels"]["deck"], "look": [-200, -70]},
        {"name": "陈毅广场 · 南京东路口", "pos": [-158, 213], "z": sc["levels"]["pave"], "look": [-260, 200]},
        {"name": "外白渡桥", "pos": [-150, 640], "z": sc["levels"]["pave"], "look": [-185, 760]},
        {"name": "黄浦公园 · 人民英雄纪念塔", "pos": [-75, 560], "z": sc["levels"]["deck"], "look": [-48, 590]},
        {"name": "外滩源 · 原英国领事馆", "pos": [-235, 585], "z": sc["levels"]["pave"], "look": [-300, 590]},
        {"name": "中山东一路 · 汇丰银行前", "pos": [_bund_x(sc, -110) - 9, -110], "z": sc["levels"]["pave"], "look": [-220, -110]},
        {"name": "外滩信号台", "pos": [_deck_x(sc, -420), -420], "z": sc["levels"]["deck"], "look": [25, -440]},
        {"name": "金陵东路渡口（轮渡）", "pos": [118, -470], "z": sc["levels"]["pave"], "look": [300, -560]},
    ]
    return {
        "levels": sc["levels"],
        "core": sc["core"],
        "water": sc["water"],
        "deck": sc["deck"],
        "buildings": blds,
        "labels": labels,
        "trees": sc["trees"],
        "lamps": sc["lamps"],
        "signals": sc["signals"],
        "ferry_routes": sc.get("ferry_routes", []),
        "ferry_terminals": sc.get("ferry_terminals", []),
        "teleports": [dict(t, pos=[r(t["pos"][0]), r(t["pos"][1])]) for t in teleports],
        "roads": [{"p": [[r(x), r(y)] for x, y in rd["pts"]], "w": rd["width"], "c": rd["class"]} for rd in sc["roads"]],
        "attribution": "Map data: Overture Maps Foundation / © OpenStreetMap contributors (ODbL)",
    }


def main():
    t0 = time.time()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    with open(os.path.join(ROOT, "data", "scene.json"), encoding="utf-8") as fh:
        sc = json.load(fh)
    os.makedirs(OUT, exist_ok=True)
    mats = materials.build_all()
    root = U.coll("Shanghai_Bund")
    ground.build(sc, mats, U.coll("Ground_Roads_Water", root))
    facade.build_all(sc, mats, root, quick=False, web=True)
    landmarks.build_all(sc, mats, root)
    bridge.build_all(sc, mats, root)
    backdrop.build_all(sc, mats, root)
    context.build_all(mats, root)
    furniture.build_all(sc, mats, root, web=True)
    window_variants(mats)
    print(f"[web] scene built ({time.time() - t0:.0f}s)")
    # the browser draws its own water and riverbed; its fog hides the horizon ring
    for name in ("Water_Huangpu_SuzhouCreek", "Riverbed", "Far_City_Carpet_Water", "Far_HighRises"):
        o = bpy.data.objects.get(name)
        if o:
            bpy.data.objects.remove(o)
    parts = {
        "ground": "Ground_Roads_Water",
        "buildings_core": "Buildings_Bund_Core",
        "buildings_back": "Buildings_Background",
        "landmarks": "Landmarks_Historic_Bund",
        "bridges": "Bridges_Viaducts",
        "lujiazui": "Backdrop_Lujiazui_Pudong",
        "context": "Context_City_Ring",
        "furniture": "Street_Furniture_Flowers",
    }
    sizes = {}
    manifest = {"files": {}}
    print(f"[web] baked building colours on {bake_building_colours(parts.values())} meshes")
    for coll_name in parts.values():
        n = merge_by_material(coll_name, MERGE_CELL.get(coll_name, 0))
        print(f"[web] {coll_name}: {n} merged meshes")
    for key, coll_name in parts.items():
        raw = os.path.join(OUT, key + ".raw.glb")
        dst = os.path.join(OUT, key + ".glb.gz")
        if export_collection(coll_name, raw):
            gltfpack(raw, dst)
            sizes[key] = round(os.path.getsize(dst) / 1e6, 2)
            manifest["files"][key] = {"file": key + ".glb.gz", "bytes": os.path.getsize(dst)}
    with open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1)
    with open(os.path.join(OUT, "world.json"), "w", encoding="utf-8") as fh:
        json.dump(world_json(sc), fh, ensure_ascii=False, separators=(",", ":"))
    sizes["world.json"] = round(os.path.getsize(os.path.join(OUT, "world.json")) / 1e6, 2)
    print("[web] sizes MB:", sizes, f"({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
