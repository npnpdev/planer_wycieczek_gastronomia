from app.schemas import TransportRoute, TransportRouteRequest


class MockTransportClient:
    """Deterministyczny mock klienta Transportu do pracy offline przed integracją."""

    async def fetch_routes(self, request: TransportRouteRequest) -> list[TransportRoute]:
        """Zwraca deterministyczne czasy i koszty przejazdów w minutach i groszach."""
        raise NotImplementedError("Implement on branch feat/transport-client")
