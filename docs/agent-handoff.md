# Инструкция для агента

## Что читать

Перед работой агент читает только:

1. `docs/architecture-rules.md` — обязательные инварианты.
2. `docs/decision-log.md` — уже принятые решения.
3. `docs/iterations/mvp-X.Y.md` — только назначенную итерацию.
4. `README.md` и затронутый код/тесты.

Roadmap нужен для ориентации, но не дает разрешения реализовывать будущие итерации.
Исходное большое ТЗ перечитывать не требуется, если спецификация итерации достаточна.

## Порядок работы

1. Проверить текущую ветку, dirty files и открытые TODO текущей итерации.
2. Сопоставить acceptance criteria с существующим кодом и тестами.
3. Записать новое архитектурное решение в decision log до реализации, если оно меняет
   публичный контракт, schema, privacy или deployment.
4. Реализовать только назначенный scope.
5. Запустить format/lint/type/tests и container smoke test, если доступен Docker.
6. Обновить спецификацию: отметить выполненное и оставить конкретные known limitations.
7. Сделать логические коммиты, push и draft PR с результатами проверок.

## Definition of Done

- Все acceptance criteria итерации либо проверены, либо явно отмечены как blocker.
- Бизнес-логика отсутствует в Telegram/API handlers.
- Миграции соответствуют моделям.
- Нет секретов и персональных данных в git/logs.
- Документация запуска воспроизводима.
- Working tree после публикации чистый.

## Формат передачи

В финальном сообщении указать: ветку, коммиты, PR, реализованный scope, команды проверок,
known limitations и точный следующий документ для чтения.

## Текущее состояние

MVP 0.5 добавляет versioned deterministic coach facts/rules, weekly/monthly/rolling
analytics, classification/risk flags, canonical `/next`, expanded `/week`, safe draft
plans, eligible group monthly awards/goals и idempotent monthly outbox. External wording
остается optional, требует explicit user opt-in и получает только aggregate allowlist;
Strava history блокирует внешний вызов. Privacy/ingestion/Health Connect foundation не
переписывался. Спецификации следующей итерации пока нет: после merge сначала читать
`docs/architecture-rules.md`, затем работать только по явно добавленной iteration spec.

## Публикация MVP 0.5

- Ветка: `codex/mvp-0.5-coach-engine`.
- Draft PR: https://github.com/MattoYuzuru/Idaten/pull/5
- Логические коммиты: `cd42965` backend/migration/tests, `dee70b5` release config/docs.
- Versions: `coach-facts-v1`, `coach-rules-v1`; migration `20260707_0005`.
- Backend: Ruff format/lint, strict mypy и 80 pytest прошли; fake providers проверяют
  no-key/timeout/error/retry/fallback, opt-in, Strava exclusion и sensitive allowlist.
- PostgreSQL: clean upgrade, downgrade `0005 -> 0004`, повторный upgrade и Alembic schema
  check прошли. Monthly report/outbox retry/idempotency и transaction rollback покрыты.
- Docker: image `0.5.0` собран, Compose backend/PostgreSQL healthy, `/health` и `/ready`
  возвращают success.
- GitHub CI run `28891013266`: `backend`, `image`, `android` прошли. Финальный doc-only
  handoff commit проверяется последним run в PR #5.
- Реальные external provider network calls не запускались без credentials; остальные
  known limitations перечислены в `docs/iterations/mvp-0.5.md`.
