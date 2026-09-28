# SIH demonstration guide

## Before the demo

1. Install dependencies and start the app from the project root:

   ```powershell
   python -m pip install -r requirements.txt
   python -m uvicorn backend.main:app --reload
   ```

2. Open `http://127.0.0.1:8000` and `/docs`. Confirm the health endpoint is
   healthy and that the dashboard loads reports and analytics.
3. Explain that the initial database records are labeled sample data. They are
   not current observations or actual citizen submissions.
4. The live dashboard fetches Open-Meteo observations for eight configured
   Indian city points and USGS earthquake events from an India-bounded FDSN
   GeoJSON query. The map also has India and World views with tappable major-city
   markers. Each marker requests current weather, fog/visibility, a five-day
   forecast, and USGS earthquakes of magnitude 2.5+ within 200 km over the past
   30 days. NASA POWER daily weather context is requested manually for a
   selected city/date range. Network/provider availability is required; city
   points are not nationwide coverage and NASA values are not real-time.

## Suggested 5-minute walkthrough

1. **Dashboard and map:** show summary cards, report markers, event filters,
   weather observation and USGS earthquake markers, analytics, active alerts,
   and the sample-data notice. Switch between India and World map views, then
   open a city marker to show weather, forecast, visibility, and nearby USGS
   results. Explain the 200 km/30-day/magnitude 2.5 query limits.
2. **Submit a report:** expand “Submit a weather report”; enter a unique
   location and coordinates, choose an event, describe the observation, and
   submit it.
3. **Explain the response:** the report is saved in PostgreSQL with status
   `Review`. When trained artifacts are available, the local text model adds a
   separate classification signal. It does not verify the event.
4. **Show duplicate handling:** submit the same event type, coordinates, and
   time again. The second report remains stored and is flagged as a possible
   duplicate when it is within 5 km and the 24-hour matching window.
5. **Show external data:** identify Open-Meteo and USGS as separate sources;
   distinguish observation/event time from retrieval time and citizen-report
   time. The location/date filters apply to citizen reports. Provider errors
   should be shown as unavailable, not replaced with sample readings. Use the
   NASA POWER panel to request daily context and point out unavailable fill
   values rather than treating them as zero.
6. **Close with limitations:** this app has no report moderation/status-update
   interface. New submissions stay in `Review` and do not create alerts
   automatically; seeded verified records and their alerts are illustrative
   samples.

## API checks

- `GET /api/health`
- `GET /api/summary`
- `GET /api/events?limit=10`
- `POST /api/events` with a timezone-aware ISO timestamp and coordinates
- `POST /api/classify` with non-empty text (trained models required)
- `GET /api/live-weather?latitude=22.5&longitude=78.9`
- `GET /api/earthquakes/nearby?latitude=35.7&longitude=139.7&radius_km=200&days=30&minimum_magnitude=2.5`
- `GET /api/weather/india`
- `GET /api/weather/nasa-power/daily?latitude=28.6&longitude=77.2&start_date=2026-09-20&end_date=2026-09-26`
- `GET /api/earthquakes/india?minimum_magnitude=2.5`
- `GET /api/events?location=Patna&from_date=2026-01-01&to_date=2026-12-31`
- `GET /api/analytics`
- `GET /api/alerts?status=active`

Use `/docs` to inspect request schemas. Do not submit credentials or real
personal data during the public presentation.

## Pre-demo test commands

From the project root:

```powershell
python backend/test_main.py
python datasets/test_pipeline.py
python datasets/clean_data.py
python datasets/train_models.py
```

The training command writes random-split, per-class, confusion-matrix, and
India/Nepal region-holdout metrics under `datasets/models/`. The current corpus
does not provide usable tweet dates, so temporal evaluation is unavailable.
Region-held-out metrics show source shift; do not describe the model as
production-validated or as an event-verification system.

## Suggested presentation outline

1. **Problem:** timely weather-event reporting and visibility challenges.
2. **System:** browser dashboard, FastAPI service, PostgreSQL, and separate data
   sources.
3. **Data:** Mendeley social-text classification corpus and the separate
   historical IIT Delhi flood inventory; cite sources and licenses.
4. **Workflow:** report submission, persistence, map/report display, filters,
   duplicate flagging, and analytics.
5. **AI approach:** TF-IDF + Logistic Regression; classification is a text
   signal only, never proof that a report happened.
6. **Evaluation:** random holdout compared with India/Nepal regional holdouts;
   show per-class metrics and explain domain shift and missing temporal test.
7. **Live conditions and limitations:** Open-Meteo observations, NASA POWER
   daily context, USGS FDSN results, network dependency, city-point coverage,
   heuristic-only weather signals, sample-data labeling, and the lack of an
   automatic report-verification flow.
8. **Next steps:** acquire time-stamped local reports, improve validation,
   calibration, monitoring, and production data governance.
