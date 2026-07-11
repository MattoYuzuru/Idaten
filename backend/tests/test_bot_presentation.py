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
    _menu_keyboard,
    _parse_assisted_consent_callback,
    _parse_privacy_callback,
    _privacy_keyboard,
    _require_assisted_owner,
)
from app.bot.messages import HELP_SECTIONS, REPOSITORY_URL, format_manual_draft, format_privacy
from app.bot.runtime import PRIVATE_BOT_COMMANDS
from app.core.config import Settings
from app.groups.models import GroupRole, ShareLevel
from app.groups.schemas import GroupInfo, PrivacyOverview
from app.services import build_services


def test_private_commands_help_and_menu_hide_internal_paths() -> None:
    help_text = "\n".join(HELP_SECTIONS.values())
    commands = {command.command for command in PRIVATE_BOT_COMMANDS}
    assert commands == {
        "start",
        "menu",
        "run",
        "stats",
        "pr",
        "next",
        "privacy",
        "link",
        "devices",
        "revoke_device",
        "help",
    }
    removed = {"plan", "external_processing", "share", "imports", "week", "ai_access"}
    callbacks = {
        button.callback_data
        for linked in (False, True)
        for row in _menu_keyboard(linked=linked).inline_keyboard
        for button in row
    }
    assert all(f"/{command}" not in help_text for command in removed)
    assert all(not any(command in (value or "") for command in removed) for value in callbacks)
    assert REPOSITORY_URL == "https://github.com/MattoYuzuru/Idaten"


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


def test_privacy_keyboard_uses_opaque_bounded_callbacks_and_rejects_forgery() -> None:
    group_id = uuid.uuid4()
    overview = PrivacyOverview(
        group_sharing_enabled=False,
        groups=(
            GroupInfo(
                group_id=group_id,
                telegram_chat_id=-1_001_234_567_890,
                title="Runners <private>",
                timezone="Europe/Moscow",
                role=GroupRole.MEMBER,
                share_level=ShareLevel.NONE,
                auto_share=False,
            ),
        ),
    )

    keyboard = _privacy_keyboard(overview)
    callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    rendered = format_privacy(overview)

    assert _parse_privacy_callback(f"priv:r:{group_id.hex}:SUMMARY") == (
        "group",
        group_id,
        "SUMMARY",
    )
    assert all(value is not None and len(value.encode()) <= 64 for value in callbacks)
    assert all(str(overview.groups[0].telegram_chat_id) not in (value or "") for value in callbacks)
    assert "Runners &lt;private&gt;" in rendered
    assert "Runners <private>" not in rendered
    with pytest.raises(ValueError, match="Некорректное"):
        _parse_privacy_callback(f"priv:r:{group_id.hex}:PUBLISH_NOW")


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
