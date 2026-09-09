"""Хеширование паролей.

Используем библиотеку bcrypt напрямую, без passlib: passlib 1.7.4 не
обновлялся с 2020 года и ломается на bcrypt 5.x (ValueError при хешировании).
Лишняя обёртка тут ничего не даёт — API самого bcrypt состоит из двух функций.
"""

import bcrypt

# bcrypt по своей конструкции обрабатывает не более 72 байт пароля и на
# длинных значениях бросает ValueError. Обрезаем сами, чтобы регистрация
# не падала на пользователе с очень длинным паролем.
_MAX_PASSWORD_BYTES = 72


def _encode(password: str) -> bytes:
    return password.encode("utf-8")[:_MAX_PASSWORD_BYTES]


def hash_password(password: str) -> str:
    """Возвращает хеш пароля. Соль генерируется случайно и хранится внутри хеша."""
    return bcrypt.hashpw(_encode(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Сверяет пароль с хешем.

    checkpw сравнивает за постоянное время — это защита от атак по времени
    ответа, когда злоумышленник подбирает пароль, замеряя длительность проверки.
    """
    try:
        return bcrypt.checkpw(_encode(password), hashed.encode("utf-8"))
    except ValueError:
        # Хеш в базе повреждён или имеет неизвестный формат — это не повод
        # ронять запрос, достаточно считать пароль неверным.
        return False
