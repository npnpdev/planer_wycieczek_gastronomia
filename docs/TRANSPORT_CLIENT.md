# Klient Transportu, mock i RouteService — notatka od Agenta 2

Gałąź: `feat/transport-client`. Dotyczy plików:

- `app/clients/transport.py` — klient HTTP do serwisu Transport + fabryka klienta,
- `app/clients/mock_transport.py` — deterministyczny mock Transportu,
- `app/services/route_service.py` — orkiestracja: Transport → cache SQLite → fallback,
- `tests/test_transport_client.py` — 38 testów (nie wymagają działającej bazy ani Transportu).

Zamrożonych plików (`schemas.py`, `config.py`, `exceptions.py` itd.) nie zmieniałem.

---

## TL;DR

| Kto | Co musi wiedzieć |
|---|---|
| **Agent 1 (DB)** | `RouteService` woła tylko `upsert_cached_routes(...)` i `get_cached_routes(...)`. Cache musi przyjmować trasy z `available=False` i polami `None`. W seedzie użyj `location_id` = `rest-01` … `rest-04`. |
| **Agent 3 (API)** | Klienta tworzysz przez `create_transport_client(settings)`, trasy pobierasz przez `RouteService.get_routes_from_attraction(...)`. Brak klucza w zwróconej mapie = brak dojazdu. `TransportUnavailableError` → `503` + `Retry-After`. |
| **Wszyscy** | Transport zna tylko odcinki `start ↔ X`. Para atrakcja → lokal **zawsze** daje brak połączenia (także w mocku). |

---

## Jak to działa

```
Planer ──► Agent 3: GET /api/gastronomy/proposals
                 │
                 ▼
          RouteService.get_routes_from_attraction(from_location_id, places, mode)
                 │
                 ├─► client.fetch_routes(...)        (MockTransportClient albo HttpTransportClient)
                 │      sukces ──► repository.upsert_cached_routes(trasy) ──► zwrot mapy
                 │
                 └─► TransportUnavailableError
                        ├─ fallback włączony i cache ma trasy ──► zwrot z cache (from_cache=True)
                        └─ fallback wyłączony / cache pusty ──► TransportUnavailableError (→ 503)
```

Rozróżnienie, o które prosili organizatorzy:

| Sytuacja | Wynik |
|---|---|
| Transport odpowiedział, ale dla pary nie ma połączenia (`NO_CONNECTION`) | `TransportRoute(available=False, duration_minutes=None, price_groszy=None)` — to **nie** jest awaria |
| Timeout, connection refused, HTTP 4xx/5xx, zły JSON, brak wymaganego pola | `TransportUnavailableError` |

---

## Dla Agenta 1 — baza i repozytorium

`RouteService` używa **tylko dwóch** metod `GastronomyRepository`:

### `upsert_cached_routes(routes: list[TransportRoute]) -> None`

- Dostaje **wszystkie** trasy z udanego zapytania, także `available=False`. Brak połączenia też jest poprawną odpowiedzią, więc też go cache'ujemy.
- Przy `available=False` pola `distance_meters`, `duration_minutes`, `price_groszy` są `None` → kolumny w `transport_cache` muszą być **nullable**.
- `distance_meters` jest `None` także przy `available=True` z prawdziwego Transportu (Transport nie zwraca dystansu). Mock dystans podaje.
- Klucz: `(from_location_id, to_location_id, transport_mode)`; istniejący wiersz nadpisujemy (`INSERT ... ON CONFLICT DO UPDATE` albo `INSERT OR REPLACE`).
- `transport_mode` zapisuj jako `route.transport_mode.value` (np. `"TAXI"` — to **nasza** nazwa, nie `CAR` z Transportu).
- Pole `from_cache` **nie** musi trafiać do bazy.

### `get_cached_routes(from_location_id, to_location_ids, transport_mode) -> dict[str, TransportRoute]`

- Zwraca mapę `to_location_id → TransportRoute` tylko dla par, które są w cache; brakujących par po prostu nie ma w mapie (nie rzucaj wyjątku).
- Ustawianie `from_cache=True` **nie** jest wymagane — `RouteService` i tak to robi (`model_copy(update={"from_cache": True})`). Jeśli ustawisz, też będzie dobrze.

Gdy któraś z tych metod rzuci wyjątek, `RouteService` loguje go i działa dalej (zapis) albo traktuje cache jako pusty (odczyt). Błąd bazy nie wywróci więc odpowiedzi, ale zobaczysz go w logach.

### `location_id` w seedzie

Transport ma w tabeli tymczasowe ID lokali `rest-01` … `rest-04`. Jeśli seed użyje dokładnie tych `location_id`, mock i prawdziwy Transport od razu zwrócą realne wartości:

| `start ↔` | `WALK` | `PUBLIC_TRANSPORT` | `TAXI` (`CAR`) |
|---|---|---|---|
| `rest-01` | 9 min / 0 gr | 8 / 480 | 5 / 1145 |
| `rest-02` | 22 / 0 | 11 / 480 | 7 / 1530 |
| `rest-03` | 34 / 0 | 14 / 480 | 9 / 1880 |
| `rest-04` | brak połączenia | 26 / 480 | 17 / 3245 |

Dla innych ID (np. `bistro-zielone`) mock też działa — liczy dystans ze współrzędnych lokalu (dlatego spójne `lat`/`lng` w seedzie mają znaczenie), a prawdziwy Transport zwróci `NO_CONNECTION`, dopóki zespół Transport nie dopisze tych ID do swojej tabeli.

---

## Dla Agenta 3 — API i integracja

### Tworzenie klienta i serwisu (np. w `lifespan` albo zależności FastAPI)

```python
from app.clients.transport import create_transport_client
from app.config import get_settings
from app.db.repository import GastronomyRepository
from app.services.route_service import RouteService

settings = get_settings()
route_service = RouteService(
    client=create_transport_client(settings),  # mock gdy USE_MOCK_TRANSPORT=true
    repository=GastronomyRepository(settings.db_path),
    use_cache_fallback=settings.use_cache_fallback_on_transport_error,
)
```

Do `/health` (`mock_transport`) użyj `settings.use_mock_transport`.

### Pobieranie tras w `/proposals`

```python
routes = await route_service.get_routes_from_attraction(
    from_location_id=from_location_id,
    places=places,                    # lista Place z repozytorium
    transport_mode=transport_mode,
    from_coordinates=from_coords,     # opcjonalne (fromLat/fromLng) — używa ich tylko mock
)
# routes: dict[str, TransportRoute] po place.location_id
```

Jak interpretować wynik dla każdego lokalu:

```python
route = routes.get(place.location_id)
if route is None or not route.available:
    continue                          # brak dojazdu → lokal odpada
travel_minutes = route.duration_minutes   # int
travel_price = route.price_groszy         # int, grosze na 1 osobę
travel_distance = route.distance_meters   # int | None (prawdziwy Transport: zawsze None)
from_cache = route.from_cache             # → MealProposal.transport_from_cache
```

Jest też ogólniejsza metoda `route_service.get_routes(from_location_id, to_location_ids, transport_mode, coordinates=None)`, gdyby była potrzebna bez obiektów `Place`.

### Błędy

- `TransportUnavailableError` wylatuje z `get_routes_from_attraction` tylko wtedy, gdy Transport padł **i** nie ma czym go zastąpić (fallback wyłączony albo cache pusty). Mapuj na `503` z nagłówkiem `Retry-After: settings.retry_after_seconds` i `ErrorResponse`; `str(exc)` zawiera czytelny powód (timeout / HTTP 500 / brak połączenia).
- Pusta lista lokali → `{}` bez zapytania do Transportu.

### Tryby transportu

| Nasz `TransportMode` | Transport | Uwagi |
|---|---|---|
| `WALK` | `WALK` | koszt zawsze 0, max 3,5 km |
| `PUBLIC_TRANSPORT` | `PUBLIC_TRANSPORT` | 480 gr za odcinek |
| `TAXI` | `CAR` | mapowanie robi klient |
| `BIKE` | — | Transport nie obsługuje → wszystkie trasy `available=False`, bez zapytania HTTP (mock zachowuje się tak samo) |

### ⚠️ Problem do ustalenia z Planerem

Transport zna wyłącznie odcinki `start ↔ X`. Jeśli Planer zawoła `/proposals?fromLocationId=attr-01` (pierwsza atrakcja), każda para `attr-01 → rest-0x` da brak połączenia i lista propozycji będzie pusta. Mock odtwarza to zachowanie celowo, żeby problem wyszedł przed integracją. Do wyboru: Planer pyta z `fromLocationId=start` albo zespół Transport dopisuje odcinki atrakcja ↔ lokal.

---

## Konfiguracja `.env`

Domyślna ścieżka w `app/config.py` (`/api/transport/routes`) **nie zgadza się** z Transportem, a plik jest zamrożony — ustaw ją w lokalnym `.env`:

```env
# praca offline (domyślnie)
USE_MOCK_TRANSPORT=true

# prawdziwy Transport w LAN
USE_MOCK_TRANSPORT=false
TRANSPORT_BASE_URL=http://172.20.147.17:8083
TRANSPORT_ROUTES_PATH=/api/v1/routes
TRANSPORT_TIMEOUT_MS=2000
USE_CACHE_FALLBACK_ON_TRANSPORT_ERROR=true
```

## Gdy Transport zmieni JSON w trakcie hackathonu

Poprawiamy **tylko** stałe na górze `app/clients/transport.py`: `MODE_MAP`, `REQ_*` (pola żądania), `RES_*` (pola odpowiedzi), `STATUS_OK`, `MAX_PAIRS_PER_REQUEST`. Jeśli Transport przestanie wysyłać wymagane pole (np. zmieni `durationMin` na inną nazwę), klient rzuci `TransportUnavailableError` z komunikatem wskazującym brakujące pole — nie będzie po cichu zwracał samych „braków połączenia”.

## Testy

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pytest -q tests/test_transport_client.py
```

W testach jest `FakeRepository` (cache w pamięci) — możesz go podejrzeć jako wzór oczekiwanego zachowania `upsert_cached_routes` / `get_cached_routes`.
