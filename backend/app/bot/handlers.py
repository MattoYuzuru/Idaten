from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import Message

from app.activities.schemas import ActivityInputError, parse_run_command
from app.bot.messages import HELP_TEXT, format_personal_records, format_stats
from app.services import AppServices
from app.users.schemas import TelegramIdentity

router = Router(name="private")
router.message.filter(F.chat.type == ChatType.PRIVATE)


def identity_from_message(message: Message) -> TelegramIdentity:
    sender = message.from_user
    if sender is None:
        raise ActivityInputError("Не удалось определить пользователя Telegram.")
    return TelegramIdentity(
        telegram_user_id=sender.id,
        private_chat_id=message.chat.id,
        username=sender.username,
        first_name=sender.first_name,
        last_name=sender.last_name,
    )


@router.message(CommandStart())
async def start(message: Message, services: AppServices) -> None:
    user = await services.users.register(identity_from_message(message))
    await message.answer(
        f"Привет, {user.display_name}! Я сохраню пробежки и посчитаю прогресс.\n\n{HELP_TEXT}"
    )


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(HELP_TEXT)


@router.message(Command("run"))
async def run(message: Message, command: CommandObject, services: AppServices) -> None:
    try:
        run_input = parse_run_command(command.args, datetime.now(UTC))
        result = await services.activities.record_manual_run(
            identity_from_message(message), run_input
        )
    except ActivityInputError as error:
        await message.answer(str(error))
        return
    await message.answer(result.report_message)


@router.message(Command("stats"))
async def stats(message: Message, services: AppServices) -> None:
    try:
        result = await services.activities.stats(identity_from_message(message).telegram_user_id)
    except ActivityInputError as error:
        await message.answer(str(error))
        return
    await message.answer(format_stats(result, "Статистика за все время"))


@router.message(Command("week"))
async def week(message: Message, services: AppServices) -> None:
    try:
        result = await services.activities.week(identity_from_message(message).telegram_user_id)
    except ActivityInputError as error:
        await message.answer(str(error))
        return
    await message.answer(format_stats(result, "Текущая неделя"))


@router.message(Command("pr"))
async def personal_records(message: Message, services: AppServices) -> None:
    try:
        result = await services.activities.personal_records(
            identity_from_message(message).telegram_user_id
        )
    except ActivityInputError as error:
        await message.answer(str(error))
        return
    await message.answer(format_personal_records(result))
