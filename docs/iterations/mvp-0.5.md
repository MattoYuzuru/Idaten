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

## Версии и deterministic rules

- `calculator_version = coach-facts-v1`, `rule_version = coach-rules-v1`; обе версии
  сохраняются в `facts_json`, plan/report metadata и canonical rule result.
- Calendar week начинается в понедельник, calendar month — в первый день; границы
  вычисляются в IANA timezone пользователя/группы и запрашиваются как UTC half-open range.
- Rolling 7d/30d включают activity не позже `as_of`; average pace 30d — weighted по
  суммарным duration/distance.
- Pace classification относительно baseline: `RECOVERY >=115%`, `EASY >=105%`,
  `TEMPO <=90%`, иначе `STEADY`; title markers задают RACE/INTERVAL/TEMPO/RECOVERY/EASY/
  LONG_RUN, а long run без marker — не менее 10 км и 150% previous long baseline.
- `VOLUME_SPIKE` начинается с 130% среднего weekly volume предыдущих 28d,
  `LONG_RUN_SPIKE` — с 125% longest предыдущих 30d, hard-run flag — с трех hard runs
  за 7d, insufficient rest — activity во все семь local calendar days.
- Plan weekly targets растут не более чем на 10%; при недостаточной истории используется
  консервативный baseline и EASY recommendation.
- Pair run в MVP 0.5 — два или больше eligible участников с activity в один local day.

## Checklist

- [x] Deterministic weekly/monthly/rolling analytics и classification boundaries.
- [x] Versioned facts, risk flags, canonical `/next`, expanded `/week` и safe `/plan`.
- [x] TrainingPlan/PlannedWorkout и FIRST_10K/HALF/MARATHON/CUSTOM goals.
- [x] NONE/OpenAI/Gemini/DeepSeek/OpenRouter/Ollama abstraction, opt-in, timeout/retry/fallback.
- [x] Allowlisted LLM payload, Strava exclusion и provider/model/prompt hash persistence.
- [x] Eligible group `/month`, awards, pair runs, group goal и idempotent monthly outbox job.
- [x] Migration `20260707_0005` с clean upgrade, downgrade/upgrade и schema check.
- [x] Ruff format/lint, strict mypy, full pytest и Docker health/ready smoke.

## Known limitations

- Реальные network-вызовы providers не проверялись без credentials; timeout/error/retry,
  payload и fallback проверены fake adapters. Ollama требует отдельно запущенный endpoint.
- Classification не пытается восстановить интервалы без title marker из split/HR series;
  такие пробежки классифицируются по aggregate pace или как `UNKNOWN` при плохих данных.
- Draft plan MVP 0.5 содержит одну ключевую тренировку на неделю и weekly volume target;
  календарная периодизация нескольких тренировок в неделю остается вне текущего scope.
- Pair runs означают совпавший local calendar day, а не доказанный совместный GPS/time overlap.
