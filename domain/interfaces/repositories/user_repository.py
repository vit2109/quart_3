"""Контракт репозитория пользователей."""

from abc import ABC, abstractmethod
from typing import List, Optional

from domain.entities.user import User


class UserRepository(ABC):
    """Абстракция хранилища пользователей."""

    @abstractmethod
    async def get_by_email(self, email: str) -> Optional[User]:
        """Найти пользователя по email."""

    @abstractmethod
    async def get_by_id(self, user_id: int) -> Optional[User]:
        """Найти пользователя по ID."""

    @abstractmethod
    async def create(self, user: User) -> User:
        """Создать пользователя."""

    @abstractmethod
    async def update(self, user: User) -> User:
        """Обновить пользователя."""

    @abstractmethod
    async def list_users(self) -> List[User]:
        """Список всех пользователей."""
