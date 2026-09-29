# National Weather Intelligence Platform

A weather-event dashboard with a FastAPI backend, PostgreSQL persistence, and
trained social-text classification models. Initial sample reports are labelled
and are not live observations.

## Project structure

```text
SIHproject/
  backend/                 FastAPI application, API tests, and SQLite importer
  datasets/
    models/                Trained classifier artifacts and evaluation reports
    raw/                   Source data and source/license documentation
    processed/             Regenerable outputs from clean_data.py (git-ignored)
    clean_data.py          Dataset validation and preprocessing
    train_models.py        Model training and evaluation
    test_pipeline.py       Dataset-pipeline tests
  index.html               Dashboard
  frontend-config.js       Local default API URL (empty for same-origin hosting)
  script.js                Dashboard behavior and API calls
  style.css                Dashboard styles
  build_frontend.py        Builds an isolated Render static-site publish directory
  render.yaml              Render API and frontend service definitions
  requirements.txt         Python dependencies
```

## PostgreSQL setup

Install PostgreSQL locally or provision a PostgreSQL database with your hosting
provider. Create an empty database and a database user with permission to create
tables, then copy `.env.example` to `.env` and set `DATABASE_URL` to the
connection string for that database. Keep `.env` private; it is excluded from
Git. The backend loads `.env` for local development and gives an environment
variable supplied by the deployment platform precedence.

```text
DATABASE_URL=postgresql://username:password@host:port/database
```

Never commit real connection strings or credentials. `DATABASE_URL` is the only
required backend environment variable. PostgreSQL tables and indexes are
created automatically on FastAPI startup.

To preserve the existing local SQLite records, leave `backend/weather.db` in
place and run the one-time, repeatable importer after configuring the target
PostgreSQL `DATABASE_URL`:

```powershell
python -m backend.migrate_sqlite_to_postgres
```

The importer copies reports, alerts, weather observations/cache, NASA POWER
observations, and earthquakes using primary-key upserts. It does not modify or
delete the SQLite source. You may use `SQLITE_SOURCE_PATH` to import a different
SQLite file. PostgreSQL and the existing model artifacts remain separate; no
database file is required in production.

## Install and run locally

From this project directory in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
# Edit .env and replace the DATABASE_URL placeholder with your local PostgreSQL URL.
python -m uvicorn backend.main:app --reload
```

Open <http://127.0.0.1:8000>. The API documentation is at
<http://127.0.0.1:8000/docs>.

### Open with VS Code Live Server (port 5500)

Live Server only hosts the static HTML/CSS/JavaScript; FastAPI must also be
running for reports, weather, earthquakes, and analytics. Start FastAPI in a
separate VS Code terminal from this project directory:

```powershell
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Then right-click this project's `index.html` (inside the `SIHproject` folder)
and choose **Open with Live Server**. If VS Code has the parent `SIH Project`
folder open, open `http://127.0.0.1:5500/SIHproject/`; if VS Code has the
`SIHproject` folder itself open, open `http://127.0.0.1:5500/`. A directory
listing at the bare port means Live Server is serving the parent folder, so
open the project subfolder URL above. The dashboard detects port 5500 and sends
API requests to FastAPI at port 8000. The backend allows browser API access
from `localhost:5500`, `127.0.0.1:5500`, and any exact origins listed in
`FRONTEND_ORIGINS`. Alternatively, skip Live Server and open the complete
FastAPI-hosted dashboard at `http://127.0.0.1:8000`.

## API overview

- `GET /api/health`
- `GET /api/summary`
- `GET /api/events?event=Rain&status=Review&state=Jharkhand`
- `GET /api/events/{id}`
- `POST /api/events`
- `POST /api/classify`
- `GET /api/analytics`
- `GET /api/alerts?status=active`
- `GET /api/live-weather?latitude=22.5&longitude=78.9` (Open-Meteo current conditions and five-day forecast, with MET Norway fallback when Open-Meteo is unavailable)
- `GET /api/live-weather/batch?latitude=23.3&longitude=85.3&latitude=25.6&longitude=85.1` (one Open-Meteo current-conditions request for up to 100 paired points)
- `GET /api/weather/india` (Open-Meteo city observations, persisted to PostgreSQL)
- `GET /api/weather/nasa-power/daily?latitude=28.6&longitude=77.2&start_date=2026-09-20&end_date=2026-09-26` (NASA POWER daily context, max 31 days)
- `GET /api/earthquakes/india?minimum_magnitude=2.5` (USGS FDSN GeoJSON query, persisted to PostgreSQL)
- `GET /api/earthquakes/nearby?latitude=35.7&longitude=139.7&radius_km=200&days=30&minimum_magnitude=2.5` (USGS nearby events)

Recent Weather Events filters select citizen reports by event, report status,
state, location, and report date. Each matching report with coordinates also
loads current Open-Meteo conditions and USGS events within 200 km from the last
30 days. Open-Meteo conditions for all matching points are fetched in one
multi-location provider request; USGS nearby queries are limited to four
concurrent requests. Open-Meteo responses are cached in PostgreSQL per rounded
coordinate for 15 minutes and shared by the map, city feed, and location
lookups. During an outage or rate limit, the last saved reading is shown with a
stale label. If the requested point has no exact saved reading, an older India
city-grid reading within 25 km may be shown and its distance is disclosed;
without a nearby cached reading, the API falls back to MET Norway's location
forecast service for a live reading; if both providers fail, the API returns an
explicit provider error. The manual **Get Live Weather** form sends an immediate
force-refresh request and does not display the automatic cooldown timer first.
It identifies which provider returned the reading. MET Norway does not provide
all Open-Meteo fields: feels-like temperature, visibility, and precipitation
probability may be unavailable, and its forecast fields are adapted from its
time-series forecast. Automatic dashboard polling is every 15 minutes. These current
conditions do not represent the report-date weather and do not verify a report.
NASA POWER remains a separate manually requested historical daily-context feed.

The map has India and World views, with tappable markers at 15 major Indian
cities and 24 major cities worldwide. A marker requests Open-Meteo current
conditions, visibility/fog signal, and a five-day forecast, plus USGS events
within 200 km from the previous 30 days at magnitude 2.5 or higher. The popup
shows each provider's attribution and reports provider errors rather than
substituting sample observations. The nearby earthquake query is a limited
source feed, not proof that an area has had no earthquakes.

New reports are stored as `Review`; this project has no report-review or
status-update interface. A report of the same event type within 5 km and 24
hours is retained but flagged as a possible duplicate. Seeded sample records
may already have verified statuses and corresponding alerts. New citizen
reports do not create alerts automatically; active alerts currently come from
the seeded sample records.

Public report submissions are attributed as citizen reports; clients cannot
claim a trusted external source or set their own review status. Live conditions
are fetched from Open-Meteo. The dashboard refreshes eight configured city
points in one multi-location request and the USGS India-region query every
fifteen minutes. The backend upserts those provider observations into separate PostgreSQL
tables using their observation time or stable USGS event ID. Responses retain
the source, event time, and retrieval time. The weather city points are
examples, not complete India coverage; provider/network failures are shown as
unavailable rather than replaced with generated data.

NASA POWER daily weather context is requested manually for one of the
configured cities and a date range of up to 31 days. It supplies daily gridded
temperature, corrected precipitation, humidity, and wind estimates—not a
real-time station observation. NASA POWER's fill value is converted to `null`;
the source URL, units, and retrieval time are retained. NASA daily data can
include near-real-time gaps and may be revised by later climate-quality
products, so it is not used as a live alert or report-verification signal.

Open-Meteo conditions and heuristic signals (for example fog code, visibility,
temperature, and wind thresholds) are not official warnings and do not verify a
citizen report. The USGS endpoint is its FDSN Event Web Service, queried for an
India bounding box, the past 24 hours, and the selected minimum magnitude;
results remain USGS source-reported information, not an independent cross-check
by this app. IMD is intentionally not integrated; historical source research is
documented under `datasets/`, but no IMD API is called by the backend or
dashboard.

This build does not yet ingest a live flood inventory, national rainfall
dataset, heatwave alert, or dust-storm warning feed. The historical flood
inventory remains a separate contextual dataset, and citizens can submit
reports for the dashboard's supported event categories.

The seeded demo records have illustrative confidence values. A trained social
text classifier is separate from verification: it classifies submitted text,
but cannot establish that a report is true, current, or supported by official
observations. Newly submitted reports remain in `Review` status.

## Public datasets and text model

See [datasets/README.md](./datasets/README.md) for the source register, actual
licenses, raw/processed separation, common schema, and model limitations. The
Mendeley tweet archive and Zenodo India Flood Inventory files are in
`datasets/raw/`. After installing requirements, run:

```powershell
python datasets/clean_data.py
python datasets/train_models.py
```

This trains social-text classification models only. Model output is an
`AI Classified` signal and does not verify a report; new citizen submissions
remain `Review`. The Zenodo record currently specifies
CC BY-NC 4.0, so its files must not be used commercially without additional
permission.

The training command also reports India/Nepal leave-one-region-out metrics
and explicitly records that temporal evaluation is unavailable because the
tweet corpus does not include usable dates. Regional holdout results show
material source shift; see [datasets/README.md](./datasets/README.md) before
interpreting the model output.

## SIH demo preparation

See [SIH_DEMO.md](./SIH_DEMO.md) for the click-through demonstration, checks,
known limitations, and a suggested presentation outline. Do not present
sample records as live reports or classifier scores as verification.

## Deployment

The target architecture separates the static frontend, FastAPI API, and
managed database:

```text
Browser → Render Static Site → Render FastAPI Web Service → Neon PostgreSQL
```

[render.yaml](./render.yaml) defines the Render static site and API web service.
The static-site build publishes only the dashboard assets (not the backend,
datasets, local database, or environment files) and generates its API base URL
from the API service host. The API permits local Live Server origins plus the
exact production origins supplied in `FRONTEND_ORIGINS`.

### First deployment

1. Create a Render Blueprint from this repository using
   [render.yaml](./render.yaml). It creates `sihproject-api` and
   `sihproject-frontend`.
2. In the [Neon Console](https://console.neon.tech/), create a PostgreSQL
   project and copy its pooled connection string including `sslmode=require`.
   Set that value as the API service's secret `DATABASE_URL`; never commit it
   or put it in a public file.
3. Set the API service's `FRONTEND_ORIGINS` to the exact static-site origin
   shown in Render (for example, `https://sihproject-frontend.onrender.com`).
   For multiple domains, separate origins with commas. Do not include paths or
   use a wildcard. Redeploy the API service after changing this setting.
4. Verify the frontend loads, its API requests succeed, and the API's
   `/api/health`, `/api/summary`, and `/docs` endpoints respond.

The API creates its tables at startup. Keep `.env` local and private; the
deployed API reads `DATABASE_URL` from Render's environment. Render's free web
service may sleep while idle; the first request after inactivity can take
longer. Neon hosts the database separately and persists it across web-service
restarts.

The existing single-service deployment at
<https://sihproject-fbr0.onrender.com/> remains unchanged until the new
Blueprint services are created and verified. The trained classifier artifacts
are not included in the repository by default. Other dashboard features can
deploy without them, but `/api/classify` requires generated model files under
`datasets/models/`; make those artifacts available to the API build if needed.

### Redeploying later

Push code changes to the repository's deployment branch. Render rebuilds the
static site and API according to their configured deploy settings. Keep the
Neon connection string in the API service's environment settings; it should
not change for ordinary code deployments.

## Tests

```powershell
python -m unittest discover -s backend -p "test_*.py"
```

The API tests use an isolated SQLite test database and do not require
`backend/weather.db` or a running PostgreSQL server. Production startup and
deployment require a reachable PostgreSQL `DATABASE_URL`.
