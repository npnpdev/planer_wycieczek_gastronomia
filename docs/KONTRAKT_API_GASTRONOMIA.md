# Gastronomia (zespół 2): kontrakt API

Dokument dla zespołów **Planer i integracja** oraz **Transport**. Opisuje rzeczywisty kontrakt HTTP + JSON udostępniany przez serwis Gastronomia.

| | |
|---|---|
| Adres serwisu | `http://172.20.147.27:8000` |
| Format | HTTP + JSON (`camelCase`), UTF-8 |
| Dokumentacja interaktywna | `http://172.20.147.27:8000/docs` (Swagger UI) |
| Repozytorium | https://github.com/npnpdev/planer_wycieczek_gastronomia |
| Zalecany timeout po stronie klienta | **3 s** |
| Nasz dostawca | Transport, `POST http://172.20.147.17:8083/api/v1/routes`, timeout **2 s** |

---

## Najważniejsze w 5 punktach

1. Główny endpoint to `GET /api/gastronomy/proposals`. Zwraca posiłki pasujące do diety i budżetu razem z dojazdem od wskazanej atrakcji.
2. **Dojazd liczymy przez punkt `start`**, bo Transport zna tylko odcinki `start ↔ X`: dojazd = `atrakcja → start` + `start → lokal`.
3. Ceny są w **groszach na 1 osobę**, czasy w **minutach** (liczby całkowite), a godziny otwarcia `openingFrom` / `openingTo` w formacie `"HH:MM"`.
4. **Brak pasujących propozycji to nie błąd.** Dostajecie `200` i `"proposals": []`.
5. **Awaria Transportu to błąd `503`** z nagłówkiem `Retry-After: 60`. Wcześniej próbujemy ostatnich znanych tras z cache w SQLite — wtedy propozycje mają `"transportFromCache": true`.

---

## `GET /api/gastronomy/proposals`

### Co przyjmujemy (parametry query)

```http
GET http://172.20.147.27:8000/api/gastronomy/proposals?fromLocationId=ATR_002&transportMode=PUBLIC_TRANSPORT&diet=VEGETARIAN&maxBudgetGroszy=4500
```

| Parametr | Alias(y) | Typ | Wymagany | Dozwolone wartości / ograniczenia |
|---|---|---|---|---|
| `fromLocationId` | `from_location_id` | string | tak | niepusty `locationId` pierwszej atrakcji (np. `ATR_001`, `ATR_002`, `ATR_004`) lub `start` |
| `transportMode` | `mode`, `transport_mode` | string | tak | `WALK`, `PUBLIC_TRANSPORT`, `CAR` *(wielkość liter bez znaczenia; akceptowane są też `TAXI` mapowane na `CAR` i `BIKE` bez połączeń)* |
| `diet` | — | string | nie | `STANDARD`, `VEGETARIAN`, `VEGAN`, `GLUTEN_FREE` |
| `maxBudgetGroszy` | `maxBudgetGrosze`, `max_budget_groszy` | integer | nie | `>= 0`, limit na **posiłek + dojazd** (`totalPriceGroszy`) |
| `fromLat`, `fromLng` | `from_lat`, `from_lng` | number | nie | opcjonalne współrzędne punktu startowego (podawane razem, `-90..90` i `-180..180`) |

Znaczenie `diet`:

| `diet` | Które posiłki zwracamy |
|---|---|
| brak parametru albo `STANDARD` | wszystkie |
| `VEGETARIAN` / `VEGAN` / `GLUTEN_FREE` | tylko posiłki oznaczone tą dietą |

### Jak liczymy wynik

Najpierw pytamy Transport o odcinki od `fromLocationId` do lokali; gdy Transport nie ma połączeń bezpośrednich (`fromLocationId != "start"`), składamy dwie kwerendy: `fromLocationId → start` oraz `start → rest-01..04`:

| Pole | Wzór |
|---|---|
| `travelDurationMinutes` | `durationMin(fromLocationId → start)` + `durationMin(start → lokal)` |
| `travelPriceGroszy` | `costGrosze(fromLocationId → start)` + `costGrosze(start → lokal)` |
| `totalPriceGroszy` | `mealPriceGroszy` + `travelPriceGroszy` |
| `totalDurationMinutes` | `visitDurationMinutes` + `travelDurationMinutes` |

Reguły:

- Jeśli którykolwiek z dwóch odcinków ma w Transporcie `NO_CONNECTION`, lokal **odpada**. Nie zwracamy go i nie traktujemy tego jako błąd.
- Gdy `fromLocationId = start`, odpytujemy bezpośrednio pary `start → lokal`.
- Odrzucamy propozycje z `totalPriceGroszy > maxBudgetGroszy`, o ile podano limit budżetu.
- **Jedna propozycja = jeden posiłek.** Lokal z trzema pasującymi posiłkami daje trzy propozycje.
- Sortowanie jest deterministyczne: `totalPriceGroszy` ↑, potem `totalDurationMinutes` ↑, potem `placeId` ↑, potem `mealId` ↑.
- Powrotu (`lokal → druga atrakcja → start`) **nie liczymy**. Te odcinki Planer pobiera sam z Transportu.
- Zwracamy `openingFrom` i `openingTo` lokalu (`"HH:MM"` lub `null`), żeby Planer mógł odfiltrować lokale zamknięte o danej porze dnia (np. `rest-04` otwarte od `17:00`).

### Co zwracamy (odpowiedź `200 OK`)

| Pole | Typ | Zawsze obecne | Opis |
|---|---|---|---|
| `fromLocationId` | string | tak | jak w żądaniu |
| `transportMode` | string | tak | znormalizowany tryb transportu (`WALK` / `PUBLIC_TRANSPORT` / `CAR` / ...) |
| `diet` | string \| null | tak | jak w żądaniu, `null` gdy nie podano |
| `proposals` | tablica | tak | posortowane propozycje, może być pusta |
| `proposals[].placeId` | string | tak | ID lokalu, równe jego `locationId` (`rest-01` … `rest-04`) |
| `proposals[].placeName` | string | tak | nazwa lokalu |
| `proposals[].locationId` | string | tak | `locationId` lokalu u Transportu (`rest-01` … `rest-04`) |
| `proposals[].coordinates` | obiekt | tak | `{"lat": number, "lng": number}` |
| `proposals[].mealId` | string | tak | ID posiłku |
| `proposals[].mealName` | string | tak | nazwa posiłku |
| `proposals[].diets` | tablica string | tak | diety, które spełnia posiłek |
| `proposals[].mealPriceGroszy` | integer | tak | cena posiłku, 1 osoba |
| `proposals[].visitDurationMinutes` | integer | tak | czas pobytu w lokalu |
| `proposals[].openingFrom` | string \| null | tak | godzina otwarcia `"HH:MM"` |
| `proposals[].openingTo` | string \| null | tak | godzina zamknięcia `"HH:MM"` |
| `proposals[].transportMode` | string | tak | tryb transportu |
| `proposals[].travelDistanceMeters` | integer \| null | tak | dystans w metrach (`null` dla prawdziwego Transportu, liczba dla mocka) |
| `proposals[].travelDurationMinutes` | integer | tak | dojazd przez `start` |
| `proposals[].travelPriceGroszy` | integer | tak | koszt dojazdu przez `start`, 1 osoba |
| `proposals[].totalPriceGroszy` | integer | tak | posiłek + dojazd |
| `proposals[].totalDurationMinutes` | integer | tak | wizyta + dojazd |
| `proposals[].transportFromCache` | boolean | tak | `true`, gdy trasy pochodzą z naszego cache SQLite, bo Transport nie odpowiadał |

Przykład odpowiedzi na żądanie powyżej (`ATR_002`, `PUBLIC_TRANSPORT`, `VEGETARIAN`, budżet `4500` gr, z prawdziwym Transportem):

```json
{
  "fromLocationId": "ATR_002",
  "transportMode": "PUBLIC_TRANSPORT",
  "diet": "VEGETARIAN",
  "proposals": [
    {
      "placeId": "rest-01",
      "placeName": "Bar Mleczny Familijny",
      "locationId": "rest-01",
      "coordinates": { "lat": 52.2337, "lng": 21.0187 },
      "mealId": "familijny-zupa-pomidorowa",
      "mealName": "Zupa pomidorowa",
      "diets": ["VEGETARIAN"],
      "mealPriceGroszy": 900,
      "visitDurationMinutes": 30,
      "openingFrom": "08:00",
      "openingTo": "19:00",
      "transportMode": "PUBLIC_TRANSPORT",
      "travelDistanceMeters": null,
      "travelDurationMinutes": 19,
      "travelPriceGroszy": 960,
      "totalPriceGroszy": 1860,
      "totalDurationMinutes": 49,
      "transportFromCache": false
    },
    {
      "placeId": "rest-01",
      "placeName": "Bar Mleczny Familijny",
      "locationId": "rest-01",
      "coordinates": { "lat": 52.2337, "lng": 21.0187 },
      "mealId": "familijny-pierogi-ruskie",
      "mealName": "Pierogi ruskie",
      "diets": ["VEGETARIAN"],
      "mealPriceGroszy": 1800,
      "visitDurationMinutes": 30,
      "openingFrom": "08:00",
      "openingTo": "19:00",
      "transportMode": "PUBLIC_TRANSPORT",
      "travelDistanceMeters": null,
      "travelDurationMinutes": 19,
      "travelPriceGroszy": 960,
      "totalPriceGroszy": 2760,
      "totalDurationMinutes": 49,
      "transportFromCache": false
    },
    {
      "placeId": "rest-02",
      "placeName": "Zielona Miska",
      "locationId": "rest-02",
      "coordinates": { "lat": 52.2295, "lng": 21.0124 },
      "mealId": "zielona-bowl-falafel",
      "mealName": "Bowl z falafelem",
      "diets": ["VEGAN", "VEGETARIAN"],
      "mealPriceGroszy": 3200,
      "visitDurationMinutes": 45,
      "openingFrom": "10:00",
      "openingTo": "21:00",
      "transportMode": "PUBLIC_TRANSPORT",
      "travelDistanceMeters": null,
      "travelDurationMinutes": 22,
      "travelPriceGroszy": 960,
      "totalPriceGroszy": 4160,
      "totalDurationMinutes": 67,
      "transportFromCache": false
    }
  ]
}
```

---

## Błędy i niedostępność

Format błędu jest ujednolicony w `ErrorResponse`: `{"error": "<KOD>", "detail": "..."}`.

| Sytuacja | Kod HTTP | Treść odpowiedzi | Co powinien zrobić klient |
|---|---|---|---|
| wszystko OK, także gdy nic nie pasuje | `200` | jak wyżej, ewentualnie `"proposals": []` | pusta lista oznacza brak lokalu w budżecie lub z dojazdem, czyli może prowadzić do „brak pasującego planu” |
| brak `fromLocationId` lub `transportMode`/`mode`, nieznany tryb lub dieta, `maxBudgetGroszy` ujemny lub nie liczba | `400` | `{"error":"INVALID_REQUEST","detail":"..."}` | poprawić żądanie (błąd po stronie klienta) |
| nieznany lokal w `GET /api/gastronomy/places/{place_id}` | `404` | `{"error":"PLACE_NOT_FOUND","detail":"..."}` | sprawdzić ID |
| Transport nie odpowiada (timeout 2 s, `500`, brak sieci) **i** nie mamy tras w cache | `503` + nagłówek `Retry-After: 60` | `{"error":"TRANSPORT_UNAVAILABLE","detail":"..."}` | pokazać „usługa Transport niedostępna”, ewentualnie ponowić po `Retry-After` sekundach |
| Transport nie odpowiada, ale mamy trasy w cache SQLite | `200` | propozycje z `"transportFromCache": true` | użyć normalnie, można oznaczyć dane jako „ostatnie znane” |
| Gastronomia nie odpowiada | — | timeout albo connection refused | po **3 s** przerwać i pokazać „usługa Gastronomia niedostępna” |

Przykład `400`:

```json
{
  "error": "INVALID_REQUEST",
  "detail": "Unsupported transportMode 'SPACESHIP'. Allowed values: WALK, PUBLIC_TRANSPORT, CAR, TAXI, BIKE."
}
```

> **Ważne:** pusta lista `proposals` (`200`) oznacza, że nic nie pasuje. `503` oznacza **awarię Transportu**. To coś innego niż „brak planu”.

---

## Endpointy pomocnicze

| Żądanie | Odpowiedź |
|---|---|
| `GET /health` | `{"status":"ok","service":"Planer Wycieczek - Gastronomia","mockTransport":false}` |
| `GET /api/gastronomy/diets` | `["STANDARD","VEGETARIAN","VEGAN","GLUTEN_FREE"]` |
| `GET /api/gastronomy/places` | lista lokali z posiłkami (format niżej) |
| `GET /api/gastronomy/places/{place_id}` | jeden lokal albo `404` (`PLACE_NOT_FOUND`) |

Format lokalu (`Place` dla `GET /api/gastronomy/places/rest-01`):

```json
{
  "id": "rest-01",
  "name": "Bar Mleczny Familijny",
  "locationId": "rest-01",
  "city": "Warszawa",
  "address": "ul. Nowy Świat 39",
  "coordinates": { "lat": 52.2337, "lng": 21.0187 },
  "visitDurationMinutes": 30,
  "openingFrom": "08:00",
  "openingTo": "19:00",
  "meals": [
    {
      "id": "familijny-zupa-pomidorowa",
      "placeId": "rest-01",
      "name": "Zupa pomidorowa",
      "priceGroszy": 900,
      "diets": ["VEGETARIAN"]
    },
    {
      "id": "familijny-pierogi-ruskie",
      "placeId": "rest-01",
      "name": "Pierogi ruskie",
      "priceGroszy": 1800,
      "diets": ["VEGETARIAN"]
    },
    {
      "id": "familijny-schabowy",
      "placeId": "rest-01",
      "name": "Kotlet schabowy z ziemniakami",
      "priceGroszy": 2600,
      "diets": ["STANDARD"]
    }
  ]
}
```

---

## Lokale i posiłki (dane w bazie SQLite `app/db/seed.py`)

`locationId` lokali są takie same jak w tabeli Transportu (`rest-01` … `rest-04`).

| `id` / `locationId` | Nazwa (adres) | Wizyta | Godziny otwarcia | Posiłki (`id`, nazwa, cena gr, diety) |
|---|---|---|---|---|
| `rest-01` | Bar Mleczny Familijny (`ul. Nowy Świat 39`) | 30 min | `08:00`–`19:00` | `familijny-zupa-pomidorowa` Zupa pomidorowa 900 (`VEGETARIAN`); `familijny-pierogi-ruskie` Pierogi ruskie 1800 (`VEGETARIAN`); `familijny-schabowy` Kotlet schabowy z ziemniakami 2600 (`STANDARD`) |
| `rest-02` | Zielona Miska (`ul. Chmielna 10`) | 45 min | `10:00`–`21:00` | `zielona-bowl-falafel` Bowl z falafelem 3200 (`VEGAN`, `VEGETARIAN`); `zielona-curry` Curry z ciecierzycą i ryżem 3600 (`GLUTEN_FREE`, `VEGAN`, `VEGETARIAN`) |
| `rest-03` | Trattoria pod Łazienkami (`ul. Agrykola 1`) | 60 min | `11:00`–`22:00` | `trattoria-margherita` Pizza Margherita 3900 (`VEGETARIAN`); `trattoria-carbonara` Spaghetti carbonara 4500 (`STANDARD`); `trattoria-risotto` Risotto z grzybami 4800 (`GLUTEN_FREE`, `VEGETARIAN`) |
| `rest-04` | Restauracja Belweder (`ul. Belwederska 52`) | 150 min | `17:00`–`23:00` | `belweder-menu-wege` Menu degustacyjne wege 28000 (`VEGETARIAN`); `belweder-menu-degustacyjne` Menu degustacyjne (7 dań) 32000 (`STANDARD`) |

---

## Ręcznie policzony scenariusz

Żądanie: `fromLocationId=ATR_002`, `transportMode=PUBLIC_TRANSPORT`, `diet=VEGETARIAN`, `maxBudgetGroszy=4500`.

Odcinek `ATR_002 → start` = **11 min / 480 gr** (z tabeli Transportu).

| Lokal | `start → lokal` | Dojazd razem | Posiłek wegetariański | Koszt razem | Czas razem | W budżecie 4500? |
|---|---|---|---|---|---|---|
| `rest-01` | 8 / 480 | 19 min / 960 gr | `familijny-zupa-pomidorowa` 900 | **1860** | 30 + 19 = **49** | tak |
| `rest-01` | 8 / 480 | 19 min / 960 gr | `familijny-pierogi-ruskie` 1800 | **2760** | 30 + 19 = **49** | tak |
| `rest-02` | 11 / 480 | 22 min / 960 gr | `zielona-bowl-falafel` 3200 | **4160** | 45 + 22 = **67** | tak |
| `rest-02` | 11 / 480 | 22 min / 960 gr | `zielona-curry` 3600 | 4560 | 67 | nie |
| `rest-03` | 14 / 480 | 25 min / 960 gr | `trattoria-margherita` 3900 | 4860 | 85 | nie |
| `rest-03` | 14 / 480 | 25 min / 960 gr | `trattoria-risotto` 4800 | 5760 | 85 | nie |
| `rest-04` | 26 / 480 | 37 min / 960 gr | `belweder-menu-wege` 28000 | 28960 | 187 | nie *(i otwarte od 17:00)* |

Wynik po sortowaniu po koszcie: `familijny-zupa-pomidorowa` (1860), `familijny-pierogi-ruskie` (2760), `zielona-bowl-falafel` (4160). Odpowiada to przykładowi JSON wyżej.

Dodatkowe przypadki kontrolne:
- `fromLocationId=ATR_001` + `mode=WALK` + `maxBudgetGroszy=500` → `200`, `"proposals": []` (najtańszy posiłek kosztuje 900 gr — scenariusz „brak pasującego planu”).
- `fromLocationId=start` + `mode=WALK` → `rest-04` odrzucone (`NO_CONNECTION` pieszo).

---

## Co wysyłamy do Transportu

Dla `fromLocationId=ATR_002` wysyłamy żądania o odcinek `ATR_002 → start` oraz `start → rest-01..04` na `POST /api/v1/routes`:

```json
{
  "mode": "PUBLIC_TRANSPORT",
  "pairs": [
    { "fromLocationId": "start", "toLocationId": "rest-01" },
    { "fromLocationId": "start", "toLocationId": "rest-02" },
    { "fromLocationId": "start", "toLocationId": "rest-03" },
    { "fromLocationId": "start", "toLocationId": "rest-04" }
  ]
}
```

- Timeout: **2 s**, zgodnie z zaleceniem Transportu.
- `200` z `NO_CONNECTION` to brak trasy, a nie awaria.
- `4xx`/`5xx`, timeout i brak sieci traktujemy jako niedostępność. Wtedy próbujemy cache w SQLite, a bez cache zwracamy `503`.
- Każdą udaną odpowiedź zapisujemy w cache (`transport_cache` w SQLite), żeby mieć dane na wypadek awarii.

---

## Szybki test

PowerShell:

```powershell
Invoke-RestMethod "http://172.20.147.27:8000/api/gastronomy/proposals?fromLocationId=ATR_002&transportMode=PUBLIC_TRANSPORT&diet=VEGETARIAN&maxBudgetGroszy=4500"
```

curl:

```bash
curl "http://172.20.147.27:8000/api/gastronomy/proposals?fromLocationId=ATR_002&transportMode=PUBLIC_TRANSPORT&diet=VEGETARIAN&maxBudgetGroszy=4500"
```

Python (`requests`):

```python
import requests

resp = requests.get(
    "http://172.20.147.27:8000/api/gastronomy/proposals",
    params={
        "fromLocationId": "ATR_002",
        "transportMode": "PUBLIC_TRANSPORT",
        "diet": "VEGETARIAN",
        "maxBudgetGroszy": 4500,
    },
    timeout=3,
)
if resp.status_code == 503:
    print("Transport niedostępny, spróbuj za", resp.headers.get("Retry-After"), "s")
else:
    resp.raise_for_status()  # 400 -> wyjątek
    for p in resp.json()["proposals"]:
        print(p["placeName"], p["mealName"], p["totalPriceGroszy"], "gr", p["totalDurationMinutes"], "min")
```

---

## Kontakt

Zespół Gastronomia, osoba kontaktowa: Paweł Reguła
