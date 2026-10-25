"""Download Overture Maps features (OSM-derived) for the Bund study area.

Overture GeoParquet files live in a public S3 bucket. Each file's footer has
row-group statistics on the ``bbox`` struct, so we scan footers in parallel,
read only the row groups that intersect our area and keep the rows that
actually overlap it. Output is one GeoJSON FeatureCollection per type in
``data/raw/``.

Usage: python tools/fetch_overture.py [--release 2026-10-21.0]
"""
import argparse
import json
import os
import concurrent.futures as cf

import pyarrow.fs as pafs
import pyarrow.parquet as pq
import shapely
from shapely import wkb

BUCKET = "overturemaps-us-west-2"

# lon/lat boxes: (xmin, ymin, xmax, ymax)
AREAS = {
    # Historic Bund: Yan'an East Rd (south) .. north bank of Suzhou Creek,
    # Henan Middle Rd (west) .. middle of the Huangpu River (east).
    "bund": (121.4815, 31.2300, 121.4975, 31.2475),
    # Lujiazui skyline across the river, used as low-detail backdrop.
    "lujiazui": (121.4940, 31.2280, 121.5130, 31.2450),
    # Surrounding city (massing only) so wide shots end in real streets, not a void.
    "context": (121.4550, 31.2100, 121.5350, 31.2720),
}
# types fetched for the context ring are written to <type>_context.geojson
CONTEXT_TYPES = ["building", "water", "segment", "land_use"]

TYPES = {
    "building": ("buildings", ["bund", "lujiazui"]),
    "building_part": ("buildings", ["bund", "lujiazui"]),
    "segment": ("transportation", ["bund", "lujiazui"]),
    "connector": ("transportation", ["bund"]),
    "water": ("base", ["bund", "lujiazui"]),
    "land_use": ("base", ["bund", "lujiazui"]),
    "land": ("base", ["bund", "lujiazui"]),
    "infrastructure": ("base", ["bund"]),
    "land_cover": ("base", ["bund"]),
    "place": ("places", ["bund"]),
}


def s3fs():
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    kw = dict(anonymous=True, region="us-west-2")
    if proxy:
        kw["proxy_options"] = proxy
    return pafs.S3FileSystem(**kw)


def list_files(fs, release, theme, typ):
    sel = pafs.FileSelector(f"{BUCKET}/release/{release}/theme={theme}/type={typ}/")
    return sorted(i.path for i in fs.get_file_info(sel) if i.path.endswith(".parquet"))


def bbox_cols(md, rg):
    out = {}
    r = md.row_group(rg)
    for i in range(r.num_columns):
        c = r.column(i)
        if c.path_in_schema.startswith("bbox.") and c.statistics is not None:
            key = c.path_in_schema.split(".")[1]
            out[key] = (c.statistics.min, c.statistics.max)
    return out


def hits(md, box):
    xmin, ymin, xmax, ymax = box
    res = []
    for rg in range(md.num_row_groups):
        s = bbox_cols(md, rg)
        if not s:
            res.append(rg)
            continue
        if s["xmin"][0] > xmax or s["xmax"][1] < xmin:
            continue
        if s["ymin"][0] > ymax or s["ymax"][1] < ymin:
            continue
        res.append(rg)
    return res


def jsonable(v):
    if isinstance(v, dict):
        return {k: jsonable(x) for k, x in v.items() if x is not None}
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    if isinstance(v, bytes):
        return v.hex()
    return v


def scan_file(fs, path, boxes):
    f = pq.ParquetFile(path, filesystem=fs)
    md = f.metadata
    want = sorted({rg for b in boxes for rg in hits(md, b)})
    if not want:
        return []
    feats = []
    tbl = f.read_row_groups(want)
    rows = tbl.to_pylist()
    for row in rows:
        bb = row.get("bbox")
        ok = False
        for (xmin, ymin, xmax, ymax) in boxes:
            if bb and not (bb["xmin"] > xmax or bb["xmax"] < xmin or bb["ymin"] > ymax or bb["ymax"] < ymin):
                ok = True
                break
        if not ok:
            continue
        geom = wkb.loads(row.pop("geometry"))
        row.pop("bbox", None)
        feats.append({
            "type": "Feature",
            "geometry": shapely.geometry.mapping(geom),
            "properties": jsonable(row),
        })
    return feats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--release", default="2026-10-21.0")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "data", "raw"))
    ap.add_argument("--types", nargs="*", default=list(TYPES))
    ap.add_argument("--context", action="store_true", help="fetch the wide context ring instead")
    args = ap.parse_args()
    if args.context:
        fetch_context(args)
        return
    fs = s3fs()
    os.makedirs(args.out, exist_ok=True)
    for typ in args.types:
        theme, areas = TYPES[typ]
        boxes = [AREAS[a] for a in areas]
        files = list_files(fs, args.release, theme, typ)
        print(f"{typ}: {len(files)} files", flush=True)
        feats = []
        with cf.ThreadPoolExecutor(16) as ex:
            for res in ex.map(lambda p: scan_file(fs, p, boxes), files):
                feats.extend(res)
        # json.dumps cannot handle Decimal/datetime; stringify fallback
        path = os.path.join(args.out, f"{typ}.geojson")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"type": "FeatureCollection", "features": feats,
                       "attribution": "Overture Maps Foundation, release " + args.release +
                       "; contains data © OpenStreetMap contributors (ODbL)"},
                      fh, ensure_ascii=False, default=str)
        print(f"  -> {len(feats)} features, {os.path.getsize(path)/1e6:.1f} MB", flush=True)


def fetch_context(args):
    """Wide area, slimmed down: footprints + height for buildings, polygons for water/parks,
    major roads only. Written as compact GeoJSON."""
    fs = s3fs()
    box_ = AREAS["context"]
    keep = {
        "building": ["height", "num_floors", "min_height", "has_parts", "id"],
        "water": ["subtype", "class"],
        "segment": ["subtype", "class", "names"],
        "land_use": ["subtype", "class"],
    }
    for typ in CONTEXT_TYPES:
        theme = TYPES[typ][0]
        files = list_files(fs, args.release, theme, typ)
        print(f"{typ} (context): {len(files)} files", flush=True)
        feats = []
        with cf.ThreadPoolExecutor(16) as ex:
            for res in ex.map(lambda p: scan_file(fs, p, [box_]), files):
                feats.extend(res)
        out = []
        for f in feats:
            pr = f["properties"]
            if typ == "segment" and (pr.get("subtype") != "road" or pr.get("class") not in (
                    "motorway", "trunk", "primary", "secondary", "tertiary")):
                continue
            if typ == "land_use" and pr.get("class") not in ("park", "grass", "garden", "cemetery", "recreation_ground"):
                continue
            g = shapely.geometry.shape(f["geometry"]).simplify(0.000008)
            f["geometry"] = shapely.geometry.mapping(g)
            f["properties"] = {k: pr.get(k) for k in keep[typ] if pr.get(k) is not None}
            if typ == "segment":
                f["properties"]["names"] = (pr.get("names") or {}).get("primary")
            out.append(f)
        path = os.path.join(args.out, f"{typ}_context.geojson")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"type": "FeatureCollection", "features": out,
                       "attribution": "Overture Maps Foundation, release " + args.release +
                       "; contains data © OpenStreetMap contributors (ODbL)"}, fh, ensure_ascii=False, default=str)
        print(f"  -> {len(out)} features, {os.path.getsize(path)/1e6:.1f} MB", flush=True)


if __name__ == "__main__":
    main()
