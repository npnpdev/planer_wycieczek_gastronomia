"""Repozytorium SQLite Gastronomii – jedyne miejsce z SQL-em.

Zwraca modele z ``app.schemas`` (Place, Meal, TransportRoute).
Każda metoda otwiera własne, krótkie połączenie, więc instancję można
bezpiecznie tworzyć per żądanie FastAPI.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
import json
import sqlite3

from app.db.database import get_connection
from app.schemas import Coordinates, DietType, Meal, Place, TransportMode, TransportRoute


class GastronomyRepository:
    """Repozytorium SQLite obsługujące lokale, posiłki i cache tras z Transportu."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = db_path

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = get_connection(self.db_path)
        try:
            yield conn
        finally:
            conn.close()

    # ------------------------------------------------------------ mapowanie

    @staticmethod
    def _to_meal(row: sqlite3.Row) -> Meal:
        return Meal(
            id=row["id"],
            place_id=row["place_id"],
            name=row["name"],
            price_groszy=row["price_groszy"],
            diets=[DietType(d) for d in json.loads(row["diets"])],
        )

    @staticmethod
    def _to_place(row: sqlite3.Row, meals: list[Meal]) -> Place:
        return Place(
            id=row["id"],
            name=row["name"],
            location_id=row["location_id"],
            city=row["city"],
            address=row["address"],
            coordinates=Coordinates(lat=row["lat"], lng=row["lng"]),
            visit_duration_minutes=row["visit_duration_minutes"],
            meals=meals,
        )

    @staticmethod
    def _to_route(row: sqlite3.Row) -> TransportRoute:
        return TransportRoute(
            from_location_id=row["from_location_id"],
            to_location_id=row["to_location_id"],
            transport_mode=TransportMode(row["transport_mode"]),
            available=bool(row["available"]),
            distance_meters=row["distance_meters"],
            duration_minutes=row["duration_minutes"],
            price_groszy=row["price_groszy"],
        )

    def _load_places(
        self,
        conn: sqlite3.Connection,
        place_ids: list[str] | None = None,
        diet: DietType | None = None,
        max_meal_price_groszy: int | None = None,
    ) -> list[Place]:
        """Lokale (posortowane po id) z posiłkami spełniającymi filtry.

        Gdy podano jakikolwiek filtr posiłków, lokale bez pasujących posiłków są pomijane.
        """
        place_sql = "SELECT * FROM places"
        place_params: list[object] = []
        if place_ids is not None:
            place_sql += f" WHERE id IN ({','.join('?' * len(place_ids))})"
            place_params.extend(place_ids)
        place_rows = conn.execute(place_sql + " ORDER BY id", place_params).fetchall()

        meal_where: list[str] = []
        meal_params: list[object] = []
        if diet is not None:
            meal_where.append("EXISTS (SELECT 1 FROM json_each(meals.diets) WHERE value = ?)")
            meal_params.append(DietType(diet).value)
        if max_meal_price_groszy is not None:
            meal_where.append("price_groszy <= ?")
            meal_params.append(max_meal_price_groszy)
        meal_sql = "SELECT * FROM meals"
        if meal_where:
            meal_sql += " WHERE " + " AND ".join(meal_where)
        meal_sql += " ORDER BY price_groszy, id"

        meals_by_place: dict[str, list[Meal]] = {}
        for row in conn.execute(meal_sql, meal_params).fetchall():
            meals_by_place.setdefault(row["place_id"], []).append(self._to_meal(row))

        filtering = diet is not None or max_meal_price_groszy is not None
        return [
            self._to_place(row, meals_by_place.get(row["id"], []))
            for row in place_rows
            if not filtering or row["id"] in meals_by_place
        ]

    # ------------------------------------------------------------ lokale

    def get_all_places(self) -> list[Place]:
        """Zwraca wszystkie lokale wraz z ich posiłkami."""
        with self._connect() as conn:
            return self._load_places(conn)

    def get_place_by_id(self, place_id: str) -> Place | None:
        """Zwraca pojedynczy lokal po `place_id` albo `None`, jeśli nie istnieje."""
        with self._connect() as conn:
            places = self._load_places(conn, place_ids=[place_id])
        return places[0] if places else None

    def find_places_with_meals(
        self,
        diet: DietType | None = None,
        max_meal_price_groszy: int | None = None,
    ) -> list[Place]:
        """Zwraca lokale zawierające co najmniej jeden posiłek pasujący do filtrów.

        Lista `meals` każdego lokalu zawiera wyłącznie pasujące posiłki.
        """
        with self._connect() as conn:
            return self._load_places(
                conn, diet=diet, max_meal_price_groszy=max_meal_price_groszy
            )

    # ------------------------------------------------------------ cache tras

    def get_cached_route(
        self,
        from_location_id: str,
        to_location_id: str,
        transport_mode: TransportMode,
    ) -> TransportRoute | None:
        """Odczytuje zapisaną trasę dla pojedynczej pary i trybu transportu."""
        with self._connect() as conn:
            row = conn.execute(
                """SELECT * FROM transport_cache
                   WHERE from_location_id = ? AND to_location_id = ? AND transport_mode = ?""",
                (from_location_id, to_location_id, TransportMode(transport_mode).value),
            ).fetchone()
        return self._to_route(row) if row else None

    def get_cached_routes(
        self,
        from_location_id: str,
        to_location_ids: list[str],
        transport_mode: TransportMode,
    ) -> dict[str, TransportRoute]:
        """Odczytuje zapisane trasy z `from_location_id` do wskazanych lokalizacji."""
        ids = list(dict.fromkeys(to_location_ids))
        if not ids:
            return {}
        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT * FROM transport_cache
                    WHERE from_location_id = ? AND transport_mode = ?
                      AND to_location_id IN ({','.join('?' * len(ids))})""",
                (from_location_id, TransportMode(transport_mode).value, *ids),
            ).fetchall()
        return {row["to_location_id"]: self._to_route(row) for row in rows}

    def upsert_cached_routes(self, routes: list[TransportRoute]) -> None:
        """Zapisuje lub nadpisuje trasy w tabeli `transport_cache`.

        Dla `available=False` liczby nie są zapisywane (NULL).
        """
        data = [
            (
                r.from_location_id,
                r.to_location_id,
                TransportMode(r.transport_mode).value,
                int(r.available),
                r.distance_meters if r.available else None,
                r.duration_minutes if r.available else None,
                r.price_groszy if r.available else None,
            )
            for r in routes
        ]
        if not data:
            return
        with self._connect() as conn:
            conn.executemany(
                """INSERT INTO transport_cache
                       (from_location_id, to_location_id, transport_mode, available,
                        distance_meters, duration_minutes, price_groszy)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (from_location_id, to_location_id, transport_mode) DO UPDATE SET
                       available        = excluded.available,
                       distance_meters  = excluded.distance_meters,
                       duration_minutes = excluded.duration_minutes,
                       price_groszy     = excluded.price_groszy,
                       updated_at       = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')""",
                data,
            )
            conn.commit()
