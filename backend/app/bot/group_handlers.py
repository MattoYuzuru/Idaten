from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.filters import Command
from aiogram.types import Message

from app.bot.messages import format_group_week, format_leaderboard, format_streaks
from app.groups.schemas import GroupError
from app.services import AppServices

router = Router(name="groups")
router.message.filter(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))


def telegram_user_id(message: Message) -> int:
    if message.from_user is None:
        raise GroupError("Не удалось определить пользователя Telegram.")
    return message.from_user.id


@router.message(Command("setup_group"))
async def setup_group(message: Message, services: AppServices) -> None:
    try:
        user_id = telegram_user_id(message)
        bot = message.bot
        if bot is None:
            raise GroupError("Telegram bot недоступен.")
        chat_member = await bot.get_chat_member(message.chat.id, user_id)
        is_admin = chat_member.status in {
            ChatMemberStatus.CREATOR,
            ChatMemberStatus.ADMINISTRATOR,
        }
        result = await services.groups.setup_group(
            user_id,
            message.chat.id,
            message.chat.title or str(message.chat.id),
            actor_is_admin=is_admin,
        )
    except GroupError as error:
        await message.answer(str(error))
        return
    await message.answer(
        f"Группа «{result.title}» настроена. Выполните /join, затем настройте sharing в ЛС."
    )


@router.message(Command("join"))
async def join(message: Message, services: AppServices) -> None:
    try:
        result = await services.groups.join(telegram_user_id(message), message.chat.id)
    except GroupError as error:
        await message.answer(str(error))
        return
    await message.answer(
        f"Вы в группе «{result.title}». Sharing выключен; настройте /share в личном чате."
    )


@router.message(Command("leave"))
async def leave(message: Message, services: AppServices) -> None:
    try:
        await services.groups.leave(telegram_user_id(message), message.chat.id)
    except GroupError as error:
        await message.answer(str(error))
        return
    await message.answer("Вы вышли из беговой группы. Sharing отключен.")


@router.message(Command("leaderboard"))
async def leaderboard(message: Message, services: AppServices) -> None:
    try:
        result = await services.groups.leaderboard(message.chat.id, datetime.now(UTC))
    except GroupError as error:
        await message.answer(str(error))
        return
    await message.answer(format_leaderboard(result))


@router.message(Command("streaks"))
async def streaks(message: Message, services: AppServices) -> None:
    try:
        result = await services.groups.streaks(message.chat.id, datetime.now(UTC))
    except GroupError as error:
        await message.answer(str(error))
        return
    await message.answer(format_streaks(result))


@router.message(Command("week"))
async def week(message: Message, services: AppServices) -> None:
    try:
        result = await services.groups.week(message.chat.id, datetime.now(UTC))
    except GroupError as error:
        await message.answer(str(error))
        return
    await message.answer(format_group_week(result))
