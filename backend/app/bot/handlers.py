import uuid
from datetime import UTC, datetime
from html import escape
from io import BytesIO

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    CallbackQuery,
    ForceReply,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.activities.schemas import ActivityInputError, ManualDraft, RecordedRun
from app.bot.messages import (
    HELP_SECTIONS,
    HELP_TEXT,
    format_import_history,
    format_import_preview,
    format_manual_draft,
    format_personal_records,
    format_privacy,
    format_run_history,
    format_share_level,
    format_stats,
)
from app.coach.models import TrainingGoal
from app.coach.schemas import CoachError
from app.groups.models import ShareLevel
from app.groups.schemas import GroupError, ShareTarget
from app.health_connect.schemas import HealthConnectError
from app.ingestion.schemas import ImportError, ImportPreview
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
    identity = identity_from_message(message)
    user = await services.users.register(identity)
    devices = await services.health_connect.devices_for_user(identity.telegram_user_id)
    active = tuple(device for device in devices if not device.revoked)
    if active:
        sync = max((device.last_sync_at for device in active if device.last_sync_at), default=None)
        status = (
            f"\nПоследняя sync: {sync:%d.%m.%Y %H:%M UTC}"
            if sync
            else "\nСинхронизация еще не выполнялась."
        )
        text = (
            f"Привет, {escape(user.display_name)}!\n\n"
            "Activity по умолчанию <b>private</b>. Устройство уже подключено."
            f"{status}"
        )
        keyboard = _menu_keyboard(linked=True)
    else:
        text = (
            f"Привет, {escape(user.display_name)}!\n\n"
            "Idaten сохраняет пробежки и считает прогресс. Новая Activity всегда "
            "<b>private</b>; публикация требует отдельного согласия.\n\n"
            "Выберите, как добавить первую пробежку."
        )
        keyboard = _menu_keyboard(linked=False)
    await message.answer(text, reply_markup=keyboard)


@router.message(Command("menu"))
async def menu_command(message: Message, services: AppServices) -> None:
    identity = identity_from_message(message)
    await services.users.register(identity)
    devices = await services.health_connect.devices_for_user(identity.telegram_user_id)
    await message.answer(
        "<b>Главное меню</b>\n\nВыберите действие.",
        reply_markup=_menu_keyboard(linked=any(not item.revoked for item in devices)),
    )


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(HELP_TEXT, reply_markup=_help_keyboard())


@router.message(Command("run"))
async def run(message: Message, command: CommandObject, services: AppServices) -> None:
    if not command.args:
        identity = identity_from_message(message)
        try:
            draft = await services.activities.start_manual_draft(identity)
        except ActivityInputError as error:
            await message.answer(escape(str(error)))
            return
        master = await message.answer(
            format_manual_draft(draft), reply_markup=_draft_keyboard(draft)
        )
        await services.activities.attach_manual_draft_message(
            identity.telegram_user_id, draft.draft_id, master.message_id
        )
        await message.answer(
            "Введите дистанцию в километрах, например 10.02",
            reply_markup=ForceReply(input_field_placeholder="10.02", selective=True),
        )
        return
    try:
        result = await services.activities.record_manual_command(
            identity_from_message(message), command.args, datetime.now(UTC)
        )
    except ActivityInputError as error:
        await message.answer(escape(str(error)))
        return
    await _send_run_result(message, services, result)


async def _send_run_result(
    message: Message,
    services: AppServices,
    result: RecordedRun,
    *,
    telegram_user_id: int | None = None,
) -> None:
    await message.answer(result.report_message)
    targets = await services.groups.share_targets(
        telegram_user_id or identity_from_message(message).telegram_user_id,
        result.activity.activity_id,
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
                telegram_user_id=telegram_user_id,
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
        result = await services.coach.week(identity_from_message(message).telegram_user_id)
    except CoachError as error:
        await message.answer(str(error))
        return
    await message.answer(result.message)


@router.message(Command("next"))
async def next_workout(message: Message, services: AppServices) -> None:
    try:
        result = await services.coach.next_workout(identity_from_message(message).telegram_user_id)
    except CoachError as error:
        await message.answer(str(error))
        return
    await message.answer(result.message)


@router.message(Command("plan"))
async def plan(message: Message, command: CommandObject, services: AppServices) -> None:
    parts = (command.args or "").split(maxsplit=1)
    try:
        goal = TrainingGoal(parts[0].upper())
    except (IndexError, ValueError):
        await message.answer("Формат: /plan <FIRST_10K|HALF|MARATHON|CUSTOM> [цель]")
        return
    try:
        result = await services.coach.create_plan(
            identity_from_message(message).telegram_user_id,
            goal,
            custom_goal=parts[1] if len(parts) > 1 else None,
        )
    except CoachError as error:
        await message.answer(str(error))
        return
    await message.answer(result.message)


@router.message(Command("external_processing"))
async def external_processing(
    message: Message, command: CommandObject, services: AppServices
) -> None:
    value = (command.args or "").strip().lower()
    if value not in {"on", "off"}:
        await message.answer("Формат: /external_processing on|off")
        return
    try:
        enabled = await services.coach.set_external_processing(
            identity_from_message(message).telegram_user_id, enabled=value == "on"
        )
    except CoachError as error:
        await message.answer(str(error))
        return
    await message.answer(f"Внешняя обработка: {'включена' if enabled else 'выключена'}.")


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


@router.message(Command("imports"))
async def imports_history(message: Message, services: AppServices) -> None:
    try:
        result = await services.imports.history(identity_from_message(message).telegram_user_id)
    except (ActivityInputError, ImportError) as error:
        await message.answer(str(error))
        return
    await message.answer(format_import_history(result))


@router.message(Command("link"))
async def link_health_connect(message: Message, services: AppServices) -> None:
    try:
        result = await services.health_connect.start_link_for_identity(
            identity_from_message(message)
        )
    except (ActivityInputError, HealthConnectError) as error:
        await message.answer(str(error))
        return
    await message.answer(
        "Код для Android: "
        f"{result.code}\nКод одноразовый и действует до {result.expires_at:%H:%M UTC}."
    )


@router.message(Command("devices"))
async def health_connect_devices(message: Message, services: AppServices) -> None:
    try:
        devices = await services.health_connect.devices_for_user(
            identity_from_message(message).telegram_user_id
        )
    except (ActivityInputError, HealthConnectError) as error:
        await message.answer(str(error))
        return
    if not devices:
        await message.answer("Связанных Android-устройств нет.")
        return
    lines = [
        f"{device.device_id} · {escape(device.name)} · "
        f"{'отозвано' if device.revoked else 'активно'}"
        for device in devices
    ]
    await message.answer("\n".join(lines))


@router.message(Command("revoke_device"))
async def revoke_health_connect_device(
    message: Message, command: CommandObject, services: AppServices
) -> None:
    try:
        device_id = uuid.UUID((command.args or "").strip())
    except ValueError:
        await message.answer("Формат: /revoke_device <device_uuid>")
        return
    try:
        await services.health_connect.revoke_for_user(
            identity_from_message(message).telegram_user_id, device_id
        )
    except (ActivityInputError, HealthConnectError) as error:
        await message.answer(str(error))
        return
    await message.answer("Device token отозван.")


@router.message(F.document)
async def upload_document(message: Message, services: AppServices) -> None:
    document = message.document
    if document is None:
        return
    bot = message.bot
    if bot is None:
        await message.answer("Telegram bot недоступен.")
        return
    try:
        services.imports.validate_declared_size(document.file_size)
        buffer = BytesIO()
        await bot.download(document, destination=buffer)
        preview = await services.imports.upload_for_telegram(
            identity_from_message(message),
            filename=document.file_name or "activity",
            media_type=document.mime_type,
            content=buffer.getvalue(),
        )
    except (ActivityInputError, ImportError, TelegramAPIError) as error:
        await message.answer(str(error))
        return
    await message.answer(format_import_preview(preview), reply_markup=_import_keyboard(preview))


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


@router.callback_query(F.data.startswith("imp:"))
async def import_callback(callback: CallbackQuery, services: AppServices) -> None:
    if callback.data is None:
        await callback.answer("Некорректный callback.", show_alert=True)
        return
    try:
        action, import_id = _parse_import_callback(callback.data)
        if action == "n":
            await services.imports.cancel(callback.from_user.id, import_id)
            await callback.answer("Импорт отменен.")
            return
        result = await services.imports.confirm(
            callback.from_user.id,
            import_id,
            accept_possible_duplicate=action == "f",
        )
    except (ImportError, ValueError) as error:
        await callback.answer(str(error), show_alert=True)
        return
    if callback.message is not None:
        if result.report_message:
            await callback.message.answer(result.report_message)
        else:
            await callback.message.answer("Эта активность уже была импортирована.")
    await callback.answer("Импорт подтвержден.")


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


def _import_keyboard(preview: ImportPreview) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text="Подтвердить", callback_data=f"imp:y:{preview.import_id.hex}"),
        InlineKeyboardButton(text="Отмена", callback_data=f"imp:n:{preview.import_id.hex}"),
    ]
    if preview.duplicate_candidates:
        buttons.insert(
            1,
            InlineKeyboardButton(
                text="Сохранить всё равно", callback_data=f"imp:f:{preview.import_id.hex}"
            ),
        )
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


def _parse_import_callback(value: str) -> tuple[str, uuid.UUID]:
    prefix, action, import_hex = value.split(":", maxsplit=2)
    if prefix != "imp" or action not in {"y", "n", "f"}:
        raise ValueError("Некорректное действие импорта.")
    return action, uuid.UUID(hex=import_hex)


async def _publish(
    message: Message,
    services: AppServices,
    telegram_chat_id: int,
    activity_id: uuid.UUID,
    *,
    always: bool,
    telegram_user_id: int | None = None,
) -> None:
    try:
        bot = message.bot
        if bot is None:
            raise GroupError("Telegram bot недоступен.")
        draft = await services.groups.grant_and_prepare_publication(
            telegram_user_id or identity_from_message(message).telegram_user_id,
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


@router.callback_query(F.data.startswith("help:"))
async def help_callback(callback: CallbackQuery) -> None:
    key = (callback.data or "").partition(":")[2]
    text = HELP_SECTIONS.get(key)
    if text is None or not isinstance(callback.message, Message):
        await callback.answer("Раздел не найден.", show_alert=True)
        return
    await callback.message.edit_text(text, reply_markup=_help_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("menu:"))
async def menu_callback(callback: CallbackQuery, services: AppServices) -> None:
    if callback.data is None or not isinstance(callback.message, Message):
        await callback.answer("Некорректное действие.", show_alert=True)
        return
    action = callback.data.partition(":")[2]
    user_id = callback.from_user.id
    try:
        if action == "link":
            result = await services.health_connect.start_link_for_user(user_id)
            await callback.message.answer(
                "<b>Подключить Health Connect</b>\n\n"
                "1. Установите APK из GitHub Release.\n"
                "2. Выдайте базовые read permissions.\n"
                f"3. Введите код <code>{result.code}</code> в Android.\n"
                "4. Загрузите последние пробежки и явно нажмите «Синхронизировать»."
            )
        elif action == "manual":
            draft = await services.activities.start_manual_draft(
                TelegramIdentity(
                    telegram_user_id=user_id,
                    private_chat_id=callback.message.chat.id,
                    username=callback.from_user.username,
                    first_name=callback.from_user.first_name,
                    last_name=callback.from_user.last_name,
                )
            )
            master = await callback.message.answer(
                format_manual_draft(draft), reply_markup=_draft_keyboard(draft)
            )
            await services.activities.attach_manual_draft_message(
                user_id, draft.draft_id, master.message_id
            )
            await callback.message.answer(
                "Введите дистанцию в километрах, например 10.02",
                reply_markup=ForceReply(input_field_placeholder="10.02", selective=True),
            )
        elif action == "imports":
            await callback.message.answer(
                "Отправьте сюда GPX, TCX, FIT, CSV или ZIP с одним поддерживаемым файлом."
            )
        elif action == "help":
            await callback.message.answer(HELP_TEXT, reply_markup=_help_keyboard())
        elif action == "sync":
            await callback.message.answer(
                "Откройте Android-приложение Idaten, загрузите последние пробежки, "
                "проверьте список и нажмите «Синхронизировать». Telegram не может сам "
                "прочитать локальный Health Connect."
            )
        elif action == "history":
            groups = await services.activities.run_history(user_id)
            await callback.message.answer(
                format_run_history(groups), reply_markup=_history_keyboard(groups, 0)
            )
        elif action == "stats":
            stats = await services.activities.stats(user_id)
            await callback.message.answer(format_stats(stats, "Статистика за всё время"))
        elif action == "settings":
            overview = await services.groups.privacy_overview(user_id)
            await callback.message.answer(format_privacy(overview))
        else:
            raise ActivityInputError("Неизвестное действие меню.")
    except (ActivityInputError, HealthConnectError, GroupError) as error:
        await callback.answer(str(error), show_alert=True)
        return
    await callback.answer()


@router.callback_query(F.data.startswith("hist:"))
async def history_callback(callback: CallbackQuery, services: AppServices) -> None:
    if callback.data is None or not isinstance(callback.message, Message):
        await callback.answer("Некорректная страница.", show_alert=True)
        return
    try:
        offset = max(0, int(callback.data.partition(":")[2]))
        groups = await services.activities.run_history(callback.from_user.id)
    except (ValueError, ActivityInputError) as error:
        await callback.answer(str(error), show_alert=True)
        return
    await callback.message.edit_text(
        format_run_history(groups, offset), reply_markup=_history_keyboard(groups, offset)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("md:"))
async def manual_draft_callback(callback: CallbackQuery, services: AppServices) -> None:
    if callback.data is None or callback.message is None:
        await callback.answer("Некорректный callback.", show_alert=True)
        return
    try:
        _, action, draft_hex, *field_parts = callback.data.split(":")
        draft_id = uuid.UUID(hex=draft_hex)
        if not isinstance(callback.message, Message):
            raise ActivityInputError("Сообщение мастера больше недоступно.")
        if action == "cancel":
            draft = await services.activities.cancel_manual_draft(callback.from_user.id, draft_id)
            await callback.message.edit_text("Добавление пробежки отменено.")
        elif action == "save":
            result = await services.activities.confirm_manual_draft(callback.from_user.id, draft_id)
            await callback.message.edit_text("✅ Пробежка сохранена private.")
            await _send_run_result(
                callback.message,
                services,
                result,
                telegram_user_id=callback.from_user.id,
            )
        elif action == "field" and field_parts:
            field = field_parts[0]
            draft = await services.activities.choose_manual_draft_field(
                callback.from_user.id, draft_id, field
            )
            await callback.message.answer(
                _draft_prompt(field),
                reply_markup=ForceReply(
                    input_field_placeholder=_draft_placeholder(field), selective=True
                ),
            )
            await callback.message.edit_text(
                format_manual_draft(draft), reply_markup=_draft_keyboard(draft)
            )
        else:
            raise ActivityInputError("Неизвестное действие черновика.")
    except (ActivityInputError, ValueError) as error:
        await callback.answer(str(error), show_alert=True)
        return
    await callback.answer()


@router.message(F.text)
async def manual_draft_reply(message: Message, services: AppServices) -> None:
    if message.from_user is None or message.text is None or message.text.startswith("/"):
        return
    try:
        pending = await services.activities.pending_manual_draft(message.from_user.id)
    except ActivityInputError:
        return
    if pending is None:
        return
    draft, field = pending
    try:
        updated = await services.activities.set_manual_draft_field(
            message.from_user.id, draft.draft_id, field, message.text
        )
    except ActivityInputError as error:
        await message.answer(
            f"{escape(str(error))}\n\n{_draft_prompt(field)}",
            reply_markup=ForceReply(
                input_field_placeholder=_draft_placeholder(field), selective=True
            ),
        )
        return
    if updated.telegram_message_id is not None and message.bot is not None:
        await message.bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=updated.telegram_message_id,
            text=format_manual_draft(updated),
            reply_markup=_draft_keyboard(updated),
        )
    if field == "distance" and updated.run.elapsed_time_sec == 0:
        await services.activities.choose_manual_draft_field(
            message.from_user.id, updated.draft_id, "elapsed"
        )
        await message.answer(
            _draft_prompt("elapsed"),
            reply_markup=ForceReply(input_field_placeholder="45:30", selective=True),
        )


def _menu_keyboard(*, linked: bool) -> InlineKeyboardMarkup:
    if linked:
        rows = [
            [InlineKeyboardButton(text="🏃 Мои пробежки", callback_data="menu:history")],
            [InlineKeyboardButton(text="📱 Как синхронизировать", callback_data="menu:sync")],
            [InlineKeyboardButton(text="➕ Добавить пробежку", callback_data="menu:manual")],
            [InlineKeyboardButton(text="📊 Статистика", callback_data="menu:stats")],
            [InlineKeyboardButton(text="⚙️ Настройки", callback_data="menu:settings")],
            [InlineKeyboardButton(text="❓ Помощь", callback_data="menu:help")],
        ]
    else:
        rows = [
            [InlineKeyboardButton(text="📱 Подключить Health Connect", callback_data="menu:link")],
            [InlineKeyboardButton(text="➕ Добавить вручную", callback_data="menu:manual")],
            [InlineKeyboardButton(text="📄 Импортировать файл", callback_data="menu:imports")],
            [InlineKeyboardButton(text="❓ Что умеет бот", callback_data="menu:help")],
        ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _help_keyboard() -> InlineKeyboardMarkup:
    labels = {
        "start": "Старт",
        "activities": "Активности",
        "imports": "Импорт",
        "health": "Health Connect",
        "privacy": "Privacy и группы",
        "external": "Внешний wording",
    }
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data=f"help:{key}")]
            for key, label in labels.items()
        ]
    )


def _draft_keyboard(draft: ManualDraft) -> InlineKeyboardMarkup:
    draft_hex = draft.draft_id.hex
    rows = [
        [
            InlineKeyboardButton(text="Дистанция", callback_data=f"md:field:{draft_hex}:distance"),
            InlineKeyboardButton(
                text="Длительность", callback_data=f"md:field:{draft_hex}:elapsed"
            ),
        ],
        [
            InlineKeyboardButton(text="Дата", callback_data=f"md:field:{draft_hex}:date"),
            InlineKeyboardButton(text="Время", callback_data=f"md:field:{draft_hex}:time"),
            InlineKeyboardButton(text="Moving", callback_data=f"md:field:{draft_hex}:moving"),
        ],
        [
            InlineKeyboardButton(text="Пульс", callback_data=f"md:field:{draft_hex}:hr"),
            InlineKeyboardButton(text="Макс. пульс", callback_data=f"md:field:{draft_hex}:max_hr"),
        ],
        [
            InlineKeyboardButton(text="Каденс", callback_data=f"md:field:{draft_hex}:cadence"),
            InlineKeyboardButton(text="Набор", callback_data=f"md:field:{draft_hex}:elevation"),
            InlineKeyboardButton(text="Название", callback_data=f"md:field:{draft_hex}:title"),
        ],
        [
            InlineKeyboardButton(text="✅ Сохранить", callback_data=f"md:save:{draft_hex}"),
            InlineKeyboardButton(text="Отмена", callback_data=f"md:cancel:{draft_hex}"),
        ],
    ]
    if not draft.complete:
        rows[-1][0] = InlineKeyboardButton(
            text="Сначала дистанция и время", callback_data=f"md:field:{draft_hex}:distance"
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _history_keyboard(
    groups: tuple[object, ...], offset: int, size: int = 5
) -> InlineKeyboardMarkup | None:
    buttons: list[InlineKeyboardButton] = []
    if offset > 0:
        buttons.append(
            InlineKeyboardButton(text="← Новее", callback_data=f"hist:{max(0, offset - size)}")
        )
    if offset + size < len(groups):
        buttons.append(InlineKeyboardButton(text="Старее →", callback_data=f"hist:{offset + size}"))
    return InlineKeyboardMarkup(inline_keyboard=[buttons]) if buttons else None


def _draft_prompt(field: str) -> str:
    return {
        "distance": "Введите дистанцию в км, например 10.02",
        "elapsed": "Введите длительность: 45:30 или 1:45:30",
        "date": "Введите дату: YYYY-MM-DD",
        "time": "Введите локальное время: HH:MM",
        "moving": "Введите moving time: 45:30 или 1:45:30",
        "hr": "Введите средний пульс: 20–260",
        "max_hr": "Введите максимальный пульс: 20–260",
        "cadence": "Введите средний каденс: 30–300 spm",
        "elevation": "Введите набор высоты: 0–20000 м",
        "title": "Введите название, до 255 символов",
    }[field]


def _draft_placeholder(field: str) -> str:
    return {
        "distance": "10.02",
        "elapsed": "45:30",
        "date": "2026-06-16",
        "time": "07:30",
        "moving": "43:10",
        "hr": "152",
        "max_hr": "178",
        "cadence": "171",
        "elevation": "164",
        "title": "Полумарафон",
    }[field]
