"""
Extragem temperatura suprafetei (LST) din Landsat 8/9 prin Google Earth Engine.
Facem un compozit median pe fiecare luna (din cauza norilor) si luam valoarea la fiecare statie,
plus o grila de 500 m peste oras pentru punctele fara senzor.

Rulam earthengine ca sa ne logam la google earth acolo
Rulare: python src/02_landsat_lst_gee.py --project <punem id-ul proiectului >
"""
import argparse
from pathlib import Path

import ee
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
BBOX = [25.93, 44.30, 26.27, 44.66]       # lon_min, lat_min, lon_max, lat_max (București + Ilfov apropiat)


def mask_and_lst(img):
    qa = img.select("QA_PIXEL")
    # biți: 1 dilated cloud, 3 cloud, 4 cloud shadow, 5 snow
    mask = (qa.bitwiseAnd(1 << 1).eq(0)
            .And(qa.bitwiseAnd(1 << 3).eq(0))
            .And(qa.bitwiseAnd(1 << 4).eq(0))
            .And(qa.bitwiseAnd(1 << 5).eq(0)))
    lst = img.select("ST_B10").multiply(0.00341802).add(149.0).subtract(273.15).rename("lst_c")
    return lst.updateMask(mask).copyProperties(img, ["system:time_start"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True, help="ID-ul proiectului Google Cloud înregistrat în GEE")
    ap.add_argument("--start", default="2024-01-01")
    ap.add_argument("--end", default="2025-01-01")
    ap.add_argument("--only-grid", action="store_true", help="sare peste stații (deja descărcate)")
    args = ap.parse_args()

    ee.Initialize(project=args.project)
    region = ee.Geometry.Rectangle(BBOX)

    col = (ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
           .merge(ee.ImageCollection("LANDSAT/LC09/C02/T1_L2"))
           .filterBounds(region)
           .filterDate(args.start, args.end)
           .map(mask_and_lst))
    print(f"Scene Landsat în interval: {col.size().getInfo()}")

    ap_only_grid = (RAW / "landsat_lst_stations_monthly.csv").exists() and args.only_grid
    locs = pd.read_csv(RAW / "openaq_locations.csv").drop_duplicates("station_id")
    feats = [ee.Feature(ee.Geometry.Point([r.longitude, r.latitude]).buffer(100),
                        {"station_id": int(r.station_id)}) for r in locs.itertuples()]
    stations = ee.FeatureCollection(feats)

    months = pd.date_range(args.start, args.end, freq="MS", inclusive="left")
    rows = []
    for m in (months if not ap_only_grid else []):
        m0, m1 = m.strftime("%Y-%m-%d"), (m + pd.offsets.MonthBegin(1)).strftime("%Y-%m-%d")
        sub = col.filterDate(m0, m1)
        n = sub.size().getInfo()
        if n == 0:
            print(f"  {m:%Y-%m}: 0 scene")
            continue
        comp = sub.median().clip(region)
        fc = comp.reduceRegions(collection=stations, reducer=ee.Reducer.mean(), scale=30)
        for f in fc.getInfo()["features"]:
            p = f["properties"]
            rows.append({"station_id": p["station_id"], "month": m.strftime("%Y-%m"),
                         "lst_c": p.get("mean"), "n_scenes": n})
        print(f"  {m:%Y-%m}: {n} scene")
    if not ap_only_grid:
        pd.DataFrame(rows).to_csv(RAW / "landsat_lst_stations_monthly.csv", index=False)
        print("→ data/raw/landsat_lst_stations_monthly.csv")

    # Grilă 500 m pe toată perioada (compozit median anual) — candidații pentru noul senzor
    # GEE dă maxim 5000 de elemente pe cerere → împart zona în 4×4 bucăți
    annual = col.median()
    lon0, lat0, lon1, lat1 = BBOX
    n = 4
    dx, dy = (lon1 - lon0) / n, (lat1 - lat0) / n
    g = []
    for i in range(n):
        for j in range(n):
            tile = ee.Geometry.Rectangle([lon0 + i * dx, lat0 + j * dy,
                                          lon0 + (i + 1) * dx, lat0 + (j + 1) * dy])
            g += annual.sample(region=tile, scale=500, geometries=True).getInfo()["features"]
    pd.DataFrame([{"longitude": f["geometry"]["coordinates"][0],
                   "latitude": f["geometry"]["coordinates"][1],
                   "lst_c": f["properties"].get("lst_c")} for f in g]) \
        .to_csv(RAW / "landsat_lst_grid_500m.csv", index=False)
    print(f"→ data/raw/landsat_lst_grid_500m.csv ({len(g)} celule)")


if __name__ == "__main__":
    main()