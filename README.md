# Idaten

Self-hosted Telegram-бот и backend для учета беговых тренировок, аналитики и рекомендаций.

Сейчас реализуется **MVP 0.1**: ручной ввод пробежек через Telegram, PostgreSQL,
детерминированная статистика и отчет после тренировки. Границы следующих итераций
зафиксированы отдельно, чтобы над проектом могли последовательно работать разные агенты.

## Документация

- [Архитектурные правила](docs/architecture-rules.md)
- [Roadmap](docs/roadmap.md)
- [Инструкция для следующего агента](docs/agent-handoff.md)
- [Журнал решений](docs/decision-log.md)
- [Спецификация MVP 0.1](docs/iterations/mvp-0.1.md)
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

Команды бота: `/start`, `/run 10.02 1:02:41`, `/stats`, `/week`, `/pr`, `/help`.
