"""Общие зависимости FastAPI: кто сделал запрос и что ему позволено."""

from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth import decode_access_token
from app.models import UserRole

# auto_error=False: при отсутствии заголовка вернём None вместо готовой 403.
# Так сообщение об ошибке формируем мы сами, единообразно с остальными.
bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class CurrentUser:
    id: int
    full_name: str
    role: UserRole


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> CurrentUser:
    """Достаёт пользователя из JWT в заголовке Authorization: Bearer <token>.

    В базу не ходим: всё нужное уже лежит в подписанном токене. Для
    микросервисов это принципиально — service-2 проверяет тот же токен тем же
    секретом и не обращается к service-1 на каждый запрос.
    """
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        # Заголовок предписан стандартом HTTP для 401: он говорит клиенту,
        # какой способ аутентификации ожидается.
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None:
        raise unauthorized

    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise unauthorized

    try:
        return CurrentUser(
            id=int(payload["sub"]),
            full_name=payload.get("name", ""),
            role=UserRole(payload["role"]),
        )
    except (KeyError, ValueError) as exc:
        # Подпись верна, но содержимое не то, что мы ожидаем: чужой формат
        # токена или неизвестная роль.
        raise unauthorized from exc


async def require_admin(
    current_user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """Пропускает только администраторов.

    Разделение на два уровня осознанное: 401 означает "мы не знаем, кто вы",
    403 — "знаем, но вам сюда нельзя". Клиенту это разные ситуации: в первой
    надо войти заново, во второй вход не поможет.
    """
    if current_user.role is not UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return current_user
