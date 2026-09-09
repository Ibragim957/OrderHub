"""Выпуск и проверка JWT-токенов.

JWT (JSON Web Token) — строка из трёх частей через точку:
    заголовок.полезная_нагрузка.подпись

Первые две части — это просто base64, их может прочитать кто угодно. Секретных
данных в токен класть нельзя. Защищает третья часть — подпись: она вычисляется
из первых двух и секретного ключа. Подделать полезную нагрузку, не зная ключа,
невозможно — подпись перестанет сходиться.

Именно поэтому оба сервиса могут проверять токен самостоятельно, зная общий
секрет, и им не нужно ходить друг к другу с вопросом "а кто это?". Для
микросервисов это ключевое свойство: проверка токена не создаёт сетевых
зависимостей между сервисами.
"""

import os
from datetime import UTC, datetime, timedelta

import jwt

JWT_SECRET = os.getenv("JWT_SECRET", "change-me-in-production")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))


def create_access_token(user_id: int, full_name: str, role: str) -> str:
    """Собирает токен для пользователя.

    В нагрузку кладём ровно то, что нужно для авторизации на любом сервисе:
    кто это (sub), как зовут и какая роль. Тогда service-2 сможет проверить
    права, не обращаясь в базу service-1.
    """
    now = datetime.now(UTC)
    payload = {
        # sub (subject) — стандартное поле JWT для идентификатора владельца.
        # По спецификации это строка, поэтому int приводим к str.
        "sub": str(user_id),
        "name": full_name,
        "role": role,
        "iat": now,  # issued at — когда выпущен
        # exp — когда протухнет. Библиотека проверяет это поле сама и бросает
        # ExpiredSignatureError. Без срока жизни украденный токен работал бы вечно.
        "exp": now + timedelta(minutes=JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    """Проверяет подпись и срок годности. Возвращает None, если токен негоден.

    Список algorithms обязателен: без него библиотека согласилась бы принять
    алгоритм, указанный в самом токене, и злоумышленник подставил бы "none",
    то есть токен вообще без подписи. Это классическая уязвимость JWT.
    """
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        # Истёк срок, испорчена подпись, сломан формат — для вызывающего
        # все случаи одинаковы: токену нельзя доверять.
        return None
