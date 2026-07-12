import uuid
from dataclasses import replace
from datetime import UTC, datetime
from html import escape
from io import BytesIO

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InaccessibleMessage, InlineKeyboardMarkup, Message

from app.ai.contracts import AiError, AiTask
from app.assisted.models import ExternalAiAccessStatus
from app.assisted.schemas import AssistedError, InputGateStatus
from app.bot.messages import EXTERNAL_AI_CONSENT_TEXT
from app.bot.next_keyboards import (
    FIELD_NAMES,
    achievement_keyboard,
    ai_consent_keyboard,
    boolean_keyboard,
    check_in_method_keyboard,
    duration_keyboard,
    goal_keyboard,
    location_keyboard,
    preview_keyboard,
    recommendation_keyboard,
    scale_keyboard,
    sleep_duration_keyboard,
    target_time_keyboard,
)
from app.coach.next_messages import GOAL_LABELS, format_check_in
from app.coach.schemas import CoachError, NextFlowResult, NextFlowState
from app.goals.domain import IMPROVEMENT_GOALS, RunningGoalType
from app.goals.schemas import GoalError
from app.readiness.domain import CheckInInputSource, CheckInPhase
from app.readiness.schemas import ReadinessDraft, ReadinessError, ReadinessValues
from app.services import AppServices
from app.users.schemas import TelegramIdentity

router = Router(name="adaptive-next")
router.message.filter(F.chat.type == ChatType.PRIVATE)
router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)


@router.message(Command("next"))
async def next_command(message: Message, services: AppServices) -> None:
    await _show_state(message, _message_user_id(message), services)


@router.callback_query(F.data == "menu:next")
async def next_from_menu(callback: CallbackQuery, services: AppServices) -> None:
    if callback.message is not None:
        await _show_state(callback.message, callback.from_user.id, services)
    await callback.answer()


@router.callback_query(F.data == "next:change-goal")
async def change_goal(callback: CallbackQuery) -> None:
    if callback.message is not None:
        await callback.message.answer(
            "Какая у вас сейчас основная цель?", reply_markup=goal_keyboard()
        )
    await callback.answer()


@router.callback_query(F.data.startswith("next:goal-time:"))
async def choose_goal_time(callback: CallbackQuery) -> None:
    try:
        goal = RunningGoalType((callback.data or "").split(":", 2)[2])
        if goal not in IMPROVEMENT_GOALS:
            raise ValueError
    except (ValueError, IndexError):
        await callback.answer("Некорректная цель.", show_alert=True)
        return
    if callback.message is not None:
        await callback.message.answer(
            "Выберите целевое время. Его можно изменить вместе с целью позже.",
            reply_markup=target_time_keyboard(goal),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("next:goal:"))
async def choose_goal(callback: CallbackQuery, services: AppServices) -> None:
    parts = (callback.data or "").split(":")
    try:
        goal_type = RunningGoalType(parts[2])
        target = int(parts[3]) if len(parts) == 4 else None
        await services.goals.select(
            callback.from_user.id,
            goal_type,
            target_duration_sec=target,
        )
    except (GoalError, ValueError, IndexError) as error:
        await callback.answer(str(error) or "Некорректная цель.", show_alert=True)
        return
    if callback.message is not None:
        await callback.message.answer(f"Цель сохранена: {GOAL_LABELS[goal_type]}.")
        await _show_state(callback.message, callback.from_user.id, services)
    await callback.answer()


@router.callback_query(F.data.startswith("next:method:"))
async def choose_method(callback: CallbackQuery, services: AppServices) -> None:
    parts = (callback.data or "").split(":")
    try:
        phase = CheckInPhase(parts[2])
        method = parts[3]
    except (ValueError, IndexError):
        await callback.answer("Некорректный способ ввода.", show_alert=True)
        return
    if method in {"text", "voice"}:
        identity = _callback_identity(callback)
        status = await services.assisted.ai_gate(identity, AiTask.READINESS_EXTRACTION)
        if method == "voice" and status == InputGateStatus.READY:
            status = await services.assisted.ai_gate(identity, AiTask.VOICE_TRANSCRIPTION)
        if status == InputGateStatus.CONSENT_REQUIRED:
            if callback.message is not None:
                await callback.message.answer(
                    EXTERNAL_AI_CONSENT_TEXT,
                    reply_markup=ai_consent_keyboard(phase.value, method),
                )
            await callback.answer()
            return
        if status != InputGateStatus.READY:
            await callback.answer(
                "Внешний ввод пока недоступен. Ручная проверка всегда работает.",
                show_alert=True,
            )
            return
        await _begin_ai_input(callback, services, phase, method)
        return
    if method != "manual":
        await callback.answer("Некорректный способ ввода.", show_alert=True)
        return
    try:
        draft = await services.next_run.start_check_in(
            callback.from_user.id, phase, moment=datetime.now(UTC)
        )
    except (CoachError, ReadinessError) as error:
        await callback.answer(str(error), show_alert=True)
        return
    if callback.message is not None:
        await _ask_field(callback.message, draft, "overall_readiness")
    await callback.answer()


@router.callback_query(F.data.startswith("next:consent:"))
async def readiness_consent(callback: CallbackQuery, services: AppServices) -> None:
    parts = (callback.data or "").split(":")
    try:
        action = parts[2]
        phase = CheckInPhase(parts[3])
        method = parts[4]
        if action not in {"yes", "no"} or method not in {"text", "voice"}:
            raise ValueError
    except (ValueError, IndexError):
        await callback.answer("Некорректный callback.", show_alert=True)
        return
    if action == "no":
        if callback.message is not None:
            await callback.message.answer(
                "Внешняя обработка не включена. Продолжите ручной ввод.",
                reply_markup=check_in_method_keyboard(phase.value),
            )
        await callback.answer()
        return
    try:
        task = AiTask.READINESS_EXTRACTION if method == "text" else AiTask.VOICE_TRANSCRIPTION
        request = await services.assisted.accept_consent(_callback_identity(callback), task=task)
    except AssistedError as error:
        await callback.answer(str(error), show_alert=True)
        return
    if request.notify_owner and callback.bot is not None:
        owner_id = services.assisted.owner_telegram_user_id
        if owner_id is not None:
            await callback.bot.send_message(
                owner_id,
                "Запрос external AI access: "
                f"user <code>{request.telegram_user_id}</code>, "
                f"display name {escape(request.display_name)}.",
            )
            await services.assisted.mark_notification_sent(request.telegram_user_id)
    if request.status == ExternalAiAccessStatus.ALLOWED:
        await _begin_ai_input(callback, services, phase, method)
        return
    if callback.message is not None:
        await callback.message.answer(
            "Согласие сохранено; требуется owner approval. Ручной ввод уже доступен.",
            reply_markup=check_in_method_keyboard(phase.value),
        )
    await callback.answer()


@router.message(F.voice)
async def readiness_voice(message: Message, services: AppServices) -> None:
    if message.from_user is None or message.voice is None:
        return
    pending = await services.ai_readiness.pending(message.from_user.id, "ai_voice")
    if pending is None:
        await message.answer("Сначала откройте /next и выберите голосовой ввод.")
        return
    if (
        message.voice.file_size is not None
        and message.voice.file_size > services.ai_readiness.max_audio_bytes
    ):
        await message.answer("Голосовое сообщение слишком большое. Продолжите ручной ввод.")
        return
    if message.bot is None:
        await message.answer("Telegram bot недоступен.")
        return
    try:
        buffer = BytesIO()
        await message.bot.download(message.voice, destination=buffer)
        draft = await services.ai_readiness.extract_voice(
            message.from_user.id,
            pending.check_in_id,
            buffer.getvalue(),
            "audio/ogg",
        )
    except (AiError, AssistedError, ReadinessError) as error:
        await message.answer(
            f"Не удалось распознать голос: {escape(str(error))}. Ручной ввод доступен."
        )
        return
    await message.answer(format_check_in(draft), reply_markup=preview_keyboard(draft))


@router.callback_query(F.data.startswith("next:f:"))
async def set_field(callback: CallbackQuery, services: AppServices) -> None:
    try:
        draft_id, field, raw = _parse_field(callback.data)
        draft = await services.readiness.get(callback.from_user.id, draft_id)
        updated = await _update_field(services, callback.from_user.id, draft, field, raw)
        next_field = _next_field(updated, field, raw)
    except (ReadinessError, ValueError) as error:
        await callback.answer(str(error), show_alert=True)
        return
    if callback.message is not None:
        if next_field is None:
            await callback.message.answer(
                format_check_in(updated), reply_markup=preview_keyboard(updated)
            )
        else:
            await _ask_field(callback.message, updated, next_field)
    await callback.answer()


@router.callback_query(F.data.startswith("next:e:"))
async def edit_field(callback: CallbackQuery, services: AppServices) -> None:
    parts = (callback.data or "").split(":")
    try:
        draft = await services.readiness.get(callback.from_user.id, uuid.UUID(hex=parts[2]))
        field = FIELD_NAMES[parts[3]]
    except (ReadinessError, ValueError, IndexError, KeyError) as error:
        await callback.answer(str(error), show_alert=True)
        return
    if callback.message is not None:
        await _ask_field(callback.message, draft, field)
    await callback.answer()


@router.callback_query(F.data.startswith("next:clear:"))
async def clear_field(callback: CallbackQuery, services: AppServices) -> None:
    parts = (callback.data or "").split(":")
    try:
        draft = await services.readiness.clear_optional(
            callback.from_user.id, uuid.UUID(hex=parts[2]), parts[3]
        )
    except (ReadinessError, ValueError, IndexError) as error:
        await callback.answer(str(error), show_alert=True)
        return
    if callback.message is not None:
        await callback.message.answer(format_check_in(draft), reply_markup=preview_keyboard(draft))
    await callback.answer("Очищено")


@router.callback_query(F.data.startswith("next:confirm:"))
async def confirm_check_in(callback: CallbackQuery, services: AppServices) -> None:
    try:
        draft_id = uuid.UUID(hex=(callback.data or "").split(":", 2)[2])
        result = await services.next_run.confirm_and_recommend(
            callback.from_user.id,
            draft_id,
            idempotency_key=f"telegram:{callback.id}",
        )
    except (CoachError, ReadinessError, ValueError) as error:
        await callback.answer(str(error), show_alert=True)
        return
    if callback.message is not None:
        await callback.message.answer(
            result.message,
            reply_markup=recommendation_keyboard(result.recommendation_id),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("next:cancel:"))
async def cancel_check_in(callback: CallbackQuery, services: AppServices) -> None:
    try:
        draft_id = uuid.UUID(hex=(callback.data or "").split(":", 2)[2])
        await services.readiness.cancel(callback.from_user.id, draft_id)
    except (ReadinessError, ValueError) as error:
        await callback.answer(str(error), show_alert=True)
        return
    if callback.message is not None:
        await callback.message.answer("Проверка готовности отменена. Ручной /next доступен позже.")
    await callback.answer()


@router.callback_query(F.data.startswith("next:complete:"))
async def complete_goal(callback: CallbackQuery, services: AppServices) -> None:
    try:
        goal_id = uuid.UUID(hex=(callback.data or "").split(":", 2)[2])
        await services.goals.complete(callback.from_user.id, goal_id)
    except (GoalError, ValueError) as error:
        await callback.answer(str(error), show_alert=True)
        return
    if callback.message is not None:
        await callback.message.answer(
            "Цель отмечена выполненной. Выберите следующую.", reply_markup=goal_keyboard()
        )
    await callback.answer()


@router.callback_query(F.data == "next:achievement-later")
async def achievement_later(callback: CallbackQuery) -> None:
    await callback.answer("Цель остаётся активной.")


@router.callback_query(F.data.startswith("next:revise:"))
async def revise(callback: CallbackQuery, services: AppServices) -> None:
    try:
        recommendation_id = uuid.UUID(hex=(callback.data or "").split(":", 2)[2])
        draft = await services.next_run.revision_draft(callback.from_user.id, recommendation_id)
    except (CoachError, ReadinessError, ValueError) as error:
        await callback.answer(str(error), show_alert=True)
        return
    if callback.message is not None:
        await callback.message.answer(format_check_in(draft), reply_markup=preview_keyboard(draft))
    await callback.answer()


@router.callback_query(F.data.startswith("next:change-time:"))
async def change_available_time(callback: CallbackQuery, services: AppServices) -> None:
    try:
        recommendation_id = uuid.UUID(hex=(callback.data or "").split(":", 2)[2])
        draft = await services.next_run.revision_draft(callback.from_user.id, recommendation_id)
    except (CoachError, ReadinessError, ValueError) as error:
        await callback.answer(str(error), show_alert=True)
        return
    if callback.message is not None:
        await _ask_field(callback.message, draft, "available_time_sec")
    await callback.answer()


@router.callback_query(F.data.startswith("next:recalc:"))
async def recalculate(callback: CallbackQuery, services: AppServices) -> None:
    try:
        recommendation_id = uuid.UUID(hex=(callback.data or "").split(":", 2)[2])
        result = await services.next_run.recalculate(
            callback.from_user.id,
            recommendation_id,
            idempotency_key=f"telegram-recalc:{callback.id}",
        )
    except (CoachError, ReadinessError, ValueError) as error:
        await callback.answer(str(error), show_alert=True)
        return
    if callback.message is not None:
        await callback.message.answer(
            "Входы не менялись; создана новая audit revision.\n\n" + result.message,
            reply_markup=recommendation_keyboard(result.recommendation_id),
        )
    await callback.answer()


@router.callback_query(F.data == "next:home")
async def next_home(callback: CallbackQuery) -> None:
    if callback.message is not None:
        await callback.message.answer(
            "<b>Главное меню</b>\n\n"
            "/run — добавить пробежку\n"
            "/next — следующая пробежка\n"
            "/stats — прогресс"
        )
    await callback.answer()


async def _show_state(
    message: Message | InaccessibleMessage, user_id: int, services: AppServices
) -> None:
    try:
        result = await services.next_run.state(user_id)
    except (CoachError, GoalError, ReadinessError) as error:
        await message.answer(escape(str(error)))
        return
    await _render_state(message, result)


async def _render_state(message: Message | InaccessibleMessage, result: NextFlowResult) -> None:
    if result.state == NextFlowState.NEED_GOAL:
        await message.answer("Какая у вас сейчас основная цель?", reply_markup=goal_keyboard())
    elif result.state in {NextFlowState.NEED_CHECK_IN_METHOD, NextFlowState.NEED_PRE_RUN_CHECK_IN}:
        phase = (
            CheckInPhase.PRE_RUN
            if result.state == NextFlowState.NEED_PRE_RUN_CHECK_IN
            else CheckInPhase.POST_RUN
        )
        text = (
            "Перед стартом быстро перепроверьте самочувствие."
            if phase == CheckInPhase.PRE_RUN
            else "Как заполнить короткую проверку готовности?"
        )
        await message.answer(text, reply_markup=check_in_method_keyboard(phase.value))
    elif result.state == NextFlowState.EDIT_CHECK_IN and result.check_in is not None:
        await message.answer(
            format_check_in(result.check_in),
            reply_markup=preview_keyboard(result.check_in),
        )
    elif result.state in {NextFlowState.SHOW_PROVISIONAL, NextFlowState.SHOW_CONFIRMED}:
        assert result.recommendation is not None
        await message.answer(
            result.recommendation.message,
            reply_markup=recommendation_keyboard(result.recommendation.recommendation_id),
        )
    elif result.state == NextFlowState.GOAL_ACHIEVEMENT_CONFIRMATION:
        assert result.achievement is not None
        await message.answer(
            "Похоже, цель достигнута. Отметить её выполненной?",
            reply_markup=achievement_keyboard(result.achievement.goal.goal_id),
        )


async def _ask_field(
    message: Message | InaccessibleMessage, draft: ReadinessDraft, field: str
) -> None:
    prompt, keyboard = _field_prompt(draft, field)
    await message.answer(prompt, reply_markup=keyboard)


def _field_prompt(draft: ReadinessDraft, field: str) -> tuple[str, InlineKeyboardMarkup]:
    draft_id = draft.check_in_id
    if field == "overall_readiness":
        return "Общая готовность сегодня: 1–5?", scale_keyboard(draft_id, field, range(1, 6))
    if field == "general_fatigue":
        return "Общая усталость: 0–10?", scale_keyboard(draft_id, field, range(0, 11))
    if field == "muscle_soreness":
        return "Мышечная болезненность: 0–10?", scale_keyboard(draft_id, field, range(0, 11))
    if field == "pain_present":
        return "Есть боль?", boolean_keyboard(draft_id, field)
    if field == "pain_severity":
        return "Выраженность боли: 0–10?", scale_keyboard(draft_id, field, range(0, 11))
    if field == "pain_location":
        return "Где ощущается боль?", location_keyboard(draft_id)
    if field == "pain_affects_movement":
        return "Боль влияет на движение?", boolean_keyboard(draft_id, field)
    if field == "pain_is_new":
        return "Эта боль новая?", boolean_keyboard(draft_id, field)
    if field == "pain_is_worsening":
        return "Боль усиливается?", boolean_keyboard(draft_id, field)
    if field == "illness_symptoms":
        return "Есть признаки болезни?", boolean_keyboard(draft_id, field)
    if field == "sleep_quality":
        return "Качество сна 1–5? Можно пропустить.", scale_keyboard(
            draft_id, field, range(1, 6), optional=True
        )
    if field == "sleep_duration_sec":
        return "Сколько длился сон? Можно не указывать.", sleep_duration_keyboard(draft_id)
    if field == "external_load":
        return "Внешняя нагрузка вне бега: 0–10?", scale_keyboard(draft_id, field, range(0, 11))
    if field == "motivation":
        return "Мотивация 1–5? Можно пропустить.", scale_keyboard(
            draft_id, field, range(1, 6), optional=True
        )
    if field == "available_time_sec":
        return "Сколько времени доступно?", duration_keyboard(draft_id, field)
    if field == "session_rpe":
        return "Насколько тяжёлой была прошлая пробежка: RPE 1–10?", scale_keyboard(
            draft_id, field, range(1, 11), optional=True
        )
    raise ReadinessError("Неизвестное поле check-in.")


async def _update_field(
    services: AppServices,
    user_id: int,
    draft: ReadinessDraft,
    field: str,
    raw: str,
) -> ReadinessDraft:
    values = draft.values
    value: object = None if raw == "skip" else int(raw) if raw.isdigit() else raw
    if field in {
        "pain_present",
        "pain_affects_movement",
        "pain_is_new",
        "pain_is_worsening",
        "illness_symptoms",
    }:
        value = raw == "1"
    if field == "pain_location":
        value = {
            "knee": "колено",
            "foot": "стопа",
            "shin": "голень",
            "hip": "бедро",
            "other": "другая зона",
        }.get(raw)
        if value is None:
            raise ReadinessError("Некорректная зона боли.")
    if field == "pain_present" and value is False:
        values = replace(
            values,
            pain_present=False,
            pain_severity=None,
            pain_location=None,
            pain_affects_movement=None,
            pain_is_new=None,
            pain_is_worsening=None,
        )
    else:
        values = _replace_value(values, field, value)
    return await services.readiness.update(
        user_id,
        draft.check_in_id,
        values,
        expected_version=draft.version,
    )


def _next_field(draft: ReadinessDraft, field: str, raw: str) -> str | None:
    if field == "overall_readiness":
        return "general_fatigue"
    if field == "general_fatigue":
        return "muscle_soreness"
    if field == "muscle_soreness":
        return "pain_present"
    if field == "pain_present":
        return "pain_severity" if raw == "1" else "illness_symptoms"
    pain_order = {
        "pain_severity": "pain_location",
        "pain_location": "pain_affects_movement",
        "pain_affects_movement": "pain_is_new",
        "pain_is_new": "pain_is_worsening",
        "pain_is_worsening": "illness_symptoms",
    }
    if field in pain_order:
        return pain_order[field]
    if field == "illness_symptoms":
        return "sleep_quality"
    if field == "sleep_quality":
        return "sleep_duration_sec"
    if field == "sleep_duration_sec":
        return "external_load"
    if field == "external_load":
        return "motivation"
    if field == "motivation":
        return "available_time_sec"
    if field == "available_time_sec":
        return (
            "session_rpe"
            if draft.phase == CheckInPhase.POST_RUN and draft.linked_activity_id is not None
            else None
        )
    return None


def _replace_value(values: ReadinessValues, field: str, value: object) -> ReadinessValues:
    if field in {
        "overall_readiness",
        "general_fatigue",
        "muscle_soreness",
        "motivation",
        "sleep_quality",
        "sleep_duration_sec",
        "external_load",
        "pain_severity",
        "available_time_sec",
        "session_rpe",
    }:
        number = _optional_number(value)
        if field == "overall_readiness":
            return replace(values, overall_readiness=number)
        if field == "general_fatigue":
            return replace(values, general_fatigue=number)
        if field == "muscle_soreness":
            return replace(values, muscle_soreness=number)
        if field == "motivation":
            return replace(values, motivation=number)
        if field == "sleep_quality":
            return replace(values, sleep_quality=number)
        if field == "sleep_duration_sec":
            return replace(values, sleep_duration_sec=number)
        if field == "external_load":
            return replace(values, external_load=number)
        if field == "pain_severity":
            return replace(values, pain_severity=number)
        if field == "available_time_sec":
            return replace(values, available_time_sec=number)
        return replace(values, session_rpe=number)
    if field in {
        "pain_present",
        "pain_affects_movement",
        "pain_is_new",
        "pain_is_worsening",
        "illness_symptoms",
    }:
        if not isinstance(value, bool):
            raise ReadinessError("Некорректное логическое значение.")
        if field == "pain_present":
            return replace(values, pain_present=value)
        if field == "pain_affects_movement":
            return replace(values, pain_affects_movement=value)
        if field == "pain_is_new":
            return replace(values, pain_is_new=value)
        if field == "pain_is_worsening":
            return replace(values, pain_is_worsening=value)
        return replace(values, illness_symptoms=value)
    if field == "pain_location" and isinstance(value, str):
        return replace(values, pain_location=value)
    raise ReadinessError("Неизвестное поле check-in.")


def _optional_number(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ReadinessError("Ожидалось целое число.")
    return value


def _parse_field(data: str | None) -> tuple[uuid.UUID, str, str]:
    parts = (data or "").split(":")
    if len(parts) != 5 or parts[:2] != ["next", "f"]:
        raise ReadinessError("Некорректный callback.")
    try:
        field = FIELD_NAMES[parts[3]]
    except KeyError as error:
        raise ReadinessError("Некорректный callback.") from error
    return uuid.UUID(hex=parts[2]), field, parts[4]


def _message_user_id(message: Message) -> int:
    if message.from_user is None:
        raise CoachError("Не удалось определить пользователя.")
    return message.from_user.id


async def _begin_ai_input(
    callback: CallbackQuery,
    services: AppServices,
    phase: CheckInPhase,
    method: str,
) -> None:
    source = CheckInInputSource.AI_TEXT if method == "text" else CheckInInputSource.AI_VOICE
    try:
        draft = await services.next_run.start_check_in(
            callback.from_user.id,
            phase,
            source=source,
        )
        await services.readiness.set_pending_field(
            callback.from_user.id,
            draft.check_in_id,
            "ai_text" if method == "text" else "ai_voice",
        )
    except (CoachError, ReadinessError) as error:
        await callback.answer(str(error), show_alert=True)
        return
    if callback.message is not None:
        await callback.message.answer(
            "Опишите текущее самочувствие одним сообщением."
            if method == "text"
            else "Отправьте одно голосовое сообщение о текущем самочувствии."
        )
    await callback.answer()


def _callback_identity(callback: CallbackQuery) -> TelegramIdentity:
    chat_id = callback.from_user.id
    if callback.message is not None:
        chat_id = callback.message.chat.id
    return TelegramIdentity(
        telegram_user_id=callback.from_user.id,
        private_chat_id=chat_id,
        username=callback.from_user.username,
        first_name=callback.from_user.first_name,
        last_name=callback.from_user.last_name,
    )
