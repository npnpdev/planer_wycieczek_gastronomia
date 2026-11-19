"""Deterministyczny mock serwisu Transport (włączany przez `USE_MOCK_TRANSPORT=true`).

Zasady (wszystko deterministyczne, symetryczne: A -> B == B -> A):
1. Ta sama lokalizacja po obu stronach -> `OK`, 0 min, 0 gr, 0 m.
2. Pary `start <-> X` z tabeli w `docs/KONTRAKT_API.md` -> dokładnie wartości z kontraktu.
3. Tryby nieobsługiwane przez Transport (np. `BIKE`, patrz `MODE_MAP`) -> brak połączenia.
4. Pary dwóch znanych ID z kontraktu bez `start` (np. `attr-01 -> rest-01`) -> brak połączenia,
   tak jak w prawdziwym Transporcie.
5. Pozostałe pary -> dystans z współrzędnych (haversine x współczynnik objazdu), a gdy ich brak —
   ze stabilnego hasha ID; z dystansu liczone są czas i koszt wg profilu trybu.
"""

import hashlib
import math

from app.clients.transport import MODE_MAP
from app.schemas import Coordinates, LocationPair, TransportMode, TransportRoute, TransportRouteRequest

START_LOCATION_ID = "start"

# (minuty, grosze) lub None dla NO_CONNECTION; tryb TAXI odpowiada `CAR` w Transporcie.
_W, _P, _T = TransportMode.WALK, TransportMode.PUBLIC_TRANSPORT, TransportMode.TAXI
CONTRACT_TABLE: dict[str, dict[TransportMode, tuple[int, int] | None]] = {
    "attr-01": {_W: (15, 0), _P: (9, 480), _T: (6, 1320)},
    "attr-02": {_W: (21, 0), _P: (11, 480), _T: (7, 1495)},
    "attr-03": {_W: (28, 0), _P: (12, 480), _T: (8, 1705)},
    "attr-04": {_W: (29, 0), _P: (13, 480), _T: (8, 1740)},
    "attr-05": {_W: None, _P: (17, 480), _T: (11, 2230)},
    "attr-06": {_W: None, _P: (28, 480), _T: (19, 3560)},
    "rest-01": {_W: (9, 0), _P: (8, 480), _T: (5, 1145)},
    "rest-02": {_W: (22, 0), _P: (11, 480), _T: (7, 1530)},
    "rest-03": {_W: (34, 0), _P: (14, 480), _T: (9, 1880)},
    "rest-04": {_W: None, _P: (26, 480), _T: (17, 3245)},
}

# Profile prędkości/kosztów dla par spoza tabeli kontraktu.
WALK_METERS_PER_MIN = 80
WALK_MAX_METERS = 3500
PUBLIC_METERS_PER_MIN = 350
PUBLIC_WAIT_MIN = 5
PUBLIC_TICKET_GROSZY = 480
TAXI_METERS_PER_MIN = 500
TAXI_PICKUP_MIN = 2
TAXI_BASE_GROSZY = 800
TAXI_GROSZY_PER_KM = 300

DETOUR_FACTOR = 1.3
HASH_MIN_METERS = 500
HASH_SPAN_METERS = 7500
EARTH_RADIUS_METERS = 6_371_000


class MockTransportClient:
    """Deterministyczny mock klienta Transportu do pracy offline przed integracją."""

    async def fetch_routes(self, request: TransportRouteRequest) -> list[TransportRoute]:
        """Zwraca deterministyczne czasy i koszty przejazdów w minutach i groszach."""
        return [self.route_for(pair, request.transport_mode) for pair in request.pairs]

    def route_for(self, pair: LocationPair, mode: TransportMode) -> TransportRoute:
        """Wylicza trasę dla pojedynczej pary (metoda publiczna dla wygody testów)."""
        a, b = pair.from_location_id, pair.to_location_id
        base = {"from_location_id": a, "to_location_id": b, "transport_mode": mode}

        if mode not in MODE_MAP:
            return TransportRoute(**base, available=False)

        if a == b:
            return TransportRoute(**base, available=True, distance_meters=0, duration_minutes=0, price_groszy=0)

        contract = _contract_lookup(a, b, mode)
        if contract is not _NOT_IN_CONTRACT:
            if contract is None:
                return TransportRoute(**base, available=False)
            duration, price, distance = contract
            return TransportRoute(
                **base, available=True, distance_meters=distance, duration_minutes=duration, price_groszy=price
            )

        distance = _distance_meters(pair)
        estimate = _estimate(distance, mode)
        if estimate is None:
            return TransportRoute(**base, available=False)
        duration, price = estimate
        return TransportRoute(
            **base, available=True, distance_meters=distance, duration_minutes=duration, price_groszy=price
        )


_NOT_IN_CONTRACT = object()


def _contract_lookup(a: str, b: str, mode: TransportMode):
    """Zwraca (min, gr, m) z tabeli kontraktu, None dla NO_CONNECTION, albo `_NOT_IN_CONTRACT`."""
    known_a = a == START_LOCATION_ID or a in CONTRACT_TABLE
    known_b = b == START_LOCATION_ID or b in CONTRACT_TABLE
    if not (known_a and known_b):
        return _NOT_IN_CONTRACT
    if START_LOCATION_ID not in (a, b):
        return None  # Transport zna tylko odcinki start <-> X
    other = b if a == START_LOCATION_ID else a
    row = CONTRACT_TABLE[other]
    lookup_mode = TransportMode.TAXI if mode == TransportMode.CAR else mode
    entry = row.get(lookup_mode)
    if entry is None:
        return None
    return entry[0], entry[1], _contract_distance(row)


def _contract_distance(row: dict[TransportMode, tuple[int, int] | None]) -> int:
    """Szacuje dystans dla wiersza kontraktu (kontrakt nie podaje metrów)."""
    walk = row.get(TransportMode.WALK)
    if walk is not None:
        return walk[0] * WALK_METERS_PER_MIN
    taxi = row[TransportMode.TAXI]
    return taxi[0] * TAXI_METERS_PER_MIN if taxi else 0


def _distance_meters(pair: LocationPair) -> int:
    if pair.from_coordinates is not None and pair.to_coordinates is not None:
        return round(_haversine(pair.from_coordinates, pair.to_coordinates) * DETOUR_FACTOR)
    key = "|".join(sorted((pair.from_location_id, pair.to_location_id))).encode("utf-8")
    digest = int.from_bytes(hashlib.sha256(key).digest()[:8], "big")
    return HASH_MIN_METERS + digest % HASH_SPAN_METERS


def _haversine(a: Coordinates, b: Coordinates) -> float:
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlat = lat2 - lat1
    dlng = math.radians(b.lng - a.lng)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * EARTH_RADIUS_METERS * math.asin(math.sqrt(h))


def _estimate(distance: int, mode: TransportMode) -> tuple[int, int] | None:
    """Zwraca (minuty, grosze) dla dystansu w danym trybie albo None (brak połączenia)."""
    if mode == TransportMode.WALK:
        if distance > WALK_MAX_METERS:
            return None
        return math.ceil(distance / WALK_METERS_PER_MIN), 0
    if mode == TransportMode.PUBLIC_TRANSPORT:
        return PUBLIC_WAIT_MIN + math.ceil(distance / PUBLIC_METERS_PER_MIN), PUBLIC_TICKET_GROSZY
    if mode not in (TransportMode.TAXI, TransportMode.CAR):
        return None
    duration = TAXI_PICKUP_MIN + math.ceil(distance / TAXI_METERS_PER_MIN)
    price = TAXI_BASE_GROSZY + math.ceil(distance * TAXI_GROSZY_PER_KM / 1000)
    return duration, price
