# Idaten

Self-hosted Telegram-бот и backend для учета беговых тренировок, аналитики и рекомендаций.

Реализован **MVP 0.2**: ручной ввод пробежек, privacy-aware Telegram-группы,
явное разрешение публикаций, недельный leaderboard и streaks. Границы следующих
итераций зафиксированы отдельно, чтобы над проектом могли последовательно работать
разные агенты.

## Документация

- [Архитектурные правила](docs/architecture-rules.md)
- [Roadmap](docs/roadmap.md)
- [Инструкция для следующего агента](docs/agent-handoff.md)
- [Журнал решений](docs/decision-log.md)
- [Спецификация MVP 0.2](docs/iterations/mvp-0.2.md)
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

Личные команды: `/start`, `/run 10.02 1:02:41`, `/stats`, `/week`, `/pr`,
`/privacy [on|off]`, `/share <chat_id> <none|summary|detailed>`, `/help`.

Команды в Telegram-группе: `/setup_group` (только Telegram admin/owner), `/join`,
`/leave`, `/week`, `/leaderboard`, `/streaks`. После `/run` бот предлагает отдельное
разрешение «Да/Нет/Всегда» для каждой группы. Без opt-in активность остается private и
не учитывается в групповой статистике.
