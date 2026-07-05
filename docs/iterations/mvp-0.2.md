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

## Не входит

Файлы, Strava, Android, LLM, monthly awards, публичный dashboard.

