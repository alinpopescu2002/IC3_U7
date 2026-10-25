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

Documente: [`datacard_U7.md`](datacard_U7.md) · [`docs/SOA_U7.md`](docs/SOA_U7.md)

Cheia API **nu** se pune în cod. Se citește din variabila de mediu `OPENAQ_API_KEY`.
