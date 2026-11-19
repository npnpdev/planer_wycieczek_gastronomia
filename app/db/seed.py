"""Idempotentny seed danych pod pokaz (Warszawa).

Uruchomienie ręczne:  python -m app.db.seed
Wielokrotne uruchomienie niczego nie dubluje – rekordy są upsertowane po id.

Konwencje:
  * id lokalu = locationId w Transporcie (rest-01 … rest-04); o dojazd
    pytamy Transport (para start → rest-NN), a on zwraca czas i koszt,
    które odsyłamy Planerowi razem z posiłkiem,
  * ceny w groszach, czasy w minutach, godziny "HH:MM",
  * diety to wartości DietType; posiłek bez ograniczeń ma [STANDARD].
"""

from pathlib import Path
import json

from app.db.database import get_connection, init_db
from app.schemas import DietType

CITY = "Warszawa"

V, VG, GF, STD = DietType.VEGETARIAN, DietType.VEGAN, DietType.GLUTEN_FREE, DietType.STANDARD

PLACES: list[dict] = [
    {
        "id": "rest-01",
        "name": "Bar Mleczny Familijny",
        "address": "ul. Nowy Świat 39",
        "lat": 52.2337, "lng": 21.0187,
        "visit_duration_minutes": 30,
        "opening_from": "08:00", "opening_to": "19:00",
    },
    {
        "id": "rest-02",
        "name": "Zielona Miska",
        "address": "ul. Chmielna 10",
        "lat": 52.2295, "lng": 21.0124,
        "visit_duration_minutes": 45,
        "opening_from": "10:00", "opening_to": "21:00",
    },
    {
        "id": "rest-03",
        "name": "Trattoria pod Łazienkami",
        "address": "ul. Agrykola 1",
        "lat": 52.2189, "lng": 21.0301,
        "visit_duration_minutes": 60,
        "opening_from": "11:00", "opening_to": "22:00",
    },
    {
        # Droga i otwierana wieczorem – do pokazu "brak pasującego planu".
        "id": "rest-04",
        "name": "Restauracja Belweder",
        "address": "ul. Belwederska 52",
        "lat": 52.2143, "lng": 21.0264,
        "visit_duration_minutes": 150,
        "opening_from": "17:00", "opening_to": "23:00",
    },
]

MEALS: list[dict] = [
    # rest-01 – Bar Mleczny Familijny
    {"id": "familijny-zupa-pomidorowa", "place_id": "rest-01",
     "name": "Zupa pomidorowa", "price_groszy": 900, "diets": [V]},
    {"id": "familijny-pierogi-ruskie", "place_id": "rest-01",
     "name": "Pierogi ruskie", "price_groszy": 1800, "diets": [V]},
    {"id": "familijny-schabowy", "place_id": "rest-01",
     "name": "Kotlet schabowy z ziemniakami", "price_groszy": 2600, "diets": [STD]},
    # rest-02 – Zielona Miska
    {"id": "zielona-bowl-falafel", "place_id": "rest-02",
     "name": "Bowl z falafelem", "price_groszy": 3200, "diets": [VG, V]},
    {"id": "zielona-curry", "place_id": "rest-02",
     "name": "Curry z ciecierzycą i ryżem", "price_groszy": 3600, "diets": [VG, V, GF]},
    # rest-03 – Trattoria pod Łazienkami
    {"id": "trattoria-margherita", "place_id": "rest-03",
     "name": "Pizza Margherita", "price_groszy": 3900, "diets": [V]},
    {"id": "trattoria-carbonara", "place_id": "rest-03",
     "name": "Spaghetti carbonara", "price_groszy": 4500, "diets": [STD]},
    {"id": "trattoria-risotto", "place_id": "rest-03",
     "name": "Risotto z grzybami", "price_groszy": 4800, "diets": [V, GF]},
    # rest-04 – Restauracja Belweder
    {"id": "belweder-menu-wege", "place_id": "rest-04",
     "name": "Menu degustacyjne wege", "price_groszy": 28000, "diets": [V]},
    {"id": "belweder-menu-degustacyjne", "place_id": "rest-04",
     "name": "Menu degustacyjne (7 dań)", "price_groszy": 32000, "diets": [STD]},
]


def seed_database(db_path: str | Path) -> None:
    """Idempotentnie zasila bazę startowymi lokalami i posiłkami do pokazu."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        with conn:
            conn.executemany(
                """INSERT INTO places
                       (id, name, location_id, city, address, lat, lng,
                        visit_duration_minutes, opening_from, opening_to)
                   VALUES (:id, :name, :id, :city, :address, :lat, :lng,
                           :visit_duration_minutes, :opening_from, :opening_to)
                   ON CONFLICT (id) DO UPDATE SET
                       name = excluded.name, location_id = excluded.location_id,
                       city = excluded.city, address = excluded.address,
                       lat = excluded.lat, lng = excluded.lng,
                       visit_duration_minutes = excluded.visit_duration_minutes,
                       opening_from = excluded.opening_from, opening_to = excluded.opening_to""",
                [{**p, "city": CITY} for p in PLACES],
            )
            conn.executemany(
                """INSERT INTO meals (id, place_id, name, price_groszy, diets)
                   VALUES (:id, :place_id, :name, :price_groszy, :diets)
                   ON CONFLICT (id) DO UPDATE SET
                       place_id = excluded.place_id, name = excluded.name,
                       price_groszy = excluded.price_groszy, diets = excluded.diets""",
                [
                    {**m, "diets": json.dumps(sorted(DietType(d).value for d in m["diets"]))}
                    for m in MEALS
                ],
            )
    finally:
        conn.close()


if __name__ == "__main__":
    from app.config import get_settings

    path = get_settings().db_path
    seed_database(path)
    print(f"Seed OK: {len(PLACES)} places, {len(MEALS)} meals -> {path}")
