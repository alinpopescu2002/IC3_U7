"""
Reprezentarea alternativa: embeddings AlphaEarth (Google Satellite Embedding V1, anual, 10 m).
Fiecare pixel are un vector de 64 de valori (A00..A63) invatat de un model pre-antrenat
pe imagini satelitare. Iau media vectorului intr-un buffer de 100 m in jurul fiecarei statii,
plus o grila de 500 m peste oras pentru punctele fara senzor.

Rulare: python src/05_alphaearth_gee.py --project <id-proiect-gee> --year 2024
"""
import argparse
from pathlib import Path

import ee
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
BBOX = [25.93, 44.30, 26.27, 44.66]
BANDS = [f"A{i:02d}" for i in range(64)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--year", type=int, default=2024)
    ap.add_argument("--skip-grid", action="store_true")
    args = ap.parse_args()

    RAW.mkdir(parents=True, exist_ok=True)
    ee.Initialize(project=args.project)
    region = ee.Geometry.Rectangle(BBOX)
    emb = (ee.ImageCollection("GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL")
           .filterDate(f"{args.year}-01-01", f"{args.year + 1}-01-01")
           .filterBounds(region)
           .mosaic()
           .select(BANDS))

    # statiile: le iau din stations.csv (dupa unirea duplicatelor), altfel din locatii
    st_path = ROOT / "data" / "processed" / "stations.csv"
    locs = pd.read_csv(st_path if st_path.exists() else RAW / "openaq_locations.csv")
    locs = locs.drop_duplicates("station_id")
    fc = ee.FeatureCollection([
        ee.Feature(ee.Geometry.Point([r.longitude, r.latitude]).buffer(100),
                   {"station_id": int(r.station_id)}) for r in locs.itertuples()])
    res = emb.reduceRegions(collection=fc, reducer=ee.Reducer.mean(), scale=10).getInfo()
    rows = [{"station_id": f["properties"]["station_id"],
             **{b: f["properties"].get(b) for b in BANDS}} for f in res["features"]]
    out = pd.DataFrame(rows)
    out.to_csv(RAW / "alphaearth_stations.csv", index=False)
    print(f"-> data/raw/alphaearth_stations.csv ({len(out)} statii, "
          f"{out[BANDS].notna().all(axis=1).sum()} complete)")

    if args.skip_grid:
        return
    # grila 500 m, in 4x4 bucati (GEE da max 5000 elemente pe cerere)
    lon0, lat0, lon1, lat1 = BBOX
    n = 4
    dx, dy = (lon1 - lon0) / n, (lat1 - lat0) / n
    g = []
    for i in range(n):
        for j in range(n):
            tile = ee.Geometry.Rectangle([lon0 + i * dx, lat0 + j * dy,
                                          lon0 + (i + 1) * dx, lat0 + (j + 1) * dy])
            g += emb.sample(region=tile, scale=500, geometries=True).getInfo()["features"]
    pd.DataFrame([{"longitude": f["geometry"]["coordinates"][0],
                   "latitude": f["geometry"]["coordinates"][1],
                   **{b: f["properties"].get(b) for b in BANDS}} for f in g]) \
        .to_csv(RAW / "alphaearth_grid_500m.csv", index=False)
    print(f"-> data/raw/alphaearth_grid_500m.csv ({len(g)} celule)")


if __name__ == "__main__":
    main()
