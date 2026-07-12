# Журнал решений

Записи не переписываются задним числом. Изменение решения оформляется новой записью со
ссылкой на замененное решение.

## ADR-001 — модульный монолит

- Дата: 2026-07-05
- Статус: принято
- Решение: backend и Telegram bot поставляются одним Python-приложением, а модули
  разделены внутри кода. Микросервисы, Redis и отдельный worker не вводятся в MVP 0.1.
- Причина: VPS ограничен по RAM, а текущая нагрузка не оправдывает распределенную систему.

## ADR-002 — polling для Telegram в MVP 0.1

- Дата: 2026-07-05
- Статус: принято
- Решение: aiogram long polling запускается в lifespan FastAPI, если задан bot token.
- Причина: не требует публичного домена, TLS и ingress. Переход на webhook остается
  транспортной заменой и не меняет application services.

## ADR-003 — PostgreSQL production default

- Дата: 2026-07-05
- Статус: принято
- Решение: production и Docker Compose используют PostgreSQL. Тесты могут использовать
  SQLite только как быстрый adapter-level контур, если поведение PostgreSQL отдельно
  проверяется миграциями/container smoke test.

## ADR-004 — UTC в БД, IANA timezone у пользователя

- Дата: 2026-07-05
- Статус: принято
- Решение: timestamps сохраняются timezone-aware; границы недели вычисляются в timezone
  пользователя и преобразуются в UTC для запроса.

## ADR-005 — осторожное определение PR

- Дата: 2026-07-05
- Статус: принято
- Решение: MVP 0.1 считает 5K/10K PR только по активности, дистанция которой находится
  между целевой дистанцией и +2%. Средний темп длинной пробежки не выдается за реальный
  best effort на коротком отрезке. Splits/best efforts появятся с импортами.

## ADR-006 — backend ownership бизнес-логики

- Дата: 2026-07-05
- Статус: принято
- Решение: Telegram handlers используют application services. Расчет пейса, статистики,
  границ недели, PR и отчетов находится вне bot package.

## ADR-007 — закрытый HTTP import endpoint в MVP 0.3

- Дата: 2026-07-06
- Статус: принято
- Решение: multipart import API отключен, пока не задан `IMPORT_API_TOKEN`. Клиент
  передает shared token в `X-Idaten-Import-Token` и существующий Telegram user ID в
  `X-Telegram-User-Id`. Telegram flow использует тот же application service без HTTP.
- Причина: в MVP 0.3 нет отдельной account/session authentication, но endpoint нельзя
  оставлять публичным. Shared token ограничивает endpoint для доверенной локальной
  интеграции; полноценная пользовательская авторизация остается отдельным будущим scope.

## ADR-008 — scoped device tokens для Health Connect

- Дата: 2026-07-06
- Статус: принято
- Решение: Android-устройство связывается с существующим пользователем одноразовым
  короткоживущим кодом, созданным в private Telegram flow. Код и выданный device token
  сохраняются только как keyed HMAC; token содержит публичный UUID устройства и
  случайный секрет, имеет фиксированный scope `health_connect:sync` и может быть
  немедленно отозван на backend.
- Причина: Android не должен получать Telegram credentials или использовать общий
  import token, а утечка БД не должна раскрывать действующие link codes/device tokens.

## ADR-009 — transactional outbox для private sync reports

- Дата: 2026-07-06
- Статус: принято
- Решение: Health Connect sync создает Activity, splits, coach report и уникальное
  private Telegram outbox-сообщение в одной DB-транзакции. Polling runtime доставляет
  outbox с lease/retry; уникальность по Activity предотвращает повторный report при
  повторной sync-доставке.
- Причина: сетевой вызов Telegram нельзя включить в SQL-транзакцию, поэтому durable
  outbox отделяет атомарную фиксацию результата от повторяемой доставки.

## ADR-010 — versioned coach facts и изолированный внешний wording

- Дата: 2026-07-07
- Статус: принято
- Решение: analytics calculator формирует детерминированный allowlisted `facts_json` с
  обязательными `calculator_version` и `rule_version`. Canonical recommendation строится
  локальными rules/templates; внешний provider может только переформулировать этот
  результат после явного user opt-in. Provider metadata сохраняется без ключа и полного
  prompt. Plan и coach report фиксируются атомарно, а monthly group report и его Telegram
  outbox создаются в одной транзакции с уникальностью по group, period и report type.
- Причина: одинаковые facts должны давать воспроизводимый результат, внешняя ошибка не
  должна менять метрики или откатывать продуктовые данные, а повтор monthly job не должен
  создавать второй report или Telegram message.

## ADR-011 — signed GitHub release и deployment в существующий k3s

- Дата: 2026-07-07
- Статус: принято
- Решение: Android APK подписывается одной постоянной release identity и публикуется
  GitHub Release workflow только из тега merge commit актуального `main`. Тот же workflow
  публикует backend в `ghcr.io/mattoyuzuru/idaten-backend` с version и commit SHA tags;
  production фиксирует immutable digest. Idaten развертывается одним backend replica со
  стратегией `Recreate` в отдельном namespace существующего k3s и переиспользует Traefik,
  cert-manager `letsencrypt-prod` и PostgreSQL `prod/postgres`. В PostgreSQL создаются
  отдельные database/role `idaten`; runtime secrets и local-path PVC принадлежат только
  namespace `idaten`. Production deployment остается явной локальной SSH-операцией, без
  server private key в GitHub Actions.
- Причина: постоянная подпись сохраняет Android update path, immutable image связывает
  deployment с проверенным release commit, а reuse существующей инфраструктуры экономит
  ресурсы малого VPS. Один replica исключает одновременный Telegram polling и periodic
  jobs; отдельные DB/user/namespace/secret/storage изолируют Idaten от других workloads.

## ADR-012 — cadence как optional Health Connect permission

- Дата: 2026-07-08
- Статус: принято
- Решение: Android companion больше не считает `StepsCadenceRecord` обязательным
  permission для состояния `READY`. Приложение запрашивает базовые read permissions для
  exercise session, distance, heart rate, speed и elevation; cadence samples читаются
  только если Health Connect уже выдал соответствующий доступ. Отсутствие cadence не
  блокирует загрузку пробежек или ручную синхронизацию.
- Причина: manual acceptance на реальном устройстве показал состояние 5/6 permissions,
  где Health Connect не позволял пользователю выдать cadence, из-за чего весь sync flow
  оставался недоступен. Cadence является дополнительным sample, а не обязательным полем
  Activity; отсутствие optional sample уже поддерживается backend ingestion.

## ADR-013 — source sessions, manual drafts и batch sync summary

- Дата: 2026-07-08
- Статус: принято
- Решение: каждая Health Connect exercise session сохраняется отдельной Activity с
  исходным external ID; объединение выполняется только в presentation DTO по локальной
  календарной дате пользователя. Backend сортирует входной sync batch по
  `(started_at, external_id)` и не считает порядок Android доверенным. Для batch из
  нескольких элементов создается одна запись `health_connect_sync_batches` и один
  durable Telegram outbox event; identity batch детерминированно строится из device и
  набора external ID, а per-activity unique constraint остается источником
  идемпотентности persistence. Одиночный sync сохраняет существующий after-run outbox.
  Поле cursor остается internal status metadata и не обещает incremental read, пока
  Health Connect paging ограничивается явными lookback/page limits.
- Решение: aggregate cadence и elevation gain хранятся nullable typed columns Activity
  с range constraints. Кнопочный ручной ввод использует persistent typed
  `manual_activity_drafts`: один ACTIVE draft на пользователя, expiry, optimistic
  version и terminal SAVED/CANCELLED/EXPIRED states. Confirm вызывает тот же
  `ActivityService` use case, что slash-команда; Telegram callback несет только opaque
  draft ID и действие.
- Причина: совпадение календарного дня не доказывает, что source sessions можно
  безопасно склеить; item transactions должны переживать partial batch failure, а
  Telegram retry не должен создавать N отчетов или повторный summary. Persistent draft
  делает restart/callback retry безопасными и не прячет queryable activity metrics в
  untyped JSON.

## ADR-014 — assisted activity input, consent и ephemeral media

- Дата: 2026-07-11
- Статус: принято
- Решение: кнопка добавления пробежки сначала предлагает три функциональных способа:
  пошаговый ввод, произвольный текст и скриншот. Текст и изображение нормализуются через
  отдельный доменный контракт `ActivityExtractionProvider`; provider не имеет tools,
  доступа к БД или истории пользователя и возвращает только strict typed extraction.
  Активный provider/model выбираются deployment-конфигурацией, а не Telegram-командой.
- Решение: перед первой передачей raw text/image внешний provider требует отдельного
  versioned consent. Отказ не создает access request и не уведомляет администратора.
  После согласия доступ выдается owner-only командой или callback; request идемпотентен,
  revoke применяется backend до каждого provider call. Секретные команды не публикуются
  через `setMyCommands`.
- Решение: изображение проверяется и обрабатывается синхронно в памяти. Оно не пишется в
  filesystem/БД и не попадает в логи; после provider call сохраняются только SHA-256,
  provider/model/request metadata и нормализованные typed поля. Очередь и отдельный
  worker не вводятся. Timeout оставляет черновик готовым к повторной отправке.
- Решение: persistent activity draft расширяется input method и provenance. Text
  Activity получает source `TEXT`, screenshot — `SCREENSHOT`; оба источника создаются
  `PRIVATE` и не становятся group-eligible в этой итерации. Pace/speed, validation,
  duplicate policy и persistence остаются backend-owned.
- Решение: fuzzy duplicate contract использует локальную календарную дату и совпадение
  хотя бы distance или elapsed duration в документированных пределах. Он применяется к
  manual/text/screenshot preview и повторно внутри confirm transaction. Fuzzy match не
  перезаписывает существующую Activity и требует явного `save anyway`; exact source/hash
  identity остается идемпотентной.
- Причина: интерфейс должен описывать пользовательскую задачу, а не рекламировать AI;
  один серверный ключ и allowlist подходят закрытой beta, но raw fitness screenshot
  требует отдельного согласия, ограничений расходов и data minimization. Provider
  abstraction сохраняет заменяемость OpenAI без преждевременного микросервиса.

## ADR-015 — adaptive `/next` и versioned deterministic pipeline

- Дата: 2026-07-12
- Статус: принято
- Решение: `/next` использует активную `RunningGoal`, immutable confirmed readiness и всю
  non-deleted RUN history через versioned recency-weighted pipeline
  `quality -> features -> state -> candidates -> safety -> scoring -> prescription`.
  Hard safety применяется до scoring; LLM не получает историю и не рассчитывает
  тренировку. Старая coach-v2 ветка заменяется, `/run` остаётся отдельным use case, а
  historical `TrainingPlan`/`PlannedWorkout` сохраняются без runtime dependency.
- Причина: одинаковые typed inputs и config должны воспроизводимо давать одну безопасную
  следующую пробежку, а цель не должна обходить ограничения самочувствия, перерыва и
  качества данных.

## ADR-016 — immutable reports и operational recommendation revisions

- Дата: 2026-07-12
- Статус: принято
- Решение: каждый расчёт создаёт immutable `CoachReport` и новую
  `NextRunRecommendation` revision. На пользователя существует не больше одной current
  revision в `PROVISIONAL`/`CONFIRMED`; предыдущая строка переводится в terminal status и
  связывается через `supersedes_id`. Confirm callback идемпотентен. Goal/readiness changes
  supersede current, expiry закрывает её через 72 часа после `not_before`, новая
  фактическая RUN после creation потребляет recommendation, а chronological backfill
  только supersede-ит её. Три Activity writer используют общий lifecycle collaborator в
  существующей транзакции.
- Причина: audit snapshot нельзя перезаписывать, но operational состояние должно
  атомарно переживать callback retry, import retry, backfill и несколько путей записи
  Activity.

## ADR-017 — unified AI registry, external access и consent v2

- Дата: 2026-07-12
- Статус: принято
- Решение: Activity extraction, readiness extraction и voice transcription используют
  единый task-aware `app/ai` registry/router. Единственный production provider MVP 1.0 —
  OpenAI с model per task; extension seam проверяется in-memory provider contract.
  `AssistedAccess` становится общим `ExternalAiAccess`: owner ALLOWED/REVOKED сохраняется,
  но пользователь повторно принимает consent v2 для wellbeing, sleep, fatigue, pain и
  voice. Text/image/audio/transcript обрабатываются ephemeral; audit хранит только hash,
  task/provider/model/status и timestamps. Historical provider metadata сохраняется, а
  runtime wording path и конкурирующие provider settings удаляются.
- Причина: application services не должны зависеть от vendor SDK или иметь несколько
  способов настройки одной интеграции; чувствительные raw inputs требуют общего
  data-minimized consent/access gate перед каждым external call.

## ADR-018 — optional Health Connect sleep summary

- Дата: 2026-07-12
- Статус: принято
- Решение: companion может отдельно синхронизировать bounded `SleepSessionRecord` как
  typed `SleepSummary` без stages/raw payload. `READ_SLEEP` optional и не влияет на RUN
  sync readiness. Backend идемпотентен по device/external ID и предлагает longest
  plausible session, завершившуюся не более 36 часов назад. Значения участвуют в engine
  только после editable preview и confirmed check-in; manual override имеет приоритет,
  а quality не выводится из duration или stages.
- Причина: Health Connect sleep может сократить ручной ввод, но permission, свежесть и
  доступность данных различаются между устройствами и не должны блокировать `/next` или
  создавать скрытую оценку восстановления.
