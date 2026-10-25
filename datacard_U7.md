# Data card — U7 · UrbanTwin: rețeaua de senzori de aer din București

*Generat automat de `src/03_build_dataset.py`. Cifrele vin din date, nu sunt scrise de mână.*

## 1. Scop
Estimarea câmpului continuu de PM2.5/PM10 în punctele neobservate din București, pentru a decide
**unde se amplasează următorul senzor** (client: Direcția de Urbanism, Primăria București).

## 2. Surse
| Sursă | Ce conține | Acces | Licență |
|---|---|---|---|
| **OpenAQ API v3** | PM10, PM2.5 orare: stații RNMCA/EEA (coduri `RO00xxA` și `B-x`) și eventuali senzori low-cost | `api.openaq.org/v3` (`/locations`, `/sensors/{id}/hours`), cheie API gratuită | Datele OpenAQ sunt agregate sub CC BY 4.0. Licența fiecărui furnizor e în `openaq_locations.csv` |
| **Landsat 8/9 Collection 2 Level-2** | Temperatura suprafeței (ST_B10), 30 m, revizită 16 zile (8 zile cu L8+L9) | Google Earth Engine `LANDSAT/LC08/C02/T1_L2`, `LC09` | USGS, domeniu public |

## 3. Acoperire
| Câmp | Valoare |
|---|---|
| Zonă | București, rază de 25 km în jurul (44.4323 N, 26.1063 E) |
| Perioadă | 2023-12-31 → 2025-01-01 (exclusiv) |
| Stații | **63** unice: 59 de referință, 4 low-cost, 0 de tip nedeterminat (după câmpul `isMonitor` din OpenAQ) |
| Senzori | 114: 92 PM10, 22 PM2.5 |
| Rezoluție temporală | orară (brut) → **zilnică** (aliniată, ziua locală Europe/Bucharest) |
| Rezoluție spațială | puncte (stații); LST 30 m, agregat la buffer de 100 m și la grilă de 500 m |
| Unități | PM: µg/m³; LST: °C (din K: DN·0.00341802 + 149.0 − 273.15) |
| Eșantioane | 293,123 ore curate → 6,642 stație-zile valide |
| PM10 zilnic | medie 24.1 µg/m³, P95 55.6 µg/m³ |
| PM2.5 zilnic | medie 19.1 µg/m³, P95 52.2 µg/m³ |
| LST | Landsat 8/9 C2 L2 ST_B10, compozit median lunar, buffer 100 m în jurul stației; 98.0% din stație-zile au LST atașat |

## 4. Curățare și aliniere
- Locații OpenAQ duplicate (același nume și aceleași coordonate) unite: 29.
- Stații diferite în același punct fizic (< 50 m): RO0065A≈B-1, B-10≈B-10, B-9≈B-9, B-25≈B-25, Domnesti≈Domnesti. Sunt aceeași stație raportată prin doi furnizori, deci trebuie ținute în **același** fold, altfel apare leakage. KMeans pe coordonate face asta automat.
- Valori lipsă eliminate: 18345; negative: 0; > 1000 µg/m³: 0; duplicate: 0.
- Consistență fizică: PM2.5 > PM10 (toleranță 5%) în 974 ore (1.93%). Sunt marcate, nu eliminate, și apar mai ales la senzorii low-cost.
- **Temporal:** ore UTC → zi locală. O zi e validă dacă are ≥ 18 ore (75%, criteriul UE pentru media zilnică).
- **Spațial:** LST lunar atașat după (stație, lună). Grila de 500 m dă candidații pentru noul senzor.

## 5. Goluri
- Zile lipsă per senzor: mediană **77.1%** (min 43.1%, max 100.0%).
- Cel mai lung gol (mediană pe senzori): 155 zile.
- Senzori cu ≥ 75% zile valide: **0 / 114**.
- Landsat: norii elimină o parte din scene, mai ales iarna. De aceea folosim compozitul lunar.

Cei mai compleți senzori:

| Stație | Param. | Zile valide | % lipsă | Gol max (zile) |
|---|---|---|---|---|
| B-5 | pm10 | 209 | 43.1 | 52 |
| B-2 | pm10 | 203 | 44.7 | 52 |
| B-8 | pm10 | 190 | 48.2 | 52 |
| B-6 | pm10 | 187 | 49.0 | 52 |
| B-8 | pm25 | 181 | 50.7 | 52 |
| B-2 | pm10 | 174 | 52.6 | 87 |
| B-3 | pm10 | 168 | 54.2 | 52 |
| B-8 | pm10 | 156 | 57.5 | 57 |

Cei mai incompleți senzori:

| Stație | Param. | Zile valide | % lipsă | Gol max (zile) |
|---|---|---|---|---|
| Domnesti | pm10 | 0 | 100.0 | 367 |
| Domnesti | pm25 | 0 | 100.0 | 367 |
| Bucharest | pm10 | 13 | 96.5 | 354 |
| Bucharest | pm25 | 13 | 96.5 | 354 |
| RO0072A | pm10 | 17 | 95.4 | 337 |

Figura: `figures/fig_coverage.png`.

## 6. Împărțire train/test
**Split spațial, leave-stations-out.** Stațiile sunt grupate în 5 fold-uri geografice
(blocuri KMeans pe coordonate, repartizate echilibrat, seed 42), cu dimensiunile [23, 11, 9, 10, 10]. La fiecare rundă un fold întreg e test,
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
python src/01_download_openaq.py --start 2023-12-31 --end 2025-01-01
python src/02_landsat_lst_gee.py --project <proiect-gee> --start 2023-12-31 --end 2025-01-01
python src/03_build_dataset.py
```

## 9. Literatură (SOA)


| # | Articol | Metodă | Date | Metrică | Rezultat |
|---|---|---|---|---|---|
| 1 | Krause, Singh, Guestrin (2008), *JMLR* 9:235–284 | GP + selecție greedy pe informația mutuală (submodulară) | 2 seturi reale de senzori (temperatură, precipitații) | Informație mutuală / eroare de predicție | Garanție (1−1/e) ≈ 63% din optim; MI bate criteriul de entropie |
| 2 | Zheng, Liu, Hsieh (2013), *KDD* (U-Air) | Co-training: clasificator spațial (ANN) + temporal (CRF) | Beijing, 22 de stații + meteo, POI, drumuri, GPS taxi | Precizie / recall pe clase AQI | PM10: precizie 0.83, recall 0.83; bate interpolarea și CALPUFF |
| 3 | Hsieh, Lin, Zheng (2015), *KDD* | AQInf (graf de afinitate, semi-supervizat) + GEM (minimizare de entropie) pentru stații noi | Beijing, 22 de stații, PM2.5/PM10 orar 2012–13, meteo, POI | RMSE; Top-Rank Ratio | Bate kNN, IDW, kriging ordinar, ANN, SVR, U-Air; TRR < 0.2 la recomandare |
| 4 | Hu et al. (2017), *ES&T* 51(12):6936–44 | Random Forest (AOD + meteo + land-use + PM vecin) | SUA, PM2.5 zilnic 2011 | CV R², RMSPE | R² = 0.80, RMSPE = 2.83 µg/m³ |
| 5 | Stafoggia et al. (2019), *Env. Int.* 124:170–179 | RF spațio-temporal în 5 etape (land-use) | Italia, 1 km, PM zilnic 2013–15, AOD MAIAC | CV R² | PM10: 0.84; PM2.5: 0.86 (etapa 5) |
| 6 | Di et al. (2019), *Env. Int.* 130 | Ansamblu NN + RF + GBM, combinat prin GAM | SUA, 1 km, 2000–2015, AOD, CTM, land-use | CV R² (10-fold) | R² = 0.86 PM2.5 zilnic |
| 7 | Wei et al. (2019), *RSE* 231:111221 | Space-time RF (STRF) | China, ~1 480 de stații, MAIAC AOD 1 km, ERA-Interim | CV R², RMSE | R² = 0.85; RMSE = 15.6 µg/m³ |
| 8 | Mijling (2020), *AMT* 13:4601–17 | Dispersie AERMOD + interpolare optimă a obs. eterogene (referință + low-cost) | Amsterdam, NO₂ orar, 15 stații ref. + senzori low-cost | RMSE relativ | ~39% în raza de 2 km de o stație, ~53% mai departe |
| 9 | Patel et al. (2022), *AAAI* | GP cu kernel nestaționar + Hamming + periodic | Beijing (36 de stații), Londra | RMSE în CV | Beijing: RMSE −9% față de RF, −17% față de ADAIN, −49% față de IDW |
| 10 | Kelp et al. (2023), *GeoHealth* | mrDMD cu cost (echitate) pentru amplasarea senzorilor | Câmp PM2.5 1 km SUA 2005–16 + recensământ ACS | Variabilitate captată / acoperire demografică | Rețele de 150–250 de senzori/oraș; mai mulți senzori în cartiere defavorizate |

**Ce reiese pentru U7:**
- Pentru *estimare* (rândurile 4–7), RF și ansamblurile ajung la CV R² 0.80–0.86. **RF e baseline-ul de bătut.**
- Kriging și IDW sunt baseline-urile spațiale clasice (3, 9).
- Pentru *amplasare*, GP cu informație mutuală (1) și minimizarea entropiei (3) sunt metodele de referință pentru „următorul senzor”.
- Golul: niciun studiu pe București, iar LST e folosit rar ca predictor urban.
- **Atenție:** CV-ul aleator din 4–7 supraestimează performanța în puncte noi. Noi raportăm split spațial.
