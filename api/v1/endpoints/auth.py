from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, Field
from typing import Optional

from application.use_cases.auth.auth_service import AuthService
from core.exceptions import AppException
from infrastructure.persistence.file_user_repository import FileUserRepository

router = APIRouter(prefix="/auth", tags=["authentication"])


def _auth_service() -> AuthService:
    return AuthService(FileUserRepository())


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserRegister(BaseModel):
    email: EmailStr
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=6)
    full_name: Optional[str] = None


class RefreshRequest(BaseModel):
    refresh_token: str


def _token_response(user, access_token: str, refresh_token: str) -> dict:
    return {
        "status": "success",
        "data": {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "user": AuthService.user_public(user),
        },
    }


@router.post("/login")
async def login(user_data: UserLogin):
    """Вход пользователя — возвращает JWT access и refresh токены."""
    try:
        user, access_token, refresh_token = await _auth_service().authenticate(
            user_data.email, user_data.password
        )
        return _token_response(user, access_token, refresh_token)
    except AppException:
        raise


@router.post("/register")
async def register(user_data: UserRegister):
    """Регистрация нового пользователя (первый — admin, остальные — viewer)."""
    try:
        user = await _auth_service().register(
            user_data.email,
            user_data.username,
            user_data.password,
            user_data.full_name,
        )
        return {
            "status": "success",
            "message": "User registered",
            "data": AuthService.user_public(user),
        }
    except AppException:
        raise


@router.post("/refresh")
async def refresh_token(body: RefreshRequest):
    """Обновление access-токена по refresh-токену."""
    try:
        access_token = await _auth_service().refresh_token(body.refresh_token)
        return {
            "status": "success",
            "data": {
                "access_token": access_token,
                "token_type": "bearer",
            },
        }
    except AppException:
        raise
