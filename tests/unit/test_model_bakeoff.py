"""Lifecycle and secrecy contracts for the local model bake-off harness."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "model_bakeoff.sh"
RUN_E2E_SCRIPT = ROOT / "scripts" / "run_e2e.sh"


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
    # The router's source-derived policy allows four known matches plus one
    # proposed domain per route invocation. With three queue attempts this
    # gives 84 route invocations and 420 routed jobs. The acceptance budget is
    # 84 classifier + 84 top-level seed-resolution + 252 personal-stage +
    # 3,780 routed-stage + 1,260 routed-seed invocations = 5,460.
    # ceil(0.5 * 5460 / 2 + 60) = 1425.
    assert "poll_timeout_s=1425" in completed.stdout
    assert "domain_routing_enabled=true" in completed.stdout
    assert "initial_domain_count=4" in completed.stdout
    assert "max_unique_routed_domains=5" in completed.stdout
    assert "route_attempts=3" in completed.stdout
    assert "extraction_attempts=3" in completed.stdout
    assert "max_route_invocations=84" in completed.stdout
    assert "max_routed_extraction_jobs=420" in completed.stdout
    assert "top_level_seed_resolution_stage_invocations_max=84" in completed.stdout
    assert "routed_seed_stage_invocations_max=1260" in completed.stdout
    assert "operational_acceptance_stage_invocations=5460" in completed.stdout
    assert "PydanticAI theoretical retries" in completed.stdout
    assert "excludes parent-seed recursion" in completed.stdout


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
    assert "max_unique_routed_domains=0" in completed.stdout
    assert "top_level_seed_resolution_stage_invocations_max=0" in completed.stdout
    assert "routed_seed_stage_invocations_max=0" in completed.stdout
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


def test_bakeoff_defaults_mcp_token_to_admin_token_without_printing_values() -> None:
    completed = _dry_run(NEOCORTEX_MCP_TOKEN="")

    assert completed.returncode == 0, completed.stderr
    assert "mcp_token_env=NEOCORTEX_MCP_TOKEN configured=yes" in completed.stdout
    assert "admin-secret" not in completed.stdout


def test_default_run_id_matches_snapshot_safe_grammar() -> None:
    completed = _dry_run(NEOCORTEX_BAKEOFF_RUN_ID="")

    assert completed.returncode == 0, completed.stderr
    assert re.search(r"^bakeoff_run_id=[0-9]{8}T[0-9]{6}Z-[0-9]+$", completed.stdout, re.MULTILINE)


@pytest.mark.parametrize("unsafe_run_id", ["unsafe.run", "unsafe:run"])
def test_unsafe_run_id_is_rejected_before_destructive_actions(unsafe_run_id: str) -> None:
    completed = _dry_run(NEOCORTEX_BAKEOFF_RUN_ID=unsafe_run_id)

    assert completed.returncode == 2
    assert "invalid safe format" in completed.stderr
    assert "manage.sh start --fresh" not in completed.stdout


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
    (project / "dev_tokens.json").write_text(json.dumps({"admin-token": "admin"}))
    (project / "dev_tokens_test.json").write_text(
        json.dumps({"alice-token": "alice", "bob-token": "bob", "eve-token": "eve", "admin-token-neocortex": "admin"})
    )
    log_path = tmp_path / "commands.log"
    pg_ready_marker = tmp_path / "pg-ready"

    (bin_dir / "uv").write_text("""#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == *.diagnostics.tsv* ]]; then
  shift 2
  exec python3 "$@"
fi
if [[ "$*" == *recall_scorer.py* && "${FAKE_RECALL_STATUS:-0}" != 0 ]]; then
  exit "${FAKE_RECALL_STATUS}"
fi
if [[ "$*" == *compute_metrics.py* && "$*" =~ --phase[[:space:]]e2e ]]; then
  if [[ -f "${FAKE_PG_READY_MARKER:?}" ]]; then
    printf 'e2e_metrics_pg_ready=yes\\n' >>"${FAKE_COMMAND_LOG:?}"
  else
    printf 'e2e_metrics_pg_ready=no\\n' >>"${FAKE_COMMAND_LOG:?}"
    exit 91
  fi
fi
if [[ "$*" == *"e2e_manifest.py build"* ]]; then
  printf 'manifest_build=yes\\n' >>"${FAKE_COMMAND_LOG:?}"
fi
if [[ "$*" == *"e2e_manifest.py validate"* ]]; then
  printf 'manifest_validate=yes\\n' >>"${FAKE_COMMAND_LOG:?}"
  if [[ "${FAKE_MANIFEST_VALIDATE_STATUS:-0}" != 0 ]]; then
    exit "${FAKE_MANIFEST_VALIDATE_STATUS}"
  fi
fi
if [[ "$*" == *'x["total"]'* ]]; then
  cat | python3 -c 'import json,sys
x=json.load(sys.stdin)
keys=("todo","doing","succeeded","failed","cancelled","total")
assert (isinstance(x,dict) and all(type(x.get(k)) is int and x[k] >= 0 for k in keys)
        and x["total"] > 0 and sum(x[k] for k in keys[:-1]) == x["total"])
failure_rate_ok=(x["failed"] + x["cancelled"]) / x["total"] <= 0.10
print(" ".join(f"{k}={x[k]}" for k in keys)
      + f" failure_rate_ok={failure_rate_ok}")'
  exit 0
fi
if [[ "$*" == *corpus_loader.py* && "$*" == *--dry-run* ]]; then
  seq 1 28
elif [[ "$*" == *MAX_UNIQUE_ROUTED_DOMAINS* ]]; then
  printf '5\\n'
elif [[ "$*" == *SEED_DOMAINS* ]]; then
  printf '4\\n'
elif [[ "$*" == *retry_strategy* && "$*" == *extract_episode* ]]; then
  printf '3\\n'
elif [[ "$*" == *retry_strategy* && "$*" == *route_episode* ]]; then
  printf '3\\n'
elif [[ "$*" == *'data.get("name")'* ]]; then
  :
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
  if [[ -n "${FAKE_JOB_SUMMARY:-}" ]]; then
    printf '%s\\n' "$FAKE_JOB_SUMMARY"
  else
    printf '{"todo":0,"doing":0,"succeeded":1,"failed":0,"cancelled":0,"total":1}\\n'
  fi
fi
""")
    (scripts / "run_e2e.sh").write_text("""#!/usr/bin/env bash
set -euo pipefail
e2e_format='e2e child_run_id=%s dev_tokens_file=%s admin_set=%s mcp_set=%s '
e2e_format+='alice_set=%s bob_set=%s eve_set=%s keep_pg=%s\\n'
printf "$e2e_format" \\
  "${NEOCORTEX_E2E_RUN_ID:?}" "${NEOCORTEX_DEV_TOKENS_FILE##*/}" \\
  "${NEOCORTEX_ADMIN_TOKEN+x}" "${NEOCORTEX_MCP_TOKEN+x}" \\
  "${NEOCORTEX_ALICE_TOKEN+x}" "${NEOCORTEX_BOB_TOKEN+x}" "${NEOCORTEX_EVE_TOKEN+x}" \\
  "${KEEP_POSTGRES_RUNNING:-}" >>"${FAKE_COMMAND_LOG:?}"
status="${FAKE_E2E_STATUS:-0}"
if [[ "${KEEP_POSTGRES_RUNNING:-}" != 1 ]]; then
  rm -f "${FAKE_PG_READY_MARKER:?}"
fi
exit "$status"
""")
    (scripts / "manage.sh").write_text("""#!/usr/bin/env bash
set -euo pipefail
printf 'manage %q ' "$@" >>"${FAKE_COMMAND_LOG:?}"
printf '\\n' >>"${FAKE_COMMAND_LOG:?}"
case "${1:-} ${2:-}" in
  'start ')
    if [[ "${FAKE_START_STATUS:-0}" != 0 ]]; then exit "${FAKE_START_STATUS}"; fi
    if [[ "${FAKE_START_MAKES_PG_READY:-1}" == 1 ]]; then touch "${FAKE_PG_READY_MARKER:?}"; fi
    ;;
  'start --fresh')
    if [[ "${FAKE_FRESH_START_STATUS:-0}" != 0 ]]; then exit "${FAKE_FRESH_START_STATUS}"; fi
    touch "${FAKE_PG_READY_MARKER:?}"
    ;;
  'snapshot save')
    mkdir -p "${FAKE_BACKUP_DIR:?}"
    if [[ "${FAKE_SKIP_SNAPSHOT_FILE:-0}" != 1 ]]; then
      archive_path="${FAKE_BACKUP_DIR}/${3:?}-fixed.tar.gz"
      meta_dir="$(mktemp -d)"
      printf '{"name":"%s"}\n' "$3" >"$meta_dir/snapshot.json"
      tar -czf "$archive_path" -C "$meta_dir" snapshot.json
      rm -rf "$meta_dir"
      if [[ -n "${NEOCORTEX_SNAPSHOT_PATH_FILE:-}" ]]; then
        printf '%s\n' "$archive_path" >"${NEOCORTEX_SNAPSHOT_PATH_FILE:?}"
      fi
    fi
    ;;
  'snapshot load')
    [[ -f "${FAKE_PG_READY_MARKER:?}" ]] || exit 42
    exit "${FAKE_RESTORE_STATUS:-0}"
    ;;
  'stop --all')
    rm -f "${FAKE_PG_READY_MARKER:?}"
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
            "NEOCORTEX_ADMIN_TOKEN": "admin-token",
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
    assert "admin-token" not in command_log
    assert "--arg" not in command_log
    assert "@-" in command_log


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("NEOCORTEX_DEV_TOKENS_FILE", "dev_tokens_test.json"),
        ("NEOCORTEX_ADMIN_TOKEN", "admin-token-neocortex"),
    ],
)
def test_bakeoff_requires_canonical_admin_identity_before_destructive_actions(
    fake_bakeoff_project: tuple[Path, dict[str, str], Path], variable: str, value: str
) -> None:
    project, env, log_path = fake_bakeoff_project
    env[variable] = value

    completed = _run_fake(project, env)

    assert completed.returncode == 2
    command_log = log_path.read_text() if log_path.exists() else ""
    assert "manage start --fresh" not in command_log
    assert "snapshot save" not in command_log


def test_relative_canonical_dev_token_path_resolves_from_repository_root(
    fake_bakeoff_project: tuple[Path, dict[str, str], Path],
) -> None:
    project, env, _log_path = fake_bakeoff_project
    env.update({"NEOCORTEX_DEV_TOKENS_FILE": "dev_tokens.json", "FAKE_INITIAL_PG_READY": "1"})

    completed = _run_fake(project, env)

    assert completed.returncode == 0, completed.stderr


def test_existing_canonical_metrics_are_quarantined_before_fresh_start(
    fake_bakeoff_project: tuple[Path, dict[str, str], Path],
) -> None:
    project, env, _log_path = fake_bakeoff_project
    resources = project / "docs/plans/33-local-qwen-migration/resources"
    resources.mkdir(parents=True)
    canonical = resources / "metrics-test.json"
    canonical.write_text('{"run_id":"old-failed-run"}\n')
    env["FAKE_INITIAL_PG_READY"] = "1"

    completed = _run_fake(project, env)

    assert completed.returncode == 0, completed.stderr
    stale = resources / "metrics-test.json.stale"
    assert not canonical.exists()
    assert stale.read_text() == '{"run_id":"old-failed-run"}\n'
    assert completed.stdout.index("quarantined stale canonical metrics") < completed.stdout.index("start --fresh")


def test_e2e_lifecycle_uses_test_token_map_without_corpus_credentials(
    fake_bakeoff_project: tuple[Path, dict[str, str], Path],
) -> None:
    project, env, log_path = fake_bakeoff_project
    env["FAKE_INITIAL_PG_READY"] = "1"

    completed = _run_fake(project, env)

    assert completed.returncode == 0, completed.stderr
    e2e_lines = [line for line in log_path.read_text().splitlines() if line.startswith("e2e ")]
    assert len(e2e_lines) == 5
    assert e2e_lines == [
        f"e2e child_run_id=test-run.e2e.{index:02d} dev_tokens_file=dev_tokens_test.json "
        "admin_set= mcp_set= alice_set= bob_set= eve_set= keep_pg=1"
        for index in range(1, 6)
    ]
    command_log = log_path.read_text()
    assert "admin-token" not in command_log
    assert "mcp-secret" not in command_log


def test_e2e_manifest_is_built_and_validated_without_metrics_merge(
    fake_bakeoff_project: tuple[Path, dict[str, str], Path],
) -> None:
    project, env, log_path = fake_bakeoff_project
    env["FAKE_INITIAL_PG_READY"] = "1"

    completed = _run_fake(project, env)

    assert completed.returncode == 0, completed.stderr
    assert log_path.read_text().count("manifest_build=yes") == 1
    assert log_path.read_text().count("manifest_validate=yes") == 1
    assert "offline_merge=yes" not in log_path.read_text()
    assert "e2e_metrics_pg_ready=yes" not in log_path.read_text()
    assert "e2e_metrics_pg_ready=no" not in log_path.read_text()


def test_recall_failure_is_not_reported_as_a_passing_harness(
    fake_bakeoff_project: tuple[Path, dict[str, str], Path],
) -> None:
    project, env, log_path = fake_bakeoff_project
    env.update({"FAKE_INITIAL_PG_READY": "1", "FAKE_RECALL_STATUS": "9"})

    completed = _run_fake(project, env)

    assert completed.returncode == 9
    assert len([line for line in log_path.read_text().splitlines() if line.startswith("e2e ")]) == 5


def test_retained_diagnostics_index_uses_resolvable_relative_paths_even_on_later_failure(
    fake_bakeoff_project: tuple[Path, dict[str, str], Path],
    tmp_path: Path,
) -> None:
    project, env, _log_path = fake_bakeoff_project
    private_parent = tmp_path / "private"
    private_parent.mkdir(mode=0o700)
    env.update(
        {
            "FAKE_INITIAL_PG_READY": "1",
            "FAKE_RECALL_STATUS": "9",
            "FAKE_MANIFEST_VALIDATE_STATUS": "23",
            "NEOCORTEX_BAKEOFF_PRIVATE_DIR": str(private_parent),
        }
    )

    completed = _run_fake(project, env)

    assert completed.returncode == 23
    run_dir = next(private_parent.glob("neocortex-bakeoff.test-run.*"))
    index = json.loads((run_dir / "diagnostics-index.json").read_text())
    recall = next(row for row in index["diagnostics"] if row["script"] == "recall_scorer.py")
    assert recall["stdout"]["file"] == "e2e/recall.stdout"
    assert recall["stderr"]["file"] == "e2e/recall.stderr"
    assert (run_dir / recall["stdout"]["file"]).is_file()
    assert (run_dir / recall["stderr"]["file"]).is_file()


def test_post_e2e_failure_restores_snapshot_while_postgres_is_running(
    fake_bakeoff_project: tuple[Path, dict[str, str], Path],
) -> None:
    project, env, log_path = fake_bakeoff_project
    env.update({"FAKE_INITIAL_PG_READY": "1", "FAKE_E2E_STATUS": "17"})

    completed = _run_fake(project, env)

    assert completed.returncode == 17
    commands = log_path.read_text().splitlines()
    e2e_lines = [line for line in commands if line.startswith("e2e ")]
    assert len(e2e_lines) == 5
    assert [line.split()[1].split("=", 1)[1] for line in e2e_lines] == [
        f"test-run.e2e.{index:02d}" for index in range(1, 6)
    ]
    e2e_index = next(i for i, line in enumerate(commands) if line.startswith("e2e "))
    restore_index = next(i for i, line in enumerate(commands) if "snapshot manage load" in line)
    assert e2e_index < restore_index
    assert "manage snapshot manage load manage test-pre-test-run " not in commands
    assert any(line == "manage snapshot manage load manage test-pre-test-run-fixed " for line in commands)
    assert "restoration failure" not in completed.stderr


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


def test_harness_rejects_inconsistent_or_over_rate_job_summary(
    fake_bakeoff_project: tuple[Path, dict[str, str], Path],
) -> None:
    project, env, log_path = fake_bakeoff_project
    env.update(
        {
            "FAKE_INITIAL_PG_READY": "1",
            "FAKE_JOB_SUMMARY": '{"todo":0,"doing":0,"succeeded":8,"failed":1,"cancelled":1,"total":10}',
        }
    )

    completed = _run_fake(project, env)

    assert completed.returncode == 2
    assert "job summary exceeds failure-rate gate" in completed.stderr
    assert not any(line.startswith("e2e ") for line in log_path.read_text().splitlines())


def test_embedded_job_summary_parser_executes_and_emits_parseable_nonterminal_counts() -> None:
    poll_jobs = SCRIPT.read_text().split("poll_jobs() {", 1)[1].split("result_matches_child()", 1)[0]
    match = re.search(r"uv run python -c\s*\\\s*'([^']+)'", poll_jobs)
    assert match is not None

    summary = {"todo": 1, "doing": 0, "succeeded": 9, "failed": 0, "cancelled": 0, "total": 10}
    completed = subprocess.run(
        ["uv", "run", "python", "-c", match.group(1)],
        cwd=ROOT,
        input=json.dumps(summary),
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    fields = dict(item.split("=", 1) for item in completed.stdout.split())
    assert fields == {
        "todo": "1",
        "doing": "0",
        "succeeded": "9",
        "failed": "0",
        "cancelled": "0",
        "total": "10",
        "failure_rate_ok": "True",
    }


def test_missing_pre_snapshot_archive_refuses_fresh_start(
    fake_bakeoff_project: tuple[Path, dict[str, str], Path],
) -> None:
    project, env, log_path = fake_bakeoff_project
    env.update({"FAKE_INITIAL_PG_READY": "1", "FAKE_SKIP_SNAPSHOT_FILE": "1"})

    completed = _run_fake(project, env)

    assert completed.returncode == 2
    assert "snapshot path receipt is missing" in completed.stderr
    assert "manage start --fresh" not in log_path.read_text()


def test_restore_failure_has_a_distinct_nonzero_status(fake_bakeoff_project: tuple[Path, dict[str, str], Path]) -> None:
    project, env, _log_path = fake_bakeoff_project
    env.update({"FAKE_INITIAL_PG_READY": "1", "FAKE_RESTORE_STATUS": "41"})

    completed = _run_fake(project, env)

    assert completed.returncode == 3
    assert "restoration failure status=3 (original status=0)" in completed.stderr


@pytest.mark.parametrize(
    ("keep_postgres", "expected_cleanup"),
    [("1", "manage stop"), (None, "manage stop --all")],
)
def test_run_e2e_cleanup_preserves_postgres_only_when_requested(
    tmp_path: Path,
    keep_postgres: str | None,
    expected_cleanup: str,
) -> None:
    project = tmp_path / "project"
    scripts = project / "scripts"
    bin_dir = tmp_path / "bin"
    scripts.mkdir(parents=True)
    bin_dir.mkdir()
    shutil.copy2(RUN_E2E_SCRIPT, scripts / "run_e2e.sh")
    test_script = project / "test_script.py"
    test_script.write_text("# fake e2e script\n")
    log_path = tmp_path / "commands.log"
    (scripts / "manage.sh").write_text("""#!/usr/bin/env bash
set -euo pipefail
printf 'manage %s\\n' "$*" >>"${FAKE_COMMAND_LOG:?}"
""")
    (bin_dir / "uv").write_text("""#!/usr/bin/env bash
set -euo pipefail
printf 'uv %s\\n' "$*" >>"${FAKE_COMMAND_LOG:?}"
""")
    for command in (scripts / "run_e2e.sh", scripts / "manage.sh", bin_dir / "uv"):
        command.chmod(0o755)

    env = os.environ.copy()
    env.update({"PATH": f"{bin_dir}:{env['PATH']}", "FAKE_COMMAND_LOG": str(log_path)})
    env.pop("KEEP_RUNNING", None)
    if keep_postgres is None:
        env.pop("KEEP_POSTGRES_RUNNING", None)
    else:
        env["KEEP_POSTGRES_RUNNING"] = keep_postgres

    completed = subprocess.run(
        [str(scripts / "run_e2e.sh"), str(test_script)],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert log_path.read_text().splitlines()[-1] == expected_cleanup


def test_bash_syntax_is_valid() -> None:
    completed = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr
