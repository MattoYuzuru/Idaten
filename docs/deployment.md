# Локальный запуск и deployment MVP 0.7

## Локальный backend

Требуются Python 3.12, Docker с Compose plugin и Telegram bot token. Создайте `.env` из
`.env.example`; production values использовать локально не нужно.

```bash
python3.12 -m venv backend/.venv
backend/.venv/bin/pip install -e 'backend[dev]'
docker compose up --build -d
docker compose ps
curl --fail http://localhost:8000/health
curl --fail http://localhost:8000/ready
```

Backend применяет `alembic upgrade head` перед FastAPI и Telegram polling. Одновременно
должен работать только один polling instance. Raw activity artifacts хранятся в
`${STORAGE_PATH:-/data/idaten}`. Health Connect Activity всегда создается `PRIVATE`, а
route остается отдельным per-session consent.

## Android companion

Требуются JDK 21, Android SDK Platform 36 и Build Tools 36.0.0. Health Connect работает
на Android 9+ с Google Play Services; work profile и устройства без Google Play могут
быть unsupported. На Android 9–13 приложение открывает Google Play и использует HTTPS
fallback, на Android 14+ — системные настройки Health Connect.

```bash
cd android
./gradlew -PIDATEN_BASE_URL=https://idaten.keykomi.com/ spotlessCheck
./gradlew -PIDATEN_BASE_URL=https://idaten.keykomi.com/ testDebugUnitTest
./gradlew -PIDATEN_BASE_URL=https://idaten.keykomi.com/ assembleDebug
./gradlew -PIDATEN_BASE_URL=https://idaten.keykomi.com/ lintDebug
```

Release build требует четыре environment variables и путь к постоянному keystore:

```text
ANDROID_RELEASE_KEYSTORE_PATH
ANDROID_RELEASE_KEY_ALIAS
ANDROID_RELEASE_KEYSTORE_PASSWORD
ANDROID_RELEASE_KEY_PASSWORD
```

Keystore и recovery credentials хранятся и резервируются вне repository с mode `0600`.
Не создавайте новый key для следующей версии: APK с другой подписью нельзя установить как
update существующего package `dev.idaten.companion`.

## GitHub configuration и release

Actions secrets:

```text
ANDROID_RELEASE_KEYSTORE_BASE64
ANDROID_RELEASE_KEY_ALIAS
ANDROID_RELEASE_KEYSTORE_PASSWORD
ANDROID_RELEASE_KEY_PASSWORD
```

Actions variable: `IDATEN_BASE_URL=https://idaten.keykomi.com/`. Workflow
`.github/workflows/release.yml` запускается только tag `v*`, проверяет, что commit входит
в `origin/main`, повторяет backend/Android gates, верифицирует подпись и публикует:

- `idaten-v0.7.0.apk` и `idaten-v0.7.0.apk.sha256` в GitHub Release;
- `ghcr.io/mattoyuzuru/idaten-backend:v0.7.0`;
- `ghcr.io/mattoyuzuru/idaten-backend:sha-<merge-commit>`.

Tag создается только после merge зеленого PR и явного production confirmation:

```bash
git switch main
git pull --ff-only origin main
git tag -a v0.7.0 -m 'Idaten v0.7.0'
git push origin v0.7.0
gh run watch --exit-status
```

Workflow не перезаписывает существующий Release: повторный `gh release create` завершится
ошибкой. После первого push package должен быть public. Проверка artifact:

```bash
mkdir -p /tmp/idaten-v0.7.0 && cd /tmp/idaten-v0.7.0
gh release download v0.7.0 -R MattoYuzuru/Idaten
shasum -a 256 --check idaten-v0.7.0.apk.sha256
"$ANDROID_HOME/build-tools/36.0.0/apksigner" verify --verbose idaten-v0.7.0.apk
docker buildx imagetools inspect ghcr.io/mattoyuzuru/idaten-backend:v0.7.0
```

APK, checksum и public GHCR manifest дополнительно скачиваются без GitHub credentials.

## Production infrastructure audit

Production использует SSH alias `keykomi`, существующие k3s, Traefik, cert-manager
`letsencrypt-prod` и PostgreSQL service
`postgres.prod.svc.cluster.local:5432`. Второй Compose/PostgreSQL не запускается.

```bash
ssh keykomi 'free -h; df -h /; sudo k3s kubectl top nodes; sudo k3s kubectl get pods -A'
ssh keykomi 'sudo k3s kubectl get clusterissuer,certificate,ingress -A'
dig +short idaten.keykomi.com A
dig +short idaten.keykomi.com AAAA
```

Ожидается A record, совпадающий с Traefik ingress IP. AAAA допустимо не иметь; ошибочный
AAAA необходимо исправить до certificate/smoke.

## Secret-safe provisioning

`~/.running_bot_tokens` должен иметь mode `0600` и assignments для
`TELEGRAM_BOT_TOKEN`, `POSTGRES_PASSWORD`, `HEALTH_CONNECT_SECURITY_PEPPER` (минимум
32 bytes), опционально `IMPORT_API_TOKEN`. Файл нельзя source-ить. Helper разбирает
только allowlisted keys, URL-encodes только password component `DATABASE_URL` и не
выводит values:

```bash
chmod 600 ~/.running_bot_tokens
./deploy/provision-production.py
# После production confirmation:
./deploy/provision-production.py --apply
```

`--apply` идемпотентно создает/обновляет только role `idaten`, database `idaten` и Secret
`idaten/idaten-runtime`. Он не читает и не меняет `prod/mnema-secrets`, mnema database
или grants. Runtime использует `LLM_PROVIDER=NONE`.

## Kubernetes dry-run и rollout

Manifests находятся в `deploy/kubernetes`: namespace, 5 GiB `local-path` PVC,
single-replica `Recreate` Deployment, ClusterIP Service, HTTP redirect middleware,
Traefik HTTPS Ingress и cert-manager TLS Secret. Backend имеет 50m/128Mi requests,
500m/384Mi limits, non-root/read-only security context и startup/readiness/liveness
probes. Host port, NodePort и LoadBalancer не создаются.

Получите digest release image и не используйте mutable tag для production:

```bash
DIGEST=$(docker buildx imagetools inspect \
  ghcr.io/mattoyuzuru/idaten-backend:v0.7.0 --format '{{json .Manifest.Digest}}' | tr -d '"')
./deploy/deploy-production.sh --digest "$DIGEST"
# После успешного server-side dry-run:
./deploy/deploy-production.sh --digest "$DIGEST" --apply
```

До provisioning helper server-validates Namespace и client-validates bundle, поскольку
Kubernetes не принимает server dry-run namespaced resources в несуществующий namespace.
После provisioning выполняется полный server-side dry-run перед apply.

## Production smoke

```bash
ssh keykomi 'sudo k3s kubectl get deployment,pod,service,ingress,certificate,pvc -n idaten'
ssh keykomi 'sudo k3s kubectl top pod -n idaten'
ssh keykomi 'sudo k3s kubectl exec -n idaten deployment/idaten-backend -- alembic check'
curl --fail --silent --show-error https://idaten.keykomi.com/health
curl --fail --silent --show-error https://idaten.keykomi.com/ready
curl --head http://idaten.keykomi.com/health
openssl s_client -connect idaten.keykomi.com:443 -servername idaten.keykomi.com </dev/null
```

Ожидается ровно один Ready pod со стабильным restart count, certificate `Ready=True`,
валидная hostname/chain и permanent HTTP→HTTPS redirect. Логи проверяются только на
startup/error metadata; token, payload и Secret values не запрашиваются и не печатаются.
Telegram `/start`, `/link`, link complete и status проверяются вручную в private chat.

## Backup и restore

Создайте каталог backup с mode `0700`. PostgreSQL custom dump не содержит role password:

```bash
umask 077
mkdir -p "$HOME/Backups/idaten-production"
ssh keykomi 'sudo k3s kubectl exec -i -n prod postgres-0 -- sh -c '\''pg_dump -U "$POSTGRES_USER" --format=custom --no-owner --no-acl idaten'\''' \
  > "$HOME/Backups/idaten-production/idaten-$(date +%F-%H%M%S).dump"
ssh keykomi 'sudo k3s kubectl exec -n idaten deployment/idaten-backend -- tar -C /data/idaten -czf - .' \
  > "$HOME/Backups/idaten-production/storage-$(date +%F-%H%M%S).tar.gz"
```

Перед restore остановите backend, сохраните новый backup и проверьте целевой database.
Restore не является обычным rollback и требует явного maintenance решения:

```bash
ssh keykomi 'sudo k3s kubectl scale deployment/idaten-backend -n idaten --replicas=0'
cat BACKUP.dump | ssh keykomi 'sudo k3s kubectl exec -i -n prod postgres-0 -- sh -c '\''pg_restore -U "$POSTGRES_USER" --exit-on-error --clean --if-exists --no-owner --role=idaten -d idaten'\'''
ssh keykomi 'sudo k3s kubectl scale deployment/idaten-backend -n idaten --replicas=1'
```

Local-path PVC привязан к VPS/node и не является HA storage; database и storage backups
нужно хранить вне сервера и периодически проверять restore на отдельной БД.

## Application rollback

Зафиксируйте предыдущий digest до rollout. Rollback меняет только image и никогда не
удаляет namespace/PVC и не запускает Alembic downgrade автоматически:

Для первого production rollout `v0.6.0` не является допустимой rollback target: он не
достиг Ready из-за startup blockers. Первый подтвержденный healthy digest —
`sha256:ca915aacde39692b715526d107bf2e0830af5f7b61fe0e59343b47a5d128df51`
(`v0.6.1`). До появления следующего healthy release аварийный rollback означает остановку
Deployment с сохранением DB/PVC:

```bash
ssh keykomi 'sudo k3s kubectl scale deployment/idaten-backend -n idaten --replicas=0'
```

```bash
ssh keykomi 'sudo k3s kubectl set image deployment/idaten-backend -n idaten backend=ghcr.io/mattoyuzuru/idaten-backend@sha256:PREVIOUS_DIGEST'
ssh keykomi 'sudo k3s kubectl rollout status deployment/idaten-backend -n idaten --timeout=180s'
```

Перед rollback оцените backward compatibility уже примененной schema. Если старая версия
не совместима, оставьте текущий image и исправляйте forward либо выполняйте отдельное
согласованное maintenance восстановление.

## Manual checklist на телефоне

1. Проверить чистую установку signed APK и обновление поверх предыдущего APK без удаления данных.
2. На Android 9–13 проверить Play Store и HTTPS fallback; на Android 14+ — system settings path.
3. Проверить grant, deny, partial grant и повторный ручной permission request.
4. Убедиться, что link screen доступен после deny, а route отсутствует в базовом запросе.
5. В private Telegram chat выполнить `/link`, ввести code, проверить backend status.
6. На истории WALK/BIKE и нескольких страниц проверить, что найдены до N последних RUN.
7. Проверить несколько RUN одного дня, missing distance, counts и newest-first список.
8. Отдельно разрешить/отклонить route, выполнить Manual Sync и проверить один batch summary.
9. Убедиться, что duplicate/retry не создает вторую Activity или summary.
10. Проверить `/menu`, полный `/help`, slash `/run`, кнопочный `/run`, restart посреди draft,
    повтор save/cancel callback и HTML escaping названия с `<`, `>` и `&`.
11. Отозвать device через `/revoke_device` и проверить отказ следующей sync.

Rich Messages Bot API 10.1 доступны в aiogram 3.29.1, но MVP 0.7 использует проверяемый
HTML fallback: поддержка целевых Telegram-клиентов для rich blocks не подтверждена, а
streaming drafts и перенос durable outbox не входят в scope.
