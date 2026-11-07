"""
CP2: baseline-uri si protocol.
Sarcina: estimez PM-ul zilnic intr-o statie "ascunsa" folosind doar celelalte statii din aceeasi zi.

Baseline-uri (de la simplu la greu):
  climatologie  - media lunara a statiilor de antrenare
  medie oras    - media statiilor de antrenare din aceeasi zi
  IDW           - interpolare cu ponderi 1/d^2 din statiile de antrenare din aceeasi zi
  RF (A)        - Random Forest pe reprezentarea A: coordonate, LST, calendar, vecini (IDW, medie, distanta)
  RF (B)        - la fel, dar cu embeddings AlphaEarth (64 val.) in loc de coordonate + LST
                  (doar daca exista data/raw/alphaearth_stations.csv)
Persistenta (maine = azi) nu se poate aplica: intr-un punct fara senzor nu exista "azi".

Protocol:
  spatial - cele 5 fold-uri de statii de la CP1; statiile de test nu apar deloc la antrenare
  aleator - 5 fold-uri pe randuri statie-zi; il rulez doar ca sa arat cat umfla rezultatele

Rulare: python src/06_baselines.py            (ambele tinte: pm25 si pm10)
        python src/06_baselines.py --target pm10
"""
import argparse
import sys
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor

ROOT = Path(__file__).resolve().parents[1]
PROC, RAW, FIG = ROOT / "data" / "processed", ROOT / "data" / "raw", ROOT / "figures"
SEED = 42
N_FOLDS = 5
LAT0 = 44.43


def load(target):
    d = pd.read_csv(PROC / "pm_daily_aligned.csv", parse_dates=["date"])
    st = pd.read_csv(PROC / "stations.csv").drop_duplicates("station_id").set_index("station_id")
    d = d.dropna(subset=[target])
    stations = sorted(d.station_id.unique())
    days = pd.date_range(d.date.min(), d.date.max(), freq="D")
    Y = d.pivot_table(index="date", columns="station_id", values=target).reindex(index=days, columns=stations)
    obs = Y.notna().to_numpy()
    Yv = Y.to_numpy()
    # LST lunar pe statie (cu umplere din media lunara a orasului unde lipseste)
    if "lst_c" in d:
        L = d.pivot_table(index="date", columns="station_id", values="lst_c").reindex(index=days, columns=stations)
        L = L.apply(lambda c: c.fillna(L.mean(axis=1)))
        L = L.fillna(L.stack().mean()).to_numpy()
    else:
        L = np.zeros_like(Yv)
    s = st.loc[stations]
    xy = np.c_[(s.longitude - 26.1) * 111.32 * np.cos(np.radians(LAT0)), (s.latitude - LAT0) * 110.57]
    fold = s.fold.to_numpy()
    emb = None
    p = RAW / "alphaearth_stations.csv"
    if p.exists():
        e = pd.read_csv(p).drop_duplicates("station_id").set_index("station_id").reindex(stations)
        emb = e.fillna(e.mean()).to_numpy()
    return Yv, obs, L, xy, fold, days, stations, emb


def neighbour_feats(Yv, known, xy):
    """Pentru fiecare (zi, statie): IDW, media si distanta la cea mai apropiata statie cunoscuta,
    calculate DOAR din celulele 'known' si excluzand statia insasi."""
    D = np.hypot(*(xy[:, None, :] - xy[None, :, :]).transpose(2, 0, 1))
    D = np.maximum(D, 0.1)                      # statii aproape suprapuse
    W = 1.0 / D ** 2
    np.fill_diagonal(W, 0.0)                    # exclud statia insasi
    Yk = np.where(known, Yv, 0.0)
    K = known.astype(float)
    den = K @ W.T
    idw = np.divide(Yk @ W.T, den, out=np.full_like(den, np.nan), where=den > 0)
    n_known = K.sum(1, keepdims=True) - K
    tot = Yk.sum(1, keepdims=True) - Yk
    city = np.divide(tot, n_known, out=np.full_like(tot, np.nan), where=n_known > 0)
    Dn = np.where(np.eye(len(xy), dtype=bool), np.inf, D)
    near = np.where(known[:, None, :], Dn[None, :, :], np.inf).min(axis=2)
    near[np.isinf(near)] = np.nan
    return idw, city, near, n_known


def clim(Yv, known, days):
    m = days.month.to_numpy()
    out = np.full(Yv.shape, np.nan)
    for mo in np.unique(m):
        r = m == mo
        v = Yv[r][known[r]]
        out[r] = v.mean() if v.size else np.nan
    return out


def metrics(y, p):
    ok = ~np.isnan(p)
    y, p = y[ok], p[ok]
    rmse = float(np.sqrt(np.mean((y - p) ** 2)))
    mae = float(np.mean(np.abs(y - p)))
    r2 = float(1 - np.sum((y - p) ** 2) / np.sum((y - y.mean()) ** 2))
    return rmse, mae, r2


def run_split(Yv, obs, L, xy, days, emb, train_mask, test_mask):
    idw, city, near, nk = neighbour_feats(Yv, train_mask, xy)
    cl = clim(Yv, train_mask, days)
    S = Yv.shape[1]
    doy = np.repeat(days.day_of_year.to_numpy()[:, None], S, 1)
    dow = np.repeat(days.day_of_week.to_numpy()[:, None], S, 1)
    X0 = np.repeat(xy[None], len(days), 0)
    common = [np.sin(2 * np.pi * doy / 365.25), np.cos(2 * np.pi * doy / 365.25), dow,
              idw, city, near, nk, cl]
    feats_A = np.stack([X0[..., 0], X0[..., 1], L] + common, -1)
    preds = {"Climatologie": cl, "Medie oraș (zi)": city, "IDW": idw}
    ytr, yte = Yv[train_mask], Yv[test_mask]

    def fit(F, name):
        Xtr, Xte = F[train_mask], F[test_mask]
        # completez lipsurile cu media pe coloana din antrenare (nu cu media intregii matrice)
        with np.errstate(all="ignore"):
            mu = np.nan_to_num(np.nanmean(Xtr, axis=0))
        Xtr = np.where(np.isnan(Xtr), mu, Xtr)
        Xte = np.where(np.isnan(Xte), mu, Xte)
        rf = RandomForestRegressor(n_estimators=300, min_samples_leaf=5, max_features=0.5,
                                   n_jobs=-1, random_state=SEED).fit(Xtr, ytr)
        p = np.full(Yv.shape, np.nan)
        p[test_mask] = rf.predict(Xte)
        preds[name] = p

    fit(feats_A, "RF (A: coord+LST+vecini)")
    if emb is not None:
        E = np.repeat(emb[None], len(days), 0)
        feats_B = np.concatenate([E, np.stack(common, -1)], -1)
        fit(feats_B, "RF (B: AlphaEarth+vecini)")
    return {k: metrics(yte, v[test_mask]) for k, v in preds.items()}


def evaluate(target):
    Yv, obs, L, xy, fold, days, stations, emb = load(target)
    rows = []
    # protocol 1: spatial (statii intregi ascunse)
    for f in range(N_FOLDS):
        te_st = fold == f
        if not te_st.any():
            continue
        test_mask = obs & te_st[None, :]
        train_mask = obs & ~te_st[None, :]
        for m, (rmse, mae, r2) in run_split(Yv, obs, L, xy, days, emb, train_mask, test_mask).items():
            rows.append(dict(target=target, protocol="spațial", fold=f, method=m,
                             rmse=rmse, mae=mae, r2=r2, n_test=int(test_mask.sum())))
    # protocol 2: aleator pe randuri statie-zi (leakage)
    rng = np.random.default_rng(SEED)
    rnd = np.full(obs.shape, -1)
    rnd[obs] = rng.integers(0, N_FOLDS, obs.sum())
    for f in range(N_FOLDS):
        test_mask, train_mask = rnd == f, obs & (rnd != f)
        for m, (rmse, mae, r2) in run_split(Yv, obs, L, xy, days, emb, train_mask, test_mask).items():
            rows.append(dict(target=target, protocol="aleator", fold=f, method=m,
                             rmse=rmse, mae=mae, r2=r2, n_test=int(test_mask.sum())))
    info = dict(n_stations=len(stations), n_station_days=int(obs.sum()),
                period=[str(days.min().date()), str(days.max().date())], alphaearth=emb is not None)
    return pd.DataFrame(rows), info


def summarise(res):
    g = res.groupby(["target", "protocol", "method"])
    s = g.agg(rmse=("rmse", "mean"), rmse_sd=("rmse", "std"), mae=("mae", "mean"),
              r2=("r2", "mean"), r2_sd=("r2", "std")).reset_index()
    return s.round(2)


def figure(summary, target, path):
    s = summary[summary.target == target]
    methods = list(dict.fromkeys(s.method))
    sp = s[s.protocol == "spațial"].set_index("method").reindex(methods)
    ra = s[s.protocol == "aleator"].set_index("method").reindex(methods)
    x = np.arange(len(methods))
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(x - 0.2, sp.rmse, 0.4, yerr=sp.rmse_sd, capsize=3, color="#1B2A41", label="split spațial (onest)")
    ax.bar(x + 0.2, ra.rmse, 0.4, yerr=ra.rmse_sd, capsize=3, color="#C8702A", label="split aleator (leakage)")
    ax.set_xticks(x, methods, rotation=15, ha="right", fontsize=8)
    ax.set_ylabel(f"RMSE {target.upper().replace('PM25', 'PM2.5')} (µg/m³)")
    ax.set_title("Eroarea în stații ascunse: medie ± abatere pe 5 fold-uri")
    ax.grid(axis="y", ls="--", alpha=.4)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", choices=["pm25", "pm10", "both"], default="both")
    args = ap.parse_args()
    targets = ["pm25", "pm10"] if args.target == "both" else [args.target]
    FIG.mkdir(exist_ok=True)
    all_res, infos = [], {}
    for t in targets:
        print(f"== {t} ==")
        r, info = evaluate(t)
        all_res.append(r)
        infos[t] = info
    res = pd.concat(all_res)
    res.to_csv(PROC / "baseline_results_per_fold.csv", index=False)
    summary = summarise(res)
    summary.to_csv(PROC / "baseline_summary.csv", index=False)
    for t in targets:
        figure(summary, t, FIG / f"fig_baselines_{t}.png")
    (PROC / "baseline_info.json").write_text(json.dumps(infos, indent=2, ensure_ascii=False), encoding="utf-8")
    pd.set_option("display.width", 160)
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
