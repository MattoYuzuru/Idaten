# Локальный запуск и deployment MVP 0.5

## Требования

- Docker + Docker Compose plugin
- Telegram bot token от BotFather
- Свободный порт 8000

## Запуск

```bash
cp .env.example .env
```

Заполните `TELEGRAM_BOT_TOKEN`. Пароли в `.env` должны отличаться от production.
Для HTTP import endpoint задайте отдельный длинный `IMPORT_API_TOKEN`; без него endpoint
возвращает 503 и остается отключенным.

Для Health Connect обязательно задайте отдельный случайный
`HEALTH_CONNECT_SECURITY_PEPPER` (минимум 32 случайных байта). Без него linking endpoint
возвращает 503. Pepper не меняют после выдачи device tokens: смена немедленно инвалидирует
все существующие tokens. Link TTL, rate limit, batch limit и outbox polling настраиваются
переменными из `.env.example`.

Coach работает без внешнего provider при `LLM_PROVIDER=NONE`. Для optional wording
поддерживаются `OPENAI`, `GEMINI`, `DEEPSEEK`, `OPENROUTER`, `OLLAMA`; задайте
`LLM_MODEL`, при необходимости `LLM_API_KEY` и override `LLM_ENDPOINT`. Timeout и
bounded retry задаются `LLM_TIMEOUT_SECONDS`/`LLM_RETRIES`. Даже при наличии ключа
внешний вызов выполняется только после `/external_processing on`; Strava history
консервативно блокирует внешний вызов. Provider получает только allowlisted aggregate
facts и canonical recommendation, без raw/route/GPS/HR series/exact start/person IDs.

```bash
docker compose up --build -d
docker compose ps
curl http://localhost:8000/health
curl http://localhost:8000/ready
docker compose logs -f backend
```

Backend перед стартом применяет `alembic upgrade head`, затем FastAPI lifespan запускает
polling. Одновременно должен работать только один polling instance.

При активном Telegram polling hourly job идемпотентно создает отчет за предыдущий месяц
и durable group outbox. Уникальность `(group, period, report type)` и `report_id` не дает
повторному job/retry создать второй report или Telegram message.

Для группового сценария пользователь сначала выполняет `/start` в личном чате. Затем
Telegram admin/owner выполняет `/setup_group` в группе, участники — `/join`, а sharing
настраивается в личном чате через `/privacy` и `/share`. По умолчанию sharing выключен.

Raw artifacts и compressed activity series сохраняются в `${STORAGE_PATH:-/data/idaten}`.
Compose монтирует named volume `activity_storage`, поэтому файлы переживают restart и
пересоздание backend container. Не публикуйте этот volume через web server и ограничьте
доступ к нему на host.

Health Connect sync принимает только ограниченный batch, сохраняет Activity как PRIVATE,
а route/HR/speed/cadence/elevation series — gzip JSON через тот же StorageService. Private
Telegram report фиксируется вместе с Activity в outbox и доставляется polling runtime с
lease и ограниченным exponential retry. `/devices` показывает UUID устройств,
`/revoke_device <uuid>` немедленно запрещает их sync/status.

## Android companion

Требуются JDK 21 и Android SDK Platform/Build Tools 36. Backend URL должен быть HTTPS;
cleartext traffic в приложении запрещен. URL задается только на этапе сборки и не содержит
секретов:

```bash
cd android
./gradlew -PIDATEN_BASE_URL=https://idaten.example/ spotlessCheck
./gradlew -PIDATEN_BASE_URL=https://idaten.example/ testDebugUnitTest
./gradlew -PIDATEN_BASE_URL=https://idaten.example/ assembleDebug
./gradlew -PIDATEN_BASE_URL=https://idaten.example/ lintDebug
```

Device token шифруется AES-GCM ключом Android Keystore; в SharedPreferences находится
только ciphertext. Route читается только при наличии route permission либо после
отдельного per-session `ExerciseRouteRequestContract`. Background sync/WorkManager нет.

## Остановка и данные

```bash
docker compose down
```

PostgreSQL и activity storage используют named volumes. Для полного удаления dev-данных:

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
