"""
CP3: metoda (Gaussian Process / kriging) vs. baseline-uri, pe seed-uri, cu intervale de incredere.
Sarcina ramane cea din CP2: PM zilnic intr-o statie "ascunsa", din celelalte statii din aceeasi zi.

Metoda: GP pe log(PM+1), cu hiperparametri comuni pentru toate zilele (zilele = realizari independente):
  k(s, s') = c + s2 * Matern32(r) + tau2 * [s = s']
  r^2      = |xy - xy'|^2 / l^2  (+ (LST - LST')^2 / lL^2 in varianta cu LST)
  c        = nivelul zilei (necunoscut, integrat analitic -> kriging ordinar)
  s2, l    = cat de mult si pe ce distanta difera statiile de media zilei
  tau2     = zgomot local / de senzor
Hiperparametrii se invata prin maximizarea verosimilitatii marginale DOAR pe statiile de antrenare.
In plus fata de baseline-uri, GP da si o incertitudine in fiecare punct (folosita la CP4-5 pentru amplasare).

Protocol: split spatial (statii intregi ascunse), 5 fold-uri x 3 seed-uri. Seed-ul schimba impartirea
statiilor in fold-uri (KMeans, ca la CP1; seed 42 = fold-urile din CP1) si seed-ul RF.
IC 95%: bootstrap pe statii (statia = unitatea independenta), aceleasi esantioane pentru toate metodele,
deci diferentele sunt pereche.

Rulare: python src/07_gp_vs_baselines.py              (pm10 si pm25)
        python src/07_gp_vs_baselines.py --target pm10
Iesiri: results_v1_U7.csv (radacina), data/processed/cp3_*.csv, figures/fig_cp3_rmse_ci.png
"""
import argparse
import importlib.util
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.cluster import KMeans

ROOT = Path(__file__).resolve().parents[1]
PROC, FIG = ROOT / "data" / "processed", ROOT / "figures"
SEEDS = [42, 7, 123]
N_FOLDS = 5
N_BOOT = 2000
Z90 = 1.6449

_spec = importlib.util.spec_from_file_location("baselines", ROOT / "src" / "06_baselines.py")
B = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(B)

GP_COORD = "GP (kriging: coord)"
GP_LST = "GP (coord+LST)"
REF = "IDW"                      # baseline-ul de referinta pentru diferente
REF2 = "Medie oraș (zi)"


# ---------------------------------------------------------------- fold-uri pe seed
def folds_for_seed(stations, seed):
    """Aceeasi procedura ca in 03_build_dataset.py, cu alt random_state."""
    st = pd.read_csv(PROC / "stations.csv").drop_duplicates("station_id").reset_index(drop=True)
    k = min(2 * N_FOLDS, len(st))
    st["block"] = KMeans(n_clusters=k, n_init=10, random_state=seed).fit_predict(
        st[["latitude", "longitude"]].to_numpy())
    sizes, fold_of = [0] * N_FOLDS, {}
    for b, n in st["block"].value_counts().items():
        f = int(np.argmin(sizes)); fold_of[b] = f; sizes[f] += n
    return st.set_index("station_id")["block"].map(fold_of).loc[stations].to_numpy()


# ---------------------------------------------------------------- GP
class DailyGP:
    """GP cu hiperparametri comuni, potrivit pe toate zilele deodata (matrici padate, Cholesky in lot)."""

    def __init__(self, use_lst):
        self.use_lst = use_lst

    def _kernel(self, th, xa, xb, la, lb):
        c, s2, l, tau2 = np.exp(th[:4])
        d2 = ((xa[..., :, None, :] - xb[..., None, :, :]) ** 2).sum(-1) / l ** 2
        if self.use_lst:
            d2 = d2 + (la[..., :, None] - lb[..., None, :]) ** 2 / np.exp(th[4]) ** 2
        r = np.sqrt(3 * d2)
        return c + s2 * (1 + r) * np.exp(-r)

    def _batch(self, Z, known, xy, L):
        days = np.where(known.any(1))[0]
        nmax = int(known[days].sum(1).max())
        X = np.zeros((len(days), nmax, 2)); Ls = np.zeros((len(days), nmax))
        R = np.zeros((len(days), nmax)); M = np.zeros((len(days), nmax), bool)
        for i, t in enumerate(days):
            j = np.where(known[t])[0]
            X[i, :len(j)], Ls[i, :len(j)], R[i, :len(j)], M[i, :len(j)] = xy[j], L[t, j], Z[t, j], True
        return X, Ls, R, M

    def _nll(self, th, X, Ls, R, M):
        tau2 = np.exp(th[3])
        K = self._kernel(th, X, X, Ls, Ls)
        mm = M[:, :, None] & M[:, None, :]
        K = np.where(mm, K, 0.0)
        n = K.shape[1]
        eye = np.eye(n, dtype=bool)[None]
        K = np.where(eye, np.where(M[:, :, None], K + tau2, 1.0), K)   # padding -> identitate
        try:
            C = np.linalg.cholesky(K)
        except np.linalg.LinAlgError:
            return 1e12
        a = np.linalg.solve(K, R[..., None])[..., 0]
        logdet = 2 * np.log(np.diagonal(C, axis1=1, axis2=2)).sum()
        return 0.5 * (R * a).sum() + 0.5 * logdet + 0.5 * M.sum() * np.log(2 * np.pi)

    def fit(self, Yv, train_mask, xy, L):
        Z = np.log1p(np.where(train_mask, Yv, np.nan))
        self.mu = np.nanmean(Z)
        Z = np.nan_to_num(Z - self.mu)
        X, Ls, R, M = self._batch(Z, train_mask, xy, L)
        dm = np.array([R[i, M[i]].mean() for i in range(len(R))])
        an = np.concatenate([R[i, M[i]] - dm[i] for i in range(len(R))])
        th0 = [np.log(max(dm.var(), 1e-3)), np.log(max(an.var() / 2, 1e-3)), np.log(5.0),
               np.log(max(an.var() / 2, 1e-3))] + ([np.log(3.0)] if self.use_lst else [])
        bounds = [(-7, 3), (-7, 3), (np.log(0.3), np.log(100)), (-7, 3)] + \
                 ([(np.log(0.3), np.log(50))] if self.use_lst else [])
        res = minimize(self._nll, th0, args=(X, Ls, R, M), method="L-BFGS-B", bounds=bounds)
        self.th = res.x
        self.nll = float(res.fun)
        return self

    def params(self):
        names = ["c", "sigma2", "l_km", "tau2"] + (["l_lst_C"] if self.use_lst else [])
        return dict(zip(names, np.exp(self.th).round(4)))

    def predict(self, Yv, train_mask, test_mask, xy, L):
        """Medie (µg/m³, transformare inversa lognormala) si sd pe scara log, pe celulele test."""
        Z = np.log1p(np.where(train_mask, Yv, np.nan)) - self.mu
        c, s2, l, tau2 = np.exp(self.th[:4])
        mean = np.full(Yv.shape, np.nan); sd = np.full(Yv.shape, np.nan)
        prior = c + s2 + tau2
        for t in np.where(test_mask.any(1))[0]:
            te, tr = np.where(test_mask[t])[0], np.where(train_mask[t])[0]
            if len(tr) == 0:
                m, v = np.zeros(len(te)), np.full(len(te), prior)
            else:
                K = self._kernel(self.th, xy[tr], xy[tr], L[t, tr], L[t, tr]) + tau2 * np.eye(len(tr))
                ks = self._kernel(self.th, xy[te], xy[tr], L[t, te], L[t, tr])
                A = np.linalg.solve(K, np.c_[Z[t, tr], ks.T])
                m = ks @ A[:, 0]
                v = np.maximum(prior - np.einsum("ij,ji->i", ks, A[:, 1:]), 1e-9)
            mean[t, te] = np.expm1(self.mu + m + v / 2)
            sd[t, te] = np.sqrt(v)
        return mean, sd


# ---------------------------------------------------------------- evaluare
def evaluate(target):
    Yv, obs, L, xy, _, days, stations, emb = B.load(target)
    cells, folds_rows, hyp = [], [], []
    for seed in SEEDS:
        fold = folds_for_seed(stations, seed)
        for f in range(N_FOLDS):
            te_st = fold == f
            if not te_st.any():
                continue
            test_mask, train_mask = obs & te_st[None, :], obs & ~te_st[None, :]
            preds = B.predict_split(Yv, L, xy, days, emb, train_mask, test_mask, seed=seed)
            near = preds.pop("_near_km")
            gp_sd = {}
            for name, use_lst in [(GP_COORD, False), (GP_LST, True)]:
                gp = DailyGP(use_lst).fit(Yv, train_mask, xy, L)
                preds[name], gp_sd[name] = gp.predict(Yv, train_mask, test_mask, xy, L)
                hyp.append(dict(target=target, seed=seed, fold=f, method=name, nll=round(gp.nll, 1), **gp.params()))
            ti, si = np.where(test_mask)
            df = pd.DataFrame(dict(target=target, seed=seed, fold=f, station_id=np.array(stations)[si],
                                   date=days[ti].date, y=Yv[ti, si], near_km=near[ti, si]))
            for m, p in preds.items():
                df[m] = p[ti, si]
            z = np.log1p(Yv[ti, si])
            for m, s in gp_sd.items():
                # acoperirea intervalului predictiv 90% (pe scara log, in jurul mediei latente)
                mlat = np.log1p(df[m].to_numpy()) - s[ti, si] ** 2 / 2
                df[f"{m} |cov90"] = (np.abs(z - mlat) <= Z90 * s[ti, si]).astype(int)
            cells.append(df)
            for m in preds:
                rmse, mae, r2 = B.metrics(df.y.to_numpy(), df[m].to_numpy())
                folds_rows.append(dict(target=target, seed=seed, fold=f, method=m, rmse=rmse, mae=mae, r2=r2,
                                       n_test=len(df), n_test_stations=int(te_st.sum())))
            print(f"  {target} seed {seed} fold {f}: " +
                  ", ".join(f"{m.split(' (')[0]}{'+L' if m == GP_LST else ''}={folds_rows[-len(preds) + i]['rmse']:.2f}"
                            for i, m in enumerate(preds)), flush=True)
    return pd.concat(cells, ignore_index=True), pd.DataFrame(folds_rows), pd.DataFrame(hyp)


def methods_of(cells):
    skip = {"target", "seed", "fold", "station_id", "date", "y", "near_km", "dist"}
    return [c for c in cells.columns if c not in skip and "|" not in c]


def summarise(cells, rng):
    """RMSE comasat pe seed (fiecare statie e testata o data pe seed), mediat pe seed-uri;
    IC 95% prin bootstrap pe statii, pereche intre metode."""
    out = []
    for target, c in cells.groupby("target"):
        ms = methods_of(c)
        st = np.array(sorted(c.station_id.unique()))
        seeds = sorted(c.seed.unique())
        # SSE, AE, n pe (seed, statie, metoda)
        sse = np.zeros((len(seeds), len(st), len(ms))); ae = np.zeros_like(sse); n = np.zeros((len(seeds), len(st)))
        for i, s in enumerate(seeds):
            g = c[c.seed == s].groupby("station_id")
            for k, m in enumerate(ms):
                e = c.loc[c.seed == s, m] - c.loc[c.seed == s, "y"]
                sse[i, :, k] = (e ** 2).groupby(c.loc[c.seed == s, "station_id"]).sum().reindex(st).fillna(0)
                ae[i, :, k] = e.abs().groupby(c.loc[c.seed == s, "station_id"]).sum().reindex(st).fillna(0)
            n[i] = g.size().reindex(st).fillna(0)

        def rmse_of(idx):          # -> (metode,) RMSE mediat pe seed-uri
            return np.sqrt(sse[:, idx].sum(1) / n[:, idx].sum(1)[:, None]).mean(0)

        point = rmse_of(np.arange(len(st)))
        per_seed = np.sqrt(sse.sum(1) / n.sum(1)[:, None])
        boot = np.array([rmse_of(rng.integers(0, len(st), len(st))) for _ in range(N_BOOT)])
        k_ref, k_ref2 = ms.index(REF), ms.index(REF2)
        y = c.y.to_numpy()
        for k, m in enumerate(ms):
            d1, d2 = boot[:, k] - boot[:, k_ref], boot[:, k] - boot[:, k_ref2]
            r2 = np.mean([B.metrics(c.loc[c.seed == s, "y"].to_numpy(), c.loc[c.seed == s, m].to_numpy())[2]
                          for s in seeds])
            cov = c[f"{m} |cov90"].mean() if f"{m} |cov90" in c else np.nan
            out.append(dict(
                target=target, method=m, n_stations=len(st), n_station_days=int(n[0].sum()),
                n_seeds=len(seeds), n_folds=N_FOLDS,
                rmse=point[k], rmse_ci95_lo=np.percentile(boot[:, k], 2.5), rmse_ci95_hi=np.percentile(boot[:, k], 97.5),
                rmse_seed_min=per_seed[:, k].min(), rmse_seed_max=per_seed[:, k].max(),
                mae=(ae[:, :, k].sum(1) / n.sum(1)).mean(), r2=r2,
                d_rmse_vs_idw=point[k] - point[k_ref],
                d_vs_idw_ci95_lo=np.percentile(d1, 2.5), d_vs_idw_ci95_hi=np.percentile(d1, 97.5),
                d_rmse_vs_medie=point[k] - point[k_ref2],
                d_vs_medie_ci95_lo=np.percentile(d2, 2.5), d_vs_medie_ci95_hi=np.percentile(d2, 97.5),
                coverage90=cov))
    s = pd.DataFrame(out)
    num = s.select_dtypes("number").columns.drop(["n_stations", "n_station_days", "n_seeds", "n_folds"])
    s[num] = s[num].round(3)
    return s


def by_distance(cells):
    bins, labels = [0, 2, 5, np.inf], ["< 2 km", "2–5 km", "> 5 km"]
    rows = []
    for target, c in cells.groupby("target"):
        c = c.assign(dist=pd.cut(c.near_km, bins, labels=labels, right=False))
        for lab, g in c.groupby("dist", observed=True):
            r = dict(target=target, dist_nearest_train=lab, n=len(g))
            for m in methods_of(c):
                r[m] = round(float(np.sqrt(np.mean((g[m] - g.y) ** 2))), 2)
            rows.append(r)
    return pd.DataFrame(rows)


def figure(summary, path):
    ts = list(summary.target.unique())
    fig, axes = plt.subplots(1, len(ts), figsize=(5.5 * len(ts), 3.8), squeeze=False)
    for ax, t in zip(axes[0], ts):
        s = summary[summary.target == t].reset_index(drop=True)
        col = ["#C8702A" if m.startswith("GP") else "#1B2A41" for m in s.method]
        y = np.arange(len(s))[::-1]
        for i in range(len(s)):
            ax.errorbar(s.rmse[i], y[i], xerr=[[s.rmse[i] - s.rmse_ci95_lo[i]], [s.rmse_ci95_hi[i] - s.rmse[i]]],
                        fmt="none", ecolor=col[i], capsize=3)
        ax.scatter(s.rmse, y, c=col, zorder=3)
        ax.axvline(s.loc[s.method == REF, "rmse"].iloc[0], ls="--", c="#6A7179", lw=1)
        ax.set_yticks(y, s.method, fontsize=8)
        ax.set_xlabel(f"RMSE {t.upper().replace('PM25', 'PM2.5')} (µg/m³), IC 95%")
        ax.grid(axis="x", ls="--", alpha=.4)
    fig.suptitle("Stații ascunse: 5 fold-uri spațiale × 3 seed-uri, bootstrap pe stații", fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", choices=["pm25", "pm10", "both"], default="both")
    args = ap.parse_args()
    targets = ["pm10", "pm25"] if args.target == "both" else [args.target]
    C, Fr, H = [], [], []
    for t in targets:
        print(f"== {t} ==")
        c, f, h = evaluate(t)
        C.append(c); Fr.append(f); H.append(h)
    cells, folds, hyp = pd.concat(C), pd.concat(Fr), pd.concat(H)
    summary = summarise(cells, np.random.default_rng(0))
    summary.to_csv(ROOT / "results_v1_U7.csv", index=False)
    folds.round(4).to_csv(PROC / "cp3_results_per_fold.csv", index=False)
    hyp.to_csv(PROC / "cp3_gp_hyperparams.csv", index=False)
    dist = by_distance(cells)
    dist.to_csv(PROC / "cp3_error_by_distance.csv", index=False)
    cells.round(3).to_csv(PROC / "cp3_predictions.csv.gz", index=False)
    FIG.mkdir(exist_ok=True)
    figure(summary, FIG / "fig_cp3_rmse_ci.png")
    pd.set_option("display.width", 200); pd.set_option("display.max_columns", 30)
    print(summary[["target", "method", "rmse", "rmse_ci95_lo", "rmse_ci95_hi", "r2",
                   "d_rmse_vs_idw", "d_vs_idw_ci95_lo", "d_vs_idw_ci95_hi", "coverage90"]].to_string(index=False))
    print(dist.to_string(index=False))
    print(hyp.groupby(["target", "method"]).median(numeric_only=True).drop(columns=["seed", "fold"]).to_string())


if __name__ == "__main__":
    main()
