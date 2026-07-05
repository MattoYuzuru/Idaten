# AGENTS.md — правила разработки Idaten

Этот файл задает устойчивые конвенции для любых итераций. Спецификация конкретного
релиза находится в `docs/iterations/mvp-X.Y.md`; она определяет scope, но не отменяет
архитектурные и quality-инварианты ниже.

## 1. Обязательный контекст перед изменениями

Перед началом работы прочитай в указанном порядке:

1. `docs/architecture-rules.md`;
2. `docs/decision-log.md`;
3. `docs/agent-handoff.md`;
4. спецификацию только текущей итерации в `docs/iterations/`;
5. `README.md`, `docs/deployment.md` и затрагиваемые код/тесты.

Roadmap и спецификации будущих итераций дают контекст, но не разрешают расширять scope.
Проверь текущую ветку, `git status -sb`, удаленный default branch и состояние предыдущего
PR/CI. Работай в отдельной ветке от актуального `main`; не переписывай рабочий фундамент
без воспроизводимой причины.

## 2. Архитектура и направление зависимостей

Сохраняй направление зависимостей:

```text
Telegram / HTTP / jobs
        -> application services
        -> repositories + domain calculations
        -> SQLAlchemy / external adapters
```

- Handler/router — тонкий transport adapter: разобрать вход, вызвать use case,
  преобразовать ожидаемую ошибку и отформатировать ответ.
- В handlers/routers запрещены SQL, транзакции, privacy decisions, агрегаты, leaderboard,
  streaks, coach rules и вычисление метрик.
- Application service владеет use case, authorization/privacy policy и границей
  транзакции. Сервис принимает доменные DTO/простые значения, а не Telegram objects.
- Repository инкапсулирует SQLAlchemy queries и persistence. Не возвращай наружу сырой
  `Row`, если у результата есть доменный смысл: используй dataclass/Pydantic DTO.
- Детерминированные расчеты держи чистыми функциями в domain/analytics-модуле. Они не
  должны зависеть от bot, FastAPI, session или внешней сети.
- Интеграции реализуют доменный контракт; домен не импортирует SDK интеграции.
- Общие зависимости собираются в composition root (`app/services.py`, runtime/lifespan),
  а не создаются внутри handlers.

## 3. Моделирование и чистый код

- Python >= 3.12, полная типизация, `mypy --strict`; не скрывай ошибки через `Any`,
  `cast` или `# type: ignore` без локального обоснования.
- Имена отражают бизнес-смысл. Функция выполняет одну задачу; ранние возвраты
  предпочтительнее глубокой вложенности.
- Не дублируй policy checks между transport-слоями. Один backend-сервис должен быть
  источником истины для authorization/privacy.
- Ожидаемые пользовательские ошибки выражай отдельными исключениями или result DTO;
  не перехватывай общий `Exception` без добавления контекста и повторного выброса.
- Enum-значения стабильны и сохраняются строками. Внутренние ID — UUID. Время —
  timezone-aware; расстояние — целые метры, длительность — целые секунды.
- Не вводи абстракцию «на будущее». Выделяй интерфейс, новый модуль или dependency,
  когда этого требует текущий use case, тестируемость или уже существующая вторая
  реализация.
- Комментарии объясняют причины и инварианты, а не пересказывают код. TODO должен иметь
  конкретный scope и не заменять обязательную реализацию текущей итерации.

## 4. Privacy и безопасность данных

- Новая activity по умолчанию `PRIVATE`.
- Публикация требует явного opt-in. Callback/кнопка/UI не являются разрешением сами по
  себе: backend повторно проверяет membership, sharing preference, visibility, source
  policy и soft-delete непосредственно перед публикацией.
- Leaderboard, group stats и streaks используют тот же backend eligibility contract и
  не обходят его отдельным запросом.
- Route/GPS, HR, raw payload, exact start time, токены и секреты не попадают в group
  messages, внешние модели и логи без отдельного разрешения спецификации.
- Любое privacy-sensitive изменение требует положительных и отрицательных тестов:
  отсутствие opt-in, `NONE`, private activity, запрещенный source, non-member,
  soft-deleted activity и повторная доставка, если применимо.

## 5. База данных и миграции

- Production schema меняется только новой Alembic revision. Не используй
  `Base.metadata.create_all()` вне тестового adapter-контекста.
- Сначала спроектируй constraints, foreign keys, delete behavior, unique/index rules и
  enum storage, затем синхронно измени SQLAlchemy models и migration.
- Миграция должна иметь рабочие `upgrade()` и `downgrade()` и применяться от чистой БД
  и от предыдущего `head`.
- Тесты на SQLite допустимы для быстрого контура, но PostgreSQL-специфичное поведение и
  schema drift проверяются Alembic/PostgreSQL и Docker smoke test.
- Для webhook/callback/job обеспечивай идемпотентность constraint-ом и обработкой на
  уровне use case, а не только предварительным `SELECT`.

## 6. Тестовая стратегия

Добавляй тест на каждый новый use case и регрессионный тест на каждый исправленный bug.
Предпочтительные уровни:

- pure unit tests — parsing, metrics, eligibility/policy и форматирование;
- service/repository tests — транзакции, permissions, queries и отрицательные сценарии;
- transport tests — только wiring, parsing и отображение service result/error;
- PostgreSQL/Alembic smoke — ограничения и соответствие production schema;
- Docker smoke — сборка, миграция, readiness и базовый runtime path.

Тест должен проверять observable behavior, а не внутреннюю последовательность вызовов.
Данные теста должны явно показывать, почему запись eligible/ineligible. Для времени
фиксируй timezone-aware timestamp; не полагайся на текущую дату без необходимости.

## 7. Рабочий цикл изменения

1. Сопоставь acceptance criteria с существующим кодом и тестами.
2. Если меняется устойчивый архитектурный контракт, schema/privacy/deployment strategy,
   сначала добавь новую ADR-запись в `docs/decision-log.md`. Не редактируй старые ADR.
3. Реализуй минимальный вертикальный срез текущего scope: model/migration -> repository
   -> service/policy -> transport -> tests/docs.
4. После локального среза запусти форматирование и узкие тесты затронутого модуля.
5. Перед коммитом проверь diff и отсутствие секретов/generated/user data.
6. Делай небольшие логические коммиты в работающем состоянии. Не смешивай массовый
   рефакторинг, feature, migration и документацию, если их можно независимо проверить.
7. Перед PR обнови checklist и known limitations спецификации итерации, README/handoff
   только если фактический запуск или передача работы изменились.

## 8. Команды проверок

Из корня репозитория подготовь окружение один раз:

```bash
python3.12 -m venv backend/.venv
backend/.venv/bin/pip install -e 'backend[dev]'
```

Во время разработки запускай быстрый feedback loop:

```bash
cd backend
.venv/bin/ruff format app tests
.venv/bin/ruff check app tests
.venv/bin/pytest -q tests/<затронутый_файл>.py
```

Перед каждым PR обязательны все проверки CI:

```bash
cd backend
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy app
.venv/bin/pytest -q
DATABASE_URL=postgresql+asyncpg://idaten:idaten@localhost:5432/idaten \
  .venv/bin/alembic upgrade head
DATABASE_URL=postgresql+asyncpg://idaten:idaten@localhost:5432/idaten \
  .venv/bin/alembic check
```

Для проверки миграций используй отдельную/одноразовую PostgreSQL БД. Затем из корня:

```bash
docker compose build
docker compose up -d
docker compose exec backend alembic upgrade head
curl --fail http://localhost:8000/health
curl --fail http://localhost:8000/ready
docker compose down -v
```

Если среда не позволяет выполнить проверку, не отмечай ее успешной: запиши точную
команду, ошибку и влияние в PR/known limitations.

## 9. Git и PR gate

- Перед staging просмотри `git status -sb` и `git diff`; не добавляй чужие или
  несвязанные изменения.
- Не используй destructive history operations для обхода конфликтов или failing tests.
- Push делай только после полного локального gate. PR по умолчанию draft.
- PR описывает scope, причины, пользовательский эффект, migration/privacy behavior,
  выполненные команды и известные ограничения.
- После push проверь CI. Working tree должен быть чистым; в handoff перечисли ветку,
  коммиты, PR, проверки, known limitations и следующий документ для чтения.

## 10. Definition of Done

Итерация завершена только когда acceptance criteria реализованы или явно обозначены как
blocker, schema соответствует моделям, отрицательные privacy-сценарии покрыты, transport
не содержит бизнес-логики, документация воспроизводима, все обязательные проверки
пройдены, изменения опубликованы в draft PR, а рабочее дерево чистое.
