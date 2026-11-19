from enum import Enum

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Bazowy model Pydantic serializujący i parsujący pola w camelCase."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class DietType(str, Enum):
    """Obsługiwane typy diet w posiłkach."""

    STANDARD = "STANDARD"
    VEGETARIAN = "VEGETARIAN"
    VEGAN = "VEGAN"
    GLUTEN_FREE = "GLUTEN_FREE"


class TransportMode(str, Enum):
    """Obsługiwane sposoby przemieszczania się między punktami."""

    WALK = "WALK"
    PUBLIC_TRANSPORT = "PUBLIC_TRANSPORT"
    TAXI = "TAXI"
    BIKE = "BIKE"


class Coordinates(CamelModel):
    """Współrzędne geograficzne punktu."""

    lat: float
    lng: float


class Meal(CamelModel):
    """Pojedyncza pozycja posiłku dostępna w lokalu."""

    id: str
    place_id: str
    name: str
    price_groszy: int = Field(ge=0)
    diets: list[DietType]


class Place(CamelModel):
    """Lokal gastronomiczny wraz z ofertą posiłków."""

    id: str
    name: str
    location_id: str
    city: str
    address: str | None = None
    coordinates: Coordinates
    visit_duration_minutes: int = Field(gt=0)
    meals: list[Meal] = Field(default_factory=list)


class LocationPair(CamelModel):
    """Para lokalizacji przekazywana w zapytaniu do serwisu Transport."""

    from_location_id: str
    to_location_id: str
    from_coordinates: Coordinates | None = None
    to_coordinates: Coordinates | None = None


class TransportRouteRequest(CamelModel):
    """Żądanie wyznaczenia tras wysyłane do serwisu Transport."""

    transport_mode: TransportMode
    pairs: list[LocationPair]


class TransportRoute(CamelModel):
    """Pojedynczy wynik przejazdu zwrócony przez Transport lub odczytany z cache."""

    from_location_id: str
    to_location_id: str
    transport_mode: TransportMode
    available: bool
    distance_meters: int | None = Field(default=None, ge=0)
    duration_minutes: int | None = Field(default=None, ge=0)
    price_groszy: int | None = Field(default=None, ge=0)
    from_cache: bool = False


class TransportRouteResponse(CamelModel):
    """Odpowiedź zbiorcza z serwisu Transport dla listy par lokalizacji."""

    transport_mode: TransportMode
    results: list[TransportRoute]


class MealProposal(CamelModel):
    """Propozycja posiłku wraz z kosztem i czasem dojazdu od pierwszej atrakcji."""

    place_id: str
    place_name: str
    location_id: str
    coordinates: Coordinates
    meal_id: str
    meal_name: str
    diets: list[DietType]
    meal_price_groszy: int = Field(ge=0)
    visit_duration_minutes: int = Field(gt=0)
    transport_mode: TransportMode
    travel_distance_meters: int | None = Field(default=None, ge=0)
    travel_duration_minutes: int = Field(ge=0)
    travel_price_groszy: int = Field(ge=0)
    total_price_groszy: int = Field(ge=0)
    total_duration_minutes: int = Field(gt=0)
    transport_from_cache: bool = False


class ProposalsResponse(CamelModel):
    """Odpowiedź głównego endpointu propozycji posiłków dla Planera."""

    from_location_id: str
    transport_mode: TransportMode
    diet: DietType | None = None
    proposals: list[MealProposal]


class HealthResponse(CamelModel):
    """Odpowiedź endpointu kontrolnego /health."""

    status: str
    service: str
    mock_transport: bool


class ErrorResponse(CamelModel):
    """Ujednolicony format błędu zwracany przez API."""

    error: str
    detail: str | None = None
