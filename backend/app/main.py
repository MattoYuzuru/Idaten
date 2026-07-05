import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.health import router as health_router
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

        runtime: BotRuntime | None = None
        if resolved_settings.bot_token:
            runtime = BotRuntime(resolved_settings.bot_token, services)
            await runtime.start()
        else:
            logger.warning("TELEGRAM_BOT_TOKEN is empty; polling is disabled")

        try:
            yield
        finally:
            if runtime is not None:
                await runtime.stop()
            await engine.dispose()

    app = FastAPI(title=resolved_settings.app_name, version="0.1.0", lifespan=lifespan)
    app.include_router(health_router)
    return app


app = create_app()
