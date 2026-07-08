# Idaten

Self-hosted Telegram-бот и backend для учета беговых тренировок, аналитики и рекомендаций.

Реализован **MVP 0.6**: устанавливаемый Android companion с Health Connect onboarding,
постоянно подписанный GitHub Release APK, immutable backend image в GHCR и production
manifests для существующего k3s. Coach, imports и privacy/source policy предыдущих MVP
сохранены; Activity из Health Connect по-прежнему создается `PRIVATE`.

## Документация

- [Архитектурные правила](docs/architecture-rules.md)
- [Roadmap](docs/roadmap.md)
- [Инструкция для следующего агента](docs/agent-handoff.md)
- [Журнал решений](docs/decision-log.md)
- [Спецификация MVP 0.6](docs/iterations/mvp-0.6.md)
- [План следующей итерации MVP 0.7](docs/iterations/mvp-0.7.md)
- [Спецификации следующих MVP](docs/iterations/)
- [Локальный запуск](docs/deployment.md)

## Быстрый запуск

```bash
cp .env.example .env
# Укажите TELEGRAM_BOT_TOKEN в .env
docker compose up --build
```

Проверка backend:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
```

Личные команды: `/start`, `/run 10.02 1:02:41`, `/stats`, `/week`, `/next`,
`/plan <FIRST_10K|HALF|MARATHON|CUSTOM> [цель]`, `/external_processing on|off`, `/pr`,
`/privacy [on|off]`, `/share <chat_id> <none|summary|detailed>`, `/link`, `/devices`,
`/revoke_device <device_uuid>`, `/help`.

Подписанный Android APK публикуется в [GitHub Releases](https://github.com/MattoYuzuru/Idaten/releases).
После установки предоставьте read permissions Health Connect, выполните `/link` в
private Telegram chat и введите одноразовый код в приложении. Установка, ручное обновление
и проверка checksum описаны в deployment guide.

Для импорта отправьте GPX/TCX/FIT/CSV или ZIP с одним поддерживаемым файлом в личный
чат. Бот покажет normalized preview; Activity появится только после подтверждения.
`/imports` показывает последние попытки и их status.

Команды в Telegram-группе: `/setup_group` (только Telegram admin/owner), `/join`,
`/leave`, `/week`, `/month`, `/group_goal <км>`, `/leaderboard`, `/streaks`. После `/run` бот предлагает отдельное
разрешение «Да/Нет/Всегда» для каждой группы. Без opt-in активность остается private и
не учитывается в групповой статистике.

HTTP multipart endpoint `/imports` по умолчанию отключен. Для доверенной интеграции
задайте `IMPORT_API_TOKEN` и передавайте его вместе с `X-Telegram-User-Id`:

```bash
curl -F file=@activity.gpx \
  -H "X-Idaten-Import-Token: $IMPORT_API_TOKEN" \
  -H "X-Telegram-User-Id: 123456" \
  http://localhost:8000/imports
```
