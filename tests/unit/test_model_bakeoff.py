"""Lifecycle and secrecy contracts for the local model bake-off harness."""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "model_bakeoff.sh"
RUN_E2E_SCRIPT = ROOT / "scripts" / "run_e2e.sh"
SUPERVISOR = ROOT / "docs/plans/34-qwen-thinking-benchmark/validation/stage7_arm_supervisor.py"
PARTIAL_EVIDENCE = ROOT / "docs/plans/34-qwen-thinking-benchmark/validation/stage7_partial_evidence.py"


def _dry_run(*, arm: str = "test", **overrides: str) -> subprocess.CompletedProcess[str]:
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
        [str(SCRIPT), "--arm", arm, "--dry-run"],
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
    validation = project / "docs/plans/34-qwen-thinking-benchmark/validation"
    scripts.mkdir(parents=True)
    bin_dir.mkdir()
    backups.mkdir()
    validation.mkdir(parents=True)
    shutil.copy2(SCRIPT, scripts / "model_bakeoff.sh")
    shutil.copy2(SUPERVISOR, validation / "stage7_arm_supervisor.py")
    shutil.copy2(PARTIAL_EVIDENCE, validation / "stage7_partial_evidence.py")
    (project / "dev_tokens.json").write_text(json.dumps({"admin-token": "admin"}))
    (project / "dev_tokens_test.json").write_text(
        json.dumps({"alice-token": "alice", "bob-token": "bob", "eve-token": "eve", "admin-token-neocortex": "admin"})
    )
    log_path = tmp_path / "commands.log"
    pg_ready_marker = tmp_path / "pg-ready"
    fake_date_state = tmp_path / "fake-date-state"
    real_python = sys.executable

    (bin_dir / "python3").write_text("""#!/usr/bin/env bash
set -euo pipefail
if [[ "${FAKE_PROVENANCE_CHILD_FAILURE:-0}" == 1 && "${6:-}" == e2e_child_reset ]]; then
  exit 73
fi
if [[ "${FAKE_VERIFY_SERVICES_FAIL:-0}" == 1 && "${2:-}" == --verify-services ]]; then
  exit 74
fi
if [[ "${2:-}" == finalize ]]; then
  printf 'finalizer_start\\n' >>"${FAKE_COMMAND_LOG:?}"
  if [[ "${FAKE_PARTIAL_EVIDENCE_FAIL:-0}" == 1 ]]; then
    exit 71
  fi
  "${FAKE_REAL_PYTHON:?}" "$@"
  status=$?
  printf 'finalizer_end=%s\\n' "$status" >>"${FAKE_COMMAND_LOG:?}"
  exit "$status"
fi
if [[ "${2:-}" == write-unavailable && "${FAKE_WRITE_UNAVAILABLE_FAIL:-0}" == 1 ]]; then
  printf 'write_unavailable_failed=72\\n' >>"${FAKE_COMMAND_LOG:?}"
  exit 72
fi
exec "${FAKE_REAL_PYTHON:?}" "$@"
""")

    (bin_dir / "uv").write_text("""#!/usr/bin/env bash
set -euo pipefail
argument_after() {
  local wanted="$1" previous="" value
  shift
  for value in "$@"; do
    if [[ "$previous" == "$wanted" ]]; then printf '%s\\n' "$value"; return 0; fi
    previous="$value"
  done
  return 1
}
emit_unavailable() {
  local kind="$1" path="$2" arm="$3" reason="producer_expected_quality"
  local summary="$PWD/docs/plans/33-local-qwen-migration/resources/job-summary-$arm-${NEOCORTEX_BAKEOFF_RUN_ID:?}.json"
  "${FAKE_REAL_PYTHON:?}" \
    "$PWD/docs/plans/34-qwen-thinking-benchmark/validation/stage7_partial_evidence.py" \
    write-unavailable --path "$path" --kind "$kind" \
    --run-id "${NEOCORTEX_BAKEOFF_RUN_ID:?}" --arm "$arm" --reason "$reason" \
    --source "$summary" --job-summary-path "$summary" >/dev/null
}
if [[ "$*" == *.diagnostics.tsv* ]]; then
  shift 2
  exec python3 "$@"
fi
if [[ "$*" == *recall_scorer.py* && "${FAKE_RECALL_STATUS:-0}" != 0 ]]; then
  exit "${FAKE_RECALL_STATUS}"
fi
if [[ "$*" == *compute_metrics.py* ]]; then
  metrics_status="${FAKE_METRICS_STATUS:-0}"
  if [[ "$*" =~ --phase[[:space:]]e2e ]]; then
    metrics_status="${FAKE_METRICS_MERGE_STATUS:-0}"
  fi
  if [[ "$metrics_status" != 0 ]]; then
    if [[ "${FAKE_PRODUCER_UNAVAILABLE:-0}" == 1 ]]; then
      arm="$(argument_after --arm "$@")"
      emit_unavailable metrics "$PWD/docs/plans/33-local-qwen-migration/resources/metrics-$arm.json" "$arm"
    fi
    exit "$metrics_status"
  fi
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
  if [[ "${FAKE_MANIFEST_BUILD_STATUS:-0}" != 0 ]]; then
    if [[ "${FAKE_PRODUCER_UNAVAILABLE:-0}" == 1 ]]; then
      output_path="$(argument_after --output-path "$@")"
      arm="$(argument_after --arm "$@")"
      emit_unavailable e2e_manifest "$output_path" "$arm"
    fi
    exit "${FAKE_MANIFEST_BUILD_STATUS}"
  fi
fi
if [[ "$*" == *"e2e_manifest.py validate"* ]]; then
  printf 'manifest_validate=yes\\n' >>"${FAKE_COMMAND_LOG:?}"
  if [[ "${FAKE_MANIFEST_VALIDATE_STATUS:-0}" != 0 ]]; then
    exit "${FAKE_MANIFEST_VALIDATE_STATUS}"
  fi
fi
if [[ "$*" == *generate_qwen_parsing_report.py* && "${FAKE_REPORT_STATUS:-0}" != 0 ]]; then
  if [[ "${FAKE_PRODUCER_UNAVAILABLE:-0}" == 1 ]]; then
    output_dir="$(argument_after --output-dir "$@")"
    run_id="$(argument_after --run-id "$@")"
    arm="$(argument_after --arm "$@")"
    emit_unavailable report "$output_dir/qwen-parsing-report-$arm-$run_id.json" "$arm"
  fi
  exit "${FAKE_REPORT_STATUS}"
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
    (bin_dir / "fake-service").write_text("""#!/usr/bin/env bash
set -euo pipefail
stop() { printf 'owned_service_stopped=%s\\n' "$$" >>"${FAKE_COMMAND_LOG:?}"; exit 0; }
trap stop TERM INT
while :; do
  printf 'owned_service_request=%s\\n' "$$" >>"${FAKE_COMMAND_LOG:?}"
  sleep 0.02 & wait $!
done
""")
    (bin_dir / "date").write_text("""#!/usr/bin/env bash
set -euo pipefail
if [[ "${FAKE_POLL_IMMEDIATE_TIMEOUT:-0}" == 1 && "$*" == +%s ]]; then
  count=0
  [[ ! -f "${FAKE_DATE_STATE:?}" ]] || count="$(<"${FAKE_DATE_STATE:?}")"
  count=$((count + 1))
  printf '%s\\n' "$count" >"${FAKE_DATE_STATE:?}"
  if (( count == 1 )); then printf '100\\n'; else printf '101\\n'; fi
else
  exec /bin/date "$@"
fi
""")
    (scripts / "run_e2e.sh").write_text("""#!/usr/bin/env bash
set -euo pipefail
cleanup() {
  if [[ "${FAKE_E2E_BLOCK:-0}" == 1 ]]; then
    printf 'child_cleanup_start\\n' >>"${FAKE_COMMAND_LOG:?}"
    "$(dirname "$0")/manage.sh" stop
    sleep "${FAKE_CHILD_CLEANUP_DELAY:-0.1}"
    printf 'child_cleanup_end\\n' >>"${FAKE_COMMAND_LOG:?}"
  fi
}
trap cleanup EXIT
trap 'exit 143' TERM
if [[ "${FAKE_ASSERT_PLANNED:-0}" == 1 ]]; then
  python3 - "$(dirname "$0")/../docs/plans/34-qwen-thinking-benchmark/validation/provenance.json" \
    "${NEOCORTEX_E2E_RUN_ID:?}" <<'PY'
import json, sys
document = json.load(open(sys.argv[1], encoding="utf-8"))
child_run_id = sys.argv[2]
run_id = child_run_id.split(".e2e.", 1)[0]
events = document["runs"][run_id]["events"]
assert any(
    event["status"] == "planned"
    and event["action"] == "e2e_child_reset"
    and event["target"] == child_run_id
    for event in events
)
PY
  printf 'child_saw_planned=%s\\n' "${NEOCORTEX_E2E_RUN_ID:?}" >>"${FAKE_COMMAND_LOG:?}"
fi
e2e_format='e2e child_run_id=%s dev_tokens_file=%s admin_set=%s mcp_set=%s '
e2e_format+='alice_set=%s bob_set=%s eve_set=%s keep_pg=%s\\n'
printf "$e2e_format" \\
  "${NEOCORTEX_E2E_RUN_ID:?}" "${NEOCORTEX_DEV_TOKENS_FILE##*/}" \\
  "${NEOCORTEX_ADMIN_TOKEN+x}" "${NEOCORTEX_MCP_TOKEN+x}" \\
  "${NEOCORTEX_ALICE_TOKEN+x}" "${NEOCORTEX_BOB_TOKEN+x}" "${NEOCORTEX_EVE_TOKEN+x}" \\
  "${KEEP_POSTGRES_RUNNING:-}" >>"${FAKE_COMMAND_LOG:?}"
if [[ "${FAKE_E2E_BLOCK:-0}" == 1 ]]; then
  printf 'child_blocking\\n' >>"${FAKE_COMMAND_LOG:?}"
  sleep 30
fi
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
project_dir="$(dirname "$0")/.."
stop_services() {
  local pid_file pid
  for pid_file in "$project_dir/.mcp.pid" "$project_dir/.ingestion.pid"; do
    if [[ -f "$pid_file" ]]; then
      pid="$(<"$pid_file")"
      kill "$pid" 2>/dev/null || true
      rm -f "$pid_file"
    fi
  done
}
start_services() {
  stop_services
  fake-service >/dev/null 2>&1 & printf '%s\\n' "$!" >"$project_dir/.mcp.pid"
  fake-service >/dev/null 2>&1 & printf '%s\\n' "$!" >"$project_dir/.ingestion.pid"
}
case "${1:-} ${2:-}" in
  'start ')
    if [[ "${FAKE_START_STATUS:-0}" != 0 ]]; then exit "${FAKE_START_STATUS}"; fi
    if [[ "${FAKE_START_MAKES_PG_READY:-1}" == 1 ]]; then touch "${FAKE_PG_READY_MARKER:?}"; fi
    start_services
    ;;
  'start --fresh')
    if [[ "${FAKE_FRESH_START_STATUS:-0}" != 0 ]]; then exit "${FAKE_FRESH_START_STATUS}"; fi
    touch "${FAKE_PG_READY_MARKER:?}"
    start_services
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
    stop_services
    [[ -f "${FAKE_PG_READY_MARKER:?}" ]] || exit 42
    if [[ -n "${FAKE_RESTORE_MARKER:-}" ]]; then touch "$FAKE_RESTORE_MARKER"; fi
    if [[ "${FAKE_RESTORE_DELAY:-0}" != 0 ]]; then sleep "$FAKE_RESTORE_DELAY"; fi
    exit "${FAKE_RESTORE_STATUS:-0}"
    ;;
  'stop --all')
    stop_services
    rm -f "${FAKE_PG_READY_MARKER:?}"
    ;;
  'stop ')
    stop_services
    ;;
esac
""")
    for command in (
        bin_dir / "python3",
        bin_dir / "uv",
        bin_dir / "docker",
        bin_dir / "fake-service",
        bin_dir / "date",
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
            "FAKE_DATE_STATE": str(fake_date_state),
            "FAKE_BACKUP_DIR": str(backups),
            "FAKE_REAL_PYTHON": real_python,
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


def test_tuned_dry_run_orders_graph_evidence_before_child_resets_and_report_last() -> None:
    completed = _dry_run(
        arm="qwen-flash-next-compact-tuned",
        NEOCORTEX_BAKEOFF_CORPUS_PROFILE="compact",
        NEOCORTEX_ONTOLOGY_THINKING_EFFORT="false",
        NEOCORTEX_EXTRACTOR_THINKING_EFFORT="false",
        NEOCORTEX_LIBRARIAN_THINKING_EFFORT="false",
        NEOCORTEX_DOMAIN_CLASSIFIER_THINKING_EFFORT="false",
    )

    assert completed.returncode == 0, completed.stderr
    output = completed.stdout
    corpus_metrics = output.index("action=write_corpus_metrics")
    skip_export = output.index("action=export_skip_events")
    graph_export = output.index("action=export_graph_sample")
    metrics_merge = output.index("action=merge_consistency_metrics")
    first_child = output.index("+ e2e index=1")
    manifest_build = output.index("action=build_e2e_manifest")
    manifest_validate = output.index("e2e_manifest.py validate")
    report = output.index("action=generate_tuned_report")
    assert corpus_metrics < skip_export < graph_export < metrics_merge < first_child
    assert metrics_merge < manifest_build < manifest_validate < report
    assert "skip-events-qwen-flash-next-compact-tuned-test-run.json" in output
    assert "quality-sample-qwen-flash-next-compact-tuned-test-run.json" in output
    assert "effort_ontology=false" in output
    assert "effort_extractor=false" in output
    assert "effort_librarian=false" in output
    assert "effort_domain_classifier=false" in output


def test_tuned_run_records_safe_provenance_before_external_writes(
    fake_bakeoff_project: tuple[Path, dict[str, str], Path],
) -> None:
    project, env, _log_path = fake_bakeoff_project
    env.update(
        {
            "FAKE_INITIAL_PG_READY": "1",
            "FAKE_ASSERT_PLANNED": "1",
            "NEOCORTEX_BAKEOFF_RUN_ID": "tuned-provenance",
        }
    )

    completed = subprocess.run(
        [str(project / "scripts/model_bakeoff.sh"), "--arm", "qwen-flash-next-compact-tuned"],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    provenance = json.loads((project / "docs/plans/34-qwen-thinking-benchmark/validation/provenance.json").read_text())
    events = provenance["runs"]["tuned-provenance"]["events"]
    actions = [(event["status"], event["action"]) for event in events]
    for action in (
        "preserve_existing_graph",
        "reset_local_graph",
        "load_corpus",
        "save_measured_snapshot",
        "write_corpus_metrics",
        "export_skip_events",
        "export_graph_sample",
        "merge_consistency_metrics",
        "write_recall_evidence",
        "build_e2e_manifest",
        "generate_tuned_report",
        "restore_preserved_snapshot",
    ):
        assert actions.index(("planned", action)) < actions.index(("completed", action))
    encoded = json.dumps(provenance)
    assert "admin-token" not in encoded
    assert "mcp-secret" not in encoded
    assert any(event["action"] == "preserved_snapshot_identity" for event in events)
    child_observations = [line for line in _log_path.read_text().splitlines() if line.startswith("child_saw_planned=")]
    assert child_observations == [f"child_saw_planned=tuned-provenance.e2e.{index:02d}" for index in range(1, 6)]


def test_tuned_run_refuses_historical_artifact_collision_before_destructive_actions(
    fake_bakeoff_project: tuple[Path, dict[str, str], Path],
) -> None:
    project, env, log_path = fake_bakeoff_project
    resources = project / "docs/plans/33-local-qwen-migration/resources"
    resources.mkdir(parents=True)
    historical = resources / "qwen-parsing-report-qwen-flash-next-compact-tuned-test-run.json"
    historical.write_text('{"historical":true}\n')
    env["FAKE_INITIAL_PG_READY"] = "1"

    completed = subprocess.run(
        [str(project / "scripts/model_bakeoff.sh"), "--arm", "qwen-flash-next-compact-tuned"],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "refusing to overwrite historical run artifact" in completed.stderr
    assert historical.read_text() == '{"historical":true}\n'
    assert "start --fresh" not in (log_path.read_text() if log_path.exists() else "")


def test_tuned_provenance_records_the_actual_external_write_error(
    fake_bakeoff_project: tuple[Path, dict[str, str], Path],
) -> None:
    project, env, _log_path = fake_bakeoff_project
    env.update({"FAKE_INITIAL_PG_READY": "1", "FAKE_RECALL_STATUS": "19"})

    completed = subprocess.run(
        [str(project / "scripts/model_bakeoff.sh"), "--arm", "qwen-flash-next-compact-tuned"],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 19
    provenance = json.loads((project / "docs/plans/34-qwen-thinking-benchmark/validation/provenance.json").read_text())
    failed = [
        event
        for event in provenance["runs"]["test-run"]["events"]
        if event["status"] == "failed" and event["action"] == "write_recall_evidence"
    ]
    assert failed == [
        {
            "action": "write_recall_evidence",
            "at": failed[0]["at"],
            "exit_code": 19,
            "status": "failed",
            "target": "recall-results-qwen-flash-next-compact-tuned-test-run.json",
        }
    ]


def test_supervisor_defaults_reserve_600_seconds_inside_7200(tmp_path: Path) -> None:
    status_path = tmp_path / "supervisor.json"

    completed = subprocess.run(
        [
            sys.executable,
            str(SUPERVISOR),
            "--status",
            str(status_path),
            "--run-id",
            "test-run",
            "--arm",
            "test-arm",
            "--",
            "/usr/bin/true",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    status = json.loads(status_path.read_text())
    assert status["workload_budget_seconds"] == 6_600
    assert status["cleanup_reserve_seconds"] == 600
    assert status["total_budget_seconds"] == 7_200


def test_supervisor_timeout_waits_for_child_cleanup_then_restores_and_retains_diagnostics(
    fake_bakeoff_project: tuple[Path, dict[str, str], Path], tmp_path: Path
) -> None:
    project, env, log_path = fake_bakeoff_project
    private_parent = tmp_path / "private"
    private_parent.mkdir(mode=0o700)
    status_path = tmp_path / "supervisor.json"
    env.update(
        {
            "FAKE_INITIAL_PG_READY": "1",
            "FAKE_E2E_BLOCK": "1",
            "NEOCORTEX_BAKEOFF_PRIVATE_DIR": str(private_parent),
        }
    )
    sentinel = subprocess.Popen(["sleep", "30"], start_new_session=True)
    try:
        started = time.monotonic()
        completed = subprocess.run(
            [
                sys.executable,
                str(SUPERVISOR),
                "--status",
                str(status_path),
                "--run-id",
                "test-run",
                "--arm",
                "test",
                "--workload-seconds",
                "3",
                "--total-seconds",
                "6",
                "--",
                str(project / "scripts/model_bakeoff.sh"),
                "--arm",
                "test",
            ],
            cwd=project,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=8,
        )
        elapsed = time.monotonic() - started

        assert completed.returncode == 124, completed.stderr
        assert elapsed < 6
        assert sentinel.poll() is None
        assert "private_diagnostics_path=" in completed.stdout
        commands = log_path.read_text().splitlines()
        cleanup_end = commands.index("child_cleanup_end")
        restore = next(index for index, line in enumerate(commands) if "snapshot" in line and "load" in line)
        assert cleanup_end < restore
        assert sum("snapshot" in line and "load" in line for line in commands) == 1
        assert not any("start --fresh" in line for line in commands[restore + 1 :])
        assert list(private_parent.glob("neocortex-bakeoff.test-run.*"))
        status = json.loads(status_path.read_text())
        assert status["status"] == "TIMEOUT"
        assert status["run_id"] == "test-run"
        assert status["arm"] == "test"
        assert status["timed_out"] is True
        assert status["return_code"] == 124
        assert status["workload_wall_seconds"] >= 3
        assert status["total_wall_seconds"] >= status["workload_wall_seconds"]
    finally:
        sentinel.terminate()
        sentinel.wait(timeout=2)


def test_supervisor_preserves_restore_failure_status_after_timeout(
    fake_bakeoff_project: tuple[Path, dict[str, str], Path], tmp_path: Path
) -> None:
    project, env, _log_path = fake_bakeoff_project
    env.update({"FAKE_INITIAL_PG_READY": "1", "FAKE_E2E_BLOCK": "1", "FAKE_RESTORE_STATUS": "41"})

    completed = subprocess.run(
        [
            sys.executable,
            str(SUPERVISOR),
            "--status",
            str(tmp_path / "supervisor.json"),
            "--run-id",
            "test-run",
            "--arm",
            "test",
            "--workload-seconds",
            "3",
            "--total-seconds",
            "6",
            "--",
            str(project / "scripts/model_bakeoff.sh"),
            "--arm",
            "test",
        ],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=8,
    )

    assert completed.returncode == 3
    assert "restoration failure status=3 (original status=124)" in completed.stderr
    status = json.loads((tmp_path / "supervisor.json").read_text())
    assert status["status"] == "FAILED"
    assert status["return_code"] == 3


def _write_signal_fixture(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + body)
    path.chmod(0o755)


def test_supervisor_deadline_does_not_interrupt_natural_restore(tmp_path: Path) -> None:
    log_path = tmp_path / "signals.log"
    child = tmp_path / "natural-restore.sh"
    _write_signal_fixture(
        child,
        """
restore() {
  trap '' TERM INT
  : >"${NEOCORTEX_BAKEOFF_RECOVERY_MARKER:?}"
  printf 'restore_start\\n' >>"${SIGNAL_LOG:?}"
  sleep 1
  printf 'restore_end\\n' >>"${SIGNAL_LOG:?}"
}
trap restore EXIT
printf 'ready\n' >>"${SIGNAL_LOG:?}"
sleep 0.05 &
wait $!
""",
    )
    env = os.environ.copy()
    env["SIGNAL_LOG"] = str(log_path)

    completed = subprocess.run(
        [
            sys.executable,
            str(SUPERVISOR),
            "--status",
            str(tmp_path / "status.json"),
            "--run-id",
            "natural-restore",
            "--arm",
            "test",
            "--workload-seconds",
            "0.5",
            "--total-seconds",
            "3",
            "--",
            str(child),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=2,
    )

    assert completed.returncode == 0, completed.stderr
    assert log_path.read_text().splitlines() == ["ready", "restore_start", "restore_end"]


def test_supervisor_latches_external_stop_across_deadline_and_repeated_signals(tmp_path: Path) -> None:
    log_path = tmp_path / "signals.log"
    child = tmp_path / "external-stop.sh"
    child_body = """
restore() {
  trap '' TERM INT
  : >"${NEOCORTEX_BAKEOFF_RECOVERY_MARKER:?}"
  printf 'restore_start\\n' >>"${SIGNAL_LOG:?}"
  sleep 0.25
  printf 'restore_end\\n' >>"${SIGNAL_LOG:?}"
}
stop() {
  trap '' TERM INT
  printf 'cleanup_start\\n' >>"${SIGNAL_LOG:?}"
  sleep 0.45
  printf 'cleanup_end\\n' >>"${SIGNAL_LOG:?}"
  exit 124
}
trap restore EXIT
trap stop TERM INT
printf 'ready\n' >>"${SIGNAL_LOG:?}"
while :; do :; done
"""
    _write_signal_fixture(child, child_body)
    env = os.environ.copy()
    env["SIGNAL_LOG"] = str(log_path)
    process = subprocess.Popen(
        [
            sys.executable,
            str(SUPERVISOR),
            "--status",
            str(tmp_path / "status.json"),
            "--run-id",
            "external-stop",
            "--arm",
            "test",
            "--workload-seconds",
            "1",
            "--total-seconds",
            "3",
            "--",
            str(child),
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        if log_path.exists() and "ready" in log_path.read_text():
            break
        time.sleep(0.01)
    process.send_signal(signal.SIGTERM)
    deadline = time.monotonic() + 1.2
    while time.monotonic() < deadline:
        if log_path.exists() and "restore_start" in log_path.read_text():
            break
        time.sleep(0.01)
    process.send_signal(signal.SIGTERM)
    process.send_signal(signal.SIGINT)
    _stdout, stderr = process.communicate(timeout=2)

    assert process.returncode == 124, stderr
    assert log_path.read_text().splitlines() == [
        "ready",
        "cleanup_start",
        "cleanup_end",
        "restore_start",
        "restore_end",
    ]


def test_tuned_high_failure_summary_continues_as_report_only_evidence(
    fake_bakeoff_project: tuple[Path, dict[str, str], Path],
) -> None:
    project, env, log_path = fake_bakeoff_project
    summary = {"todo": 0, "doing": 0, "succeeded": 8, "failed": 1, "cancelled": 1, "total": 10}
    env.update(
        {
            "FAKE_INITIAL_PG_READY": "1",
            "FAKE_JOB_SUMMARY": json.dumps(summary),
            "FAKE_METRICS_STATUS": "22",
            "FAKE_MANIFEST_BUILD_STATUS": "24",
            "FAKE_REPORT_STATUS": "25",
            "FAKE_PRODUCER_UNAVAILABLE": "1",
        }
    )

    completed = subprocess.run(
        [str(project / "scripts/model_bakeoff.sh"), "--arm", "qwen-flash-next-compact-tuned"],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "stability status=FAIL; tuned REPORT continuation enabled" in completed.stdout
    assert len([line for line in log_path.read_text().splitlines() if line.startswith("e2e ")]) == 5
    resources = project / "docs/plans/33-local-qwen-migration/resources"
    recorded = json.loads((resources / "job-summary-qwen-flash-next-compact-tuned-test-run.json").read_text())
    assert recorded["job_summary"] == summary
    assert recorded["stability"] == {"status": "FAIL", "failed_or_cancelled_rate": 0.2}
    metrics = json.loads((resources / "metrics-qwen-flash-next-compact-tuned.json").read_text())
    assert metrics["status"] == "NOT_MEASURED"
    assert metrics["reason"] == "producer_expected_quality"
    assert metrics["job_summary"] == summary
    assert metrics["stability"]["status"] == "FAIL"
    manifest = json.loads((resources / "e2e-manifest-qwen-flash-next-compact-tuned-test-run.json").read_text())
    assert manifest["status"] == "NOT_MEASURED"
    assert manifest["reason"] == "producer_expected_quality"
    report = json.loads((resources / "qwen-parsing-report-qwen-flash-next-compact-tuned-test-run.json").read_text())
    assert report["status"] == "NOT_MEASURED"
    assert report["reason"] == "producer_expected_quality"
    assert "manifest_validate=yes" not in log_path.read_text()
    provenance = json.loads((project / "docs/plans/34-qwen-thinking-benchmark/validation/provenance.json").read_text())
    failures = {
        (event["action"], event["exit_code"])
        for event in provenance["runs"]["test-run"]["events"]
        if event["status"] == "failed" and "exit_code" in event
    }
    assert {("write_corpus_metrics", 22), ("build_e2e_manifest", 24), ("generate_tuned_report", 25)} <= failures


def test_timeout_during_active_jobs_writes_truthful_partial_evidence_and_restores(
    fake_bakeoff_project: tuple[Path, dict[str, str], Path],
) -> None:
    project, env, log_path = fake_bakeoff_project
    summary = {"todo": 2, "doing": 1, "succeeded": 7, "failed": 0, "cancelled": 0, "total": 10}
    env.update(
        {
            "FAKE_INITIAL_PG_READY": "1",
            "FAKE_JOB_SUMMARY": json.dumps(summary),
            "FAKE_POLL_IMMEDIATE_TIMEOUT": "1",
            "BAKEOFF_POLL_TIMEOUT": "1",
        }
    )

    sentinel = subprocess.Popen(["sleep", "30"], start_new_session=True)
    try:
        completed = subprocess.run(
            [str(project / "scripts/model_bakeoff.sh"), "--arm", "qwen-flash-next-compact-tuned"],
            cwd=project,
            env={**env, "NEOCORTEX_BAKEOFF_RUN_ID": "active-jobs"},
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        assert sentinel.poll() is None
    finally:
        sentinel.terminate()
        sentinel.wait(timeout=2)

    assert completed.returncode == 1, completed.stderr
    assert "job poll timed out" in completed.stderr
    resources = project / "docs/plans/33-local-qwen-migration/resources"
    recorded = json.loads((resources / "job-summary-qwen-flash-next-compact-tuned-active-jobs.json").read_text())
    assert recorded["job_summary"] == summary
    assert recorded["stability"]["status"] == "NOT_MEASURED"
    metrics = json.loads((resources / "metrics-qwen-flash-next-compact-tuned.json").read_text())
    assert metrics["status"] == "NOT_MEASURED"
    assert metrics["job_summary"] == summary
    sample = json.loads((resources / "quality-sample-qwen-flash-next-compact-tuned-active-jobs.json").read_text())
    assert sample["status"] == "NOT_MEASURED"
    assert "rows" not in sample and "sample_size" not in sample
    for artifact in (
        "recall-results-qwen-flash-next-compact-tuned-active-jobs.json",
        "skip-events-qwen-flash-next-compact-tuned-active-jobs.json",
        "qwen-parsing-report-qwen-flash-next-compact-tuned-active-jobs.json",
    ):
        assert json.loads((resources / artifact).read_text())["status"] == "NOT_MEASURED"
    assert (
        "Status: NOT_MEASURED"
        in (resources / "qwen-parsing-report-qwen-flash-next-compact-tuned-active-jobs.md").read_text()
    )
    manifest = json.loads((resources / "e2e-manifest-qwen-flash-next-compact-tuned-active-jobs.json").read_text())
    assert all(child["status"] == "NOT_MEASURED" and "exit_code" not in child for child in manifest["children"])
    commands = log_path.read_text().splitlines()
    service_stops = [index for index, line in enumerate(commands) if line.startswith("owned_service_stopped=")]
    finalizer_start = commands.index("finalizer_start")
    assert sum("snapshot" in line and "load" in line for line in commands) == 1
    restore = next(index for index, line in enumerate(commands) if "snapshot" in line and "load" in line)
    assert len(service_stops) == 2
    assert max(service_stops) < finalizer_start < restore
    assert any(line.startswith("owned_service_request=") for line in commands[:finalizer_start])
    assert not any(line.startswith("owned_service_request=") for line in commands[finalizer_start:])
    assert not any(line.startswith("e2e ") for line in commands)
    assert not any("start --fresh" in line for line in commands[restore + 1 :])


def test_malformed_job_summary_stops_owned_services_before_partial_finalizer(
    fake_bakeoff_project: tuple[Path, dict[str, str], Path],
) -> None:
    project, env, log_path = fake_bakeoff_project
    env.update({"FAKE_INITIAL_PG_READY": "1", "FAKE_JOB_SUMMARY": '{"todo":"unknown"}'})

    completed = subprocess.run(
        [str(project / "scripts/model_bakeoff.sh"), "--arm", "qwen-flash-next-compact-tuned"],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )

    assert completed.returncode == 2
    assert "job summary malformed" in completed.stderr
    commands = log_path.read_text().splitlines()
    stops = [index for index, line in enumerate(commands) if line.startswith("owned_service_stopped=")]
    finalizer = commands.index("finalizer_start")
    restore = next(index for index, line in enumerate(commands) if "snapshot" in line and "load" in line)
    assert len(stops) == 2
    assert max(stops) < finalizer < restore
    report = json.loads(
        (
            project
            / "docs/plans/33-local-qwen-migration/resources"
            / "qwen-parsing-report-qwen-flash-next-compact-tuned-test-run.json"
        ).read_text()
    )
    assert report["reason"] == "job_poll_malformed"


@pytest.mark.parametrize(
    ("failure_env", "failure_message"),
    [
        ({"FAKE_VERIFY_SERVICES_FAIL": "1"}, "identity verification failed status=74"),
        ({"BASH_ENV": "{kill_failure}"}, "group termination failed status=75"),
    ],
)
def test_unproven_owned_service_shutdown_skips_partial_finalization_and_preserves_unrelated_process(
    fake_bakeoff_project: tuple[Path, dict[str, str], Path],
    tmp_path: Path,
    failure_env: dict[str, str],
    failure_message: str,
) -> None:
    project, env, log_path = fake_bakeoff_project
    if failure_env.get("BASH_ENV") == "{kill_failure}":
        bash_env = tmp_path / "bash-env"
        bash_env.write_text(
            "kill() {\n"
            '  local last="${!#}"\n'
            '  if [[ "$last" == -* ]]; then return 75; fi\n'
            '  command kill "$@"\n'
            "}\n"
        )
        failure_env = {"BASH_ENV": str(bash_env)}
    env.update(
        {
            "FAKE_INITIAL_PG_READY": "1",
            "FAKE_JOB_SUMMARY": '{"todo":1,"doing":0,"succeeded":0,"failed":0,"cancelled":0,"total":1}',
            "FAKE_POLL_IMMEDIATE_TIMEOUT": "1",
            "BAKEOFF_POLL_TIMEOUT": "1",
            **failure_env,
        }
    )
    sentinel = subprocess.Popen(["sleep", "30"], start_new_session=True)
    try:
        completed = subprocess.run(
            [str(project / "scripts/model_bakeoff.sh"), "--arm", "qwen-flash-next-compact-tuned"],
            cwd=project,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        assert sentinel.poll() is None
    finally:
        sentinel.terminate()
        sentinel.wait(timeout=2)

    assert completed.returncode == 1
    assert failure_message in completed.stderr
    assert "unsafe poll-failure finalization skipped" in completed.stderr
    commands = log_path.read_text().splitlines()
    assert "finalizer_start" not in commands
    assert sum("snapshot" in line and "load" in line for line in commands) == 1
    assert not any(line.startswith("e2e ") for line in commands)


def test_report_only_infrastructure_failure_stops_without_launching_later_e2e(
    fake_bakeoff_project: tuple[Path, dict[str, str], Path],
) -> None:
    project, env, log_path = fake_bakeoff_project
    env.update(
        {
            "FAKE_INITIAL_PG_READY": "1",
            "FAKE_JOB_SUMMARY": '{"todo":0,"doing":0,"succeeded":8,"failed":1,"cancelled":1,"total":10}',
            "FAKE_METRICS_STATUS": "22",
        }
    )

    completed = subprocess.run(
        [str(project / "scripts/model_bakeoff.sh"), "--arm", "qwen-flash-next-compact-tuned"],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 22
    assert "failed without valid current-run NOT_MEASURED" in completed.stderr
    commands = log_path.read_text().splitlines()
    finalizer = commands.index("finalizer_start")
    stops = [index for index, line in enumerate(commands) if line.startswith("owned_service_stopped=")]
    assert len(stops) == 2 and max(stops) < finalizer
    assert not any(line.startswith("e2e ") for line in commands)
    assert sum("snapshot" in line and "load" in line for line in commands) == 1


def test_report_only_unavailable_writer_failure_preserves_status_and_restores(
    fake_bakeoff_project: tuple[Path, dict[str, str], Path],
) -> None:
    project, env, log_path = fake_bakeoff_project
    env.update(
        {
            "FAKE_INITIAL_PG_READY": "1",
            "FAKE_JOB_SUMMARY": '{"todo":0,"doing":0,"succeeded":8,"failed":1,"cancelled":1,"total":10}',
            "FAKE_METRICS_STATUS": "22",
            "FAKE_WRITE_UNAVAILABLE_FAIL": "1",
        }
    )

    completed = subprocess.run(
        [str(project / "scripts/model_bakeoff.sh"), "--arm", "qwen-flash-next-compact-tuned"],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 72
    assert "NOT_MEASURED evidence writer failed status=72" in completed.stderr
    commands = log_path.read_text().splitlines()
    assert "write_unavailable_failed=72" in commands
    assert not any(line.startswith("e2e ") for line in commands)
    assert sum("snapshot" in line and "load" in line for line in commands) == 1


def test_stale_unavailable_artifact_does_not_authorize_a_later_failed_producer(
    fake_bakeoff_project: tuple[Path, dict[str, str], Path],
) -> None:
    project, env, log_path = fake_bakeoff_project
    env.update(
        {
            "FAKE_INITIAL_PG_READY": "1",
            "FAKE_JOB_SUMMARY": '{"todo":0,"doing":0,"succeeded":8,"failed":1,"cancelled":1,"total":10}',
            "FAKE_METRICS_STATUS": "22",
            "FAKE_METRICS_MERGE_STATUS": "26",
            "FAKE_PRODUCER_UNAVAILABLE": "1",
        }
    )

    completed = subprocess.run(
        [str(project / "scripts/model_bakeoff.sh"), "--arm", "qwen-flash-next-compact-tuned"],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 26
    assert "action=merge_consistency_metrics status=26" in completed.stderr
    assert not any(line.startswith("e2e ") for line in log_path.read_text().splitlines())


def test_external_stop_during_e2e_finalizes_after_child_cleanup_then_restores(
    fake_bakeoff_project: tuple[Path, dict[str, str], Path], tmp_path: Path
) -> None:
    project, env, log_path = fake_bakeoff_project
    env.update({"FAKE_INITIAL_PG_READY": "1", "FAKE_E2E_BLOCK": "1"})
    process = subprocess.Popen(
        [
            sys.executable,
            str(SUPERVISOR),
            "--status",
            str(tmp_path / "status.json"),
            "--run-id",
            "active-e2e",
            "--arm",
            "qwen-flash-next-compact-tuned",
            "--workload-seconds",
            "10",
            "--total-seconds",
            "15",
            "--",
            str(project / "scripts/model_bakeoff.sh"),
            "--arm",
            "qwen-flash-next-compact-tuned",
        ],
        cwd=project,
        env={**env, "NEOCORTEX_BAKEOFF_RUN_ID": "active-e2e"},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if log_path.exists() and "child_blocking" in log_path.read_text():
            break
        time.sleep(0.01)
    assert "child_blocking" in log_path.read_text()
    process.send_signal(signal.SIGTERM)
    _stdout, stderr = process.communicate(timeout=5)

    assert process.returncode == 124, stderr
    commands = log_path.read_text().splitlines()
    cleanup_end = commands.index("child_cleanup_end")
    restore = next(index for index, line in enumerate(commands) if "snapshot" in line and "load" in line)
    assert cleanup_end < restore
    assert sum("snapshot" in line and "load" in line for line in commands) == 1
    manifest_path = (
        project
        / "docs/plans/33-local-qwen-migration/resources"
        / "e2e-manifest-qwen-flash-next-compact-tuned-active-e2e.json"
    )
    manifest = json.loads(manifest_path.read_text())
    assert manifest["status"] == "NOT_MEASURED"
    assert all(child["status"] == "NOT_MEASURED" for child in manifest["children"])


def test_partial_finalizer_preserves_existing_measured_artifact(tmp_path: Path) -> None:
    measured = tmp_path / "metrics.json"
    measured.write_text('{"status":"MEASURED","actual":17}\n')
    summary_path = tmp_path / "summary.json"
    subprocess.run(
        [
            sys.executable,
            str(PARTIAL_EVIDENCE),
            "record-summary",
            "--path",
            str(summary_path),
            "--run-id",
            "preserve",
            "--arm",
            "test",
            "--summary",
            '{"todo":0,"doing":0,"succeeded":1,"failed":0,"cancelled":0,"total":1}',
        ],
        check=True,
    )
    paths = {name: tmp_path / f"{name}.json" for name in ("recall", "manifest", "skip", "sample", "report")}
    completed = subprocess.run(
        [
            sys.executable,
            str(PARTIAL_EVIDENCE),
            "finalize",
            "--run-id",
            "preserve",
            "--arm",
            "test",
            "--reason",
            "workload_term",
            "--job-summary-path",
            str(summary_path),
            "--metrics-path",
            str(measured),
            "--recall-path",
            str(paths["recall"]),
            "--manifest-path",
            str(paths["manifest"]),
            "--skip-events-path",
            str(paths["skip"]),
            "--sample-path",
            str(paths["sample"]),
            "--report-json-path",
            str(paths["report"]),
            "--report-md-path",
            str(tmp_path / "report.md"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(measured.read_text()) == {"status": "MEASURED", "actual": 17}


def test_evidence_finalizer_failure_still_restores_snapshot(
    fake_bakeoff_project: tuple[Path, dict[str, str], Path], tmp_path: Path
) -> None:
    project, env, log_path = fake_bakeoff_project
    env.update(
        {
            "FAKE_INITIAL_PG_READY": "1",
            "FAKE_JOB_SUMMARY": '{"todo":2,"doing":0,"succeeded":8,"failed":0,"cancelled":0,"total":10}',
            "FAKE_PARTIAL_EVIDENCE_FAIL": "1",
        }
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(SUPERVISOR),
            "--status",
            str(tmp_path / "status.json"),
            "--run-id",
            "finalizer-fails",
            "--arm",
            "qwen-flash-next-compact-tuned",
            "--workload-seconds",
            "2",
            "--total-seconds",
            "6",
            "--",
            str(project / "scripts/model_bakeoff.sh"),
            "--arm",
            "qwen-flash-next-compact-tuned",
        ],
        cwd=project,
        env={**env, "NEOCORTEX_BAKEOFF_RUN_ID": "finalizer-fails"},
        capture_output=True,
        text=True,
        check=False,
        timeout=7,
    )

    assert completed.returncode == 124
    assert "partial evidence finalizer failed status=71" in completed.stderr
    assert sum("snapshot" in line and "load" in line for line in log_path.read_text().splitlines()) == 1


def test_child_planned_provenance_failure_is_fail_closed_and_restores(
    fake_bakeoff_project: tuple[Path, dict[str, str], Path],
) -> None:
    project, env, log_path = fake_bakeoff_project
    env.update({"FAKE_INITIAL_PG_READY": "1", "FAKE_PROVENANCE_CHILD_FAILURE": "1"})

    completed = subprocess.run(
        [str(project / "scripts/model_bakeoff.sh"), "--arm", "qwen-flash-next-compact-tuned"],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 73
    commands = log_path.read_text().splitlines()
    assert not any(line.startswith("e2e ") for line in commands)
    assert sum("snapshot" in line and "load" in line for line in commands) == 1
    provenance = json.loads((project / "docs/plans/34-qwen-thinking-benchmark/validation/provenance.json").read_text())
    assert provenance["runs"]["test-run"]["events"]


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
    (bin_dir / "curl").write_text("""#!/usr/bin/env bash
set -euo pipefail
printf 'curl %s\\n' "$*" >>"${FAKE_COMMAND_LOG:?}"
""")
    for command in (scripts / "run_e2e.sh", scripts / "manage.sh", bin_dir / "uv", bin_dir / "curl"):
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
    commands = log_path.read_text().splitlines()
    assert commands[-1] == expected_cleanup
    test_index = commands.index(f"uv run python {test_script}")
    health_calls = [index for index, command in enumerate(commands) if command.startswith("curl -sf ")]
    assert len(health_calls) == 2
    assert all(index < test_index for index in health_calls)


def test_run_e2e_term_cleans_up_once_and_exits_143(tmp_path: Path) -> None:
    project = tmp_path / "project"
    scripts = project / "scripts"
    bin_dir = tmp_path / "bin"
    scripts.mkdir(parents=True)
    bin_dir.mkdir()
    shutil.copy2(RUN_E2E_SCRIPT, scripts / "run_e2e.sh")
    test_script = project / "test_script.py"
    test_script.write_text("# fake blocking e2e\n")
    log_path = tmp_path / "commands.log"
    (scripts / "manage.sh").write_text('#!/usr/bin/env bash\nprintf \'manage %s\\n\' "$*" >>"${FAKE_COMMAND_LOG:?}"\n')
    (bin_dir / "uv").write_text(
        "#!/usr/bin/env bash\n"
        'printf \'uv %s\\n\' "$*" >>"${FAKE_COMMAND_LOG:?}"\n'
        "sleep 30 &\n"
        "child_pid=$!\n"
        'printf \'uv READY child=%s\\n\' "$child_pid" >>"${FAKE_COMMAND_LOG:?}"\n'
        'wait "$child_pid"\n'
    )
    (bin_dir / "curl").write_text("#!/usr/bin/env bash\nexit 0\n")
    for command in (scripts / "run_e2e.sh", scripts / "manage.sh", bin_dir / "uv", bin_dir / "curl"):
        command.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "FAKE_COMMAND_LOG": str(log_path),
            "KEEP_POSTGRES_RUNNING": "1",
        }
    )
    process = subprocess.Popen(
        [str(scripts / "run_e2e.sh"), str(test_script)],
        cwd=project,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    deadline = time.monotonic() + 2
    while (not log_path.exists() or "uv READY child=" not in log_path.read_text()) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert "uv READY child=" in log_path.read_text()
    os.killpg(process.pid, signal.SIGTERM)
    _stdout, stderr = process.communicate(timeout=2)

    assert process.returncode == 143, stderr
    assert log_path.read_text().splitlines().count("manage stop") == 1


def test_bash_syntax_is_valid() -> None:
    completed = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr
