"""Połączenie z SQLite i tworzenie schematu bazy Gastronomii.

Baza działa bez konfiguracji: ścieżkę podaje ``Settings.db_path``
(domyślnie ``gastronomia.db``).
"""

from pathlib import Path
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS places (
    id                      TEXT PRIMARY KEY,        -- np. "rest-01"
    name                    TEXT NOT NULL,
    location_id             TEXT NOT NULL UNIQUE,    -- locationId w Transporcie (= id)
    city                    TEXT NOT NULL,
    address                 TEXT,
    lat                     REAL NOT NULL,
    lng                     REAL NOT NULL,
    visit_duration_minutes  INTEGER NOT NULL CHECK (visit_duration_minutes > 0),
    opening_from            TEXT,                    -- "HH:MM", dla Planera (poza schemas.Place)
    opening_to              TEXT                     -- "HH:MM"
);

CREATE TABLE IF NOT EXISTS meals (
    id            TEXT PRIMARY KEY,
    place_id      TEXT NOT NULL REFERENCES places(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    price_groszy  INTEGER NOT NULL CHECK (price_groszy >= 0),
    diets         TEXT NOT NULL DEFAULT '[]'         -- tablica JSON wartości DietType
);

CREATE INDEX IF NOT EXISTS idx_meals_place ON meals(place_id);

CREATE TABLE IF NOT EXISTS transport_cache (
    from_location_id  TEXT NOT NULL,
    to_location_id    TEXT NOT NULL,
    transport_mode    TEXT NOT NULL,                 -- wartość TransportMode
    available         INTEGER NOT NULL CHECK (available IN (0, 1)),
    distance_meters   INTEGER,
    duration_minutes  INTEGER,
    price_groszy      INTEGER,
    updated_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    PRIMARY KEY (from_location_id, to_location_id, transport_mode)
);
"""


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    """Tworzy i konfiguruje połączenie SQLite (row_factory=sqlite3.Row, foreign_keys=ON)."""
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: str | Path) -> None:
    """Inicjalizuje schemat bazy SQLite z trzema tabelami: places, meals, transport_cache."""
    conn = get_connection(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
