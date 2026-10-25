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
                              export_yup=True, export_extras=False, export_cameras=False, export_lights=False)
    return True


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
