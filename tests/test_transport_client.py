import json

import httpx
import pytest

from app.clients.mock_transport import MockTransportClient
from app.clients.transport import HttpTransportClient, create_transport_client
from app.config import Settings
from app.exceptions import TransportUnavailableError
from app.schemas import (
    Coordinates,
    LocationPair,
    Place,
    TransportMode,
    TransportRoute,
    TransportRouteRequest,
)
from app.services.route_service import RouteService

BASE_URL = "http://transport.test"
ROUTES_PATH = "/api/v1/routes"


def make_request(mode: TransportMode, *to_ids: str, from_id: str = "start") -> TransportRouteRequest:
    return TransportRouteRequest(
        transport_mode=mode,
        pairs=[LocationPair(from_location_id=from_id, to_location_id=to_id) for to_id in to_ids],
    )


def make_client(handler) -> HttpTransportClient:
    return HttpTransportClient(
        base_url=BASE_URL,
        routes_path=ROUTES_PATH,
        timeout_seconds=2.0,
        transport=httpx.MockTransport(handler),
    )


def ok(from_id: str, to_id: str, duration: int, cost: int) -> dict:
    return {"fromLocationId": from_id, "toLocationId": to_id, "status": "OK", "durationMin": duration, "costGrosze": cost}


def no_connection(from_id: str, to_id: str) -> dict:
    return {"fromLocationId": from_id, "toLocationId": to_id, "status": "NO_CONNECTION"}


# --- HttpTransportClient ------------------------------------------------------------------


async def test_http_200_maps_ok_and_no_connection():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "mode": "WALK",
                "results": [ok("start", "rest-01", 9, 0), no_connection("start", "rest-04")],
            },
        )

    routes = await make_client(handler).fetch_routes(make_request(TransportMode.WALK, "rest-01", "rest-04"))

    assert captured["method"] == "POST"
    assert captured["path"] == ROUTES_PATH
    assert captured["body"] == {
        "mode": "WALK",
        "pairs": [
            {"fromLocationId": "start", "toLocationId": "rest-01"},
            {"fromLocationId": "start", "toLocationId": "rest-04"},
        ],
    }
    assert routes[0] == TransportRoute(
        from_location_id="start",
        to_location_id="rest-01",
        transport_mode=TransportMode.WALK,
        available=True,
        duration_minutes=9,
        price_groszy=0,
    )
    assert routes[1].available is False
    assert routes[1].duration_minutes is None and routes[1].price_groszy is None
    assert routes[1].transport_mode == TransportMode.WALK


async def test_http_taxi_is_sent_as_car_and_mode_comes_from_request():
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["mode"] == "CAR"
        return httpx.Response(200, json={"mode": "CAR", "results": [ok("start", "rest-02", 7, 1530)]})

    routes = await make_client(handler).fetch_routes(make_request(TransportMode.TAXI, "rest-02"))

    assert routes[0].transport_mode == TransportMode.TAXI
    assert (routes[0].duration_minutes, routes[0].price_groszy) == (7, 1530)


async def test_http_coordinates_are_not_sent():
    def handler(request: httpx.Request) -> httpx.Response:
        pair = json.loads(request.content)["pairs"][0]
        assert set(pair) == {"fromLocationId", "toLocationId"}
        return httpx.Response(200, json={"mode": "WALK", "results": [ok("start", "x", 1, 0)]})

    request = TransportRouteRequest(
        transport_mode=TransportMode.WALK,
        pairs=[
            LocationPair(
                from_location_id="start",
                to_location_id="x",
                from_coordinates=Coordinates(lat=50.0, lng=19.9),
                to_coordinates=Coordinates(lat=50.1, lng=19.9),
            )
        ],
    )
    assert (await make_client(handler).fetch_routes(request))[0].available


async def test_http_unsupported_mode_returns_unavailable_without_http_call():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("BIKE nie powinien wywoływać Transportu")

    routes = await make_client(handler).fetch_routes(make_request(TransportMode.BIKE, "rest-01", "rest-02"))

    assert [r.available for r in routes] == [False, False]
    assert all(r.transport_mode == TransportMode.BIKE for r in routes)


async def test_http_empty_pairs_returns_empty_list():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("pusta lista par nie powinna wywoływać Transportu")

    assert await make_client(handler).fetch_routes(make_request(TransportMode.WALK)) == []


async def test_http_matches_results_by_pair_not_by_order():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"mode": "WALK", "results": [ok("start", "b", 20, 0), ok("start", "a", 10, 0)]},
        )

    routes = await make_client(handler).fetch_routes(make_request(TransportMode.WALK, "a", "b"))

    assert [(r.to_location_id, r.duration_minutes) for r in routes] == [("a", 10), ("b", 20)]


async def test_http_missing_result_is_treated_as_no_connection():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"mode": "WALK", "results": [ok("start", "a", 10, 0)]})

    routes = await make_client(handler).fetch_routes(make_request(TransportMode.WALK, "a", "b"))

    assert [r.available for r in routes] == [True, False]


async def test_http_splits_more_than_500_pairs_into_chunks():
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        pairs = json.loads(request.content)["pairs"]
        calls.append(len(pairs))
        return httpx.Response(
            200,
            json={"mode": "WALK", "results": [ok(p["fromLocationId"], p["toLocationId"], 5, 0) for p in pairs]},
        )

    to_ids = [f"rest-{i:03d}" for i in range(501)]
    routes = await make_client(handler).fetch_routes(make_request(TransportMode.WALK, *to_ids))

    assert calls == [500, 1]
    assert len(routes) == 501 and all(r.available for r in routes)


@pytest.mark.parametrize(
    "exc",
    [
        httpx.ReadTimeout("timeout"),
        httpx.ConnectTimeout("timeout"),
        httpx.ConnectError("connection refused"),
    ],
)
async def test_http_timeout_and_network_errors_raise_unavailable(exc):
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    with pytest.raises(TransportUnavailableError):
        await make_client(handler).fetch_routes(make_request(TransportMode.WALK, "rest-01"))


@pytest.mark.parametrize("status", [400, 404, 500, 503])
async def test_http_error_status_raises_unavailable(status):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": "X", "message": "boom"})

    with pytest.raises(TransportUnavailableError, match=str(status)):
        await make_client(handler).fetch_routes(make_request(TransportMode.WALK, "rest-01"))


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>nie JSON</html>"),
        httpx.Response(200, json={"mode": "WALK"}),
        httpx.Response(200, json={"mode": "WALK", "results": [{"fromLocationId": "start", "toLocationId": "rest-01", "status": "OK"}]}),
        httpx.Response(200, json={"mode": "WALK", "results": [ok("start", "rest-01", -3, 0)]}),
    ],
    ids=["not-json", "no-results", "ok-without-duration", "negative-duration"],
)
async def test_http_malformed_response_raises_unavailable(response):
    def handler(request: httpx.Request) -> httpx.Response:
        return response

    with pytest.raises(TransportUnavailableError):
        await make_client(handler).fetch_routes(make_request(TransportMode.WALK, "rest-01"))


def test_create_transport_client_respects_mock_flag():
    assert isinstance(create_transport_client(Settings(use_mock_transport=True)), MockTransportClient)
    client = create_transport_client(
        Settings(
            use_mock_transport=False,
            transport_base_url="http://172.20.147.17:8083/",
            transport_routes_path="/api/v1/routes",
            transport_timeout_ms=2000,
        )
    )
    assert isinstance(client, HttpTransportClient)
    assert client.base_url == "http://172.20.147.17:8083"
    assert client.timeout_seconds == 2.0


# --- MockTransportClient ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "to_id", "expected"),
    [
        (TransportMode.WALK, "rest-01", (9, 0)),
        (TransportMode.PUBLIC_TRANSPORT, "rest-02", (11, 480)),
        (TransportMode.TAXI, "rest-04", (17, 3245)),
        (TransportMode.TAXI, "attr-06", (19, 3560)),
    ],
)
async def test_mock_uses_contract_table(mode, to_id, expected):
    (route,) = await MockTransportClient().fetch_routes(make_request(mode, to_id))
    assert route.available
    assert (route.duration_minutes, route.price_groszy) == expected


async def test_mock_contract_no_connection_cases():
    mock = MockTransportClient()
    (walk,) = await mock.fetch_routes(make_request(TransportMode.WALK, "rest-04"))
    (no_start,) = await mock.fetch_routes(make_request(TransportMode.WALK, "rest-01", from_id="attr-01"))
    (bike,) = await mock.fetch_routes(make_request(TransportMode.BIKE, "rest-01"))
    assert not walk.available and not no_start.available and not bike.available


async def test_mock_same_location_is_zero():
    (route,) = await MockTransportClient().fetch_routes(make_request(TransportMode.TAXI, "start"))
    assert route.available
    assert (route.duration_minutes, route.price_groszy, route.distance_meters) == (0, 0, 0)


@pytest.mark.parametrize("mode", [TransportMode.WALK, TransportMode.PUBLIC_TRANSPORT, TransportMode.TAXI])
async def test_mock_is_deterministic_and_symmetric(mode):
    mock = MockTransportClient()
    first = await mock.fetch_routes(make_request(mode, "bistro-zielone", "pizzeria-roma", from_id="muzeum-narodowe"))
    second = await mock.fetch_routes(make_request(mode, "bistro-zielone", "pizzeria-roma", from_id="muzeum-narodowe"))
    (reverse,) = await mock.fetch_routes(make_request(mode, "muzeum-narodowe", from_id="bistro-zielone"))

    assert first == second
    assert (reverse.available, reverse.duration_minutes, reverse.price_groszy, reverse.distance_meters) == (
        first[0].available,
        first[0].duration_minutes,
        first[0].price_groszy,
        first[0].distance_meters,
    )


async def test_mock_units_are_non_negative_ints():
    mock = MockTransportClient()
    for mode in (TransportMode.WALK, TransportMode.PUBLIC_TRANSPORT, TransportMode.TAXI):
        for route in await mock.fetch_routes(make_request(mode, "rest-01", "rest-03", "lokal-a", "lokal-b")):
            if route.available:
                for value in (route.duration_minutes, route.price_groszy, route.distance_meters):
                    assert isinstance(value, int) and value >= 0
            else:
                assert route.duration_minutes is None and route.price_groszy is None


async def test_mock_uses_coordinates_and_walk_limit():
    center = Coordinates(lat=50.0614, lng=19.9372)  # Rynek Główny
    near = Coordinates(lat=50.0640, lng=19.9400)  # ~350 m
    far = Coordinates(lat=50.1000, lng=19.9372)  # ~4,3 km

    def pair(to_id: str, coords: Coordinates) -> LocationPair:
        return LocationPair(from_location_id="a", to_location_id=to_id, from_coordinates=center, to_coordinates=coords)

    near_route, far_route = await MockTransportClient().fetch_routes(
        TransportRouteRequest(transport_mode=TransportMode.WALK, pairs=[pair("near", near), pair("far", far)])
    )
    assert near_route.available and near_route.price_groszy == 0
    assert 300 <= near_route.distance_meters <= 600
    assert not far_route.available

    (taxi_far,) = await MockTransportClient().fetch_routes(
        TransportRouteRequest(transport_mode=TransportMode.TAXI, pairs=[pair("far", far)])
    )
    assert taxi_far.available and taxi_far.price_groszy > 800


# --- RouteService -------------------------------------------------------------------------


class FakeRepository:
    """Repozytorium w pamięci — testy nie zależą od implementacji SQLite (Agent 1)."""

    def __init__(self, fail_on_write: bool = False) -> None:
        self.cache: dict[tuple[str, str, TransportMode], TransportRoute] = {}
        self.fail_on_write = fail_on_write
        self.writes = 0

    def upsert_cached_routes(self, routes: list[TransportRoute]) -> None:
        if self.fail_on_write:
            raise RuntimeError("disk full")
        self.writes += 1
        for r in routes:
            self.cache[(r.from_location_id, r.to_location_id, r.transport_mode)] = r

    def get_cached_routes(self, from_location_id, to_location_ids, transport_mode) -> dict[str, TransportRoute]:
        return {
            to_id: self.cache[(from_location_id, to_id, transport_mode)]
            for to_id in to_location_ids
            if (from_location_id, to_id, transport_mode) in self.cache
        }


class FakeClient:
    def __init__(self, routes: list[TransportRoute] | None = None, error: Exception | None = None) -> None:
        self.routes = routes or []
        self.error = error
        self.requests: list[TransportRouteRequest] = []

    async def fetch_routes(self, request: TransportRouteRequest) -> list[TransportRoute]:
        self.requests.append(request)
        if self.error:
            raise self.error
        return self.routes


def route(to_id: str, available: bool = True, minutes: int = 10, price: int = 480) -> TransportRoute:
    return TransportRoute(
        from_location_id="start",
        to_location_id=to_id,
        transport_mode=TransportMode.PUBLIC_TRANSPORT,
        available=available,
        duration_minutes=minutes if available else None,
        price_groszy=price if available else None,
    )


async def test_service_success_saves_to_cache_and_returns_map():
    repo = FakeRepository()
    client = FakeClient([route("rest-01"), route("rest-04", available=False)])
    service = RouteService(client, repo)

    result = await service.get_routes("start", ["rest-01", "rest-04", "rest-01"], TransportMode.PUBLIC_TRANSPORT)

    assert set(result) == {"rest-01", "rest-04"}
    assert not result["rest-04"].available
    assert not result["rest-01"].from_cache
    assert len(client.requests[0].pairs) == 2  # deduplikacja
    assert len(repo.cache) == 2  # zapisane także available=False


async def test_service_falls_back_to_cache_on_transport_error():
    repo = FakeRepository()
    repo.upsert_cached_routes([route("rest-01", minutes=8)])
    service = RouteService(FakeClient(error=TransportUnavailableError("timeout")), repo)

    result = await service.get_routes("start", ["rest-01", "rest-02"], TransportMode.PUBLIC_TRANSPORT)

    assert list(result) == ["rest-01"]
    assert result["rest-01"].from_cache is True
    assert result["rest-01"].duration_minutes == 8


async def test_service_raises_when_cache_is_empty():
    service = RouteService(FakeClient(error=TransportUnavailableError("down")), FakeRepository())

    with pytest.raises(TransportUnavailableError):
        await service.get_routes("start", ["rest-01"], TransportMode.PUBLIC_TRANSPORT)


async def test_service_raises_when_fallback_disabled():
    repo = FakeRepository()
    repo.upsert_cached_routes([route("rest-01")])
    service = RouteService(FakeClient(error=TransportUnavailableError("down")), repo, use_cache_fallback=False)

    with pytest.raises(TransportUnavailableError):
        await service.get_routes("start", ["rest-01"], TransportMode.PUBLIC_TRANSPORT)


async def test_service_empty_targets_do_not_call_transport():
    client = FakeClient(error=AssertionError("nie powinno wołać"))
    assert await RouteService(client, FakeRepository()).get_routes("start", [], TransportMode.WALK) == {}
    assert client.requests == []


async def test_service_cache_write_failure_does_not_break_response():
    service = RouteService(FakeClient([route("rest-01")]), FakeRepository(fail_on_write=True))

    result = await service.get_routes("start", ["rest-01"], TransportMode.PUBLIC_TRANSPORT)

    assert result["rest-01"].available


async def test_service_get_routes_from_attraction_with_mock_client():
    places = [
        Place(
            id="p1",
            name="Bistro",
            location_id="rest-01",
            city="Kraków",
            coordinates=Coordinates(lat=50.06, lng=19.94),
            visit_duration_minutes=45,
        ),
        Place(
            id="p2",
            name="Daleko",
            location_id="rest-04",
            city="Kraków",
            coordinates=Coordinates(lat=50.10, lng=19.90),
            visit_duration_minutes=60,
        ),
    ]
    repo = FakeRepository()
    service = RouteService(MockTransportClient(), repo)

    result = await service.get_routes_from_attraction("start", places, TransportMode.WALK)

    assert result["rest-01"].available and result["rest-01"].duration_minutes == 9
    assert not result["rest-04"].available
    assert repo.writes == 1
