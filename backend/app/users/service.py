from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.users.models import TelegramAccount, User
from app.users.repository import UserRepository
from app.users.schemas import TelegramIdentity


class UserService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        default_timezone: str,
        default_locale: str,
    ) -> None:
        self.session_factory = session_factory
        self.default_timezone = default_timezone
        self.default_locale = default_locale

    async def register(self, identity: TelegramIdentity) -> User:
        async with self.session_factory.begin() as session:
            repository = UserRepository(session)
            existing = await repository.get_by_telegram_id(identity.telegram_user_id)
            if existing:
                user, account = existing
                user.display_name = identity.display_name
                account.username = identity.username
                account.first_name = identity.first_name
                account.last_name = identity.last_name
                account.private_chat_id = identity.private_chat_id
                return user

            user = User(
                display_name=identity.display_name,
                timezone=self.default_timezone,
                locale=self.default_locale,
            )
            repository.add_user(user)
            await session.flush()
            account = TelegramAccount(
                user_id=user.id,
                telegram_user_id=identity.telegram_user_id,
                username=identity.username,
                first_name=identity.first_name,
                last_name=identity.last_name,
                private_chat_id=identity.private_chat_id,
            )
            repository.add_account(account)
            await session.flush()
            return user
