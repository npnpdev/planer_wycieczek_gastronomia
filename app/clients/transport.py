from typing import Protocol

from app.schemas import TransportRoute, TransportRouteRequest


class TransportClient(Protocol):
    """Interfejs klienta do pobierania tras przejazdów z serwisu Transport."""

    async def fetch_routes(self, request: TransportRouteRequest) -> list[TransportRoute]:
        """Pobiera koszty i czasy przejazdów dla wskazanych par lokalizacji."""
        ...


class HttpTransportClient:
    """Klient HTTP komunikujący się z zewnętrznym serwisem Transport."""

    def __init__(
        self,
        base_url: str,
        routes_path: str = "/api/transport/routes",
        timeout_seconds: float = 5.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.routes_path = routes_path
        self.timeout_seconds = timeout_seconds

    async def fetch_routes(self, request: TransportRouteRequest) -> list[TransportRoute]:
        """Wysyła zapytanie HTTP do Transportu i mapuje odpowiedź na `TransportRoute`."""
        raise NotImplementedError("Implement on branch feat/transport-client")
