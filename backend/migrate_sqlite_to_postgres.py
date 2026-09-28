from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from backend.main import DATABASE_URL, database_session, initialize_database


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SQLITE_PATH = PROJECT_ROOT / "backend" / "weather.db"
TABLE_KEYS = {
    "events": ("id",),
    "alerts": ("id",),
    "weather_observations": ("city_key", "observed_at"),
    "live_weather_cache": ("latitude", "longitude", "include_forecast"),
    "nasa_power_observations": ("location_key", "observation_date"),
    "earthquakes": ("source_id",),
}
TABLE_ORDER = tuple(TABLE_KEYS)


def _quote_identifier(identifier: str) -> str:
    if not identifier.replace("_", "").isalnum():
        raise ValueError(f"Unsupported database identifier: {identifier!r}")
    return f'"{identifier}"'


def migrate(sqlite_path: Path = DEFAULT_SQLITE_PATH) -> dict[str, object]:
    if not DATABASE_URL.startswith(("postgresql://", "postgres://")):
        raise RuntimeError(
            "Set DATABASE_URL to the target PostgreSQL database before migrating."
        )
    if not sqlite_path.is_file():
        raise FileNotFoundError(f"SQLite source database not found: {sqlite_path}")

    initialize_database(seed_demo_data=False)
    source = sqlite3.connect(
        f"{sqlite_path.resolve().as_uri()}?mode=ro",
        uri=True,
    )
    source.row_factory = sqlite3.Row
    imported: dict[str, int] = {}
    try:
        source_tables = {
            row["name"]
            for row in source.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        missing_tables = sorted(set(TABLE_ORDER) - source_tables)
        if missing_tables:
            raise ValueError(
                "SQLite source is missing expected tables: "
                + ", ".join(missing_tables)
            )

        with database_session() as destination:
            for table in TABLE_ORDER:
                quoted_table = _quote_identifier(table)
                source_columns = {
                    row["name"]
                    for row in source.execute(f"PRAGMA table_info({quoted_table})")
                }
                destination_columns = {
                    row["column_name"]
                    for row in destination.execute(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema = current_schema() AND table_name = ?
                        """,
                        (table,),
                    ).fetchall()
                }
                columns = sorted(source_columns & destination_columns)
                key_columns = TABLE_KEYS[table]
                if not set(key_columns).issubset(columns):
                    raise ValueError(
                        f"Could not identify the primary key for source table {table!r}."
                    )

                quoted_columns = ", ".join(_quote_identifier(name) for name in columns)
                placeholders = ", ".join("?" for _ in columns)
                conflict_columns = ", ".join(
                    _quote_identifier(name) for name in key_columns
                )
                update_columns = [
                    name for name in columns if name not in key_columns
                ]
                conflict_action = (
                    "DO UPDATE SET "
                    + ", ".join(
                        f"{_quote_identifier(name)} = EXCLUDED.{_quote_identifier(name)}"
                        for name in update_columns
                    )
                    if update_columns
                    else "DO NOTHING"
                )
                insert_sql = (
                    f"INSERT INTO {quoted_table} ({quoted_columns}) "
                    f"VALUES ({placeholders}) ON CONFLICT ({conflict_columns}) "
                    f"{conflict_action}"
                )
                order_by = (
                    " ORDER BY id"
                    if table in ("events", "alerts")
                    else ""
                )
                rows = source.execute(
                    f"SELECT {quoted_columns} FROM {quoted_table}{order_by}"
                )
                imported[table] = 0
                for row in rows:
                    destination.execute(insert_sql, tuple(row))
                    imported[table] += 1

            for table in ("events", "alerts"):
                destination.execute(
                    f"""
                    SELECT setval(
                        pg_get_serial_sequence('{table}', 'id'),
                        COALESCE(MAX(id), 1),
                        COUNT(*) > 0
                    )
                    FROM {_quote_identifier(table)}
                    """
                )
    finally:
        source.close()

    return {
        "source_database": str(sqlite_path.resolve()),
        "rows_processed": imported,
        "result": "SQLite rows imported with primary-key upserts; source left unchanged.",
    }


if __name__ == "__main__":
    source_path = Path(os.getenv("SQLITE_SOURCE_PATH", str(DEFAULT_SQLITE_PATH)))
    print(json.dumps(migrate(source_path), indent=2))
