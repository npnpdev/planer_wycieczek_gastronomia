from typing import TypeVar

from fastapi import APIRouter, Depends, Query

from app.clients.mock_transport import MockTransportClient
from app.clients.transport import HttpTransportClient, TransportClient
from app.config import Settings, get_settings
from app.db.repository import GastronomyRepository
from app.exceptions import InvalidRequestError, PlaceNotFoundError
from app.schemas import (
    Coordinates,
    DietType,
    HealthResponse,
    MealProposal,
    Place,
    ProposalsResponse,
    TransportMode,
    TransportRoute,
)
from app.services.route_service import RouteService

T = TypeVar("T")

router = APIRouter()


def get_repository(settings: Settings = Depends(get_settings)) -> GastronomyRepository:
    """Dostarcza instancję repozytorium SQLite skonfigurowaną ścieżką z ustawień."""
    return GastronomyRepository(settings.db_path)


def get_transport_client(settings: Settings = Depends(get_settings)) -> TransportClient:
    """Dostarcza klienta HTTP Transportu lub deterministyczny mock zależnie od konfiguracji."""
    if settings.use_mock_transport:
        return MockTransportClient()
    return HttpTransportClient(
        base_url=settings.transport_base_url,
        routes_path=settings.transport_routes_path,
        timeout_seconds=settings.transport_timeout_seconds,
    )


def get_route_service(
    settings: Settings = Depends(get_settings),
    repository: GastronomyRepository = Depends(get_repository),
    client: TransportClient = Depends(get_transport_client),
) -> RouteService:
    """Dostarcza serwis wyznaczania tras z obsługą cache i fallbacku."""
    return RouteService(
        client=client,
        repository=repository,
        use_cache_fallback=settings.use_cache_fallback_on_transport_error,
    )


def _resolve_alias(
    camel_value: T | None,
    snake_value: T | None,
    camel_name: str,
    snake_name: str,
) -> T | None:
    """Rozwiązuje parę aliasów camelCase/snake_case i wykrywa sprzeczne wartości."""
    if camel_value is not None and snake_value is not None:
        if camel_value != snake_value:
            raise InvalidRequestError(
                f"Conflicting query parameters '{camel_name}' and '{snake_name}'."
            )
        return camel_value
    return camel_value if camel_value is not None else snake_value


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


@router.get(
    "/api/gastronomy/proposals",
    response_model=ProposalsResponse,
    tags=["gastronomy"],
)
async def get_proposals(
    fromLocationId: str | None = Query(default=None),
    from_location_id: str | None = Query(default=None),
    transportMode: str | None = Query(default=None),
    transport_mode: str | None = Query(default=None),
    diet: str | None = Query(default=None),
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
    raw_from_location = _resolve_alias(
        fromLocationId,
        from_location_id,
        "fromLocationId",
        "from_location_id",
    )
    if raw_from_location is None or not raw_from_location.strip():
        raise InvalidRequestError("Missing required query parameter: fromLocationId.")
    resolved_from_location_id = raw_from_location.strip()

    raw_transport_mode = _resolve_alias(
        transportMode,
        transport_mode,
        "transportMode",
        "transport_mode",
    )
    resolved_transport_mode = _parse_transport_mode(raw_transport_mode)
    resolved_diet = _parse_diet(diet)

    resolved_max_budget = _resolve_alias(
        maxBudgetGroszy,
        max_budget_groszy,
        "maxBudgetGroszy",
        "max_budget_groszy",
    )
    if resolved_max_budget is not None and resolved_max_budget < 0:
        raise InvalidRequestError("Parameter 'maxBudgetGroszy' must be >= 0.")

    resolved_from_lat = _resolve_alias(fromLat, from_lat, "fromLat", "from_lat")
    resolved_from_lng = _resolve_alias(fromLng, from_lng, "fromLng", "from_lng")
    from_coordinates = _parse_coordinates(resolved_from_lat, resolved_from_lng)

    places = repository.find_places_with_meals(
        diet=resolved_diet,
        max_meal_price_groszy=resolved_max_budget,
    )
    if not places:
        return ProposalsResponse(
            from_location_id=resolved_from_location_id,
            transport_mode=resolved_transport_mode,
            diet=resolved_diet,
            proposals=[],
        )

    routes_by_location = await route_service.get_routes_from_attraction(
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
            if resolved_diet is not None and resolved_diet not in meal.diets:
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
