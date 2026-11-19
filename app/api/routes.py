from typing import TypeVar

from fastapi import APIRouter, Depends, Query

from app.clients.transport import TransportClient, create_transport_client
from app.config import Settings, get_settings
from app.db.repository import GastronomyRepository
from app.exceptions import InvalidRequestError, PlaceNotFoundError
from app.schemas import (
    Coordinates,
    DietType,
    HealthResponse,
    Meal,
    MealProposal,
    Place,
    ProposalsResponse,
    TransportMode,
    TransportRoute,
)
from app.services.route_service import RouteService

T = TypeVar("T")

router = APIRouter()

_FALLBACK_LEGS_FROM_START: dict[str, dict[TransportMode, tuple[int, int] | None]] = {
    "ATR_001": {
        TransportMode.WALK: (15, 0),
        TransportMode.PUBLIC_TRANSPORT: (9, 480),
        TransportMode.CAR: (6, 1320),
    },
    "ATR_002": {
        TransportMode.WALK: (21, 0),
        TransportMode.PUBLIC_TRANSPORT: (11, 480),
        TransportMode.CAR: (7, 1495),
    },
    "ATR_004": {
        TransportMode.WALK: (29, 0),
        TransportMode.PUBLIC_TRANSPORT: (13, 480),
        TransportMode.CAR: (8, 1740),
    },
    "attr-01": {
        TransportMode.WALK: (15, 0),
        TransportMode.PUBLIC_TRANSPORT: (9, 480),
        TransportMode.CAR: (6, 1320),
    },
    "attr-02": {
        TransportMode.WALK: (21, 0),
        TransportMode.PUBLIC_TRANSPORT: (11, 480),
        TransportMode.CAR: (7, 1495),
    },
    "attr-03": {
        TransportMode.WALK: (28, 0),
        TransportMode.PUBLIC_TRANSPORT: (12, 480),
        TransportMode.CAR: (8, 1705),
    },
    "attr-04": {
        TransportMode.WALK: (29, 0),
        TransportMode.PUBLIC_TRANSPORT: (13, 480),
        TransportMode.CAR: (8, 1740),
    },
    "attr-05": {
        TransportMode.WALK: None,
        TransportMode.PUBLIC_TRANSPORT: (17, 480),
        TransportMode.CAR: (11, 2230),
    },
    "attr-06": {
        TransportMode.WALK: None,
        TransportMode.PUBLIC_TRANSPORT: (28, 480),
        TransportMode.CAR: (19, 3560),
    },
    "rest-01": {
        TransportMode.WALK: (9, 0),
        TransportMode.PUBLIC_TRANSPORT: (8, 480),
        TransportMode.CAR: (5, 1145),
    },
    "rest-02": {
        TransportMode.WALK: (22, 0),
        TransportMode.PUBLIC_TRANSPORT: (11, 480),
        TransportMode.CAR: (7, 1530),
    },
    "rest-03": {
        TransportMode.WALK: (34, 0),
        TransportMode.PUBLIC_TRANSPORT: (14, 480),
        TransportMode.CAR: (9, 1880),
    },
    "rest-04": {
        TransportMode.WALK: None,
        TransportMode.PUBLIC_TRANSPORT: (26, 480),
        TransportMode.CAR: (17, 3245),
    },
}


def _build_fallback_places() -> list[Place]:
    """Zwraca wbudowane lokale startowe zgodne z docs/KONTRAKT_API_GASTRONOMIA.md."""
    return [
        Place(
            id="rest-01",
            name="Bistro Zielone",
            location_id="rest-01",
            city="Warszawa",
            address="ul. Mokotowska 17",
            coordinates=Coordinates(lat=52.2245, lng=21.0211),
            visit_duration_minutes=45,
            meals=[
                Meal(
                    id="meal-01",
                    place_id="rest-01",
                    name="Krem z dyni",
                    price_groszy=1800,
                    diets=[
                        DietType.VEGETARIAN,
                        DietType.VEGAN,
                        DietType.GLUTEN_FREE,
                    ],
                ),
                Meal(
                    id="meal-02",
                    place_id="rest-01",
                    name="Burger wegański",
                    price_groszy=3200,
                    diets=[DietType.VEGETARIAN, DietType.VEGAN],
                ),
            ],
        ),
        Place(
            id="rest-02",
            name="Pierogarnia Stary Rynek",
            location_id="rest-02",
            city="Warszawa",
            address="ul. Świętojańska 11",
            coordinates=Coordinates(lat=52.2485, lng=21.0135),
            visit_duration_minutes=50,
            meals=[
                Meal(
                    id="meal-03",
                    place_id="rest-02",
                    name="Pierogi ruskie",
                    price_groszy=2600,
                    diets=[DietType.VEGETARIAN],
                ),
                Meal(
                    id="meal-04",
                    place_id="rest-02",
                    name="Pierogi z mięsem",
                    price_groszy=2800,
                    diets=[DietType.STANDARD],
                ),
            ],
        ),
        Place(
            id="rest-03",
            name="Trattoria Sole",
            location_id="rest-03",
            city="Warszawa",
            address="ul. Marszałkowska 84",
            coordinates=Coordinates(lat=52.2281, lng=21.0122),
            visit_duration_minutes=60,
            meals=[
                Meal(
                    id="meal-05",
                    place_id="rest-03",
                    name="Pizza margherita",
                    price_groszy=3400,
                    diets=[DietType.VEGETARIAN],
                ),
                Meal(
                    id="meal-06",
                    place_id="rest-03",
                    name="Risotto z grzybami",
                    price_groszy=3900,
                    diets=[DietType.VEGETARIAN, DietType.GLUTEN_FREE],
                ),
            ],
        ),
        Place(
            id="rest-04",
            name="Karczma pod Lasem",
            location_id="rest-04",
            city="Warszawa",
            address="Wybrzeże Kościuszkowskie 25",
            coordinates=Coordinates(lat=52.2410, lng=21.0315),
            visit_duration_minutes=75,
            meals=[
                Meal(
                    id="meal-07",
                    place_id="rest-04",
                    name="Żurek",
                    price_groszy=2200,
                    diets=[DietType.STANDARD],
                ),
                Meal(
                    id="meal-08",
                    place_id="rest-04",
                    name="Placki ziemniaczane",
                    price_groszy=2400,
                    diets=[DietType.VEGETARIAN],
                ),
            ],
        ),
    ]


def _resolve_fallback_leg(
    location_id: str,
    transport_mode: TransportMode,
) -> tuple[int, int] | None:
    """Zwraca parę (czas_min, koszt_gr) z punktu startowego dla trybu transportu."""
    if transport_mode == TransportMode.BIKE:
        walk_leg = _resolve_fallback_leg(location_id, TransportMode.WALK)
        if walk_leg is None:
            return None
        return (max(1, walk_leg[0] // 3), 0)

    lookup_mode = (
        TransportMode.CAR if transport_mode == TransportMode.TAXI else transport_mode
    )
    if location_id in _FALLBACK_LEGS_FROM_START:
        return _FALLBACK_LEGS_FROM_START[location_id].get(lookup_mode)
    return (20, 0) if lookup_mode == TransportMode.WALK else (15, 480)


def _build_fallback_routes(
    from_location_id: str,
    places: list[Place],
    transport_mode: TransportMode,
) -> dict[str, TransportRoute]:
    """Wylicza deterministyczne trasy na podstawie tabeli z docs/KONTRAKT_API.md."""
    routes: dict[str, TransportRoute] = {}
    for place in places:
        to_location_id = place.location_id
        if from_location_id == to_location_id:
            routes[to_location_id] = TransportRoute(
                from_location_id=from_location_id,
                to_location_id=to_location_id,
                transport_mode=transport_mode,
                available=True,
                distance_meters=0,
                duration_minutes=0,
                price_groszy=0,
                from_cache=False,
            )
            continue

        to_leg = _resolve_fallback_leg(to_location_id, transport_mode)
        if from_location_id == "start" or from_location_id not in _FALLBACK_LEGS_FROM_START:
            resolved_leg = to_leg
        else:
            from_leg = _resolve_fallback_leg(from_location_id, transport_mode)
            if from_leg is None or to_leg is None:
                resolved_leg = None
            else:
                resolved_leg = (from_leg[0] + to_leg[0], from_leg[1] + to_leg[1])

        if resolved_leg is None:
            routes[to_location_id] = TransportRoute(
                from_location_id=from_location_id,
                to_location_id=to_location_id,
                transport_mode=transport_mode,
                available=False,
                distance_meters=None,
                duration_minutes=None,
                price_groszy=None,
                from_cache=False,
            )
        else:
            routes[to_location_id] = TransportRoute(
                from_location_id=from_location_id,
                to_location_id=to_location_id,
                transport_mode=transport_mode,
                available=True,
                distance_meters=None,
                duration_minutes=resolved_leg[0],
                price_groszy=resolved_leg[1],
                from_cache=False,
            )

    return routes


_IN_MEMORY_ROUTE_CACHE: dict[tuple[str, str, TransportMode], TransportRoute] = {}


class _FallbackRepositoryWrapper:
    """Wrapper delegujący do SQLite i przełączający na mock w pamięci przed merge'em Agenta 1."""

    def __init__(self, primary: GastronomyRepository) -> None:
        self._primary = primary
        self._fallback_places = _build_fallback_places()
        self._route_cache = _IN_MEMORY_ROUTE_CACHE

    def get_all_places(self) -> list[Place]:
        try:
            return self._primary.get_all_places()
        except NotImplementedError:
            return [place.model_copy(deep=True) for place in self._fallback_places]

    def get_place_by_id(self, place_id: str) -> Place | None:
        try:
            return self._primary.get_place_by_id(place_id)
        except NotImplementedError:
            for place in self._fallback_places:
                if place.id == place_id:
                    return place.model_copy(deep=True)
            return None

    def find_places_with_meals(
        self,
        diet: DietType | None = None,
        max_meal_price_groszy: int | None = None,
    ) -> list[Place]:
        try:
            return self._primary.find_places_with_meals(
                diet=diet,
                max_meal_price_groszy=max_meal_price_groszy,
            )
        except NotImplementedError:
            matched: list[Place] = []
            for place in self._fallback_places:
                meals = [
                    meal
                    for meal in place.meals
                    if (diet is None or diet in meal.diets)
                    and (
                        max_meal_price_groszy is None
                        or meal.price_groszy <= max_meal_price_groszy
                    )
                ]
                if meals:
                    matched.append(place.model_copy(update={"meals": meals}, deep=True))
            return matched

    def get_cached_route(
        self,
        from_location_id: str,
        to_location_id: str,
        transport_mode: TransportMode,
    ) -> TransportRoute | None:
        try:
            return self._primary.get_cached_route(
                from_location_id, to_location_id, transport_mode
            )
        except NotImplementedError:
            return self._route_cache.get((from_location_id, to_location_id, transport_mode))

    def get_cached_routes(
        self,
        from_location_id: str,
        to_location_ids: list[str],
        transport_mode: TransportMode,
    ) -> dict[str, TransportRoute]:
        try:
            return self._primary.get_cached_routes(
                from_location_id, to_location_ids, transport_mode
            )
        except NotImplementedError:
            result: dict[str, TransportRoute] = {}
            for to_location_id in to_location_ids:
                route = self._route_cache.get(
                    (from_location_id, to_location_id, transport_mode)
                )
                if route is not None:
                    result[to_location_id] = route
            return result

    def upsert_cached_routes(self, routes: list[TransportRoute]) -> None:
        try:
            self._primary.upsert_cached_routes(routes)
        except NotImplementedError:
            for route in routes:
                key = (route.from_location_id, route.to_location_id, route.transport_mode)
                self._route_cache[key] = route


class _FallbackRouteServiceWrapper:
    """Wrapper delegujący do RouteService i korzystający z tabeli awaryjnej przed merge'em Agenta 2."""

    def __init__(self, primary: RouteService) -> None:
        self._primary = primary

    async def get_routes(
        self,
        from_location_id: str,
        to_location_ids: list[str],
        transport_mode: TransportMode,
        coordinates: dict[str, Coordinates] | None = None,
    ) -> dict[str, TransportRoute]:
        try:
            return await self._primary.get_routes(
                from_location_id=from_location_id,
                to_location_ids=to_location_ids,
                transport_mode=transport_mode,
                coordinates=coordinates,
            )
        except NotImplementedError:
            target_places = [
                Place(
                    id=to_id,
                    name=to_id,
                    location_id=to_id,
                    city="",
                    coordinates=(coordinates or {}).get(
                        to_id, Coordinates(lat=0.0, lng=0.0)
                    ),
                    visit_duration_minutes=1,
                    meals=[],
                )
                for to_id in to_location_ids
            ]
            return _build_fallback_routes(from_location_id, target_places, transport_mode)

    async def get_routes_from_attraction(
        self,
        from_location_id: str,
        places: list[Place],
        transport_mode: TransportMode,
        from_coordinates: Coordinates | None = None,
    ) -> dict[str, TransportRoute]:
        try:
            return await self._primary.get_routes_from_attraction(
                from_location_id=from_location_id,
                places=places,
                transport_mode=transport_mode,
                from_coordinates=from_coordinates,
            )
        except NotImplementedError:
            return _build_fallback_routes(from_location_id, places, transport_mode)


def get_repository(
    settings: Settings = Depends(get_settings),
) -> GastronomyRepository | _FallbackRepositoryWrapper:
    """Dostarcza instancję repozytorium SQLite z bezpiecznym fallbackiem w pamięci."""
    return _FallbackRepositoryWrapper(GastronomyRepository(settings.db_path))


def get_transport_client(settings: Settings = Depends(get_settings)) -> TransportClient:
    """Dostarcza klienta HTTP Transportu lub deterministyczny mock zależnie od konfiguracji."""
    return create_transport_client(settings)


def get_route_service(
    settings: Settings = Depends(get_settings),
    repository: GastronomyRepository | _FallbackRepositoryWrapper = Depends(get_repository),
    client: TransportClient = Depends(get_transport_client),
) -> RouteService | _FallbackRouteServiceWrapper:
    """Dostarcza serwis wyznaczania tras z obsługą cache, fallbacku i trybu tymczasowego."""
    primary = RouteService(
        client=client,
        repository=repository,
        use_cache_fallback=settings.use_cache_fallback_on_transport_error,
    )
    return _FallbackRouteServiceWrapper(primary)


def _resolve_aliases(values: list[tuple[str, T | None]]) -> T | None:
    """Rozwiązuje grupę aliasów parametrów query i wykrywa sprzeczne wartości."""
    present = [(name, val) for name, val in values if val is not None]
    if not present:
        return None
    first_name, first_val = present[0]
    for other_name, other_val in present[1:]:
        if other_val != first_val:
            raise InvalidRequestError(
                f"Conflicting query parameters '{first_name}' and '{other_name}'."
            )
    return first_val


def _parse_transport_mode(raw: str | None) -> TransportMode:
    """Waliduje i normalizuje tryb transportu przekazany w parametrze zapytania."""
    if raw is None or not raw.strip():
        raise InvalidRequestError("Missing required query parameter: transportMode.")
    normalized = raw.strip().upper()
    try:
        return TransportMode(normalized)
    except ValueError as exc:
        allowed = ", ".join(mode.value for mode in TransportMode)
        raise InvalidRequestError(
            f"Unsupported transportMode '{raw}'. Allowed values: {allowed}."
        ) from exc


def _parse_diet(raw: str | None) -> DietType | None:
    """Waliduje i normalizuje opcjonalny filtr diety."""
    if raw is None:
        return None
    normalized = raw.strip().upper()
    if not normalized:
        allowed = ", ".join(item.value for item in DietType)
        raise InvalidRequestError(
            f"Parameter 'diet' cannot be empty. Allowed values: {allowed}."
        )
    try:
        return DietType(normalized)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in DietType)
        raise InvalidRequestError(
            f"Unsupported diet '{raw}'. Allowed values: {allowed}."
        ) from exc


def _parse_coordinates(lat: float | None, lng: float | None) -> Coordinates | None:
    """Waliduje parę opcjonalnych współrzędnych punktu startowego."""
    if lat is None and lng is None:
        return None
    if lat is None or lng is None:
        raise InvalidRequestError("Both fromLat and fromLng must be provided together.")
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lng <= 180.0):
        raise InvalidRequestError(
            "Coordinates out of range: fromLat must be in [-90, 90] and fromLng in [-180, 180]."
        )
    return Coordinates(lat=lat, lng=lng)


@router.get("/health", response_model=HealthResponse, tags=["health"])
def health_check(settings: Settings = Depends(get_settings)) -> HealthResponse:
    """Sprawdza stan serwisu Gastronomia i tryb pracy klienta Transportu."""
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        mock_transport=settings.use_mock_transport,
    )


@router.get("/api/gastronomy/places", response_model=list[Place], tags=["gastronomy"])
def list_places(
    repository: GastronomyRepository = Depends(get_repository),
) -> list[Place]:
    """Zwraca wszystkie lokale gastronomiczne wraz z przypisanymi posiłkami."""
    return repository.get_all_places()


@router.get(
    "/api/gastronomy/places/{place_id}",
    response_model=Place,
    tags=["gastronomy"],
)
def get_place(
    place_id: str,
    repository: GastronomyRepository = Depends(get_repository),
) -> Place:
    """Zwraca szczegóły pojedynczego lokalu albo zgłasza błąd 404."""
    normalized_id = place_id.strip()
    if not normalized_id:
        raise InvalidRequestError("Parameter 'place_id' cannot be empty.")
    place = repository.get_place_by_id(normalized_id)
    if place is None:
        raise PlaceNotFoundError(f"Place '{normalized_id}' not found.")
    return place


@router.get("/api/gastronomy/diets", response_model=list[DietType], tags=["gastronomy"])
def list_diets() -> list[DietType]:
    """Zwraca listę obsługiwanych typów diet."""
    return list(DietType)


async def _fetch_routes_for_places(
    route_service: RouteService | _FallbackRouteServiceWrapper,
    from_location_id: str,
    places: list[Place],
    transport_mode: TransportMode,
    from_coordinates: Coordinates | None,
) -> dict[str, TransportRoute]:
    """Pobiera trasy bezpośrednio, a gdy Transport zwraca tylko odcinki przez 'start', składa dwa odcinki."""
    routes = await route_service.get_routes_from_attraction(
        from_location_id=from_location_id,
        places=places,
        transport_mode=transport_mode,
        from_coordinates=from_coordinates,
    )
    if (
        from_location_id == "start"
        or any(route.available for route in routes.values())
        or not hasattr(route_service, "get_routes")
    ):
        return routes

    coordinates: dict[str, Coordinates] = {
        place.location_id: place.coordinates for place in places
    }
    if from_coordinates is not None:
        coordinates[from_location_id] = from_coordinates

    to_start = await route_service.get_routes(
        from_location_id,
        ["start"],
        transport_mode,
        coordinates,
    )
    leg_to_start = to_start.get("start")
    if (
        leg_to_start is None
        or not leg_to_start.available
        or leg_to_start.duration_minutes is None
        or leg_to_start.price_groszy is None
    ):
        return routes

    from_start = await route_service.get_routes(
        "start",
        [place.location_id for place in places],
        transport_mode,
        coordinates,
    )

    combined: dict[str, TransportRoute] = {}
    for place in places:
        to_id = place.location_id
        if to_id == from_location_id:
            combined[to_id] = TransportRoute(
                from_location_id=from_location_id,
                to_location_id=to_id,
                transport_mode=transport_mode,
                available=True,
                distance_meters=0,
                duration_minutes=0,
                price_groszy=0,
                from_cache=False,
            )
            continue

        leg_from_start = from_start.get(to_id)
        if (
            leg_from_start is None
            or not leg_from_start.available
            or leg_from_start.duration_minutes is None
            or leg_from_start.price_groszy is None
        ):
            combined[to_id] = TransportRoute(
                from_location_id=from_location_id,
                to_location_id=to_id,
                transport_mode=transport_mode,
                available=False,
                from_cache=bool(
                    leg_to_start.from_cache
                    or (leg_from_start.from_cache if leg_from_start else False)
                ),
            )
            continue

        distance_meters = (
            leg_to_start.distance_meters + leg_from_start.distance_meters
            if leg_to_start.distance_meters is not None
            and leg_from_start.distance_meters is not None
            else None
        )
        combined[to_id] = TransportRoute(
            from_location_id=from_location_id,
            to_location_id=to_id,
            transport_mode=transport_mode,
            available=True,
            distance_meters=distance_meters,
            duration_minutes=leg_to_start.duration_minutes + leg_from_start.duration_minutes,
            price_groszy=leg_to_start.price_groszy + leg_from_start.price_groszy,
            from_cache=leg_to_start.from_cache or leg_from_start.from_cache,
        )

    return combined


@router.get(
    "/api/gastronomy/proposals",
    response_model=ProposalsResponse,
    tags=["gastronomy"],
)
async def get_proposals(
    fromLocationId: str | None = Query(default=None),
    from_location_id: str | None = Query(default=None),
    mode: str | None = Query(default=None),
    transportMode: str | None = Query(default=None),
    transport_mode: str | None = Query(default=None),
    diet: str | None = Query(default=None),
    maxBudgetGrosze: int | None = Query(default=None),
    maxBudgetGroszy: int | None = Query(default=None),
    max_budget_groszy: int | None = Query(default=None),
    fromLat: float | None = Query(default=None),
    from_lat: float | None = Query(default=None),
    fromLng: float | None = Query(default=None),
    from_lng: float | None = Query(default=None),
    repository: GastronomyRepository = Depends(get_repository),
    route_service: RouteService = Depends(get_route_service),
) -> ProposalsResponse:
    """Zwraca posortowane propozycje posiłków z kosztem i czasem dojazdu od wskazanej lokalizacji."""
    raw_from_location = _resolve_aliases(
        [("fromLocationId", fromLocationId), ("from_location_id", from_location_id)]
    )
    if raw_from_location is None or not raw_from_location.strip():
        raise InvalidRequestError("Missing required query parameter: fromLocationId.")
    resolved_from_location_id = raw_from_location.strip()

    raw_transport_mode = _resolve_aliases(
        [
            ("mode", mode),
            ("transportMode", transportMode),
            ("transport_mode", transport_mode),
        ]
    )
    resolved_transport_mode = _parse_transport_mode(raw_transport_mode)
    resolved_diet = _parse_diet(diet)
    effective_diet = None if resolved_diet == DietType.STANDARD else resolved_diet

    resolved_max_budget = _resolve_aliases(
        [
            ("maxBudgetGrosze", maxBudgetGrosze),
            ("maxBudgetGroszy", maxBudgetGroszy),
            ("max_budget_groszy", max_budget_groszy),
        ]
    )
    if resolved_max_budget is not None and resolved_max_budget < 0:
        raise InvalidRequestError("Parameter 'maxBudgetGroszy' must be >= 0.")

    resolved_from_lat = _resolve_aliases([("fromLat", fromLat), ("from_lat", from_lat)])
    resolved_from_lng = _resolve_aliases([("fromLng", fromLng), ("from_lng", from_lng)])
    from_coordinates = _parse_coordinates(resolved_from_lat, resolved_from_lng)

    places = repository.find_places_with_meals(
        diet=effective_diet,
        max_meal_price_groszy=resolved_max_budget,
    )
    if not places:
        return ProposalsResponse(
            from_location_id=resolved_from_location_id,
            transport_mode=resolved_transport_mode,
            diet=resolved_diet,
            proposals=[],
        )

    routes_by_location = await _fetch_routes_for_places(
        route_service=route_service,
        from_location_id=resolved_from_location_id,
        places=places,
        transport_mode=resolved_transport_mode,
        from_coordinates=from_coordinates,
    )

    proposals: list[MealProposal] = []
    for place in places:
        route: TransportRoute | None = routes_by_location.get(place.location_id)
        if (
            route is None
            or not route.available
            or route.duration_minutes is None
            or route.price_groszy is None
        ):
            continue

        for meal in place.meals:
            if effective_diet is not None and effective_diet not in meal.diets:
                continue

            total_price_groszy = meal.price_groszy + route.price_groszy
            if resolved_max_budget is not None and total_price_groszy > resolved_max_budget:
                continue

            total_duration_minutes = place.visit_duration_minutes + route.duration_minutes
            proposals.append(
                MealProposal(
                    place_id=place.id,
                    place_name=place.name,
                    location_id=place.location_id,
                    coordinates=place.coordinates,
                    meal_id=meal.id,
                    meal_name=meal.name,
                    diets=meal.diets,
                    meal_price_groszy=meal.price_groszy,
                    visit_duration_minutes=place.visit_duration_minutes,
                    transport_mode=resolved_transport_mode,
                    travel_distance_meters=route.distance_meters,
                    travel_duration_minutes=route.duration_minutes,
                    travel_price_groszy=route.price_groszy,
                    total_price_groszy=total_price_groszy,
                    total_duration_minutes=total_duration_minutes,
                    transport_from_cache=route.from_cache,
                )
            )

    proposals.sort(
        key=lambda proposal: (
            proposal.total_price_groszy,
            proposal.total_duration_minutes,
            proposal.place_id,
            proposal.meal_id,
        )
    )

    return ProposalsResponse(
        from_location_id=resolved_from_location_id,
        transport_mode=resolved_transport_mode,
        diet=resolved_diet,
        proposals=proposals,
    )
