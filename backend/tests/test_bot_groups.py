import uuid
from datetime import UTC, datetime

from app.activities.models import SourceType
from app.bot.handlers import (
    _import_keyboard,
    _parse_import_callback,
    _parse_share_callback,
    _share_callback_data,
    _share_keyboard,
)
from app.groups.schemas import ShareTarget
from app.ingestion.schemas import ImportPreview


def test_share_callback_data_fits_telegram_limit_and_round_trips() -> None:
    activity_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
    target = ShareTarget(
        telegram_chat_id=-1_001_234_567_890,
        title="Idaten Runners",
        auto_share=False,
    )

    callback_data = _share_callback_data("a", target, activity_id)

    assert len(callback_data.encode()) <= 64
    assert _parse_share_callback(callback_data) == (
        "a",
        target.telegram_chat_id,
        activity_id,
    )


def test_share_keyboard_has_explicit_choices_for_each_group() -> None:
    activity_id = uuid.uuid4()
    targets = (
        ShareTarget(-1001, "First", False),
        ShareTarget(-1002, "Second", False),
    )

    keyboard = _share_keyboard(targets, activity_id)

    assert len(keyboard.inline_keyboard) == 2
    assert [[button.text for button in row] for row in keyboard.inline_keyboard] == [
        ["Да · First", "Нет", "Всегда"],
        ["Да · Second", "Нет", "Всегда"],
    ]


def test_import_callback_fits_telegram_limit_and_force_requires_candidate() -> None:
    import_id = uuid.uuid4()
    preview = ImportPreview(
        import_id=import_id,
        source_type=SourceType.GPX,
        started_at=datetime(2026, 7, 6, tzinfo=UTC),
        distance_m=5_000,
        elapsed_time_sec=1_800,
        title=None,
        duplicate_candidates=(),
    )

    keyboard = _import_keyboard(preview)
    callback_data = keyboard.inline_keyboard[0][0].callback_data

    assert callback_data is not None
    assert len(callback_data.encode()) <= 64
    assert _parse_import_callback(callback_data) == ("y", import_id)
    assert [button.text for button in keyboard.inline_keyboard[0]] == [
        "Подтвердить",
        "Отмена",
    ]
