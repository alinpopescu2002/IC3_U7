# Tabel SOA — U7: estimarea câmpului de poluare în puncte neobservate și amplasarea senzorilor

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
