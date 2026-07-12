import asyncio
import contextlib
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllChatAdministrators,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
)

from app.bot.group_handlers import router as group_router
from app.bot.handlers import router
from app.bot.next_handlers import router as next_router
from app.jobs.monthly import MonthlyReportJob
from app.services import AppServices

logger = logging.getLogger(__name__)

PRIVATE_BOT_COMMANDS = (
    BotCommand(command="start", description="Начать работу"),
    BotCommand(command="menu", description="Главное меню"),
    BotCommand(command="run", description="Добавить пробежку"),
    BotCommand(command="stats", description="Личный прогресс"),
    BotCommand(command="pr", description="Результаты и оценки"),
    BotCommand(command="next", description="Следующая тренировка"),
    BotCommand(command="privacy", description="Настройки приватности"),
    BotCommand(command="link", description="Подключить Health Connect"),
    BotCommand(command="devices", description="Связанные устройства"),
    BotCommand(command="revoke_device", description="Отозвать устройство"),
    BotCommand(command="help", description="Краткая помощь"),
)


class BotRuntime:
    def __init__(self, token: str, services: AppServices, *, outbox_poll_seconds: int = 5) -> None:
        self.bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        self.dispatcher = Dispatcher()
        self.dispatcher.include_router(next_router)
        self.dispatcher.include_router(router)
        self.dispatcher.include_router(group_router)
        self.services = services
        self.outbox_poll_seconds = outbox_poll_seconds
        self.task: asyncio.Task[None] | None = None
        self.outbox_task: asyncio.Task[None] | None = None
        self.monthly_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        await self.bot.set_my_commands(
            list(PRIVATE_BOT_COMMANDS),
            scope=BotCommandScopeAllPrivateChats(),
        )
        await self.bot.set_my_commands(
            [
                BotCommand(command="week", description="Неделя группы"),
                BotCommand(command="month", description="Месяц группы"),
                BotCommand(command="join", description="Вступить в беговую группу"),
                BotCommand(command="leave", description="Покинуть беговую группу"),
                BotCommand(command="leaderboard", description="Рейтинг группы"),
                BotCommand(command="streaks", description="Серии по неделям"),
                BotCommand(command="help", description="Помощь"),
            ],
            scope=BotCommandScopeAllGroupChats(),
        )
        await self.bot.set_my_commands(
            [
                BotCommand(command="setup_group", description="Настроить беговую группу"),
                BotCommand(command="group_goal", description="Цель группы на месяц"),
            ],
            scope=BotCommandScopeAllChatAdministrators(),
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
        self.outbox_task = asyncio.create_task(self._outbox_loop(), name="telegram-outbox")
        self.monthly_task = asyncio.create_task(self._monthly_loop(), name="monthly-reports")
        logger.info("Telegram polling started")

    async def stop(self) -> None:
        if self.task is not None:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
        if self.outbox_task is not None:
            self.outbox_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.outbox_task
        if self.monthly_task is not None:
            self.monthly_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.monthly_task
        await self.bot.session.close()
        logger.info("Telegram polling stopped")

    async def _outbox_loop(self) -> None:
        while True:
            try:
                await self.services.outbox.deliver_pending(self._send_private_message)
                await self.services.monthly.deliver_pending(self._send_private_message)
            except Exception:
                logger.exception("Telegram outbox poll failed")
            await asyncio.sleep(self.outbox_poll_seconds)

    async def _monthly_loop(self) -> None:
        job = MonthlyReportJob(self.services.monthly)
        while True:
            try:
                await job.run()
            except Exception:
                logger.exception("Monthly report job failed")
            await asyncio.sleep(3600)

    async def _send_private_message(self, chat_id: int, text: str) -> int:
        sent = await self.bot.send_message(chat_id, text)
        return sent.message_id
