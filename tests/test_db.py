import re

import pytest

from app.db.database import get_connection, init_db
from app.db.repository import GastronomyRepository
from app.db.seed import MEALS, PLACES, seed_database
from app.schemas import DietType, Place, TransportMode, TransportRoute


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    seed_database(path)
    return path


@pytest.fixture
def repo(db_path):
    return GastronomyRepository(db_path)


def _count(db_path, table):
    conn = get_connection(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def route(to_id, mode=TransportMode.WALK, available=True, minutes=10, price=0, dist=800,
          from_id="start"):
    return TransportRoute(
        from_location_id=from_id, to_location_id=to_id, transport_mode=mode,
        available=available,
        duration_minutes=minutes if available else None,
        price_groszy=price if available else None,
        distance_meters=dist if available else None,
    )


# ---------------------------------------------------------------- schemat i seed

def test_init_creates_three_tables(tmp_path):
    path = tmp_path / "schema.db"
    init_db(path)
    init_db(path)  # ponowne wywołanie nie psuje bazy
    conn = get_connection(path)
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert {"places", "meals", "transport_cache"} <= names


def test_connection_settings(tmp_path):
    conn = get_connection(tmp_path / "c.db")
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("SELECT 1 AS x").fetchone()["x"] == 1
    conn.close()


def test_seed_is_idempotent(db_path):
    seed_database(db_path)
    seed_database(db_path)
    assert _count(db_path, "places") == len(PLACES)
    assert _count(db_path, "meals") == len(MEALS)


def test_seed_works_on_fresh_file(tmp_path):
    path = tmp_path / "fresh.db"
    seed_database(path)  # bez wcześniejszego init_db
    assert len(GastronomyRepository(path).get_all_places()) == len(PLACES)


def test_place_ids_match_transport(repo):
    ids = [p.id for p in repo.get_all_places()]
    assert ids == [f"rest-{n:02d}" for n in range(1, len(PLACES) + 1)]
    for p in repo.get_all_places():
        assert p.location_id == p.id
        assert re.fullmatch(r"rest-\d{2}", p.location_id)


def test_seed_data_consistent(repo):
    for p in repo.get_all_places():
        assert isinstance(p, Place)
        assert p.city == "Warszawa" and p.address
        assert 52.0 < p.coordinates.lat < 52.4 and 20.8 < p.coordinates.lng < 21.3
        assert p.visit_duration_minutes > 0
        assert p.meals, f"lokal {p.id} bez posiłków"
        for m in p.meals:
            assert m.place_id == p.id
            assert m.price_groszy > 0 and m.diets
            assert all(isinstance(d, DietType) for d in m.diets)


def test_opening_hours_stored(db_path):
    conn = get_connection(db_path)
    row = conn.execute("SELECT opening_from, opening_to FROM places WHERE id='rest-04'").fetchone()
    conn.close()
    assert (row["opening_from"], row["opening_to"]) == ("17:00", "23:00")


# ---------------------------------------------------------------- lokale

def test_get_all_places_with_meals(repo):
    places = repo.get_all_places()
    assert len(places) == len(PLACES)
    assert sum(len(p.meals) for p in places) == len(MEALS)
    prices = [m.price_groszy for m in places[0].meals]
    assert prices == sorted(prices)


def test_get_place_by_id(repo):
    p = repo.get_place_by_id("rest-02")
    assert p is not None and p.name == "Zielona Miska" and len(p.meals) == 2
    assert repo.get_place_by_id("nie-ma-takiego") is None


def test_place_serializes_to_camel_case(repo):
    data = repo.get_place_by_id("rest-01").model_dump(by_alias=True)
    assert {"locationId", "visitDurationMinutes", "coordinates", "meals"} <= data.keys()
    assert "priceGroszy" in data["meals"][0]


# ---------------------------------------------------------------- filtrowanie

def test_find_without_filters_returns_everything(repo):
    assert [p.id for p in repo.find_places_with_meals()] == [p.id for p in repo.get_all_places()]


def test_find_by_diet(repo):
    places = repo.find_places_with_meals(diet=DietType.VEGAN)
    assert [p.id for p in places] == ["rest-02"]
    assert all(DietType.VEGAN in m.diets for p in places for m in p.meals)


def test_find_by_diet_returns_only_matching_meals(repo):
    places = {p.id: p for p in repo.find_places_with_meals(diet=DietType.GLUTEN_FREE)}
    assert set(places) == {"rest-02", "rest-03"}
    assert [m.id for m in places["rest-03"].meals] == ["trattoria-risotto"]


def test_find_by_max_price(repo):
    places = repo.find_places_with_meals(max_meal_price_groszy=1800)
    assert [p.id for p in places] == ["rest-01"]
    assert {m.id for m in places[0].meals} == {"familijny-zupa-pomidorowa", "familijny-pierogi-ruskie"}


def test_find_by_diet_and_price(repo):
    places = repo.find_places_with_meals(diet=DietType.VEGETARIAN, max_meal_price_groszy=3500)
    meals = [m for p in places for m in p.meals]
    assert meals and all(m.price_groszy <= 3500 and DietType.VEGETARIAN in m.diets for m in meals)
    assert "rest-04" not in {p.id for p in places}


def test_find_no_match(repo):
    assert repo.find_places_with_meals(max_meal_price_groszy=100) == []
    assert repo.find_places_with_meals(diet=DietType.VEGAN, max_meal_price_groszy=1000) == []


def test_find_standard_diet(repo):
    places = repo.find_places_with_meals(diet=DietType.STANDARD)
    assert {p.id for p in places} == {"rest-01", "rest-03", "rest-04"}


# ---------------------------------------------------------------- cache tras

def test_cache_miss(repo):
    assert repo.get_cached_route("start", "rest-01", TransportMode.WALK) is None
    assert repo.get_cached_routes("start", ["rest-01"], TransportMode.WALK) == {}


def test_cache_upsert_and_get(repo):
    repo.upsert_cached_routes([
        route("rest-01", minutes=9, price=0, dist=700),
        route("rest-04", available=False),
    ])
    ok = repo.get_cached_route("start", "rest-01", TransportMode.WALK)
    assert isinstance(ok, TransportRoute)
    assert ok.available and ok.duration_minutes == 9 and ok.price_groszy == 0
    assert ok.distance_meters == 700 and ok.transport_mode == TransportMode.WALK

    none = repo.get_cached_route("start", "rest-04", TransportMode.WALK)
    assert none.available is False
    assert none.duration_minutes is None and none.price_groszy is None

    assert repo.get_cached_route("start", "rest-01", TransportMode.TAXI) is None


def test_cache_upsert_overwrites(repo, db_path):
    repo.upsert_cached_routes([route("rest-02", TransportMode.PUBLIC_TRANSPORT, minutes=20, price=480)])
    repo.upsert_cached_routes([route("rest-02", TransportMode.PUBLIC_TRANSPORT, minutes=11, price=480)])
    r = repo.get_cached_route("start", "rest-02", TransportMode.PUBLIC_TRANSPORT)
    assert r.duration_minutes == 11
    assert _count(db_path, "transport_cache") == 1


def test_cache_upsert_ok_to_unavailable(repo):
    repo.upsert_cached_routes([route("rest-03", minutes=34)])
    repo.upsert_cached_routes([route("rest-03", available=False)])
    r = repo.get_cached_route("start", "rest-03", TransportMode.WALK)
    assert r.available is False and r.duration_minutes is None


def test_cache_upsert_empty_list(repo, db_path):
    repo.upsert_cached_routes([])
    assert _count(db_path, "transport_cache") == 0


def test_get_cached_routes_batch(repo):
    repo.upsert_cached_routes([
        route("rest-01", minutes=9),
        route("rest-02", minutes=22),
        route("rest-02", TransportMode.TAXI, minutes=7, price=1530),
        route("rest-03", from_id="attr-01", minutes=5),
    ])
    found = repo.get_cached_routes("start", ["rest-01", "rest-02", "rest-03", "brak"], TransportMode.WALK)
    assert set(found) == {"rest-01", "rest-02"}
    assert found["rest-02"].duration_minutes == 22
    assert found["rest-01"].from_cache is False  # flagę ustawia RouteService
