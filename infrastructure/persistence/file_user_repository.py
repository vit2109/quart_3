"""Async-обёртка над файловым user_store."""

from __future__ import annotations

import asyncio
from typing import List, Optional

from domain.entities.user import User
from domain.interfaces.repositories.user_repository import UserRepository
from infrastructure.storage import user_store


class FileUserRepository(UserRepository):
    """Репозиторий пользователей на JSON-манифесте."""

    async def get_by_email(self, email: str) -> Optional[User]:
        return await asyncio.to_thread(user_store.get_by_email, email)

    async def get_by_id(self, user_id: int) -> Optional[User]:
        return await asyncio.to_thread(user_store.get_by_id, user_id)

    async def create(self, user: User) -> User:
        return await asyncio.to_thread(user_store.create_user, user)

    async def update(self, user: User) -> User:
        return await asyncio.to_thread(user_store.update_user, user)

    async def list_users(self) -> List[User]:
        return await asyncio.to_thread(user_store.list_users)
