# IC3 · U7 · UrbanTwin: rețeaua de senzori de aer din București

**Întrebare:** cum estimăm câmpul continuu de PM2.5/PM10 în punctele neobservate din București,
ca să alegem locul următorului senzor?
**Client:** Urbanism, Primăria București. **Decizia:** unde se investește în următorul senzor fizic.

## Stratul 1: Observații (CP1)

| Pas | Script | Ieșire |
|---|---|---|
| 1. Descărcare PM orar OpenAQ v3 (paginat, cu interval de timp) | `src/01_download_openaq.py` | `data/raw/openaq_locations.csv`, `data/raw/openaq_hourly.csv` |
| 2. Landsat 8/9 LST din GEE (compozit lunar la stații + grilă 500 m) | `src/02_landsat_lst_gee.py` | `data/raw/landsat_lst_*.csv` |
| 3. Curățare, aliniere zilnică, goluri, split spațial, data card | `src/03_build_dataset.py` | `data/processed/*.csv`, `figures/*.png`, `datacard_U7.md` |


```bash
pip install -r requirements.txt
# Windows PowerShell:  $env:OPENAQ_API_KEY="cheia_ta"
export OPENAQ_API_KEY=cheia_api
python src/01_download_openaq.py --start 2024-01-01 --end 2025-01-01
earthengine authenticate - pentru autentificare
python src/02_landsat_lst_gee.py --project <IDUL RESPECTIV> --start 2024-01-01 --end 2025-01-01
python src/03_build_dataset.py

```

## Stratul 2: Reprezentare (CP2)

**Sarcina:** estimez PM-ul zilnic într-o stație „ascunsă” folosind doar celelalte stații din aceeași zi
(imită un punct fără senzor).

| Pas | Script | Ieșire |
|---|---|---|
| 4. Embeddings AlphaEarth (Google Satellite Embedding V1, 64-d, 10 m) la stații + grilă 500 m | `src/05_alphaearth_gee.py` | `data/raw/alphaearth_stations.csv`, `data/raw/alphaearth_grid_500m.csv` |
| 5. Baseline-uri pe split spațial vs. aleator, PM10 și PM2.5 | `src/06_baselines.py` | `data/processed/baseline_summary.csv`, `baseline_results_per_fold.csv`, `baseline_info.json`, `figures/fig_baselines_*.png` |

- **Reprezentarea A:** coordonate, LST lunar (Landsat), calendar (zi din an, zi din săptămână),
  vecinii din aceeași zi (IDW, media orașului, distanța la cea mai apropiată stație cunoscută).
- **Alternativa B:** embeddings AlphaEarth (64 valori) în locul coordonatelor + LST, cu aceiași vecini.
  Intră automat în `06_baselines.py` dacă există `data/raw/alphaearth_stations.csv`.
- **Baseline-uri:** climatologie lunară, media orașului din aceeași zi, IDW (1/d²), Random Forest pe A (și pe B).
  Persistența (mâine = azi) nu se aplică: într-un punct fără senzor nu există „azi”.
- **Metrici:** RMSE (principală), MAE, R², medie ± abatere pe fold-uri.
- **Protocol:** split **spațial**, cele 5 fold-uri de stații de la CP1. Stațiile de test nu apar deloc la antrenare,
  exact ca un punct fără senzor. Splitul **aleator** pe rânduri stație-zi e rulat doar ca să arate cât de mult
  umflă rezultatele (leakage). LOYO e amânat: deocamdată avem doar anul 2024.

Rezultat (RMSE spațial, µg/m³): la PM10 (62 stații) IDW și media orașului ≈ 11,3, RF (A) 11,9; cu split aleator,
RF ar părea cu ~35% mai bun. La PM2.5 sunt doar 15 stații (R² ≈ 0), deci concluziile sunt slabe.

```bash
python src/05_alphaearth_gee.py --project <IDUL RESPECTIV> --year 2024   # opțional, pentru B
python src/06_baselines.py            # ambele ținte; sau --target pm10 / pm25
```

Slide-uri: `CP2_U7.pptx`

## Stratul 3: Învățare (CP3)

**Metoda:** Gaussian Process (kriging ordinar) pe log(PM+1), cu hiperparametri comuni pentru toate zilele:
`k = c + σ²·Matérn3/2(d/ℓ) + τ²`. Aici `c` e nivelul zilei (integrat analitic), `σ², ℓ` dau diferențele locale,
iar `τ²` e zgomotul. Varianta a doua adaugă LST ca dimensiune cu lungimea ei de corelație.
Hiperparametrii se învață din verosimilitatea marginală, doar pe stațiile de antrenare.
GP dă și o incertitudine în fiecare punct, de care avem nevoie la amplasarea senzorului (CP4–5).

| Pas | Script | Ieșire |
|---|---|---|
| 6. GP vs. baseline-uri, 5 fold-uri spațiale × 3 seed-uri (42, 7, 123), IC 95% bootstrap pe stații | `src/07_gp_vs_baselines.py` | `results_v1_U7.csv`, `data/processed/cp3_*.csv`, `cp3_predictions.csv.gz`, `figures/fig_cp3_rmse_ci.png` |

- Seed-ul schimbă împărțirea stațiilor în fold-uri (KMeans, ca la CP1; seed 42 = fold-urile CP1) și seed-ul RF.
- IC: bootstrap pe stații (2000 de eșantioane), aceleași pentru toate metodele, deci Δ față de IDW e pereche.
- RMSE e comasat pe toate stație-zilele testate, nu mediat pe fold-uri, de aceea diferă puțin de CP2.

**Rezultat (negativ, raportat ca atare):** la PM10, GP are RMSE 11,07 µg/m³ față de 11,02 la IDW
(Δ +0,05, IC 95% [−0,12; +0,24]), deci nu e mai bun. Nicio metodă nu bate semnificativ IDW sau media orașului.
Câștigul GP e incertitudinea calibrată: 88% din valori cad în intervalul de 90% (PM2.5: 91%).
GP învață că doar ~12% din variație e spațială structurată (ℓ ≈ 5 km), iar restul e nivelul zilei plus zgomot.
LST nu ajută. PM2.5 are 15 stații și IC foarte late.

```bash
python src/07_gp_vs_baselines.py        # ~2 min; sau --target pm10 / pm25
```

Slide-uri: `CP3_U7.pptx`

Documente: [`datacard_U7.md`](datacard_U7.md) · [`docs/SOA_U7.md`](docs/SOA_U7.md)

Cheia API **nu** se pune în cod. Se citește din variabila de mediu `OPENAQ_API_KEY`.
