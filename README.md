# Planer Wycieczek — Serwis Gastronomia

Mikroserwis zespołu **Gastronomia** (Speedkathon PSSO) zbudowany w **Pythonie 3.12**, **FastAPI** i **SQLite**.
Udostępnia listę lokali, obsługiwane diety oraz propozycje posiłków wzbogacone o czas i koszt dojazdu pobierane z serwisu **Transport**.

## Konwencje i jednostki

- **Format wymiany:** HTTP + JSON (`camelCase`, z obsługą aliasów `snake_case` w parametrach query).
- **Ceny:** wyłącznie w **groszach** (`int`, np. `2500` = 25,00 zł).
- **Czasy:** wyłącznie w **minutach** (`int`).
- **Dystans:** w **metrach** (`int | null`).
- **Obsługiwane diety:** `STANDARD`, `VEGETARIAN`, `VEGAN`, `GLUTEN_FREE`.
- **Obsługiwane tryby transportu:** `WALK`, `PUBLIC_TRANSPORT`, `CAR`, `TAXI`, `BIKE` *(kontrakt Transportu z `docs/KONTRAKT_API.md` używa `WALK`, `PUBLIC_TRANSPORT`, `CAR`)*.

---

## Wymagania i instalacja

```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# Linux/macOS:
# source .venv/bin/activate

pip install -r requirements.txt
```

## Konfiguracja `.env`

Skopiuj plik przykładowy i dopasuj adres serwisu Transport oraz tryb mocka:

```powershell
Copy-Item .env.example .env
```

Domyślne zmienne w [.env.example](.env.example):

```env
APP_NAME="Planer Wycieczek - Gastronomia"
HOST=0.0.0.0
PORT=8000
DB_PATH=gastronomia.db
TRANSPORT_BASE_URL=http://172.20.147.17:8083
TRANSPORT_ROUTES_PATH=/api/v1/routes
TRANSPORT_TIMEOUT_MS=2000
USE_MOCK_TRANSPORT=true
USE_CACHE_FALLBACK_ON_TRANSPORT_ERROR=true
RETRY_AFTER_SECONDS=60
```

- Przed podłączeniem żywego serwisu Transport zostaw `USE_MOCK_TRANSPORT=true`.
- Do pełnej integracji w sieci LAN ustaw `USE_MOCK_TRANSPORT=false` i sprawdź `TRANSPORT_BASE_URL`.

## Uruchomienie w Dockerze (bez instalacji Pythona)

### Docker Compose (zalecane)

```bash
docker compose up --build
```

- Domyślnie działa z mockiem Transportu (`USE_MOCK_TRANSPORT=true`).
- Aby połączyć się z żywym serwisem Transport, ustaw `USE_MOCK_TRANSPORT=false` w `.env` lub w zmiennych środowiskowych przed uruchomieniem:

```powershell
$env:USE_MOCK_TRANSPORT="false"
docker compose up --build
```

### Bezpośrednio przez `docker build` / `docker run`

```bash
docker build -t planer-wycieczek-gastronomia .
docker run --rm -p 8000:8000 planer-wycieczek-gastronomia
```

Z prawdziwym Transportem:

```bash
docker run --rm -p 8000:8000 -e USE_MOCK_TRANSPORT=false -e TRANSPORT_BASE_URL=http://172.20.147.17:8083 planer-wycieczek-gastronomia
```

Uruchomienie pełnych testów w kontenerze:

```bash
docker run --rm planer-wycieczek-gastronomia pytest -v
```

## Uruchomienie w sieci lokalnej (LAN)

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Po starcie:
- Dokumentacja Swagger UI: `http://<TWOJE_IP>:8000/docs`
- Healthcheck: `http://<TWOJE_IP>:8000/health`

> **Stan integracji (Faza 1 + Faza 2 + Faza 3 + Docker):** wszystkie 3 części są już połączone (`feat/db-and-seed` + `feat/transport-client` + `feat/api-and-integration`). Przy starcie serwis automatycznie tworzy bazę SQLite (`DB_PATH`) i idempotentnie zasila 4 lokale warszawskie (`rest-01`–`rest-04`, 10 posiłków) oraz tabelę `transport_cache`. Z `USE_MOCK_TRANSPORT=false` komunikuje się bezpośrednio z Transportem (`http://172.20.147.17:8083/api/v1/routes`) i korzysta z trwałego fallbacku w SQLite przy błędzie lub timeoucie. Endpoint `/api/gastronomy/proposals` akceptuje zarówno `transportMode` / `maxBudgetGroszy`, jak i aliasy `mode` / `maxBudgetGrosze`.

## Testy

```bash
pytest
```

---

## Kontrakt API dla zespołu Planer i integracja

### 1. `GET /health`
Sprawdza dostępność serwisu w sieci LAN.

```bash
curl http://localhost:8000/health
```

Odpowiedź `200 OK`:
```json
{
  "status": "ok",
  "service": "Planer Wycieczek - Gastronomia",
  "mockTransport": true
}
```

### 2. `GET /api/gastronomy/diets`
Zwraca listę obsługiwanych diet do formularza.

```bash
curl http://localhost:8000/api/gastronomy/diets
```

Odpowiedź `200 OK`:
```json
["STANDARD", "VEGETARIAN", "VEGAN", "GLUTEN_FREE"]
```

### 3. `GET /api/gastronomy/places`
Zwraca wszystkie lokale gastronomiczne wraz z posiłkami.

```bash
curl http://localhost:8000/api/gastronomy/places
```

### 4. `GET /api/gastronomy/places/{place_id}`
Zwraca szczegóły pojedynczego lokalu lub `404 Not Found`.

```bash
curl http://localhost:8000/api/gastronomy/places/place-1
```

Błąd `404 Not Found`:
```json
{
  "error": "PLACE_NOT_FOUND",
  "detail": "Place 'unknown' not found."
}
```

### 5. `GET /api/gastronomy/proposals`
Główny endpoint dla Planera. Łączy lokale pasujące do diety/budżetu z trasami z Transportu, odrzuca lokale bez połączenia (`available=false`), liczy koszt całkowity (`mealPriceGroszy + travelPriceGroszy`) i czas całkowity (`visitDurationMinutes + travelDurationMinutes`), filtruje po budżecie całkowitym i sortuje deterministycznie po cenie całkowitej, czasie całkowitym, `placeId` i `mealId`.

**Parametry query:**
- `fromLocationId` *(wymagany)* — np. `start` lub `attr-01`
- `transportMode` *(wymagany)* — `WALK`, `PUBLIC_TRANSPORT`, `CAR`, `TAXI`, `BIKE`
- `diet` *(opcjonalny)* — `STANDARD`, `VEGETARIAN`, `VEGAN`, `GLUTEN_FREE`
- `maxBudgetGroszy` *(opcjonalny, `>= 0`)* — maksymalny łączny koszt posiłku + dojazdu
- `fromLat`, `fromLng` *(opcjonalne, podawane razem)* — współrzędne punktu startowego

Przykładowe wywołanie `curl`:
```bash
curl "http://localhost:8000/api/gastronomy/proposals?fromLocationId=start&transportMode=CAR&diet=VEGAN&maxBudgetGroszy=5000"
```

Przykładowe wywołanie PowerShell:
```powershell
Invoke-RestMethod "http://localhost:8000/api/gastronomy/proposals?fromLocationId=start&transportMode=CAR&diet=VEGAN&maxBudgetGroszy=5000"
```

Odpowiedź `200 OK`:
```json
{
  "fromLocationId": "start",
  "transportMode": "CAR",
  "diet": "VEGAN",
  "proposals": [
    {
      "placeId": "place-2",
      "placeName": "Bar Mleczny Centrum",
      "locationId": "rest-02",
      "coordinates": {
        "lat": 52.2281,
        "lng": 21.0122
      },
      "mealId": "meal-2a",
      "mealName": "Krem z dyni i grzanki",
      "diets": ["VEGETARIAN", "VEGAN"],
      "mealPriceGroszy": 2200,
      "visitDurationMinutes": 30,
      "transportMode": "CAR",
      "travelDistanceMeters": 2100,
      "travelDurationMinutes": 7,
      "travelPriceGroszy": 1445,
      "totalPriceGroszy": 3645,
      "totalDurationMinutes": 37,
      "transportFromCache": false
    }
  ]
}
```

#### Obsługa błędów na `/api/gastronomy/proposals`
- **`400 Bad Request`** — błędne lub brakujące parametry wejściowe (bez wywoływania Transportu):
  ```json
  {
    "error": "INVALID_REQUEST",
    "detail": "Missing required query parameter: fromLocationId."
  }
  ```
- **`503 Service Unavailable`** — gdy Transport nie odpowiada, a cache nie zawiera tras (nagłówek `Retry-After: 60`):
  ```json
  {
    "error": "TRANSPORT_UNAVAILABLE",
    "detail": "Transport service timed out"
  }
  ```
