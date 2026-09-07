# OrderHub

Сервис доставки еды на микросервисной архитектуре. Дипломный проект.

## Архитектура

Два независимых сервиса, у каждого **своя база данных** (Database per Service).
Прямых обращений к чужой БД нет: сервисы общаются по HTTP и через события RabbitMQ.

```
                      ┌──────────────┐
   клиент  ──────────▶│    nginx     │  reverse proxy, балансировка, rate limit
                      └──────┬───────┘
                    ┌────────┴────────┐
                    ▼                 ▼
            ┌──────────────┐   ┌─────────────────────┐
            │  service-1   │   │ service-2 (×2)      │
            │ Order Service│   │ Catalog & Delivery  │
            └──────┬───────┘   └──────────┬──────────┘
                   │                      │
            ┌──────▼──────┐        ┌──────▼──────┐
            │ postgres-1  │        │ postgres-2  │
            └─────────────┘        └─────────────┘
                   │                      │
                   └────┬─────────────┬───┘
                        ▼             ▼
                 ┌────────────┐ ┌──────────┐
                 │  RabbitMQ  │ │  Redis   │
                 └────────────┘ └──────────┘
```

| Сервис | Домен | Модели |
|---|---|---|
| **service-1** | заказы и пользователи | `User`, `Order`, `OrderItem` |
| **service-2** | каталог и доставка | `Restaurant`, `MenuItem`, `Courier` |

### Почему между сервисами нет ForeignKey

`Order.restaurant_id` и `Order.courier_id` — обычные целые числа без внешнего
ключа. Причина в том, что записи, на которые они ссылаются, лежат в **другой
базе данных**: constraint не может пересечь границу СУБД. Целостность
обеспечивается на уровне приложения и через события RabbitMQ.

По той же причине там, где нужны данные чужого сервиса, используются
**снимки** (`customer_name_snapshot`, `price_at_order`): заказ должен показывать
цену и имя на момент покупки, даже если каталог позже изменит цену, а
пользователь — имя.

## Запуск

```bash
cp .env.example .env      # при необходимости поменяйте значения
docker compose up --build
```

| Что | Адрес |
|---|---|
| API через nginx | http://localhost:8080/api/catalog/ , http://localhost:8080/api/orders/ |
| Swagger каталога | http://localhost:8080/api/catalog/docs |
| RabbitMQ management | http://localhost:15672 |
| Метрики Prometheus | `/metrics` у каждого сервиса |

Проверка балансировки — в ответе `/health` возвращается имя инстанса:

```bash
for i in 1 2 3 4; do curl -s localhost:8080/api/catalog/health; echo; done
# instance чередуется между service-2-a и service-2-b
```

## Локальная разработка без Docker

```bash
python -m venv .venv && .venv/Scripts/activate
pip install -r service-2/requirements.txt
cd service-2 && alembic upgrade head
uvicorn app.main:app --reload --port 8002
```

## Миграции

У каждого сервиса своя история миграций — следствие Database per Service.

```bash
cd service-1        # или service-2
alembic revision --autogenerate -m "описание"
alembic upgrade head
alembic downgrade -1
```

Автогенерация не создаёт и не удаляет типы PostgreSQL `ENUM` — их приходится
добавлять в миграцию вручную, иначе после `downgrade` остаются осиротевшие
типы и повторный `upgrade` падает с `DuplicateObject`.

## Тесты и линтер

```bash
ruff check service-1 service-2
cd service-2 && pytest -v
```

CI запускает то же самое при каждом push (`.github/workflows/ci.yml`):
линтер, тесты на матрице из двух сервисов, затем сборка Docker-образов.

## Стек

FastAPI · SQLAlchemy 2 (async) · PostgreSQL · Alembic · Pydantic v2 · JWT ·
RabbitMQ · Redis · Nginx · Docker Compose · Prometheus · GitHub Actions
