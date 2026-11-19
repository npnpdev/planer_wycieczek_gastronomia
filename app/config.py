from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Konfiguracja serwisu Gastronomia wczytywana ze zmiennych środowiskowych / pliku .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Planer Wycieczek - Gastronomia"
    host: str = "0.0.0.0"
    port: int = 8000
    db_path: str = "gastronomia.db"
    transport_base_url: str = "http://127.0.0.1:8080"
    transport_routes_path: str = "/api/transport/routes"
    transport_timeout_ms: int = 5000
    use_mock_transport: bool = True
    use_cache_fallback_on_transport_error: bool = True
    retry_after_seconds: int = 60

    @property
    def transport_timeout_seconds(self) -> float:
        """Zwraca timeout zapytań HTTP do Transportu wyrażony w sekundach."""
        return self.transport_timeout_ms / 1000.0


@lru_cache
def get_settings() -> Settings:
    """Zwraca zcache'owaną instancję ustawień aplikacji."""
    return Settings()
