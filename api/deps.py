"""Общие зависимости FastAPI для эндпоинтов."""

from typing import Annotated

from fastapi import Depends

from core.security import require_role
from domain.entities.user import User, UserRole

ViewerDep = Annotated[User, Depends(require_role(UserRole.VIEWER))]
AnalystDep = Annotated[User, Depends(require_role(UserRole.ANALYST))]
AdminDep = Annotated[User, Depends(require_role(UserRole.ADMIN))]
