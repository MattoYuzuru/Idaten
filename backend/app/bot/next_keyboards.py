import uuid

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.goals.domain import RunningGoalType
from app.readiness.domain import CheckInPhase
from app.readiness.schemas import ReadinessDraft

FIELD_CODES = {
    "overall_readiness": "o",
    "general_fatigue": "f",
    "muscle_soreness": "s",
    "pain_present": "p",
    "pain_severity": "ps",
    "pain_location": "pl",
    "pain_affects_movement": "pm",
    "pain_is_new": "pn",
    "pain_is_worsening": "pw",
    "illness_symptoms": "i",
    "sleep_quality": "sq",
    "sleep_duration_sec": "sd",
    "external_load": "x",
    "motivation": "m",
    "available_time_sec": "a",
    "session_rpe": "r",
}
FIELD_NAMES = {value: key for key, value in FIELD_CODES.items()}


def goal_keyboard() -> InlineKeyboardMarkup:
    rows = [
        (_goal("Впервые 5 км", RunningGoalType.FIRST_5K),),
        (_goal("Впервые 10 км", RunningGoalType.FIRST_10K),),
        (_goal("Первый полумарафон", RunningGoalType.FIRST_HALF),),
        (_goal("Первый марафон", RunningGoalType.FIRST_MARATHON),),
        (
            InlineKeyboardButton(
                text="Улучшить полумарафон",
                callback_data="next:goal-time:IMPROVE_HALF",
            ),
        ),
        (
            InlineKeyboardButton(
                text="Улучшить марафон",
                callback_data="next:goal-time:IMPROVE_MARATHON",
            ),
        ),
        (_goal("Общая выносливость", RunningGoalType.GENERAL_ENDURANCE),),
    ]
    return InlineKeyboardMarkup(inline_keyboard=[list(row) for row in rows])


def target_time_keyboard(goal: RunningGoalType) -> InlineKeyboardMarkup:
    seconds = (
        (5_400, 6_300, 7_200, 9_000)
        if goal == RunningGoalType.IMPROVE_HALF
        else (10_800, 12_600, 14_400, 18_000)
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_clock(value),
                    callback_data=f"next:goal:{goal.value}:{value}",
                )
                for value in seconds[index : index + 2]
            ]
            for index in range(0, len(seconds), 2)
        ]
    )


def check_in_method_keyboard(phase: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Ввести по шагам", callback_data=f"next:method:{phase}:manual"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Описать текстом", callback_data=f"next:method:{phase}:text"
                ),
                InlineKeyboardButton(
                    text="Отправить голосом", callback_data=f"next:method:{phase}:voice"
                ),
            ],
        ]
    )


def ai_consent_keyboard(phase: str, method: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Согласен",
                    callback_data=f"next:consent:yes:{phase}:{method}",
                ),
                InlineKeyboardButton(
                    text="Не согласен",
                    callback_data=f"next:consent:no:{phase}:{method}",
                ),
            ]
        ]
    )


def scale_keyboard(
    draft_id: uuid.UUID,
    field: str,
    values: range,
    *,
    optional: bool = False,
) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=str(value), callback_data=_field(draft_id, field, str(value)))
        for value in values
    ]
    rows = [buttons[index : index + 5] for index in range(0, len(buttons), 5)]
    if optional:
        rows.append(
            [InlineKeyboardButton(text="Пропустить", callback_data=_field(draft_id, field, "skip"))]
        )
    rows.append([_cancel(draft_id)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def boolean_keyboard(draft_id: uuid.UUID, field: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Нет", callback_data=_field(draft_id, field, "0")),
                InlineKeyboardButton(text="Да", callback_data=_field(draft_id, field, "1")),
            ],
            [_cancel(draft_id)],
        ]
    )


def location_keyboard(draft_id: uuid.UUID) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=label, callback_data=_field(draft_id, "pain_location", key)
                )
                for label, key in (("Колено", "knee"), ("Стопа", "foot"))
            ],
            [
                InlineKeyboardButton(
                    text=label, callback_data=_field(draft_id, "pain_location", key)
                )
                for label, key in (("Голень", "shin"), ("Бедро", "hip"))
            ],
            [
                InlineKeyboardButton(
                    text="Другая зона", callback_data=_field(draft_id, "pain_location", "other")
                )
            ],
            [_cancel(draft_id)],
        ]
    )


def duration_keyboard(draft_id: uuid.UUID, field: str) -> InlineKeyboardMarkup:
    values = (1_200, 1_800, 2_700, 3_600, 5_400)
    rows = [
        [
            InlineKeyboardButton(
                text=f"{value // 60} мин",
                callback_data=_field(draft_id, field, str(value)),
            )
            for value in values[:3]
        ],
        [
            InlineKeyboardButton(
                text=f"{value // 60} мин",
                callback_data=_field(draft_id, field, str(value)),
            )
            for value in values[3:]
        ],
        [InlineKeyboardButton(text="Пропустить", callback_data=_field(draft_id, field, "skip"))],
        [_cancel(draft_id)],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def sleep_duration_keyboard(draft_id: uuid.UUID) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{hours} ч",
                    callback_data=_field(draft_id, "sleep_duration_sec", str(hours * 3_600)),
                )
                for hours in (6, 7, 8, 9)
            ],
            [
                InlineKeyboardButton(
                    text="Не указывать",
                    callback_data=_field(draft_id, "sleep_duration_sec", "skip"),
                )
            ],
            [_cancel(draft_id)],
        ]
    )


def preview_keyboard(draft: ReadinessDraft) -> InlineKeyboardMarkup:
    draft_id = draft.check_in_id
    editable_schedule = [
        InlineKeyboardButton(
            text="Доступное время", callback_data=_edit(draft_id, "available_time_sec")
        )
    ]
    if draft.phase == CheckInPhase.POST_RUN and draft.linked_activity_id is not None:
        editable_schedule.append(
            InlineKeyboardButton(
                text="RPE прошлой пробежки", callback_data=_edit(draft_id, "session_rpe")
            )
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Подтвердить", callback_data=f"next:confirm:{draft_id.hex}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Готовность", callback_data=_edit(draft_id, "overall_readiness")
                ),
                InlineKeyboardButton(
                    text="Усталость", callback_data=_edit(draft_id, "general_fatigue")
                ),
                InlineKeyboardButton(
                    text="Мышцы", callback_data=_edit(draft_id, "muscle_soreness")
                ),
            ],
            [
                InlineKeyboardButton(text="Боль", callback_data=_edit(draft_id, "pain_present")),
                InlineKeyboardButton(
                    text="Болезнь", callback_data=_edit(draft_id, "illness_symptoms")
                ),
                InlineKeyboardButton(text="Сон", callback_data=_edit(draft_id, "sleep_quality")),
            ],
            [
                InlineKeyboardButton(
                    text="Нагрузка", callback_data=_edit(draft_id, "external_load")
                ),
                InlineKeyboardButton(text="Мотивация", callback_data=_edit(draft_id, "motivation")),
            ],
            editable_schedule,
            [
                InlineKeyboardButton(
                    text="Очистить сон", callback_data=f"next:clear:{draft_id.hex}:sleep"
                ),
                InlineKeyboardButton(
                    text="Очистить время", callback_data=f"next:clear:{draft_id.hex}:available_time"
                ),
            ],
            [_cancel(draft_id)],
        ]
    )


def recommendation_keyboard(recommendation_id: uuid.UUID) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Самочувствие изменилось",
                    callback_data=f"next:revise:{recommendation_id.hex}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Изменить доступное время",
                    callback_data=f"next:change-time:{recommendation_id.hex}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Пересчитать",
                    callback_data=f"next:recalc:{recommendation_id.hex}",
                )
            ],
            [InlineKeyboardButton(text="Изменить цель", callback_data="next:change-goal")],
        ]
    )


def achievement_keyboard(goal_id: uuid.UUID) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Отметить выполненной", callback_data=f"next:complete:{goal_id.hex}"
                )
            ],
            [InlineKeyboardButton(text="Пока нет", callback_data="next:achievement-later")],
        ]
    )


def after_run_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Рассчитать следующую пробежку", callback_data="menu:next")],
            [InlineKeyboardButton(text="Вернуться в меню", callback_data="next:home")],
        ]
    )


def _goal(label: str, goal: RunningGoalType) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=label, callback_data=f"next:goal:{goal.value}")


def _field(draft_id: uuid.UUID, field: str, value: str) -> str:
    return f"next:f:{draft_id.hex}:{FIELD_CODES[field]}:{value}"


def _edit(draft_id: uuid.UUID, field: str) -> str:
    return f"next:e:{draft_id.hex}:{FIELD_CODES[field]}"


def _cancel(draft_id: uuid.UUID) -> InlineKeyboardButton:
    return InlineKeyboardButton(text="Отменить", callback_data=f"next:cancel:{draft_id.hex}")


def _clock(seconds: int) -> str:
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}"
