# MVP 0.7 — надежная синхронизация и guided Telegram UX

## Цель

Сделать первый пользовательский сценарий Idaten понятным без чтения документации:
пользователь запускает бота, подключает Android/Health Connect или выбирает ручной ввод,
явно подтверждает синхронизацию и получает один аккуратный обзор последних пробежек в
правильном порядке. Все основные private-chat действия доступны через кнопки, а команды
остаются быстрым и полностью документированным интерфейсом для опытного пользователя.

Публичная версия результата — `v0.7.0`. OCR/screenshot parsing, Mini App и фоновая
синхронизация в эту итерацию не входят.

## Обязательный порядок работы агента

1. Прочитать `AGENTS.md`, `docs/architecture-rules.md`, `docs/decision-log.md`,
   `docs/agent-handoff.md`, этот файл, `README.md`, `docs/deployment.md` и затрагиваемые
   Android/backend тесты.
2. Проверить свежий `origin/main`, открытые PR и последний CI; создать отдельную ветку.
3. Сопоставить каждый acceptance criterion ниже с существующим кодом и тестом.
4. До изменения schema, manual input contract и ADR-009 outbox semantics добавить новую
   ADR, не переписывая старые решения. В ней зафиксировать distinct source sessions,
   daily presentation grouping, persistent manual drafts и batch sync summary.
5. Реализовывать вертикальными срезами в порядке раздела «План выполнения»; не смешивать
   reliability fix, Telegram redesign и release metadata в один коммит.
6. Не переносить в scope OCR, Samsung export ZIP adapter, Mini App, Web App или background
   sync только ради более эффектного интерфейса.

## Продуктовые решения

### Source sessions и дневная группировка

- Каждая Health Connect `ExerciseSessionRecord` остается отдельной `Activity` со своим
  external ID. Несколько пробежек в один день не склеиваются и не теряют provenance.
- Личные обзоры группируют Activity по локальной календарной дате пользователя и
  показывают дневной итог: число сессий, суммарную дистанцию и суммарную длительность.
- Внутри дня отдельные сессии остаются видимыми в хронологическом порядке.
- Автоматическое объединение близких сессий, ручной merge/split и изменение исходных
  метрик не входят в MVP 0.7: одно совпадение дня или небольшой временной gap недостаточны
  для безопасного решения.

### Порядок данных

- Список «последние пробежки» отображается от новой к старой, с явной локальной датой и
  временем: это обзор, где важнее всего самая свежая запись.
- Sync batch нормализуется backend по `(started_at, external_id)` от старой к новой до
  persistence/report calculations. Клиентский порядок не считается доверенным.
- Telegram outbox доставляет batch/report events в порядке их создания. Номер пробежки
  за неделю вычисляется по хронологической истории, а не по порядку входного batch.
- Текст не использует двусмысленное «первая пробежка» без периода; формат —
  «1-я пробежка на неделе 15–21 июня».

### Native Telegram UI

MVP 0.7 использует возможности обычного Bot API, а не отдельное приложение внутри
Telegram:

- inline keyboards — действия, выбор optional fields, подтверждение, отмена и пагинация;
- `ForceReply` — ввод дистанции, длительности, даты и числовых значений;
- scoped bot commands — разные меню для private chat, group chat и group admins;
- редактирование одного сообщения мастера вместо длинной цепочки служебных сообщений;
- server-side draft ID в callback data; бизнес-данные не кодируются в callback payload;
- единый `/menu` как кнопочная точка входа, при сохранении всех slash-команд.

Bot API 10.1 добавил Rich Messages, а используемая ветка aiogram 3.x уже содержит
`sendRichMessage`. В начале Telegram-среза выполнить bounded compatibility spike для
структурированных help/batch-summary сообщений. Rich Messages можно использовать как
progressive enhancement только при подтвержденной поддержке целевых клиентов и наличии
простого HTML fallback; streaming rich drafts и перенос всего outbox в новый формат не
являются целью итерации.

Reply keyboard не должна постоянно занимать экран. Mini App/Web App не вводится, пока
нативный мастер покрывает текущие поля и не появляется измеримая потребность в форме.

Реализация должна сверяться с актуальной официальной документацией Telegram:

- <https://core.telegram.org/bots/api#inlinekeyboardmarkup>;
- <https://core.telegram.org/bots/api#forcereply>;
- <https://core.telegram.org/bots/api#botcommandscope>;
- <https://core.telegram.org/bots/api#formatting-options>;
- <https://core.telegram.org/bots/api#sendrichmessage>.

## Health Connect reliability

### Корректная выборка последних RUN

- `latestRuns(limit)` возвращает до `limit` именно беговых сессий, а не фильтрует RUN
  после получения одной страницы из `limit` любых упражнений.
- Реализовать bounded pagination через Health Connect page token: читать страницы, пока
  не найдено нужное число RUN, источник не исчерпан или не достигнут защитный предел.
- Пределы `limit`, page size, maximum pages и lookback period должны быть явными,
  тестируемыми и не позволять бесконечное чтение всей истории.
- Сессии с отсутствующей обязательной DistanceRecord не исчезают молча: UI показывает
  skipped item и безопасную причину без raw health payload.
- Android показывает период поиска, found/ready/skipped counts и для каждого skipped item
  стабильную категорию причины: non-running, missing distance, invalid duration или read
  error. Non-running aggregate count можно показать без раскрытия деталей чужих records.
- Optional HR, cadence, speed, elevation и route по-прежнему не блокируют activity.

### Sync и диагностика

- Manual Sync остается foreground и требует явного действия пользователя.
- Повторный sync external ID остается идемпотентным и показывает `duplicate`, а не
  выглядит как потерянная запись.
- Результат batch содержит saved/duplicate/skipped/error counts и item-level status.
- Cursor либо начинает реально ограничивать incremental read, либо удаляется из
  пользовательских обещаний и помечается internal-only; фиктивный cursor запрещен.
- Android различает отсутствие записей в Health Connect, записи вне lookback, локальную
  permission/provider проблему и backend/network error.
- Если Samsung Health не передал запись в Health Connect, Idaten честно сообщает, что не
  может прочитать ее автоматически, и предлагает ручной flow или GPX/TCX/FIT/CSV import.

## Post-link onboarding

### `/start` и главное меню

`/start` регистрирует пользователя и строит onboarding по backend state:

1. Коротко объясняет ценность и privacy default: новые Activity private.
2. Если активного устройства нет, показывает кнопки:
   `Подключить Health Connect`, `Добавить вручную`, `Импортировать файл`, `Что умеет бот`.
3. `Подключить Health Connect` создает одноразовый `/link` code и показывает короткие
   шаги: установить APK, выдать permissions, ввести code, проверить найденные пробежки,
   подтвердить Manual Sync.
4. Если устройство уже связано, показывает status последней sync и действия:
   `Мои пробежки`, `Как синхронизировать`, `Добавить пробежку`, `Статистика`, `Настройки`.
5. Returning user не получает повторно длинную инструкцию, если onboarding завершен.

Бот не может сам прочитать локальный Health Connect: чтение выполняет Android companion.
Telegram не должен обещать автоматическую загрузку до permission grant и подтвержденного
Manual Sync. После успешного link complete backend отправляет короткое private
уведомление «Устройство подключено» с дальнейшими шагами; кнопка синхронизации в Telegram
показывает инструкцию открыть Android, если надежный app deep link отдельно не реализован
и не проверен.

### Итог первой синхронизации

- Sync одной новой Activity создает обычный after-run report.
- Sync нескольких Activity, особенно initial history import, создает один идемпотентный
  private batch summary вместо серии из N почти одинаковых Telegram-сообщений.
- Summary содержит:
  - период и число найденных/saved/duplicate/skipped/error записей;
  - суммарные километры и время сохраненных Activity;
  - до N последних пробежек с локальной датой, дистанцией, временем и пейсом;
  - дневную группировку, если в одну дату было несколько сессий;
  - понятные следующие действия: статистика, ручное добавление, файл, help.
- Batch summary имеет отдельный idempotency key и durable outbox semantics. Повторная
  доставка того же sync batch не создает второе сообщение.
- Создание каждой Activity остается item-transactional; summary не делает весь batch
  all-or-nothing и честно отражает partial result.

## Ручное добавление и восстановление

### Быстрая команда

Сохранить обратную совместимость:

```text
/run <км> <длительность>
```

Расширенный формат:

```text
/run <км> <длительность> [date=YYYY-MM-DD] [time=HH:MM]
  [moving=H:MM:SS] [hr=<avg>] [max_hr=<max>] [cadence=<spm>]
  [elevation=<м>] [title="..."] [tz=<IANA timezone>]
```

Пример:

```text
/run 21.10 1:55:30 date=2026-06-16 time=07:30 hr=152 max_hr=178 cadence=171 elevation=164 title="Полумарафон"
```

Правила:

- обязательны только distance и elapsed duration;
- при отсутствии date/time используется текущее локальное время пользователя;
- timezone по умолчанию берется из user profile; naive timestamp в БД запрещен;
- pace и average speed всегда вычисляются из distance/time и не принимаются как
  независимый пользовательский ввод;
- `moving <= elapsed`, `avg_hr <= max_hr`, значения проходят явные domain ranges;
- exact start time, HR и cadence остаются private и не попадают в group summary;
- parser поддерживает quoted title, неизвестные/повторные keys отклоняются с подсказкой;
- старый `/run 10.02 1:02:41` продолжает работать без изменений.

Aggregate cadence и elevation gain требуют typed nullable полей Activity и Alembic
migration, если code audit подтвердит, что существующего normalized summary недостаточно.
Ручной ввод sample series, route/GPS и произвольных splits не реализуется: для них
используются Health Connect либо GPX/TCX/FIT.

### Кнопочный мастер `/run`

`/run` без аргументов и кнопка `Добавить пробежку` открывают один и тот же backend use
case:

1. Создать persistent draft со сроком жизни и одним active draft на пользователя.
2. Запросить distance через `ForceReply`, валидировать и показать нормализованное значение.
3. Запросить elapsed duration через `ForceReply` с примерами `45:30` и `1:45:30`.
4. Показать preview и optional buttons: `Дата`, `Время`, `Moving time`, `Пульс`,
   `Макс. пульс`, `Каденс`, `Набор высоты`, `Название`.
5. После каждого ответа повторно валидировать весь draft и редактировать preview.
6. `Сохранить` выполняет тот же application service, что расширенная slash-команда;
   `Отмена` закрывает draft; повторный callback идемпотентен.
7. После сохранения показать красивый private report и существующий explicit group-share
   prompt. Нажатие кнопки не заменяет backend privacy eligibility check.

Draft хранит typed values/status/expiry, но не Telegram objects. Restart backend не
должен создавать Activity из незавершенного draft или ломать уже выполненный callback.

## Telegram presentation

### Единый стиль сообщений

- Использовать Telegram HTML parse mode с централизованным escaping пользовательского
  текста. MarkdownV2 не использовать одновременно с HTML и не собирать разметку из raw
  title/username.
- Вынести presentation builders из handlers; handler только выбирает DTO, renderer и
  keyboard. Бизнес-метрики и privacy policy остаются в application services.
- Основную метрику выделять умеренно, например:

```html
🏃 <b>10,02 км</b> · 1:02:41
Темп: <b>6:15/км</b>
📅 16 июня 2026, 07:30
```

- Единицы и локаль единообразны: км с разумной точностью, duration без лишних нулей,
  даты в timezone пользователя, никаких raw ISO timestamps в пользовательском UI.
- Emoji используются как навигационные маркеры, не заменяют текст и не перегружают
  каждую строку.
- Длинные списки имеют bounded page size и inline pagination; callback содержит только
  action и opaque short ID.
- Ошибки содержат причину, допустимый формат и ближайшее действие, но не traceback/raw
  payload.

Обновить в этом стиле private reports, stats/week/month/PR/next/plan, import preview и
history, device/link/status, privacy/share, group summaries и validation errors. Group
messages сохраняют существующие privacy-safe поля.

### Полный `/help`

`/help` является исчерпывающей справкой текущего release, а не коротким примером. Она
должна быть разбита на категории и доступна через inline buttons:

- старт и меню: `/start`, `/menu`, `/help`;
- активности: `/run` с полным списком optional keys, `/stats`, `/week`, `/pr`, `/next`,
  `/plan` со всеми goals;
- импорт: поддерживаемые GPX/TCX/FIT/CSV/ZIP, preview/confirm и `/imports`;
- Health Connect: `/link`, `/devices`, `/revoke_device`, порядок действий в Android;
- privacy и группы: `/privacy`, `/share`, `/setup_group`, `/join`, `/leave`, `/month`,
  `/group_goal`, `/leaderboard`, `/streaks` и ограничения ролей;
- внешний wording: `/external_processing on|off` и его privacy meaning.

Для каждой команды указать context (private/group/admin), полный syntax, обязательные и
optional arguments, один рабочий пример и ожидаемый результат. Runtime `setMyCommands`
должен иметь согласованный список и отдельные scopes, чтобы private menu не засорялось
group-only командами.

## Schema и migration design

До реализации зафиксировать точный design в ADR и migration review:

- nullable aggregate `avg_cadence_spm` и `elevation_gain_m` либо обоснованное повторное
  использование существующего typed normalized summary;
- `manual_activity_drafts`: user FK, typed fields, status, expiry, version/idempotency,
  timestamps и constraint одного active draft;
- batch sync/report identity и durable outbox uniqueness без ослабления существующей
  per-activity idempotency;
- check constraints для новых числовых полей и согласованные model/migration enums;
- рабочие upgrade/downgrade, clean PostgreSQL upgrade и upgrade от предыдущего head.

JSON draft допустим только для действительно optional UI state; бизнес-поля Activity и
значимые queryable aggregates не прячутся в untyped payload.

## План выполнения

### Этап 1 — reliability и chronology

1. Добавить regression tests на filter-after-page bug и смешанные exercise types.
2. Реализовать bounded Health Connect pagination и диагностические item states.
3. Сортировать batch на backend, исправить weekly ordinal и локальное форматирование дат.
4. Проверить duplicate, partial failure, route consent и optional cadence regressions.

### Этап 2 — batch summary и daily presentation

1. Добавить pure daily grouping DTO/calculation с timezone boundary tests.
2. Спроектировать migration/idempotency для batch report/outbox.
3. Заменить initial multi-sync message flood одним summary; сохранить single-run report.
4. Покрыть retry, duplicate delivery, partial batch и несколько сессий одного дня.

### Этап 3 — extended manual use case

1. Расширить domain DTO, validation и Activity schema/migration.
2. Реализовать backward-compatible key-value parser и service tests.
3. Добавить persistent draft service и один transactional confirm path.
4. Подключить slash parser и wizard к одному application service.

### Этап 4 — Telegram UX и onboarding

1. Проверить Rich Messages на целевых клиентах; ввести reusable HTML
   presentation/escaping, fallback и keyboard builders.
2. Реализовать state-aware `/start`, `/menu`, link guidance и post-sync next actions.
3. Реализовать `/run` wizard с ForceReply, edit-preview, save/cancel/idempotency.
4. Перевести остальные сообщения и списки на единый стиль и pagination.
5. Сделать полный categorized `/help` и scoped `setMyCommands`.

### Этап 5 — release gate

1. Обновить Android/backend version до `0.7.0`, README, deployment и handoff.
2. Пройти backend, Android, PostgreSQL/Alembic и Docker gates из `AGENTS.md`.
3. Пройти manual device acceptance с mixed exercise history и несколькими RUN одного дня.
4. Проверить Telegram flows на новом и существующем пользователе, restart посреди draft,
   callback retry, HTML escaping и отсутствие privacy leaks.
5. Опубликовать draft PR; tag/release/deploy выполнять только после green main и явного
   production confirmation.

## Тестовая стратегия

- Pure unit: pagination policy, chronology, daily grouping, dates, parser, validation,
  HTML escaping и bounded pagination tokens.
- Android unit/state: mixed session pages, missing distance, empty/history-limited,
  permission/provider/network separation, newest-first display.
- Service/repository: persistent draft lifecycle, concurrent confirm, batch order,
  summary idempotency, outbox retry и migration constraints.
- Bot transport: `/start` state branches, wizard transitions, malformed reply, cancel,
  repeated callback, help categories, command scopes и parse mode.
- Privacy: manual HR/cadence/exact time absent from group output; private defaults,
  `NONE`, non-member, forbidden source and soft-delete remain covered.
- PostgreSQL/Alembic and Docker smoke remain mandatory before PR.

## Acceptance criteria

1. При истории из ходьбы/велосипеда и более чем одной страницы Health Connect приложение
   находит до N последних RUN, а не N последних упражнений до фильтра.
2. Android показывает found/ready/skipped/error counts и не маскирует source absence под
   backend error.
3. Backend обрабатывает sync от старой Activity к новой независимо от порядка клиента;
   Telegram dates и weekly ordinal корректны в timezone пользователя.
4. Три сессии одного дня остаются тремя Activity, но overview показывает один дневной
   блок с итогом и отдельными строками.
5. Initial multi-sync отправляет один идемпотентный summary; retry/duplicate не создают
   повторное сообщение или Activity.
6. `/run 10.02 1:02:41` работает как раньше, а расширенная команда сохраняет historical
   date/time, moving time, HR, cadence, elevation и title после полной валидации.
7. `/run` без аргументов позволяет кнопками собрать те же данные, preview, сохранить или
   отменить; restart и повторный callback безопасны.
8. `/start` дает понятный путь connect/manual/import, а после link+Manual Sync пользователь
   получает обзор последних пробежек и следующие действия.
9. Все основные private actions доступны через `/menu`/inline buttons; slash-команды не
   удалены и остаются быстрым интерфейсом.
10. `/help` и scoped command menus описывают каждую реально доступную команду, context,
    все arguments и примеры без несуществующих возможностей.
11. Пользовательские сообщения используют безопасный единый HTML style, локальные даты и
    выделенные ключевые метрики; raw ISO, unescaped title и payload не выводятся.
12. HR, cadence, exact start time, route и raw payload не попадают в group messages;
    существующая backend eligibility policy не обходится кнопками.
13. Full backend/Android CI, Alembic/PostgreSQL, Docker smoke и physical-device checklist
    пройдены; release `v0.7.0` опубликован из зеленого merge commit `main`.

## Не входит

- OCR/vision и импорт скриншотов;
- Samsung Health export ZIP semantics или прямой Samsung Health SDK adapter;
- автоматический merge/split Activity;
- Mini App/Web App и отдельный web frontend;
- WorkManager/background sync и silent auto-import;
- Google Play publication, iOS companion и Strava integration;
- ручной ввод GPS route, sample series или произвольных splits;
- изменение group eligibility/source policy без отдельного решения.

## Checklist

- [x] ADR для session grouping, drafts и batch outbox добавлена.
- [x] Health Connect pagination/filter/order и diagnostics исправлены.
- [x] Daily grouping и chronological reports реализованы.
- [x] Initial sync batch summary идемпотентен.
- [x] Extended `/run` и schema migration реализованы.
- [x] Persistent button wizard использует тот же manual use case.
- [x] `/start`, `/menu`, post-link onboarding и next actions реализованы.
- [x] HTML presentation, pagination и privacy-safe formatting применены.
- [x] Полный `/help` и scoped command menus синхронизированы.
- [ ] Backend/Android/PostgreSQL/Docker gates пройдены.
- [ ] Physical-device и Telegram UX acceptance пройдены.
- [ ] README/deployment/handoff обновлены, draft PR опубликован.

## Результат pre-production gate

- Backend: Ruff format/check, strict mypy и 94 pytest прошли.
- Android: 23 unit tests, Spotless, debug assembly и lint прошли. Signed release assembly
  выполняется GitHub CI, поскольку локальные release-signing credentials не экспортированы.
- PostgreSQL 17: clean upgrade, upgrade `0005 -> 0006`, schema check, downgrade
  `0006 -> 0005`, повторный upgrade и check прошли на disposable container.
- Docker Compose: image build, migrations, `/health` и `/ready` прошли; volumes и
  containers удалены после smoke.
- Deployment: provisioning unit tests, shellcheck и kustomize assertions прошли.
- Bot API 10.1 spike: aiogram 3.29.1 содержит `sendRichMessage`, но целевые Telegram
  клиенты не подтверждены; выбран обязательный HTML fallback без streaming rich drafts.

Open release blocker: `adb devices -l` не показал подключенного физического устройства,
поэтому mixed-history/route/upgrade checklist и live Telegram UX еще не выполнены. До
этой проверки нельзя отмечать acceptance criterion 13, создавать `v0.7.0` и выполнять
production rollout.

## Known limitations после MVP 0.7

- Health Connect остается источником Android sync; отсутствующую в нем Samsung запись
  можно восстановить командой или GPX/TCX/FIT/CSV, но не скриншотом.
- Sync остается foreground/manual и требует установленного Android companion.
- Separate source sessions не объединяются автоматически, даже если близки по времени.
- Native Telegram wizard удобен для aggregate fields, но не заменяет форму для route или
  sample series; появление Mini App оценивается только при реальной необходимости.
