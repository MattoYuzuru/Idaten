#!/usr/bin/env python3
"""Provision the isolated Idaten database and runtime Secret without logging values."""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import re
import shlex
import stat
import subprocess
from urllib.parse import quote

REQUIRED_KEYS = {
    "TELEGRAM_BOT_TOKEN",
    "POSTGRES_PASSWORD",
    "HEALTH_CONNECT_SECURITY_PEPPER",
}
OPTIONAL_KEYS = {
    "IMPORT_API_TOKEN",
    "ACTIVITY_EXTRACTION_API_KEY",
    "ACTIVITY_EXTRACTION_ENABLED",
    "ACTIVITY_EXTRACTION_ENDPOINT",
    "ACTIVITY_EXTRACTION_DAILY_USER_LIMIT",
    "ACTIVITY_EXTRACTION_MAX_IMAGE_BYTES",
    "ACTIVITY_EXTRACTION_MAX_IMAGE_PIXELS",
    "ACTIVITY_EXTRACTION_MAX_TEXT_CHARS",
    "ACTIVITY_EXTRACTION_MODEL",
    "ACTIVITY_EXTRACTION_MONTHLY_GLOBAL_LIMIT",
    "ACTIVITY_EXTRACTION_PROVIDER",
    "ACTIVITY_EXTRACTION_RETRIES",
    "ACTIVITY_EXTRACTION_TIMEOUT_SECONDS",
    "BOT_OWNER_TELEGRAM_ID",
}
KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")


def parse_secret_file(path: Path) -> dict[str, str]:
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != 0o600:
        raise ValueError(f"{path} must have mode 0600, got {mode:04o}")
    values: dict[str, str] = {}
    for number, raw in enumerate(path.read_text().splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").lstrip()
        if "=" not in line:
            raise ValueError(f"invalid assignment at line {number}")
        key, encoded = line.split("=", 1)
        key = key.strip()
        if not KEY_PATTERN.fullmatch(key):
            raise ValueError(f"invalid key at line {number}")
        if key not in REQUIRED_KEYS | OPTIONAL_KEYS:
            continue
        parsed = shlex.split(encoded, posix=True)
        if len(parsed) != 1:
            raise ValueError(f"value at line {number} must be one shell-quoted token")
        values[key] = parsed[0]
    missing = sorted(key for key in REQUIRED_KEYS if not values.get(key))
    if missing:
        raise ValueError(f"missing required keys: {', '.join(missing)}")
    if len(values["HEALTH_CONNECT_SECURITY_PEPPER"].encode()) < 32:
        raise ValueError("HEALTH_CONNECT_SECURITY_PEPPER must be at least 32 bytes")
    return values


def ssh_stdin(host: str, command: str, payload: str) -> None:
    subprocess.run(["ssh", host, command], input=payload, text=True, check=True)


def database_sql(password: str) -> str:
    escaped = password.replace("'", "''")
    return f"""\
\\set ON_ERROR_STOP on
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'idaten') THEN
        CREATE ROLE idaten LOGIN PASSWORD '{escaped}';
    ELSE
        ALTER ROLE idaten LOGIN PASSWORD '{escaped}';
    END IF;
END
$$;
ALTER ROLE idaten NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
SELECT 'CREATE DATABASE idaten OWNER idaten'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'idaten')\\gexec
ALTER DATABASE idaten OWNER TO idaten;
REVOKE ALL ON DATABASE idaten FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE idaten TO idaten;
"""


def secret_manifest(values: dict[str, str]) -> str:
    password = quote(values["POSTGRES_PASSWORD"], safe="")
    runtime = {
        "DATABASE_URL": (
            "postgresql+asyncpg://idaten:"
            f"{password}@postgres.prod.svc.cluster.local:5432/idaten"
        ),
        "TELEGRAM_BOT_TOKEN": values["TELEGRAM_BOT_TOKEN"],
        "HEALTH_CONNECT_SECURITY_PEPPER": values["HEALTH_CONNECT_SECURITY_PEPPER"],
    }
    if values.get("IMPORT_API_TOKEN"):
        runtime["IMPORT_API_TOKEN"] = values["IMPORT_API_TOKEN"]
    for key in (
        "ACTIVITY_EXTRACTION_API_KEY",
        "ACTIVITY_EXTRACTION_DAILY_USER_LIMIT",
        "ACTIVITY_EXTRACTION_ENABLED",
        "ACTIVITY_EXTRACTION_ENDPOINT",
        "ACTIVITY_EXTRACTION_MAX_IMAGE_BYTES",
        "ACTIVITY_EXTRACTION_MAX_IMAGE_PIXELS",
        "ACTIVITY_EXTRACTION_MAX_TEXT_CHARS",
        "ACTIVITY_EXTRACTION_MODEL",
        "ACTIVITY_EXTRACTION_MONTHLY_GLOBAL_LIMIT",
        "ACTIVITY_EXTRACTION_PROVIDER",
        "ACTIVITY_EXTRACTION_RETRIES",
        "ACTIVITY_EXTRACTION_TIMEOUT_SECONDS",
        "BOT_OWNER_TELEGRAM_ID",
    ):
        if values.get(key):
            runtime[key] = values[key]
    manifest = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": "idaten-runtime", "namespace": "idaten"},
        "type": "Opaque",
        "data": {
            key: base64.b64encode(value.encode()).decode()
            for key, value in runtime.items()
        },
    }
    return json.dumps(manifest)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--secret-file", type=Path, default=Path.home() / ".running_bot_tokens"
    )
    parser.add_argument("--ssh-host", default="keykomi")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    values = parse_secret_file(args.secret_file)
    present = sorted(key for key in REQUIRED_KEYS | OPTIONAL_KEYS if values.get(key))
    print(f"validated secret names: {', '.join(present)}")
    print("planned resources: database=idaten role=idaten secret=idaten/idaten-runtime")
    if not args.apply:
        print("validation only; pass --apply after the production confirmation gate")
        return

    namespace = '{"apiVersion":"v1","kind":"Namespace","metadata":{"name":"idaten"}}'
    ssh_stdin(args.ssh_host, "sudo k3s kubectl apply -f -", namespace)
    ssh_stdin(
        args.ssh_host,
        "sudo k3s kubectl exec -i -n prod postgres-0 -- sh -c "
        "'psql -U \"$POSTGRES_USER\" -d postgres'",
        database_sql(values["POSTGRES_PASSWORD"]),
    )
    ssh_stdin(args.ssh_host, "sudo k3s kubectl apply -f -", secret_manifest(values))
    print("production database, role and Kubernetes Secret provisioned")


if __name__ == "__main__":
    main()
