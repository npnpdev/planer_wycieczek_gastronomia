from pathlib import Path
import sqlite3


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    """Tworzy i konfiguruje połączenie SQLite (row_factory=sqlite3.Row, foreign_keys=ON)."""
    raise NotImplementedError("Implement on branch feat/db-and-seed")


def init_db(db_path: str | Path) -> None:
    """Inicjalizuje schemat bazy SQLite z trzema tabelami:

    1. `places`: id, name, location_id, city, address, lat, lng, visit_duration_minutes.
    2. `meals`: id, place_id (FK -> places.id), name, price_groszy, diets (np. JSON).
    3. `transport_cache`: (from_location_id, to_location_id, transport_mode) PK,
       available, distance_meters, duration_minutes, price_groszy, updated_at.
    """
    raise NotImplementedError("Implement on branch feat/db-and-seed")
