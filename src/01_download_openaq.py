"""
Descarcam datele de PM2.5 si PM10 din OpenAQ (API v3) pentru statiile din Bucuresti.
Luam mediile orare pe intervalul dat, cu paginare, si salvam si metadatele statiilor.

Cheia api nu este in cod, o bagam in variabila.
Rulare: python src/01_download_openaq.py --start 2024-01-01 --end 2025-01-01
"""
import argparse
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests

BASE_URL = "https://api.openaq.org/v3"
CENTER = "44.4323,26.1063"     # lat,lon centrul Bucureștiului
RADIUS_M = 25000               # maximul permis de API
PARAMS_OK = {"pm25", "pm10"}
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"


def get(session, url, params=None, max_retry=5):
    """GET cu respectarea limitei de rată și reîncercări."""
    for attempt in range(max_retry):
        r = session.get(url, params=params, timeout=60)
        if r.status_code == 200:
            remaining = r.headers.get("x-ratelimit-remaining")
            if remaining is not None and int(remaining) <= 1:
                time.sleep(int(r.headers.get("x-ratelimit-reset", 60)) + 1)
            return r.json()
        if r.status_code == 429:                     # prea multe cereri
            wait = int(r.headers.get("x-ratelimit-reset", 60)) + 1
            print(f"   429 rate limit → aștept {wait}s")
            time.sleep(wait)
            continue
        if r.status_code >= 500:
            time.sleep(5 * (attempt + 1))
            continue
        print(f"   Eroare {r.status_code}: {r.text[:200]}")
        return None
    return None


def fetch_locations(session):
    data = get(session, f"{BASE_URL}/locations",
               {"coordinates": CENTER, "radius": RADIUS_M, "limit": 1000})
    if data is None:
        sys.exit("Nu am putut lista locațiile — verifică cheia API.")
    rows = []
    for loc in data.get("results", []):
        c = loc.get("coordinates") or {}
        lic = loc.get("licenses") or []
        for s in loc.get("sensors", []):
            p = (s.get("parameter") or {})
            if str(p.get("name", "")).lower() not in PARAMS_OK:
                continue
            rows.append({
                "station_id": loc["id"],
                "station_name": loc.get("name"),
                "sensor_id": s["id"],
                "parameter": p.get("name").lower(),
                "unit": p.get("units"),
                "latitude": c.get("latitude"),
                "longitude": c.get("longitude"),
                "is_monitor": loc.get("isMonitor"),   # True = stație de referință
                "is_mobile": loc.get("isMobile"),
                "owner": (loc.get("owner") or {}).get("name"),
                "provider": (loc.get("provider") or {}).get("name"),
                "license": "; ".join(l.get("name", "") for l in lic) if lic else None,
                "datetime_first": ((loc.get("datetimeFirst") or {}).get("utc")),
                "datetime_last": ((loc.get("datetimeLast") or {}).get("utc")),
            })
    return pd.DataFrame(rows)


def fetch_sensor_hours(session, sensor_id, start, end):
    """Toate orele unui senzor în [start, end), pagină cu pagină."""
    out, page = [], 1
    while True:
        data = get(session, f"{BASE_URL}/sensors/{sensor_id}/hours",
                   {"datetime_from": start, "datetime_to": end,
                    "limit": 1000, "page": page})
        if not data:
            break
        res = data.get("results", [])
        for row in res:
            per = row.get("period") or {}
            cov = row.get("coverage") or {}
            out.append({
                "sensor_id": sensor_id,
                "value": row.get("value"),
                # ora de START a intervalului orar (UTC)
                "datetime_utc": (per.get("datetimeFrom") or {}).get("utc"),
                "coverage_pct": cov.get("percentComplete"),
            })
        if len(res) < 1000:
            break
        page += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2024-01-01")
    ap.add_argument("--end", default="2025-01-01")
    args = ap.parse_args()

    key = os.environ.get("OPENAQ_API_KEY")
    if not key:
        sys.exit("Setează variabila de mediu OPENAQ_API_KEY (nu pune cheia în cod!).")
    RAW.mkdir(parents=True, exist_ok=True)

    s = requests.Session()
    s.headers.update({"X-API-Key": key, "Accept": "application/json"})

    print("1/2 Listez stațiile din București ...")
    locs = fetch_locations(s)
    locs.to_csv(RAW / "openaq_locations.csv", index=False)
    print(f"   {locs.station_id.nunique()} stații, {len(locs)} senzori PM → data/raw/openaq_locations.csv")

    print(f"2/2 Descarc mediile orare {args.start} → {args.end} ...")
    rows = []
    for i, r in enumerate(locs.itertuples(), 1):
        # sar peste senzorii care nu au date în interval
        if r.datetime_last and r.datetime_last[:10] < args.start:
            print(f"   [{i}/{len(locs)}] {r.station_name} {r.parameter}: fără date după {r.datetime_last[:10]}, sar")
            continue
        got = fetch_sensor_hours(s, r.sensor_id, args.start, args.end)
        print(f"   [{i}/{len(locs)}] {r.station_name:>10} {r.parameter:>4}: {len(got)} ore")
        rows.extend(got)

    hours = pd.DataFrame(rows)
    if hours.empty:
        sys.exit("Nu s-a descărcat nimic — verifică intervalul de timp.")
    meta = locs[["sensor_id", "station_id", "station_name", "latitude", "longitude",
                 "parameter", "unit"]]
    df = hours.merge(meta, on="sensor_id", how="left")
    df = df[["station_id", "station_name", "sensor_id", "latitude", "longitude",
             "parameter", "value", "unit", "datetime_utc", "coverage_pct"]]
    df.to_csv(RAW / "openaq_hourly.csv", index=False)
    print(f"\nGata: {len(df):,} înregistrări orare → data/raw/openaq_hourly.csv")


if __name__ == "__main__":
    main()
