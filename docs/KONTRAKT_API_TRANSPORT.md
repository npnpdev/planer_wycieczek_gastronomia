# Transport (zespół 3): kontrakt API

**Adres:** `http://172.20.147.17:8083` · HTTP + JSON · zalecany timeout klienta **2 s**

**Zasady:**
- Jeden punkt startowy `start`. Znamy tylko odcinki **`start` ↔ atrakcja** i **`start` ↔ lokal**, w obie strony tak samo.
- Czas w **minutach**, koszt w **groszach na 1 osobę**, oba jako liczby całkowite.
- Tryby: `WALK`, `PUBLIC_TRANSPORT`, `CAR`.
- **Brak połączenia to nie błąd**: zwracamy `200`.

---

## `GET /api/v1/locations/{locationId}/transport-options`

Wszystkie dostępne tryby dotarcia ze `start` do atrakcji albo lokalu, z czasem i kosztem w jedną stronę.

```http
GET /api/v1/locations/ATR_001/transport-options
```
```json
{
  "fromLocationId": "start",
  "toLocationId": "ATR_001",
  "options": [
    { "mode": "WALK",             "durationMin": 15, "costGrosze": 0 },
    { "mode": "PUBLIC_TRANSPORT", "durationMin": 9,  "costGrosze": 480 },
    { "mode": "CAR",              "durationMin": 6,  "costGrosze": 1320 }
  ]
}
```
- Tryby bez połączenia są pominięte.
- Nieznany `locationId` daje `"options": []`.

---

## `POST /api/v1/routes`

Czas i koszt dla wielu par w jednym trybie: `mode` jest wymagany, `pairs` ma od 1 do 500 elementów.

```json
{
  "mode": "WALK",
  "pairs": [
    { "fromLocationId": "start",   "toLocationId": "ATR_001" },
    { "fromLocationId": "start",   "toLocationId": "rest-04" }
  ]
}
```
```json
{
  "mode": "WALK",
  "results": [
    { "fromLocationId": "start", "toLocationId": "ATR_001", "status": "OK", "durationMin": 15, "costGrosze": 0 },
    { "fromLocationId": "start", "toLocationId": "rest-04", "status": "NO_CONNECTION" }
  ]
}
```
- `results` mają tę samą kolejność co `pairs`.
- `NO_CONNECTION` oznacza, że pól `durationMin` i `costGrosze` nie ma. Dotyczy braku odcinka, pary bez `start` i nieznanego ID.

---

## Błędy

| Sytuacja | Odpowiedź |
|---|---|
| brak połączenia | `200`: `NO_CONNECTION` albo puste `options` |
| błędne żądanie (brak pól, nieznany tryb, zły JSON) | `400` `{"error":"BAD_REQUEST","message":"..."}` |
| awaria Transportu | `500` `{"error":"INTERNAL_ERROR","message":"..."}` |
| brak odpowiedzi w 2 s | traktować jako „Transport niedostępny”, a nie „brak planu” |

Pomocnicze: `GET /health`, `GET /api/v1/modes`, `GET /api/v1/locations`.

---

## Aktualne dane (czas min / koszt gr, w jedną stronę)

| `start` ↔ | `WALK` | `PUBLIC_TRANSPORT` | `CAR` |
|---|---|---|---|
| `ATR_001` | 15 / 0 | 9 / 480 | 6 / 1320 |
| `ATR_002` | 21 / 0 | 11 / 480 | 7 / 1495 |
| `ATR_004` | 29 / 0 | 13 / 480 | 8 / 1740 |
| `rest-01` | 9 / 0 | 8 / 480 | 5 / 1145 |
| `rest-02` | 22 / 0 | 11 / 480 | 7 / 1530 |
| `rest-03` | 34 / 0 | 14 / 480 | 9 / 1880 |
| `rest-04` | brak | 26 / 480 | 17 / 3245 |

ID lokali `rest-0x` są tymczasowe. Gastronomio, podeślijcie swoje ID.

Kontakt: _do uzupełnienia_
