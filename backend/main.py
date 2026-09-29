from __future__ import annotations

import asyncio
import json
import math
import os
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from time import monotonic
from typing import Literal
from urllib.parse import unquote, urlsplit

import httpx
import psycopg
from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, field_validator
from psycopg import Cursor
from psycopg.rows import Row, tuple_row

if __package__:
    from .classifier import classify_text
else:
    from classifier import classify_text


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env", override=False)
DATABASE_URL = os.getenv("DATABASE_URL", "")
FRONTEND_ORIGINS = [
    origin.strip().rstrip("/")
    for origin in os.getenv("FRONTEND_ORIGINS", "").split(",")
    if origin.strip()
]
EVENT_TYPES = {
    "Rain": ("rain", "fa-cloud-rain"),
    "Flood": ("flood", "fa-water"),
    "Heatwave": ("heat", "fa-sun"),
    "Thunderstorm": ("thunder", "fa-bolt"),
    "Fog": ("fog", "fa-smog"),
    "Dust Storm": ("dust", "fa-wind"),
}
SEVERITIES = ("low", "medium", "high", "critical")
OPEN_METEO_CACHE_SECONDS = 15 * 60
OPEN_METEO_DEFAULT_RETRY_SECONDS = 60
OPEN_METEO_RETRY_UNTIL = 0.0
OPEN_METEO_REQUEST_LOCK = asyncio.Lock()
WEATHER_CODES = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    4: "Smoke",
    5: "Haze",
    6: "Dust in suspension",
    7: "Dust or sand raised by wind",
    8: "Dust whirl",
    9: "Duststorm",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with hail",
    99: "Heavy thunderstorm with hail",
}
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
MET_NORWAY_URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
NASA_POWER_DAILY_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
NASA_POWER_PARAMETERS = {
    "T2M": ("temperature_mean_c", "C"),
    "T2M_MAX": ("temperature_max_c", "C"),
    "T2M_MIN": ("temperature_min_c", "C"),
    "PRECTOTCORR": ("precipitation_mm_day", "mm/day"),
    "RH2M": ("humidity_percent", "%"),
    "WS10M": ("wind_speed_m_s", "m/s"),
}
USGS_EARTHQUAKE_QUERY_URL = (
    "https://earthquake.usgs.gov/fdsnws/event/1/query"
)
INDIA_CITIES = (
    {"name": "Delhi", "state": "Delhi", "latitude": 28.6139, "longitude": 77.2090},
    {"name": "Mumbai", "state": "Maharashtra", "latitude": 19.0760, "longitude": 72.8777},
    {"name": "Kolkata", "state": "West Bengal", "latitude": 22.5726, "longitude": 88.3639},
    {"name": "Chennai", "state": "Tamil Nadu", "latitude": 13.0827, "longitude": 80.2707},
    {"name": "Bengaluru", "state": "Karnataka", "latitude": 12.9716, "longitude": 77.5946},
    {"name": "Guwahati", "state": "Assam", "latitude": 26.1445, "longitude": 91.7362},
    {"name": "Jaipur", "state": "Rajasthan", "latitude": 26.9124, "longitude": 75.7873},
    {"name": "Patna", "state": "Bihar", "latitude": 25.5941, "longitude": 85.1376},
)


class HybridRow(dict):
    def __getitem__(self, key):
        if isinstance(key, int):
            key = tuple(self.keys())[key]
        return super().__getitem__(key)


def _hybrid_row_factory(cursor: Cursor[Row]) -> object:
    if cursor.description is None:
        return tuple_row(cursor)
    columns = tuple(column.name for column in cursor.description)
    return lambda row: HybridRow(zip(columns, row))


class DatabaseConnection:
    def __init__(self, connection, dialect: str):
        self.connection = connection
        self.dialect = dialect

    def execute(self, query: str, parameters=()):
        if self.dialect == "postgresql":
            query = query.replace("?", "%s")
        return self.connection.execute(query, parameters)

    def executescript(self, query: str) -> None:
        if self.dialect == "sqlite":
            self.connection.executescript(query)
            return
        for statement in query.split(";"):
            if statement.strip():
                self.connection.execute(statement)

    def commit(self) -> None:
        self.connection.commit()

    def rollback(self) -> None:
        self.connection.rollback()

    def close(self) -> None:
        self.connection.close()


def _sqlite_path(database_url: str) -> Path:
    parsed = urlsplit(database_url)
    if parsed.scheme != "sqlite" or not database_url.startswith("sqlite:///"):
        raise ValueError("SQLite is supported only through a sqlite:/// test DATABASE_URL.")
    return Path(unquote(database_url[len("sqlite:///") :]))


def get_connection() -> DatabaseConnection:
    if DATABASE_URL.startswith("sqlite:///"):
        if os.getenv("APP_ENV") != "test":
            raise RuntimeError("SQLite DATABASE_URL is permitted only when APP_ENV=test.")
        path = _sqlite_path(DATABASE_URL)
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return DatabaseConnection(connection, "sqlite")
    if not DATABASE_URL.startswith(("postgresql://", "postgres://")):
        raise RuntimeError(
            "Set DATABASE_URL to a PostgreSQL connection string before starting the API."
        )
    connection = psycopg.connect(
        DATABASE_URL,
        connect_timeout=10,
        row_factory=_hybrid_row_factory,
    )
    return DatabaseConnection(connection, "postgresql")


@contextmanager
def database_session():
    connection = get_connection()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database(*, seed_demo_data: bool = True) -> None:
    with database_session() as connection:
        schema = """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                location TEXT NOT NULL,
                state TEXT NOT NULL,
                event_type TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('Verified', 'Review', 'Suspicious')),
                source TEXT NOT NULL,
                confidence INTEGER NOT NULL CHECK (confidence BETWEEN 0 AND 100),
                severity TEXT NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'critical')),
                latitude REAL NOT NULL CHECK (latitude BETWEEN -90 AND 90),
                longitude REAL NOT NULL CHECK (longitude BETWEEN -180 AND 180),
                duplicate_of_id INTEGER REFERENCES events(id),
                is_demo INTEGER NOT NULL DEFAULT 0 CHECK (is_demo IN (0, 1)),
                report_text TEXT NOT NULL DEFAULT '',
                ai_disaster_label TEXT,
                ai_disaster_confidence REAL,
                ai_social_event_type TEXT,
                ai_event_type_confidence REAL,
                ai_model_version TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_events_occurred_at ON events(occurred_at);
            CREATE INDEX IF NOT EXISTS idx_events_type_status ON events(event_type, status);
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL UNIQUE REFERENCES events(id),
                severity TEXT NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'critical')),
                message TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'resolved')),
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS weather_observations (
                city_key TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                city TEXT NOT NULL,
                state TEXT NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                condition TEXT NOT NULL,
                weather_code INTEGER NOT NULL,
                temperature_c REAL,
                apparent_temperature_c REAL,
                humidity_percent REAL,
                precipitation_mm REAL,
                visibility_m REAL,
                wind_speed_kmh REAL,
                source TEXT NOT NULL,
                retrieved_at TEXT NOT NULL,
                PRIMARY KEY (city_key, observed_at)
            );
            CREATE INDEX IF NOT EXISTS idx_weather_observations_time
                ON weather_observations(observed_at);
            CREATE TABLE IF NOT EXISTS live_weather_cache (
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                include_forecast INTEGER NOT NULL,
                weather_json TEXT NOT NULL,
                retrieved_at TEXT NOT NULL,
                PRIMARY KEY (latitude, longitude, include_forecast)
            );
            CREATE TABLE IF NOT EXISTS nasa_power_observations (
                location_key TEXT NOT NULL,
                observation_date TEXT NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                temperature_mean_c REAL,
                temperature_max_c REAL,
                temperature_min_c REAL,
                precipitation_mm_day REAL,
                humidity_percent REAL,
                wind_speed_m_s REAL,
                source TEXT NOT NULL,
                source_url TEXT NOT NULL,
                retrieved_at TEXT NOT NULL,
                PRIMARY KEY (location_key, observation_date)
            );
            CREATE INDEX IF NOT EXISTS idx_nasa_power_observation_date
                ON nasa_power_observations(observation_date);
            CREATE TABLE IF NOT EXISTS earthquakes (
                source_id TEXT PRIMARY KEY,
                place TEXT NOT NULL,
                magnitude REAL,
                occurred_at TEXT NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                depth_km REAL,
                source_url TEXT NOT NULL,
                source TEXT NOT NULL,
                retrieved_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_earthquakes_occurred_at
                ON earthquakes(occurred_at);
            """
        if connection.dialect == "postgresql":
            schema = (
                schema.replace(
                    "id INTEGER PRIMARY KEY AUTOINCREMENT",
                    "id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY",
                )
                .replace(
                    "duplicate_of_id INTEGER REFERENCES",
                    "duplicate_of_id BIGINT REFERENCES",
                )
                .replace("event_id INTEGER NOT NULL UNIQUE REFERENCES",
                         "event_id BIGINT NOT NULL UNIQUE REFERENCES")
            )
        connection.executescript(schema)
        if connection.dialect == "sqlite":
            existing_columns = {
                column["name"]
                for column in connection.execute("PRAGMA table_info(events)").fetchall()
            }
        else:
            existing_columns = {
                column["column_name"]
                for column in connection.execute(
                    """
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema = current_schema() AND table_name = 'events'
                    """
                ).fetchall()
            }
        migrations = {
            "report_text": "TEXT NOT NULL DEFAULT ''",
            "ai_disaster_label": "TEXT",
            "ai_disaster_confidence": "REAL",
            "ai_social_event_type": "TEXT",
            "ai_event_type_confidence": "REAL",
            "ai_model_version": "TEXT",
        }
        for column_name, declaration in migrations.items():
            if column_name not in existing_columns:
                connection.execute(
                    f"ALTER TABLE events ADD COLUMN {column_name} {declaration}"
                )
        existing = connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        if seed_demo_data and existing == 0:
            _seed_demo_data(connection)


def _seed_demo_data(connection: DatabaseConnection) -> None:
    now = datetime.now(timezone.utc)
    demo_events = [
        ("Ranchi, Jharkhand", "Jharkhand", "Rain", "Verified", "Citizen Report", 94, "high", 23.3441, 85.3096, 0),
        ("Patna, Bihar", "Bihar", "Flood", "Verified", "Official API", 98, "critical", 25.5941, 85.1376, 1),
        ("Delhi, Delhi", "Delhi", "Heatwave", "Review", "Website", 76, "medium", 28.6139, 77.2090, 2),
        ("Jaipur, Rajasthan", "Rajasthan", "Dust Storm", "Verified", "Social Media", 88, "medium", 26.9124, 75.7873, 3),
        ("Mumbai, Maharashtra", "Maharashtra", "Thunderstorm", "Verified", "Official API", 91, "high", 19.0760, 72.8777, 4),
    ]
    for location, state_name, event_type, review_status, source, confidence, severity, lat, lon, hours_ago in demo_events:
        occurred_at = (now - timedelta(hours=hours_ago)).isoformat()
        cursor = connection.execute(
            """
            INSERT INTO events (
                location, state, event_type, occurred_at, status, source,
                confidence, severity, latitude, longitude, is_demo, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?) RETURNING id
            """,
            (
                location,
                state_name,
                event_type,
                occurred_at,
                review_status,
                source,
                confidence,
                severity,
                lat,
                lon,
                now.isoformat(),
            ),
        )
        event_id = cursor.fetchone()["id"]
        if review_status == "Verified" and severity in ("high", "critical"):
            connection.execute(
                """
                INSERT INTO alerts (event_id, severity, message, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    event_id,
                    severity,
                    f"{event_type} reported in {location}",
                    now.isoformat(),
                ),
            )


def event_to_dict(row: HybridRow | sqlite3.Row) -> dict:
    data = dict(row)
    data["is_demo"] = bool(data["is_demo"])
    data["ai_classification"] = None
    if data["ai_disaster_label"] is not None:
        data["ai_classification"] = {
            "disaster_label": data["ai_disaster_label"],
            "disaster_score": data["ai_disaster_confidence"],
            "social_event_type": data["ai_social_event_type"],
            "event_type_score": data["ai_event_type_confidence"],
            "model_version": data["ai_model_version"],
            "verification_status": "Unverified",
        }
    if data["status"] == "Review" and not data["is_demo"]:
        data["confidence"] = None
    data["time"] = data.pop("occurred_at")
    data["type"], data["icon"] = EVENT_TYPES[data.pop("event_type")]
    data["event"] = next(
        name for name, (event_class, _) in EVENT_TYPES.items() if event_class == data["type"]
    )
    data["duplicate_detected"] = data["duplicate_of_id"] is not None
    data["verification_status"] = "Unverified" if not data["is_demo"] else "Sample"
    return data


class EventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location: str = Field(min_length=2, max_length=120)
    state: str = Field(min_length=2, max_length=80)
    event: Literal["Rain", "Flood", "Heatwave", "Thunderstorm", "Fog", "Dust Storm"]
    description: str = Field(default="", max_length=2000)
    time: datetime
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)

    @field_validator("time")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("time must include a timezone offset.")
        return value


class ClassifyRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_km = 6371.0
    lat1_rad, lat2_rad = math.radians(lat1), math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
    )
    return earth_radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    yield


app = FastAPI(
    title="National Weather Intelligence Platform API",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        *FRONTEND_ORIGINS,
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(PROJECT_ROOT / "index.html")


@app.get("/style.css", include_in_schema=False)
def stylesheet() -> FileResponse:
    return FileResponse(PROJECT_ROOT / "style.css", media_type="text/css")


@app.get("/script.js", include_in_schema=False)
def dashboard_script() -> FileResponse:
    return FileResponse(PROJECT_ROOT / "script.js", media_type="application/javascript")


@app.get("/frontend-config.js", include_in_schema=False)
def frontend_config() -> FileResponse:
    return FileResponse(PROJECT_ROOT / "frontend-config.js", media_type="application/javascript")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/classify")
def classify_report_text(request: ClassifyRequest) -> dict:
    try:
        return classify_text(request.text)
    except RuntimeError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error


@app.get("/api/events")
@app.get("/api/reports", include_in_schema=False)
def list_events(
    event_type: str | None = Query(default=None, alias="event"),
    report_status: Literal["Verified", "Review", "Suspicious"] | None = Query(default=None, alias="status"),
    state_name: str | None = Query(default=None, alias="state"),
    location_name: str | None = Query(default=None, alias="location"),
    start_date: date | None = Query(default=None, alias="from_date"),
    end_date: date | None = Query(default=None, alias="to_date"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    filters: list[str] = []
    values: list[object] = []
    if event_type:
        if event_type not in EVENT_TYPES:
            raise HTTPException(status_code=400, detail="Unsupported event type.")
        filters.append("event_type = ?")
        values.append(event_type)
    if report_status:
        filters.append("status = ?")
        values.append(report_status)
    if state_name:
        like_operator = "LIKE" if DATABASE_URL.startswith("sqlite:///") else "ILIKE"
        filters.append(f"state {like_operator} ?")
        values.append(f"%{state_name.strip()}%")
    if location_name:
        like_operator = "LIKE" if DATABASE_URL.startswith("sqlite:///") else "ILIKE"
        filters.append(f"location {like_operator} ?")
        values.append(f"%{location_name.strip()}%")
    if start_date:
        filters.append("occurred_at >= ?")
        values.append(datetime.combine(start_date, datetime.min.time(), timezone.utc).isoformat())
    if end_date:
        filters.append("occurred_at < ?")
        values.append(
            datetime.combine(
                end_date + timedelta(days=1), datetime.min.time(), timezone.utc
            ).isoformat()
        )
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=422, detail="from_date must be on or before to_date.")
    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    with database_session() as connection:
        total = connection.execute(
            f"SELECT COUNT(*) FROM events {where}", values
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT * FROM events {where}
            ORDER BY occurred_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            [*values, limit, offset],
        ).fetchall()
    return {"items": [event_to_dict(row) for row in rows], "total": total, "limit": limit, "offset": offset}


@app.post("/api/events", status_code=status.HTTP_201_CREATED)
def create_event(report: EventCreate) -> dict:
    event_type = report.event
    occurred_at = report.time.astimezone(timezone.utc)
    now = datetime.now(timezone.utc).isoformat()
    duplicate_id = None
    classification = None
    classification_error = None
    report_text = " ".join(report.description.split())
    if report_text:
        try:
            classification = classify_text(report_text)
        except RuntimeError as error:
            classification_error = str(error)

    with database_session() as connection:
        rows = connection.execute(
            """
            SELECT id, latitude, longitude FROM events
            WHERE event_type = ? AND duplicate_of_id IS NULL
              AND occurred_at BETWEEN ? AND ?
            """,
            (
                event_type,
                (occurred_at - timedelta(hours=24)).isoformat(),
                (occurred_at + timedelta(hours=24)).isoformat(),
            ),
        ).fetchall()
        for row in rows:
            if _distance_km(
                report.latitude, report.longitude, row["latitude"], row["longitude"]
            ) <= 5:
                duplicate_id = row["id"]
                break

        review_status = "Review"
        confidence = 25 if duplicate_id is not None else 50
        cursor = connection.execute(
            """
            INSERT INTO events (
                location, state, event_type, occurred_at, status, source,
                confidence, severity, latitude, longitude, duplicate_of_id,
                report_text, ai_disaster_label, ai_disaster_confidence,
                ai_social_event_type, ai_event_type_confidence, ai_model_version,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (
                report.location.strip(),
                report.state.strip(),
                event_type,
                occurred_at.isoformat(),
                review_status,
                "Citizen Report",
                confidence,
                report.severity,
                report.latitude,
                report.longitude,
                duplicate_id,
                report_text,
                classification["disaster_label"] if classification else None,
                classification["disaster_score"] if classification else None,
                classification["social_event_type"] if classification else None,
                classification["event_type_score"] if classification else None,
                classification["model_version"] if classification else None,
                now,
            ),
        )
        event_id = cursor.fetchone()["id"]
        row = connection.execute(
            "SELECT * FROM events WHERE id = ?", (event_id,)
        ).fetchone()
    result = event_to_dict(row)
    result["ai_classification_status"] = (
        "classified"
        if classification
        else "model_unavailable"
        if report_text and classification_error
        else "not_requested"
    )
    if classification_error:
        result["ai_classification_error"] = classification_error
    result["possible_duplicate"] = duplicate_id is not None
    return result


@app.get("/api/events/{event_id}")
def get_event(event_id: int) -> dict:
    with database_session() as connection:
        row = connection.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Report not found.")
    return event_to_dict(row)


@app.get("/api/summary")
def summary() -> dict[str, int | bool]:
    with database_session() as connection:
        counts = connection.execute(
            """
            SELECT
                COUNT(*) AS total_reports,
                SUM(CASE WHEN status = 'Verified' THEN 1 ELSE 0 END) AS verified_reports,
                SUM(CASE WHEN status = 'Suspicious' THEN 1 ELSE 0 END) AS suspicious_reports,
                SUM(CASE WHEN is_demo = 1 THEN 1 ELSE 0 END) AS sample_reports
            FROM events
            """
        ).fetchone()
        active_alerts = connection.execute(
            "SELECT COUNT(*) FROM alerts WHERE status = 'active'"
        ).fetchone()[0]
    return {
        "total_reports": counts["total_reports"],
        "verified_reports": counts["verified_reports"],
        "suspicious_reports": counts["suspicious_reports"],
        "active_alerts": active_alerts,
        "includes_demo_data": counts["sample_reports"] > 0,
    }


@app.get("/api/analytics")
def analytics() -> dict:
    with database_session() as connection:
        rows = connection.execute(
            "SELECT event_type, COUNT(*) AS count FROM events GROUP BY event_type ORDER BY count DESC"
        ).fetchall()
        total = connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        sample_count = connection.execute(
            "SELECT COUNT(*) FROM events WHERE is_demo = 1"
        ).fetchone()[0]
    distribution = [
        {
            "event": row["event_type"],
            "count": row["count"],
            "percentage": round(row["count"] * 100 / total, 1) if total else 0,
        }
        for row in rows
    ]
    return {
        "total_reports": total,
        "distribution": distribution,
        "includes_demo_data": sample_count > 0,
    }


@app.get("/api/live-weather")
async def live_weather(
    latitude: float = Query(22.5, ge=-90, le=90),
    longitude: float = Query(78.9, ge=-180, le=180),
    force_refresh: bool = Query(False),
) -> dict:
    results, errors = await _get_live_weather_points(
        [(latitude, longitude)],
        include_forecast=True,
        force_refresh=force_refresh,
    )
    key = _weather_cache_key(latitude, longitude)
    if key not in results:
        primary_error = errors.get(key)
        try:
            fallback_weather = await _fetch_met_norway_weather(latitude, longitude)
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as fallback_error:
            detail = primary_error["detail"] if primary_error else "Open-Meteo returned no data."
            if (
                primary_error
                and primary_error["status_code"] == status.HTTP_429_TOO_MANY_REQUESTS
            ):
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"{detail} MET Norway fallback failed: {fallback_error}",
                    headers={
                        "Retry-After": str(primary_error["retry_after_seconds"])
                    },
                ) from fallback_error
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=(
                    f"{detail} MET Norway fallback also failed: {fallback_error}"
                ),
            ) from fallback_error
        _store_live_weather_cache(
            latitude,
            longitude,
            True,
            fallback_weather,
            fallback_weather["retrieved_at"],
        )
        return fallback_weather
    weather = results[key]
    return {**weather, "source": weather.get("source", "Open-Meteo")}


async def _fetch_met_norway_weather(latitude: float, longitude: float) -> dict:
    async with httpx.AsyncClient(
        timeout=12,
        headers={"User-Agent": "NationalWeatherDashboard/1.0"},
    ) as client:
        response = await client.get(
            MET_NORWAY_URL,
            params={"lat": latitude, "lon": longitude},
        )
        response.raise_for_status()
        payload = response.json()
    weather = _normalize_met_norway(payload, latitude, longitude)
    weather["source"] = "MET Norway"
    weather["source_url"] = str(response.request.url)
    weather["retrieved_at"] = datetime.now(timezone.utc).isoformat()
    weather["cache_status"] = "live"
    weather["provider_note"] = (
        "Fallback weather provider used because Open-Meteo was unavailable."
    )
    return weather


def _met_norway_weather_code(symbol: object) -> int:
    if not isinstance(symbol, str):
        return 3
    name = symbol.split("_", 1)[0]
    if name.startswith(("clearsky",)):
        return 0
    if name.startswith(("fair",)):
        return 1
    if name.startswith(("partlycloudy",)):
        return 2
    if name.startswith(("fog",)):
        return 45
    if "thunder" in name:
        return 95 if "heavy" not in name else 99
    if "snow" in name:
        return 75 if "heavy" in name else 71
    if "sleet" in name:
        return 67 if "heavy" in name else 66
    if "rain" in name:
        if "showers" in name:
            return 82 if "heavy" in name else 80
        return 65 if "heavy" in name else 61
    return 3


def _normalize_met_norway(
    payload: object, latitude: float, longitude: float
) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("MET Norway response must be a JSON object.")
    properties = payload.get("properties")
    timeseries = properties.get("timeseries") if isinstance(properties, dict) else None
    if not isinstance(timeseries, list) or not timeseries:
        raise ValueError("MET Norway response is missing forecast observations.")

    observations = []
    for item in timeseries:
        if not isinstance(item, dict) or not isinstance(item.get("time"), str):
            continue
        data = item.get("data")
        instant = data.get("instant") if isinstance(data, dict) else None
        details = instant.get("details") if isinstance(instant, dict) else None
        if isinstance(details, dict):
            observations.append((item, details))
    if not observations:
        raise ValueError("MET Norway response contains no valid weather observations.")

    current_item, current_details = observations[0]
    current_data = current_item["data"]
    next_hour = current_data.get("next_1_hours", {})
    next_hour_summary = (
        next_hour.get("summary", {}) if isinstance(next_hour, dict) else {}
    )
    symbol = next_hour_summary.get("symbol_code") if isinstance(next_hour_summary, dict) else None
    weather_code = _met_norway_weather_code(symbol)
    precipitation_details = next_hour.get("details", {}) if isinstance(next_hour, dict) else {}
    precipitation = (
        precipitation_details.get("precipitation_amount")
        if isinstance(precipitation_details, dict)
        else None
    )
    wind_speed = _number_or_none(current_details.get("wind_speed"))
    wind_speed_kmh = wind_speed * 3.6 if wind_speed is not None else None
    wind_gust = _number_or_none(current_details.get("wind_speed_of_gust"))
    observed_at = _parse_open_meteo_time(current_item["time"]).isoformat()

    forecast_by_date: dict[str, list[tuple[dict, dict]]] = {}
    for item, details in observations:
        day = _parse_open_meteo_time(item["time"]).date().isoformat()
        forecast_by_date.setdefault(day, []).append((item, details))
    forecast = []
    for forecast_date, day_observations in list(forecast_by_date.items())[:5]:
        temperatures = [
            value
            for _, details in day_observations
            if (value := _number_or_none(details.get("air_temperature"))) is not None
        ]
        representative = day_observations[min(len(day_observations) - 1, 12)][0]
        representative_data = representative.get("data", {})
        six_hour = representative_data.get("next_6_hours", {})
        six_hour_summary = six_hour.get("summary", {}) if isinstance(six_hour, dict) else {}
        representative_symbol = (
            six_hour_summary.get("symbol_code")
            if isinstance(six_hour_summary, dict)
            else None
        )
        forecast.append({
            "date": forecast_date,
            "condition": WEATHER_CODES.get(
                _met_norway_weather_code(representative_symbol), "Unknown conditions"
            ),
            "temperature_min_c": min(temperatures) if temperatures else None,
            "temperature_max_c": max(temperatures) if temperatures else None,
            "precipitation_probability_percent": None,
            "precipitation_sum_mm": None,
        })

    normalized = {
        "latitude": latitude,
        "longitude": longitude,
        "observed_at": observed_at,
        "condition": WEATHER_CODES.get(weather_code, "Unknown conditions"),
        "weather_code": weather_code,
        "temperature_c": _number_or_none(current_details.get("air_temperature")),
        "apparent_temperature_c": None,
        "humidity_percent": _number_or_none(current_details.get("relative_humidity")),
        "precipitation_mm": _number_or_none(precipitation),
        "visibility_m": None,
        "wind_speed_kmh": wind_speed_kmh,
        "wind_direction_degrees": _number_or_none(
            current_details.get("wind_from_direction")
        ),
        "wind_gusts_kmh": wind_gust * 3.6 if wind_gust is not None else None,
        "forecast": forecast,
    }
    normalized["weather_event"] = _weather_event(
        weather_code, normalized["precipitation_mm"]
    )
    normalized["signals"] = _weather_signals(
        weather_code,
        normalized["temperature_c"],
        normalized["visibility_m"],
        normalized["wind_speed_kmh"],
    )
    return normalized


@app.get("/api/live-weather/batch")
async def live_weather_batch(
    latitudes: list[float] = Query(..., alias="latitude"),
    longitudes: list[float] = Query(..., alias="longitude"),
) -> dict:
    if (
        not latitudes
        or len(latitudes) != len(longitudes)
        or len(latitudes) > 100
        or any(not math.isfinite(value) or not -90 <= value <= 90 for value in latitudes)
        or any(not math.isfinite(value) or not -180 <= value <= 180 for value in longitudes)
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Provide 1-100 paired latitude/longitude values within valid ranges.",
        )

    points = list(zip(latitudes, longitudes))
    results, errors = await _get_live_weather_points(
        points, include_forecast=False
    )
    observations = []
    for latitude, longitude in points:
        weather = results.get(_weather_cache_key(latitude, longitude))
        if weather is not None:
            observations.append(
                {
                    **weather,
                    "requested_latitude": latitude,
                    "requested_longitude": longitude,
                }
            )
    partial_errors = [
        {
            "latitude": latitude,
            "longitude": longitude,
            **errors[_weather_cache_key(latitude, longitude)],
        }
        for latitude, longitude in points
        if _weather_cache_key(latitude, longitude) in errors
    ]
    if not observations and partial_errors:
        first_error = partial_errors[0]
        if first_error["status_code"] == status.HTTP_429_TOO_MANY_REQUESTS:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=first_error["detail"],
                headers={"Retry-After": str(first_error["retry_after_seconds"])},
            )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "message": "Open-Meteo returned no valid location observations.",
                "errors": partial_errors,
            },
        )
    return {
        "source": "Open-Meteo",
        "items": observations,
        "total": len(observations),
        "partial_errors": partial_errors,
    }


def _open_meteo_params(
    latitude: float, longitude: float, *, include_forecast: bool = False
) -> dict[str, str | float]:
    params: dict[str, str | float] = {
        "latitude": latitude,
        "longitude": longitude,
        "current": (
            "temperature_2m,relative_humidity_2m,apparent_temperature,"
            "precipitation,weather_code,wind_speed_10m,wind_direction_10m,"
            "wind_gusts_10m"
        ),
        "hourly": "visibility",
        "forecast_days": 5 if include_forecast else 1,
        "timezone": "UTC",
    }
    if include_forecast:
        params["daily"] = (
            "weather_code,temperature_2m_max,temperature_2m_min,"
            "precipitation_probability_max,precipitation_sum"
        )
    return params


def _number_or_none(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _parse_open_meteo_time(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("Open-Meteo observation time is invalid.")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError("Open-Meteo observation time is invalid.") from error
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _weather_signals(
    weather_code: int, temperature_c: float | None, visibility_m: float | None, wind_speed_kmh: float | None
) -> list[str]:
    signals = []
    if weather_code in (45, 48) or (visibility_m is not None and visibility_m < 1000):
        signals.append("Fog / low visibility observed")
    if weather_code in (4, 5, 6, 7, 8, 9):
        signals.append("Dust / haze / smoke weather code reported")
    if weather_code in (95, 96, 99):
        signals.append("Thunderstorm weather code reported")
    if temperature_c is not None and temperature_c >= 40:
        signals.append("High temperature condition (40°C+); not an official heatwave warning")
    if wind_speed_kmh is not None and wind_speed_kmh >= 50:
        signals.append("High wind condition (50 km/h+); not an official warning")
    if weather_code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
        signals.append("Rain / precipitation weather code reported")
    return signals


def _normalize_open_meteo(
    payload: object, latitude: float, longitude: float
) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("Open-Meteo response must be a JSON object.")
    current = payload.get("current")
    if (
        not isinstance(current, dict)
        or not isinstance(current.get("weather_code"), int)
        or not isinstance(current.get("time"), str)
        or not current["time"]
    ):
        raise ValueError("Open-Meteo response is missing current weather conditions.")
    hourly = payload.get("hourly")
    hourly_times = hourly.get("time") if isinstance(hourly, dict) else None
    visibility_values = hourly.get("visibility") if isinstance(hourly, dict) else None
    observed_time = current["time"]
    parsed_observed_time = _parse_open_meteo_time(observed_time)
    visibility = None
    if isinstance(hourly_times, list) and isinstance(visibility_values, list):
        nearest_hours = []
        for index, hourly_time in enumerate(hourly_times):
            if index >= len(visibility_values) or not isinstance(hourly_time, str):
                continue
            try:
                hour_time = _parse_open_meteo_time(hourly_time)
            except ValueError:
                continue
            difference_seconds = abs((hour_time - parsed_observed_time).total_seconds())
            nearest_hours.append((difference_seconds, index))
        if nearest_hours:
            difference_seconds, nearest_index = min(nearest_hours)
            if difference_seconds <= 30 * 60:
                visibility = _number_or_none(visibility_values[nearest_index])

    code = current["weather_code"]
    provider_latitude = _number_or_none(payload.get("latitude"))
    provider_longitude = _number_or_none(payload.get("longitude"))
    normalized = {
        "latitude": provider_latitude if provider_latitude is not None else latitude,
        "longitude": provider_longitude if provider_longitude is not None else longitude,
        "observed_at": parsed_observed_time.isoformat(),
        "condition": WEATHER_CODES.get(code, "Unknown conditions"),
        "weather_code": code,
        "temperature_c": _number_or_none(current.get("temperature_2m")),
        "apparent_temperature_c": _number_or_none(current.get("apparent_temperature")),
        "humidity_percent": _number_or_none(current.get("relative_humidity_2m")),
        "precipitation_mm": _number_or_none(current.get("precipitation")),
        "visibility_m": visibility,
        "wind_speed_kmh": _number_or_none(current.get("wind_speed_10m")),
        "wind_direction_degrees": _number_or_none(current.get("wind_direction_10m")),
        "wind_gusts_kmh": _number_or_none(current.get("wind_gusts_10m")),
    }
    normalized["weather_event"] = _weather_event(code, normalized["precipitation_mm"])
    normalized["signals"] = _weather_signals(
        code,
        normalized["temperature_c"],
        visibility,
        normalized["wind_speed_kmh"],
    )
    daily = payload.get("daily")
    forecast = []
    if isinstance(daily, dict):
        daily_times = daily.get("time")
        if isinstance(daily_times, list):
            forecast_fields = {
                "condition": daily.get("weather_code"),
                "temperature_max_c": daily.get("temperature_2m_max"),
                "temperature_min_c": daily.get("temperature_2m_min"),
                "precipitation_probability_percent": daily.get(
                    "precipitation_probability_max"
                ),
                "precipitation_sum_mm": daily.get("precipitation_sum"),
            }
            for index, forecast_date in enumerate(daily_times):
                if not isinstance(forecast_date, str):
                    continue
                forecast_item = {"date": forecast_date}
                for field, values in forecast_fields.items():
                    value = values[index] if isinstance(values, list) and index < len(values) else None
                    forecast_item[field] = (
                        WEATHER_CODES.get(value, "Unknown conditions")
                        if field == "condition" and isinstance(value, int)
                        else None if field == "condition"
                        else _number_or_none(value)
                    )
                forecast.append(forecast_item)
    normalized["forecast"] = forecast
    return normalized


def _weather_cache_key(latitude: float, longitude: float) -> tuple[float, float]:
    return round(latitude, 5), round(longitude, 5)


def _read_live_weather_cache(
    latitude: float, longitude: float, include_forecast: bool
) -> tuple[dict, float] | None:
    cache_latitude, cache_longitude = _weather_cache_key(latitude, longitude)
    with database_session() as connection:
        row = connection.execute(
            """
            SELECT weather_json, retrieved_at FROM live_weather_cache
            WHERE latitude = ? AND longitude = ? AND include_forecast = ?
            """,
            (cache_latitude, cache_longitude, int(include_forecast)),
        ).fetchone()
        legacy_row = None
        cache_distance_km = 0.0
        if row is None:
            legacy_rows = connection.execute(
                """
                SELECT * FROM weather_observations
                WHERE retrieved_at = (
                    SELECT MAX(retrieved_at) FROM weather_observations AS latest
                    WHERE latest.latitude = weather_observations.latitude
                      AND latest.longitude = weather_observations.longitude
                )
                """
            ).fetchall()
            nearby_rows = [
                (
                    _distance_km(
                        latitude,
                        longitude,
                        weather_row["latitude"],
                        weather_row["longitude"],
                    ),
                    weather_row,
                )
                for weather_row in legacy_rows
            ]
            nearby_rows = [item for item in nearby_rows if item[0] <= 25]
            if nearby_rows:
                cache_distance_km, legacy_row = min(
                    nearby_rows,
                    key=lambda item: (item[0], item[1]["retrieved_at"]),
                )
    if row is None and legacy_row is None:
        return None
    if row is None:
        weather = {
            "latitude": legacy_row["latitude"],
            "longitude": legacy_row["longitude"],
            "observed_at": legacy_row["observed_at"],
            "retrieved_at": legacy_row["retrieved_at"],
            "condition": legacy_row["condition"],
            "weather_code": legacy_row["weather_code"],
            "temperature_c": legacy_row["temperature_c"],
            "apparent_temperature_c": legacy_row["apparent_temperature_c"],
            "humidity_percent": legacy_row["humidity_percent"],
            "precipitation_mm": legacy_row["precipitation_mm"],
            "visibility_m": legacy_row["visibility_m"],
            "wind_speed_kmh": legacy_row["wind_speed_kmh"],
            "wind_direction_degrees": None,
            "wind_gusts_kmh": None,
            "forecast": [],
            "cache_location_distance_km": round(cache_distance_km, 1),
        }
        weather["weather_event"] = _weather_event(
            weather["weather_code"], weather["precipitation_mm"]
        )
        weather["signals"] = _weather_signals(
            weather["weather_code"],
            weather["temperature_c"],
            weather["visibility_m"],
            weather["wind_speed_kmh"],
        )
        retrieved_at = datetime.fromisoformat(weather["retrieved_at"])
        if retrieved_at.tzinfo is None:
            retrieved_at = retrieved_at.replace(tzinfo=timezone.utc)
        age_seconds = max(
            0,
            (
                datetime.now(timezone.utc)
                - retrieved_at.astimezone(timezone.utc)
            ).total_seconds(),
        )
        return weather, max(age_seconds, OPEN_METEO_CACHE_SECONDS + 1)
    try:
        retrieved_at = datetime.fromisoformat(row["retrieved_at"])
        weather = json.loads(row["weather_json"])
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(weather, dict):
        return None
    if retrieved_at.tzinfo is None:
        retrieved_at = retrieved_at.replace(tzinfo=timezone.utc)
    age_seconds = max(
        0, (datetime.now(timezone.utc) - retrieved_at.astimezone(timezone.utc)).total_seconds()
    )
    return weather, age_seconds


def _store_live_weather_cache(
    latitude: float,
    longitude: float,
    include_forecast: bool,
    weather: dict,
    retrieved_at: str,
) -> None:
    cache_latitude, cache_longitude = _weather_cache_key(latitude, longitude)
    with database_session() as connection:
        connection.execute(
            """
            INSERT INTO live_weather_cache (
                latitude, longitude, include_forecast, weather_json, retrieved_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(latitude, longitude, include_forecast) DO UPDATE SET
                weather_json = excluded.weather_json,
                retrieved_at = excluded.retrieved_at
            """,
            (
                cache_latitude,
                cache_longitude,
                int(include_forecast),
                json.dumps(weather),
                retrieved_at,
            ),
        )


def _weather_retry_seconds(response: httpx.Response) -> int:
    retry_after = response.headers.get("Retry-After")
    if retry_after is not None:
        try:
            return max(1, int(retry_after))
        except ValueError:
            pass
    return OPEN_METEO_DEFAULT_RETRY_SECONDS


async def _get_live_weather_points(
    points: list[tuple[float, float]],
    *,
    include_forecast: bool,
    force_refresh: bool = False,
) -> tuple[dict[tuple[float, float], dict], dict[tuple[float, float], dict]]:
    global OPEN_METEO_RETRY_UNTIL

    unique_points = {}
    for latitude, longitude in points:
        unique_points.setdefault(_weather_cache_key(latitude, longitude), (latitude, longitude))

    results: dict[tuple[float, float], dict] = {}
    stale_cache: dict[tuple[float, float], tuple[dict, float]] = {}
    errors: dict[tuple[float, float], dict] = {}

    def apply_cached_point(key: tuple[float, float], point: tuple[float, float]) -> None:
        cached = _read_live_weather_cache(*point, include_forecast)
        if cached is None:
            return
        weather, age_seconds = cached
        if force_refresh:
            stale_cache[key] = (
                weather,
                max(age_seconds, OPEN_METEO_CACHE_SECONDS + 1),
            )
        elif age_seconds <= OPEN_METEO_CACHE_SECONDS:
            results[key] = {**weather, "cache_status": "cached"}
            stale_cache.pop(key, None)
        else:
            stale_cache[key] = (weather, age_seconds)

    for key, point in unique_points.items():
        apply_cached_point(key, point)
    missing = {key: point for key, point in unique_points.items() if key not in results}
    if not missing:
        return results, errors

    async with OPEN_METEO_REQUEST_LOCK:
        if not force_refresh:
            for key, point in missing.copy().items():
                apply_cached_point(key, point)
                if key in results:
                    missing.pop(key)
        if missing:
            retry_seconds = max(0, int(OPEN_METEO_RETRY_UNTIL - monotonic()))
            if retry_seconds and not force_refresh:
                failure = {
                    "status_code": status.HTTP_429_TOO_MANY_REQUESTS,
                    "detail": (
                        "Open-Meteo rate limit is active; using cached data where "
                        f"available. Automatic provider requests are paused for {retry_seconds} seconds."
                    ),
                    "retry_after_seconds": retry_seconds,
                }
                for key in missing:
                    errors[key] = failure
            else:
                params = _open_meteo_params(
                    0, 0, include_forecast=include_forecast
                )
                params["latitude"] = ",".join(
                    str(point[0]) for point in missing.values()
                )
                params["longitude"] = ",".join(
                    str(point[1]) for point in missing.values()
                )
                try:
                    async with httpx.AsyncClient(timeout=15) as client:
                        response = await client.get(OPEN_METEO_URL, params=params)
                        response.raise_for_status()
                        provider_data = response.json()
                except httpx.HTTPStatusError as error:
                    if error.response.status_code == 429:
                        retry_seconds = _weather_retry_seconds(error.response)
                        OPEN_METEO_RETRY_UNTIL = monotonic() + retry_seconds
                        failure = {
                            "status_code": status.HTTP_429_TOO_MANY_REQUESTS,
                            "detail": (
                                "Open-Meteo rate limit reached; using cached data "
                                "where available. Retry automatically after "
                                f"{retry_seconds} seconds."
                            ),
                            "retry_after_seconds": retry_seconds,
                        }
                    else:
                        failure = {
                            "status_code": status.HTTP_502_BAD_GATEWAY,
                            "detail": f"Open-Meteo returned HTTP {error.response.status_code}.",
                            "retry_after_seconds": 0,
                        }
                    for key in missing:
                        errors[key] = failure
                except (httpx.HTTPError, ValueError) as error:
                    failure = {
                        "status_code": status.HTTP_502_BAD_GATEWAY,
                        "detail": f"Open-Meteo request failed: {error}",
                        "retry_after_seconds": 0,
                    }
                    for key in missing:
                        errors[key] = failure
                else:
                    if isinstance(provider_data, dict) and len(missing) == 1:
                        point_data_items = [provider_data]
                    elif isinstance(provider_data, list) and len(provider_data) == len(missing):
                        point_data_items = provider_data
                    else:
                        point_data_items = []
                    if not point_data_items:
                        failure = {
                            "status_code": status.HTTP_502_BAD_GATEWAY,
                            "detail": "Open-Meteo returned an invalid number of location observations.",
                            "retry_after_seconds": 0,
                        }
                        for key in missing:
                            if key not in stale_cache:
                                errors[key] = failure
                    else:
                        retrieved_at = datetime.now(timezone.utc).isoformat()
                        for (key, point), point_data in zip(missing.items(), point_data_items):
                            try:
                                weather = _normalize_open_meteo(
                                    point_data, point[0], point[1]
                                )
                            except (ValueError, TypeError) as error:
                                errors[key] = {
                                    "status_code": status.HTTP_502_BAD_GATEWAY,
                                    "detail": f"Open-Meteo returned invalid weather data: {error}",
                                    "retry_after_seconds": 0,
                                }
                                continue
                            weather["retrieved_at"] = retrieved_at
                            _store_live_weather_cache(
                                point[0],
                                point[1],
                                include_forecast,
                                weather,
                                retrieved_at,
                            )
                            stale_cache.pop(key, None)
                            results[key] = {**weather, "cache_status": "live"}

    for key, (weather, age_seconds) in stale_cache.items():
        results.setdefault(key, {
            **weather,
            "cache_status": "stale",
            "cache_age_seconds": int(age_seconds),
            "provider_error": errors.get(key, {}).get("detail"),
        })
    return results, errors


def _weather_event(weather_code: int, precipitation_mm: float | None) -> str:
    if weather_code in (7, 8, 9):
        return "Dust Storm"
    if weather_code in (45, 48):
        return "Fog"
    if weather_code in (95, 96, 99):
        return "Thunderstorm"
    if weather_code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
        return "Rain"
    if precipitation_mm is not None and precipitation_mm > 0:
        return "Rain"
    return "Weather"


def _store_weather_observation(
    connection: DatabaseConnection, city: dict, weather: dict, retrieved_at: str
) -> None:
    connection.execute(
        """
        INSERT INTO weather_observations (
            city_key, observed_at, city, state, latitude, longitude, condition,
            weather_code, temperature_c, apparent_temperature_c, humidity_percent,
            precipitation_mm, visibility_m, wind_speed_kmh, source, retrieved_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(city_key, observed_at) DO UPDATE SET
            condition = excluded.condition,
            weather_code = excluded.weather_code,
            temperature_c = excluded.temperature_c,
            apparent_temperature_c = excluded.apparent_temperature_c,
            humidity_percent = excluded.humidity_percent,
            precipitation_mm = excluded.precipitation_mm,
            visibility_m = excluded.visibility_m,
            wind_speed_kmh = excluded.wind_speed_kmh,
            source = excluded.source,
            retrieved_at = excluded.retrieved_at
        """,
        (
            city["name"].casefold(),
            weather["observed_at"],
            city["name"],
            city["state"],
            weather["latitude"],
            weather["longitude"],
            weather["condition"],
            weather["weather_code"],
            weather["temperature_c"],
            weather["apparent_temperature_c"],
            weather["humidity_percent"],
            weather["precipitation_mm"],
            weather["visibility_m"],
            weather["wind_speed_kmh"],
            "Open-Meteo",
            retrieved_at,
        ),
    )


@app.get("/api/weather/india")
async def india_weather() -> dict:
    points = [(city["latitude"], city["longitude"]) for city in INDIA_CITIES]
    results, point_errors = await _get_live_weather_points(
        points, include_forecast=False
    )
    observations = []
    errors = []
    for city in INDIA_CITIES:
        key = _weather_cache_key(city["latitude"], city["longitude"])
        weather = results.get(key)
        if weather is None:
            error = point_errors.get(key, {})
            errors.append(
                {"city": city["name"], "detail": error.get("detail", "No data available.")}
            )
            continue
        observations.append(
            {
                **city,
                **weather,
                "source": "Open-Meteo",
                "verification_status": "Provider observation; not disaster verification",
            }
        )
    if not observations and errors:
        first_error = next(iter(point_errors.values()), {})
        if first_error.get("status_code") == status.HTTP_429_TOO_MANY_REQUESTS:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=first_error["detail"],
                headers={"Retry-After": str(first_error["retry_after_seconds"])},
            )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Open-Meteo multi-location request failed: {first_error.get('detail', 'No valid observations returned.')}",
        )

    retrieved_at = max(item["retrieved_at"] for item in observations)
    with database_session() as connection:
        for observation in observations:
            city = next(item for item in INDIA_CITIES if item["name"] == observation["name"])
            _store_weather_observation(connection, city, observation, retrieved_at)

    return {
        "source": "Open-Meteo",
        "source_url": OPEN_METEO_URL,
        "retrieved_at": retrieved_at,
        "updated_at": max(item["observed_at"] for item in observations),
        "items": observations,
        "total": len(observations),
        "partial_errors": errors,
        "note": "Cached model output is labelled; weather output is not an official warning or citizen-report verification.",
    }


def _normalize_nasa_power(
    payload: object, latitude: float, longitude: float
) -> tuple[list[dict], dict[str, str]]:
    if not isinstance(payload, dict):
        raise ValueError("NASA POWER response must be a JSON object.")
    properties = payload.get("properties")
    parameters = properties.get("parameter") if isinstance(properties, dict) else None
    metadata = payload.get("parameters")
    header = payload.get("header")
    fill_value = (
        _number_or_none(header.get("fill_value"))
        if isinstance(header, dict)
        else -999.0
    )
    if not isinstance(parameters, dict) or not isinstance(metadata, dict):
        raise ValueError("NASA POWER response is missing daily parameter data.")

    date_keys: set[str] = set()
    for parameter_name in NASA_POWER_PARAMETERS:
        values = parameters.get(parameter_name)
        if not isinstance(values, dict):
            raise ValueError(f"NASA POWER response is missing {parameter_name}.")
        date_keys.update(key for key in values if isinstance(key, str))

    items = []
    for date_key in sorted(date_keys):
        try:
            observation_date = datetime.strptime(date_key, "%Y%m%d").date()
        except ValueError as error:
            raise ValueError(f"NASA POWER returned an invalid date: {date_key}.") from error
        item: dict[str, object] = {
            "date": observation_date.isoformat(),
            "latitude": latitude,
            "longitude": longitude,
        }
        for parameter_name, (field_name, _) in NASA_POWER_PARAMETERS.items():
            values = parameters[parameter_name]
            value = _number_or_none(values.get(date_key))
            item[field_name] = None if value == fill_value else value
        items.append(item)

    units = {}
    for parameter_name, (field_name, default_unit) in NASA_POWER_PARAMETERS.items():
        parameter_metadata = metadata.get(parameter_name)
        unit = (
            parameter_metadata.get("units")
            if isinstance(parameter_metadata, dict)
            else None
        )
        units[field_name] = unit if isinstance(unit, str) else default_unit
    return items, units


def _store_nasa_power_observations(
    connection: DatabaseConnection,
    latitude: float,
    longitude: float,
    items: list[dict],
    source_url: str,
    retrieved_at: str,
) -> None:
    location_key = f"{latitude:.4f},{longitude:.4f}"
    for item in items:
        connection.execute(
            """
            INSERT INTO nasa_power_observations (
                location_key, observation_date, latitude, longitude,
                temperature_mean_c, temperature_max_c, temperature_min_c,
                precipitation_mm_day, humidity_percent, wind_speed_m_s,
                source, source_url, retrieved_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(location_key, observation_date) DO UPDATE SET
                temperature_mean_c = excluded.temperature_mean_c,
                temperature_max_c = excluded.temperature_max_c,
                temperature_min_c = excluded.temperature_min_c,
                precipitation_mm_day = excluded.precipitation_mm_day,
                humidity_percent = excluded.humidity_percent,
                wind_speed_m_s = excluded.wind_speed_m_s,
                source_url = excluded.source_url,
                retrieved_at = excluded.retrieved_at
            """,
            (
                location_key,
                item["date"],
                latitude,
                longitude,
                item["temperature_mean_c"],
                item["temperature_max_c"],
                item["temperature_min_c"],
                item["precipitation_mm_day"],
                item["humidity_percent"],
                item["wind_speed_m_s"],
                "NASA POWER",
                source_url,
                retrieved_at,
            ),
        )


@app.get("/api/weather/nasa-power/daily")
async def nasa_power_daily(
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    start_date: date = Query(...),
    end_date: date = Query(...),
) -> dict:
    if start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="start_date must be on or before end_date.",
        )
    if start_date < date(1981, 1, 1):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="NASA POWER daily data begins on 1981-01-01.",
        )
    if (end_date - start_date).days > 30:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="NASA POWER requests are limited to a 31-day range.",
        )
    if end_date > datetime.now(timezone.utc).date():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="end_date cannot be in the future.",
        )
    retrieved_at = datetime.now(timezone.utc).isoformat()
    params = {
        "parameters": ",".join(NASA_POWER_PARAMETERS),
        "community": "AG",
        "longitude": longitude,
        "latitude": latitude,
        "start": start_date.strftime("%Y%m%d"),
        "end": end_date.strftime("%Y%m%d"),
        "format": "JSON",
        "time-standard": "UTC",
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(NASA_POWER_DAILY_URL, params=params)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="NASA POWER could not be reached or returned invalid JSON.",
        ) from error
    try:
        items, units = _normalize_nasa_power(payload, latitude, longitude)
    except (ValueError, TypeError) as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"NASA POWER returned invalid daily data: {error}",
        ) from error

    request_url = str(response.request.url)
    with database_session() as connection:
        _store_nasa_power_observations(
            connection, latitude, longitude, items, request_url, retrieved_at
        )
    return {
        "source": "NASA POWER",
        "source_url": request_url,
        "product": "Daily meteorological data (AG community; UTC)",
        "location": {"latitude": latitude, "longitude": longitude},
        "period": {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
        "retrieved_at": retrieved_at,
        "units": units,
        "items": items,
        "total": len(items),
        "note": (
            "NASA POWER daily gridded data is climate/weather context, not a real-time "
            "station observation, official warning, or verification of a citizen report. "
            "Unavailable source values are returned as null."
        ),
    }


@app.get("/api/earthquakes/india")
async def india_earthquakes(
    minimum_magnitude: float = Query(0, ge=0, le=10),
) -> dict:
    retrieved_at = datetime.now(timezone.utc).isoformat()
    start_time = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    params = {
        "format": "geojson",
        "starttime": start_time,
        "minlatitude": 6,
        "maxlatitude": 38,
        "minlongitude": 68,
        "maxlongitude": 98,
        "minmagnitude": minimum_magnitude,
        "orderby": "time",
        "limit": 1000,
    }
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.get(USGS_EARTHQUAKE_QUERY_URL, params=params)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="USGS FDSN query could not be reached or returned invalid data.",
        ) from error

    features = payload.get("features") if isinstance(payload, dict) else None
    if not isinstance(features, list):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="USGS FDSN query response is missing its feature list.",
        )

    earthquakes = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties")
        geometry = feature.get("geometry")
        coordinates = geometry.get("coordinates") if isinstance(geometry, dict) else None
        if not isinstance(properties, dict) or not isinstance(coordinates, list) or len(coordinates) < 2:
            continue
        longitude = _number_or_none(coordinates[0])
        latitude = _number_or_none(coordinates[1])
        magnitude = _number_or_none(properties.get("mag"))
        epoch_ms = _number_or_none(properties.get("time"))
        source_id = feature.get("id")
        if (
            not isinstance(source_id, str)
            or latitude is None
            or longitude is None
            or not (6 <= latitude <= 38 and 68 <= longitude <= 98)
            or (magnitude is not None and magnitude < minimum_magnitude)
            or epoch_ms is None
        ):
            continue
        try:
            occurred_at = datetime.fromtimestamp(
                epoch_ms / 1000, timezone.utc
            ).isoformat()
        except (OverflowError, OSError, ValueError):
            continue
        earthquakes.append(
            {
                "source_id": source_id,
                "place": str(properties.get("place") or "Location not provided"),
                "magnitude": magnitude,
                "occurred_at": occurred_at,
                "latitude": latitude,
                "longitude": longitude,
                "depth_km": _number_or_none(coordinates[2]) if len(coordinates) > 2 else None,
                "source_url": str(properties.get("url") or ""),
                "source": "USGS",
                "retrieved_at": retrieved_at,
                "status": "USGS reported; not independently verified by this platform",
            }
        )

    _store_earthquakes(earthquakes)
    earthquakes.sort(key=lambda item: item["occurred_at"], reverse=True)
    return {
        "source": "USGS",
        "source_url": str(response.request.url),
        "retrieved_at": retrieved_at,
        "items": earthquakes[:100],
        "total": len(earthquakes),
        "note": "USGS source reports; this platform does not independently verify earthquake events.",
    }


def _store_earthquakes(earthquakes: list[dict]) -> None:
    with database_session() as connection:
        for item in earthquakes:
            connection.execute(
                """
                INSERT INTO earthquakes (
                    source_id, place, magnitude, occurred_at, latitude, longitude,
                    depth_km, source_url, source, retrieved_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    place = excluded.place,
                    magnitude = excluded.magnitude,
                    occurred_at = excluded.occurred_at,
                    latitude = excluded.latitude,
                    longitude = excluded.longitude,
                    depth_km = excluded.depth_km,
                    source_url = excluded.source_url,
                    retrieved_at = excluded.retrieved_at
                """,
                (
                    item["source_id"],
                    item["place"],
                    item["magnitude"],
                    item["occurred_at"],
                    item["latitude"],
                    item["longitude"],
                    item["depth_km"],
                    item["source_url"],
                    item["source"],
                    item["retrieved_at"],
                ),
            )


@app.get("/api/earthquakes/nearby")
async def nearby_earthquakes(
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(200, ge=10, le=1000),
    days: int = Query(30, ge=1, le=30),
    minimum_magnitude: float = Query(2.5, ge=0, le=10),
) -> dict:
    retrieved_at = datetime.now(timezone.utc).isoformat()
    start_time = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    params = {
        "format": "geojson",
        "starttime": start_time,
        "latitude": latitude,
        "longitude": longitude,
        "maxradiuskm": radius_km,
        "minmagnitude": minimum_magnitude,
        "orderby": "time",
        "limit": 100,
    }
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.get(USGS_EARTHQUAKE_QUERY_URL, params=params)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="USGS nearby earthquake query could not be reached or returned invalid data.",
        ) from error

    features = payload.get("features") if isinstance(payload, dict) else None
    if not isinstance(features, list):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="USGS nearby earthquake response is missing its feature list.",
        )

    earthquakes = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties")
        geometry = feature.get("geometry")
        coordinates = geometry.get("coordinates") if isinstance(geometry, dict) else None
        if not isinstance(properties, dict) or not isinstance(coordinates, list) or len(coordinates) < 2:
            continue
        longitude_value = _number_or_none(coordinates[0])
        latitude_value = _number_or_none(coordinates[1])
        magnitude = _number_or_none(properties.get("mag"))
        epoch_ms = _number_or_none(properties.get("time"))
        source_id = feature.get("id")
        if (
            not isinstance(source_id, str)
            or latitude_value is None
            or longitude_value is None
            or magnitude is None
            or magnitude < minimum_magnitude
            or epoch_ms is None
        ):
            continue
        try:
            occurred_at = datetime.fromtimestamp(epoch_ms / 1000, timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            continue
        earthquakes.append(
            {
                "source_id": source_id,
                "place": str(properties.get("place") or "Location not provided"),
                "magnitude": magnitude,
                "occurred_at": occurred_at,
                "latitude": latitude_value,
                "longitude": longitude_value,
                "depth_km": _number_or_none(coordinates[2]) if len(coordinates) > 2 else None,
                "source_url": str(properties.get("url") or ""),
                "source": "USGS",
                "retrieved_at": retrieved_at,
            }
        )

    _store_earthquakes(earthquakes)
    earthquakes.sort(key=lambda item: item["occurred_at"], reverse=True)
    return {
        "source": "USGS",
        "source_url": str(response.request.url),
        "retrieved_at": retrieved_at,
        "center": {"latitude": latitude, "longitude": longitude},
        "radius_km": radius_km,
        "days": days,
        "minimum_magnitude": minimum_magnitude,
        "items": earthquakes,
        "total": len(earthquakes),
        "note": "USGS source-reported earthquakes; not an independent verification.",
    }


@app.get("/api/alerts")
def list_alerts(
    alert_status: Literal["active", "resolved"] = Query(default="active", alias="status"),
) -> dict:
    with database_session() as connection:
        rows = connection.execute(
            """
            SELECT alerts.*, events.location, events.event_type
            FROM alerts JOIN events ON events.id = alerts.event_id
            WHERE alerts.status = ?
            ORDER BY alerts.created_at DESC
            """,
            (alert_status,),
        ).fetchall()
    return {"items": [dict(row) for row in rows], "total": len(rows)}
