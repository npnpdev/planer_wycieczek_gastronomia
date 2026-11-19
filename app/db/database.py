"""Połączenie z SQLite i tworzenie schematu.

Baza działa bez konfiguracji: domyślnie plik ``gastronomia.db`` w katalogu
roboczym. Ścieżkę można zmienić zmienną środowiskową ``GASTRO_DB_PATH``
(np. ``:memory:`` w testach).
"""

from __future__ import annotations

import os
import sqlite3

DEFAULT_DB_PATH = "gastronomia.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS places (
    id            TEXT PRIMARY KEY,           -- "rest-NN", np. "rest-01" (jak w Transporcie)
    location_id   TEXT NOT NULL UNIQUE,       -- wspólny locationId (ten sam co w Transporcie)
    name          TEXT NOT NULL,
    city          TEXT NOT NULL,
    lat           REAL NOT NULL,
    lng           REAL NOT NULL,
    cuisine       TEXT NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    opening_from  TEXT NOT NULL,              -- "HH:MM"
    opening_to    TEXT NOT NULL               -- "HH:MM"
);

CREATE TABLE IF NOT EXISTS meals (
    id             TEXT PRIMARY KEY,
    place_id       TEXT NOT NULL REFERENCES places(id) ON DELETE CASCADE,
    name           TEXT NOT NULL,
    diets          TEXT NOT NULL DEFAULT '[]', -- tablica JSON, np. ["vegan","gluten_free"]
    price_groszy   INTEGER NOT NULL CHECK (price_groszy >= 0),
    visit_minutes  INTEGER NOT NULL CHECK (visit_minutes > 0)
);

CREATE INDEX IF NOT EXISTS idx_meals_place ON meals(place_id);
CREATE INDEX IF NOT EXISTS idx_meals_price ON meals(price_groszy);

CREATE TABLE IF NOT EXISTS transport_cache (
    from_location_id  TEXT NOT NULL,
    to_location_id    TEXT NOT NULL,
    mode              TEXT NOT NULL,          -- WALK | PUBLIC_TRANSPORT | CAR (jak w Transporcie)
    available         INTEGER NOT NULL CHECK (available IN (0, 1)), -- 0 = brak połączenia
    duration_minutes  INTEGER,                -- NULL gdy available = 0
    cost_groszy       INTEGER,                -- NULL gdy available = 0
    updated_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    PRIMARY KEY (from_location_id, to_location_id, mode)
);
"""


def get_db_path() -> str:
    return os.getenv("GASTRO_DB_PATH", DEFAULT_DB_PATH)


def get_connection(path: str | None = None) -> sqlite3.Connection:
    """Otwiera połączenie z wierszami dostępnymi po nazwie kolumny.

    ``check_same_thread=False`` – FastAPI może wołać repozytorium z różnych
    wątków puli; zapisy są krótkie i chronione transakcjami.
    """
    conn = sqlite3.connect(path or get_db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Tworzy 3 tabele (places, meals, transport_cache), jeśli nie istnieją."""
    with conn:
        conn.executescript(SCHEMA)
