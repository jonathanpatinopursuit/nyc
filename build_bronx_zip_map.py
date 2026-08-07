"""
Fetches NYC Modified ZIP Code Tabulation Area (MODZCTA) boundaries (NYC Open Data,
dataset pri4-ifjk), filters down to the Bronx (zip codes starting with "104"), and
bakes them into a lightweight static SVG-path asset for the small zip-code map on
the CTA slide. Geometry is static so this only needs to be rerun if the
projection/simplification needs tuning.
"""
import json
import math
import os
from pathlib import Path

import requests
from shapely.geometry import shape
from shapely.ops import transform

BASE_URL = "https://data.cityofnewyork.us/resource/pri4-ifjk.geojson"
REQUEST_TIMEOUT = 60
SIMPLIFY_TOLERANCE_DEG = 0.0002
TARGET_WIDTH = 360
REF_LAT = 40.85


def load_env():
    env_path = Path(__file__).resolve().parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def project(lon, lat):
    x = lon * math.cos(math.radians(REF_LAT))
    y = lat
    return x, y


def ring_to_path(coords):
    pts = " ".join(f"{x:.2f},{y:.2f}" for x, y in coords)
    first = coords[0]
    return f"M{first[0]:.2f},{first[1]:.2f} L{pts} Z"


def polygon_to_subpaths(poly):
    subpaths = [ring_to_path(list(poly.exterior.coords))]
    for interior in poly.interiors:
        subpaths.append(ring_to_path(list(interior.coords)))
    return subpaths


def geometry_to_path(geom):
    subpaths = []
    if geom.geom_type == "Polygon":
        subpaths.extend(polygon_to_subpaths(geom))
    elif geom.geom_type == "MultiPolygon":
        for poly in geom.geoms:
            subpaths.extend(polygon_to_subpaths(poly))
    return " ".join(subpaths)


def main():
    load_env()
    token = os.environ.get("NYC_OPEN_DATA_TOKEN")
    headers = {"Accept": "application/json"}
    if token:
        headers["X-App-Token"] = token

    print("Fetching MODZCTA boundaries...")
    resp = requests.get(
        BASE_URL, headers=headers, params={"$limit": 300}, timeout=REQUEST_TIMEOUT
    )
    resp.raise_for_status()
    fc = resp.json()

    projected = {}
    for feature in fc["features"]:
        zip_code = feature["properties"]["modzcta"]
        if not zip_code.startswith("104"):
            continue
        geom = shape(feature["geometry"])
        geom = geom.simplify(SIMPLIFY_TOLERANCE_DEG, preserve_topology=True)
        geom = transform(lambda x, y, z=None: project(x, y), geom)
        projected[zip_code] = geom

    print(f"  {len(projected)} Bronx zip codes")

    all_bounds = [g.bounds for g in projected.values()]
    minx = min(b[0] for b in all_bounds)
    miny = min(b[1] for b in all_bounds)
    maxx = max(b[2] for b in all_bounds)
    maxy = max(b[3] for b in all_bounds)

    pad = (maxx - minx) * 0.02
    minx -= pad
    miny -= pad
    maxx += pad
    maxy += pad

    scale = TARGET_WIDTH / (maxx - minx)
    height = (maxy - miny) * scale

    def to_svg(x, y):
        return (x - minx) * scale, (maxy - y) * scale

    zips = {}
    for zip_code, geom in projected.items():
        geom_svg = transform(lambda x, y, z=None: to_svg(x, y), geom)
        label_point = max(
            (geom_svg.geoms if geom_svg.geom_type == "MultiPolygon" else [geom_svg]),
            key=lambda p: p.area,
        ).representative_point()
        zips[zip_code] = {
            "path": geometry_to_path(geom_svg),
            "labelX": round(label_point.x, 2),
            "labelY": round(label_point.y, 2),
        }

    out = {
        "viewBox": f"0 0 {TARGET_WIDTH:.2f} {height:.2f}",
        "width": round(TARGET_WIDTH, 2),
        "height": round(height, 2),
        "zips": zips,
    }

    out_path = Path(__file__).resolve().parent / "public" / "bronx-zips.json"
    out_path.write_text(json.dumps(out))
    size_kb = out_path.stat().st_size / 1024
    print(f"\nSaved {out_path} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
