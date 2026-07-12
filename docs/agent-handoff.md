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

MVP 0.9 опубликован через PR #14 и release hotfix PR #15; актуальный `main` и tag
`v0.9.1` указывают на `b38367a`. GitHub CI run `29168820885` на `main` green. Alembic
head — `20260711_0007`.

MVP 1.0 реализован локально в ветке `codex/mvp-1.0-implementation`: active goals,
typed POST_RUN/PRE_RUN readiness, recency-weighted adaptive engine, immutable report и
recommendation revisions, отдельный Telegram `/next`, unified OpenAI task registry с
consent v2/readiness text+voice и optional Health Connect sleep prefill. Historical plan
schema сохранена, runtime wording path удалён. Alembic head — `20260712_0012`.

Логические коммиты реализации: `6e3be33` (ADR), `127fe5e` (goals/readiness), `e681f20`
(engine), `82ebf4a` (lifecycle), `f3a465e` (AI/backend sleep/cleanup), `d469ecb` (Android
sleep). Локально прошли Ruff format/check, strict mypy, 157 pytest, PostgreSQL 17 clean
upgrade/check, downgrade `0012 -> 0007`, повторный upgrade/check, provisioning tests,
29 Android unit tests, Spotless, debug assembly/lint и `docker compose config`.

Clean Docker image build на этой workstation блокируется TLS interception:
`pip install .` не скачивает `hatchling` из-за `SSLCertVerificationError: self-signed
certificate in certificate chain`. TLS verification не отключалась, поэтому Compose
up/migrate/health/ready локально не отмечены успешными и должны быть подтверждены CI.
Live OpenAI, physical-device Health Connect и Telegram UX не запускались без
owner-controlled key/device/data и остаются manual checklist.

- Branch: `codex/mvp-1.0-implementation`; remote branch и PR ещё не созданы.
- Следующий обязательный документ: `docs/deployment.md` перед публикацией и manual
  acceptance; push/draft PR требуют явного разрешения владельца.

MVP 0.8 реализован и опубликован draft PR #13: consent-gated assisted text/screenshot
input с ephemeral media, owner allowlist, typed persistent preview, shared duplicate
policy и private-only persistence. GitHub CI run `29165075909` green: backend Ruff,
strict mypy, 114 pytest, PostgreSQL/Alembic, clean Docker image build, deployment checks,
Android signed release, lint и APK verification. CI выявил timezone-dependent SQLite draft
edit: naive timestamps теперь трактуются как declared draft timezone, а не timezone runner.

- Branch: `codex/mvp-0.8-assisted-activity-import`; commits `010e845`, `ccf6f06`,
  `3b914d9`, `eca54f7`.
- PR: https://github.com/MattoYuzuru/Idaten/pull/13 (draft, green CI).
- Необходимый release blocker: live OpenAI smoke и Samsung Health screenshot eval только
  с owner-controlled key/input; raw input/key не печатать. Локальная Docker TLS
  interception остаётся ограничением workstation, но CI clean build прошёл.
- Следующий обязательный документ: `docs/deployment.md` перед tag/release/deploy после
  явного production confirmation.

MVP 0.7 реализован и опубликован через PR #11, tag `v0.7.0` и production rollout:
bounded Health Connect pagination и diagnostics, chronological item transactions, daily
grouping, durable batch summary, extended manual input, persistent Telegram wizard,
state-aware `/start`/`/menu`, complete `/help`, scoped commands и safe HTML presentation.

Локально прошли Ruff, strict mypy, 94 pytest, 23 Android unit tests, Spotless,
debug assembly/lint, PostgreSQL clean/previous-head upgrade + downgrade/check, Docker
Compose health/readiness smoke и deployment checks. Release-signing assembly должен
подтвердить GitHub CI.

Физический Android не подключался (`adb devices -l` вернул пустой список), поэтому
manual device checklist и live Telegram UX acceptance остаются обязательной ручной
проверкой после установки APK. Tag/release/deploy выполнены по явному production
confirmation владельца.

- PR: https://github.com/MattoYuzuru/Idaten/pull/11, merge
  `1775b3d51a4425ac8f6f11bc70076f2302a463ec`.
- Main CI run `28974371151` прошел: backend, Android signed release/APK verification,
  image и deployment jobs green.
- Release: https://github.com/MattoYuzuru/Idaten/releases/tag/v0.7.0; release run
  `28996693584` прошел, APK SHA-256
  `ba3ab9f87b3b4320b90954aa68bd069ed42e65d8fe0a17b36b523e1c8792483f`.
- Production image:
  `ghcr.io/mattoyuzuru/idaten-backend@sha256:7cc63d6b92509b8771b3e8b6e925735bab04d29fe27151eefe6cb5bbc04565cc`.
- Production rollout 2026-07-09 successful: one Ready pod with zero restarts,
  certificate `Ready=True`, Alembic current `20260708_0006 (head)`, Alembic check
  reports no new operations, `/health`, `/ready`, HTTP→HTTPS redirect and TLS verify
  passed.
- Pre-rollout DB/storage backups created under `~/Backups/idaten-production` and
  verified with `pg_restore --list` in the postgres pod and `tar -tzf`.

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
- Следующий обязательный документ: следующая назначенная итерация в `docs/iterations/`.
  Для MVP 0.7 остается только manual physical-device и Telegram checklist из
  `docs/deployment.md` на реальном телефоне.
