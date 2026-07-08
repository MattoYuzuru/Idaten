# Roadmap

Roadmap задает последовательность, а не обещание реализовать все заранее. Каждая
итерация должна оставлять работающий deployable продукт.

## MVP 0.1 — manual Telegram tracking

Цель: после ручного ввода пробежка сохраняется и сразу участвует в личной статистике.

Включено: FastAPI health/readiness, aiogram polling, PostgreSQL, users,
telegram accounts, activity sources, activities, coach reports, Alembic, Docker Compose,
`/start`, `/run`, `/stats`, `/week`, `/pr`, `/help`, template after-run report.

Не включено: группы, файлы, Android, Strava, LLM, планы, route/series.

Подробности: [mvp-0.1.md](iterations/mvp-0.1.md).

## MVP 0.2 — groups, privacy and social baseline

Добавляет Telegram-группы и opt-in публикации. Backend становится единственным местом,
где решается, разрешено ли использовать активность в сообщении или leaderboard.

Подробности: [mvp-0.2.md](iterations/mvp-0.2.md).

## MVP 0.3 — file ingestion

Добавляет raw artifacts, storage abstraction, GPX/TCX/FIT/CSV adapters, preview/confirm,
deduplication и import history. Это первая полноценная реализация общего ingestion flow.

Подробности: [mvp-0.3.md](iterations/mvp-0.3.md).

## MVP 0.4 — Android Health Connect

Добавляет Kotlin companion app, link code, device credentials и ручную синхронизацию
последних тренировок. Background-first sync намеренно отложен.

Подробности: [mvp-0.4.md](iterations/mvp-0.4.md).

## MVP 0.5 — coach, plans and summaries

Добавляет расширенную deterministic analytics, rules engine, планы, weekly/monthly
reports и optional LLM wording providers.

Подробности: [mvp-0.5.md](iterations/mvp-0.5.md).

## MVP 0.6 — Android release и production deployment

Добавляет Health Connect onboarding, постоянную release-подпись APK, GitHub Release/GHCR
pipeline и single-replica deployment в существующий k3s за HTTPS с изолированными
PostgreSQL database/user, Kubernetes Secret и PVC.

Подробности: [mvp-0.6.md](iterations/mvp-0.6.md).

## MVP 0.7 — reliable sync и guided Telegram UX

Исправляет Health Connect pagination/filter/order, добавляет диагностируемую ручную
синхронизацию, хронологические и сгруппированные по дням обзоры без склейки исходных
Activity. Расширяет `/run` historical/optional metrics и добавляет persistent кнопочный
мастер, state-aware onboarding, единый `/menu`, полный `/help`, scoped command menus и
безопасно форматированные Telegram-сообщения. Initial multi-sync завершается одним
идемпотентным batch summary вместо серии сообщений.

OCR/screenshots, Samsung ZIP, Mini App и background sync в итерацию не входят.

Подробности: [mvp-0.7.md](iterations/mvp-0.7.md).

## После MVP 0.7

Отдельно оцениваются: Strava private integration, screenshot OCR/vision, web dashboard,
Samsung Health export adapter, background sync, Telegram Mini App, race search,
S3/MinIO, Redis и observability stack. Они не должны заранее усложнять MVP.
