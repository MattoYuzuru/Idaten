from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TelegramIdentity:
    telegram_user_id: int
    private_chat_id: int
    first_name: str
    last_name: str | None = None
    username: str | None = None

    @property
    def display_name(self) -> str:
        full_name = " ".join(part for part in (self.first_name, self.last_name) if part)
        return full_name.strip() or self.username or str(self.telegram_user_id)
