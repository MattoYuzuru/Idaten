from __future__ import annotations

import base64
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).with_name("provision-production.py")
SPEC = importlib.util.spec_from_file_location("provision_production", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load provisioning module")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ProvisionProductionTest(unittest.TestCase):
    def test_parser_and_database_url_encode_only_password_component(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "secrets"
            path.write_text(
                "TELEGRAM_BOT_TOKEN='token'\n"
                "POSTGRES_PASSWORD='p@ss:/?#[]'\n"
                f"HEALTH_CONNECT_SECURITY_PEPPER='{'x' * 32}'\n"
                "IMPORT_API_TOKEN='import'\n"
                "ACTIVITY_EXTRACTION_ENABLED='true'\n"
                "ACTIVITY_EXTRACTION_PROVIDER='OPENAI'\n"
                "ACTIVITY_EXTRACTION_DAILY_USER_LIMIT='5'\n",
            )
            path.chmod(0o600)
            values = MODULE.parse_secret_file(path)
            manifest = json.loads(MODULE.secret_manifest(values))
            encoded_url = manifest["data"]["DATABASE_URL"]
            database_url = base64.b64decode(encoded_url).decode()
            self.assertEqual(
                "postgresql+asyncpg://idaten:p%40ss%3A%2F%3F%23%5B%5D@"
                "postgres.prod.svc.cluster.local:5432/idaten",
                database_url,
            )
            self.assertEqual(
                "true",
                base64.b64decode(manifest["data"]["ACTIVITY_EXTRACTION_ENABLED"]).decode(),
            )
            self.assertEqual(
                "5",
                base64.b64decode(
                    manifest["data"]["ACTIVITY_EXTRACTION_DAILY_USER_LIMIT"]
                ).decode(),
            )

    def test_parser_rejects_permissive_file_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "secrets"
            path.write_text("TELEGRAM_BOT_TOKEN=x\n")
            path.chmod(0o644)
            with self.assertRaisesRegex(ValueError, "0600"):
                MODULE.parse_secret_file(path)


if __name__ == "__main__":
    unittest.main()
