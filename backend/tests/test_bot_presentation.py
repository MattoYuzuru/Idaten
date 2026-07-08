import uuid
from datetime import UTC, datetime

from app.activities.schemas import ManualDraft, ManualRunInput
from app.bot.handlers import _draft_keyboard
from app.bot.messages import HELP_SECTIONS, format_manual_draft


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
