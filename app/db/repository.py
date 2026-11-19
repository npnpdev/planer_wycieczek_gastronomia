"""Dostęp do danych Gastronomii. Jedyne miejsce z SQL-em.

Zwraca proste dataclassy w snake_case – mapowanie na JSON (camelCase)
robi warstwa API.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True)
class Place:
    id: str
    location_id: str
    name: str
    city: str
    lat: float
    lng: float
    cuisine: str
    description: str
    opening_from: str
    opening_to: str


@dataclass(frozen=True)
class Meal:
    id: str
    place_id: str
    name: str
    diets: list[str] = field(default_factory=list)
    price_groszy: int = 0
    visit_minutes: int = 0


@dataclass(frozen=True)
class MealWithPlace:
    meal: Meal
    place: Place


@dataclass(frozen=True)
class CachedRoute:
    from_location_id: str
    to_location_id: str
    mode: str
    available: bool                 # False = Transport mówi, że nie ma połączenia
    duration_minutes: int | None
    cost_groszy: int | None
    updated_at: str | None = None


# ---------------------------------------------------------------- mapowanie

def _place(row: sqlite3.Row, prefix: str = "") -> Place:
    return Place(
        id=row[f"{prefix}id"],
        location_id=row[f"{prefix}location_id"],
        name=row[f"{prefix}name"],
        city=row[f"{prefix}city"],
        lat=row[f"{prefix}lat"],
        lng=row[f"{prefix}lng"],
        cuisine=row[f"{prefix}cuisine"],
        description=row[f"{prefix}description"],
        opening_from=row[f"{prefix}opening_from"],
        opening_to=row[f"{prefix}opening_to"],
    )


def _meal(row: sqlite3.Row, prefix: str = "") -> Meal:
    return Meal(
        id=row[f"{prefix}id"],
        place_id=row[f"{prefix}place_id"],
        name=row[f"{prefix}name"],
        diets=json.loads(row[f"{prefix}diets"]),
        price_groszy=row[f"{prefix}price_groszy"],
        visit_minutes=row[f"{prefix}visit_minutes"],
    )


def _route(row: sqlite3.Row) -> CachedRoute:
    return CachedRoute(
        from_location_id=row["from_location_id"],
        to_location_id=row["to_location_id"],
        mode=row["mode"],
        available=bool(row["available"]),
        duration_minutes=row["duration_minutes"],
        cost_groszy=row["cost_groszy"],
        updated_at=row["updated_at"],
    )


# ---------------------------------------------------------------- lokale

def get_places(conn: sqlite3.Connection) -> list[Place]:
    rows = conn.execute("SELECT * FROM places ORDER BY id").fetchall()
    return [_place(r) for r in rows]


def get_place(conn: sqlite3.Connection, place_id: str) -> Place | None:
    row = conn.execute("SELECT * FROM places WHERE id = ?", (place_id,)).fetchone()
    return _place(row) if row else None


def get_meals_for_place(conn: sqlite3.Connection, place_id: str) -> list[Meal]:
    rows = conn.execute(
        "SELECT * FROM meals WHERE place_id = ? ORDER BY price_groszy, id", (place_id,)
    ).fetchall()
    return [_meal(r) for r in rows]


# ---------------------------------------------------------------- posiłki

_MEAL_WITH_PLACE_SQL = """
SELECT
    m.id AS m_id, m.place_id AS m_place_id, m.name AS m_name, m.diets AS m_diets,
    m.price_groszy AS m_price_groszy, m.visit_minutes AS m_visit_minutes,
    p.id AS p_id, p.location_id AS p_location_id, p.name AS p_name, p.city AS p_city,
    p.lat AS p_lat, p.lng AS p_lng, p.cuisine AS p_cuisine, p.description AS p_description,
    p.opening_from AS p_opening_from, p.opening_to AS p_opening_to
FROM meals m
JOIN places p ON p.id = m.place_id
"""


def find_meals(
    conn: sqlite3.Connection,
    diets: Iterable[str] | None = None,
    max_price_groszy: int | None = None,
) -> list[MealWithPlace]:
    """Posiłki spełniające WSZYSTKIE podane diety i nie droższe niż limit.

    ``diets=None`` lub pusta lista = bez ograniczeń dietetycznych.
    Wynik posortowany rosnąco po cenie (potem po id – deterministycznie).
    """
    where: list[str] = []
    params: list[object] = []

    for diet in sorted(set(diets or [])):
        where.append("EXISTS (SELECT 1 FROM json_each(m.diets) WHERE value = ?)")
        params.append(diet)

    if max_price_groszy is not None:
        where.append("m.price_groszy <= ?")
        params.append(max_price_groszy)

    sql = _MEAL_WITH_PLACE_SQL
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY m.price_groszy, m.id"

    rows = conn.execute(sql, params).fetchall()
    return [MealWithPlace(meal=_meal(r, "m_"), place=_place(r, "p_")) for r in rows]


def get_diets(conn: sqlite3.Connection) -> list[str]:
    """Wszystkie diety występujące w posiłkach (pod GET /api/gastronomy/diets)."""
    rows = conn.execute(
        "SELECT DISTINCT j.value AS diet FROM meals m, json_each(m.diets) j ORDER BY diet"
    ).fetchall()
    return [r["diet"] for r in rows]


# ---------------------------------------------------------------- cache tras

def get_cached_route(
    conn: sqlite3.Connection, from_location_id: str, to_location_id: str, mode: str
) -> CachedRoute | None:
    row = conn.execute(
        """SELECT * FROM transport_cache
           WHERE from_location_id = ? AND to_location_id = ? AND mode = ?""",
        (from_location_id, to_location_id, mode),
    ).fetchone()
    return _route(row) if row else None


def get_cached_routes(
    conn: sqlite3.Connection, from_location_id: str, to_location_ids: Iterable[str], mode: str
) -> dict[str, CachedRoute]:
    """Wsadowo: {to_location_id: CachedRoute} – tylko te pary, które są w cache."""
    ids = list(dict.fromkeys(to_location_ids))
    if not ids:
        return {}
    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(
        f"""SELECT * FROM transport_cache
            WHERE from_location_id = ? AND mode = ? AND to_location_id IN ({placeholders})""",
        (from_location_id, mode, *ids),
    ).fetchall()
    return {r["to_location_id"]: _route(r) for r in rows}


def upsert_cached_routes(conn: sqlite3.Connection, routes: Iterable[CachedRoute]) -> int:
    """Zapisuje/odświeża trasy w cache. Zwraca liczbę zapisanych wierszy."""
    data = [
        (
            r.from_location_id,
            r.to_location_id,
            r.mode,
            int(r.available),
            r.duration_minutes if r.available else None,
            r.cost_groszy if r.available else None,
        )
        for r in routes
    ]
    with conn:
        conn.executemany(
            """INSERT INTO transport_cache
                   (from_location_id, to_location_id, mode, available, duration_minutes, cost_groszy)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT (from_location_id, to_location_id, mode) DO UPDATE SET
                   available        = excluded.available,
                   duration_minutes = excluded.duration_minutes,
                   cost_groszy      = excluded.cost_groszy,
                   updated_at       = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')""",
            data,
        )
    return len(data)
