"""Keep reduced bake-off input explicit, strict, and traceable."""

from __future__ import annotations

import asyncio
import hashlib
import os
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from scripts import compute_metrics  # ty: ignore[unresolved-import]
from scripts.corpus_loader import (  # ty: ignore[unresolved-import]
    COMPACT_CORPUS,
    CORPUS,
    CORPUS_EPISODE_IDS,
    load_corpus,
)

ROOT = Path(__file__).parents[2]


def test_compact_corpus_retains_original_ids_and_reduces_input() -> None:
    compact = load_corpus(profile="compact")
    full = load_corpus()
    assert tuple(episode["number"] for episode in compact) == CORPUS_EPISODE_IDS["compact"]
    assert (
        sum(len(str(episode["text"])) for episode in compact) < sum(len(str(episode["text"])) for episode in full) / 3
    )


@pytest.mark.parametrize("profile,path", [("full", CORPUS), ("compact", COMPACT_CORPUS)])
@pytest.mark.parametrize("corruption", ["duplicate", "reordered", "missing", "empty", "wrong_profile"])
def test_corpus_rejects_incorrect_episode_set(tmp_path: Path, profile: str, path: Path, corruption: str) -> None:
    text = path.read_text()
    first, second = CORPUS_EPISODE_IDS[profile][:2]
    if corruption == "duplicate":
        text = text.replace(f"### Episode {second} --", f"### Episode {first} --")
    elif corruption == "reordered":
        text = text.replace(f"### Episode {first} --", "### Episode TEMP --")
        text = text.replace(f"### Episode {second} --", f"### Episode {first} --")
        text = text.replace("### Episode TEMP --", f"### Episode {second} --")
    elif corruption == "missing":
        text = text.replace(f"### Episode {first} --", f"### Missing {first} --")
    elif corruption == "empty":
        text = ""
    else:
        text = (CORPUS if profile == "compact" else COMPACT_CORPUS).read_text()
    selected = tmp_path / "episodes.md"
    selected.write_text(text)
    with pytest.raises(ValueError, match="expected episode IDs"):
        load_corpus(selected, profile=profile)


def test_compact_dry_run_propagates_profile_and_scales_deadline() -> None:
    env = os.environ.copy()
    env.update(
        NEOCORTEX_BAKEOFF_CORPUS_PROFILE="full",  # CLI must win.
        NEOCORTEX_LOCAL_MODEL_TIMEOUT_S="37",
        NEOCORTEX_WORKER_CONCURRENCY="2",
        NEOCORTEX_DOMAIN_ROUTING_ENABLED="true",
    )
    env.pop("BAKEOFF_POLL_TIMEOUT", None)
    result = subprocess.run(
        ["./scripts/model_bakeoff.sh", "--arm", "compact-test", "--corpus-profile", "compact", "--dry-run"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "corpus_profile=compact" in result.stdout
    assert "corpus_size=8" in result.stdout
    assert "corpus_path=docs/plans/33-local-qwen-migration/resources/compact-corpus.md" in result.stdout
    assert "operational_acceptance_stage_invocations=1560" in result.stdout
    assert "poll_timeout_s=28920" in result.stdout
    for script in ("corpus_loader.py", "compute_metrics.py", "recall_scorer.py"):
        commands = [line for line in result.stdout.splitlines() if script in line and line.startswith("+")]
        assert commands
        assert all("--corpus-profile compact" in line for line in commands)


def test_metrics_record_actual_compact_source(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = AsyncMock()
    connection.fetch.return_value = []
    monkeypatch.setattr(compute_metrics.asyncpg, "connect", AsyncMock(return_value=connection))
    monkeypatch.setattr(compute_metrics, "_git_metadata", lambda: {})
    monkeypatch.setattr(
        compute_metrics,
        "fetch_job_summary",
        AsyncMock(
            return_value={
                "todo": 0,
                "doing": 0,
                "succeeded": 8,
                "failed": 0,
                "cancelled": 0,
                "total": 8,
            }
        ),
    )
    result = asyncio.run(
        compute_metrics.collect(
            "compact-test",
            "corpus",
            corpus_profile="compact",
            admin_token="test-token",
            run_id="test-run",
        )
    )
    metadata = result["run_metadata"]
    assert metadata["corpus_profile"] == "compact"
    assert metadata["corpus_episode_ids"] == list(CORPUS_EPISODE_IDS["compact"])
    assert metadata["corpus_size"] == 8
    assert metadata["corpus_sha256"] == hashlib.sha256(COMPACT_CORPUS.read_bytes()).hexdigest()
    assert result["input_paths"]["corpus"] == str(COMPACT_CORPUS.relative_to(ROOT))
    connection.close.assert_awaited_once()


def test_compact_episode_contents_match_original_source_exactly() -> None:
    full = {episode["number"]: episode for episode in load_corpus()}
    for episode in load_corpus(profile="compact"):
        assert episode == full[episode["number"]]


def test_compact_report_schema_requires_each_selected_key_once() -> None:
    import json

    from jsonschema import Draft202012Validator

    schema = json.loads((COMPACT_CORPUS.parent / "qwen-parsing-report-compact.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    # Exercise the actual schema's set/cardinality constraints separately from
    # episode payload validation: duplicate IDs must fail even with different payloads.
    constraints = dict(schema["properties"]["episodes"])
    constraints.pop("items")
    validator = Draft202012Validator(constraints)
    rows = [{"episode_key": f"E{number:02d}"} for number in CORPUS_EPISODE_IDS["compact"]]
    validator.validate(rows)
    for invalid in (
        rows[:-1],
        [*rows, {"episode_key": "E01"}],
        [*rows[:-1], {"episode_key": "E02", "different": True}],
    ):
        assert list(validator.iter_errors(invalid))
