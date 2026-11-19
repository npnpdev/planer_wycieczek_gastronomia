# Przewodnik współpracy dla zespołu Gastronomia (3 niezależnych agentów)

## Rola serwisu w systemie
- **Nazwa serwisu:** Gastronomia (Planer Wycieczek — Speedkathon PSSO)
- **Stack:** Python 3.12, FastAPI, SQLite (wbudowane `sqlite3`), `httpx`, Pydantic v2
- **Nasz klient:** `Planer i integracja` — odpytuje nas po HTTP + JSON o lokale i propozycje posiłków z czasem i kosztem dojazdu od pierwszej atrakcji.
- **Nasz dostawca:** `Transport` — odpytujemy go po HTTP + JSON o czas, dystans i koszt przejazdu dla par `fromLocationId` -> `toLocationId` w wybranym trybie przemieszczania się.

## Jednostki i konwencje
- **Ceny:** wyłącznie w **groszach** (`int`, np. `2500` = 25,00 zł).
- **Czasy:** wyłącznie w **minutach** (`int`).
- **Dystans:** w **metrach** (`int | None`).
- **Format pól JSON:** `camelCase` — obsługiwany automatycznie przez klasę bazową `CamelModel` w `app/schemas.py` (w Pythonie używamy `snake_case`, a Pydantic serializuje/parsuje `camelCase`).
- **Daty (jeśli występują):** `YYYY-MM-DD`.
- **Rozróżnienie błędów Transportu:**
  - brak połączenia dla danej pary -> `TransportRoute(available=False, ...)` (nie jest awarią serwisu),
  - błąd HTTP / timeout / brak sieci -> `TransportUnavailableError` (w zależności od konfiguracji fallback do cache SQLite lub `503 Service Unavailable` z nagłówkiem `Retry-After`).

## Zamrożone pliki wspólne (ZAKAZ EDYCJI na gałęziach feat/*)
Żaden z 3 agentów nie może modyfikować poniższych plików na swojej gałęzi roboczej (ewentualne zmiany kontraktów robimy wyłącznie przez ustalenie i osobny PR na `main`):
- `app/schemas.py`
- `app/config.py`
- `app/exceptions.py`
- `requirements.txt`
- `pyproject.toml`
- `.env.example`
- `.gitignore`

---

## Podział pracy na 3 agentów

### Agent 1 — Baza SQLite, Seed i Repozytorium
- **Gałąź:** `feat/db-and-seed`
- **Pliki własne:**
  - `app/db/database.py`
  - `app/db/repository.py`
  - `app/db/seed.py`
  - `tests/test_db.py`
- **Zakres obowiązków:**
  1. W `app/db/database.py`: implementacja `get_connection(db_path)` (z `row_factory = sqlite3.Row` i `PRAGMA foreign_keys = ON`) oraz `init_db(db_path)` tworzącego 3 tabele: `places`, `meals`, `transport_cache`.
  2. W `app/db/repository.py`: implementacja metod klasy `GastronomyRepository` (`get_all_places`, `get_place_by_id`, `find_places_with_meals`, `get_cached_route`, `get_cached_routes`, `upsert_cached_routes`) zgodnie z sygnaturami z Fazy 0.
  3. W `app/db/seed.py`: idempotentny `seed_database(db_path)` ładujący realistyczne lokale i posiłki (różne diety z `DietType`, różne ceny w groszach, czasy wizyty w minutach, spójne `location_id` oraz współrzędne).
- **Testy akceptacyjne (`tests/test_db.py`):**
  - tworzenie schematu na bazie `:memory:` / pliku tymczasowego,
  - idempotentność `seed_database` (podwójne wywołanie nie duplikuje rekordów),
  - filtrowanie po diecie i budżecie (`max_meal_price_groszy`),
  - zapis (`upsert_cached_routes`) i odczyt (`get_cached_route`, `get_cached_routes`) w `transport_cache` wraz z nadpisywaniem istniejących tras.

### Agent 2 — Klient HTTP Transportu, Cache/Fallback i Mock
- **Gałąź:** `feat/transport-client`
- **Pliki własne:**
  - `app/clients/transport.py`
  - `app/clients/mock_transport.py`
  - `app/services/route_service.py`
  - `tests/test_transport_client.py`
- **Zakres obowiązków:**
  1. W `app/clients/transport.py`: implementacja `HttpTransportClient.fetch_routes` przy użyciu `httpx.AsyncClient` i timeoutu ze settingsów; mapowanie odpowiedzi JSON Transportu na `list[TransportRoute]`; zgłaszanie `TransportUnavailableError` przy timeoutcie, błędzie sieciowym lub statusie `5xx`/`4xx` z Transportu.
  2. W `app/clients/mock_transport.py`: deterministyczna implementacja `MockTransportClient.fetch_routes` (współrzędne / hash ID -> przewidywalne `duration_minutes`, `price_groszy`, `distance_meters` oraz kontrolowane przypadki `available=False`), aby reszta zespołu mogła testować lokalnie bez działającego Transportu.
  3. W `app/services/route_service.py`: implementacja `RouteService.get_routes_from_attraction` — najpierw próba wywołania `client.fetch_routes`, przy sukcesie zapis tras w `repository.upsert_cached_routes`, przy `TransportUnavailableError` (jeśli `use_cache_fallback=True`) próba odczytu z `repository.get_cached_routes` (z `from_cache=True`), a gdy cache jest pusty lub fallback wyłączony — podniesienie `TransportUnavailableError`.
- **Testy akceptacyjne (`tests/test_transport_client.py`):**
  - testy `HttpTransportClient` na `httpx.MockTransport`: odpowiedź `200 OK` (trasa dostępna i niedostępna `available=False`), timeout, błąd sieci, `503` -> `TransportUnavailableError`,
  - testy `MockTransportClient`: deterministyczność i poprawność jednostek,
  - testy `RouteService`: zapis do repo po sukcesie z klienta, fallback do cache przy `TransportUnavailableError`, propagacja `TransportUnavailableError` przy braku danych w cache.

### Agent 3 — Endpointy FastAPI, Logika Propozycji i Dokumentacja
- **Gałąź:** `feat/api-and-integration`
- **Pliki własne:**
  - `app/main.py`
  - `app/api/routes.py`
  - `tests/test_api.py`
  - `README.md`
- **Zakres obowiązków:**
  1. W `app/main.py`: konfiguracja aplikacji FastAPI z `lifespan` (wywołanie `init_db` i `seed_database`), middleware CORS dla Planera/Reacta oraz handlery wyjątków (`InvalidRequestError` -> `400`, `PlaceNotFoundError` -> `404`, `TransportUnavailableError` -> `503` z nagłówkiem `Retry-After` i `ErrorResponse`).
  2. W `app/api/routes.py`: implementacja 5 endpointów:
     - `GET /health` -> `HealthResponse`
     - `GET /api/gastronomy/places` -> `list[Place]`
     - `GET /api/gastronomy/places/{place_id}` -> `Place` (lub `404` przez `PlaceNotFoundError`)
     - `GET /api/gastronomy/diets` -> lista obsługiwanych diet (`list[DietType]`)
     - `GET /api/gastronomy/proposals` -> `ProposalsResponse` (parametry query m.in. `fromLocationId` / `from_location_id`, `transportMode` / `transport_mode`, opcjonalnie `diet`, `maxBudgetGroszy` / `max_budget_groszy`, `fromLat`/`fromLng`); łączy lokale z repo i trasy z `RouteService`, odrzuca pary z `available=False`, wylicza `total_price_groszy = meal_price_groszy + travel_price_groszy` oraz `total_duration_minutes = visit_duration_minutes + travel_duration_minutes`, filtruje po budżecie całkowitym i sortuje deterministycznie.
  3. W `README.md`: instrukcja uruchomienia w sieci LAN (`uvicorn app.main:app --host 0.0.0.0 --port 8000`), konfiguracja `.env`, przykładowe żądania `curl` i JSON-y dla Planera.
- **Testy akceptacyjne (`tests/test_api.py`):**
  - testy przez `fastapi.testclient.TestClient` (z zamockowanym lub tymczasowym repo/klientem): `GET /health`, lista i szczegóły lokali (`200` i `404`), lista diet, `GET /api/gastronomy/proposals` (happy path, filtrowanie diety i budżetu, pusta lista gdy nic nie mieści się w budżecie, `400` przy błędnych parametrach, `503` + `Retry-After` przy niedostępności Transportu).

---

## Kolejność scalania (Merge Order na GitHubie)
Aby zachować czystą integrację bez konfliktów, PR-y łączymy do `main` w kolejności:
1. `feat/db-and-seed` -> `main`
2. `feat/transport-client` -> `main`
3. `feat/api-and-integration` -> `main`

Po każdym merge'u uruchamiamy `pytest` przed przyjęciem kolejnego PR-a.
