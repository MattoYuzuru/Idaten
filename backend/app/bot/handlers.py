import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from html import escape
from io import BytesIO

from aiogram import F, Router
from aiogram.enums import ChatAction, ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    CallbackQuery,
    ForceReply,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.activities.models import DraftInputMethod
from app.activities.schemas import (
    ActivityInputError,
    ManualDraft,
    PossibleDuplicateError,
    RecordedRun,
)
from app.assisted.models import AssistedAccessStatus
from app.assisted.schemas import AccessRequestResult, AssistedError, InputGateStatus
from app.bot.messages import (
    HELP_SECTIONS,
    HELP_TEXT,
    REPOSITORY_URL,
    format_import_preview,
    format_manual_draft,
    format_personal_records,
    format_privacy,
    format_run_history,
    format_stats,
)
from app.coach.schemas import CoachError
from app.groups.schemas import GroupError, PrivacyGroupAction, PrivacyOverview, ShareTarget
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
            "Idaten сохраняет пробежки, показывает личный прогресс и помогает выбрать "
            "следующую спокойную тренировку. Новая пробежка всегда <b>private</b>."
            f"{status}\n\n"
            f'<a href="{REPOSITORY_URL}">Код и документация Idaten</a>'
        )
        keyboard = _menu_keyboard(linked=True)
    else:
        text = (
            f"Привет, {escape(user.display_name)}!\n\n"
            "Idaten сохраняет пробежки, показывает личный прогресс и помогает выбрать "
            "следующую спокойную тренировку. Новая пробежка всегда <b>private</b>; "
            "публикация требует отдельного согласия.\n\n"
            "Добавьте первую пробежку или подключите Health Connect.\n\n"
            f'<a href="{REPOSITORY_URL}">Код и документация Idaten</a>'
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
        await message.answer("Как добавить пробежку?", reply_markup=_add_method_keyboard())
        return
    try:
        result = await services.activities.record_manual_command(
            identity_from_message(message), command.args, datetime.now(UTC)
        )
    except PossibleDuplicateError as error:
        if error.run is None:
            await message.answer(escape(str(error)))
            return
        identity = identity_from_message(message)
        draft = await services.activities.start_manual_draft(identity, prefill=error.run)
        await message.answer("Похоже, такая пробежка уже сохранена. Проверьте данные.")
        master = await message.answer(
            format_manual_draft(draft), reply_markup=_draft_keyboard(draft)
        )
        await services.activities.attach_manual_draft_message(
            identity.telegram_user_id, draft.draft_id, master.message_id
        )
        return
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
    await message.answer(format_stats(result))


@router.message(Command("next"))
async def next_workout(message: Message, services: AppServices) -> None:
    try:
        result = await services.coach.next_workout(identity_from_message(message).telegram_user_id)
    except CoachError as error:
        await message.answer(str(error))
        return
    await message.answer(result.message)


@router.message(Command("ai_access"))
async def ai_access(message: Message, command: CommandObject, services: AppServices) -> None:
    parts = (command.args or "").split()
    if len(parts) != 2 or parts[0] not in {"grant", "revoke", "status"}:
        await message.answer("Формат: /ai_access grant|revoke|status <telegram_id>")
        return
    try:
        actor_id = identity_from_message(message).telegram_user_id
        _require_assisted_owner(services, actor_id)
        target_id = int(parts[1])
        if parts[0] == "status":
            overview = await services.assisted.access_overview(actor_id, target_id)
        else:
            overview = await services.assisted.decide_access(
                actor_id,
                target_id,
                allow=parts[0] == "grant",
            )
    except (AssistedError, ValueError) as error:
        await message.answer(escape(str(error)))
        return
    status = overview.status.value if overview.status else "NOT_REQUESTED"
    await message.answer(
        f"User <code>{overview.telegram_user_id}</code>: {status}; "
        f"consent={'yes' if overview.consent_current else 'no'}"
    )
    if parts[0] == "grant" and message.bot is not None:
        await message.bot.send_message(target_id, "Доступ к вводу текстом и скриншотом открыт.")


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
    if message.from_user is not None:
        pending = await services.assisted.pending_input(
            message.from_user.id, DraftInputMethod.SCREENSHOT
        )
        if pending is not None:
            await _process_assisted_document(message, services, pending)
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


@router.message(F.photo)
async def upload_photo(message: Message, services: AppServices) -> None:
    if message.from_user is None or not message.photo:
        return
    draft_id = await services.assisted.pending_input(
        message.from_user.id, DraftInputMethod.SCREENSHOT
    )
    if draft_id is None:
        await message.answer("Сначала выберите «Добавить пробежку» → «Отправить скриншот».")
        return
    async with _assisted_processing(message) as placeholder:
        photo = message.photo[-1]
        try:
            services.assisted.validate_declared_image_size(photo.file_size)
            if message.bot is None:
                raise AssistedError("Telegram bot недоступен.", code="BOT_UNAVAILABLE")
            buffer = BytesIO()
            await message.bot.download(photo, destination=buffer)
            await _finish_assisted_image(
                message,
                placeholder,
                services,
                draft_id,
                buffer.getvalue(),
                "image/jpeg",
            )
        except (AssistedError, ActivityInputError, TelegramAPIError) as error:
            await _replace_processing_message(
                message, placeholder, _assisted_failure_message(error)
            )


async def _process_assisted_document(
    message: Message, services: AppServices, draft_id: uuid.UUID
) -> None:
    document = message.document
    if document is None:
        return
    async with _assisted_processing(message) as placeholder:
        try:
            services.assisted.validate_declared_image_size(document.file_size)
            if message.bot is None:
                raise AssistedError("Telegram bot недоступен.", code="BOT_UNAVAILABLE")
            buffer = BytesIO()
            await message.bot.download(document, destination=buffer)
            await _finish_assisted_image(
                message,
                placeholder,
                services,
                draft_id,
                buffer.getvalue(),
                document.mime_type,
            )
        except (AssistedError, ActivityInputError, TelegramAPIError) as error:
            await _replace_processing_message(
                message, placeholder, _assisted_failure_message(error)
            )


async def _finish_assisted_image(
    message: Message,
    placeholder: Message,
    services: AppServices,
    draft_id: uuid.UUID,
    content: bytes,
    media_type: str | None,
) -> None:
    if message.from_user is None:
        raise AssistedError("Не удалось определить пользователя.", code="USER_NOT_FOUND")
    await services.assisted.extract_image(message.from_user.id, draft_id, content, media_type)
    draft = await services.activities.manual_draft(message.from_user.id, draft_id)
    master = await _replace_processing_message(
        message,
        placeholder,
        format_manual_draft(draft),
        reply_markup=_draft_keyboard(draft),
    )
    await services.activities.attach_manual_draft_message(
        message.from_user.id, draft.draft_id, master.message_id
    )


@router.message(Command("privacy"))
async def privacy(message: Message, services: AppServices) -> None:
    try:
        result = await services.groups.privacy_overview(
            identity_from_message(message).telegram_user_id
        )
    except (ActivityInputError, GroupError) as error:
        await message.answer(str(error))
        return
    await message.answer(format_privacy(result), reply_markup=_privacy_keyboard(result))


@router.callback_query(F.data.startswith("priv:"))
async def privacy_callback(callback: CallbackQuery, services: AppServices) -> None:
    if callback.data is None or not isinstance(callback.message, Message):
        await callback.answer("Некорректное действие.", show_alert=True)
        return
    try:
        scope, identifier, action = _parse_privacy_callback(callback.data)
        if scope == "global":
            overview = await services.groups.set_privacy(
                callback.from_user.id, enabled=action == "ON"
            )
        else:
            assert identifier is not None
            overview = await services.groups.set_group_privacy(
                callback.from_user.id,
                identifier,
                PrivacyGroupAction(action),
            )
        await callback.message.edit_text(
            format_privacy(overview), reply_markup=_privacy_keyboard(overview)
        )
    except (GroupError, ValueError) as error:
        await callback.answer(str(error), show_alert=True)
        return
    await callback.answer("Настройки сохранены.")


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
            await callback.message.answer(
                "Как добавить пробежку?", reply_markup=_add_method_keyboard()
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
            await callback.message.answer(format_stats(stats))
        elif action == "next":
            next_result = await services.coach.next_workout(user_id)
            await callback.message.answer(next_result.message)
        elif action == "privacy":
            overview = await services.groups.privacy_overview(user_id)
            await callback.message.answer(
                format_privacy(overview), reply_markup=_privacy_keyboard(overview)
            )
        elif action == "devices":
            devices = await services.health_connect.devices_for_user(user_id)
            active = tuple(device for device in devices if not device.revoked)
            if not active:
                await callback.message.answer("Активных подключений Health Connect нет.")
            else:
                await callback.message.answer(
                    "<b>Health Connect подключён</b>\n\n"
                    + "\n".join(f"• {escape(device.name)}" for device in active)
                    + "\n\nСинхронизация запускается вручную в Android-приложении."
                )
        else:
            raise ActivityInputError("Неизвестное действие меню.")
    except (ActivityInputError, AssistedError, HealthConnectError, GroupError) as error:
        await callback.answer(str(error), show_alert=True)
        return
    await callback.answer()


@router.callback_query(F.data.startswith("add:"))
async def add_method_callback(callback: CallbackQuery, services: AppServices) -> None:
    if callback.data is None or not isinstance(callback.message, Message):
        await callback.answer("Некорректное действие.", show_alert=True)
        return
    method_name = callback.data.partition(":")[2]
    try:
        method = {
            "steps": DraftInputMethod.STEPS,
            "text": DraftInputMethod.TEXT,
            "screenshot": DraftInputMethod.SCREENSHOT,
        }[method_name]
    except KeyError:
        await callback.answer("Некорректное действие.", show_alert=True)
        return
    await callback.answer()
    try:
        if method == DraftInputMethod.STEPS:
            await _start_steps(callback.message, callback, services)
        else:
            await _begin_assisted(callback.message, callback, services, method)
    except (ActivityInputError, AssistedError) as error:
        await callback.message.answer(escape(str(error)))
        return


def _identity_from_callback(callback: CallbackQuery) -> TelegramIdentity:
    if not isinstance(callback.message, Message):
        raise AssistedError("Сообщение недоступно.", code="MESSAGE_UNAVAILABLE")
    return TelegramIdentity(
        telegram_user_id=callback.from_user.id,
        private_chat_id=callback.message.chat.id,
        username=callback.from_user.username,
        first_name=callback.from_user.first_name,
        last_name=callback.from_user.last_name,
    )


async def _start_steps(message: Message, callback: CallbackQuery, services: AppServices) -> None:
    identity = _identity_from_callback(callback)
    draft = await services.activities.start_manual_draft(identity)
    master = await message.answer(format_manual_draft(draft), reply_markup=_draft_keyboard(draft))
    await services.activities.attach_manual_draft_message(
        identity.telegram_user_id, draft.draft_id, master.message_id
    )
    await message.answer(
        "Введите дистанцию в километрах, например 10.02",
        reply_markup=ForceReply(input_field_placeholder="10.02", selective=True),
    )


async def _begin_assisted(
    message: Message,
    callback: CallbackQuery,
    services: AppServices,
    method: DraftInputMethod,
) -> None:
    identity = _identity_from_callback(callback)
    gate = await services.assisted.gate(identity, method)
    if gate.status == InputGateStatus.CONSENT_REQUIRED:
        label = "текст" if method == DraftInputMethod.TEXT else "изображение"
        await message.answer(
            "Для распознавания Idaten передаст внешний provider только текущие "
            f"{label} и timezone. Данные профиля, история, GPS и Telegram identity "
            "не передаются. Исходное содержимое не сохраняется на VPS.",
            reply_markup=_consent_keyboard(method),
        )
        return
    if gate.status == InputGateStatus.ACCESS_REVOKED:
        raise AssistedError("Доступ к этой функции отозван.", code="ACCESS_REVOKED")
    if gate.status == InputGateStatus.DISABLED:
        raise AssistedError("Этот способ ввода сейчас недоступен.", code="PROVIDER_DISABLED")
    if gate.status == InputGateStatus.ACCESS_PENDING:
        request = await services.assisted.accept_consent(identity)
        if request.notify_owner:
            await _notify_access_owner(callback, services, request)
        await message.answer("Запрос доступа отправлен владельцу бота.")
        return
    await _start_assisted_prompt(message, identity.telegram_user_id, services, method)


async def _start_assisted_prompt(
    message: Message,
    telegram_user_id: int,
    services: AppServices,
    method: DraftInputMethod,
) -> None:
    await services.assisted.start_draft(telegram_user_id, method)
    if method == DraftInputMethod.TEXT:
        await message.answer(
            "Опишите одну пробежку одним сообщением. Например: «7 июля пробежал "
            "8,4 км за 47:20, средний пульс 151»."
        )
    else:
        await message.answer("Отправьте один JPEG или PNG скриншот пробежки.")


async def _notify_access_owner(
    callback: CallbackQuery,
    services: AppServices,
    request: AccessRequestResult,
) -> None:
    owner_chat_id = services.assisted.owner_chat_id
    if owner_chat_id is None or callback.bot is None:
        return
    username = f"@{escape(request.username)}" if request.username else "без username"
    await callback.bot.send_message(
        owner_chat_id,
        "<b>Запрошен доступ к распознаванию тренировок</b>\n\n"
        f"{escape(request.display_name)} · {username}\n"
        f"Telegram ID: <code>{request.telegram_user_id}</code>",
        reply_markup=_access_keyboard(request.telegram_user_id),
    )
    await services.assisted.mark_notification_sent(request.telegram_user_id)


@router.callback_query(F.data.startswith("assist:consent:"))
async def assisted_consent_callback(callback: CallbackQuery, services: AppServices) -> None:
    if callback.data is None or not isinstance(callback.message, Message):
        await callback.answer("Некорректное действие.", show_alert=True)
        return
    try:
        action, method = _parse_assisted_consent_callback(callback.data)
    except ValueError as error:
        await callback.answer(str(error), show_alert=True)
        return
    await callback.answer()
    if action == "no":
        await callback.message.edit_text(
            "Внешняя обработка не включена. Вы сможете согласиться при следующей попытке."
        )
        return
    try:
        request = await services.assisted.accept_consent(_identity_from_callback(callback))
        if request.notify_owner:
            await _notify_access_owner(callback, services, request)
        if request.status == AssistedAccessStatus.ALLOWED:
            await _start_assisted_prompt(callback.message, callback.from_user.id, services, method)
        elif request.status == AssistedAccessStatus.REVOKED:
            await callback.message.edit_text("Доступ к этой функции отозван владельцем бота.")
        else:
            await callback.message.edit_text(
                "Согласие сохранено. Запрос доступа отправлен владельцу бота."
            )
    except AssistedError as error:
        await callback.message.answer(escape(str(error)))
        return


@router.callback_query(F.data.startswith("aia:"))
async def assisted_admin_callback(callback: CallbackQuery, services: AppServices) -> None:
    if callback.data is None:
        await callback.answer("Некорректное действие.", show_alert=True)
        return
    try:
        _prefix, action, target = callback.data.split(":")
        if action not in {"grant", "revoke"}:
            raise ValueError("Некорректное действие.")
        target_id = int(target)
        _require_assisted_owner(services, callback.from_user.id)
        overview = await services.assisted.decide_access(
            callback.from_user.id, target_id, allow=action == "grant"
        )
        if callback.bot is not None and overview.status == AssistedAccessStatus.ALLOWED:
            await callback.bot.send_message(
                target_id, "Доступ к вводу текстом и скриншотом открыт."
            )
    except (AssistedError, ValueError) as error:
        await callback.answer(str(error), show_alert=True)
        return
    await callback.answer(f"Статус: {overview.status.value if overview.status else 'NONE'}")


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
    if callback.data is None or not isinstance(callback.message, Message):
        await callback.answer("Некорректный callback.", show_alert=True)
        return
    message = callback.message
    try:
        _, action, draft_hex, *field_parts = callback.data.split(":")
        draft_id = uuid.UUID(hex=draft_hex)
        if action == "cancel":
            draft = await services.activities.cancel_manual_draft(callback.from_user.id, draft_id)
            await message.edit_text("Добавление пробежки отменено.")
        elif action in {"save", "force"}:
            result = await services.activities.confirm_manual_draft(
                callback.from_user.id,
                draft_id,
                accept_possible_duplicate=action == "force",
            )
            await message.edit_text("✅ Пробежка сохранена private.")
            if result.created:
                await _send_run_result(
                    message,
                    services,
                    result,
                    telegram_user_id=callback.from_user.id,
                )
        elif action == "field" and field_parts:
            field = field_parts[0]
            draft = await services.activities.choose_manual_draft_field(
                callback.from_user.id, draft_id, field
            )
            await message.answer(
                _draft_prompt(field),
                reply_markup=ForceReply(
                    input_field_placeholder=_draft_placeholder(field), selective=True
                ),
            )
            await message.edit_text(format_manual_draft(draft), reply_markup=_draft_keyboard(draft))
        else:
            raise ActivityInputError("Неизвестное действие черновика.")
    except PossibleDuplicateError as error:
        refreshed = await services.activities.manual_draft(callback.from_user.id, draft_id)
        await message.edit_text(
            format_manual_draft(refreshed), reply_markup=_draft_keyboard(refreshed)
        )
        await callback.answer(str(error), show_alert=True)
        return
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
    if field == "assisted_input":
        if draft.input_method != DraftInputMethod.TEXT:
            await message.answer("Ожидается JPEG или PNG скриншот.")
            return
        async with _assisted_processing(message) as placeholder:
            try:
                await services.assisted.extract_text(
                    message.from_user.id, draft.draft_id, message.text
                )
                updated = await services.activities.manual_draft(
                    message.from_user.id, draft.draft_id
                )
                master = await _replace_processing_message(
                    message,
                    placeholder,
                    format_manual_draft(updated),
                    reply_markup=_draft_keyboard(updated),
                )
                await services.activities.attach_manual_draft_message(
                    message.from_user.id, updated.draft_id, master.message_id
                )
            except (ActivityInputError, AssistedError) as error:
                await _replace_processing_message(
                    message, placeholder, _assisted_failure_message(error)
                )
        return
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


@asynccontextmanager
async def _assisted_processing(message: Message) -> AsyncIterator[Message]:
    placeholder = await message.answer("⏳ <b>Распознаю пробежку…</b>")
    stop = asyncio.Event()
    if message.bot is not None:
        await _send_typing(message)
        task = asyncio.create_task(_typing_loop(message, stop), name="telegram-assisted-typing")
    else:
        task = None
    try:
        yield placeholder
    finally:
        stop.set()
        if task is not None:
            await task


async def _send_typing(message: Message) -> None:
    if message.bot is None:
        return
    try:
        await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    except TelegramAPIError:
        return


async def _typing_loop(message: Message, stop: asyncio.Event) -> None:
    while True:
        try:
            await asyncio.wait_for(stop.wait(), timeout=4)
            return
        except TimeoutError:
            await _send_typing(message)


async def _replace_processing_message(
    source: Message,
    placeholder: Message,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> Message:
    try:
        await placeholder.edit_text(text, reply_markup=reply_markup)
        return placeholder
    except TelegramAPIError:
        return await source.answer(text, reply_markup=reply_markup)


def _assisted_failure_message(error: Exception) -> str:
    if isinstance(error, AssistedError):
        detail = {
            "PROVIDER_TIMEOUT": "Сервис не ответил вовремя.",
            "PROVIDER_FAILED": "Сервис временно недоступен.",
            "NOT_A_RUN": "На входе не удалось уверенно найти одну пробежку.",
            "IMAGE_SIZE": "Изображение слишком большое.",
            "IMAGE_TYPE": "Нужен JPEG или PNG.",
            "IMAGE_MIME": "Тип файла не совпадает с содержимым.",
            "IMAGE_PIXELS": "У изображения недопустимое разрешение.",
            "IMAGE_INVALID": "Файл изображения повреждён.",
            "DAILY_LIMIT": "Дневной лимит распознаваний исчерпан.",
            "MONTHLY_LIMIT": "Месячный лимит распознаваний исчерпан.",
            "ACCESS_REVOKED": "Доступ к распознаванию отозван.",
        }.get(error.code, "Не удалось обработать данные.")
    elif isinstance(error, TelegramAPIError):
        detail = "Не удалось получить изображение из Telegram."
    else:
        detail = "Не удалось подготовить черновик."
    return (
        "<b>Не удалось распознать пробежку</b>\n\n"
        f"{detail} Черновик сохранён: исправьте данные или отправьте их ещё раз."
    )


def _menu_keyboard(*, linked: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🏃 Мои пробежки", callback_data="menu:history")],
        [InlineKeyboardButton(text="➕ Добавить пробежку", callback_data="menu:manual")],
        [InlineKeyboardButton(text="📊 Личный прогресс", callback_data="menu:stats")],
        [InlineKeyboardButton(text="➡️ Следующая тренировка", callback_data="menu:next")],
        [InlineKeyboardButton(text="🔒 Приватность", callback_data="menu:privacy")],
    ]
    if linked:
        rows.extend(
            (
                [InlineKeyboardButton(text="📱 Как синхронизировать", callback_data="menu:sync")],
                [
                    InlineKeyboardButton(
                        text="🔗 Подключённые устройства", callback_data="menu:devices"
                    )
                ],
            )
        )
    else:
        rows.append(
            [InlineKeyboardButton(text="📱 Подключить Health Connect", callback_data="menu:link")]
        )
    rows.append([InlineKeyboardButton(text="❓ Краткая помощь", callback_data="menu:help")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _help_keyboard() -> InlineKeyboardMarkup:
    labels = {
        "start": "Старт",
        "activities": "Активности",
        "imports": "Импорт",
        "health": "Health Connect",
        "privacy": "Приватность",
    }
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data=f"help:{key}")]
            for key, label in labels.items()
        ]
    )


def _privacy_keyboard(overview: PrivacyOverview) -> InlineKeyboardMarkup:
    global_action = "OFF" if overview.group_sharing_enabled else "ON"
    rows = [
        [
            InlineKeyboardButton(
                text=(
                    "Выключить групповой sharing"
                    if overview.group_sharing_enabled
                    else "Включить групповой sharing"
                ),
                callback_data=f"priv:g:-:{global_action}",
            )
        ]
    ]
    for group in overview.groups:
        group_hex = group.group_id.hex
        choices = (
            (PrivacyGroupAction.NONE, "не делиться"),
            (PrivacyGroupAction.SUMMARY, "кратко"),
            (PrivacyGroupAction.DETAILED, "подробно"),
            (PrivacyGroupAction.ALWAYS, "всегда"),
        )
        buttons: list[InlineKeyboardButton] = []
        for action, label in choices:
            selected = (
                group.auto_share
                if action == PrivacyGroupAction.ALWAYS
                else not group.auto_share and group.share_level.value == action.value
            )
            buttons.append(
                InlineKeyboardButton(
                    text=f"{'✓ ' if selected else ''}{label}",
                    callback_data=f"priv:r:{group_hex}:{action.value}",
                )
            )
        rows.append(buttons)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _parse_privacy_callback(value: str) -> tuple[str, uuid.UUID | None, str]:
    prefix, scope, identifier, action = value.split(":", maxsplit=3)
    if prefix != "priv":
        raise ValueError("Некорректное действие.")
    if scope == "g" and identifier == "-" and action in {"ON", "OFF"}:
        return "global", None, action
    if scope == "r" and action in {item.value for item in PrivacyGroupAction}:
        return "group", uuid.UUID(hex=identifier), action
    raise ValueError("Некорректное действие приватности.")


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
            InlineKeyboardButton(
                text=("Сохранить всё равно" if draft.duplicate_candidates else "✅ Сохранить"),
                callback_data=(
                    f"md:force:{draft_hex}"
                    if draft.duplicate_candidates
                    else f"md:save:{draft_hex}"
                ),
            ),
            InlineKeyboardButton(text="Отмена", callback_data=f"md:cancel:{draft_hex}"),
        ],
    ]
    if not draft.complete:
        if not draft.date_confirmed:
            required_field = "date"
        elif not draft.run.distance_m:
            required_field = "distance"
        else:
            required_field = "elapsed"
        rows[-1][0] = InlineKeyboardButton(
            text="Заполните обязательные поля",
            callback_data=f"md:field:{draft_hex}:{required_field}",
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _add_method_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Ввести по шагам", callback_data="add:steps")],
            [InlineKeyboardButton(text="Описать текстом", callback_data="add:text")],
            [InlineKeyboardButton(text="Отправить скриншот", callback_data="add:screenshot")],
        ]
    )


def _consent_keyboard(method: DraftInputMethod) -> InlineKeyboardMarkup:
    value = "text" if method == DraftInputMethod.TEXT else "screenshot"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Согласен", callback_data=f"assist:consent:yes:{value}"),
                InlineKeyboardButton(
                    text="Не согласен", callback_data=f"assist:consent:no:{value}"
                ),
            ]
        ]
    )


def _parse_assisted_consent_callback(value: str) -> tuple[str, DraftInputMethod]:
    try:
        prefix, consent, action, method_name = value.split(":")
        method = {
            "text": DraftInputMethod.TEXT,
            "screenshot": DraftInputMethod.SCREENSHOT,
        }[method_name]
    except (KeyError, ValueError) as error:
        raise ValueError("Некорректное действие согласия.") from error
    if prefix != "assist" or consent != "consent" or action not in {"yes", "no"}:
        raise ValueError("Некорректное действие согласия.")
    return action, method


def _require_assisted_owner(services: AppServices, telegram_user_id: int) -> None:
    if services.assisted.owner_chat_id != telegram_user_id:
        raise AssistedError("Команда доступна только владельцу.", code="OWNER_REQUIRED")


def _access_keyboard(telegram_user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Разрешить", callback_data=f"aia:grant:{telegram_user_id}"
                ),
                InlineKeyboardButton(
                    text="Отклонить", callback_data=f"aia:revoke:{telegram_user_id}"
                ),
            ]
        ]
    )


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
