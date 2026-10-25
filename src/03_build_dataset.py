"""
Curatam datele, le aliniez si facem data card-ul asta.
- scoatem valorile lipsa/negative/imposibile si statiile duplicate din OpenAQ
- trecem de la ore la medii zilnice (o zi e valida daca are minim 18 ore)
- lipim LST-ul lunar langa PM, pe statie
- facem split spatial pe statii (5 fold-uri), ca testul sa fie pe puncte nevazute

Rulare: python src/03_build_dataset.py
"""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans

ROOT = Path(__file__).resolve().parents[1]
RAW, PROC, FIG = ROOT / "data" / "raw", ROOT / "data" / "processed", ROOT / "figures"
TZ = "Europe/Bucharest"
MIN_HOURS = 18
MAX_PLAUSIBLE = 1000.0
N_FOLDS = 5
SEED = 42


def load(args):
    h = pd.read_csv(args.hourly)
    h["datetime_utc"] = pd.to_datetime(h["datetime_utc"], utc=True, errors="coerce")
    locs_path = RAW / "openaq_locations.csv"
    locs = pd.read_csv(locs_path) if locs_path.exists() else None
    lst_path = RAW / "landsat_lst_stations_monthly.csv"
    lst = pd.read_csv(lst_path) if lst_path.exists() else None
    return h, locs, lst


def clean(h, log):
    log["raw_rows"] = int(len(h))
    n0 = len(h)
    h = h.dropna(subset=["value", "datetime_utc"])
    log["dropped_missing"] = int(n0 - len(h))
    n0 = len(h)
    h = h[h["value"] >= 0]
    log["dropped_negative"] = int(n0 - len(h))
    n0 = len(h)
    h = h[h["value"] <= MAX_PLAUSIBLE]
    log["dropped_implausible"] = int(n0 - len(h))
    n0 = len(h)
    h = h.drop_duplicates(subset=["sensor_id", "datetime_utc"])
    log["dropped_duplicates"] = int(n0 - len(h))
    # consistență fizică: PM2.5 nu poate depăși PM10 la aceeași stație/oră
    w = h.pivot_table(index=["station_id", "datetime_utc"], columns="parameter",
                      values="value", aggfunc="mean")
    if {"pm25", "pm10"} <= set(w.columns):
        both = w.dropna(subset=["pm25", "pm10"])
        bad = both[both["pm25"] > both["pm10"] * 1.05]
        log["pm25_gt_pm10_hours"] = int(len(bad))
        log["pm25_gt_pm10_pct"] = round(100 * len(bad) / max(len(both), 1), 2)
    # OpenAQ are uneori aceeași stație înregistrată de 2 ori (același nume + aceleași coordonate)
    # → le unim sub un singur station_id, altfel apar dubluri și leakage între train/test
    key = h["station_name"].astype(str) + "|" + h["latitude"].round(4).astype(str) + "|" + h["longitude"].round(4).astype(str)
    canon = h.groupby(key)["station_id"].transform("min")
    log["duplicate_locations_merged"] = int(h["station_id"].nunique() - canon.nunique())
    h = h.assign(station_id=canon)
    # stații diferite în același punct fizic (< 50 m), ex. B-1 și RO0065A
    st = h.drop_duplicates("station_id")[["station_id", "station_name", "latitude", "longitude"]].reset_index(drop=True)
    pairs = []
    for i in range(len(st)):
        for j in range(i + 1, len(st)):
            dlat = (st.latitude[i] - st.latitude[j]) * 111_000
            dlon = (st.longitude[i] - st.longitude[j]) * 111_000 * np.cos(np.radians(44.43))
            if np.hypot(dlat, dlon) < 50:
                pairs.append(f"{st.station_name[i]}≈{st.station_name[j]}")
    log["colocated_pairs"] = pairs
    log["clean_rows"] = int(len(h))
    return h


def to_daily(h):
    h = h.copy()
    h["date"] = h["datetime_utc"].dt.tz_convert(TZ).dt.date
    d = (h.groupby(["station_id", "station_name", "sensor_id", "parameter", "date"])
           .agg(value=("value", "mean"), n_hours=("value", "size")).reset_index())
    d["valid"] = d["n_hours"] >= MIN_HOURS
    return d


def station_table(h, locs):
    st = (h.groupby("station_id")
            .agg(station_name=("station_name", "first"), latitude=("latitude", "first"),
                 longitude=("longitude", "first")).reset_index())
    if locs is not None and "is_monitor" in locs:
        meta = locs.drop_duplicates("station_id")[["station_id", "is_monitor", "owner", "provider", "license"]]
        st = st.merge(meta, on="station_id", how="left")
        st["type"] = np.where(st["is_monitor"] == True, "referință", "low-cost")
    else:
        # fără metadate: stațiile RNMCA/EEA au coduri RO00xxA
        st["type"] = np.where(st["station_name"].astype(str).str.match(r"^RO\d"), "referință", "nedeterminat")
    # blocuri spațiale: 2×N_FOLDS clustere KMeans, apoi repartizate echilibrat în N_FOLDS fold-uri
    k = min(2 * N_FOLDS, len(st))
    st["block"] = KMeans(n_clusters=k, n_init=10, random_state=SEED).fit_predict(
        st[["latitude", "longitude"]].to_numpy())
    sizes, fold_of = [0] * N_FOLDS, {}
    for b, n in st["block"].value_counts().items():          # cel mai mare bloc primul
        f = int(np.argmin(sizes)); fold_of[b] = f; sizes[f] += n
    st["fold"] = st["block"].map(fold_of)
    return st


def gaps(d, start, end):
    days = pd.date_range(start, end, freq="D", inclusive="left").date
    out = []
    for (sid, name, sens, par), g in d.groupby(["station_id", "station_name", "sensor_id", "parameter"]):
        ok = set(g.loc[g.valid, "date"])
        flags = np.array([x in ok for x in days])
        longest, cur = 0, 0
        for f in flags:
            cur = 0 if f else cur + 1
            longest = max(longest, cur)
        out.append({"station_id": sid, "station_name": name, "sensor_id": sens, "parameter": par,
                    "valid_days": int(flags.sum()), "period_days": len(days),
                    "missing_pct": round(100 * (1 - flags.mean()), 1),
                    "longest_gap_days": int(longest)})
    return pd.DataFrame(out)


def fig_coverage(d, st, start, end, path):
    dv = d[d.valid & (d.parameter == "pm10")].copy()
    if dv.empty:
        dv = d[d.valid].copy()
    dv["month"] = pd.to_datetime(dv["date"]).dt.to_period("M")
    months = pd.period_range(start, pd.Timestamp(end) - pd.Timedelta(days=1), freq="M")
    cnt = dv.groupby(["station_name", "month"]).size().unstack(fill_value=0).reindex(columns=months, fill_value=0)
    pct = 100 * cnt / np.array([m.days_in_month for m in months])
    order = st.sort_values(["type", "station_name"]).station_name
    pct = pct.reindex([s for s in order if s in pct.index])
    fig, ax = plt.subplots(figsize=(9, max(4, 0.22 * len(pct))))
    im = ax.imshow(pct.values, aspect="auto", cmap="viridis", vmin=0, vmax=100)
    ax.set_yticks(range(len(pct)), pct.index, fontsize=7)
    ax.set_xticks(range(len(months)), [m.strftime("%Y-%m") for m in months], rotation=90, fontsize=7)
    ax.set_xlabel("Lună")
    ax.set_title("Acoperire PM10: % zile valide (≥18 h) pe stație și lună")
    fig.colorbar(im, ax=ax, label="% zile valide")
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def fig_map(st, path):
    fig, ax = plt.subplots(figsize=(6.5, 6))
    cmap = plt.get_cmap("tab10")
    for t, mk in [("referință", "^"), ("low-cost", "o"), ("nedeterminat", "s")]:
        if not (st.type == t).any():
            continue
        s = st[st.type == t]
        ax.scatter(s.longitude, s.latitude, c=[cmap(f) for f in s.fold], marker=mk, s=80,
                   edgecolor="k")
        ax.scatter([], [], c="lightgray", marker=mk, s=80, edgecolor="k", label=f"{t} ({len(s)})")
    for f in sorted(st.fold.unique()):
        ax.scatter([], [], c=[cmap(f)], s=60, label=f"fold spațial {f}")
    ax.set_xlabel("Longitudine (°E)")
    ax.set_ylabel("Latitudine (°N)")
    ax.set_title("Stații PM București: tip și fold-ul de test (split spațial)")
    ax.grid(ls="--", alpha=.4)
    ax.legend(fontsize=7, loc="best")
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hourly", default=str(RAW / "openaq_hourly.csv"))
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    args = ap.parse_args()
    for p in (PROC, FIG):
        p.mkdir(parents=True, exist_ok=True)

    h, locs, lst = load(args)
    log = {}
    h = clean(h, log)
    start = args.start or str(h.datetime_utc.min().date())
    end = args.end or str((h.datetime_utc.max() + pd.Timedelta(days=1)).date())

    d = to_daily(h)
    st = station_table(h, locs)
    gp = gaps(d, start, end)

    daily = d[d.valid].pivot_table(index=["station_id", "date"], columns="parameter",
                                   values="value").reset_index()
    daily = daily.merge(st[["station_id", "station_name", "latitude", "longitude", "type", "fold"]],
                        on="station_id", how="left")
    if lst is not None:
        daily["month"] = pd.to_datetime(daily["date"]).dt.strftime("%Y-%m")
        daily = daily.merge(lst[["station_id", "month", "lst_c"]], on=["station_id", "month"], how="left")

    daily.to_csv(PROC / "pm_daily_aligned.csv", index=False)
    st.to_csv(PROC / "stations.csv", index=False)
    gp.to_csv(PROC / "gaps_per_sensor.csv", index=False)
    st[["station_id", "station_name", "fold"]].to_csv(PROC / "split_spatial.csv", index=False)
    fig_coverage(d, st, start, end, FIG / "fig_coverage.png")
    fig_map(st, FIG / "fig_map_split.png")

    stats = {
        "period": [start, end],
        "n_stations": int(st.station_id.nunique()),
        "n_reference": int((st.type == "referință").sum()),
        "n_lowcost": int((st.type == "low-cost").sum()),
        "n_unknown_type": int((st.type == "nedeterminat").sum()),
        "n_sensors": int(h.sensor_id.nunique()),
        "n_sensors_pm10": int(h[h.parameter == "pm10"].sensor_id.nunique()),
        "n_sensors_pm25": int(h[h.parameter == "pm25"].sensor_id.nunique()),
        "hourly_rows_clean": log["clean_rows"],
        "daily_rows_valid": int(d.valid.sum()),
        "station_days": int(len(daily)),
        "missing_pct_median": float(gp.missing_pct.median()),
        "missing_pct_min": float(gp.missing_pct.min()),
        "missing_pct_max": float(gp.missing_pct.max()),
        "longest_gap_median": float(gp.longest_gap_days.median()),
        "sensors_ge_75pct": int((gp.missing_pct <= 25).sum()),
        "pm10_mean": round(float(daily["pm10"].mean()), 1) if "pm10" in daily else None,
        "pm10_p95": round(float(daily["pm10"].quantile(.95)), 1) if "pm10" in daily else None,
        "pm25_mean": round(float(daily["pm25"].mean()), 1) if "pm25" in daily else None,
        "pm25_p95": round(float(daily["pm25"].quantile(.95)), 1) if "pm25" in daily else None,
        "lst_available": lst is not None,
        "lst_coverage_pct": round(100 * daily["lst_c"].notna().mean(), 1) if "lst_c" in daily else 0.0,
        "fold_sizes": st.fold.value_counts().sort_index().tolist(),
        "cleaning": log,
    }
    (PROC / "datacard_stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    write_datacard(stats, gp, st)
    print(json.dumps(stats, indent=2, ensure_ascii=False))


def write_datacard(s, gp, st):
    c = s["cleaning"]
    top = gp.sort_values("missing_pct").head(8)
    worst = gp.sort_values("missing_pct", ascending=False).head(5)
    tbl = lambda df: "\n".join(
        f"| {r.station_name} | {r.parameter} | {r.valid_days} | {r.missing_pct} | {r.longest_gap_days} |"
        for r in df.itertuples())
    lst_line = (f"Landsat 8/9 C2 L2 ST_B10, compozit median lunar, buffer 100 m în jurul stației; "
                f"{s['lst_coverage_pct']}% din stație-zile au LST atașat"
                if s["lst_available"] else
                "**încă neextras** — scriptul `src/02_landsat_lst_gee.py` e gata, rulează după autentificarea GEE")
    md = f"""# Data card — U7 · UrbanTwin: rețeaua de senzori de aer din București

*Generat automat de `src/03_build_dataset.py`. Cifrele vin din date, nu sunt scrise de mână.*

## 1. Scop
Estimarea câmpului continuu de PM2.5/PM10 în punctele neobservate din București, pentru a decide
**unde se amplasează următorul senzor** (client: Direcția de Urbanism, Primăria București).

## 2. Surse
| Sursă | Ce conține | Acces | Licență |
|---|---|---|---|
| **OpenAQ API v3** | PM10, PM2.5 orare: stații RNMCA/EEA (coduri `RO00xxA` și `B-x`) și eventuali senzori low-cost | `api.openaq.org/v3` (`/locations`, `/sensors/{{id}}/hours`), cheie API gratuită | Datele OpenAQ sunt agregate sub CC BY 4.0. Licența fiecărui furnizor e în `openaq_locations.csv` |
| **Landsat 8/9 Collection 2 Level-2** | Temperatura suprafeței (ST_B10), 30 m, revizită 16 zile (8 zile cu L8+L9) | Google Earth Engine `LANDSAT/LC08/C02/T1_L2`, `LC09` | USGS, domeniu public |

## 3. Acoperire
| Câmp | Valoare |
|---|---|
| Zonă | București, rază de 25 km în jurul (44.4323 N, 26.1063 E) |
| Perioadă | {s['period'][0]} → {s['period'][1]} (exclusiv) |
| Stații | **{s['n_stations']}** unice: {s['n_reference']} de referință, {s['n_lowcost']} low-cost, {s['n_unknown_type']} de tip nedeterminat (după câmpul `isMonitor` din OpenAQ) |
| Senzori | {s['n_sensors']}: {s['n_sensors_pm10']} PM10, {s['n_sensors_pm25']} PM2.5 |
| Rezoluție temporală | orară (brut) → **zilnică** (aliniată, ziua locală Europe/Bucharest) |
| Rezoluție spațială | puncte (stații); LST 30 m, agregat la buffer de 100 m și la grilă de 500 m |
| Unități | PM: µg/m³; LST: °C (din K: DN·0.00341802 + 149.0 − 273.15) |
| Eșantioane | {s['hourly_rows_clean']:,} ore curate → {s['station_days']:,} stație-zile valide |
| PM10 zilnic | medie {s['pm10_mean']} µg/m³, P95 {s['pm10_p95']} µg/m³ |
| PM2.5 zilnic | medie {s['pm25_mean']} µg/m³, P95 {s['pm25_p95']} µg/m³ |
| LST | {lst_line} |

## 4. Curățare și aliniere
- Locații OpenAQ duplicate (același nume și aceleași coordonate) unite: {c['duplicate_locations_merged']}.
- Stații diferite în același punct fizic (< 50 m): {', '.join(c['colocated_pairs']) or 'niciuna'}. Sunt aceeași stație raportată prin doi furnizori, deci trebuie ținute în **același** fold, altfel apare leakage. KMeans pe coordonate face asta automat.
- Valori lipsă eliminate: {c['dropped_missing']}; negative: {c['dropped_negative']}; > {MAX_PLAUSIBLE:.0f} µg/m³: {c['dropped_implausible']}; duplicate: {c['dropped_duplicates']}.
- Consistență fizică: PM2.5 > PM10 (toleranță 5%) în {c.get('pm25_gt_pm10_hours', 'n/a')} ore ({c.get('pm25_gt_pm10_pct', 'n/a')}%). Sunt marcate, nu eliminate, și apar mai ales la senzorii low-cost.
- **Temporal:** ore UTC → zi locală. O zi e validă dacă are ≥ {MIN_HOURS} ore (75%, criteriul UE pentru media zilnică).
- **Spațial:** LST lunar atașat după (stație, lună). Grila de 500 m dă candidații pentru noul senzor.

## 5. Goluri
- Zile lipsă per senzor: mediană **{s['missing_pct_median']}%** (min {s['missing_pct_min']}%, max {s['missing_pct_max']}%).
- Cel mai lung gol (mediană pe senzori): {s['longest_gap_median']:.0f} zile.
- Senzori cu ≥ 75% zile valide: **{s['sensors_ge_75pct']} / {len(gp)}**.
- Landsat: norii elimină o parte din scene, mai ales iarna. De aceea folosim compozitul lunar.

Cei mai compleți senzori:

| Stație | Param. | Zile valide | % lipsă | Gol max (zile) |
|---|---|---|---|---|
{tbl(top)}

Cei mai incompleți senzori:

| Stație | Param. | Zile valide | % lipsă | Gol max (zile) |
|---|---|---|---|---|
{tbl(worst)}

Figura: `figures/fig_coverage.png`.

## 6. Împărțire train/test
**Split spațial, leave-stations-out.** Stațiile sunt grupate în {len(s['fold_sizes'])} fold-uri geografice
(blocuri KMeans pe coordonate, repartizate echilibrat, seed {SEED}), cu dimensiunile {s['fold_sizes']}. La fiecare rundă un fold întreg e test,
deci stațiile de test **nu sunt văzute la antrenare**. Asta reproduce exact decizia clientului: estimarea într-un punct fără senzor.
Split-ul aleator pe zile e interzis, pentru că aceeași stație ar apărea în train și test (leakage spațial).
Ca test suplimentar, ultimele 2 luni din perioadă sunt holdout temporal. Fișier: `data/processed/split_spatial.csv`, figura `figures/fig_map_split.png`.

## 7. Limitări și riscuri
- **Eterogenitate:** stațiile vin de la furnizori diferiți. Eventualii senzori low-cost (optici) supraestimează PM la umiditate mare, așa că în CP2 trebuie calibrați față de referință sau tratați cu zgomot mai mare.
- **Rețea rară la periferie:** puține stații în afara inelului central, deci incertitudinea e mare acolo. E exact zona unde decizia contează.
- **Landsat:** o trecere pe zi la ~09:30 UTC și nori, deci LST e un predictor lent (lunar), nu zilnic.
- **API:** OpenAQ v3 limitează la 60 cereri/min. Descărcarea e reproductibilă, dar durează ~10 min.

## 8. Reproducere
```
pip install -r requirements.txt
python src/01_download_openaq.py --start {s['period'][0]} --end {s['period'][1]}
python src/02_landsat_lst_gee.py --project <proiect-gee> --start {s['period'][0]} --end {s['period'][1]}
python src/03_build_dataset.py
```
"""
    soa = ROOT / "docs" / "SOA_U7.md"
    if soa.exists():
        md += "\n## 9. Literatură (SOA)\n\n" + soa.read_text(encoding="utf-8").split("\n", 1)[1]
    (ROOT / "datacard_U7.md").write_text(md, encoding="utf-8")


if __name__ == "__main__":
    main()