from pathlib import Path

from app.schemas import DietType, Place, TransportMode, TransportRoute


class GastronomyRepository:
    """Repozytorium SQLite obsługujące lokale, posiłki i cache tras z Transportu."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = db_path

    def get_all_places(self) -> list[Place]:
        """Zwraca wszystkie lokale wraz z ich posiłkami."""
        raise NotImplementedError("Implement on branch feat/db-and-seed")

    def get_place_by_id(self, place_id: str) -> Place | None:
        """Zwraca pojedynczy lokal po `place_id` albo `None`, jeśli nie istnieje."""
        raise NotImplementedError("Implement on branch feat/db-and-seed")

    def find_places_with_meals(
        self,
        diet: DietType | None = None,
        max_meal_price_groszy: int | None = None,
    ) -> list[Place]:
        """Zwraca lokale zawierające co najmniej jeden posiłek pasujący do filtrów."""
        raise NotImplementedError("Implement on branch feat/db-and-seed")

    def get_cached_route(
        self,
        from_location_id: str,
        to_location_id: str,
        transport_mode: TransportMode,
    ) -> TransportRoute | None:
        """Odczytuje zapisaną trasę dla pojedynczej pary i trybu transportu."""
        raise NotImplementedError("Implement on branch feat/db-and-seed")

    def get_cached_routes(
        self,
        from_location_id: str,
        to_location_ids: list[str],
        transport_mode: TransportMode,
    ) -> dict[str, TransportRoute]:
        """Odczytuje zapisane trasy z `from_location_id` do wskazanych lokalizacji."""
        raise NotImplementedError("Implement on branch feat/db-and-seed")

    def upsert_cached_routes(self, routes: list[TransportRoute]) -> None:
        """Zapisuje lub nadpisuje trasy w tabeli `transport_cache`."""
        raise NotImplementedError("Implement on branch feat/db-and-seed")
