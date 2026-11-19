from fastapi import FastAPI

from app.api.routes import router
from app.config import get_settings

# Implement lifespan (init_db + seed_database), CORS, and exception handlers
# on branch feat/api-and-integration.
settings = get_settings()
app = FastAPI(title=settings.app_name)
app.include_router(router)
