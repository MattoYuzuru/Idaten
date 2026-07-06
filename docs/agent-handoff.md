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

MVP 0.4 добавляет Android Health Connect companion, one-time Telegram linking, HMAC-only
link/device credentials, revocable scoped devices, bounded partial batch sync, общий
NormalizedActivity validation, PRIVATE activities, StorageService series и durable
private Telegram outbox. Group source policy по-прежнему допускает только MANUAL.
Следующая итерация после merge MVP 0.4 начинает чтение с
`docs/iterations/mvp-0.5.md` и не должна расширять этот PR ее scope.

## Публикация MVP 0.4

- Ветка: `codex/mvp-0.4-health-connect`.
- Draft PR: https://github.com/MattoYuzuru/Idaten/pull/4
- Логические коммиты: `79726f2` backend/security/migration, `fc2c27a` Android/CI,
  `e8aaf56` docs, `ad43cf6` Gradle wrapper line endings.
- Backend: Ruff format/lint, strict mypy, 54 pytest, clean PostgreSQL migration,
  downgrade/upgrade и Alembic check прошли.
- Android: Spotless, unit tests, assembleDebug и lintDebug прошли на SDK 36;
  instrumentation не запускался без emulator/device с Health Connect provider.
- Docker: image build, clean Compose health/ready, Alembic и StorageService persistence
  после backend restart прошли.
- GitHub CI: состояние проверяется в PR #4; при передаче работы смотреть последний run.
