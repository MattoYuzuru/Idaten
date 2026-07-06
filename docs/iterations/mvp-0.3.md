# MVP 0.3 — file ingestion и source abstraction

## Цель

Пользователь загружает GPX/TCX/FIT/CSV, проверяет draft и только затем сохраняет
нормализованную активность.

## Scope

- `StorageService` и local filesystem implementation с безопасными generated names.
- Модели `raw_artifacts`, `imports`, `activity_splits`, `activity_series`.
- Контракт `NormalizedActivity` и adapters Manual/GPX/TCX/FIT/CSV.
- Upload через Telegram и ограниченный HTTP multipart endpoint.
- Pipeline: save raw -> parse -> normalize -> validate -> dedup -> preview -> confirm -> save.
- Hash исходника, MIME/extension/size validation, import history.
- Series сохраняются compressed в storage; SQL содержит URI и summary.

## Dedup

Кандидат: тот же user, started_at ±2 минуты, distance ±100 м, duration ±60 секунд.
Exact external ID/hash имеет больший приоритет. Решение показывается пользователю при
неуверенности; pipeline должен быть idempotent при повторной доставке.

## Security

- ZIP защищен от path traversal, zip bombs и чрезмерного числа файлов.
- XML parsing запрещает external entities.
- Upload size configurable; пользовательское имя не становится filesystem path.
- Screenshot parser и Samsung ZIP semantics в этой итерации не реализуются.

## Acceptance criteria

1. Валидные GPX/TCX/FIT/CSV дают normalized draft.
2. До confirm Activity отсутствует.
3. Overrides повторно валидируются.
4. Confirm создает activity/splits и отчет одной транзакцией.
5. Повторный confirm/import не создает дубликат.
6. Ошибка parser сохраняет диагностируемый import status без утечки payload в лог.
7. Local storage переживает restart контейнера.

## Checklist

- [x] Добавлены `StorageService` и local filesystem adapter с generated UUID names,
  безопасными URI и persistent Docker volume.
- [x] Alembic migration добавляет `raw_artifacts`, `imports`, `activity_splits` и
  `activity_series` с constraints, indexes и delete rules.
- [x] Определен `NormalizedActivity`; Manual/GPX/TCX/FIT/CSV adapters нормализуют данные
  до общего backend-контракта.
- [x] Реализован pipeline save raw → parse → normalize → validate → dedup → preview →
  explicit confirm → transactional Activity/splits/report save.
- [x] Exact hash и external ID идемпотентны; fuzzy candidate использует окно ±2 минуты,
  ±100 м и ±60 секунд и требует отдельного согласия.
- [x] Overrides из HTTP повторно проходят backend validation до транзакции confirm.
- [x] Telegram document upload, confirm/cancel callbacks и `/imports` используют
  application service без SQL и parsing logic в handlers.
- [x] Multipart HTTP API защищен shared token, ограничивает чтение размером upload limit
  и использует тот же application service.
- [x] Track series сохраняются как gzip JSON в storage; SQL содержит URI, encoding,
  point count и безопасный summary.
- [x] XML external entities запрещены; ZIP ограничен по path, entry count, expanded size
  и compression ratio.
- [x] Parser failures сохраняют status/error code без raw payload в сообщении или логах.
- [x] Импортированная Activity создается PRIVATE и не проходит MVP 0.2 group source policy.
- [x] Тесты покрывают четыре формата, validation/security failures, preview-before-save,
  confirm, dedup, idempotency, privacy и HTTP auth.

## Known limitations

- HTTP API предназначен только для доверенной локальной интеграции и использует один
  shared token, а не пользовательские sessions/OAuth; без `IMPORT_API_TOKEN` он отключен.
- Telegram поддерживает preview/confirm/cancel, но overrides доступны только через HTTP.
- CSV MVP 0.3 — одна summary-строка с обязательными `started_at`, `distance_m` и
  `elapsed_time_sec`; произвольные vendor CSV dialects пока не распознаются.
- Generic ZIP должен содержать ровно один GPX/TCX/FIT/CSV. Samsung ZIP semantics и
  screenshot parsing намеренно не реализованы.
- FIT adapter использует стандартные session/record/lap messages; developer fields и
  multisport segmentation не поддерживаются.
- Failed/cancelled imports сохраняют raw artifact для audit. Retention/cleanup policy и
  автоматическая очистка storage orphan после аварии между filesystem и DB не входят в MVP.
- Local filesystem не шифруется приложением at rest; защита зависит от прав volume/host.
