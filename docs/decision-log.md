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
