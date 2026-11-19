# Gastronomia (zespół 2): kontrakt API

Dokument dla zespołów **Planer i integracja** oraz **Transport**. Opisuje, co serwis Gastronomia przyjmuje, co zwraca i z czego sam korzysta.

| | |
|---|---|
| Adres serwisu | `http://172.20.147.27:8000` |
| Format | HTTP + JSON, UTF-8 |
| Dokumentacja interaktywna | `http://172.20.147.27:8000/docs` (Swagger) |
| Repozytorium | https://github.com/npnpdev/planer_wycieczek_gastronomia |
| Zalecany timeout po stronie klienta | **3 s** |
| Nasz dostawca | Transport, `POST http://172.20.147.17:8083/api/v1/routes`, timeout 2 s |

---

## Najważniejsze w 5 punktach

1. Główny endpoint to `GET /api/gastronomy/proposals`. Zwraca posiłki pasujące do diety i budżetu razem z dojazdem od wskazanej atrakcji.
2. **Dojazd liczymy przez punkt `start`**, bo Transport zna tylko odcinki `start ↔ X`: dojazd = `atrakcja → start` + `start → lokal`.
3. Czas zawsze w **minutach**, koszt zawsze w **groszach na 1 osobę**. Oba to liczby całkowite. Tryby przemieszczania są takie same jak w Transporcie: `WALK`, `PUBLIC_TRANSPORT`, `CAR`.
4. **Brak pasujących propozycji to nie błąd.** Dostajecie `200` i `"proposals": []`.
5. **Awaria Transportu to błąd `503`** z nagłówkiem `Retry-After`. Wcześniej próbujemy ostatnich znanych tras z naszego cache. Wtedy propozycje mają `"transportFromCache": true`.

---

## `GET /api/gastronomy/proposals`

### Co przyjmujemy (parametry query)

```http
GET http://172.20.147.27:8000/api/gastronomy/proposals?fromLocationId=attr-02&mode=PUBLIC_TRANSPORT&diet=VEGETARIAN&maxBudgetGrosze=3600
```

| Parametr | Typ | Wymagany | Dozwolone wartości / ograniczenia |
|---|---|---|---|
| `fromLocationId` | string | tak | niepusty `locationId` pierwszej atrakcji (np. `attr-02`); może być też `start` |
| `mode` | string | tak | `WALK`, `PUBLIC_TRANSPORT`, `CAR` (wielkie litery, jak w Transporcie) |
| `diet` | string | nie | `STANDARD`, `VEGETARIAN`, `VEGAN`, `GLUTEN_FREE` |
| `maxBudgetGrosze` | integer | nie | `>= 0`, limit na **posiłek + dojazd** (`totalCostGrosze`) |

Znaczenie `diet`:

| `diet` | Które posiłki zwracamy |
|---|---|
| brak parametru albo `STANDARD` | wszystkie |
| `VEGETARIAN` / `VEGAN` / `GLUTEN_FREE` | tylko posiłki oznaczone tą dietą |

### Jak liczymy wynik

Dla każdego lokalu pytamy Transport jednym żądaniem o pary `fromLocationId → start` oraz `start → <locationId lokalu>`:

| Pole | Wzór |
|---|---|
| `travelDurationMin` | `durationMin(fromLocationId → start)` + `durationMin(start → lokal)` |
| `travelCostGrosze` | `costGrosze(fromLocationId → start)` + `costGrosze(start → lokal)` |
| `totalCostGrosze` | `mealCostGrosze` + `travelCostGrosze` |
| `totalDurationMin` | `visitDurationMin` + `travelDurationMin` |

Reguły:

- Jeśli którykolwiek z dwóch odcinków ma w Transporcie `NO_CONNECTION`, lokal **odpada**. Nie zwracamy go i nie traktujemy tego jako błąd.
- Gdy `fromLocationId = start`, pierwszy odcinek to `start → start` = 0 min, 0 gr.
- Odrzucamy propozycje z `totalCostGrosze > maxBudgetGrosze`, o ile podano `maxBudgetGrosze`.
- **Jedna propozycja = jeden posiłek.** Lokal z trzema pasującymi posiłkami daje trzy propozycje.
- Sortowanie jest deterministyczne: `totalCostGrosze` ↑, potem `totalDurationMin` ↑, potem `placeId` ↑, potem `mealId` ↑.
- Powrotu (`lokal → druga atrakcja → start`) **nie liczymy**. Te odcinki Planer pobiera sam z Transportu.

### Co zwracamy (odpowiedź `200 OK`)

| Pole | Typ | Zawsze obecne | Opis |
|---|---|---|---|
| `fromLocationId` | string | tak | jak w żądaniu |
| `mode` | string | tak | jak w żądaniu |
| `diet` | string \| null | tak | jak w żądaniu, `null` gdy nie podano |
| `maxBudgetGrosze` | integer \| null | tak | jak w żądaniu, `null` gdy nie podano |
| `proposals` | tablica | tak | posortowane propozycje, może być pusta |
| `proposals[].placeId` | string | tak | ID lokalu, równe jego `locationId` |
| `proposals[].placeName` | string | tak | nazwa lokalu |
| `proposals[].locationId` | string | tak | `locationId` lokalu u Transportu (`rest-01` … `rest-04`) |
| `proposals[].mealId` | string | tak | ID posiłku |
| `proposals[].mealName` | string | tak | nazwa posiłku |
| `proposals[].diets` | tablica string | tak | diety, które spełnia posiłek |
| `proposals[].mealCostGrosze` | integer | tak | cena posiłku, 1 osoba |
| `proposals[].visitDurationMin` | integer | tak | czas pobytu w lokalu |
| `proposals[].travelDurationMin` | integer | tak | dojazd przez `start` |
| `proposals[].travelCostGrosze` | integer | tak | koszt dojazdu przez `start`, 1 osoba |
| `proposals[].totalCostGrosze` | integer | tak | posiłek + dojazd |
| `proposals[].totalDurationMin` | integer | tak | wizyta + dojazd |
| `proposals[].transportFromCache` | boolean | tak | `true`, gdy trasy pochodzą z naszego cache, bo Transport nie odpowiadał |

Przykład odpowiedzi na żądanie powyżej (`attr-02`, `PUBLIC_TRANSPORT`, `VEGETARIAN`, budżet 3600 gr):

```json
{
  "fromLocationId": "attr-02",
  "mode": "PUBLIC_TRANSPORT",
  "diet": "VEGETARIAN",
  "maxBudgetGrosze": 3600,
  "proposals": [
    {
      "placeId": "rest-01", "placeName": "Bistro Zielone", "locationId": "rest-01",
      "mealId": "meal-01", "mealName": "Krem z dyni", "diets": ["VEGETARIAN", "VEGAN", "GLUTEN_FREE"],
      "mealCostGrosze": 1800, "visitDurationMin": 45,
      "travelDurationMin": 19, "travelCostGrosze": 960,
      "totalCostGrosze": 2760, "totalDurationMin": 64,
      "transportFromCache": false
    },
    {
      "placeId": "rest-04", "placeName": "Karczma pod Lasem", "locationId": "rest-04",
      "mealId": "meal-08", "mealName": "Placki ziemniaczane", "diets": ["VEGETARIAN"],
      "mealCostGrosze": 2400, "visitDurationMin": 75,
      "travelDurationMin": 37, "travelCostGrosze": 960,
      "totalCostGrosze": 3360, "totalDurationMin": 112,
      "transportFromCache": false
    },
    {
      "placeId": "rest-02", "placeName": "Pierogarnia Stary Rynek", "locationId": "rest-02",
      "mealId": "meal-03", "mealName": "Pierogi ruskie", "diets": ["VEGETARIAN"],
      "mealCostGrosze": 2600, "visitDurationMin": 50,
      "travelDurationMin": 22, "travelCostGrosze": 960,
      "totalCostGrosze": 3560, "totalDurationMin": 72,
      "transportFromCache": false
    }
  ]
}
```

---

## Błędy i niedostępność

Format błędu jest taki sam jak w Transporcie: `{"error": "<KOD>", "message": "..."}`.

| Sytuacja | Kod HTTP | Treść odpowiedzi | Co powinien zrobić klient |
|---|---|---|---|
| wszystko OK, także gdy nic nie pasuje | `200` | jak wyżej, ewentualnie `"proposals": []` | pusta lista oznacza brak lokalu w budżecie lub z dojazdem, czyli może prowadzić do „brak pasującego planu” |
| brak `fromLocationId` lub `mode`, nieznany tryb lub dieta, `maxBudgetGrosze` ujemny lub nie liczba | `400` | `{"error":"BAD_REQUEST","message":"..."}` | poprawić żądanie |
| nieznany lokal w `GET /api/gastronomy/places/{placeId}` | `404` | `{"error":"NOT_FOUND","message":"..."}` | sprawdzić ID |
| Transport nie odpowiada (timeout 2 s, `500`, brak sieci) **i** nie mamy tras w cache | `503` + nagłówek `Retry-After: 60` | `{"error":"TRANSPORT_UNAVAILABLE","message":"..."}` | pokazać „usługa Transport niedostępna”, ewentualnie ponowić po `Retry-After` sekundach |
| Transport nie odpowiada, ale mamy trasy w cache | `200` | propozycje z `"transportFromCache": true` | użyć normalnie, można oznaczyć dane jako „ostatnie znane” |
| Gastronomia nie odpowiada | — | timeout albo connection refused | po **3 s** przerwać i pokazać „usługa Gastronomia niedostępna” |

Przykład `400`:

```json
{ "error": "BAD_REQUEST", "message": "Nieznany tryb 'TAXI' (dozwolone: WALK, PUBLIC_TRANSPORT, CAR)" }
```

> **Ważne:** pusta lista `proposals` (`200`) oznacza, że nic nie pasuje. `503` oznacza **awarię Transportu**. To coś innego niż „brak planu”.

---

## Endpointy pomocnicze

| Żądanie | Odpowiedź |
|---|---|
| `GET /health` | `{"status":"UP","service":"gastronomia","mockTransport":false}` |
| `GET /api/gastronomy/diets` | `["STANDARD","VEGETARIAN","VEGAN","GLUTEN_FREE"]` |
| `GET /api/gastronomy/places` | lista lokali z posiłkami (format niżej) |
| `GET /api/gastronomy/places/{placeId}` | jeden lokal albo `404` |

Format lokalu:

```json
{
  "placeId": "rest-01",
  "name": "Bistro Zielone",
  "locationId": "rest-01",
  "visitDurationMin": 45,
  "meals": [
    { "mealId": "meal-01", "name": "Krem z dyni", "costGrosze": 1800, "diets": ["VEGETARIAN", "VEGAN", "GLUTEN_FREE"] },
    { "mealId": "meal-02", "name": "Burger wegański", "costGrosze": 3200, "diets": ["VEGETARIAN", "VEGAN"] }
  ]
}
```

---

## Lokale i posiłki (dane do pokazu)

`locationId` lokali są takie same jak w tabeli Transportu.

| `placeId` / `locationId` | Nazwa | Wizyta | Posiłki (cena gr, diety) |
|---|---|---|---|
| `rest-01` | Bistro Zielone | 45 min | `meal-01` Krem z dyni 1800 (VEGETARIAN, VEGAN, GLUTEN_FREE); `meal-02` Burger wegański 3200 (VEGETARIAN, VEGAN) |
| `rest-02` | Pierogarnia Stary Rynek | 50 min | `meal-03` Pierogi ruskie 2600 (VEGETARIAN); `meal-04` Pierogi z mięsem 2800 (STANDARD) |
| `rest-03` | Trattoria Sole | 60 min | `meal-05` Pizza margherita 3400 (VEGETARIAN); `meal-06` Risotto z grzybami 3900 (VEGETARIAN, GLUTEN_FREE) |
| `rest-04` | Karczma pod Lasem | 75 min | `meal-07` Żurek 2200 (STANDARD); `meal-08` Placki ziemniaczane 2400 (VEGETARIAN) |

Z tych danych i tabeli Transportu możecie liczyć wyniki ręcznie i mockować nasze odpowiedzi, zanim serwis będzie gotowy.

---

## Ręcznie policzony scenariusz

Żądanie: `fromLocationId=attr-02`, `mode=PUBLIC_TRANSPORT`, `diet=VEGETARIAN`, `maxBudgetGrosze=3600`.

Odcinek `attr-02 → start` = **11 min / 480 gr** (z tabeli Transportu).

| Lokal | `start → lokal` | Dojazd razem | Posiłek wegetariański | Koszt razem | Czas razem | W budżecie 3600? |
|---|---|---|---|---|---|---|
| `rest-01` | 8 / 480 | 19 min / 960 gr | `meal-01` 1800 | **2760** | 45 + 19 = **64** | tak |
| `rest-01` | 8 / 480 | 19 min / 960 gr | `meal-02` 3200 | 4160 | 64 | nie |
| `rest-02` | 11 / 480 | 22 min / 960 gr | `meal-03` 2600 | **3560** | 50 + 22 = **72** | tak |
| `rest-03` | 14 / 480 | 25 min / 960 gr | `meal-05` 3400 | 4360 | 85 | nie |
| `rest-03` | 14 / 480 | 25 min / 960 gr | `meal-06` 3900 | 4860 | 85 | nie |
| `rest-04` | 26 / 480 | 37 min / 960 gr | `meal-08` 2400 | **3360** | 75 + 37 = **112** | tak |

Wynik po sortowaniu po koszcie: `meal-01` (2760), `meal-08` (3360), `meal-03` (3560). Odpowiada to przykładowi JSON wyżej.

Ten sam scenariusz w trybie `WALK` odrzuca `rest-04`, bo `start ↔ rest-04` ma `NO_CONNECTION`. Dla `fromLocationId=attr-05` w trybie `WALK` lista jest pusta, bo `attr-05 → start` ma `NO_CONNECTION`.

---

## Co wysyłamy do Transportu

Jedno żądanie na wywołanie `proposals`, z parą `fromLocationId → start` i parami `start → lokal` dla wszystkich lokali:

```json
{
  "mode": "PUBLIC_TRANSPORT",
  "pairs": [
    { "fromLocationId": "attr-02", "toLocationId": "start" },
    { "fromLocationId": "start",   "toLocationId": "rest-01" },
    { "fromLocationId": "start",   "toLocationId": "rest-02" },
    { "fromLocationId": "start",   "toLocationId": "rest-03" },
    { "fromLocationId": "start",   "toLocationId": "rest-04" }
  ]
}
```

- Timeout: **2 s**, zgodnie z zaleceniem Transportu.
- `200` z `NO_CONNECTION` to brak trasy, a nie awaria.
- `500`, timeout i brak sieci traktujemy jako niedostępność. Wtedy próbujemy cache, a bez cache zwracamy `503`.
- Każdą udaną odpowiedź zapisujemy w cache (SQLite), żeby mieć dane na wypadek awarii.

---

## Szybki test

PowerShell:

```powershell
Invoke-RestMethod "http://172.20.147.27:8000/api/gastronomy/proposals?fromLocationId=attr-02&mode=PUBLIC_TRANSPORT&diet=VEGETARIAN&maxBudgetGrosze=3600"
```

curl:

```bash
curl "http://172.20.147.27:8000/api/gastronomy/proposals?fromLocationId=attr-02&mode=PUBLIC_TRANSPORT&diet=VEGETARIAN&maxBudgetGrosze=3600"
```

Python (`requests`):

```python
import requests

resp = requests.get(
    "http://172.20.147.27:8000/api/gastronomy/proposals",
    params={"fromLocationId": "attr-02", "mode": "PUBLIC_TRANSPORT", "diet": "VEGETARIAN", "maxBudgetGrosze": 3600},
    timeout=3,
)
if resp.status_code == 503:
    print("Transport niedostępny, spróbuj za", resp.headers.get("Retry-After"), "s")
else:
    resp.raise_for_status()  # 400 -> wyjątek
    for p in resp.json()["proposals"]:
        print(p["placeName"], p["mealName"], p["totalCostGrosze"], "gr", p["totalDurationMin"], "min")
```

---

## Kontakt

Zespół Gastronomia, osoba kontaktowa: Paweł Reguła
