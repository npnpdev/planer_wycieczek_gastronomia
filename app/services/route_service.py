from app.clients.transport import TransportClient
from app.db.repository import GastronomyRepository
from app.schemas import Coordinates, Place, TransportMode, TransportRoute


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

    async def get_routes_from_attraction(
        self,
        from_location_id: str,
        places: list[Place],
        transport_mode: TransportMode,
        from_coordinates: Coordinates | None = None,
    ) -> dict[str, TransportRoute]:
        """Pobiera trasy z atrakcji startowej do wskazanych lokali, zapisuje w cache i zwraca mapę po `to_location_id`."""
        raise NotImplementedError("Implement on branch feat/transport-client")
