import logging

from app.clients.transport import TransportClient
from app.db.repository import GastronomyRepository
from app.exceptions import TransportUnavailableError
from app.schemas import Coordinates, LocationPair, Place, TransportMode, TransportRoute, TransportRouteRequest

logger = logging.getLogger(__name__)


class RouteService:
    """Orkiestruje zapytania do Transportu wraz z zapisem i fallbackiem do cache SQLite."""

    def __init__(
        self,
        client: TransportClient,
        repository: GastronomyRepository,
        use_cache_fallback: bool = True,
    ) -> None:
        self.client = client
        self.repository = repository
        self.use_cache_fallback = use_cache_fallback

    async def get_routes(
        self,
        from_location_id: str,
        to_location_ids: list[str],
        transport_mode: TransportMode,
        coordinates: dict[str, Coordinates] | None = None,
    ) -> dict[str, TransportRoute]:
        """Zwraca trasy `from_location_id -> każdy z to_location_ids` jako mapę po `to_location_id`.

        1. Pytamy Transport; po sukcesie zapisujemy wszystkie trasy (także `available=False`) w cache.
        2. Przy `TransportUnavailableError` i włączonym fallbacku zwracamy trasy z cache
           (`from_cache=True`; brakujące pary po prostu nie występują w mapie).
        3. Gdy fallback wyłączony albo cache pusty — `TransportUnavailableError` (-> HTTP 503).
        """
        targets = list(dict.fromkeys(to_location_ids))  # deduplikacja z zachowaniem kolejności
        if not targets:
            return {}

        coords = coordinates or {}
        request = TransportRouteRequest(
            transport_mode=transport_mode,
            pairs=[
                LocationPair(
                    from_location_id=from_location_id,
                    to_location_id=to_id,
                    from_coordinates=coords.get(from_location_id),
                    to_coordinates=coords.get(to_id),
                )
                for to_id in targets
            ],
        )

        try:
            routes = await self.client.fetch_routes(request)
        except TransportUnavailableError as exc:
            return self._fallback_to_cache(from_location_id, targets, transport_mode, exc)

        self._save_to_cache(routes)
        return {route.to_location_id: route for route in routes if route.from_location_id == from_location_id}

    async def get_routes_from_attraction(
        self,
        from_location_id: str,
        places: list[Place],
        transport_mode: TransportMode,
        from_coordinates: Coordinates | None = None,
    ) -> dict[str, TransportRoute]:
        """Pobiera trasy z atrakcji startowej do wskazanych lokali, zapisuje w cache i zwraca mapę po `to_location_id`."""
        coordinates = {place.location_id: place.coordinates for place in places}
        if from_coordinates is not None:
            coordinates[from_location_id] = from_coordinates
        return await self.get_routes(
            from_location_id,
            [place.location_id for place in places],
            transport_mode,
            coordinates,
        )

    def _save_to_cache(self, routes: list[TransportRoute]) -> None:
        if not routes:
            return
        try:
            self.repository.upsert_cached_routes(routes)
        except Exception:  # cache jest pomocniczy — nie psujemy odpowiedzi
            logger.exception("Nie udało się zapisać tras Transportu w cache")

    def _fallback_to_cache(
        self,
        from_location_id: str,
        targets: list[str],
        transport_mode: TransportMode,
        error: TransportUnavailableError,
    ) -> dict[str, TransportRoute]:
        if not self.use_cache_fallback:
            raise error

        try:
            cached = self.repository.get_cached_routes(from_location_id, targets, transport_mode)
        except Exception:
            logger.exception("Nie udało się odczytać tras z cache")
            cached = {}

        result = {
            to_id: route.model_copy(update={"from_cache": True})
            for to_id, route in cached.items()
            if to_id in targets
        }
        if not result:
            logger.warning("Transport niedostępny (%s), a cache jest pusty", error)
            raise error

        logger.warning("Transport niedostępny (%s) — używam %d tras z cache", error, len(result))
        return result
