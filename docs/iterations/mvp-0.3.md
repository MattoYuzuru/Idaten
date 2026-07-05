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

