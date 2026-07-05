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

