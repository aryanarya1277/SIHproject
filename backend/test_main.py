import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient


class WeatherApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        os.environ["WEATHER_DATABASE_PATH"] = str(Path(cls.temp_dir.name) / "test.sqlite3")
        cls.previous_database_url = os.environ.get("DATABASE_URL")
        cls.previous_app_env = os.environ.get("APP_ENV")
        os.environ["DATABASE_URL"] = (
            "sqlite:///" + Path(os.environ["WEATHER_DATABASE_PATH"]).as_posix()
        )
        os.environ["APP_ENV"] = "test"
        from main import app

        cls.client_context = TestClient(app)
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)
        cls.temp_dir.cleanup()
        os.environ.pop("WEATHER_DATABASE_PATH", None)
        if cls.previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = cls.previous_database_url
        if cls.previous_app_env is None:
            os.environ.pop("APP_ENV", None)
        else:
            os.environ["APP_ENV"] = cls.previous_app_env

    def setUp(self):
        import main

        main.OPEN_METEO_RETRY_UNTIL = 0
        connection = sqlite3.connect(os.environ["WEATHER_DATABASE_PATH"])
        try:
            connection.execute("DELETE FROM live_weather_cache")
            connection.execute("DELETE FROM weather_observations")
            connection.commit()
        finally:
            connection.close()

    def test_health_summary_and_seed_data(self):
        self.assertEqual(self.client.get("/api/health").json(), {"status": "ok"})
        summary = self.client.get("/api/summary").json()
        self.assertEqual(summary["total_reports"], 5)
        self.assertEqual(summary["active_alerts"], 3)
        self.assertIs(summary["includes_demo_data"], True)
        events = self.client.get("/api/events").json()
        self.assertEqual(events["total"], 5)
        self.assertEqual(events["items"][0]["event"], "Rain")

    def test_live_server_origin_is_allowed_for_api_and_json_preflight(self):
        origin = "http://127.0.0.1:5500"
        response = self.client.options(
            "/api/summary",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["access-control-allow-origin"], origin
        )
        self.assertIn("POST", response.headers["access-control-allow-methods"])
        self.assertIn(
            "content-type",
            response.headers["access-control-allow-headers"].lower(),
        )

        localhost_response = self.client.get(
            "/api/health", headers={"Origin": "http://localhost:5500"}
        )
        self.assertEqual(
            localhost_response.headers["access-control-allow-origin"],
            "http://localhost:5500",
        )

    def test_filters_and_analytics(self):
        filtered = self.client.get("/api/events", params={"event": "Flood", "state": "Bihar"})
        self.assertEqual(filtered.status_code, 200)
        self.assertEqual(filtered.json()["total"], 1)
        location_filtered = self.client.get("/api/events", params={"location": "Ranchi"})
        self.assertEqual(location_filtered.status_code, 200)
        self.assertEqual(location_filtered.json()["total"], 1)
        invalid_range = self.client.get(
            "/api/events", params={"from_date": "2026-10-01", "to_date": "2026-09-01"}
        )
        self.assertEqual(invalid_range.status_code, 422)
        analytics = self.client.get("/api/analytics").json()
        self.assertEqual(analytics["total_reports"], 5)
        self.assertEqual(sum(item["count"] for item in analytics["distribution"]), 5)

    def test_report_creation_flags_nearby_duplicate(self):
        payload = {
            "location": "Ranchi Test",
            "state": "Jharkhand",
            "event": "Rain",
            "time": datetime.now(timezone.utc).isoformat(),
            "severity": "medium",
            "latitude": 23.3442,
            "longitude": 85.3097,
        }
        response = self.client.post("/api/events", json=payload)
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["duplicate_detected"])
        self.assertEqual(response.json()["status"], "Review")
        self.assertIsNone(response.json()["confidence"])

    def test_text_classification_is_not_report_verification(self):
        classification = {
            "disaster_label": "disaster",
            "disaster_score": 0.91,
            "social_event_type": "Flood",
            "event_type_score": 0.76,
            "model_version": "test-model",
            "verification_status": "Unverified",
        }
        with patch("main.classify_text", return_value=classification):
            response = self.client.post(
                "/api/events",
                json={
                    "location": "Test Town",
                    "state": "Test State",
                    "event": "Flood",
                    "description": "Flood water has entered the town market.",
                    "time": datetime.now(timezone.utc).isoformat(),
                    "severity": "high",
                    "latitude": 10,
                    "longitude": 10,
                },
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["status"], "Review")
        self.assertEqual(response.json()["ai_classification"], classification)
        self.assertEqual(response.json()["ai_classification_status"], "classified")

    def test_classification_endpoint_returns_explicit_untrained_response(self):
        with patch("main.classify_text", side_effect=RuntimeError("model not trained")):
            response = self.client.post(
                "/api/classify", json={"text": "Flood water entered a town."}
            )
        self.assertEqual(response.status_code, 503)
        self.assertIn("model not trained", response.json()["detail"])

    def test_report_is_still_saved_when_text_model_is_unavailable(self):
        payload = {
            "location": "Test City",
            "state": "Test State",
            "event": "Flood",
            "description": "Water is entering the market.",
            "time": datetime.now(timezone.utc).isoformat(),
            "severity": "high",
            "latitude": 15,
            "longitude": 15,
        }
        with patch("main.classify_text", side_effect=RuntimeError("model not trained")):
            response = self.client.post("/api/events", json=payload)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["status"], "Review")
        self.assertEqual(response.json()["ai_classification_status"], "model_unavailable")
        self.assertIn("model not trained", response.json()["ai_classification_error"])

    def test_removed_report_status_update_route_returns_not_found(self):
        response = self.client.patch(
            "/api/events/1/review", json={"status": "Verified"}
        )
        self.assertEqual(response.status_code, 404)

    @unittest.skipUnless(
        all(
            path.is_file()
            for path in (
                Path(__file__).resolve().parent.parent
                / "datasets"
                / "models"
                / "disaster_detection.joblib",
                Path(__file__).resolve().parent.parent
                / "datasets"
                / "models"
                / "event_type.joblib",
            )
        ),
        "Train the dataset models before running the trained inference test.",
    )
    def test_trained_model_classifies_without_verifying(self):
        response = self.client.post(
            "/api/classify",
            json={"text": "Heavy flooding reported after the river overflowed."},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["disaster_label"], "disaster")
        self.assertEqual(response.json()["social_event_type"], "Flood")
        self.assertEqual(response.json()["verification_status"], "Unverified")

    def test_report_rejects_client_claimed_source_and_timezone_free_time(self):
        payload = {
            "location": "Test City",
            "state": "Test State",
            "event": "Rain",
            "time": datetime.now(timezone.utc).isoformat(),
            "severity": "medium",
            "latitude": 10,
            "longitude": 10,
        }
        claimed_source = {**payload, "source": "Official API"}
        self.assertEqual(self.client.post("/api/events", json=claimed_source).status_code, 422)

        payload["time"] = "2026-09-27T08:00:00"
        self.assertEqual(self.client.post("/api/events", json=payload).status_code, 422)

    def test_live_weather_formats_provider_response(self):
        provider_response = httpx.Response(
            200,
            request=httpx.Request("GET", "https://api.open-meteo.com/v1/forecast"),
            json={
                "latitude": 22.5,
                "longitude": 78.9,
                "current": {
                    "time": "2026-09-27T10:30",
                    "weather_code": 3,
                    "temperature_2m": 30.0,
                    "apparent_temperature": 32.0,
                    "relative_humidity_2m": 60,
                    "precipitation": 0.0,
                    "wind_speed_10m": 12.0,
                },
                "hourly": {
                    "time": ["2026-09-27T10:00", "2026-09-27T11:00"],
                    "visibility": [900],
                },
                "daily": {
                    "time": ["2026-09-27"],
                    "weather_code": [45],
                    "temperature_2m_max": [32.0],
                    "temperature_2m_min": [24.0],
                    "precipitation_probability_max": [35],
                    "precipitation_sum": [1.2],
                },
            },
        )
        requested = {}
        provider_calls = []

        class MockAsyncClient:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def get(self, _url, **kwargs):
                provider_calls.append(kwargs["params"])
                requested["params"] = kwargs["params"]
                return provider_response

        with patch("main.httpx.AsyncClient", MockAsyncClient):
            response = self.client.get("/api/live-weather")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["condition"], "Overcast")
        self.assertEqual(response.json()["temperature_c"], 30.0)
        self.assertEqual(response.json()["visibility_m"], 900)
        self.assertEqual(response.json()["forecast"][0]["condition"], "Fog")
        self.assertEqual(response.json()["forecast"][0]["temperature_min_c"], 24.0)
        self.assertEqual(requested["params"]["forecast_days"], 5)
        self.assertEqual(response.json()["source"], "Open-Meteo")

    def test_live_weather_batch_queries_multiple_coordinates_once(self):
        point = {
            "current": {
                "time": "2026-09-27T10:30",
                "weather_code": 61,
                "temperature_2m": 24.0,
                "precipitation": 1.2,
            },
            "hourly": {
                "time": ["2026-09-27T10:00"],
                "visibility": [8000],
            },
        }
        provider_response = httpx.Response(
            200,
            request=httpx.Request("GET", "https://api.open-meteo.com/v1/forecast"),
            json=[
                {"latitude": 23.35, "longitude": 85.31, **point},
                {"latitude": 25.6, "longitude": 85.14, **point},
            ],
        )
        requested = {}
        provider_calls = []

        class MockAsyncClient:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def get(self, _url, **kwargs):
                provider_calls.append(kwargs["params"])
                requested["params"] = kwargs["params"]
                return provider_response

        coordinates = [
            ("latitude", "23.3441"),
            ("longitude", "85.3096"),
            ("latitude", "25.5941"),
            ("longitude", "85.1376"),
        ]
        with patch("main.httpx.AsyncClient", MockAsyncClient):
            response = self.client.get("/api/live-weather/batch", params=coordinates)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            requested["params"]["latitude"], "23.3441,25.5941"
        )
        self.assertEqual(
            requested["params"]["longitude"], "85.3096,85.1376"
        )
        self.assertEqual(response.json()["total"], 2)
        self.assertEqual(
            response.json()["items"][0]["requested_latitude"], 23.3441
        )
        self.assertEqual(
            response.json()["items"][1]["requested_longitude"], 85.1376
        )
        self.assertEqual(response.json()["items"][0]["weather_event"], "Rain")
        self.assertNotIn("daily", requested["params"])
        self.assertEqual(
            self.client.get(
                "/api/live-weather/batch",
                params=[("latitude", "23"), ("longitude", "85"), ("latitude", "24")],
            ).status_code,
            422,
        )
        single_response = self.client.get(
            "/api/live-weather/batch",
            params={"latitude": "23.3441", "longitude": "85.3096"},
        )
        self.assertEqual(single_response.status_code, 200)
        self.assertEqual(single_response.json()["total"], 1)
        self.assertEqual(single_response.json()["items"][0]["cache_status"], "cached")
        self.assertEqual(len(provider_calls), 1)

    def test_live_weather_batch_keeps_coordinates_on_partial_errors(self):
        provider_response = httpx.Response(
            200,
            request=httpx.Request("GET", "https://api.open-meteo.com/v1/forecast"),
            json=[
                {
                    "latitude": 23.34,
                    "longitude": 85.31,
                    "current": {
                        "time": "2026-09-27T10:30",
                        "weather_code": 3,
                        "temperature_2m": 26,
                    },
                    "hourly": {"time": ["2026-09-27T10:00"], "visibility": [9000]},
                },
                {"latitude": 25.6, "longitude": 85.14, "current": {}},
            ],
        )

        class MockAsyncClient:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def get(self, *_args, **_kwargs):
                return provider_response

        with patch("main.httpx.AsyncClient", MockAsyncClient):
            response = self.client.get(
                "/api/live-weather/batch",
                params=[
                    ("latitude", "23.3441"),
                    ("longitude", "85.3096"),
                    ("latitude", "25.5941"),
                    ("longitude", "85.1376"),
                ],
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 1)
        self.assertEqual(
            response.json()["partial_errors"],
            [
                {
                    "latitude": 25.5941,
                    "longitude": 85.1376,
                    "status_code": 502,
                    "detail": (
                        "Open-Meteo returned invalid weather data: Open-Meteo "
                        "response is missing current weather conditions."
                    ),
                    "retry_after_seconds": 0,
                }
            ],
        )

    def test_live_weather_batch_reports_provider_rate_limit(self):
        provider_response = httpx.Response(
            429,
            request=httpx.Request("GET", "https://api.open-meteo.com/v1/forecast"),
        )

        provider_calls = []

        class MockAsyncClient:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def get(self, *_args, **_kwargs):
                provider_calls.append(True)
                return provider_response

        with patch("main.httpx.AsyncClient", MockAsyncClient):
            response = self.client.get(
                "/api/live-weather/batch",
                params={"latitude": "23.3441", "longitude": "85.3096"},
            )
        self.assertEqual(response.status_code, 429)
        self.assertIn("rate limit", response.json()["detail"].lower())
        self.assertEqual(response.headers["retry-after"], "60")
        cooldown_response = self.client.get(
            "/api/live-weather/batch",
            params={"latitude": "19.076", "longitude": "72.8777"},
        )
        self.assertEqual(cooldown_response.status_code, 429)
        self.assertEqual(len(provider_calls), 1)

    def test_manual_live_weather_refresh_bypasses_app_cooldown(self):
        import main

        main.OPEN_METEO_RETRY_UNTIL = main.monotonic() + 900
        provider_response = httpx.Response(
            200,
            request=httpx.Request("GET", "https://api.open-meteo.com/v1/forecast"),
            json={
                "latitude": 10.25,
                "longitude": 20.5,
                "current": {
                    "time": "2026-09-27T10:30",
                    "weather_code": 1,
                    "temperature_2m": 29.0,
                },
                "hourly": {"time": ["2026-09-27T10:00"], "visibility": [10000]},
                "daily": {"time": ["2026-09-27"]},
            },
        )
        provider_calls = []

        class MockAsyncClient:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def get(self, _url, **kwargs):
                provider_calls.append(kwargs["params"])
                return provider_response

        with patch("main.httpx.AsyncClient", MockAsyncClient):
            response = self.client.get(
                "/api/live-weather",
                params={
                    "latitude": "10.25",
                    "longitude": "20.5",
                    "force_refresh": "true",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["cache_status"], "live")
        self.assertEqual(response.json()["temperature_c"], 29.0)
        self.assertEqual(len(provider_calls), 1)

    def test_live_weather_uses_met_norway_when_open_meteo_is_rate_limited(self):
        open_meteo_response = httpx.Response(
            429,
            request=httpx.Request("GET", "https://api.open-meteo.com/v1/forecast"),
            headers={"Retry-After": "60"},
        )
        met_norway_response = httpx.Response(
            200,
            request=httpx.Request(
                "GET",
                "https://api.met.no/weatherapi/locationforecast/2.0/compact",
            ),
            json={
                "properties": {
                    "timeseries": [
                        {
                            "time": "2026-09-27T10:00:00Z",
                            "data": {
                                "instant": {
                                    "details": {
                                        "air_temperature": 24.5,
                                        "relative_humidity": 70,
                                        "wind_speed": 5,
                                        "wind_from_direction": 180,
                                    }
                                },
                                "next_1_hours": {
                                    "summary": {"symbol_code": "rain"},
                                    "details": {"precipitation_amount": 0.8},
                                },
                                "next_6_hours": {
                                    "summary": {"symbol_code": "rain"},
                                    "details": {"precipitation_amount": 2.0},
                                },
                            },
                        },
                    ]
                }
            },
        )
        requested_urls = []

        class MockAsyncClient:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def get(self, url, **_kwargs):
                requested_urls.append(url)
                if "api.met.no" in url:
                    return met_norway_response
                return open_meteo_response

        with patch("main.httpx.AsyncClient", MockAsyncClient):
            response = self.client.get(
                "/api/live-weather",
                params={
                    "latitude": "10.25",
                    "longitude": "20.5",
                    "force_refresh": "true",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["source"], "MET Norway")
        self.assertEqual(response.json()["condition"], "Slight rain")
        self.assertEqual(response.json()["temperature_c"], 24.5)
        self.assertEqual(response.json()["wind_speed_kmh"], 18.0)
        self.assertEqual(response.json()["forecast"][0]["condition"], "Slight rain")
        self.assertEqual(len(requested_urls), 2)

    def test_live_weather_uses_stale_cache_during_rate_limit(self):
        provider_response = httpx.Response(
            200,
            request=httpx.Request("GET", "https://api.open-meteo.com/v1/forecast"),
            json={
                "latitude": 23.34,
                "longitude": 85.31,
                "current": {
                    "time": "2026-09-27T10:30",
                    "weather_code": 3,
                    "temperature_2m": 26.0,
                },
                "hourly": {"time": ["2026-09-27T10:00"], "visibility": [9000]},
                "daily": {"time": ["2026-09-27"]},
            },
        )

        class MockAsyncClient:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def get(self, *_args, **_kwargs):
                return provider_response

        with patch("main.httpx.AsyncClient", MockAsyncClient):
            initial_response = self.client.get(
                "/api/live-weather",
                params={"latitude": "23.3441", "longitude": "85.3096"},
            )
        self.assertEqual(initial_response.status_code, 200)

        connection = sqlite3.connect(os.environ["WEATHER_DATABASE_PATH"])
        try:
            connection.execute(
                """
                UPDATE live_weather_cache SET retrieved_at = ?
                WHERE latitude = ? AND longitude = ? AND include_forecast = 1
                """,
                ("2026-09-27T00:00:00+00:00", 23.3441, 85.3096),
            )
            connection.commit()
        finally:
            connection.close()

        provider_rate_limit = httpx.Response(
            429,
            request=httpx.Request("GET", "https://api.open-meteo.com/v1/forecast"),
        )

        class RateLimitedAsyncClient(MockAsyncClient):
            async def get(self, *_args, **_kwargs):
                return provider_rate_limit

        with patch("main.httpx.AsyncClient", RateLimitedAsyncClient):
            stale_response = self.client.get(
                "/api/live-weather",
                params={"latitude": "23.3441", "longitude": "85.3096"},
            )
        self.assertEqual(stale_response.status_code, 200)
        self.assertEqual(stale_response.json()["cache_status"], "stale")
        self.assertEqual(stale_response.json()["temperature_c"], 26.0)

    def test_live_weather_falls_back_to_saved_city_observation(self):
        import main

        city_observation = {
            "current": {
                "time": "2026-09-27T10:30",
                "weather_code": 3,
                "temperature_2m": 26.0,
                "apparent_temperature": 27.0,
                "relative_humidity_2m": 65,
                "precipitation": 0,
                "wind_speed_10m": 8,
            },
            "hourly": {
                "time": ["2026-09-27T10:00"],
                "visibility": [9000],
            },
        }
        city_response = httpx.Response(
            200,
            request=httpx.Request("GET", "https://api.open-meteo.com/v1/forecast"),
            json=[
                {
                    "latitude": city["latitude"],
                    "longitude": city["longitude"],
                    **city_observation,
                }
                for city in main.INDIA_CITIES
            ],
        )

        class CityAsyncClient:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def get(self, *_args, **_kwargs):
                return city_response

        with patch("main.httpx.AsyncClient", CityAsyncClient):
            city_response_result = self.client.get("/api/weather/india")
        self.assertEqual(city_response_result.status_code, 200)

        connection = sqlite3.connect(os.environ["WEATHER_DATABASE_PATH"])
        try:
            connection.execute(
                "UPDATE weather_observations SET retrieved_at = ?",
                ("2026-09-27T00:00:00+00:00",),
            )
            connection.commit()
        finally:
            connection.close()

        rate_limit_response = httpx.Response(
            429,
            request=httpx.Request("GET", "https://api.open-meteo.com/v1/forecast"),
        )

        class RateLimitedAsyncClient(CityAsyncClient):
            async def get(self, *_args, **_kwargs):
                return rate_limit_response

        with patch("main.httpx.AsyncClient", RateLimitedAsyncClient):
            live_response = self.client.get(
                "/api/live-weather",
                params={
                    "latitude": "28.6139",
                    "longitude": "77.209",
                },
            )
        self.assertEqual(live_response.status_code, 200)
        self.assertEqual(live_response.json()["cache_status"], "stale")
        self.assertEqual(live_response.json()["temperature_c"], 26.0)

    def test_live_weather_reports_provider_outages_and_invalid_payloads(self):
        responses = (
            httpx.Response(
                503,
                request=httpx.Request(
                    "GET", "https://api.open-meteo.com/v1/forecast"
                ),
            ),
            httpx.Response(
                200,
                request=httpx.Request(
                    "GET", "https://api.open-meteo.com/v1/forecast"
                ),
                content=b"not-json",
            ),
            httpx.Response(
                200,
                request=httpx.Request(
                    "GET", "https://api.open-meteo.com/v1/forecast"
                ),
                json={"current": {"temperature_2m": 20}},
            ),
        )

        for provider_response in responses:
            class MockAsyncClient:
                def __init__(self, **_kwargs):
                    pass

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *_args):
                    return None

                async def get(self, *_args, **_kwargs):
                    return provider_response

            with patch("main.httpx.AsyncClient", MockAsyncClient):
                response = self.client.get("/api/live-weather")
            self.assertEqual(response.status_code, 502)
            self.assertTrue(response.json()["detail"])

    def test_india_weather_ingestion_normalizes_and_persists_city_observations(self):
        provider_response = httpx.Response(
            200,
            request=httpx.Request("GET", "https://api.open-meteo.com/v1/forecast"),
            json=[
                {
                    "latitude": 28.61,
                    "longitude": 77.21,
                    "current": {
                        "time": "2026-09-27T10:00",
                        "weather_code": 45,
                        "temperature_2m": 25,
                        "apparent_temperature": 26,
                        "relative_humidity_2m": 80,
                        "precipitation": 0,
                        "wind_speed_10m": 5,
                    },
                    "hourly": {
                        "time": ["2026-09-27T10:00"],
                        "visibility": [600],
                    },
                },
            ]
            * 8,
        )
        requested = {}

        class MockAsyncClient:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def get(self, url, **kwargs):
                requested["url"] = url
                requested["params"] = kwargs["params"]
                return provider_response

        with patch("main.httpx.AsyncClient", MockAsyncClient):
            first_response = self.client.get("/api/weather/india")
            second_response = self.client.get("/api/weather/india")

        self.assertEqual(first_response.status_code, 200)
        data = first_response.json()
        self.assertEqual(data["total"], 8)
        self.assertEqual(data["source"], "Open-Meteo")
        self.assertEqual(
            requested["url"], "https://api.open-meteo.com/v1/forecast"
        )
        self.assertEqual(len(requested["params"]["latitude"].split(",")), 8)
        self.assertEqual(len(requested["params"]["longitude"].split(",")), 8)
        self.assertTrue(data["retrieved_at"])
        self.assertIn("Fog / low visibility observed", data["items"][0]["signals"])
        self.assertEqual(data["items"][0]["weather_event"], "Fog")
        connection = sqlite3.connect(os.environ["WEATHER_DATABASE_PATH"])
        try:
            count = connection.execute(
                "SELECT COUNT(*) FROM weather_observations"
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(count, 8)
        self.assertEqual(second_response.status_code, 200)

    def test_india_weather_returns_explicit_error_when_all_cities_fail(self):
        class MockAsyncClient:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def get(self, *_args, **_kwargs):
                raise httpx.ConnectError("provider offline")

        with patch("main.httpx.AsyncClient", MockAsyncClient):
            response = self.client.get("/api/weather/india")
        self.assertEqual(response.status_code, 502)
        self.assertIn("multi-location", response.json()["detail"])

    def test_india_weather_rejects_invalid_multi_location_response(self):
        provider_response = httpx.Response(
            200,
            request=httpx.Request("GET", "https://api.open-meteo.com/v1/forecast"),
            json=[{"current": {"weather_code": 0, "time": "2026-09-27T10:00"}}],
        )

        class MockAsyncClient:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def get(self, *_args, **_kwargs):
                return provider_response

        with patch("main.httpx.AsyncClient", MockAsyncClient):
            response = self.client.get("/api/weather/india")
        self.assertEqual(response.status_code, 502)
        self.assertIn("invalid number", response.json()["detail"])

    def test_nasa_power_daily_normalizes_fill_values_and_upserts(self):
        provider_response = httpx.Response(
            200,
            request=httpx.Request(
                "GET", "https://power.larc.nasa.gov/api/temporal/daily/point"
            ),
            json={
                "properties": {
                    "parameter": {
                        "T2M": {"20260925": 26.59, "20260926": -999},
                        "T2M_MAX": {"20260925": 31.1, "20260926": -999},
                        "T2M_MIN": {"20260925": 22.0, "20260926": -999},
                        "PRECTOTCORR": {"20260925": 1.18, "20260926": -999},
                        "RH2M": {"20260925": 80.36, "20260926": -999},
                        "WS10M": {"20260925": 1.72, "20260926": -999},
                    }
                },
                "header": {"fill_value": -999, "time_standard": "UTC"},
                "parameters": {
                    "T2M": {"units": "C"},
                    "T2M_MAX": {"units": "C"},
                    "T2M_MIN": {"units": "C"},
                    "PRECTOTCORR": {"units": "mm/day"},
                    "RH2M": {"units": "%"},
                    "WS10M": {"units": "m/s"},
                },
            },
        )
        requested = {}

        class MockAsyncClient:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def get(self, url, **kwargs):
                requested["url"] = url
                requested["params"] = kwargs["params"]
                return provider_response

        params = {
            "latitude": 28.6139,
            "longitude": 77.209,
            "start_date": "2026-09-25",
            "end_date": "2026-09-26",
        }
        with patch("main.httpx.AsyncClient", MockAsyncClient):
            response = self.client.get("/api/weather/nasa-power/daily", params=params)
            second_response = self.client.get(
                "/api/weather/nasa-power/daily", params=params
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            requested["url"], "https://power.larc.nasa.gov/api/temporal/daily/point"
        )
        self.assertEqual(requested["params"]["community"], "AG")
        self.assertEqual(requested["params"]["time-standard"], "UTC")
        self.assertIn("PRECTOTCORR", requested["params"]["parameters"])
        data = response.json()
        self.assertEqual(data["source"], "NASA POWER")
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["items"][0]["temperature_mean_c"], 26.59)
        self.assertIsNone(data["items"][1]["temperature_mean_c"])
        self.assertEqual(data["units"]["precipitation_mm_day"], "mm/day")
        self.assertEqual(second_response.status_code, 200)
        connection = sqlite3.connect(os.environ["WEATHER_DATABASE_PATH"])
        try:
            count = connection.execute(
                "SELECT COUNT(*) FROM nasa_power_observations"
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(count, 2)

    def test_nasa_power_validates_date_ranges_and_provider_payload(self):
        invalid_ranges = (
            {
                "latitude": 28.6,
                "longitude": 77.2,
                "start_date": "2026-09-01",
                "end_date": "2026-10-03",
            },
            {
                "latitude": 28.6,
                "longitude": 77.2,
                "start_date": "2026-09-27",
                "end_date": "2026-09-26",
            },
            {
                "latitude": 28.6,
                "longitude": 77.2,
                "start_date": "1980-12-31",
                "end_date": "1981-01-01",
            },
        )
        for params in invalid_ranges:
            response = self.client.get("/api/weather/nasa-power/daily", params=params)
            self.assertEqual(response.status_code, 422)

        provider_response = httpx.Response(
            200,
            request=httpx.Request("GET", "https://power.larc.nasa.gov/"),
            json={"messages": ["invalid request"]},
        )

        class MockAsyncClient:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def get(self, *_args, **_kwargs):
                return provider_response

        with patch("main.httpx.AsyncClient", MockAsyncClient):
            failed = self.client.get(
                "/api/weather/nasa-power/daily",
                params={
                    "latitude": 28.6,
                    "longitude": 77.2,
                    "start_date": "2026-09-25",
                    "end_date": "2026-09-26",
                },
            )
        self.assertEqual(failed.status_code, 502)

    def test_usgs_earthquake_feed_filters_india_and_upserts_by_source_id(self):
        provider_response = httpx.Response(
            200,
            request=httpx.Request(
                "GET", "https://earthquake.usgs.gov/fdsnws/event/1/query"
            ),
            json={
                "features": [
                    {
                        "id": "us-test-1",
                        "properties": {
                            "place": "Test, India",
                            "mag": 4.2,
                            "time": 1790503200000,
                            "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us-test-1",
                        },
                        "geometry": {"coordinates": [88.3, 22.5, 10]},
                    },
                    {
                        "id": "outside-india",
                        "properties": {"mag": 5, "time": 1790503200000},
                        "geometry": {"coordinates": [-120, 35, 8]},
                    },
                    {"id": "malformed", "properties": {}, "geometry": {}},
                ]
            },
        )
        requested = {}

        class MockAsyncClient:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def get(self, url, **kwargs):
                requested["url"] = url
                requested["params"] = kwargs["params"]
                return provider_response

        with patch("main.httpx.AsyncClient", MockAsyncClient):
            response = self.client.get("/api/earthquakes/india?minimum_magnitude=4")
            repeated_response = self.client.get("/api/earthquakes/india?minimum_magnitude=4")
        self.assertEqual(
            requested["url"], "https://earthquake.usgs.gov/fdsnws/event/1/query"
        )
        self.assertEqual(requested["params"]["format"], "geojson")
        self.assertEqual(requested["params"]["minlatitude"], 6)
        self.assertEqual(requested["params"]["maxlatitude"], 38)
        self.assertEqual(requested["params"]["minlongitude"], 68)
        self.assertEqual(requested["params"]["maxlongitude"], 98)
        self.assertEqual(requested["params"]["minmagnitude"], 4.0)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["source_id"], "us-test-1")
        self.assertEqual(data["items"][0]["magnitude"], 4.2)
        self.assertIn("not independently verified", data["items"][0]["status"])
        self.assertEqual(repeated_response.json()["total"], 1)
        connection = sqlite3.connect(os.environ["WEATHER_DATABASE_PATH"])
        try:
            count = connection.execute(
                "SELECT COUNT(*) FROM earthquakes WHERE source_id = 'us-test-1'"
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(count, 1)

    def test_usgs_feed_errors_on_missing_features_and_provider_outage(self):
        responses = (
            httpx.Response(
                200,
                request=httpx.Request(
                    "GET", "https://earthquake.usgs.gov/fdsnws/event/1/query"
                ),
                json={"type": "FeatureCollection"},
            ),
            httpx.Response(
                503,
                request=httpx.Request(
                    "GET", "https://earthquake.usgs.gov/fdsnws/event/1/query"
                ),
            ),
        )
        for provider_response in responses:
            class MockAsyncClient:
                def __init__(self, **_kwargs):
                    pass

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *_args):
                    return None

                async def get(self, *_args, **_kwargs):
                    return provider_response

            with patch("main.httpx.AsyncClient", MockAsyncClient):
                response = self.client.get("/api/earthquakes/india")
            self.assertEqual(response.status_code, 502)
            self.assertTrue(response.json()["detail"])

    def test_nearby_earthquake_query_returns_and_persists_events(self):
        provider_response = httpx.Response(
            200,
            request=httpx.Request(
                "GET", "https://earthquake.usgs.gov/fdsnws/event/1/query"
            ),
            json={
                "features": [
                    {
                        "id": "world-nearby-test",
                        "properties": {
                            "place": "Test event near Tokyo",
                            "mag": 4.1,
                            "time": 1790503200000,
                            "url": "https://earthquake.usgs.gov/earthquakes/eventpage/world-nearby-test",
                        },
                        "geometry": {"coordinates": [139.7, 35.7, 18]},
                    },
                    {
                        "id": "below-minimum-test",
                        "properties": {"place": "Small event", "mag": 1.2, "time": 1790503200000},
                        "geometry": {"coordinates": [139.7, 35.7, 5]},
                    },
                    {"id": "malformed-nearby-test", "properties": {}, "geometry": {}},
                ]
            },
        )
        requested = {}

        class MockAsyncClient:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def get(self, url, **kwargs):
                requested["url"] = url
                requested["params"] = kwargs["params"]
                return provider_response

        params = {
            "latitude": 35.6762,
            "longitude": 139.6503,
            "radius_km": 200,
            "days": 30,
            "minimum_magnitude": 2.5,
        }
        with patch("main.httpx.AsyncClient", MockAsyncClient):
            response = self.client.get("/api/earthquakes/nearby", params=params)
            repeat_response = self.client.get("/api/earthquakes/nearby", params=params)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(requested["url"], "https://earthquake.usgs.gov/fdsnws/event/1/query")
        self.assertEqual(requested["params"]["latitude"], 35.6762)
        self.assertEqual(requested["params"]["longitude"], 139.6503)
        self.assertEqual(requested["params"]["maxradiuskm"], 200.0)
        self.assertEqual(requested["params"]["minmagnitude"], 2.5)
        self.assertEqual(response.json()["total"], 1)
        self.assertEqual(response.json()["items"][0]["source_id"], "world-nearby-test")
        self.assertEqual(repeat_response.json()["total"], 1)
        with sqlite3.connect(os.environ["WEATHER_DATABASE_PATH"]) as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM earthquakes WHERE source_id = 'world-nearby-test'"
            ).fetchone()[0]
        self.assertEqual(count, 1)
        self.assertEqual(
            self.client.get(
                "/api/earthquakes/nearby",
                params={**params, "radius_km": 5},
            ).status_code,
            422,
        )

    def test_imd_endpoint_is_not_exposed(self):
        self.assertEqual(
            self.client.get("/api/official-rainfall?district_id=164").status_code,
            404,
        )

if __name__ == "__main__":
    unittest.main()
