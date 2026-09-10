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

### События RabbitMQ

| Событие | Публикует | Слушает | Зачем |
|---|---|---|---|
| `order.created` | service-1 | service-2 | подобрать свободного курьера |
| `courier.assigned` | service-2 | service-1 | записать курьера в заказ |
| `order.status_changed` | service-1 | service-2 | журналировать смену статуса |

Курьер назначается событием, а не HTTP-запросом: клиенту не нужно ждать подбора
курьера, чтобы оформить заказ, а если каталог недоступен, событие дождётся его
в очереди.

### Кэш Redis

Кэшируется публичный список ресторанов (`GET /restaurants`): его читают чаще всего,
а меняется он редко. Любое изменение ресторанов сбрасывает кэш. Redis — ускоритель,
а не источник данных: если он недоступен, запросы идут напрямую в PostgreSQL.

## Запуск

```bash
cp .env.example .env      # при необходимости поменяйте значения
docker compose up --build
```

| Что | Адрес |
|---|---|
| API через nginx | http://localhost:8080/api/catalog/ , http://localhost:8080/api/orders/ |
| Swagger каталога | http://localhost:8080/api/catalog/docs |
| Swagger заказов | http://localhost:8080/api/orders/docs |
| RabbitMQ management | http://localhost:15672 |
| Метрики каталога | http://localhost:8080/api/catalog/metrics |
| Метрики заказов | http://localhost:8080/api/orders/metrics |

Проверка балансировки — в ответе `/health` возвращается имя инстанса:

```bash
for i in 1 2 3 4; do curl -s localhost:8080/api/catalog/health; echo; done
# instance чередуется между service-2-a и service-2-b
```

## Вход и роли

Регистрация — `POST /api/orders/users`, токен — `POST /api/orders/auth/login`.
Токен передаётся в заголовке `Authorization: Bearer <token>`, в Swagger — через кнопку
**Authorize**. Оба сервиса принимают один и тот же токен.

Роль администратора через API не выдаётся — иначе любой назначил бы её себе сам.
Её назначают напрямую в базе:

```bash
docker compose exec postgres-1 psql -U postgres -d service_1_db -c "UPDATE users SET role='ADMIN' WHERE email='you@example.com'"
```

После этого токен нужно получить заново: роль записывается в него при выдаче.

## Локальная разработка без Docker

Нужен локальный PostgreSQL с созданной базой `service_2_db`. RabbitMQ и Redis
необязательны: без них сервис работает, просто без событий и кэша.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r service-2/requirements.txt
cd service-2 && alembic upgrade head
uvicorn app.main:app --reload --port 8002
```

## Миграции

У каждого сервиса своя история миграций — следствие Database per Service.
В Docker их выполняют одноразовые контейнеры `migrate-1` и `migrate-2` до старта
сервисов: если бы миграции запускала каждая реплика, две реплики каталога делали бы
это одновременно и мешали друг другу.

```bash
cd service-1        # или service-2
alembic revision --autogenerate -m "описание"
alembic upgrade head
alembic downgrade -1
```

Автогенерация создаёт типы PostgreSQL `ENUM` в `upgrade`, но не удаляет их в
`downgrade` — удаление приходится дописывать вручную, иначе после отката остаются
осиротевшие типы и повторный `upgrade` падает с `DuplicateObject`.

## Тесты и линтер

```bash
ruff check service-1 service-2
cd service-1 && pytest -v
cd ../service-2 && pytest -v
```

CI запускает то же самое при каждом push (`.github/workflows/ci.yml`):
линтер, тесты на матрице из двух сервисов, затем сборка Docker-образов.

## Стек

FastAPI · SQLAlchemy 2 (async) · PostgreSQL · Alembic · Pydantic v2 · JWT ·
RabbitMQ · Redis · Nginx · Docker Compose · Prometheus · GitHub Actions
