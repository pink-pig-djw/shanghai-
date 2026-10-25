"""Build the Shanghai Bund scene in Blender.

Run with Blender 4.2+ (tested with 5.2):
    blender --background --python blender/build_bund.py -- [options]
or with the bpy wheel from PyPI:
    python blender/build_bund.py [options]

Options:
    --scene PATH      scene description (default data/scene.json)
    --out PATH        .blend to write (default output/shanghai_bund.blend)
    --render CAMS     comma separated camera names (or "all") to render to renders/
    --samples N       Cycles samples for renders (default 128)
    --res WxH         render resolution (default 1920x1080)
    --quick           skip trees/props/landmark detail for a fast preview
    --no-haze         disable atmospheric haze
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import bpy  # noqa: E402

from bund import util as U  # noqa: E402
from bund import materials, ground, stage  # noqa: E402


def parse():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else argv[1:]
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", default=os.path.join(ROOT, "data", "scene.json"))
    ap.add_argument("--out", default=os.path.join(ROOT, "output", "shanghai_bund.blend"))
    ap.add_argument("--render", default="")
    ap.add_argument("--samples", type=int, default=128)
    ap.add_argument("--res", default="1920x1080")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--no-haze", action="store_true")
    ap.add_argument("--only", default="", help="debug: comma list of parts to build")
    ap.add_argument("--renders-dir", default=os.path.join(ROOT, "renders"))
    return ap.parse_args(argv)


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    try:
        import addon_utils
        addon_utils.enable("cycles", default_set=True)
    except Exception:
        pass


def main():
    a = parse()
    t0 = time.time()
    reset()
    with open(a.scene, encoding="utf-8") as fh:
        sc = json.load(fh)
    only = set(x for x in a.only.split(",") if x)

    def want(part):
        return not only or part in only

    mats = materials.build_all()
    print(f"[bund] materials: {len(mats)}  ({time.time() - t0:.1f}s)")
    root = U.coll("Shanghai_Bund")
    if want("ground"):
        ground.build(sc, mats, U.coll("Ground_Roads_Water", root))
        print(f"[bund] ground done ({time.time() - t0:.1f}s)")
    if want("buildings"):
        from bund import facade
        facade.build_all(sc, mats, root, quick=a.quick)
        print(f"[bund] buildings done ({time.time() - t0:.1f}s)")
    if want("landmarks"):
        from bund import landmarks
        landmarks.build_all(sc, mats, root, quick=a.quick)
        print(f"[bund] landmarks done ({time.time() - t0:.1f}s)")
    if want("bridges"):
        from bund import bridge
        bridge.build_all(sc, mats, root)
        print(f"[bund] bridges done ({time.time() - t0:.1f}s)")
    if want("backdrop"):
        from bund import backdrop
        backdrop.build_all(sc, mats, root)
        print(f"[bund] backdrop done ({time.time() - t0:.1f}s)")
    if want("context"):
        from bund import context
        context.build_all(mats, root)
        print(f"[bund] context done ({time.time() - t0:.1f}s)")
    if want("vegetation") and not a.quick:
        from bund import vegetation
        vegetation.build_all(sc, mats, root)
        print(f"[bund] vegetation done ({time.time() - t0:.1f}s)")
    if want("props") and not a.quick:
        from bund import props
        props.build_all(sc, mats, root)
        print(f"[bund] props done ({time.time() - t0:.1f}s)")

    stage.world(haze=not a.no_haze)
    cams = stage.cameras(sc)
    w, h = (int(v) for v in a.res.lower().split("x"))
    stage.render_settings(a.samples, (w, h))
    stage.post_process()

    if a.render:
        render_all(a, cams)

    if a.out:
        n0, n1 = U.weld_all()
        print(f"[bund] welded vertices {n0} -> {n1} ({time.time() - t0:.1f}s)")
        save_split(a.out)
        print(f"[bund] saved {a.out} ({time.time() - t0:.1f}s)")
    print(f"[bund] total {time.time() - t0:.1f}s")


def save_split(out):
    """Save the scene; the surrounding-city ring goes to a linked side file so
    each .blend stays below GitHub's 100 MB limit."""
    out = os.path.abspath(out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    ctx = bpy.data.collections.get("Context_City_Ring")
    if ctx is not None and ctx.all_objects:
        side = os.path.splitext(out)[0] + "_context.blend"
        ids = {ctx}
        for ob in ctx.all_objects:
            ids.add(ob)
            if ob.data:
                ids.add(ob.data)
                for m in getattr(ob.data, "materials", []):
                    if m:
                        ids.add(m)
        bpy.data.libraries.write(side, ids, path_remap="RELATIVE_ALL", compress=True)
        # replace the local collection by a link to the side file
        parents = [c for c in bpy.data.collections if ctx.name in c.children]
        for ob in list(ctx.all_objects):
            bpy.data.objects.remove(ob)
        for c in parents:
            c.children.unlink(ctx)
        bpy.data.collections.remove(ctx)
        if hasattr(bpy.data, "orphans_purge"):
            bpy.data.orphans_purge(do_recursive=True)
        bpy.ops.wm.save_as_mainfile(filepath=out, compress=True)
        with bpy.data.libraries.load(side, link=True, relative=True) as (src, dst):
            dst.collections = ["Context_City_Ring"]
        root = bpy.data.collections.get("Shanghai_Bund") or bpy.context.scene.collection
        for c in dst.collections:
            if c is not None:
                root.children.link(c)
        print(f"[bund] context ring -> {side} ({os.path.getsize(side) / 1e6:.1f} MB)")
    bpy.context.preferences.filepaths.use_file_compression = True
    bpy.ops.wm.save_as_mainfile(filepath=out, compress=True, relative_remap=True)
    print(f"[bund] main file {os.path.getsize(out) / 1e6:.1f} MB")


def render_all(a, cams):
    names = list(cams) if a.render == "all" else [n.strip() for n in a.render.split(",")]
    os.makedirs(a.renders_dir, exist_ok=True)
    for n in names:
        cam = cams.get(n) or next((c for k, c in cams.items() if k.startswith(n) or n in k), None)
        if cam is None:
            print("[bund] unknown camera", n)
            continue
        bpy.context.scene.camera = cam
        bpy.context.scene.render.filepath = os.path.join(a.renders_dir, cam.name + ".png")
        t1 = time.time()
        bpy.ops.render.render(write_still=True)
        print(f"[bund] rendered {cam.name} in {time.time() - t1:.0f}s")


if __name__ == "__main__":
    main()
