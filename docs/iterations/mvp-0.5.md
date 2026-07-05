# MVP 0.5 — coach engine, планы и monthly reports

## Цель

Дать полезную, воспроизводимую рекомендацию без обязательной LLM и расширить аналитику
до недельного/месячного уровня.

## Deterministic analytics

- Weekly/monthly volume and count, longest 7d/30d/all-time, average pace 30d.
- Run classification: EASY/STEADY/TEMPO/INTERVAL/LONG_RUN/RECOVERY/RACE/UNKNOWN.
- Risk flags: volume/long-run spike, too many hard runs, no rest, data quality flags.
- Правила документируются и версионируются; facts сохраняют версию calculator.

## Coach

- Следующий workout: type, distance/duration/pace range, reason и risk flags.
- `/next`, `/plan`, расширенные `/week`; group `/month` awards.
- TrainingPlan/PlannedWorkout и goal FIRST_10K/HALF/MARATHON/CUSTOM.
- Шаблонный report остается canonical fallback.

## LLM abstraction

- Providers: NONE, OpenAI, Gemini, DeepSeek, OpenRouter, Ollama.
- Provider получает только allowlisted `facts_json` без raw/route/person identifiers.
- Timeout, ограниченный retry и fallback template; ошибка LLM не откатывает activity.
- Сохраняются provider/model/prompt hash, но не секрет.
- Пользователь явно разрешает внешнюю обработку; Strava private-only исключается default.

## Monthly/social

- Total distance/runs, most distance, longest run, consistency, pair runs, group goal.
- Awards используют только privacy/source-policy eligible activities.
- Job idempotent по group + report period + type.

## Acceptance criteria

1. Одинаковые facts/rule version дают одинаковую рекомендацию.
2. `/next` работает с историей и безопасно отвечает при ее отсутствии.
3. Spike/hard/rest flags покрыты boundary tests.
4. Draft plan соответствует baseline и не увеличивает объем резко.
5. Без LLM key все команды и jobs работают на templates.
6. Provider timeout приводит к fallback, не к потере отчета.
7. Monthly job не дублирует сообщение при retry.
8. Privacy и Strava policy применяются до построения внешнего/group payload.

