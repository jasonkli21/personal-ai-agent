"""Deployment contract checks using fake CLIs; never contact Google Cloud."""

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parents[2] / "infrastructure/gcp/deploy.sh"


def test_deployment_runs_on_system_bash_with_private_services_and_worker_publisher(tmp_path):
    commands = tmp_path / "commands.log"
    executables = tmp_path / "bin"
    executables.mkdir()
    (executables / "git").write_text("""#!/bin/sh
case "$*" in *rev-parse*) echo abcdef012345 ;; esac
""")
    (executables / "gcloud").write_text("""#!/bin/sh
printf '%s\\n' "$*" >> "$DEPLOY_COMMAND_LOG"
for arg in "$@"; do
  case "$arg" in
    --env-vars-file=*) cat "${arg#--env-vars-file=}" >> "$DEPLOY_COMMAND_LOG" ;;
  esac
done
case "$*" in
  *"docker images describe"*) printf 'sha256:%064d\\n' 0 ;;
  *"services describe personal-ai-api"*) echo https://api.example.test ;;
  *"services describe personal-ai-worker"*) echo https://worker.example.test ;;
  *"services describe personal-ai-web"*) echo https://web.example.test ;;
  *"projects describe"*) echo 123456 ;;
esac
""")
    for executable in executables.iterdir():
        executable.chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{executables}:/usr/bin:/bin",
        "DEPLOY_COMMAND_LOG": str(commands),
        "MAINTENANCE_ENABLED": "false",
        "EXPORT_ENABLED": "false",
        "DELETION_ENABLED": "false",
        "NEON_RUNTIME_DSN_SECRET_NAME": "personal-ai-neon-runtime-dsn",
        "NEON_RUNTIME_DSN_SECRET_VERSION": "1",
        "DYNAMODB_ROLE_ARN": "arn:aws:iam::123456789012:role/personal-ai-runtime",
        "DYNAMODB_IDENTITY_TOKEN_AUDIENCE": "https://personal-ai.example/aws-role",
    }
    result = subprocess.run(
        [
            "/bin/bash",
            str(SCRIPT),
            "staging",
            "synthetic-project",
            "us-central1",
            "synthetic-secret",
            "synthetic-model",
            "synthetic-client",
            "Owner@GMAIL.COM",
            "https://web.example.test",
            "2",
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    log = commands.read_text()
    assert "AUTH_ALLOWED_EMAILS: '[\"owner@gmail.com\"]'" in log
    assert "run deploy personal-ai-api" in log and "--no-allow-unauthenticated" in log
    assert "backend@sha256:" in log and "frontend@sha256:" in log
    assert (
        "pubsub topics add-iam-policy-binding personal-ai-async "
        "--member=serviceAccount:personal-ai-worker-runtime@synthetic-project.iam.gserviceaccount.com "
        "--role=roles/pubsub.publisher"
    ) in log
    assert 'MAINTENANCE_ENABLED: "false"' in log
    assert 'EXPORT_ENABLED: "false"' in log and 'DELETION_ENABLED: "false"' in log
    assert 'P10_CLOUD_ADAPTERS_CONFIGURED: "true"' in log
    assert "P10_NEON_RUNTIME_DSN=personal-ai-neon-runtime-dsn:1" in log
    assert "firestore" not in log.lower()
    assert "scheduler jobs pause personal-ai-maintenance" in log
