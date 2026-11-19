"""Klient HTTP serwisu Transport.

To jest JEDYNY plik, który zna format JSON-a Transportu (patrz `docs/KONTRAKT_API.md`).
Jeśli Transport zmieni nazwę pola, ścieżkę albo nazwę trybu — poprawiamy stałe poniżej.
"""

import logging
from typing import Any, Protocol

import httpx

from app.config import Settings, get_settings
from app.exceptions import TransportUnavailableError
from app.schemas import LocationPair, TransportMode, TransportRoute, TransportRouteRequest

logger = logging.getLogger(__name__)

# --- Kontrakt Transportu: zmiany nazw pól / trybów poprawiamy wyłącznie tutaj --------------

#: Nasz `TransportMode` -> wartość pola `mode` w Transporcie. Tryb spoza mapy = brak połączenia.
MODE_MAP: dict[TransportMode, str] = {
    TransportMode.WALK: "WALK",
    TransportMode.PUBLIC_TRANSPORT: "PUBLIC_TRANSPORT",
    TransportMode.CAR: "CAR",
    TransportMode.TAXI: "CAR",
}

#: Maksymalna liczba par w jednym żądaniu (limit Transportu).
MAX_PAIRS_PER_REQUEST = 500

# Pola żądania
REQ_MODE = "mode"
REQ_PAIRS = "pairs"
REQ_FROM = "fromLocationId"
REQ_TO = "toLocationId"

# Pola odpowiedzi
RES_RESULTS = "results"
RES_FROM = "fromLocationId"
RES_TO = "toLocationId"
RES_STATUS = "status"
RES_DURATION = "durationMin"
RES_COST = "costGrosze"
RES_DISTANCE = "distanceMeters"  # opcjonalne — obecnie Transport go nie zwraca

STATUS_OK = "OK"

# -------------------------------------------------------------------------------------------


class TransportClient(Protocol):
    """Interfejs klienta do pobierania tras przejazdów z serwisu Transport."""

    async def fetch_routes(self, request: TransportRouteRequest) -> list[TransportRoute]:
        """Pobiera koszty i czasy przejazdów dla wskazanych par lokalizacji."""
        ...


def unavailable_route(pair: LocationPair, mode: TransportMode) -> TransportRoute:
    """Buduje trasę oznaczoną jako brak połączenia (`available=False`)."""
    return TransportRoute(
        from_location_id=pair.from_location_id,
        to_location_id=pair.to_location_id,
        transport_mode=mode,
        available=False,
    )


class HttpTransportClient:
    """Klient HTTP komunikujący się z zewnętrznym serwisem Transport."""

    def __init__(
        self,
        base_url: str,
        routes_path: str = "/api/v1/routes",
        timeout_seconds: float = 2.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.routes_path = routes_path if routes_path.startswith("/") else f"/{routes_path}"
        self.timeout_seconds = timeout_seconds
        self._transport = transport  # wstrzykiwany w testach (httpx.MockTransport)

    async def fetch_routes(self, request: TransportRouteRequest) -> list[TransportRoute]:
        """Wysyła zapytanie HTTP do Transportu i mapuje odpowiedź na `TransportRoute`.

        Brak połączenia dla pary -> `available=False`.
        Timeout / błąd sieci / status >= 400 / niepoprawna odpowiedź -> `TransportUnavailableError`.
        """
        mode = request.transport_mode
        pairs = request.pairs
        if not pairs:
            return []

        remote_mode = MODE_MAP.get(mode)
        if remote_mode is None:
            logger.info("Transport nie obsługuje trybu %s — wszystkie pary bez połączenia", mode.value)
            return [unavailable_route(pair, mode) for pair in pairs]

        routes: list[TransportRoute] = []
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            transport=self._transport,
        ) as client:
            for start in range(0, len(pairs), MAX_PAIRS_PER_REQUEST):
                chunk = pairs[start : start + MAX_PAIRS_PER_REQUEST]
                raw_results = await self._post_chunk(client, remote_mode, chunk)
                routes.extend(self._match_results(chunk, raw_results, mode))
        return routes

    async def _post_chunk(
        self,
        client: httpx.AsyncClient,
        remote_mode: str,
        pairs: list[LocationPair],
    ) -> list[Any]:
        payload = {
            REQ_MODE: remote_mode,
            REQ_PAIRS: [{REQ_FROM: p.from_location_id, REQ_TO: p.to_location_id} for p in pairs],
        }
        url = f"{self.base_url}{self.routes_path}"
        try:
            response = await client.post(self.routes_path, json=payload)
        except httpx.TimeoutException as exc:
            raise TransportUnavailableError(
                f"Transport nie odpowiedział w ciągu {self.timeout_seconds:g} s ({url})"
            ) from exc
        except httpx.RequestError as exc:
            raise TransportUnavailableError(
                f"Brak połączenia z Transportem ({url}): {exc.__class__.__name__}"
            ) from exc

        if response.status_code >= 400:
            hint = " (błąd żądania po stronie Gastronomii)" if 400 <= response.status_code < 500 else ""
            raise TransportUnavailableError(
                f"Transport zwrócił HTTP {response.status_code}{hint}: {response.text[:200]}"
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise TransportUnavailableError("Transport zwrócił niepoprawny JSON") from exc

        results = body.get(RES_RESULTS) if isinstance(body, dict) else None
        if not isinstance(results, list):
            raise TransportUnavailableError(f"Odpowiedź Transportu nie zawiera listy '{RES_RESULTS}'")
        return results

    def _match_results(
        self,
        pairs: list[LocationPair],
        raw_results: list[Any],
        mode: TransportMode,
    ) -> list[TransportRoute]:
        """Dopasowuje wyniki do par po (from, to); gdy brak ID w wyniku — po pozycji."""
        by_pair: dict[tuple[str, str], TransportRoute] = {}
        for index, raw in enumerate(raw_results):
            if not isinstance(raw, dict):
                raise TransportUnavailableError(f"Niepoprawny element '{RES_RESULTS}[{index}]' w odpowiedzi Transportu")
            fallback = pairs[index] if index < len(pairs) else None
            from_id = raw.get(RES_FROM) or (fallback.from_location_id if fallback else None)
            to_id = raw.get(RES_TO) or (fallback.to_location_id if fallback else None)
            if not from_id or not to_id:
                continue
            by_pair[(from_id, to_id)] = self._map_result(raw, from_id, to_id, mode)

        matched: list[TransportRoute] = []
        for pair in pairs:
            route = by_pair.get((pair.from_location_id, pair.to_location_id))
            if route is None:
                logger.warning(
                    "Transport nie zwrócił wyniku dla pary %s -> %s; traktuję jako brak połączenia",
                    pair.from_location_id,
                    pair.to_location_id,
                )
                route = unavailable_route(pair, mode)
            matched.append(route)
        return matched

    @staticmethod
    def _map_result(raw: dict[str, Any], from_id: str, to_id: str, mode: TransportMode) -> TransportRoute:
        """Mapuje pojedynczy element `results[]` Transportu na `TransportRoute`."""
        if raw.get(RES_STATUS) != STATUS_OK:
            return TransportRoute(
                from_location_id=from_id,
                to_location_id=to_id,
                transport_mode=mode,
                available=False,
            )
        return TransportRoute(
            from_location_id=from_id,
            to_location_id=to_id,
            transport_mode=mode,
            available=True,
            duration_minutes=_required_int(raw, RES_DURATION),
            price_groszy=_required_int(raw, RES_COST),
            distance_meters=_optional_int(raw, RES_DISTANCE),
        )


def _optional_int(raw: dict[str, Any], field: str) -> int | None:
    value = raw.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise TransportUnavailableError(f"Niepoprawna wartość pola '{field}' w odpowiedzi Transportu: {value!r}")
    return int(round(value))


def _required_int(raw: dict[str, Any], field: str) -> int:
    value = _optional_int(raw, field)
    if value is None:
        raise TransportUnavailableError(
            f"Brak pola '{field}' przy statusie {STATUS_OK} w odpowiedzi Transportu "
            "(zmiana kontraktu? popraw stałe w app/clients/transport.py)"
        )
    return value


def create_transport_client(settings: Settings | None = None) -> TransportClient:
    """Zwraca klienta Transportu wg konfiguracji: mock (`USE_MOCK_TRANSPORT=true`) albo HTTP."""
    settings = settings or get_settings()
    if settings.use_mock_transport:
        from app.clients.mock_transport import MockTransportClient

        return MockTransportClient()
    return HttpTransportClient(
        base_url=settings.transport_base_url,
        routes_path=settings.transport_routes_path,
        timeout_seconds=settings.transport_timeout_seconds,
    )
