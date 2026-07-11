import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.activities.models import DraftInputMethod, SourceType
from app.activities.schemas import ManualDraft, ManualRunInput
from app.assisted.schemas import AssistedError
from app.bot.handlers import (
    _add_method_keyboard,
    _draft_keyboard,
    _parse_assisted_consent_callback,
    _require_assisted_owner,
)
from app.bot.messages import HELP_SECTIONS, format_manual_draft
from app.core.config import Settings
from app.services import build_services


def test_help_documents_every_release_command() -> None:
    help_text = "\n".join(HELP_SECTIONS.values())
    commands = {
        "start",
        "menu",
        "help",
        "run",
        "stats",
        "week",
        "pr",
        "next",
        "plan",
        "imports",
        "link",
        "devices",
        "revoke_device",
        "privacy",
        "share",
        "setup_group",
        "join",
        "leave",
        "month",
        "group_goal",
        "leaderboard",
        "streaks",
        "external_processing",
    }
    assert all(f"/{command}" in help_text for command in commands)


def test_manual_preview_escapes_title_and_callbacks_contain_only_opaque_id() -> None:
    draft_id = uuid.uuid4()
    draft = ManualDraft(
        draft_id=draft_id,
        version=2,
        expires_at=datetime(2026, 7, 9, tzinfo=UTC),
        status="ACTIVE",
        run=ManualRunInput(
            distance_m=10_000,
            elapsed_time_sec=3_600,
            started_at=datetime(2026, 7, 8, tzinfo=UTC),
            timezone="Europe/Moscow",
            title="Tempo <script>&",
        ),
        complete=True,
        telegram_message_id=100,
    )

    rendered = format_manual_draft(draft)
    keyboard = _draft_keyboard(draft)
    callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]

    assert "Tempo &lt;script&gt;&amp;" in rendered
    assert "Tempo <script>" not in rendered
    assert all(value is not None and draft_id.hex in value for value in callbacks)
    assert all(
        value is not None and "10000" not in value and len(value) <= 64 for value in callbacks
    )


def test_add_activity_selector_uses_functional_labels() -> None:
    labels = [row[0].text for row in _add_method_keyboard().inline_keyboard]

    assert labels == ["Ввести по шагам", "Описать текстом", "Отправить скриншот"]
    assert "AI" not in " ".join(labels).upper()


def test_assisted_preview_shows_source_and_targets_missing_duration() -> None:
    draft = ManualDraft(
        draft_id=uuid.uuid4(),
        version=1,
        expires_at=datetime(2026, 7, 12, tzinfo=UTC),
        status="ACTIVE",
        run=ManualRunInput(
            distance_m=5_000,
            elapsed_time_sec=0,
            started_at=datetime(2026, 7, 11, tzinfo=UTC),
            timezone="Europe/Moscow",
        ),
        complete=False,
        telegram_message_id=None,
        input_method=DraftInputMethod.TEXT,
        source_type=SourceType.TEXT,
    )

    rendered = format_manual_draft(draft)
    keyboard = _draft_keyboard(draft)

    assert "Способ: описание текстом" in rendered
    assert keyboard.inline_keyboard[-1][0].callback_data == (
        f"md:field:{draft.draft_id.hex}:elapsed"
    )


def test_consent_callback_parser_rejects_forged_actions() -> None:
    assert _parse_assisted_consent_callback("assist:consent:yes:text") == (
        "yes",
        DraftInputMethod.TEXT,
    )
    assert _parse_assisted_consent_callback("assist:consent:no:screenshot") == (
        "no",
        DraftInputMethod.SCREENSHOT,
    )
    with pytest.raises(ValueError, match="Некорректное"):
        _parse_assisted_consent_callback("assist:consent:grant:text")
    with pytest.raises(ValueError, match="Некорректное"):
        _parse_assisted_consent_callback("assist:consent:yes")


@pytest.mark.asyncio
async def test_transport_repeats_owner_check() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    services = build_services(
        async_sessionmaker(engine, expire_on_commit=False),
        Settings(
            database_url="sqlite+aiosqlite://",
            bot_owner_telegram_id=42,
            _env_file=None,
        ),
    )
    try:
        _require_assisted_owner(services, 42)
        with pytest.raises(AssistedError) as captured:
            _require_assisted_owner(services, 43)
        assert captured.value.code == "OWNER_REQUIRED"
    finally:
        await engine.dispose()
