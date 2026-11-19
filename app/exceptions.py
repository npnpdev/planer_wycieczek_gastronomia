class GastronomyError(Exception):
    """Bazowy wyjątek domenowy serwisu Gastronomia."""


class InvalidRequestError(GastronomyError):
    """Błąd walidacji danych wejściowych po stronie klienta (HTTP 400)."""


class PlaceNotFoundError(GastronomyError):
    """Nie znaleziono lokalu o podanym identyfikatorze (HTTP 404)."""


class TransportUnavailableError(GastronomyError):
    """Serwis Transport jest niedostępny lub przekroczył timeout (HTTP 503)."""
