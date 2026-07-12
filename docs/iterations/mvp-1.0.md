# MVP 1.0 — Adaptive Next Run

## Статус документа

- Статус: **draft для продуктового подтверждения; реализация не начата**.
- Baseline: `main`/`v0.9.1`, commit `b38367a`, Alembic head `20260711_0007`.
- Последний CI на `main`: run `29168820885`, успешно завершён 11 июля 2026 года.
- После ответов на вопросы в конце документа нужно зафиксировать выбранные defaults,
  добавить новые ADR и только затем начинать код.

Этот документ самодостаточен для следующего coding-агента. Исходное большое задание не
должно требоваться повторно, но устойчивые правила из `AGENTS.md`,
`docs/architecture-rules.md` и `docs/decision-log.md` имеют приоритет.

## 1. Цель и пользовательский результат

MVP 1.0 превращает консервативную `/next` из MVP 0.9 в детерминированную адаптивную
систему одной следующей пробежки. Она учитывает всю доступную историю, текущую беговую
цель, недавнюю нагрузку, перерыв, подтверждённое самочувствие, доступное время и, при
наличии, редактируемый sleep prefill из Health Connect.

Пользовательский сценарий остаётся коротким:

```text
сохранил пробежку
        ↓
нажал /next
        ↓
выбрал цель, если её ещё нет
        ↓
подтвердил короткий readiness check-in
        ↓
получил provisional следующую пробежку
        ↓
перед стартом быстро перепроверил состояние
        ↓
получил confirmed, уменьшенный, перенесённый или REST-вариант
```

Главный инвариант:

```text
user input → typed readiness → local deterministic engine
           → immutable versioned report → human explanation
```

LLM может быть только необязательным input adapter. Он не получает историю пробежек и
никогда не рассчитывает тренировку.

## 2. Непереговорные продуктовые и архитектурные правила

1. Единственная пользовательская команда рекомендации — `/next`; `/coach` не добавляется.
2. `/run` и `/next` — разные use cases. `ActivityService` не содержит readiness,
   goal, candidate, scoring или recovery rules.
3. `/plan` не возвращается. `TrainingPlan` и `PlannedWorkout` сохраняются как historical
   schema, но новая система на них не опирается.
4. Рекомендуются только бег или отдых. Другие виды активности представлены только
   субъективной внешней нагрузкой.
5. Основной ручной `/next` полностью работает при выключенных AI и Health Connect.
6. Только `CONFIRMED` check-in участвует в расчёте. Draft можно редактировать; после
   подтверждения typed values становятся immutable fact.
7. Любая рекомендация воспроизводима по versioned input facts/config и immutable
   `CoachReport`.
8. Hard safety rules применяются до scoring и не растворяются в среднем readiness score.
9. Raw text/image/voice, transcript, GPS route, Telegram identity и полный профиль не
   передаются в deterministic domain и не сохраняются как часть AI flow.
10. Handler только разбирает Telegram update, вызывает application service и отображает
    typed result/error. Все lifecycle, authorization, consent и idempotency checks — backend.
11. Goal, readiness, sleep и recommendation — только private user data. Они не участвуют
    в group messages, leaderboard, streaks или monthly reports и не попадают в логи.

## 3. Фактический baseline MVP 0.9

Перед реализацией учитывать существующую структуру, а не создавать параллельный продукт:

- `app/coach/domain.py` содержит `RunFact`, facts/rules v2 и три фиксированные ветки
  `recommend_next()`;
- `app/coach/service.py` каждый раз создаёт новый `NEXT_WORKOUT` `CoachReport`, но не
  сохраняет operational lifecycle и всё ещё содержит historical plan/wording paths;
- `app/coach/provider.py` и `app/assisted/provider.py` — две конкурирующие provider
  abstraction/configuration;
- `app/activities/models.py` уже содержит immutable `CoachReport`; его не заменять;
- manual, file import и Health Connect создают Activity разными application services и
  каждый отдельно строит after-run report;
- `ActivityRepository.run_history()` уже сортирует по `started_at`, но DTO не содержит
  moving time, HR, cadence, elevation и linked session RPE;
- persistent `ManualActivityDraft` показывает рабочий образец restart-safe Telegram
  draft/edit/idempotent confirm;
- `AssistedAccess`, consent v1 и `ExtractionAttempt` относятся только к text/screenshot
  Activity extraction;
- Android запрашивает exercise/distance/HR/speed/elevation и optional cadence, но не
  `READ_SLEEP`; backend protocol принимает только running Activity;
- `/next` handler и `menu:next` напрямую вызывают `CoachService.next_workout()` без
  flow state;
- Alembic head до итерации — `20260711_0007`.

Новый код должен переиспользовать существующие repository/service patterns и composition
root `app/services.py`. Не расширять текущий 1299-строчный `bot/handlers.py` всей новой
state machine: выделить тематический private router/presentation module.

## 4. Scope и доменные контракты

### 4.1. Активная беговая цель

Добавить отдельную сущность `RunningGoal`, не связанную с календарным plan:

```python
class RunningGoalType(StrEnum):
    FIRST_5K = "FIRST_5K"
    FIRST_10K = "FIRST_10K"
    FIRST_HALF = "FIRST_HALF"
    FIRST_MARATHON = "FIRST_MARATHON"
    IMPROVE_HALF = "IMPROVE_HALF"
    IMPROVE_MARATHON = "IMPROVE_MARATHON"
    GENERAL_ENDURANCE = "GENERAL_ENDURANCE"


class RunningGoalStatus(StrEnum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
```

Минимальные поля: UUID, user UUID, type, optional `target_date`, optional
`target_duration_sec`, status, `started_at`, optional `completed_at`, created/updated.

DB invariants:

- partial unique index: максимум одна `ACTIVE` цель на пользователя;
- `target_duration_sec > 0` и разрешён только для `IMPROVE_HALF`/
  `IMPROVE_MARATHON`;
- для improvement goal целевое время обязательно в UI и service, но constraint должен
  также защищать прямую запись;
- завершённая цель имеет `completed_at`, active/cancelled — нет;
- смена цели закрывает предыдущую как `CANCELLED`, создаёт новую строку и supersede-ит
  активную recommendation в одной транзакции;
- история целей не удаляется.

На первом `/next` без active goal service возвращает `NEED_GOAL`. Отдельная команда
`/goal` не вводится. Каждая показанная рекомендация содержит кнопку «Изменить цель».

Достижение цели не меняет status автоматически. На входе в `/next` service проверяет:

- finish goal: завершённая non-deleted RUN с дистанцией не меньше 98% target distance;
  более длинная Activity также доказывает завершение дистанции;
- time goal: только фактическая RUN в коридоре target distance ±2% с
  `elapsed_time_sec <= target_duration_sec`; pace estimate длинной тренировки не подходит;
- historical backfill также может обнаружить достижение, но пользователь всё равно
  подтверждает «Отметить выполненной»;
- при подтверждении goal становится `COMPLETED`, active recommendation superseded, затем
  предлагается выбор следующей цели.

Стандартные дистанции нужно вынести в один domain contract и расширить до 5 000, 10 000,
21 097 и 42 195 м, чтобы `/pr`, goal completion и coach не имели разных tolerance.

### 4.2. Readiness check-in и persistent draft

Использовать две фазы:

```python
class CheckInPhase(StrEnum):
    POST_RUN = "POST_RUN"  # planning/replanning до not_before
    PRE_RUN = "PRE_RUN"    # перепроверка в/после not_before


class CheckInStatus(StrEnum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class CheckInInputSource(StrEnum):
    MANUAL = "MANUAL"
    AI_TEXT = "AI_TEXT"
    AI_VOICE = "AI_VOICE"
    HEALTH_CONNECT = "HEALTH_CONNECT"
    MERGED = "MERGED"
```

Typed поля confirmed check-in:

- `overall_readiness: int` — 1..5;
- `general_fatigue: int` — 0..10;
- `muscle_soreness: int` — 0..10;
- `motivation: int | None` — 1..5; proposed default: optional, пока не подтверждён
  вопрос Q1;
- `sleep_quality: int | None` — 1..5;
- `sleep_duration_sec: int | None` — положительное и plausibility-bounded;
- `sleep_ended_at: datetime | None` и `sleep_summary_id: UUID | None` для freshness и
  provenance;
- `external_load: int` — 0..10;
- `pain_present: bool`;
- `pain_severity: int | None` — 0..10;
- `pain_location: str | None` — trimmed/bounded, не передаётся в explanation дословно;
- `pain_affects_movement: bool | None`;
- `pain_is_new: bool | None`;
- `pain_is_worsening: bool | None`;
- `illness_symptoms: bool`;
- `available_time_sec: int | None`;
- `session_rpe: int | None` — 1..10, только POST_RUN и по возможности linked Activity;
- source, optional source confidence, timestamps, draft version, pending field, expiry,
  optional Telegram message ID.

Pain fields required and non-null when `pain_present=true`; они должны быть null при
`false`. `session_rpe` запрещён для PRE_RUN. `sleep_summary_id` не даёт права без
подтверждения check-in автоматически использовать Health Connect.

Draft mutable только до confirm. Confirm выполняется с row lock, повторный callback
возвращает уже созданный result, а не создаёт второй check-in/recommendation. Один active
draft каждой фазы на пользователя; старый active draft закрывается или возвращается
идемпотентно по явно документированному правилу.

Рекомендуемый короткий manual flow:

1. готовность 1–5;
2. общая усталость 0–10 и мышечная болезненность 0–10;
3. боль/признаки болезни; при боли — severity, location, movement, new, worsening;
4. сон: quality 1–5 и optional duration либо editable Health Connect prefill;
5. внешняя нагрузка 0–10;
6. optional motivation и available time;
7. для POST_RUN linked к последней Activity — session RPE 1–10;
8. единый preview всех typed полей, edit/clear/cancel/confirm.

Нельзя подставлять неотвеченные self-report поля скрытым «средним» значением. Missing
optional data снижает confidence, но не блокирует ручной `/next`.

### 4.3. Immutable report и operational recommendation

`CoachReport` остаётся immutable audit snapshot. На каждый расчёт создаётся новый report
с полными allowlisted `facts_json`, `rule_result_json`, `calculator_version` и
`rule_version`.

Для operational lifecycle использовать новую строку на каждую revision, а не
перезаписывать `current_report_id` старой строки:

```python
class RecommendationStatus(StrEnum):
    PROVISIONAL = "PROVISIONAL"
    CONFIRMED = "CONFIRMED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"
    CONSUMED = "CONSUMED"
    CANCELLED = "CANCELLED"
```

`NextRunRecommendation` хранит UUID, user/goal/source Activity/check-in/report UUID,
status, `recommended_for`, timezone-aware `not_before`, optional `valid_until`, optional
`supersedes_id`, deterministic `inputs_fingerprint`, optional idempotency key и
timestamps.

Invariants:

- partial unique index разрешает не больше одной current строки со status
  `PROVISIONAL`/`CONFIRMED` на пользователя;
- `report_id` unique; одна revision ссылается ровно на один immutable report;
- `supersedes_id` указывает на непосредственную предыдущую revision и не образует цикл;
- PRE_RUN confirm создаёт `CONFIRMED` revision и переводит provisional в `SUPERSEDED`;
- изменение goal/confirmed readiness создаёт новую revision и supersede-ит current;
- одинаковый повторный confirm callback возвращает существующую revision по
  check-in/idempotency key;
- простой повтор `/next` до `not_before` ничего не пишет и показывает current;
- явный «Пересчитать» может создать revision только один раз на callback и должен
  объяснить, что входы не изменились, если результат совпал;
- после `valid_until` current становится `EXPIRED`, затем начинается новый planning
  check-in; proposed default validity — 72 часа после `not_before` (Q4).

Новая завершённая Activity обрабатывается внутри той же транзакции, где она сохраняется:

- фактически началась после создания current recommendation — current становится
  `CONSUMED`;
- была backfill-активностью с более ранним `started_at` — current становится
  `SUPERSEDED`, но не `CONSUMED`;
- duplicate/retry не меняет lifecycle второй раз;
- Activity не считается точным выполнением prescription: в MVP `CONSUMED` означает
  только появление следующей фактической пробежки.

Для трёх Activity writers (`ActivityService`, `ImportService`, `HealthConnectService`)
выделить общий application lifecycle collaborator, принимающий существующую DB session.
Он меняет status, но не содержит calculation rules. Это сохраняет transaction boundary и
не размножает invalidation policy.

### 4.4. Domain facts

Расширить immutable `RunFact` без SQLAlchemy/Telegram/raw payload:

```python
@dataclass(frozen=True, slots=True)
class RunFact:
    activity_id: UUID
    started_at: datetime
    distance_m: int
    elapsed_time_sec: int
    moving_time_sec: int | None
    avg_pace_sec_per_km: int
    avg_hr: int | None
    max_hr: int | None
    avg_cadence_spm: int | None
    elevation_gain_m: int | None
    source_type: SourceType
    title: str | None
    session_rpe: int | None
    start_time_known: bool
```

Repository загружает всю non-deleted RUN history в stable order `(started_at,
activity_id)` и присоединяет последний confirmed POST_RUN `session_rpe` для Activity.
Future/incomplete runs исключаются по end time. Persistence order, import time и UUID не
влияют на числовой результат, кроме стабильного разрешения точного tie.

## 5. Deterministic recommendation engine v1

Не расширять существующий монолитный `recommend_next()`. Целевой pipeline:

```text
RunHistory + ActiveGoal + ConfirmedCheckIn + optional provisional bounds
        ↓
DataQualityAssessment
        ↓
TrainingFeatures
        ↓
AthleteState
        ↓
CandidateGeneration
        ↓
HardSafetyFilters
        ↓
CandidateScoring
        ↓
ContinuousPrescription
        ↓
Reason codes + observations + alternatives
```

Каждая стадия — чистая typed function/module; orchestration может быть одним facade, но
не одной функцией с ветками. Configuration — frozen versioned dataclass. Initial names:
`calculator_version="adaptive-features-v1"`, `rule_version="adaptive-next-v1"`.

### 5.1. Recency и training features

Базовый вес:

```text
weight(age_days, half_life_days) = 2 ** (-age_days / half_life_days)
```

Initial config:

| Область | Half-life |
|---|---:|
| fatigue | 7 дней |
| recent load | 28 дней |
| current capability | 90 дней |
| historical prior | 365 дней |

Age считается от фактического завершения Activity до `as_of`, не от import/create time.
Сезонность не добавляется.

Минимальные features:

- EWMA distance, duration и training load на четырёх горизонтах;
- volume 7/28/42/90 дней и frequency 7/28/90;
- longest run 30/60/90, current/historical peak volume;
- days since last run, hard run и long run;
- consistency и hard-session density;
- recent break и максимальный gap;
- robust recent pace/HR distributions, когда данных достаточно;
- elevation load penalty;
- achieved standard distances и reliable actual target-distance results;
- historical experience отдельно от current capability;
- previous recommendation consumption/adherence только если факт можно вывести без
  догадки; иначе feature остаётся unavailable.

Initial break bands: `>=21` дней снижает current capability/confidence; `>=42` дней
включает return-to-running hard filter. Исторический peak после длинного перерыва может
повысить только experience confidence. Он не поднимает допустимый volume/duration до
прошлого уровня. Cap растёт после новых confirmed check-ins и успешных Activity.

### 5.2. Training load и классификация

Если есть linked session RPE:

```text
session_load = elapsed_duration_minutes * session_rpe
```

Иначе:

```text
estimated_load = duration_minutes * intensity_factor * elevation_factor
```

Fallback kind factors должны находиться в config, например recovery `0.8`, easy `1.0`,
steady `1.15`, tempo `1.4`, long `1.15`, race `1.6`, unknown `1.1`.
`elevation_factor` ограничивается диапазоном `[1.0, 1.25]`.

Hard classification нельзя получать только из небольшого pace deviation. Допустимые
сигналы: explicit bounded title vocabulary, RPE, достаточно надёжные HR и pace
percentiles. Без RPE/title hard status требует согласия как минимум двух независимых
metric signals; иначе classification остаётся steady/unknown и confidence снижается.
INTERVAL может распознаваться как historical hard load, но interval prescription в
MVP 1.0 запрещён.

### 5.3. Data quality

Вернуть общий `data_confidence` и отдельные confidence: volume, pace, heart rate,
readiness, sleep. Каждый score `[0, 1]` учитывает coverage, plausibility, freshness,
source consistency и sample size.

Initial overall weights: volume `0.35`, pace `0.20`, HR `0.10`, readiness `0.25`, sleep
`0.10`. Отсутствие HR/sleep не блокирует result, но делает его консервативнее. Confirmed
manual и user-confirmed AI preview имеют один typed contract; AI origin сам по себе не
даёт higher confidence. Stale sleep получает confidence `0` и не входит в readiness.

Ни одна сомнительная metric не должна единолично разрешить tempo/long run или резкое
увеличение volume. В explanation при low confidence перечисляются только безопасные
категории отсутствующих данных, не internal score/formula.

### 5.4. Readiness score и hard safety

Нормализовать self-report в `[0, 1]`: readiness/motivation как `(value - 1) / 4`,
fatigue/soreness/external load как `value / 10`. Proposed numeric composition:

```text
positive = weighted mean of present values:
    overall_readiness 0.65
    motivation       0.15
    sleep            0.20

load = 0.45 * general_fatigue
     + 0.35 * muscle_soreness
     + 0.20 * external_load

readiness_score = clamp(0.70 * positive + 0.30 * (1 - load), 0, 1)
```

Missing motivation/sleep исключается из positive с renormalization, а не заменяется
скрытым значением. Sleep component использует explicit quality и duration heuristic из
versioned config; он не называется медицинской оценкой сна.

Hard safety имеет приоритет:

- pain affecting movement, worsening pain, severity `>=6` или любые illness symptoms —
  только `REST` в proposed default (Q4);
- новая/умеренная pain без movement effect — исключить tempo/long/steady, уменьшить
  volume и сдвинуть `not_before`;
- readiness `<0.25` — REST; `<0.45` — только REST/recovery short;
- break `>=42` дней — только recovery/easy short;
- insufficient history/low confidence — только conservative REST/recovery/easy;
- recent hard run, long-run spike или insufficient recovery исключает tempo;
- high external load уменьшает volume/intensity и может отложить run;
- available time — hard upper bound, но не основание сжимать unsafe workout до
  псевдоинтенсивной версии.

REST — decision рекомендательной системы, а не Activity type. Текст не ставит диагноз:

> Сегодня бег лучше отложить. Вы указали состояние, при котором безопаснее не начинать
> тренировку. Если боль или симптомы сохраняются либо усиливаются, обратитесь к
> медицинскому специалисту.

### 5.5. Candidates и scoring

```python
class RunDecision(StrEnum):
    RUN = "RUN"
    REST = "REST"


class RecommendedRunKind(StrEnum):
    RECOVERY = "RECOVERY"
    EASY = "EASY"
    STEADY = "STEADY"
    TEMPO = "TEMPO"
    LONG_RUN = "LONG_RUN"
```

Генерировать REST, recovery short, easy short/normal, steady, controlled tempo и
conservative long-run с min/preferred/max distance/duration, RPE, optional pace/HR,
recovery cost, goal value и risk penalty. Затем hard filters удаляют недопустимые.

Initial utility weights хранятся рядом с rule version, а не в handlers:

```text
utility = 2.0 * goal_alignment
        + 1.2 * adaptation_value
        + 0.8 * consistency_value
        + 0.8 * adherence_probability
        - 1.6 * fatigue_cost
        - 2.0 * risk_penalty
        - 0.8 * schedule_cost
        - 1.2 * uncertainty_penalty
```

Goal alignment задаётся versioned matrix. FIRST goals преимущественно выбирают easy и
постепенно long; improvement goals могут допустить controlled tempo только при достаточной
истории/confidence; target date никогда не отменяет safety bound. При нереалистично
близкой дате explanation сообщает ограничение, а не ускоряет рост.

### 5.6. Continuous prescription

Base duration — recency-weighted median устойчивых non-hard sessions последних 90 дней;
fallback: 25 минут без истории, не больше 30 минут после break `>=42` дней. Затем:

```text
preferred_duration = base_duration
                   * kind_multiplier
                   * goal_multiplier
                   * readiness_multiplier
                   * risk_multiplier
```

Initial readiness multiplier ограничен `[0.75, 1.10]`; historical peak не входит в него.
После формулы применяются current-volume, recent-longest, recovery, confidence и
available-time hard caps. Distance получается из robust sustainable pace только при
достаточной pace confidence.

Presentation rounding:

- distance — 500 м;
- duration — 5 минут;
- pace range — 5–10 секунд/км;
- никаких `6.437 км`;
- RPE/talk test показывается всегда для RUN;
- HR range показывается только при достаточной HR confidence;
- pace — дополнительный, а не единственный intensity ориентир.

`not_before` считается от фактического end time последней Activity и recovery duration из
versioned config; initial lower bounds: 24 часа после recovery/easy, 36 после steady и 48
после hard/long. Pain, low readiness, sleep/external load uncertainty могут только
увеличить интервал. `recommended_for` — локальная дата получившегося timestamp; сам
timezone-aware timestamp не теряется ради date-only UI.

Short alternative: тот же или более лёгкий kind, примерно 65–75% main duration, не
меньше безопасного minimum и никогда не выше main по distance/intensity. Если meaningful
short option невозможен, поле null и это не ошибка.

Canonical prescription включает decision/kind, date/not-before, rounded main values,
optional pace/HR, RPE, short alternative, confidence, reason codes и observations.
Внутренние safe min/max bounds сохраняются в `rule_result_json`: PRE_RUN улучшение может
двигаться только внутри provisional bounds. Ухудшение может выйти ниже minimum, перенести
дату или вернуть REST.

## 6. Lifecycle `/next`

Application flow service возвращает transport-neutral state DTO:

```text
NEED_GOAL
NEED_CHECK_IN_METHOD
EDIT_CHECK_IN
SHOW_PROVISIONAL
NEED_PRE_RUN_CHECK_IN
SHOW_CONFIRMED
GOAL_ACHIEVEMENT_CONFIRMATION
```

### Stage A — provisional

1. Resolve user/timezone and active goal.
2. Если goal отсутствует/достигнута — goal flow.
3. Найти current recommendation и проверить invalidation/expiry.
4. До `not_before` без новых входов показать current без DB write.
5. Иначе создать/возобновить POST_RUN draft; предложить manual/text/voice.
6. После preview confirm загрузить всю history, goal и confirmed check-in.
7. Рассчитать, атомарно создать `CoachReport` + `PROVISIONAL` revision.
8. Показать `recommended_for`, `not_before`, main, short, intensity, reason и предложение
   повторной проверки.

### Повтор до `not_before`

Показать remaining time/date и кнопки:

- «Самочувствие изменилось» → новый POST_RUN draft/revision;
- «Изменить доступное время» → draft с текущими значениями;
- «Пересчитать» → explicit idempotent recalculation;
- «Изменить цель» → goal flow.

### Stage B — pre-run

При `now >= not_before` и не истёкшем provisional `/next` начинает PRE_RUN draft. После
confirm engine получает provisional safe bounds:

- состояние не хуже — подтвердить внутри прежних bounds;
- хуже — снизить kind/duration/distance, перенести или REST;
- лучше — повысить только до provisional max, без нового unsafe candidate;
- создать новый report + `CONFIRMED` revision, provisional supersede.

## 7. Telegram UX

### 7.1. Goal

При первом `/next`:

> Какая у вас сейчас основная цель?

Кнопки: впервые 5 км, 10 км, полумарафон, марафон; улучшить полумарафон/марафон;
общая выносливость. Improvement goal затем запрашивает target time. Target date optional
и не блокирует calculation.

### 7.2. Check-in preview

Preview показывает все значения человеческими labels, provenance свежего sleep prefill и
«нет данных» для optional values. Доступны confirm, edit каждого смыслового поля,
clear optional sleep/time и cancel. Internal enum/score/formula не показываются.

Callback содержит только компактное action + opaque UUID. Ownership, draft phase/status,
expiry, current version и повторная доставка проверяются service под row lock.

### 7.3. Recommendation

Пример:

```text
Следующая пробежка

Когда: не раньше 16 июля
Основной вариант: 8 км легко, около 50 минут
Короткий вариант: 5,5 км легко, около 35 минут
Интенсивность: RPE 3–4 из 10, разговорный темп

Почему: восстановление хорошее, но недельный объём уже близок к обычному. Сейчас
полезнее закрепить нагрузку без ускорения.

Перед стартом ещё раз проверьте самочувствие.
```

Reason codes отображаются только через allowlisted Russian templates. User-entered pain
location, raw title и AI text не отражаются дословно без HTML escaping и необходимости.

### 7.4. После `/run`

Убрать из after-run report старую автоматически рассчитанную «следующую лёгкую» ветку.
После успешного direct Telegram save/confirm показать CTA:

```text
[Рассчитать следующую пробежку]
[Вернуться в меню]
```

Flow не запускается автоматически. Для Health Connect durable outbox достаточно текста с
`/next`, если текущий outbox contract не поддерживает markup. Group sharing flow остаётся
независимым.

## 8. Unified AI infrastructure

Целевой модуль:

```text
app/ai/
    contracts.py
    schemas.py
    registry.py
    router.py
    service.py
    providers/
        openai.py
        openai_compatible.py
        gemini.py        # только если подтверждён Q3
```

Tasks:

```python
class AiTask(StrEnum):
    ACTIVITY_EXTRACTION = "ACTIVITY_EXTRACTION"
    READINESS_EXTRACTION = "READINESS_EXTRACTION"
    VOICE_TRANSCRIPTION = "VOICE_TRANSCRIPTION"
```

Отдельного coaching/wording task нет. Удалить runtime path `WordingProvider`,
`ProviderExecutor`, `set_external_processing()` и старые `LLM_*`. Historical reports и
provider metadata не удалять.

Routing: `AiTask → configured provider/model → strict task adapter`. Provider credentials
переиспользуются, model выбирается per task deployment config. Обычный Telegram user не
выбирает vendor/model.

Configuration family:

```text
AI_ENABLED=true
AI_DEFAULT_PROVIDER=OPENAI
AI_OPENAI_API_KEY=
AI_OPENAI_ENDPOINT=https://api.openai.com/v1
AI_GEMINI_API_KEY=
AI_GEMINI_ENDPOINT=
AI_TASK_ACTIVITY_EXTRACTION_PROVIDER=OPENAI
AI_TASK_ACTIVITY_EXTRACTION_MODEL=gpt-4.1-nano
AI_TASK_READINESS_EXTRACTION_PROVIDER=OPENAI
AI_TASK_READINESS_EXTRACTION_MODEL=gpt-4.1-nano
AI_TASK_VOICE_TRANSCRIPTION_PROVIDER=OPENAI
AI_TASK_VOICE_TRANSCRIPTION_MODEL=<deployment-value>
```

Обновить `.env.example`, `Settings`, production provisioning allowlist, deployment docs и
tests одновременно. Не оставлять старые и новые активные settings как два способа
настроить одно и то же.

### 8.1. Readiness extraction

LLM получает только текущий raw input, timezone, local date и strict schema instructions.
Не получает Activity history, goal, profile, Telegram identity, GPS, old readiness или
`facts_json`. Structured schema forbids unknown fields and валидируется вторично в
application service с точными ranges/cross-field constraints.

Любой AI result сначала становится DRAFT preview. Только user confirm создаёт typed
confirmed check-in. Provider failure/disabled/malformed result не закрывает manual path.

### 8.2. Voice

Default pipeline: `Telegram OGG/Opus bytes → transcription → readiness extraction`.
Domain use case видит только strict typed draft и не зависит от pipeline. Bytes
обрабатываются in-memory с size/type/timeout limits, не пишутся в filesystem/DB/logs.
Transcript существует только в памяти до structured extraction. Сохраняются SHA-256,
task/provider/model/request/status/error/timestamps без content.

### 8.3. Access, consent и audit

Новый consent version должен прямо перечислять readiness, sleep, fatigue, pain, voice,
external provider, data not sent, ephemeral content и local deterministic result. Manual
flow не требует consent/owner approval.

Отказ от consent не создаёт owner request, сразу оставляет доступным manual flow и не
показывает consent повторно внутри уже начатого manual draft. Согласие само по себе не
разрешает provider call без owner ALLOWED; revoke перепроверяется перед каждым вызовом.

Proposed migration (Q2): переименовать `AssistedAccess`/table в общий
`ExternalAiAccess`, сохранить существующий ALLOWED/REVOKED owner decision, но считать
activity-extraction-v1 consent устаревшим и потребовать новый user consent. Старый allow
не создаёт повторный owner request после re-consent.

Generalize `ExtractionAttempt` в task-aware audit. Existing rows мигрируются с task
`ACTIVITY_EXTRACTION`; readiness/voice attempts не требуют Activity draft FK. Limits,
timeout/retry и revoke проверяются непосредственно перед каждым provider call. Voice
pipeline из двух external calls создаёт две audit attempts; UI воспринимает их как один
logical input request.

## 9. Health Connect sleep prefill

Текущий Android/backend protocol сон не передаёт. MVP 1.0 добавляет optional slice, не
блокирующий core:

1. Android manifest и onboarding знают optional `READ_SLEEP`; он не входит в
   `basePermissions` и его deny не меняет state `READY` для run sync.
2. Android читает bounded recent `SleepSessionRecord`, не raw stages.
3. Отдельный authenticated endpoint, например `POST /health-connect/sync/sleep`, принимает
   external ID, start/end, duration, data origin и observed/synced timestamps.
4. Backend upsert/idempotency — по device + external ID; хранится typed `SleepSummary`,
   без stages/raw payload.
5. Proposed selection: longest plausible session, завершившаяся за последние 36 часов;
   более старая получает stale status и не предлагается как «последняя ночь» (Q2).
6. `/next` показывает prefill, source/freshness и позволяет изменить или удалить.
7. Только скопированные в confirmed check-in значения участвуют в engine; manual override
   имеет приоритет и меняет source на `MERGED`/`MANUAL`.
8. Health Connect не предоставляет универсальную quality metric: отсутствие explicit
   quality остаётся `null`, значение не выводится из stages/duration.

Поскольку companion sync остаётся ручным, бот не может разбудить телефон и запросить
свежий сон во время `/next`. Это должно быть явно указано в UX/known limitations.

## 10. Целевая раскладка модулей

Точные имена можно локально уточнить, сохраняя зависимости:

```text
app/goals/                    models, repository, service, schemas
app/readiness/                models, repository, service, schemas
app/coach/
    config.py                 frozen versioned coefficients
    facts.py                  RunFact + feature calculation
    quality.py                confidence
    readiness.py              score + hard signals
    candidates.py             generation/filter/scoring
    prescription.py           continuous rounding/bounds
    lifecycle.py              application orchestration/status transitions
    service.py                /next flow facade
app/ai/                       one registry/router/provider infrastructure
app/health_connect/           sleep DTO/repository/service extension
app/bot/next_handlers.py      thin goal/readiness/recommendation transport
app/bot/next_messages.py      presentation and keyboards
```

Не создавать interface «на будущее», кроме уже необходимых multiple providers и трёх
Activity writers. Pure domain не импортирует SQLAlchemy, aiogram, FastAPI или provider SDK.

## 11. ADR до кода

После ответов на вопросы добавить новые записи, не редактируя ADR-010/014:

1. **Adaptive `/next` и versioned deterministic pipeline** — goals, readiness, full
   recency-weighted history, safety/candidate/scoring, no LLM prescription, replacement
   старого coach-v2 поведения.
2. **Immutable reports + operational recommendation revisions** — statuses, one current,
   idempotency, goal/check-in/activity invalidation, backfill vs consumed.
3. **Unified AI access/registry + consent v2** — removal wording path, access migration,
   per-task routing, ephemeral text/image/voice and data minimization.
4. **Optional Health Connect sleep summary** — protocol, permission, freshness,
   provenance, manual confirmation and no raw stages.

Если все четыре решения остаются отдельными устойчивыми контрактами, оформить четыре ADR,
а не одну длинную запись.

## 12. Schema и migrations

Предпочтительная цепочка отдельных revisions от `20260711_0007`, совпадающая с
вертикальными slices:

1. `running_goals` и partial active-goal index;
2. `readiness_check_ins`, draft/phase constraints и active-draft index;
3. `next_run_recommendations`, revision links и one-current index;
4. rename/generalization external AI access/attempt audit и удаление legacy user wording
   flag;
5. `health_connect_sleep_summaries` и idempotency indexes.

Для каждой revision:

- sync SQLAlchemy model/migration enum values, names и lengths;
- working upgrade/downgrade;
- clean upgrade;
- previous-head → new head;
- downgrade до previous head → repeat upgrade;
- `alembic check` на PostgreSQL;
- SQLite tests не заменяют PostgreSQL partial index/check/FK verification.

Не удалять `TrainingPlan`, `PlannedWorkout` или historical `CoachReport`. Если
`external_processing_enabled` удаляется, downgrade восстанавливает колонку с безопасным
default, но не пытается восстановить потерянный runtime preference.

## 13. Пошаговый roadmap реализации

Каждый slice заканчивается formatter/lint + узкими тестами, review diff и логическим
коммитом. Следующий slice не маскирует failing gate предыдущего.

### Slice 0 — decision freeze

- получить ответы Q1–Q4;
- обновить этот документ и status;
- добавить четыре ADR;
- создать implementation branch от свежего `main`, повторно проверить CI/Alembic head.

Gate: documentation diff only, все продуктовые defaults однозначны.

### Slice 1 — goal vertical slice

- goal model/migration/repository/service;
- standard-distance completion contract;
- no-goal selection/change/achievement Telegram flow;
- goal service возвращает typed change/completion result; recommendation invalidation
  подключается атомарно в Slice 5 после появления lifecycle table;
- positive/negative/service/transport tests.

### Slice 2 — manual readiness vertical slice

- typed persistent draft/check-in model and migration;
- phase/status/constraints, preview/edit/clear/cancel/confirm;
- pain follow-up, illness, sleep manual values, availability, POST_RUN RPE;
- restart/repeated/stale/forged callback tests;
- manual flow works with AI/Health Connect disabled.

### Slice 3 — historical features and quality

- expanded RunFact/repository query with RPE;
- versioned config, recency weights, multi-window features, break/peak/history behavior;
- load proxy and multi-signal classification;
- confidence DTOs;
- pure deterministic tests, including full-year and six-month break fixtures.

### Slice 4 — candidates and continuous prescription

- athlete state/readiness score;
- candidates, safety filters, goal matrix, scoring;
- continuous duration/distance/intensity, rounding, short alternative;
- reason-code allowlist and REST text;
- property/boundary tests for monotonic safety bounds and deterministic ordering.

### Slice 5 — recommendation persistence/lifecycle

- recommendation/report migration/models/repository;
- provisional creation, current read, explicit revision, expiry;
- idempotent check-in confirmation;
- shared Activity-recorded lifecycle collaborator wired into manual/import/Health Connect;
- backfill superseded vs actual next run consumed tests.

### Slice 6 — `/next` provisional Telegram flow

- flow state DTO/facade;
- dedicated router/messages/keyboards;
- goal → method → manual preview → provisional;
- repeat-before-date actions;
- remove automatic next-workout rules from after-run report and add explicit CTA;
- transport tests assert thin handler and user-safe labels.

### Slice 7 — PRE_RUN confirmation

- pre-run draft and stage transition;
- unchanged/downgrade/postpone/REST/bounded-upgrade cases;
- safe-bound persistence in report;
- timezone/not-before/expiry boundaries and callback idempotency.

### Slice 8 — unified AI registry

- central contracts/registry/router/settings;
- migrate existing Activity extraction first with behavior parity;
- migrate access/audit data and consent v2;
- delete wording runtime and competing provider abstractions;
- fake-provider/task-routing/timeout/revoke/limits tests;
- update deployment provisioning before removing old env names.

### Slice 9 — AI readiness text/voice

- strict readiness schema/validation;
- text and voice ephemeral adapters;
- consent/owner/manual fallback UX;
- preview/edit/confirm convergence with manual contract;
- raw content/transcript non-persistence and failure tests.

### Slice 10 — Health Connect sleep

- optional Android permission/read/mapping/tests;
- backend endpoint/model/migration/idempotent service;
- freshness/provenance and editable merge;
- deny/missing/stale/manual override tests;
- Android unit, Spotless, lint and assemble gates.

### Slice 11 — cleanup, full gate and publication

- remove dead coach wording/settings/tests and ensure no second AI abstraction remains;
- update `.env.example`, README, deployment, manual checklist and agent handoff;
- run full local/PostgreSQL/Docker/Android gates;
- inspect secret/user/generated data and complete checklist/known limitations;
- logical commits, push only after explicit confirmation, open draft PR, verify GitHub CI.

## 14. Обязательные тестовые сценарии

### Determinism/time

- identical history/goal/check-in/config → identical result/fingerprint;
- Activity persistence order does not affect result;
- historical backfill takes chronological place but does not become consumed run;
- naive test adapter timestamps are normalized explicitly; DST/local date/not-before
  boundaries are covered;
- repeated callbacks and concurrent confirms create one current recommendation.

### Sparse/quality

- no runs, one, two;
- no HR/sleep/RPE;
- implausible metric ignored/lowered confidence;
- low confidence only conservative candidates;
- available time below safe meaningful workout.

### Long history/break

- regular year and recency decay;
- old 50 km/week followed by six-month gap does not restore old current capability;
- historical experience can affect confidence but not initial cap;
- recent successful series gradually raises cap;
- source/import ordering and backfill stable.

### Goals

- FIRST_5K exists and changes goal alignment;
- one active goal under concurrency;
- target duration constraints;
- finish threshold and longer Activity;
- time goal ignores long-run pace estimate;
- goal completion confirmation and goal change supersede recommendation.

### Readiness/safety

- high/low readiness, fatigue, soreness, external load, poor/missing sleep;
- pain absent/present/new/worsening/movement-affecting/severe;
- illness;
- optional motivation and availability;
- POST_RUN RPE only;
- draft never participates before confirm;
- REST text has no diagnosis.

### Lifecycle

- first provisional and repeat read without duplicate;
- readiness revision;
- PRE_RUN at not-before and after date;
- unchanged confirmation, downgrade, postpone, REST and bounded improvement;
- expiry;
- new actual run consumed; old backfill superseded; duplicate delivery no second change.

### AI/privacy

- disabled, consent declined/stale, access pending/revoked;
- timeout/retry, malformed/unknown/out-of-range structured result;
- provider/model task routing;
- transcription failure;
- raw text/image/audio/transcript not persisted/logged;
- provider receives no history/goal/identity/GPS;
- manual flow succeeds under every AI failure.

### Health Connect

- permission absent does not block RUN sync;
- no sleep, stale sleep, fresh sleep, duplicate sleep sync;
- provider quality remains null unless explicit;
- user edit/delete wins over prefill;
- raw stages not persisted;
- device revoke rejects next sleep sync.

## 15. Full verification gate

Перед draft PR выполнить команды из `AGENTS.md`:

```bash
cd backend
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy app
.venv/bin/pytest -q
```

На disposable PostgreSQL: clean upgrade, previous-head upgrade, downgrade/upgrade
roundtrip и `alembic check`. Затем Docker Compose build/up/migrate/health/ready/down.

Для Android:

```bash
cd android
./gradlew -PIDATEN_BASE_URL=https://idaten.keykomi.com/ spotlessCheck
./gradlew -PIDATEN_BASE_URL=https://idaten.keykomi.com/ testDebugUnitTest
./gradlew -PIDATEN_BASE_URL=https://idaten.keykomi.com/ assembleDebug
./gradlew -PIDATEN_BASE_URL=https://idaten.keykomi.com/ lintDebug
```

Невыполненная из-за среды команда записывается с точной ошибкой и impact; она не
отмечается успешной.

## 16. Acceptance criteria

1. `/next` полностью работает manual-only, без AI и Health Connect.
2. FIRST_5K и остальные bounded goal types доступны; active goal можно менять.
3. Goal history сохраняется, completion не происходит молча.
4. Manual readiness хранится typed и участвует только после preview confirm.
5. Pain/illness details представлены typed hard signals; значимая боль может дать REST.
6. Вся RUN history участвует через recency-weighted features; old form не становится
   current form после break.
7. Engine явно разделён на quality/features/state/candidates/safety/scoring/prescription.
8. Distance, duration, intensity и short alternative персонализированы и округлены.
9. Goal влияет на scoring, но не обходит safety.
10. Каждый calculation содержит calculator/rule version и immutable CoachReport.
11. Current recommendation persist/repeat не создаёт дубликат.
12. Provisional и confirmed revisions, supersede/expire/consume работают атомарно.
13. PRE_RUN ухудшение снижает/переносит/REST; улучшение не выходит за prior safe bounds.
14. New Activity invalidates current; backfill не считается выполнением.
15. `/coach` и `/plan` отсутствуют в UX; historical plan tables не удалены.
16. `/run` не считает recommendation и после save предлагает явный CTA.
17. Manual/AI readiness сходятся в один domain contract.
18. Единственный AI registry/task router обслуживает Activity, readiness и voice tasks.
19. LLM не получает run history/goal/GPS/Telegram identity и не генерирует prescription.
20. Consent v2 явно покрывает wellbeing/sleep/pain/voice и external provider.
21. Raw text/image/audio/transcript не сохраняются; audit не содержит secrets/content.
22. AI failure не ухудшает manual product.
23. Sleep — optional editable prefill с provenance/freshness; deny/missing/stale не блокирует.
24. Internal enum/reason/formula не показываются пользователю.
25. Telegram/API handlers остаются thin; privacy/consent/lifecycle проверяются backend.
26. Все schema changes имеют Alembic upgrade/downgrade и PostgreSQL roundtrip.
27. Ruff, strict mypy, full pytest, PostgreSQL/Alembic, Docker и Android gates проходят.
28. README, `.env.example`, deployment/manual checklist и agent handoff отражают факт.
29. Изменения находятся в отдельной ветке, опубликованы draft PR после полного gate.
30. PR перечисляет scope, ADR, migration/privacy behavior, checks и known limitations.

## 17. Не входит

- отдельный `/coach`, AI chat или AI-generated workout;
- долгосрочный календарный plan и обязательные дни недели;
- non-running prescriptions/cross-training;
- interval prescriptions;
- diagnosis, treatment или обещание результата;
- seasonality, ML/RL, vector DB, embeddings;
- push/background reminders;
- background Health Connect sync;
- automatic exact adherence inference без надёжных workout samples;
- model/vendor selection обычным Telegram user;
- удаление historical plan/report rows.

## 18. Вопросы до freeze

### Q1 — минимальный manual check-in

Исходный быстрый flow не собирает одновременно `general_fatigue`, `motivation` и
`illness_symptoms`, хотя engine должен их учитывать. Proposed default: fatigue и illness
сделать обязательными, motivation — optional и редактируемой в preview. Подтвердить либо
сделать motivation отдельным обязательным вопросом.

### Q2 — sleep freshness и access migration

Proposed defaults: optional Android `READ_SLEEP`, ручной отдельный sleep sync, выбирать
longest plausible session с end не старше 36 часов; owner ALLOWED/REVOKED переносить из
`AssistedAccess`, но consent v1 считать stale и запросить consent v2. Подтвердить freshness
и сохранение старого owner decision.

### Q3 — providers MVP 1.0

Нужно подтвердить обязательный vendor scope. Proposed default: production-ready OpenAI и
generic OpenAI-compatible adapters; native Gemini включить в этот же MVP только если он
реально нужен deployment. Task registry при этом сразу поддерживает provider-specific
capabilities и разные models per task.

### Q4 — conservative safety/lifecycle defaults

Proposed defaults: любые `illness_symptoms`, movement-affecting/worsening pain или pain
severity `>=6` возвращают REST; current recommendation valid 72 часа после `not_before`;
finish goal достигается с 98% distance, time goal — только фактической Activity ±2%.
Подтвердить эти границы либо задать другие.

После ответов заменить proposed wording на принятые решения и сменить status документа на
`approved for implementation`.
