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
    def __init__(self, token: str, services: AppServices, *, outbox_poll_seconds: int = 5) -> None:
        self.bot = Bot(token=token)
        self.dispatcher = Dispatcher()
        self.dispatcher.include_router(router)
        self.dispatcher.include_router(group_router)
        self.services = services
        self.outbox_poll_seconds = outbox_poll_seconds
        self.task: asyncio.Task[None] | None = None
        self.outbox_task: asyncio.Task[None] | None = None

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
                BotCommand(command="link", description="Связать Android Health Connect"),
                BotCommand(command="devices", description="Связанные Android-устройства"),
                BotCommand(command="revoke_device", description="Отозвать Android token"),
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
        self.outbox_task = asyncio.create_task(self._outbox_loop(), name="telegram-outbox")
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
        await self.bot.session.close()
        logger.info("Telegram polling stopped")

    async def _outbox_loop(self) -> None:
        while True:
            try:
                await self.services.outbox.deliver_pending(self._send_private_message)
            except Exception:
                logger.exception("Telegram outbox poll failed")
            await asyncio.sleep(self.outbox_poll_seconds)

    async def _send_private_message(self, chat_id: int, text: str) -> int:
        sent = await self.bot.send_message(chat_id, text)
        return sent.message_id
