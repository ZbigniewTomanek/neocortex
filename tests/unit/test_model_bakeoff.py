"""Lifecycle and secrecy contracts for the local model bake-off harness."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "model_bakeoff.sh"


def _dry_run(**overrides: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "NEOCORTEX_ADMIN_TOKEN": "admin-secret",
            "NEOCORTEX_MCP_TOKEN": "mcp-secret",
            "NEOCORTEX_DEV_TOKENS_FILE": "dev_tokens.json",
            "NEOCORTEX_BAKEOFF_RUN_ID": "test-run",
        }
    )
    env.update(overrides)
    return subprocess.run(
        [str(SCRIPT), "--arm", "test", "--dry-run"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_dry_run_accounts_for_routing_topology_seed_call_and_ceils_fractional_timeout() -> None:
    completed = _dry_run(
        NEOCORTEX_LOCAL_MODEL_TIMEOUT_S="0.5",
        NEOCORTEX_WORKER_CONCURRENCY="2",
    )

    assert completed.returncode == 0, completed.stderr
    # The application declares four seed domains.  With 28 episodes, each
    # route can add one proposal, so a later route can fan out to 32 domains.
    # ceil(0.5 * (1 route + 1 seed + 3 personal + 96 fanout) * 3 * 28 / 2 + 60) = 2181.
    assert "poll_timeout_s=2181" in completed.stdout
    assert "domain_routing_enabled=true" in completed.stdout
    assert "initial_domain_count=4" in completed.stdout
    assert "max_domain_fanout=32" in completed.stdout
    assert "seed_calls_per_episode=1" in completed.stdout


def test_dry_run_can_explicitly_disable_domain_routing() -> None:
    completed = _dry_run(
        NEOCORTEX_DOMAIN_ROUTING_ENABLED="false",
        NEOCORTEX_LOCAL_MODEL_TIMEOUT_S="1.1",
        NEOCORTEX_WORKER_CONCURRENCY="2",
    )

    assert completed.returncode == 0, completed.stderr
    # ceil(1.1 * 3 * 3 * 28 / 2 + 60) = 199.
    assert "poll_timeout_s=199" in completed.stdout
    assert "domain_routing_enabled=false" in completed.stdout
    assert "initial_domain_count=0" in completed.stdout
    assert "max_domain_fanout=0" in completed.stdout
    assert "seed_calls_per_episode=0" in completed.stdout
    assert "domain routing disabled" in completed.stdout


def test_dry_run_redacts_endpoint_userinfo_and_query() -> None:
    completed = _dry_run(
        NEOCORTEX_LOCAL_MODEL_BASE_URL="https://user:password@model.example:24000/v1?api_key=query-secret#fragment"
    )

    assert completed.returncode == 0, completed.stderr
    assert "endpoint=https://model.example:24000/v1" in completed.stdout
    assert "password" not in completed.stdout
    assert "query-secret" not in completed.stdout
    assert "fragment" not in completed.stdout


@pytest.fixture
def fake_bakeoff_project(tmp_path: Path) -> tuple[Path, dict[str, str], Path]:
    """Build a disposable command environment for non-dry-run lifecycle tests."""

    project = tmp_path / "project"
    scripts = project / "scripts"
    bin_dir = tmp_path / "bin"
    backups = project / "backups"
    scripts.mkdir(parents=True)
    bin_dir.mkdir()
    backups.mkdir()
    shutil.copy2(SCRIPT, scripts / "model_bakeoff.sh")
    (project / "dev_tokens.json").write_text(json.dumps({"admin-secret": "admin"}))
    log_path = tmp_path / "commands.log"
    pg_ready_marker = tmp_path / "pg-ready"

    (bin_dir / "uv").write_text("""#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == *corpus_loader.py* && "$*" == *--dry-run* ]]; then
  seq 1 28
elif [[ "$*" == *SEED_DOMAINS* ]]; then
  printf '4\\n'
elif [[ "$*" == *' -c '* || "$*" == *' -c'* ]]; then
  cat >/dev/null || true
  printf '0\\n'
fi
""")
    (bin_dir / "docker").write_text("""#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == *pg_isready* ]]; then
  if [[ "${FAKE_INITIAL_PG_READY:-0}" == 1 || -f "${FAKE_PG_READY_MARKER:?}" ]]; then
    exit 0
  fi
  exit 1
fi
exit 0
""")
    (bin_dir / "jq").write_text("""#!/usr/bin/env bash
set -euo pipefail
printf 'jq %q ' "$@" >>"${FAKE_COMMAND_LOG:?}"
printf '\\n' >>"${FAKE_COMMAND_LOG:?}"
cat >/dev/null
""")
    (bin_dir / "curl").write_text("""#!/usr/bin/env bash
set -euo pipefail
printf 'curl %q ' "$@" >>"${FAKE_COMMAND_LOG:?}"
printf '\\n' >>"${FAKE_COMMAND_LOG:?}"
cat >/dev/null
if [[ "$*" == */admin/graphs* ]]; then
  printf '{"graphs":["ncx_shared__knowledge"]}\\n'
elif [[ "$*" == */admin/jobs/summary* ]]; then
  printf '{"todo":0,"doing":0}\\n'
fi
""")
    (scripts / "run_e2e.sh").write_text("#!/usr/bin/env bash\nexit 0\n")
    (scripts / "manage.sh").write_text("""#!/usr/bin/env bash
set -euo pipefail
printf 'manage %q ' "$@" >>"${FAKE_COMMAND_LOG:?}"
printf '\\n' >>"${FAKE_COMMAND_LOG:?}"
case "${1:-} ${2:-}" in
  'start ')
    if [[ "${FAKE_START_STATUS:-0}" != 0 ]]; then exit "${FAKE_START_STATUS}"; fi
    if [[ "${FAKE_START_MAKES_PG_READY:-1}" == 1 ]]; then touch "${FAKE_PG_READY_MARKER:?}"; fi
    ;;
  'snapshot save')
    mkdir -p "${FAKE_BACKUP_DIR:?}"
    if [[ "${FAKE_SKIP_SNAPSHOT_FILE:-0}" != 1 ]]; then
      tar -czf "${FAKE_BACKUP_DIR}/${3:?}-fixed.tar.gz" --files-from /dev/null
    fi
    ;;
  'snapshot load')
    exit "${FAKE_RESTORE_STATUS:-0}"
    ;;
esac
""")
    for command in (
        bin_dir / "uv",
        bin_dir / "docker",
        bin_dir / "jq",
        bin_dir / "curl",
        scripts / "run_e2e.sh",
        scripts / "manage.sh",
    ):
        command.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "NEOCORTEX_ADMIN_TOKEN": "admin-secret",
            "NEOCORTEX_MCP_TOKEN": "mcp-secret",
            "NEOCORTEX_DEV_TOKENS_FILE": str(project / "dev_tokens.json"),
            "GOOGLE_API_KEY": "embedding-key",
            "NEOCORTEX_BAKEOFF_RUN_ID": "test-run",
            "NEOCORTEX_DOMAIN_ROUTING_ENABLED": "false",
            "NEOCORTEX_LOCAL_MODEL_TIMEOUT_S": "1",
            "FAKE_COMMAND_LOG": str(log_path),
            "FAKE_PG_READY_MARKER": str(pg_ready_marker),
            "FAKE_BACKUP_DIR": str(backups),
        }
    )
    return project, env, log_path


def _run_fake(project: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(project / "scripts" / "model_bakeoff.sh"), "--arm", "test"],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_admin_credentials_are_not_passed_in_jq_or_curl_argv(
    fake_bakeoff_project: tuple[Path, dict[str, str], Path],
) -> None:
    project, env, log_path = fake_bakeoff_project
    env["FAKE_INITIAL_PG_READY"] = "1"

    completed = _run_fake(project, env)

    assert completed.returncode == 0, completed.stderr
    command_log = log_path.read_text()
    assert "admin-secret" not in command_log
    assert "--arg" not in command_log
    assert "@-" in command_log


def test_stopped_postgres_is_started_non_destructively_before_fresh_start(
    fake_bakeoff_project: tuple[Path, dict[str, str], Path],
) -> None:
    project, env, log_path = fake_bakeoff_project
    env["FAKE_INITIAL_PG_READY"] = "0"

    completed = _run_fake(project, env)

    assert completed.returncode == 0, completed.stderr
    commands = log_path.read_text().splitlines()
    start_idx = commands.index("manage start ")
    save_idx = next(
        i for i, line in enumerate(commands) if "snapshot" in line and "save" in line and "test-pre-test-run" in line
    )
    fresh_idx = next(i for i, line in enumerate(commands) if "manage start" in line and "--fresh" in line)
    assert start_idx < save_idx < fresh_idx


def test_failed_non_destructive_start_refuses_fresh_start(
    fake_bakeoff_project: tuple[Path, dict[str, str], Path],
) -> None:
    project, env, log_path = fake_bakeoff_project
    env.update({"FAKE_INITIAL_PG_READY": "0", "FAKE_START_MAKES_PG_READY": "0"})

    completed = _run_fake(project, env)

    assert completed.returncode == 2
    assert "refusing destructive start --fresh" in completed.stderr
    assert "manage start --fresh" not in log_path.read_text()


def test_missing_pre_snapshot_archive_refuses_fresh_start(
    fake_bakeoff_project: tuple[Path, dict[str, str], Path],
) -> None:
    project, env, log_path = fake_bakeoff_project
    env.update({"FAKE_INITIAL_PG_READY": "1", "FAKE_SKIP_SNAPSHOT_FILE": "1"})

    completed = _run_fake(project, env)

    assert completed.returncode == 2
    assert "pre-run snapshot archive is missing" in completed.stderr
    assert "manage start --fresh" not in log_path.read_text()


def test_restore_failure_has_a_distinct_nonzero_status(fake_bakeoff_project: tuple[Path, dict[str, str], Path]) -> None:
    project, env, _log_path = fake_bakeoff_project
    env.update({"FAKE_INITIAL_PG_READY": "1", "FAKE_RESTORE_STATUS": "41"})

    completed = _run_fake(project, env)

    assert completed.returncode == 3
    assert "restoration failure status=3 (original status=0)" in completed.stderr


def test_bash_syntax_is_valid() -> None:
    completed = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr
