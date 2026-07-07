# MVP 0.6 — Android onboarding, signed releases и Kubernetes deployment

## Цель

Довести существующий Health Connect companion до устанавливаемого пользовательского
сценария и развернуть Idaten в уже работающей инфраструктуре `keykomi` без отдельного
Docker Compose stack.

Результат итерации:

- пользователь скачивает подписанный `Idaten` APK из GitHub Releases и может обновлять
  его поверх предыдущей версии;
- приложение проверяет доступность Health Connect, предлагает установить/обновить его,
  запрашивает разрешения и ведет пользователя через существующий link/sync flow;
- GitHub Actions публикует APK и immutable backend image;
- backend работает в существующем k3s за HTTPS на `https://idaten.keykomi.com`;
- production использует существующие Traefik, cert-manager и PostgreSQL, но отдельные
  namespace, database, database user, Kubernetes Secret и storage Idaten.

## Обязательный порядок работы агента

1. Прочитать `AGENTS.md`, `docs/architecture-rules.md`, `docs/decision-log.md`,
   `docs/agent-handoff.md`, этот файл, `README.md`, `docs/deployment.md`, Android-код,
   CI и deployment-конфигурацию.
2. Проверить `git status -sb`, remote default branch, открытые PR и последний CI `main`.
3. Начать реализацию в новой ветке от свежего `origin/main`, например
   `codex/mvp-0.6-release-deployment`. Не продолжать удаленную ветку MVP 0.5.
4. До изменения deployment/release contract добавить новую, не переписывающую старые
   записи ADR в `docs/decision-log.md`. ADR должна зафиксировать k3s, GHCR, signed APK,
   один production backend replica и использование отдельной БД в существующем
   PostgreSQL instance.
5. Сначала сопоставить acceptance criteria с текущим кодом и тестами. Не менять coach,
   analytics, privacy/source eligibility и ingestion без воспроизводимой необходимости.
6. Реализовать Android flow, release pipeline и Kubernetes deployment отдельными
   логическими коммитами. Затем обновить README, deployment guide, roadmap, checklist и
   handoff фактическими командами и ограничениями.
7. Push и draft PR делать только после полного локального gate. Release/tag и production
   deployment выполнять только из merge commit актуального `main`, а не из feature branch.

## Зафиксированное состояние инфраструктуры

Перед реализацией агент обязан повторно проверить факты, а не считать их вечными:

- SSH alias: `keykomi`;
- Ubuntu 22.04, 4 CPU, около 3.8 GiB RAM, 4 GiB swap;
- k3s активен, default storage class — `local-path`;
- Traefik уже является ingress controller;
- cert-manager имеет готовый `ClusterIssuer` `letsencrypt-prod`;
- PostgreSQL 16 уже работает как `StatefulSet/prod/postgres`, service DNS внутри
  кластера — `postgres.prod.svc.cluster.local:5432`;
- production certificate должен выпускаться cert-manager, а не host `certbot.timer`;
- `idaten.keykomi.com` создан у DNS-провайдера, но перед release необходимо проверить
  публичное A/AAAA-разрешение и соответствие IP ingress;
- сервер уже нагружен другими workloads, поэтому не запускать второй Compose stack,
  отдельный k3s control plane или второй PostgreSQL без доказанной необходимости.

Команды аудита read-only:

```bash
ssh keykomi 'free -h; df -h /; sudo k3s kubectl top nodes; sudo k3s kubectl get pods -A'
dig +short idaten.keykomi.com A
ssh keykomi 'sudo k3s kubectl get clusterissuer,certificate,ingress -A'
```

Не выводить Kubernetes Secret values, `.env`, токены, пароли или device credentials.

## Android: Health Connect onboarding

Сохраняется существующий контракт MVP 0.4: Android читает данные локально, устройство
привязывается одноразовым `/link` code, device token хранится через Android Keystore,
sync выполняется вручную, а backend сохраняет Activity как `PRIVATE`.

### Состояния и UI

Приложение должно явно и детерминированно отображать:

1. `checking` — идет проверка provider/permissions;
2. `provider update required` — Health Connect отсутствует или требует обновления;
3. `unsupported` — устройство не поддерживается;
4. `permissions required` — provider доступен, но не все базовые read permissions выданы;
5. `ready` — provider доступен и базовые permissions выданы;
6. `linked`/`not linked`, status backend и понятную ошибку сети отдельно от Health Connect.

Нельзя запускать permission contract, чтение records или route contract, пока provider
недоступен. Кнопки должны быть disabled/скрыты в несовместимом состоянии, а повторный tap
и возврат из внешнего Activity не должны создавать конкурирующие операции.

### Установка и обновление provider

- Использовать `HealthConnectClient.getSdkStatus` и официальный provider package
  `com.google.android.apps.healthdata`/SDK constant.
- На Android 9–13 при `SDK_UNAVAILABLE_PROVIDER_UPDATE_REQUIRED` показать действие
  «Установить или обновить Health Connect», открыть Google Play через `market://` и иметь
  HTTPS fallback, если Play Store intent недоступен.
- На Android 14+ учитывать, что Health Connect является system module: направлять в
  корректные system settings/update entry points, а не обещать установку отдельного APK.
- При полном `SDK_UNAVAILABLE` показать поддерживаемое объяснение без crash-loop.
- После возврата приложения в foreground повторно проверить provider и permissions.
- Добавить accessibility labels и пользовательские тексты на русском; внутренние enum и
  state остаются стабильными и не зависят от текста UI.

Ориентироваться на актуальные официальные Android guides, а не на память:

- <https://developer.android.com/health-and-fitness/health-connect/availability>
- <https://developer.android.com/health-and-fitness/health-connect/get-started>
- <https://developer.android.com/health-and-fitness/health-connect/design/onboarding>

Health Connect требует Android 9+ и Google Play Services; work profile и устройства без
Google Play могут оставаться unsupported. Это должно быть отражено в UI и документации.

### Permissions и link/sync flow

- Запрашивать только реально читаемые MVP data types: exercise session, distance, HR,
  speed, cadence, elevation. Route остается отдельным per-session consent flow.
- До открытия системного permission dialog коротко объяснить, какие данные и зачем нужны.
- Отказ не блокирует link screen и не приводит к повторному автоматическому запросу.
- После выдачи permissions пользователь выполняет `/link` в private Telegram chat, вводит
  one-time code, видит status, загружает latest runs и запускает Manual Sync.
- Существующие token revoke, missing optional records, duplicate external ID и private
  outbox semantics не менять.
- Не добавлять background sync/WorkManager в этой итерации.

### Android tests

Добавить unit/UI-state tests минимум на:

- mapping всех SDK availability states;
- install/update action и HTTPS fallback при отсутствии Play Store handler;
- Android 14+ system path;
- отсутствие permission request/read при unavailable provider;
- refresh после возврата в foreground;
- grant, partial grant, deny и повторный ручной запрос;
- сохранение существующего link/status/latest runs/manual sync flow;
- route consent остается отдельным и не попадает в базовый permission request;
- network/backend error не маскируется под ошибку Health Connect.

Instrumentation test на реальном provider допустимо оставить manual acceptance test, но
unit tests, `spotlessCheck`, `testDebugUnitTest`, `assembleDebug`, `assembleRelease` и
`lintDebug` обязательны в CI.

## Подписанный APK и GitHub Releases

### Versioning и signing

- Поднять Android `versionName` до `0.6.0`, увеличить `versionCode`; backend/release docs
  должны использовать согласованную версию.
- Release APK должен быть подписан постоянным release keystore. Debug key и новый key на
  каждый CI run запрещены: иначе APK нельзя обновить поверх установленной версии.
- Keystore создается и резервируется вне репозитория. Потеря keystore или passwords
  означает потерю update path для установленного package name.
- CI обязан выполнить `apksigner verify` и сформировать SHA-256 checksum APK.
- APK не должен содержать Telegram token, DB credentials, pepper, import token, signing
  passwords или private key. `IDATEN_BASE_URL` секретом не является.

### GitHub configuration, которую агент должен запросить/настроить

Repository Actions secrets:

- `ANDROID_RELEASE_KEYSTORE_BASE64` — base64 постоянного `.jks`/`.keystore`;
- `ANDROID_RELEASE_KEY_ALIAS`;
- `ANDROID_RELEASE_KEYSTORE_PASSWORD`;
- `ANDROID_RELEASE_KEY_PASSWORD`.

Repository Actions variable:

- `IDATEN_BASE_URL=https://idaten.keykomi.com/`.

Отдельный PAT/GitHub token не нужен: workflow использует scoped `${{ github.token }}`.
Не добавлять SSH private key сервера в GitHub Secrets в MVP 0.6, поскольку production
deploy остается явной операцией через локальный `ssh keykomi`, а не автоматическим CD.

Если signing secrets отсутствуют, агент не публикует unsigned/fresh-debug-key release.
Он дает пользователю точные команды создания/backup keystore и `gh secret set`, не
печатает passwords и явно фиксирует release как blocker до безопасной настройки.

### Release workflow

Добавить отдельный `.github/workflows/release.yml`:

- trigger — tag `v*` и при необходимости `workflow_dispatch` только для dry-run;
- release tag должен указывать на merge commit, входящий в `main`; workflow это проверяет;
- permissions: только необходимые `contents: write`, `packages: write`;
- повторить обязательный backend/Android quality gate либо зависеть от доказуемо зеленого
  commit, не публиковать artifact после failed checks;
- собрать signed release APK с `IDATEN_BASE_URL`;
- проверить подпись, посчитать checksum, дать artifact имя `idaten-v0.6.0.apk`;
- создать non-draft GitHub Release с generated notes, APK и checksum;
- build/push backend image в `ghcr.io/mattoyuzuru/idaten-backend` с version tag и immutable
  commit SHA tag; production manifest использует immutable tag или digest;
- не передавать secrets через command-line arguments, artifacts или verbose logs;
- rerun того же tag не должен молча перезаписывать другой binary.

После первого push package сделать public либо документированно создать read-only
`imagePullSecret`. Для публичного репозитория предпочтителен public GHCR package, чтобы
production cluster не хранил лишний registry credential.

## Kubernetes deployment на keykomi

### Deployment model

Добавить воспроизводимые manifests (Kustomize допустим, Helm без необходимости не вводить):

- namespace `idaten`;
- `Deployment` backend, ровно `replicas: 1`;
- strategy `Recreate`, чтобы Telegram long polling и hourly job не работали одновременно
  в двух pod во время rollout;
- `ClusterIP Service` на backend port 8000;
- PVC через `local-path`, mounted в `/data/idaten`; размер выбрать явно и описать;
- Traefik `Ingress` для `idaten.keykomi.com`;
- cert-manager annotation на `letsencrypt-prod` и отдельный TLS Secret, например
  `idaten-keykomi-com-tls`;
- startup/readiness/liveness probes на `/ready` и `/health` с разумными timeout/failure
  thresholds, учитывающими Alembic startup;
- non-root security context, запрещенный privilege escalation и минимальные capabilities;
- resource requests/limits, соответствующие малому VPS. Начальная цель для backend:
  request 128 MiB RAM/50m CPU, limit 384 MiB RAM/500m CPU; после deploy проверить metrics
  и скорректировать по измерениям.

Не открывать host port 8000 и не создавать LoadBalancer/NodePort для backend. Публичный
вход только через Traefik HTTPS. HTTP должен редиректить на HTTPS.

### PostgreSQL

Переиспользовать существующий PostgreSQL instance, но не существующие application DB/user:

- создать отдельные database `idaten` и role `idaten` с минимальными правами;
- не менять `prod/mnema-secrets`, mnema database/schema или существующие grants;
- создать отдельный Kubernetes Secret в namespace `idaten`;
- пароль взять из локального secret source только во время provisioning, не коммитить и
  не печатать;
- если пароль содержит URL-reserved characters, percent-encode только password component
  при формировании `DATABASE_URL`; не менять сам пароль незаметно;
- перед первой публикацией выполнить Alembic clean upgrade/check в новой БД;
- зафиксировать backup/restore команды отдельно для БД Idaten.

Не запускать второй PostgreSQL pod только ради Idaten без измеримой причины. Если reuse
существующего instance невозможен, агент останавливается и описывает blocker вместо
самовольной смены deployment strategy.

### Runtime secrets

Локальный input-файл пользователя: `~/.running_bot_tokens`. Его нельзя source-ить,
копировать в repo/image/ConfigMap или выводить целиком. Перед использованием:

```bash
chmod 600 ~/.running_bot_tokens
```

Ожидаемые server-side values:

- `TELEGRAM_BOT_TOKEN` — обязателен;
- `POSTGRES_PASSWORD` — обязателен для отдельной role;
- `HEALTH_CONNECT_SECURITY_PEPPER` — обязателен, постоянный, минимум 32 random bytes;
- `IMPORT_API_TOKEN` — optional; при отсутствии HTTP import API остается disabled;
- LLM secrets не требуются, production default — `LLM_PROVIDER=NONE`.

На момент подготовки спецификации первые три values присутствовали и прошли безопасную
проверку формата/длины без вывода значений; `IMPORT_API_TOKEN` отсутствовал. Пароль БД
содержит URL-reserved characters и требует корректного percent-encoding в `DATABASE_URL`.
Агент обязан повторить проверку и сообщить только names/status, никогда values.

Secret создавать декларативно через безопасный local/STDIN workflow или server-side
команду без попадания values в shell history/process list. Не хранить plaintext Secret
manifest в рабочем дереве. Проверить, что pod env и application logs не выводят secrets.

### Deployment и rollback

Порядок production rollout:

1. Убедиться, что tag относится к зеленому merge commit `main`.
2. Проверить GHCR image digest и release APK checksum.
3. Provision isolated DB/user и Kubernetes Secret.
4. Server-side dry-run manifests, затем apply namespace/PVC/service/ingress/deployment.
5. Дождаться Alembic upgrade и readiness; один pod должен быть Ready.
6. Проверить certificate `Ready=True`, HTTPS chain/hostname и HTTP→HTTPS redirect.
7. Проверить `/health`, `/ready`, Telegram `/start`, `/link`, link complete и status без
   публикации token/health payload в терминал или логи.
8. Зафиксировать deployed image digest и команду rollback к предыдущему digest.

Удаление namespace/PVC запрещено как способ rollback. Rollback приложения не должен
автоматически делать Alembic downgrade; совместимость и порядок отдельно оцениваются до
релиза.

## Проверки и release gate

### Backend

```bash
cd backend
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy app
.venv/bin/pytest -q
DATABASE_URL=<temporary-postgres-url> .venv/bin/alembic upgrade head
DATABASE_URL=<temporary-postgres-url> .venv/bin/alembic check
```

### Android

```bash
cd android
./gradlew -PIDATEN_BASE_URL=https://idaten.keykomi.com/ spotlessCheck
./gradlew -PIDATEN_BASE_URL=https://idaten.keykomi.com/ testDebugUnitTest
./gradlew -PIDATEN_BASE_URL=https://idaten.keykomi.com/ assembleDebug
./gradlew -PIDATEN_BASE_URL=https://idaten.keykomi.com/ assembleRelease
./gradlew -PIDATEN_BASE_URL=https://idaten.keykomi.com/ lintDebug
```

### Kubernetes/release

- manifests проходят client/server dry-run;
- только один backend pod Ready, restart count стабилен;
- requests/limits видны в pod spec, memory pressure не ухудшает существующие workloads;
- certificate `Ready=True`, `curl --fail https://idaten.keykomi.com/health` и `/ready`;
- GitHub Release существует, APK и checksum скачиваются без GitHub credentials;
- `apksigner verify` проходит для скачанного release asset;
- GHCR image соответствует release commit/digest;
- чистая установка APK и обновление поверх предыдущего APK проверены на устройстве;
- реальный device acceptance: provider absent/update path либо документированный substitute,
  permission grant/deny, `/link`, latest runs, manual sync, private Telegram report.

Если физическое устройство доступно только пользователю, агент публикует release лишь
после автоматического gate и оставляет точный manual checklist. Итерация не считается
полностью принятой до результата пользовательского device test; это допустимо оформить
как явный acceptance blocker, а не как автоматически пройденную проверку.

## Acceptance criteria

1. На Android 9–13 отсутствующий/устаревший provider дает рабочую кнопку Google Play с
   fallback; приложение не падает и повторно проверяет состояние после возврата.
2. На Android 14+ приложение корректно использует system Health Connect/settings flow.
3. Permission request возможен только при доступном provider; grant/deny/partial grant
   отображаются корректно и не ломают link screen.
4. Существующий `/link` → encrypted device token → status → latest runs → Manual Sync
   работает, Activity остается PRIVATE, route требует отдельного consent.
5. Tag `v0.6.0` из зеленого `main` создает подписанный GitHub Release APK, checksum и
   immutable GHCR backend image; APK можно обновлять той же подписью.
6. Production работает в существующем k3s на `https://idaten.keykomi.com`, certificate
   выпускает/продлевает cert-manager через `letsencrypt-prod`.
7. Backend имеет один replica, не публикует port 8000 напрямую и использует отдельную БД,
   role, Kubernetes Secret и PVC без второго PostgreSQL/Compose stack.
8. Secrets отсутствуют в git diff/history, APK, image layers, Actions artifacts и logs;
   локальный secret-файл имеет mode `0600`.
9. Full backend/Android CI, PostgreSQL/Alembic, release artifact и Kubernetes smoke gates
   пройдены либо точный blocker записан в PR и checklist.
10. README/deployment/handoff позволяют повторить update, rollback, backup/restore и
    установку APK без устных знаний автора.

## Не входит

- Google Play publication и Play Console Health declaration;
- автоматический CD из GitHub Actions по SSH/kubeconfig;
- WorkManager/background sync;
- iOS companion;
- несколько backend replicas или отдельный worker;
- новый PostgreSQL instance, Redis, MinIO/S3 или observability stack;
- изменение coach/analytics/group privacy contracts;
- автоматическое in-app обновление APK.

## Checklist

- [x] ADR о k3s/GHCR/signed release/existing PostgreSQL добавлена.
- [x] Health Connect install/update/unsupported/permission onboarding реализован.
- [x] Android onboarding и regression tests добавлены.
- [x] Постоянный signing key настроен и безопасно зарезервирован.
- [ ] Release workflow публикует signed APK, checksum и GHCR image.
- [x] Kubernetes manifests и secret-safe provisioning документированы.
- [ ] Isolated Idaten DB/user созданы в существующем PostgreSQL.
- [ ] DNS, TLS, probes, PVC, limits, single-replica rollout и rollback проверены.
- [ ] Реальный APK скачан из GitHub Release, установлен и пройден manual device flow.
- [ ] Full CI и production smoke прошли.
- [ ] README, roadmap, deployment guide и handoff обновлены; draft PR опубликован.

## Known limitations, которые должны сохраниться после MVP 0.6

- Sync остается foreground/manual.
- Sideloaded APK обновляется ручной загрузкой следующего подписанного release.
- Health Connect зависит от Android 9+ и Google Play Services; work profile и некоторые
  устройства без Google Play не поддерживаются.
- Local-path PVC привязан к одному VPS/node; backup обязателен, но HA storage не вводится.
- Один backend replica означает короткий downtime при `Recreate` rollout, зато исключает
  двойной Telegram polling/job execution.
- Cert-manager продлевает Kubernetes TLS certificate автоматически; host certbot не
  управляет ingress certificate Idaten.
