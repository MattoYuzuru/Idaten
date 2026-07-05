# MVP 0.1 — Telegram + manual tracking + PostgreSQL

## Результат

Работающий self-hosted сервис: пользователь регистрируется через Telegram, вводит
пробежку командой `/run`, получает deterministic отчет и запрашивает личную статистику.

## Функциональный scope

### Telegram

- `/start`: idempotent регистрация/обновление Telegram account.
- `/run <км> <время>`: принимает десятичную точку или запятую; время `MM:SS` либо
  `H:MM:SS`; создает private RUN с источником MANUAL и текущим временем.
- `/stats`: все время — километры, число пробежек, самая длинная пробежка.
- `/week`: текущая локальная неделя — километры, количество, longest run.
- `/pr`: лучший зарегистрированный 5K/10K по правилу ADR-005.
- `/help`: синтаксис и список команд.
- Ошибка пользовательского ввода возвращает понятную подсказку и не создает запись.

### Backend

- `GET /health` возвращает liveness без обращения к зависимостям.
- `GET /ready` проверяет `SELECT 1` в БД.
- Polling запускается только при непустом `TELEGRAM_BOT_TOKEN`.
- Graceful shutdown останавливает polling и освобождает engine.
- Application services управляют регистрацией, созданием активности и отчетом.

### Persistence

Таблицы: `users`, `telegram_accounts`, `activity_sources`, `activities`, `coach_reports`.
Обязательны уникальность Telegram user ID и partial uniqueness external activity key.
Все schema changes представлены Alembic migration.

### Analytics и report

- Пейс: `elapsed_time_sec / (distance_m / 1000)` с округлением до целой секунды.
- Week start: понедельник 00:00 в timezone пользователя.
- After-run template содержит distance, duration, pace, номер пробежки за неделю и
  консервативную рекомендацию следующей легкой тренировки.
- LLM не используется.

## Нефункциональные требования

- Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, aiogram 3.
- Async I/O для Telegram и PostgreSQL.
- Конфигурация валидируется через `pydantic-settings`.
- Structured console logging без токенов/payload.
- Docker image запускается non-root user.
- Compose содержит backend и PostgreSQL с healthcheck и persistent volume.
- Unit/integration tests не требуют реального Telegram API.

## Acceptance criteria

1. `/run 10.02 1:02:41` создает одну активность и отвечает `10.02 км`, `1:02:41`,
   `6:15/км`.
2. Повторный `/start` не создает второго пользователя/account.
3. `/week` считает только записи текущей локальной недели.
4. `/stats` корректно агрегирует несколько записей.
5. `/pr` показывает 5K/10K только при наличии подходящих активностей.
6. Миграция поднимает пустую PostgreSQL schema до head.
7. `docker compose up --build` дает healthy PostgreSQL и ready backend.
8. Core tests, lint и type checks проходят.

## Не входит

REST CRUD, auth tokens, группы/privacy UI, files/raw artifacts, Android, Strava, webhooks,
LLM, планы, scheduler и публикации.

## Завершение итерации

- [x] Реализация и миграция
- [x] Автотесты
- [x] Container smoke test
- [x] Документация запуска
- [x] Draft PR

## Known limitations

- Started time для ручной команды — время получения update; пользователь пока не может
  исправить его через команду.
- PR основан на полной длительности активности близкой дистанции, а не на splits.
- Один процесс подходит для MVP; несколько replicas polling одновременно запрещены.
