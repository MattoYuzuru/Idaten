# MVP 0.8 — ввод пробежки текстом и скриншотом

## Цель

Добавить универсальный fallback для случаев, когда Health Connect не содержит
тренировку: пользователь описывает пробежку произвольным текстом либо отправляет
скриншот любого fitness-приложения, проверяет нормализованный черновик и явно сохраняет
private Activity.

Пользовательский интерфейс описывает действие, а не технологию. Кнопка «Добавить
пробежку» предлагает: «Ввести по шагам», «Описать текстом», «Отправить скриншот».

## Scope и invariants

- Существующий `/run <км> <длительность> ...` остается быстрым совместимым путем.
- `/run` без аргументов и кнопка меню показывают выбор способа ввода.
- Text/screenshot используют общий persistent typed draft и тот же confirm/persistence
  path, что manual wizard; handler не содержит validation, duplicate или privacy logic.
- Модель извлекает факты, но не считает pace/speed, не сохраняет Activity и не принимает
  privacy-решения.
- Обязательны distance, elapsed duration и local date. Отсутствующую дату пользователь
  вводит в preview; время суток optional и не выдумывается моделью.
- Activity создается `PRIVATE`. `TEXT` и `SCREENSHOT` не участвуют в group eligibility.

## Consent и закрытый доступ

1. До первого text/image input показывается отдельное согласие на передачу содержимого
   внешнему provider.
2. Отказ не сохраняется как вечный запрет: следующая попытка снова предлагает согласие.
   Access request и admin notification при отказе не создаются.
3. Принятое согласие хранит version и timestamp. При новой версии disclosure согласие
   запрашивается повторно.
4. После consent создается одна access request со status `PENDING`. Повторные попытки не
   дублируют request или уведомление.
5. Owner получает Telegram ID, безопасно escaped display/username и кнопки grant/revoke.
   Скрытые команды: `/ai_access grant|revoke|status <telegram_id>`.
6. Owner определяется `BOT_OWNER_TELEGRAM_ID`. Handler и backend service повторно
   проверяют owner; forged callback не меняет access.
7. `ALLOWED` проверяется перед каждым provider call. Revoke действует немедленно.

## Extraction provider

- Новый контракт `ActivityExtractionProvider` независим от coach wording provider.
- Первая реализация использует OpenAI Responses API с image/text input и strict JSON
  schema; стартовый configurable model — `gpt-4.1-nano`.
- Model selection остается deployment setting. Реальный capability/price и screenshot
  eval являются release gate; при недостаточном качестве используется configurable
  более сильная модель без изменения domain/service кода.
- Provider получает только текущий input, локальную дату/timezone для разбора относительной
  даты и schema. История, Telegram identity, токены, route и другие Activity не передаются.
- System instruction объявляет input недоверенными данными. Tools и свободный ответ
  отсутствуют. Backend повторно валидирует каждый field и отклоняет non-run.
- Timeout/retry bounded; provider failure не создает Activity и не закрывает draft.

## Ephemeral image и лимиты

- Private chat принимает одну JPEG/PNG картинку как photo либо image document.
- До скачивания проверяется Telegram file size; после скачивания — magic bytes,
  configurable byte limit и pixel limit.
- Bytes существуют только в памяти на время synchronous request. Local filesystem,
  raw artifact и database не используются.
- Сохраняются input SHA-256, provider/model, optional provider request ID, status и
  безопасный error code. Raw text/image, prompt и provider response не логируются.
- Per-user rolling daily limit, global monthly limit и global enable switch проверяются
  backend до provider call. Failed provider calls учитываются в лимите.

## Preview, edit и duplicate policy

Preview показывает extracted typed fields, source, missing fields, private default и
похожие Activity. Поля редактируются существующими ForceReply controls. После каждого
изменения preview строится заново.

Duplicate candidate обязан:

- принадлежать тому же пользователю и не быть soft-deleted;
- попадать в ту же локальную календарную дату;
- совпасть по distance в пределах `max(200 м, 3%)` либо по elapsed duration в пределах
  `max(120 сек, 3%)`.

Проверка выполняется в preview и повторно в confirm transaction. Fuzzy match блокирует
обычное сохранение и показывает existing date/distance/duration плюс кнопку «Сохранить
всё равно». Existing Activity не изменяется. Screenshot SHA-256/source external ID дает
exact idempotency и возвращает существующую Activity.

Policy применяется также к manual wizard и slash `/run`; direct slash при candidate
преобразуется в заполненный persistent preview с explicit override.

## Schema

- Users: extraction consent version/timestamp.
- `assisted_access`: one row per user, `PENDING|ALLOWED|REVOKED`, decision metadata.
- Persistent manual draft: input method, source, optional start-time precision,
  external/input hash и provider metadata.
- `extraction_attempts`: input hash/method, provider/model, status, timestamps и safe
  error code; raw content отсутствует.
- `SourceType.TEXT` добавляется синхронно в model/migration enum constraints.
- Migration имеет upgrade/downgrade, clean/previous-head PostgreSQL checks.

## Acceptance criteria

1. Добавление пробежки предлагает три способа без AI-маркетингового текста.
2. Отказ от consent не вызывает provider/admin side effects; последующая попытка снова
   позволяет согласиться.
3. Consent без access создает одну request; grant разрешает следующий input без
   повторного consent, revoke блокирует вызов.
4. Non-owner command/callback не меняет access и не раскрывает provider secrets.
5. Valid text и Samsung Health screenshot дают editable typed preview; модель не
   вычисляет pace и не пишет в БД Activity.
6. Missing date блокирует save до edit. Изменение даты повторно вычисляет duplicates.
7. Same-day distance-or-duration candidate требует explicit save-anyway; two legitimate
   sessions могут быть сохранены только после такого подтверждения.
8. Exact screenshot retry не создает вторую Activity.
9. Raw image/text отсутствуют в storage, DB и логах после request.
10. Size/pixel/rate/monthly/disabled limits блокируют provider до сетевого вызова.
11. Text/screenshot Activity private и отсутствуют в group leaderboard/month/streaks.
12. Без extraction key/provider manual, file import, Health Connect и весь основной
    продукт продолжают работать.
13. Ruff, strict mypy, pytest, PostgreSQL/Alembic и Docker gates проходят; live provider
    smoke выполняется только с owner-controlled test input и не печатает payload/key.

## Не входит

- General-purpose AI chat, conversation history и tools;
- хранение screenshot/raw prompt или background queue;
- Mini App, web admin и runtime provider switching через Telegram;
- Samsung ZIP adapter или прямая Samsung SDK integration;
- автоматическая публикация assisted Activity в группы;
- OCR/Tesseract fallback и распознавание нескольких тренировок на одном изображении.

## Checklist

- [ ] ADR и migration design реализованы.
- [ ] Consent/access/admin flow покрыт тестами.
- [ ] Common duplicate contract подключен к manual и assisted flows.
- [ ] OpenAI text/image provider и strict parsing реализованы.
- [ ] Ephemeral media и usage limits проверены.
- [ ] Telegram method selector, preview/edit/confirm реализованы.
- [ ] Privacy/source negative tests проходят.
- [ ] Full local/CI/release gates пройдены.
