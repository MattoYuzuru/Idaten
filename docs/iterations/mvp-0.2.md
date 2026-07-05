# MVP 0.2 — группы, privacy и social baseline

## Цель

Один бот работает в private/group chats, но использует активность в группе только после
явного opt-in пользователя и backend authorization check.

## Scope

- Модели `running_groups`, `group_members`, `group_publications`, privacy preferences.
- Роли OWNER/ADMIN/MEMBER; share level NONE/SUMMARY/DETAILED.
- `/setup_group`, `/join`, `/leave`, `/leaderboard`, `/streaks`, group `/week`.
- Private `/privacy` и `/share`.
- После `/run` inline confirmation: Да/Нет/Всегда для выбранной группы.
- Weekly leaderboard и streak вычисляются детерминированно.
- Group summary не содержит route, HR, raw payload и exact start time по умолчанию.

## Backend invariants

- Eligibility query проверяет membership, sharing enabled, activity visibility и source
  policy. UI callback не является разрешением сам по себе.
- Publication хранит Telegram message ID и текст для аудита.
- Leaderboard использует только разрешенные RUN и исключает soft-deleted records.
- Telegram group admin/owner права проверяются при setup/settings.

## Acceptance criteria

1. Группа создается один раз по Telegram chat ID.
2. Участник присоединяется и меняет share level.
3. Без подтверждения private activity не публикуется.
4. Summary содержит только разрешенные поля.
5. Leaderboard исключает NONE/private/ineligible source.
6. Повторный callback не дублирует publication.
7. Privacy behavior покрыт тестами на отрицательные сценарии.

## Checklist

- [x] Добавлены `running_groups`, `group_members`, privacy settings,
  per-activity grants и `group_publications` через Alembic.
- [x] Реализованы роли OWNER/ADMIN/MEMBER и share levels NONE/SUMMARY/DETAILED.
- [x] Реализованы `/setup_group`, `/join`, `/leave`, group `/week`, `/leaderboard`,
  `/streaks`, private `/privacy` и `/share`.
- [x] После `/run` доступны «Да/Нет/Всегда» отдельно для каждой активной группы;
  «Всегда» применяется к следующим ручным пробежкам.
- [x] Backend eligibility единообразно проверяет active membership, global sharing,
  group share level, per-activity grant, visibility, source policy и soft-delete.
- [x] Publication резервируется до отправки, затем хранит Telegram message ID и точный
  опубликованный текст; повторный callback не создает вторую публикацию.
- [x] Leaderboard и streaks используют только eligible RUN и считаются
  детерминированно в timezone группы.
- [x] Group message не содержит route/GPS, HR, raw payload и exact start time.
- [x] Отрицательные тесты покрывают no opt-in, global privacy off, NONE, private,
  revoked, forbidden source, soft-delete, non-member и forged publication.

## Known limitations

- Каждый участник должен сначала выполнить `/start` в личном чате: Telegram group chat
  не используется как private chat ID.
- Передача OWNER и ручное назначение ADMIN через команды пока отсутствуют. Существующий
  Telegram admin, повторивший `/setup_group`, получает роль ADMIN; OWNER не может выйти
  без будущего transfer flow.
- DETAILED пока использует тот же безопасный набор полей, что SUMMARY: normalized manual
  run не содержит дополнительных групповых полей, а HR/exact time намеренно закрыты.
- Streak — число последовательных календарных недель хотя бы с одной eligible-пробежкой;
  для текущего объема история вычисляется в application process без materialized view.
- Если процесс аварийно завершится между reservation и Telegram API call, незавершенная
  публикация потребует ручной очистки; обычная ошибка Telegram API отменяет reservation
  автоматически.

## Не входит

Файлы, Strava, Android, LLM, monthly awards, публичный dashboard.
