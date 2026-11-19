from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app.api.routes import _IN_MEMORY_ROUTE_CACHE, get_repository, get_route_service
from app.config import Settings, get_settings
from app.db.repository import GastronomyRepository
from app.exceptions import TransportUnavailableError
from app.main import create_app
from app.schemas import (
    Coordinates,
    DietType,
    Meal,
    Place,
    TransportMode,
    TransportRoute,
)
from app.services.route_service import RouteService


def _sample_places() -> list[Place]:
    return [
        Place(
            id="place-1",
            name="Bistro Zielone",
            location_id="rest-01",
            city="Warszawa",
            address="ul. Mokotowska 12",
            coordinates=Coordinates(lat=52.2245, lng=21.0211),
            visit_duration_minutes=45,
            meals=[
                Meal(
                    id="meal-1a",
                    place_id="place-1",
                    name="Pierogi z mięsem",
                    price_groszy=2500,
                    diets=[DietType.STANDARD],
                ),
                Meal(
                    id="meal-1b",
                    place_id="place-1",
                    name="Miska budda bezglutenowa",
                    price_groszy=3200,
                    diets=[DietType.VEGAN, DietType.GLUTEN_FREE],
                ),
            ],
        ),
        Place(
            id="place-2",
            name="Bar Mleczny Centrum",
            location_id="rest-02",
            city="Warszawa",
            address="ul. Marszałkowska 80",
            coordinates=Coordinates(lat=52.2281, lng=21.0122),
            visit_duration_minutes=30,
            meals=[
                Meal(
                    id="meal-2a",
                    place_id="place-2",
                    name="Krem z dyni i grzanki",
                    price_groszy=2200,
                    diets=[DietType.VEGETARIAN, DietType.VEGAN],
                ),
            ],
        ),
        Place(
            id="place-3",
            name="Karczma Nad Wisłą",
            location_id="rest-04",
            city="Warszawa",
            address="Wybrzeże Kościuszkowskie 5",
            coordinates=Coordinates(lat=52.2410, lng=21.0315),
            visit_duration_minutes=40,
            meals=[
                Meal(
                    id="meal-3a",
                    place_id="place-3",
                    name="Zupa pomidorowa",
                    price_groszy=1800,
                    diets=[DietType.STANDARD, DietType.VEGAN],
                ),
            ],
        ),
    ]


class FakeRepository:
    def __init__(self, places: list[Place] | None = None) -> None:
        self._places = places if places is not None else _sample_places()

    def get_all_places(self) -> list[Place]:
        return list(self._places)

    def get_place_by_id(self, place_id: str) -> Place | None:
        for place in self._places:
            if place.id == place_id:
                return place
        return None

    def find_places_with_meals(
        self,
        diet: DietType | None = None,
        max_meal_price_groszy: int | None = None,
    ) -> list[Place]:
        matched_places: list[Place] = []
        for place in self._places:
            matching_meals = [
                meal
                for meal in place.meals
                if (diet is None or diet in meal.diets)
                and (
                    max_meal_price_groszy is None
                    or meal.price_groszy <= max_meal_price_groszy
                )
            ]
            if matching_meals:
                matched_places.append(place.model_copy(update={"meals": matching_meals}))
        return matched_places


class FakeRouteService:
    def __init__(
        self,
        routes_by_location: dict[str, TransportRoute] | None = None,
        *,
        raise_unavailable: bool = False,
    ) -> None:
        self.routes_by_location = routes_by_location or {}
        self.raise_unavailable = raise_unavailable
        self.calls = 0
        self.last_from_location_id: str | None = None
        self.last_places: list[Place] | None = None
        self.last_transport_mode: TransportMode | None = None
        self.last_from_coordinates: Coordinates | None = None

    async def get_routes_from_attraction(
        self,
        from_location_id: str,
        places: list[Place],
        transport_mode: TransportMode,
        from_coordinates: Coordinates | None = None,
    ) -> dict[str, TransportRoute]:
        self.calls += 1
        self.last_from_location_id = from_location_id
        self.last_places = places
        self.last_transport_mode = transport_mode
        self.last_from_coordinates = from_coordinates
        if self.raise_unavailable:
            raise TransportUnavailableError("Transport service timed out")
        return self.routes_by_location


def _sample_routes(mode: TransportMode = TransportMode.CAR) -> dict[str, TransportRoute]:
    return {
        "rest-01": TransportRoute(
            from_location_id="start",
            to_location_id="rest-01",
            transport_mode=mode,
            available=True,
            distance_meters=1200,
            duration_minutes=5,
            price_groszy=1145,
            from_cache=False,
        ),
        "rest-02": TransportRoute(
            from_location_id="start",
            to_location_id="rest-02",
            transport_mode=mode,
            available=True,
            distance_meters=2100,
            duration_minutes=7,
            price_groszy=1445,
            from_cache=True,
        ),
        "rest-04": TransportRoute(
            from_location_id="start",
            to_location_id="rest-04",
            transport_mode=mode,
            available=False,
            distance_meters=None,
            duration_minutes=None,
            price_groszy=None,
            from_cache=False,
        ),
    }


def _build_test_client(
    repo: FakeRepository | None = None,
    route_service: FakeRouteService | None = None,
    settings: Settings | None = None,
) -> tuple[TestClient, FakeRepository, FakeRouteService]:
    active_repo = repo or FakeRepository()
    active_route_service = route_service or FakeRouteService(_sample_routes())
    app = create_app(init_storage=False)
    app.dependency_overrides[get_repository] = lambda: active_repo
    app.dependency_overrides[get_route_service] = lambda: active_route_service
    if settings is not None:
        app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app), active_repo, active_route_service


def test_health_endpoint() -> None:
    custom_settings = Settings(
        app_name="Gastronomia Test",
        use_mock_transport=True,
    )
    client, _, _ = _build_test_client(settings=custom_settings)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "Gastronomia Test",
        "mockTransport": True,
    }


def test_list_places() -> None:
    client, _, _ = _build_test_client()

    response = client.get("/api/gastronomy/places")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3
    assert data[0]["id"] == "place-1"
    assert data[0]["locationId"] == "rest-01"
    assert data[0]["visitDurationMinutes"] == 45
    assert data[0]["meals"][0]["priceGroszy"] == 2500


def test_get_place_by_id_found() -> None:
    client, _, _ = _build_test_client()

    response = client.get("/api/gastronomy/places/place-2")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "place-2"
    assert body["name"] == "Bar Mleczny Centrum"
    assert body["meals"][0]["id"] == "meal-2a"


def test_get_place_by_id_not_found() -> None:
    client, _, _ = _build_test_client()

    response = client.get("/api/gastronomy/places/unknown-place")

    assert response.status_code == 404
    body = response.json()
    assert body["error"] == "PLACE_NOT_FOUND"
    assert "unknown-place" in body["detail"]


def test_list_diets() -> None:
    client, _, _ = _build_test_client()

    response = client.get("/api/gastronomy/diets")

    assert response.status_code == 200
    assert response.json() == [diet.value for diet in DietType]


def test_proposals_happy_path_excludes_unavailable_and_sorts_deterministically() -> None:
    client, _, route_service = _build_test_client()

    response = client.get(
        "/api/gastronomy/proposals",
        params={"fromLocationId": "start", "transportMode": "CAR"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["fromLocationId"] == "start"
    assert body["transportMode"] == "CAR"
    assert body["diet"] is None

    proposals = body["proposals"]
    assert [item["mealId"] for item in proposals] == ["meal-2a", "meal-1a", "meal-1b"]
    assert all(item["placeId"] != "place-3" for item in proposals)

    first = proposals[0]
    assert first["placeId"] == "place-2"
    assert first["mealPriceGroszy"] == 2200
    assert first["travelPriceGroszy"] == 1445
    assert first["totalPriceGroszy"] == 3645
    assert first["visitDurationMinutes"] == 30
    assert first["travelDurationMinutes"] == 7
    assert first["totalDurationMinutes"] == 37
    assert first["travelDistanceMeters"] == 2100
    assert first["transportFromCache"] is True

    second = proposals[1]
    assert second["totalPriceGroszy"] == 3645
    assert second["totalDurationMinutes"] == 50
    assert second["transportFromCache"] is False
    assert route_service.calls == 1


def test_proposals_supports_snake_case_params_and_coordinates() -> None:
    route_service = FakeRouteService(_sample_routes(TransportMode.WALK))
    client, _, _ = _build_test_client(route_service=route_service)

    response = client.get(
        "/api/gastronomy/proposals",
        params={
            "from_location_id": "attr-01",
            "transport_mode": "walk",
            "max_budget_groszy": 5000,
            "from_lat": 52.2319,
            "from_lng": 21.0222,
        },
    )

    assert response.status_code == 200
    assert route_service.last_from_location_id == "attr-01"
    assert route_service.last_transport_mode == TransportMode.WALK
    assert route_service.last_from_coordinates == Coordinates(lat=52.2319, lng=21.0222)


def test_proposals_filters_by_diet_and_total_budget() -> None:
    client, _, _ = _build_test_client()

    response = client.get(
        "/api/gastronomy/proposals",
        params={
            "fromLocationId": "start",
            "transportMode": "CAR",
            "diet": "vegan",
            "maxBudgetGroszy": 3700,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["diet"] == "VEGAN"
    proposals = body["proposals"]
    assert [item["mealId"] for item in proposals] == ["meal-2a"]
    assert proposals[0]["totalPriceGroszy"] == 3645


def test_proposals_empty_list_skips_transport_call() -> None:
    repo = FakeRepository(places=[])
    route_service = FakeRouteService(_sample_routes())
    client, _, _ = _build_test_client(repo=repo, route_service=route_service)

    response = client.get(
        "/api/gastronomy/proposals",
        params={
            "fromLocationId": "start",
            "transportMode": "WALK",
            "diet": "VEGAN",
        },
    )

    assert response.status_code == 200
    assert response.json()["proposals"] == []
    assert route_service.calls == 0


@pytest.mark.parametrize(
    "params",
    [
        {"transportMode": "WALK"},
        {"fromLocationId": "   ", "transportMode": "WALK"},
        {"fromLocationId": "start"},
        {"fromLocationId": "start", "transportMode": "SPACESHIP"},
        {"fromLocationId": "start", "transportMode": "WALK", "diet": "KETO"},
        {"fromLocationId": "start", "transportMode": "WALK", "diet": "   "},
        {"fromLocationId": "start", "transportMode": "WALK", "maxBudgetGroszy": -1},
        {"fromLocationId": "start", "transportMode": "WALK", "maxBudgetGroszy": "abc"},
        {"fromLocationId": "start", "transportMode": "WALK", "fromLat": 52.23},
        {"fromLocationId": "start", "transportMode": "WALK", "fromLat": 99.0, "fromLng": 21.0},
        {
            "fromLocationId": "start",
            "from_location_id": "attr-01",
            "transportMode": "WALK",
        },
    ],
)
def test_proposals_invalid_params_return_400(params: dict[str, object]) -> None:
    client, _, route_service = _build_test_client()

    response = client.get("/api/gastronomy/proposals", params=params)

    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "INVALID_REQUEST"
    assert body["detail"]
    assert route_service.calls == 0


def test_proposals_transport_unavailable_returns_503_with_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RETRY_AFTER_SECONDS", "60")
    get_settings.cache_clear()
    try:
        route_service = FakeRouteService(raise_unavailable=True)
        client, _, _ = _build_test_client(route_service=route_service)

        response = client.get(
            "/api/gastronomy/proposals",
            params={"fromLocationId": "start", "transportMode": "WALK"},
        )

        assert response.status_code == 503
        assert response.headers["Retry-After"] == "60"
        body = response.json()
        assert body["error"] == "TRANSPORT_UNAVAILABLE"
        assert "timed out" in body["detail"]
    finally:
        get_settings.cache_clear()


def test_cors_allows_cross_origin_requests() -> None:
    client, _, _ = _build_test_client()

    response = client.get("/health", headers={"Origin": "http://localhost:3000"})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"


def test_lifespan_initializes_and_seeds_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called_init: list[str] = []
    called_seed: list[str] = []

    monkeypatch.setenv("DB_PATH", "test_lifespan.db")
    get_settings.cache_clear()
    monkeypatch.setattr("app.main.init_db", lambda db_path: called_init.append(str(db_path)))
    monkeypatch.setattr(
        "app.main.seed_database", lambda db_path: called_seed.append(str(db_path))
    )

    try:
        app = create_app(init_storage=True)
        with TestClient(app) as client:
            health = client.get("/health")
            assert health.status_code == 200

        assert called_init == ["test_lifespan.db"]
        assert called_seed == ["test_lifespan.db"]
    finally:
        get_settings.cache_clear()


def test_lifespan_handles_not_implemented_storage_gracefully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise_not_implemented(_: object) -> None:
        raise NotImplementedError("stub")

    monkeypatch.setattr("app.main.init_db", _raise_not_implemented)

    with TestClient(create_app(init_storage=True)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_in_memory_fallback_places_and_routes_work_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise_sync(*args: object, **kwargs: object) -> None:
        raise NotImplementedError("stub")

    async def _raise_async(*args: object, **kwargs: object) -> None:
        raise NotImplementedError("stub")

    _IN_MEMORY_ROUTE_CACHE.clear()
    monkeypatch.setattr("app.main.init_db", _raise_sync)
    monkeypatch.setattr(GastronomyRepository, "get_all_places", _raise_sync)
    monkeypatch.setattr(GastronomyRepository, "get_place_by_id", _raise_sync)
    monkeypatch.setattr(GastronomyRepository, "find_places_with_meals", _raise_sync)
    monkeypatch.setattr(RouteService, "get_routes_from_attraction", _raise_async)

    try:
        with TestClient(create_app(init_storage=True)) as client:
            places_resp = client.get("/api/gastronomy/places")
            assert places_resp.status_code == 200
            places = places_resp.json()
            assert [p["id"] for p in places] == [
                "rest-01",
                "rest-02",
                "rest-03",
                "rest-04",
            ]

            place_resp = client.get("/api/gastronomy/places/rest-01")
            assert place_resp.status_code == 200
            assert place_resp.json()["name"] == "Bistro Zielone"

            missing_resp = client.get("/api/gastronomy/places/missing")
            assert missing_resp.status_code == 404

            walk_resp = client.get(
                "/api/gastronomy/proposals",
                params={"fromLocationId": "start", "transportMode": "WALK"},
            )
            assert walk_resp.status_code == 200
            walk_proposals = walk_resp.json()["proposals"]
            assert all(item["placeId"] != "rest-04" for item in walk_proposals)
            assert walk_proposals[0]["mealId"] == "meal-01"
            assert walk_proposals[0]["totalPriceGroszy"] == 1800
            assert walk_proposals[0]["totalDurationMinutes"] == 54

            car_vegan_resp = client.get(
                "/api/gastronomy/proposals",
                params={"fromLocationId": "start", "transportMode": "CAR", "diet": "VEGAN"},
            )
            assert car_vegan_resp.status_code == 200
            car_vegan_by_meal = {
                item["mealId"]: item for item in car_vegan_resp.json()["proposals"]
            }
            assert car_vegan_by_meal["meal-01"]["totalPriceGroszy"] == 2945
            assert car_vegan_by_meal["meal-01"]["totalDurationMinutes"] == 50

            from_attr_resp = client.get(
                "/api/gastronomy/proposals",
                params={
                    "fromLocationId": "attr-01",
                    "transportMode": "PUBLIC_TRANSPORT",
                },
            )
            assert from_attr_resp.status_code == 200
            rest01_items = [
                item
                for item in from_attr_resp.json()["proposals"]
                if item["placeId"] == "rest-01"
            ]
            assert rest01_items
            assert rest01_items[0]["travelDurationMinutes"] == 17
            assert rest01_items[0]["travelPriceGroszy"] == 960
    finally:
        _IN_MEMORY_ROUTE_CACHE.clear()


def test_phase2_and_phase3_integrated_with_mock_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise_sync(*args: object, **kwargs: object) -> None:
        raise NotImplementedError("stub")

    _IN_MEMORY_ROUTE_CACHE.clear()
    monkeypatch.setenv("USE_MOCK_TRANSPORT", "true")
    get_settings.cache_clear()
    monkeypatch.setattr("app.main.init_db", _raise_sync)
    monkeypatch.setattr(GastronomyRepository, "get_all_places", _raise_sync)
    monkeypatch.setattr(GastronomyRepository, "get_place_by_id", _raise_sync)
    monkeypatch.setattr(GastronomyRepository, "find_places_with_meals", _raise_sync)
    monkeypatch.setattr(GastronomyRepository, "get_cached_route", _raise_sync)
    monkeypatch.setattr(GastronomyRepository, "get_cached_routes", _raise_sync)
    monkeypatch.setattr(GastronomyRepository, "upsert_cached_routes", _raise_sync)

    try:
        with TestClient(create_app(init_storage=True)) as client:
            scenario_resp = client.get(
                "/api/gastronomy/proposals",
                params={
                    "fromLocationId": "attr-02",
                    "mode": "PUBLIC_TRANSPORT",
                    "diet": "VEGETARIAN",
                    "maxBudgetGrosze": 3600,
                },
            )
            assert scenario_resp.status_code == 200
            scenario_proposals = scenario_resp.json()["proposals"]
            assert [item["mealId"] for item in scenario_proposals] == [
                "meal-01",
                "meal-08",
                "meal-03",
            ]
            assert [item["totalPriceGroszy"] for item in scenario_proposals] == [
                2760,
                3360,
                3560,
            ]
            assert [item["totalDurationMinutes"] for item in scenario_proposals] == [
                64,
                112,
                72,
            ]
            assert _IN_MEMORY_ROUTE_CACHE

            atr_resp = client.get(
                "/api/gastronomy/proposals",
                params={
                    "fromLocationId": "ATR_002",
                    "mode": "PUBLIC_TRANSPORT",
                    "diet": "VEGETARIAN",
                    "maxBudgetGrosze": 3600,
                },
            )
            assert atr_resp.status_code == 200
            atr_proposals = atr_resp.json()["proposals"]
            assert [item["mealId"] for item in atr_proposals] == [
                "meal-01",
                "meal-08",
                "meal-03",
            ]
            assert [item["totalPriceGroszy"] for item in atr_proposals] == [
                2760,
                3360,
                3560,
            ]

            car_resp = client.get(
                "/api/gastronomy/proposals",
                params={"fromLocationId": "start", "mode": "CAR", "diet": "VEGAN"},
            )
            assert car_resp.status_code == 200
            car_proposals = car_resp.json()["proposals"]
            assert [item["mealId"] for item in car_proposals] == ["meal-01", "meal-02"]
            assert car_proposals[0]["travelDurationMinutes"] == 5
            assert car_proposals[0]["travelPriceGroszy"] == 1145

            empty_walk_resp = client.get(
                "/api/gastronomy/proposals",
                params={"fromLocationId": "attr-05", "mode": "WALK"},
            )
            assert empty_walk_resp.status_code == 200
            assert empty_walk_resp.json()["proposals"] == []

            standard_resp = client.get(
                "/api/gastronomy/proposals",
                params={"fromLocationId": "start", "mode": "WALK", "diet": "STANDARD"},
            )
            assert standard_resp.status_code == 200
            standard_body = standard_resp.json()
            assert standard_body["diet"] == "STANDARD"
            assert {item["mealId"] for item in standard_body["proposals"]} == {
                "meal-01",
                "meal-02",
                "meal-03",
                "meal-04",
                "meal-05",
                "meal-06",
            }
    finally:
        _IN_MEMORY_ROUTE_CACHE.clear()
        get_settings.cache_clear()


def test_full_stack_sqlite_db_route_service_and_api_end_to_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_file = tmp_path / "e2e.db"
    monkeypatch.setenv("DB_PATH", str(db_file))
    monkeypatch.setenv("USE_MOCK_TRANSPORT", "true")
    get_settings.cache_clear()

    try:
        with TestClient(create_app(init_storage=True)) as client:
            places_resp = client.get("/api/gastronomy/places")
            assert places_resp.status_code == 200
            places = places_resp.json()
            assert [p["id"] for p in places] == [
                "rest-01",
                "rest-02",
                "rest-03",
                "rest-04",
            ]
            assert places[0]["name"] == "Bar Mleczny Familijny"
            assert places[0]["openingFrom"] == "08:00"
            assert places[0]["openingTo"] == "19:00"
            assert places[3]["openingFrom"] == "17:00"
            assert places[3]["openingTo"] == "23:00"

            place_resp = client.get("/api/gastronomy/places/rest-02")
            assert place_resp.status_code == 200
            assert place_resp.json()["name"] == "Zielona Miska"

            proposals_resp = client.get(
                "/api/gastronomy/proposals",
                params={
                    "fromLocationId": "ATR_001",
                    "mode": "PUBLIC_TRANSPORT",
                    "diet": "VEGAN",
                    "maxBudgetGrosze": 5000,
                },
            )
            assert proposals_resp.status_code == 200
            proposals = proposals_resp.json()["proposals"]
            assert [item["mealId"] for item in proposals] == [
                "zielona-bowl-falafel",
                "zielona-curry",
            ]
            assert [item["totalPriceGroszy"] for item in proposals] == [4160, 4560]
            assert [item["totalDurationMinutes"] for item in proposals] == [65, 65]
            assert proposals[0]["openingFrom"] == "10:00"
            assert proposals[0]["openingTo"] == "21:00"

            cached = GastronomyRepository(db_file).get_cached_route(
                "start",
                "rest-02",
                TransportMode.PUBLIC_TRANSPORT,
            )
            assert cached is not None
            assert cached.available is True
            assert cached.duration_minutes == 11
            assert cached.price_groszy == 480

            empty_resp = client.get(
                "/api/gastronomy/proposals",
                params={
                    "fromLocationId": "start",
                    "mode": "WALK",
                    "maxBudgetGrosze": 500,
                },
            )
            assert empty_resp.status_code == 200
            assert empty_resp.json()["proposals"] == []
    finally:
        get_settings.cache_clear()
