"""Общие зависимости FastAPI.

ВРЕМЕННАЯ ЗАГЛУШКА АУТЕНТИФИКАЦИИ.

JWT ещё не реализован, поэтому личность пользователя берётся из заголовков
запроса. Это небезопасно: любой может объявить себя админом, подставив
X-User-Role: admin. Когда появится JWT, тело get_current_user нужно заменить
на разбор и проверку токена — сигнатура функции и все роуты останутся прежними.
"""

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status

from app.models import UserRole


@dataclass
class CurrentUser:
    id: int
    full_name: str
    role: UserRole


async def get_current_user(
    x_user_id: int = Header(default=1),
    x_user_name: str = Header(default="Dev User"),
    x_user_role: UserRole = Header(default=UserRole.USER),
) -> CurrentUser:
    # TODO(auth): заменить на разбор JWT-токена из заголовка Authorization
    return CurrentUser(id=x_user_id, full_name=x_user_name, role=x_user_role)


async def require_admin(
    current_user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    if current_user.role is not UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return current_user
