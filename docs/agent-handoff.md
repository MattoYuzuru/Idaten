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

MVP 0.6 реализован в feature branch до production confirmation gate: Health Connect
provider/permission onboarding, постоянная release-подпись, GitHub Release/GHCR workflow,
k3s manifests, isolated PostgreSQL provisioning и backup/rollback/smoke документация.
Coach, ingestion и privacy/source contracts не менялись. Production namespace/DB/Secret,
tag, Release и TLS еще не создавались: это намеренная остановка перед подтверждением.

## Подготовка MVP 0.6

- Ветка: `codex/mvp-0.6-release-deployment`, основана на merge commit MVP 0.5.
- Логические коммиты: ADR/spec, Android onboarding/signing, release/k3s, documentation.
- Android: version `0.6.0`/code `2`; 18 unit tests, Spotless, debug/release assemblies,
  lint и `apksigner verify` прошли. Physical-device test остается manual blocker.
- Backend: Python 3.12, Ruff, strict mypy и 80 pytest прошли; schema не менялась.
- PostgreSQL: clean upgrade, schema check, downgrade `0005 -> 0004`, повторный upgrade и
  check прошли на disposable PostgreSQL 17.
- Docker: backend `0.6.0` собран; Compose migrations, `/health` и `/ready` прошли.
- Infrastructure read-only audit подтвердил k3s, Traefik, `letsencrypt-prod`, PostgreSQL
  16 service, `local-path` и DNS A на ingress IP. Namespace `idaten` пока отсутствует.
- Signing identity и recovery copy находятся вне repository; Actions signing secrets и
  `IDATEN_BASE_URL` настроены. Runtime values проверены только по names/format, без вывода.
- Следующий обязательный документ: `docs/iterations/mvp-0.6.md`; после зеленого draft PR
  показать gate пользователю и получить одно подтверждение перед merge/tag/deployment.
