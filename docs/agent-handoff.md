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

MVP 0.7 реализован в `codex/mvp-0.7-guided-sync`: bounded Health Connect pagination и
diagnostics, chronological item transactions, daily grouping, durable batch summary,
extended manual input, persistent Telegram wizard, state-aware `/start`/`/menu`, complete
`/help`, scoped commands и safe HTML presentation. Production этим изменением пока не
затрагивался.

Локально прошли Ruff, strict mypy, 94 pytest, 23 Android unit tests, Spotless,
debug assembly/lint, PostgreSQL clean/previous-head upgrade + downgrade/check, Docker
Compose health/readiness smoke и deployment checks. Release-signing assembly должен
подтвердить GitHub CI.

Release blocker: физический Android не подключен (`adb devices -l` вернул пустой список),
поэтому device checklist и live Telegram UX acceptance не выполнены. Не создавать
`v0.7.0` и не менять production digest до этой проверки.

- Draft PR: https://github.com/MattoYuzuru/Idaten/pull/11.
- CI run `28974031553` прошел: backend, signed Android release/apksigner, image и
  deployment jobs green.

Логические коммиты MVP 0.7: `8cc0c45`, `927998a`, `025672c`, `a645cf8`, `4c310fd`,
`702fbe6`, `f6fdaaa`, `7ed9d42`.

## Публикация MVP 0.6

- Основной PR: https://github.com/MattoYuzuru/Idaten/pull/6, merge `451d3a5`.
- Production hotfix: https://github.com/MattoYuzuru/Idaten/pull/7, merge `d40fad9`.
- Логические коммиты: `dfa729b` ADR/spec, `bfcebb9` Android onboarding/signing,
  `e12ea39` release/k3s, `99c5874` documentation.
- Latest release: https://github.com/MattoYuzuru/Idaten/releases/tag/v0.6.1;
  `v0.6.0` superseded из-за найденных при первом rollout startup blockers.
- Android: version `0.6.1`/code `3`; 18 unit tests, Spotless, debug/release assemblies,
  lint и `apksigner verify` прошли. APK SHA-256:
  `1186c7c6e81089f106f3e0ef389b612e2cd1fc859b2e645eef7fa5b8d808ccdc`.
- Backend: Python 3.12, Ruff, strict mypy и 81 pytest прошли; schema не менялась.
- PostgreSQL: clean upgrade, schema check, downgrade `0005 -> 0004`, повторный upgrade и
  check прошли на disposable PostgreSQL 17.
- GitHub release run `28898846941` прошел. Production image:
  `ghcr.io/mattoyuzuru/idaten-backend@sha256:ca915aacde39692b715526d107bf2e0830af5f7b61fe0e59343b47a5d128df51`.
- Production namespace `idaten` содержит один Ready pod без restart, ClusterIP Service,
  5 GiB local-path PVC, HTTP redirect и HTTPS Ingress. Certificate `Ready=True` выпущен
  `letsencrypt-prod`; `/health`, `/ready` и Alembic schema check прошли.
- PostgreSQL 16 переиспользован с отдельными database/role `idaten`; runtime Secret
  находится только в namespace `idaten`. Existing mnema resources не менялись.
- Первый rollout выявил и покрыл regression tests: numeric UID/GID 999 для non-root
  enforcement и escaping percent-encoded password на границе Alembic ConfigParser.
- DB/storage backups созданы вне сервера в `~/Backups/idaten-production`; restore list и
  archive integrity проверены.
- Signing identity и recovery copy находятся вне repository; Actions signing secrets и
  `IDATEN_BASE_URL` настроены. Runtime values проверены только по names/format, без вывода.
- Следующий обязательный документ: `docs/iterations/mvp-0.7.md`. Сначала завершить
  physical-device и Telegram checklist из `docs/deployment.md`, затем tag/release/deploy.
