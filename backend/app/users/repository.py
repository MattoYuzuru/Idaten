import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.users.models import TelegramAccount, User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_telegram_id(
        self, telegram_user_id: int
    ) -> tuple[User, TelegramAccount] | None:
        statement = (
            select(User, TelegramAccount)
            .join(TelegramAccount, TelegramAccount.user_id == User.id)
            .where(TelegramAccount.telegram_user_id == telegram_user_id)
        )
        row = (await self.session.execute(statement)).one_or_none()
        return (row[0], row[1]) if row else None

    async def get_by_id_for_update(self, user_id: uuid.UUID) -> User | None:
        result = await self.session.execute(
            select(User).where(User.id == user_id).with_for_update()
        )
        return result.scalar_one_or_none()

    def add_user(self, user: User) -> None:
        self.session.add(user)

    def add_account(self, account: TelegramAccount) -> None:
        self.session.add(account)
