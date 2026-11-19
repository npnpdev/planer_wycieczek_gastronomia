from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.config import get_settings
from app.db.database import init_db
from app.db.seed import seed_database
from app.exceptions import (
    InvalidRequestError,
    PlaceNotFoundError,
    TransportUnavailableError,
)
from app.schemas import ErrorResponse


def create_app(*, init_storage: bool = True) -> FastAPI:
    """Tworzy i konfiguruje aplikację FastAPI serwisu Gastronomia."""
    active_settings = get_settings()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if init_storage:
            current_settings = get_settings()
            init_db(current_settings.db_path)
            seed_database(current_settings.db_path)
        yield

    application = FastAPI(
        title=active_settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.exception_handler(InvalidRequestError)
    async def invalid_request_handler(_: Request, exc: InvalidRequestError) -> JSONResponse:
        payload = ErrorResponse(error="INVALID_REQUEST", detail=str(exc)).model_dump(
            by_alias=True
        )
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=payload)

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = "; ".join(
            f"{'.'.join(str(part) for part in err['loc'])}: {err['msg']}"
            for err in exc.errors()
        )
        payload = ErrorResponse(error="INVALID_REQUEST", detail=details).model_dump(
            by_alias=True
        )
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=payload)

    @application.exception_handler(PlaceNotFoundError)
    async def place_not_found_handler(_: Request, exc: PlaceNotFoundError) -> JSONResponse:
        payload = ErrorResponse(error="PLACE_NOT_FOUND", detail=str(exc)).model_dump(
            by_alias=True
        )
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=payload)

    @application.exception_handler(TransportUnavailableError)
    async def transport_unavailable_handler(
        _: Request, exc: TransportUnavailableError
    ) -> JSONResponse:
        current_settings = get_settings()
        payload = ErrorResponse(
            error="TRANSPORT_UNAVAILABLE",
            detail=str(exc),
        ).model_dump(by_alias=True)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            headers={"Retry-After": str(current_settings.retry_after_seconds)},
            content=payload,
        )

    application.include_router(router)
    return application


app = create_app()
