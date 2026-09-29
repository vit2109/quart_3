from typing import Optional, Tuple
from datetime import datetime, timezone
from domain.entities.user import User, UserRole
from domain.interfaces.repositories.user_repository import UserRepository
from core.security import SecurityService
from core.exceptions import AuthenticationError, ValidationError

class AuthService:
    def __init__(self, user_repository: UserRepository):
        self.user_repository = user_repository
    
    async def authenticate(self, email: str, password: str) -> Tuple[User, str, str]:
        user = await self.user_repository.get_by_email(email)
        if not user:
            raise AuthenticationError("Invalid credentials")
        
        if not SecurityService.verify_password(password, user.hashed_password):
            raise AuthenticationError("Invalid credentials")
        
        if not user.is_active:
            raise AuthenticationError("User is inactive")
        
        user.last_login = datetime.now(timezone.utc)
        await self.user_repository.update(user)
        
        token_data = {"sub": user.email, "role": user.role.value}
        access_token = SecurityService.create_access_token(token_data)
        refresh_token = SecurityService.create_refresh_token(token_data)
        
        return user, access_token, refresh_token

    async def register(
        self,
        email: str,
        username: str,
        password: str,
        full_name: Optional[str] = None,
    ) -> User:
        if len(password) < 6:
            raise ValidationError("Password must be at least 6 characters")
        existing = await self.user_repository.get_by_email(email)
        if existing:
            raise ValidationError("Email already registered")

        users = await self.user_repository.list_users()
        role = UserRole.ADMIN if not users else UserRole.VIEWER

        user = User(
            email=email,
            username=username,
            hashed_password=SecurityService.get_password_hash(password),
            full_name=full_name,
            role=role,
        )
        return await self.user_repository.create(user)
    
    async def refresh_token(self, refresh_token: str) -> str:
        payload = SecurityService.decode_token(refresh_token)
        if not payload or payload.get("type") != "refresh":
            raise AuthenticationError("Invalid refresh token")
        
        email = payload.get("sub")
        if not email:
            raise AuthenticationError("Invalid token payload")
        
        user = await self.user_repository.get_by_email(email)
        if not user or not user.is_active:
            raise AuthenticationError("User not found or inactive")
        
        token_data = {"sub": user.email, "role": user.role.value}
        return SecurityService.create_access_token(token_data)

    @staticmethod
    def user_public(user: User) -> dict:
        return {
            "id": user.id,
            "email": user.email,
            "username": user.username,
            "full_name": user.full_name,
            "role": user.role.value,
        }
