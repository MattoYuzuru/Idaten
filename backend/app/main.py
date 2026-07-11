import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.health_connect import router as health_connect_router
from app.api.imports import router as imports_router
from app.bot.runtime import BotRuntime
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.db.session import build_engine, build_session_factory
from app.services import build_services

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = build_engine(resolved_settings.database_url)
        session_factory = build_session_factory(engine)
        services = build_services(session_factory, resolved_settings)
        app.state.engine = engine
        app.state.session_factory = session_factory
        app.state.services = services
        app.state.settings = resolved_settings

        runtime: BotRuntime | None = None
        if resolved_settings.bot_token:
            runtime = BotRuntime(
                resolved_settings.bot_token,
                services,
                outbox_poll_seconds=resolved_settings.outbox_poll_seconds,
            )
            await runtime.start()
        else:
            logger.warning("TELEGRAM_BOT_TOKEN is empty; polling is disabled")

        try:
            yield
        finally:
            if runtime is not None:
                await runtime.stop()
            await engine.dispose()

    app = FastAPI(title=resolved_settings.app_name, version="0.8.0", lifespan=lifespan)
    app.include_router(health_router)
    app.include_router(imports_router)
    app.include_router(health_connect_router)
    return app


app = create_app()
