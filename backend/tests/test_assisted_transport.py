import asyncio
from dataclasses import dataclass

import pytest
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import EditMessageText

from app.assisted.schemas import AssistedError
from app.bot.handlers import (
    _assisted_failure_message,
    _assisted_processing,
    _replace_processing_message,
)


class FakeBot:
    def __init__(self) -> None:
        self.actions: list[tuple[int, ChatAction]] = []

    async def send_chat_action(self, chat_id: int, action: ChatAction) -> bool:
        self.actions.append((chat_id, action))
        return True


@dataclass
class FakeChat:
    id: int = 42


class FakePlaceholder:
    def __init__(self, message_id: int, *, edit_fails: bool = False) -> None:
        self.message_id = message_id
        self.edit_fails = edit_fails
        self.edits: list[tuple[str, object | None]] = []

    async def edit_text(self, text: str, *, reply_markup: object | None = None) -> None:
        if self.edit_fails:
            raise TelegramBadRequest(
                EditMessageText(chat_id=42, message_id=self.message_id, text=text),
                "message to edit not found",
            )
        self.edits.append((text, reply_markup))


class FakeSource:
    def __init__(self, *, placeholder_edit_fails: bool = False) -> None:
        self.bot = FakeBot()
        self.chat = FakeChat()
        self.placeholder_edit_fails = placeholder_edit_fails
        self.answers: list[tuple[str, object | None, FakePlaceholder]] = []

    async def answer(self, text: str, *, reply_markup: object | None = None) -> FakePlaceholder:
        sent = FakePlaceholder(
            100 + len(self.answers),
            edit_fails=self.placeholder_edit_fails and not self.answers,
        )
        self.answers.append((text, reply_markup, sent))
        return sent


@pytest.mark.asyncio
async def test_processing_starts_typing_and_edits_the_single_placeholder() -> None:
    source = FakeSource()

    async with _assisted_processing(source) as placeholder:
        assert source.bot.actions == [(42, ChatAction.TYPING)]
        result = await _replace_processing_message(source, placeholder, "Новая пробежка")

    assert len(source.answers) == 1
    assert result is placeholder
    assert placeholder.edits == [("Новая пробежка", None)]
    assert not any(
        task.get_name() == "telegram-assisted-typing" and not task.done()
        for task in asyncio.all_tasks()
    )


@pytest.mark.asyncio
async def test_deleted_placeholder_creates_exactly_one_fallback_preview() -> None:
    source = FakeSource(placeholder_edit_fails=True)
    placeholder = await source.answer("Распознаю пробежку…")

    result = await _replace_processing_message(source, placeholder, "Новая пробежка")

    assert len(source.answers) == 2
    assert result is source.answers[-1][2]
    assert source.answers[-1][0] == "Новая пробежка"


def test_failure_placeholder_does_not_echo_provider_or_input_details() -> None:
    rendered = _assisted_failure_message(
        AssistedError(
            "secret input; provider request req-123; key sk-private",
            code="PROVIDER_TIMEOUT",
        )
    )

    assert "Сервис не ответил вовремя" in rendered
    assert "secret input" not in rendered
    assert "req-123" not in rendered
    assert "sk-private" not in rendered
