# Transport (zespół 3): kontrakt API

Dokument dla zespołów **Atrakcje**, **Gastronomia** i **Planer**. Opisuje, co serwis Transport przyjmuje i co zwraca.

| | |
|---|---|
| Adres serwisu | `http://172.20.147.17:8083` |
| Format | HTTP + JSON, UTF-8 |
| Repozytorium | https://github.com/Hoxusik/PlanerWycieczek_Transport |
| Zalecany timeout po stronie klienta | **2 s** |

---

## Najważniejsze w 5 punktach

1. Jest **jeden punkt startowy**: `start`. Transport zna tylko odległości **`start` ↔ atrakcja** i **`start` ↔ lokal**.
2. Pytacie jednym żądaniem o wiele par naraz (`POST /api/v1/routes`).
3. Czas zawsze w **minutach**, koszt zawsze w **groszach na 1 osobę**. Oba to liczby całkowite.
4. Odcinki są symetryczne: `start → X` i `X → start` dają ten sam wynik.
5. **Brak połączenia to nie błąd**: dostajecie `200` i `"status": "NO_CONNECTION"` przy danej parze.

---

## `POST /api/v1/routes`

### Co przyjmujemy (żądanie)

```http
POST http://172.20.147.17:8083/api/v1/routes
Content-Type: application/json
```

| Pole | Typ | Wymagane | Dozwolone wartości / ograniczenia |
|---|---|---|---|
| `mode` | string | tak | `WALK`, `PUBLIC_TRANSPORT`, `CAR` (wielkie litery) |
| `pairs` | tablica | tak | od 1 do 500 elementów |
| `pairs[].fromLocationId` | string | tak | niepusty `locationId` |
| `pairs[].toLocationId` | string | tak | niepusty `locationId` |

Znaczenie trybów:

| `mode` | Znaczenie |
|---|---|
| `WALK` | pieszo, koszt zawsze 0 gr, tylko odcinki do 3,5 km |
| `PUBLIC_TRANSPORT` | komunikacja miejska, bilet 480 gr na odcinek |
| `CAR` | taxi |

Przykład:

```json
{
  "mode": "WALK",
  "pairs": [
    { "fromLocationId": "start",   "toLocationId": "attr-01" },
    { "fromLocationId": "attr-01", "toLocationId": "start" },
    { "fromLocationId": "start",   "toLocationId": "rest-01" },
    { "fromLocationId": "start",   "toLocationId": "attr-06" },
    { "fromLocationId": "attr-01", "toLocationId": "rest-01" }
  ]
}
```

### Co zwracamy (odpowiedź `200 OK`)

| Pole | Typ | Zawsze obecne | Opis |
|---|---|---|---|
| `mode` | string | tak | tryb z żądania |
| `results` | tablica | tak | **ta sama kolejność i liczba elementów co `pairs`** |
| `results[].fromLocationId` | string | tak | jak w żądaniu |
| `results[].toLocationId` | string | tak | jak w żądaniu |
| `results[].status` | string | tak | `OK` albo `NO_CONNECTION` |
| `results[].durationMin` | integer | **tylko przy `OK`** | czas przejazdu w minutach |
| `results[].costGrosze` | integer | **tylko przy `OK`** | koszt w groszach na 1 osobę |

Wartości `status`:

| `status` | Kiedy | `durationMin` / `costGrosze` |
|---|---|---|
| `OK` | odcinek istnieje w danym trybie | są wypełnione |
| `NO_CONNECTION` | brak odcinka w danym trybie, para bez `start` (np. atrakcja → lokal), nieznany `locationId` | **pól nie ma w JSON-ie** (nie są `null`) |

Szczególny przypadek: para z tym samym punktem (np. `start → start`) zwraca `OK`, `0` min i `0` gr.

Przykład odpowiedzi na żądanie powyżej:

```json
{
  "mode": "WALK",
  "results": [
    { "fromLocationId": "start",   "toLocationId": "attr-01", "status": "OK", "durationMin": 15, "costGrosze": 0 },
    { "fromLocationId": "attr-01", "toLocationId": "start",   "status": "OK", "durationMin": 15, "costGrosze": 0 },
    { "fromLocationId": "start",   "toLocationId": "rest-01", "status": "OK", "durationMin": 9,  "costGrosze": 0 },
    { "fromLocationId": "start",   "toLocationId": "attr-06", "status": "NO_CONNECTION" },
    { "fromLocationId": "attr-01", "toLocationId": "rest-01", "status": "NO_CONNECTION" }
  ]
}
```

---

## Błędy i niedostępność

| Sytuacja | Kod HTTP | Treść odpowiedzi | Co powinien zrobić klient |
|---|---|---|---|
| wszystko OK, także przy braku połączenia | `200` | jak wyżej | przy `NO_CONNECTION` odrzucić tę opcję |
| brak `mode` lub `pairs`, pusta lista, ponad 500 par, nieznany tryb, zły JSON | `400` | `{"error":"BAD_REQUEST","message":"..."}` | poprawić żądanie (błąd po stronie klienta) |
| wewnętrzny błąd Transportu | `500` | `{"error":"INTERNAL_ERROR","message":"..."}` | potraktować jak niedostępność |
| serwis nie odpowiada | — | timeout albo connection refused | po **2 s** przerwać i pokazać „usługa Transport niedostępna” |

Przykład `400`:

```json
{ "error": "BAD_REQUEST", "message": "Niepoprawny JSON albo nieznany tryb (dozwolone: WALK, PUBLIC_TRANSPORT, CAR)" }
```

> **Ważne:** `NO_CONNECTION` oznacza, że ta trasa nie istnieje, i może prowadzić do komunikatu „brak pasującego planu”. Kody `500` i timeout oznaczają **awarię Transportu**. To coś innego niż „brak planu”.

---

## Endpointy pomocnicze

| Żądanie | Odpowiedź |
|---|---|
| `GET /health` | `{"status":"UP", ...}` |
| `GET /api/v1/modes` | `["WALK","PUBLIC_TRANSPORT","CAR"]` |
| `GET /api/v1/locations` | `["attr-01", ..., "rest-04", "start"]`, czyli wszystkie znane `locationId` |

---

## Identyfikatory lokalizacji (`locationId`)

| `locationId` | Właściciel | Uwagi |
|---|---|---|
| `start` | Transport | jedyny punkt startowy i końcowy wycieczki |
| `attr-01` … `attr-06` | Atrakcje | **tymczasowe**, podmienimy na Wasze ID |
| `rest-01` … `rest-04` | Gastronomia | **tymczasowe**, podmienimy na Wasze ID |

**Prośba do Atrakcji i Gastronomii:** podeślijcie listę swoich `locationId` (np. `muzeum-narodowe`, `bistro-zielone`) z przybliżoną odległością albo dzielnicą względem punktu `start`. Dodamy je do tabeli.

---

## Aktualna tabela odcinków (czas min / koszt gr)

Wartości obowiązują w obie strony (`start → X` = `X → start`).

| `start` ↔ | `WALK` | `PUBLIC_TRANSPORT` | `CAR` |
|---|---|---|---|
| `attr-01` | 15 / 0 | 9 / 480 | 6 / 1320 |
| `attr-02` | 21 / 0 | 11 / 480 | 7 / 1495 |
| `attr-03` | 28 / 0 | 12 / 480 | 8 / 1705 |
| `attr-04` | 29 / 0 | 13 / 480 | 8 / 1740 |
| `attr-05` | `NO_CONNECTION` | 17 / 480 | 11 / 2230 |
| `attr-06` | `NO_CONNECTION` | 28 / 480 | 19 / 3560 |
| `rest-01` | 9 / 0 | 8 / 480 | 5 / 1145 |
| `rest-02` | 22 / 0 | 11 / 480 | 7 / 1530 |
| `rest-03` | 34 / 0 | 14 / 480 | 9 / 1880 |
| `rest-04` | `NO_CONNECTION` | 26 / 480 | 17 / 3245 |

Przykład ręcznego liczenia: `PUBLIC_TRANSPORT`, `start → attr-02 → start` = 11 + 11 = **22 min**, 480 + 480 = **960 gr**.

Ta tabela posłuży do mockowania, zanim podłączycie się do działającego serwisu.

---

## Szybki test

PowerShell:

```powershell
Invoke-RestMethod http://172.20.147.17:8083/api/v1/routes -Method Post -ContentType 'application/json' -Body '{"mode":"WALK","pairs":[{"fromLocationId":"start","toLocationId":"attr-01"}]}'
```

curl:

```bash
curl -X POST http://172.20.147.17:8083/api/v1/routes -H "Content-Type: application/json" -d '{"mode":"WALK","pairs":[{"fromLocationId":"start","toLocationId":"attr-01"}]}'
```

Python (`requests`):

```python
import requests

resp = requests.post(
    "http://172.20.147.17:8083/api/v1/routes",
    json={"mode": "WALK", "pairs": [{"fromLocationId": "start", "toLocationId": "rest-01"}]},
    timeout=2,
)
resp.raise_for_status()  # 400/500 -> wyjątek
for r in resp.json()["results"]:
    if r["status"] == "OK":
        print(r["toLocationId"], r["durationMin"], "min", r["costGrosze"], "gr")
    else:
        print(r["toLocationId"], "brak połączenia")
```

Java (Spring `RestClient`):

```java
var body = Map.of("mode", "WALK",
        "pairs", List.of(Map.of("fromLocationId", "start", "toLocationId", "attr-01")));
var response = RestClient.create("http://172.20.147.17:8083")
        .post().uri("/api/v1/routes")
        .contentType(MediaType.APPLICATION_JSON)
        .body(body)
        .retrieve()
        .body(Map.class);
```

---

## Kontakt

Zespół Transport, osoba kontaktowa: _do uzupełnienia_
