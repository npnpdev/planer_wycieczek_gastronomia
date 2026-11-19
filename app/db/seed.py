"""Idempotentny seed danych pod pokaz (Warszawa).

Uruchomienie ręczne:  py -m app.db.seed
Wielokrotne uruchomienie niczego nie dubluje – rekordy są upsertowane po id.

Konwencje wspólne dla projektu:
  * id lokalu = locationId w formacie rest-NN (rest-01, rest-02, ...) – tak jak w Transporcie;
    o dojazd pytamy Transport (para start → rest-NN), a on zwraca czas i koszt,
    które odsyłamy Planerowi razem z posiłkiem,
  * ceny w groszach, czasy w minutach, godziny "HH:MM".

Diety: vegetarian, vegan, gluten_free, lactose_free.
Posiłek bez tagów = zwykły (pasuje tylko, gdy klient nie podał diety).
"""

from __future__ import annotations

import json
import sqlite3

from app.db.database import get_connection, init_db

CITY = "Warszawa"

PLACES: list[dict] = [
    {
        "id": "rest-01",
        "name": "Bar Mleczny Familijny",
        "lat": 52.2337, "lng": 21.0187,
        "cuisine": "polska",
        "description": "Klasyczny bar mleczny – tanio i szybko.",
        "opening_from": "08:00", "opening_to": "19:00",
    },
    {
        "id": "rest-02",
        "name": "Zielona Miska",
        "lat": 52.2295, "lng": 21.0124,
        "cuisine": "wegańska",
        "description": "Kuchnia roślinna, bowle i zupy.",
        "opening_from": "10:00", "opening_to": "21:00",
    },
    {
        "id": "rest-03",
        "name": "Trattoria pod Łazienkami",
        "lat": 52.2189, "lng": 21.0301,
        "cuisine": "włoska",
        "description": "Pizza z pieca i domowe makarony.",
        "opening_from": "11:00", "opening_to": "22:00",
    },
    {
        # Droga i otwierana wieczorem – do pokazu "brak pasującego planu".
        "id": "rest-04",
        "name": "Restauracja Belweder",
        "lat": 52.2143, "lng": 21.0264,
        "cuisine": "fine dining",
        "description": "Menu degustacyjne. Otwarte tylko wieczorem.",
        "opening_from": "17:00", "opening_to": "23:00",
    },
]

MEALS: list[dict] = [
    # rest-01 – Bar Mleczny Familijny
    {"id": "familijny-pierogi-ruskie", "place_id": "rest-01",
     "name": "Pierogi ruskie", "diets": ["vegetarian"], "price_groszy": 1800, "visit_minutes": 30},
    {"id": "familijny-schabowy", "place_id": "rest-01",
     "name": "Kotlet schabowy z ziemniakami", "diets": [], "price_groszy": 2600, "visit_minutes": 40},
    {"id": "familijny-zupa-pomidorowa", "place_id": "rest-01",
     "name": "Zupa pomidorowa", "diets": ["vegetarian", "lactose_free"], "price_groszy": 900, "visit_minutes": 20},
    # rest-02 – Zielona Miska
    {"id": "zielona-bowl-falafel", "place_id": "rest-02",
     "name": "Bowl z falafelem", "diets": ["vegan", "vegetarian", "lactose_free"], "price_groszy": 3200, "visit_minutes": 45},
    {"id": "zielona-curry", "place_id": "rest-02",
     "name": "Curry z ciecierzycą i ryżem", "diets": ["vegan", "vegetarian", "gluten_free", "lactose_free"],
     "price_groszy": 3600, "visit_minutes": 45},
    # rest-03 – Trattoria pod Łazienkami
    {"id": "trattoria-margherita", "place_id": "rest-03",
     "name": "Pizza Margherita", "diets": ["vegetarian"], "price_groszy": 3900, "visit_minutes": 60},
    {"id": "trattoria-carbonara", "place_id": "rest-03",
     "name": "Spaghetti carbonara", "diets": [], "price_groszy": 4500, "visit_minutes": 60},
    {"id": "trattoria-risotto", "place_id": "rest-03",
     "name": "Risotto z grzybami", "diets": ["vegetarian", "gluten_free"], "price_groszy": 4800, "visit_minutes": 60},
    # rest-04 – Restauracja Belweder
    {"id": "belweder-menu-degustacyjne", "place_id": "rest-04",
     "name": "Menu degustacyjne (7 dań)", "diets": [], "price_groszy": 32000, "visit_minutes": 150},
    {"id": "belweder-menu-wege", "place_id": "rest-04",
     "name": "Menu degustacyjne wege", "diets": ["vegetarian"], "price_groszy": 28000, "visit_minutes": 150},
]


def seed(conn: sqlite3.Connection) -> None:
    """Upsertuje lokale i posiłki. Bezpieczne do wielokrotnego wywołania."""
    with conn:
        conn.executemany(
            """INSERT INTO places
                   (id, location_id, name, city, lat, lng, cuisine, description, opening_from, opening_to)
               VALUES (:id, :id, :name, :city, :lat, :lng, :cuisine, :description, :opening_from, :opening_to)
               ON CONFLICT (id) DO UPDATE SET
                   location_id = excluded.location_id, name = excluded.name, city = excluded.city,
                   lat = excluded.lat, lng = excluded.lng, cuisine = excluded.cuisine,
                   description = excluded.description,
                   opening_from = excluded.opening_from, opening_to = excluded.opening_to""",
            [{**p, "city": CITY} for p in PLACES],
        )
        conn.executemany(
            """INSERT INTO meals (id, place_id, name, diets, price_groszy, visit_minutes)
               VALUES (:id, :place_id, :name, :diets, :price_groszy, :visit_minutes)
               ON CONFLICT (id) DO UPDATE SET
                   place_id = excluded.place_id, name = excluded.name, diets = excluded.diets,
                   price_groszy = excluded.price_groszy, visit_minutes = excluded.visit_minutes""",
            [{**m, "diets": json.dumps(sorted(m["diets"]))} for m in MEALS],
        )


def main() -> None:
    conn = get_connection()
    init_db(conn)
    seed(conn)
    places = conn.execute("SELECT COUNT(*) FROM places").fetchone()[0]
    meals = conn.execute("SELECT COUNT(*) FROM meals").fetchone()[0]
    print(f"Seed OK: {places} places, {meals} meals")  # ASCII – konsola Windows (cp1252)
    conn.close()


if __name__ == "__main__":
    main()
