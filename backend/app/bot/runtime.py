import asyncio
import contextlib
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

from app.bot.group_handlers import router as group_router
from app.bot.handlers import router
from app.services import AppServices

logger = logging.getLogger(__name__)


class BotRuntime:
    def __init__(self, token: str, services: AppServices) -> None:
        self.bot = Bot(token=token)
        self.dispatcher = Dispatcher()
        self.dispatcher.include_router(router)
        self.dispatcher.include_router(group_router)
        self.services = services
        self.task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        await self.bot.set_my_commands(
            [
                BotCommand(command="start", description="Начать работу"),
                BotCommand(command="run", description="Добавить пробежку"),
                BotCommand(command="stats", description="Статистика за все время"),
                BotCommand(command="week", description="Текущая неделя"),
                BotCommand(command="pr", description="Личные результаты"),
                BotCommand(command="privacy", description="Настройки приватности"),
                BotCommand(command="share", description="Sharing для группы"),
                BotCommand(command="setup_group", description="Настроить беговую группу"),
                BotCommand(command="join", description="Вступить в беговую группу"),
                BotCommand(command="leave", description="Покинуть беговую группу"),
                BotCommand(command="leaderboard", description="Рейтинг группы"),
                BotCommand(command="streaks", description="Серии по неделям"),
                BotCommand(command="imports", description="История импортов"),
                BotCommand(command="help", description="Помощь"),
            ]
        )
        self.task = asyncio.create_task(
            self.dispatcher.start_polling(
                self.bot,
                services=self.services,
                handle_signals=False,
                close_bot_session=False,
            ),
            name="telegram-polling",
        )
        logger.info("Telegram polling started")

    async def stop(self) -> None:
        if self.task is not None:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
        await self.bot.session.close()
        logger.info("Telegram polling stopped")
