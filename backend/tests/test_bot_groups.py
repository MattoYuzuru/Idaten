import uuid

from app.bot.handlers import _parse_share_callback, _share_callback_data, _share_keyboard
from app.groups.schemas import ShareTarget


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
