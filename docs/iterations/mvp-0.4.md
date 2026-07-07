# MVP 0.4 — Android Health Connect companion

## Цель

Android-приложение вручную синхронизирует беговые тренировки из Health Connect в общий
ingestion backend и инициирует private Telegram report.

## Android scope

- Kotlin + минимальный Jetpack Compose UI.
- Экраны link/status/latest runs; link code из Telegram.
- Runtime permissions Health Connect для ExerciseSession, Distance, HeartRate, Speed,
  Cadence, Elevation и Route только при доступности/разрешении.
- Manual Sync; WorkManager/background-first отложен.
- Device token хранится в Android Keystore-backed storage.

## Backend scope

- Link code: короткоживущий, one-time, rate-limited, хранится только безопасное
  представление.
- Device model, revocable scoped token, last sync cursor/status.
- Endpoints link/start, link/complete, sync/activities, sync/status.
- `HealthConnectAdapter` производит тот же `NormalizedActivity`, что file adapters.
- Batch имеет лимит; item-level result сообщает saved/duplicate/error.
- Route/series идут в storage и никогда автоматически не публикуются.

## Acceptance criteria

1. Код связывает устройство только с инициировавшим пользователем и истекает.
2. Неверный/повторный код отклоняется.
3. После permission grant приложение показывает найденные runs.
4. Manual Sync создает новые activities и пропускает external ID duplicates.
5. Backend отправляет private report через outbox-safe mechanism.
6. Отзыв device token запрещает дальнейшую синхронизацию.
7. Отсутствующие optional records не блокируют импорт.

## Не входит

Постоянная фоновая синхронизация, iOS app, карты в группе, Google Play publication.

## Checklist

- [x] Kotlin/Compose Android module с link/status/latest runs и Manual Sync.
- [x] ExerciseSession, Distance, HeartRate, Speed, StepsCadence и Elevation permissions;
  route отделен от base permission flow и запрашивается per-session при необходимости.
- [x] Device token хранится как AES-GCM ciphertext с ключом Android Keystore.
- [x] Link code short-lived, one-time, HMAC-only в БД и привязан к Telegram user.
- [x] Backend rate limit хранит попытки по HMAC installation key.
- [x] Scoped device token возвращается один раз, хранится как HMAC и отзывается через
  `/revoke_device`; revoked token запрещает sync/status.
- [x] Alembic migration добавляет devices, link codes/attempts, sync status и outbox.
- [x] `HealthConnectAdapter` производит общий `NormalizedActivity` и проходит общий
  validation contract.
- [x] Batch ограничен конфигурацией; items сохраняются независимыми транзакциями и
  возвращают saved/duplicate/error без payload/traceback.
- [x] External ID idempotency опирается на существующий unique source constraint.
- [x] Activity всегда PRIVATE; route/HR/speed/cadence/elevation series сохраняются через
  StorageService и не попадают в group messages.
- [x] Source policy MVP 0.2 по-прежнему разрешает group eligibility только MANUAL.
- [x] Activity, splits, report и outbox создаются одной DB-транзакцией; outbox имеет
  unique Activity, lease, bounded retry и идемпотентное delivered state.
- [x] Backend security/privacy/outbox/API tests и Android mapping/permission/token/API/UI
  state tests добавлены.

## Known limitations

- Sync только foreground/manual; WorkManager отсутствует по scope.
- Route другого приложения требует отдельного пользовательского consent для конкретной
  ExerciseSession, если постоянный route permission не выдан.
- Для импорта обязательна положительная DistanceRecord; отсутствие optional HR, speed,
  cadence, elevation или route не блокирует item.
- Telegram Bot API не предоставляет idempotency key: unique outbox устраняет повторное
  создание report при повторной sync, lease/retry устраняет concurrent send, но crash
  строго после успешного Telegram send и до фиксации message ID оставляет малое окно
  возможной повторной сетевой доставки.
- Instrumentation tests требуют emulator/device с Health Connect provider; локально и в
  CI выполняются unit tests, assemble и static Android lint.
- Google Play publication, background sync, iOS и group maps остаются вне MVP 0.4.
