# Локальный запуск и deployment MVP 0.2

## Требования

- Docker + Docker Compose plugin
- Telegram bot token от BotFather
- Свободный порт 8000

## Запуск

```bash
cp .env.example .env
```

Заполните `TELEGRAM_BOT_TOKEN`. Пароли в `.env` должны отличаться от production.

```bash
docker compose up --build -d
docker compose ps
curl http://localhost:8000/health
curl http://localhost:8000/ready
docker compose logs -f backend
```

Backend перед стартом применяет `alembic upgrade head`, затем FastAPI lifespan запускает
polling. Одновременно должен работать только один polling instance.

Для группового сценария пользователь сначала выполняет `/start` в личном чате. Затем
Telegram admin/owner выполняет `/setup_group` в группе, участники — `/join`, а sharing
настраивается в личном чате через `/privacy` и `/share`. По умолчанию sharing выключен.

## Остановка и данные

```bash
docker compose down
```

PostgreSQL использует named volume. Для полного удаления dev-данных:

```bash
docker compose down -v
```

## Запуск проверок без контейнера backend

```bash
cd backend
python3.12 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
ruff check .
mypy app
pytest
alembic check
```
