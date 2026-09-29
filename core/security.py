from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Callable
import bcrypt
from jose import JWTError, jwt
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer

from .config import settings
from .exceptions import AuthenticationError, AuthorizationError
from domain.entities.user import User, UserRole

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login",
    auto_error=False,
)

ROLE_HIERARCHY = {
    UserRole.VIEWER: 0,
    UserRole.ANALYST: 1,
    UserRole.ADMIN: 2,
}


class SecurityService:
    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        if not hashed_password:
            return False
        try:
            return bcrypt.checkpw(
                plain_password.encode("utf-8"),
                hashed_password.encode("utf-8"),
            )
        except ValueError:
            return False

    @staticmethod
    def get_password_hash(password: str) -> str:
        return bcrypt.hashpw(
            password.encode("utf-8"),
            bcrypt.gensalt(),
        ).decode("utf-8")

    @staticmethod
    def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.now(timezone.utc) + expires_delta
        else:
            expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
        to_encode.update({"exp": expire})
        encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
        return encoded_jwt

    @staticmethod
    def create_refresh_token(data: Dict[str, Any]) -> str:
        expire = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
        to_encode = data.copy()
        to_encode.update({"exp": expire, "type": "refresh"})
        return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    @staticmethod
    def decode_token(token: str) -> Dict[str, Any]:
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
            return payload
        except JWTError:
            return {}


async def get_current_user(token: Optional[str] = Depends(oauth2_scheme)) -> User:
    # В DEBUG без токена / с demo-токеном даём доступ аналитика,
    # чтобы UI работал до полноценной авторизации.
    if not token or token == "demo-token":
        if settings.DEBUG:
            return User(
                email="dev@example.com",
                username="dev",
                hashed_password="",
                role=UserRole.ANALYST,
            )
        raise AuthenticationError("Not authenticated")

    payload = SecurityService.decode_token(token)
    if not payload or payload.get("type") == "refresh":
        if settings.DEBUG:
            return User(
                email="dev@example.com",
                username="dev",
                hashed_password="",
                role=UserRole.ANALYST,
            )
        raise AuthenticationError("Invalid or expired access token")

    email = payload.get("sub")
    if not email:
        raise AuthenticationError("Invalid token payload")

    role_value = payload.get("role", UserRole.VIEWER.value)
    try:
        role = UserRole(role_value)
    except ValueError:
        role = UserRole.VIEWER

    return User(
        email=email,
        username=email,
        hashed_password="",
        role=role,
    )


def require_role(required_role: UserRole) -> Callable:
    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        user_level = ROLE_HIERARCHY.get(current_user.role, -1)
        required_level = ROLE_HIERARCHY.get(required_role, 0)
        if user_level < required_level:
            raise AuthorizationError(
                f"Role '{required_role.value}' or higher is required"
            )
        return current_user

    return role_checker
