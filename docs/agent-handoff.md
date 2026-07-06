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

MVP 0.3 реализует StorageService/local filesystem, raw artifacts/import history,
NormalizedActivity adapters для Manual/GPX/TCX/FIT/CSV, preview/confirm pipeline,
deterministic dedup, splits, compressed series и Telegram/HTTP transport. Импорт создает
только PRIVATE Activity после explicit confirm; group source policy остается backend
инвариантом. Следующая итерация после merge MVP 0.3 начинает чтение с
`docs/iterations/mvp-0.4.md` и не должна расширять этот PR ее scope.
