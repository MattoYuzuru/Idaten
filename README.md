# Idaten

Self-hosted Telegram-бот и backend для учета беговых тренировок, аналитики и рекомендаций.

Реализован **MVP 0.9**: Telegram сразу показывает статус распознавания текста/скриншота,
а `/stats` объединяет текущую неделю, два 28-дневных окна и восьминедельный график.
`/pr` честно разделяет фактические результаты 5 км, 10 км и полумарафона от оценок по
среднему темпу; `/next` объясняет дату, объём и причины консервативной рекомендации.
Настройки группового sharing доступны кнопками в `/privacy`. Все новые Activity
по-прежнему создаются `PRIVATE`, raw text/image не сохраняются.

## Документация

- [Архитектурные правила](docs/architecture-rules.md)
- [Roadmap](docs/roadmap.md)
- [Инструкция для следующего агента](docs/agent-handoff.md)
- [Журнал решений](docs/decision-log.md)
- [Спецификация MVP 0.9](docs/iterations/mvp-0.9.md)
- [Draft спецификации MVP 1.0](docs/iterations/mvp-1.0.md)
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

Личные команды: `/start`, `/menu`, `/run`, `/stats`, `/pr`, `/next`, `/privacy`, `/link`,
`/devices`, `/revoke_device <device_uuid>`, `/help`. Расширенный slash-ввод пробежки
`/run 10.02 1:02:41` остаётся поддержан, но обычный путь открывается кнопками.

`/run` без аргументов и кнопка «Добавить пробежку» предлагают три способа: ввод по
шагам, описание текстом и скриншот. Text/screenshot доступны только после отдельного
согласия и owner approval; при отключенном provider остальные способы продолжают работать.

Подписанный Android APK публикуется в [GitHub Releases](https://github.com/MattoYuzuru/Idaten/releases).
После установки предоставьте read permissions Health Connect, выполните `/link` в
private Telegram chat и введите одноразовый код в приложении. Установка, ручное обновление
и проверка checksum описаны в deployment guide.

Для импорта отправьте GPX/TCX/FIT/CSV или ZIP с одним поддерживаемым файлом в личный
чат. Бот покажет normalized preview; Activity появится только после подтверждения.

Команды в Telegram-группе: `/setup_group` (только Telegram admin/owner), `/join`,
`/leave`, `/week`, `/month`, `/group_goal <км>`, `/leaderboard`, `/streaks`. Уровень
sharing настраивается кнопками в личном `/privacy`; публикация конкретной пробежки
по-прежнему требует «Да/Нет/Всегда». Без opt-in активность остаётся private и не
учитывается в групповой статистике.

HTTP multipart endpoint `/imports` по умолчанию отключен. Для доверенной интеграции
задайте `IMPORT_API_TOKEN` и передавайте его вместе с `X-Telegram-User-Id`:

```bash
curl -F file=@activity.gpx \
  -H "X-Idaten-Import-Token: $IMPORT_API_TOKEN" \
  -H "X-Telegram-User-Id: 123456" \
  http://localhost:8000/imports
```
