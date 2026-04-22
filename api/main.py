from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import admin, funds, health, holdings, macro, overview
from .settings import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="DB OCIO API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
    app.include_router(health.router, prefix="/api", tags=["health"])
    app.include_router(funds.router, prefix="/api", tags=["funds"])
    app.include_router(overview.router, prefix="/api", tags=["overview"])
    app.include_router(holdings.router, prefix="/api", tags=["holdings"])
    app.include_router(macro.router, prefix="/api", tags=["macro"])
    app.include_router(admin.router, prefix="/api", tags=["admin"])
    return app


app = create_app()
