import pytest

from app.db import repository as repo
from app.db.database import get_connection, init_db
from app.db.seed import MEALS, PLACES, seed


@pytest.fixture
def conn():
    c = get_connection(":memory:")
    init_db(c)
    seed(c)
    yield c
    c.close()


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_init_creates_three_tables():
    c = get_connection(":memory:")
    init_db(c)
    names = {r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"places", "meals", "transport_cache"} <= names


def test_seed_is_idempotent(conn):
    seed(conn)
    seed(conn)
    assert _count(conn, "places") == len(PLACES)
    assert _count(conn, "meals") == len(MEALS)


def test_seed_data_consistent(conn):
    for p in repo.get_places(conn):
        assert p.location_id == p.id
        assert 52.0 < p.lat < 52.4 and 20.8 < p.lng < 21.3
        assert repo.get_meals_for_place(conn, p.id), f"lokal {p.id} bez posiłków"
    for m, _ in ((mw.meal, mw.place) for mw in repo.find_meals(conn)):
        assert isinstance(m.price_groszy, int) and m.price_groszy > 0
        assert isinstance(m.visit_minutes, int) and m.visit_minutes > 0


def test_get_place(conn):
    p = repo.get_place(conn, "rest-02")
    assert p is not None and p.cuisine == "wegańska" and p.city == "Warszawa"
    assert repo.get_place(conn, "nie-ma-takiego") is None


def test_find_meals_without_filters_sorted_by_price(conn):
    meals = repo.find_meals(conn)
    assert len(meals) == len(MEALS)
    prices = [m.meal.price_groszy for m in meals]
    assert prices == sorted(prices)
    assert meals[0].place.id == meals[0].meal.place_id


def test_find_meals_by_diet(conn):
    vegan = repo.find_meals(conn, diets=["vegan"])
    assert vegan and all("vegan" in m.meal.diets for m in vegan)
    assert {m.place.id for m in vegan} == {"rest-02"}


def test_find_meals_requires_all_diets(conn):
    meals = repo.find_meals(conn, diets=["vegan", "gluten_free"])
    assert [m.meal.id for m in meals] == ["zielona-curry"]


def test_find_meals_by_max_price(conn):
    meals = repo.find_meals(conn, max_price_groszy=1800)
    assert {m.meal.id for m in meals} == {"familijny-zupa-pomidorowa", "familijny-pierogi-ruskie"}


def test_find_meals_diet_and_price(conn):
    meals = repo.find_meals(conn, diets=["vegetarian"], max_price_groszy=3500)
    assert all(m.meal.price_groszy <= 3500 and "vegetarian" in m.meal.diets for m in meals)
    assert "trattoria-margherita" not in {m.meal.id for m in meals}


def test_find_meals_no_match(conn):
    assert repo.find_meals(conn, max_price_groszy=100) == []
    assert repo.find_meals(conn, diets=["keto"]) == []


def test_get_diets(conn):
    assert repo.get_diets(conn) == ["gluten_free", "lactose_free", "vegan", "vegetarian"]


def test_cache_miss(conn):
    assert repo.get_cached_route(conn, "start", "rest-02", "WALK") is None


def test_cache_upsert_and_get(conn):
    n = repo.upsert_cached_routes(conn, [
        repo.CachedRoute("start", "rest-02", "WALK", True, 12, 0),
        repo.CachedRoute("start", "rest-03", "WALK", False, None, None),
    ])
    assert n == 2

    ok = repo.get_cached_route(conn, "start", "rest-02", "WALK")
    assert ok.available and ok.duration_minutes == 12 and ok.cost_groszy == 0
    assert ok.updated_at

    none = repo.get_cached_route(conn, "start", "rest-03", "WALK")
    assert none.available is False and none.duration_minutes is None

    # inny tryb to inny wpis
    assert repo.get_cached_route(conn, "start", "rest-02", "CAR") is None


def test_cache_upsert_overwrites(conn):
    key = ("start", "rest-02", "PUBLIC_TRANSPORT")
    repo.upsert_cached_routes(conn, [repo.CachedRoute(*key, True, 20, 440)])
    repo.upsert_cached_routes(conn, [repo.CachedRoute(*key, True, 15, 340)])
    r = repo.get_cached_route(conn, *key)
    assert (r.duration_minutes, r.cost_groszy) == (15, 340)
    assert _count(conn, "transport_cache") == 1


def test_cache_unavailable_drops_numbers(conn):
    repo.upsert_cached_routes(conn, [repo.CachedRoute("a", "b", "WALK", False, 99, 99)])
    r = repo.get_cached_route(conn, "a", "b", "WALK")
    assert r.duration_minutes is None and r.cost_groszy is None


def test_get_cached_routes_batch(conn):
    repo.upsert_cached_routes(conn, [
        repo.CachedRoute("start", "rest-02", "WALK", True, 10, 0),
        repo.CachedRoute("start", "rest-03", "WALK", True, 14, 0),
        repo.CachedRoute("start", "rest-03", "CAR", True, 5, 1500),
    ])
    found = repo.get_cached_routes(conn, "start", ["rest-02", "rest-03", "brak"], "WALK")
    assert set(found) == {"rest-02", "rest-03"}
    assert found["rest-03"].duration_minutes == 14
    assert repo.get_cached_routes(conn, "start", [], "WALK") == {}


def test_place_ids_match_transport_format(conn):
    import re
    ids = [p.id for p in repo.get_places(conn)]
    assert all(re.fullmatch(r"rest-\d{2}", i) for i in ids), ids
    assert sorted(ids, key=lambda i: int(i[5:])) == [f"rest-{n:02d}" for n in range(1, len(PLACES) + 1)]
