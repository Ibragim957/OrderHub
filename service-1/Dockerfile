FROM python:3.13-slim

# Питон не буферизует вывод — иначе логи теряются при падении контейнера,
# и не пишет .pyc — в контейнере они бесполезны.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /code

# Зависимости ставим отдельным слоем, до копирования кода: пока requirements.txt
# не менялся, Docker переиспользует кэш и не переустанавливает пакеты при
# каждой правке исходников.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini .
COPY alembic ./alembic
COPY app ./app

# Контейнер работает не от root — если приложение скомпрометируют,
# у злоумышленника не будет прав администратора внутри контейнера.
RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /code
USER appuser

EXPOSE 8000

# Миграции накатываются при старте, затем поднимается сервер.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
