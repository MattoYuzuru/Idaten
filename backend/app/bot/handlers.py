import uuid
from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.activities.schemas import ActivityInputError, parse_run_command
from app.bot.messages import (
    HELP_TEXT,
    format_personal_records,
    format_privacy,
    format_share_level,
    format_stats,
)
from app.groups.models import ShareLevel
from app.groups.schemas import GroupError, ShareTarget
from app.services import AppServices
from app.users.schemas import TelegramIdentity

router = Router(name="private")
router.message.filter(F.chat.type == ChatType.PRIVATE)
router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)


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
    targets = await services.groups.share_targets(
        identity_from_message(message).telegram_user_id, result.activity.activity_id
    )
    manual_targets = tuple(target for target in targets if not target.auto_share)
    if manual_targets:
        await message.answer(
            "Опубликовать пробежку?",
            reply_markup=_share_keyboard(manual_targets, result.activity.activity_id),
        )
    for target in targets:
        if target.auto_share:
            await _publish(
                message,
                services,
                target.telegram_chat_id,
                result.activity.activity_id,
                always=True,
            )


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


@router.message(Command("privacy"))
async def privacy(message: Message, command: CommandObject, services: AppServices) -> None:
    try:
        argument = (command.args or "").strip().lower()
        if argument in {"on", "off"}:
            result = await services.groups.set_privacy(
                identity_from_message(message).telegram_user_id,
                enabled=argument == "on",
            )
        elif argument:
            raise GroupError("Формат команды: /privacy [on|off]")
        else:
            result = await services.groups.privacy_overview(
                identity_from_message(message).telegram_user_id
            )
    except (ActivityInputError, GroupError) as error:
        await message.answer(str(error))
        return
    await message.answer(format_privacy(result))


@router.message(Command("share"))
async def share(message: Message, command: CommandObject, services: AppServices) -> None:
    try:
        parts = (command.args or "").lower().split()
        if len(parts) != 2:
            raise GroupError("Формат команды: /share <chat_id> <none|summary|detailed>")
        chat_id = int(parts[0])
        share_level = ShareLevel(parts[1].upper())
        result = await services.groups.set_share_level(
            identity_from_message(message).telegram_user_id, chat_id, share_level
        )
    except (ActivityInputError, GroupError, ValueError) as error:
        await message.answer(str(error))
        return
    await message.answer(format_share_level(result.title, result.share_level))


@router.callback_query(F.data.startswith("shr:"))
async def share_callback(callback: CallbackQuery, services: AppServices) -> None:
    if callback.from_user is None or callback.data is None:
        await callback.answer("Не удалось определить пользователя.", show_alert=True)
        return
    bot = callback.bot
    if bot is None:
        await callback.answer("Telegram bot недоступен.", show_alert=True)
        return
    try:
        action, chat_id, activity_id = _parse_share_callback(callback.data)
        if action == "n":
            await services.groups.decline_publication(callback.from_user.id, chat_id, activity_id)
            await callback.answer("Пробежка не опубликована.")
            return
        draft = await services.groups.grant_and_prepare_publication(
            callback.from_user.id,
            chat_id,
            activity_id,
            always=action == "a",
        )
        try:
            sent = await bot.send_message(draft.telegram_chat_id, draft.message_text)
        except TelegramAPIError as error:
            await services.groups.cancel_pending_publication(draft)
            raise GroupError("Telegram отклонил публикацию; попробуйте еще раз.") from error
        try:
            recorded = await services.groups.record_publication(draft, sent.message_id)
        except GroupError:
            await bot.delete_message(draft.telegram_chat_id, sent.message_id)
            await services.groups.cancel_pending_publication(draft)
            raise
        if not recorded:
            await bot.delete_message(draft.telegram_chat_id, sent.message_id)
            raise GroupError("Эта пробежка уже опубликована в группе.")
    except (GroupError, ValueError) as error:
        await callback.answer(str(error), show_alert=True)
        return
    await callback.answer("Пробежка опубликована.")


def _share_keyboard(
    targets: tuple[ShareTarget, ...], activity_id: uuid.UUID
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for target in targets:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"Да · {target.title}",
                    callback_data=_share_callback_data("y", target, activity_id),
                ),
                InlineKeyboardButton(
                    text="Нет", callback_data=_share_callback_data("n", target, activity_id)
                ),
                InlineKeyboardButton(
                    text="Всегда", callback_data=_share_callback_data("a", target, activity_id)
                ),
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _share_callback_data(action: str, target: ShareTarget, activity_id: uuid.UUID) -> str:
    return f"shr:{action}:{target.telegram_chat_id}:{activity_id.hex}"


def _parse_share_callback(value: str) -> tuple[str, int, uuid.UUID]:
    prefix, action, chat_id, activity_hex = value.split(":", maxsplit=3)
    if prefix != "shr" or action not in {"y", "n", "a"}:
        raise ValueError("Некорректное действие.")
    return action, int(chat_id), uuid.UUID(hex=activity_hex)


async def _publish(
    message: Message,
    services: AppServices,
    telegram_chat_id: int,
    activity_id: uuid.UUID,
    *,
    always: bool,
) -> None:
    try:
        bot = message.bot
        if bot is None:
            raise GroupError("Telegram bot недоступен.")
        draft = await services.groups.grant_and_prepare_publication(
            identity_from_message(message).telegram_user_id,
            telegram_chat_id,
            activity_id,
            always=always,
        )
        try:
            sent = await bot.send_message(draft.telegram_chat_id, draft.message_text)
        except TelegramAPIError as error:
            await services.groups.cancel_pending_publication(draft)
            raise GroupError("Telegram отклонил публикацию; попробуйте еще раз.") from error
        try:
            await services.groups.record_publication(draft, sent.message_id)
        except GroupError:
            await bot.delete_message(draft.telegram_chat_id, sent.message_id)
            await services.groups.cancel_pending_publication(draft)
            raise
    except GroupError as error:
        await message.answer(f"Не удалось опубликовать в группе {telegram_chat_id}: {error}")
