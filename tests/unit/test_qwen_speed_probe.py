"""Deterministic tests for the Qwen speed probe and its pipeline hooks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from scripts import qwen_speed_probe as probe  # ty: ignore[unresolved-import]

from neocortex.db.mock import InMemoryRepository
from neocortex.extraction.agents import AgentInferenceConfig
from neocortex.extraction.pipeline import run_extraction
from neocortex.extraction.schemas import ExtractedEntity, ExtractedRelation, ExtractionResult

AGENT = "qwen_speed_probe"
TEST_CONFIG = AgentInferenceConfig(use_test_model=True)


def _record(event: str, **fields: Any) -> dict[str, Any]:
    return {"event": event, "fields": fields}


def _extraction() -> ExtractionResult:
    return ExtractionResult(
        entities=[
            ExtractedEntity(name="Alpha", type_name="Person", description="an engineer", importance=0.7),
            ExtractedEntity(name="Beta", type_name="Project", description="a service"),
        ],
        relations=[ExtractedRelation(source_name="Alpha", target_name="Beta", relation_type="WORKS_ON")],
        rationale="fixture",
    )


# ── Aggregation ──


def test_aggregate_stage_rows_two_stages_one_timeout() -> None:
    """A finished stage reports ok; a started-but-unfinished stage inherits the outcome."""
    records = [
        _record("agent_run_started", agent="ontology"),
        _record(
            "agent_usage",
            stage="ontology_agent",
            requests=1,
            tool_calls=2,
            input_tokens=900,
            output_tokens=120,
            reasoning_tokens=None,
        ),
        _record("stage_timing", stage="ontology_agent", elapsed_s=41.5),
        _record("agent_run_started", agent="extractor"),
        _record("stage_timing", stage="metadata_fetch", elapsed_s=0.01),
    ]

    rows = probe.aggregate_stage_rows("E04", records, outcome="timeout")

    assert [row["stage"] for row in rows] == ["ontology", "extractor"]
    ontology, extractor = rows
    assert ontology == {
        "episode": "E04",
        "stage": "ontology",
        "seconds": 41.5,
        "requests": 1,
        "tool_calls": 2,
        "input_tokens": 900,
        "output_tokens": 120,
        "reasoning_tokens": 0,
        "entities": None,
        "relations": None,
        "status": "ok",
    }
    assert extractor["status"] == "timeout"
    assert extractor["seconds"] is None
    assert extractor["requests"] == 0


def test_aggregate_stage_rows_records_cardinality_and_trajectory() -> None:
    """Extractor cardinality and bounded-librarian diagnostics land on their rows."""
    records = [
        _record("extractor_cardinality", stage="extractor_agent", entity_count=30, relation_count=33),
        _record("stage_timing", stage="extractor_agent", elapsed_s=431.9),
        _record(
            "agent_usage",
            stage="librarian_agent",
            requests=42,
            tool_calls=61,
            input_tokens=430_000,
            output_tokens=9_000,
            reasoning_tokens=6_800,
        ),
        _record("stage_timing", stage="librarian_agent", elapsed_s=1200.0),
        _record(
            "librarian_trajectory",
            stage="librarian_agent",
            requests=42,
            reads=12,
            mutations_succeeded=30,
            hard_reason="no_progress",
        ),
    ]

    rows = {row["stage"]: row for row in probe.aggregate_stage_rows("E05", records)}

    assert rows["extractor"]["entities"] == 30
    assert rows["extractor"]["relations"] == 33
    assert rows["extractor"]["seconds"] == 431.9
    assert rows["librarian"]["reasoning_tokens"] == 6_800
    assert rows["librarian"]["trajectory"] == {
        "requests": 42,
        "reads": 12,
        "mutations_succeeded": 30,
        "hard_reason": "no_progress",
    }


def test_aggregate_stage_rows_ignores_non_agent_stages() -> None:
    """Book-keeping stage timings never create rows."""
    records = [
        _record("stage_timing", stage="metadata_fetch", elapsed_s=0.02),
        _record("stage_timing", stage="type_persist", elapsed_s=0.01),
        _record("stage_timing", stage="embedding_precompute", elapsed_s=1.4),
    ]

    assert probe.aggregate_stage_rows("E02", records) == []


# ── Cache ──


def test_cache_key_is_setup_specific() -> None:
    """The key separates episodes, models, thinking levels, and test-model runs."""
    base = probe.cache_key("E04", "local:qwen3.8-flash-next", "low", "abc", test_model=False)
    assert base.startswith("E04-")
    assert len(base) == len("E04-") + 12
    assert base != probe.cache_key("E05", "local:qwen3.8-flash-next", "low", "abc", test_model=False)
    assert base != probe.cache_key("E04", "local:other", "low", "abc", test_model=False)
    assert base != probe.cache_key("E04", "local:qwen3.8-flash-next", False, "abc", test_model=False)
    assert base != probe.cache_key("E04", "local:qwen3.8-flash-next", "low", "def", test_model=False)
    assert base != probe.cache_key("E04", "local:qwen3.8-flash-next", "low", "abc", test_model=True)


def test_cache_round_trip(tmp_path: Path) -> None:
    """A written cache entry loads back as an equal ExtractionResult plus ontology."""
    result = _extraction()
    node_types = [{"name": "Person", "description": "a human"}]
    edge_types = [{"name": "WORKS_ON", "description": ""}]

    path = probe.save_cached_extraction(tmp_path, "E04-deadbeef1234", result, node_types, edge_types)
    loaded, ontology = probe.load_cached_extraction(tmp_path, "E04-deadbeef1234")

    assert path == tmp_path / "E04-deadbeef1234.json"
    assert loaded == result
    assert ontology == {"node_types": node_types, "edge_types": edge_types}


def test_type_snapshot_normalizes_missing_descriptions() -> None:
    from neocortex.schemas.memory import TypeInfo

    snapshot = probe.type_snapshot([TypeInfo(id=1, name="Person", description=None)])

    assert snapshot == [{"name": "Person", "description": ""}]


# ── Pipeline hooks ──


@pytest.mark.asyncio
async def test_precomputed_skips_ontology_and_extractor_agents() -> None:
    """A cached extraction runs the librarian only — no ontology/extractor model runs."""
    repo = InMemoryRepository()
    episode_id = await repo.store_episode(AGENT, "Alpha works on Beta.")
    started: list[str] = []
    stages: list[str] = []

    def collect(record: Any) -> None:
        fields = record.record["extra"]
        if record.record["message"] == "agent_run_started":
            started.append(str(fields.get("agent")))
        elif record.record["message"] == "stage_timing":
            stages.append(str(fields.get("stage")))

    from loguru import logger

    sink_id = logger.add(collect, level="DEBUG", filter=lambda r: bool(r["extra"].get("action_log")))
    try:
        await run_extraction(
            repo=repo,
            embeddings=None,
            agent_id=AGENT,
            episode_ids=[episode_id],
            ontology_config=TEST_CONFIG,
            extractor_config=TEST_CONFIG,
            librarian_config=TEST_CONFIG,
            precomputed={episode_id: _extraction()},
        )
    finally:
        logger.remove(sink_id)

    assert started == ["librarian"]
    assert "ontology_agent" not in stages
    assert "extractor_agent" not in stages
    assert "librarian_agent" in stages


@pytest.mark.asyncio
async def test_on_extracted_receives_the_extractor_output() -> None:
    """The hook fires once per real extractor run with that episode's result."""
    repo = InMemoryRepository()
    episode_id = await repo.store_episode(AGENT, "Alpha works on Beta.")
    captured: list[tuple[int, ExtractionResult]] = []

    async def capture(extracted_id: int, result: ExtractionResult) -> None:
        captured.append((extracted_id, result))

    await run_extraction(
        repo=repo,
        embeddings=None,
        agent_id=AGENT,
        episode_ids=[episode_id],
        ontology_config=TEST_CONFIG,
        extractor_config=TEST_CONFIG,
        librarian_config=TEST_CONFIG,
        on_extracted=capture,
    )

    assert len(captured) == 1
    assert captured[0][0] == episode_id
    assert isinstance(captured[0][1], ExtractionResult)


@pytest.mark.asyncio
async def test_on_extracted_not_called_for_precomputed_episode() -> None:
    """A skipped extractor stage has nothing new to cache."""
    repo = InMemoryRepository()
    episode_id = await repo.store_episode(AGENT, "Alpha works on Beta.")
    captured: list[int] = []

    async def capture(extracted_id: int, result: ExtractionResult) -> None:
        del result
        captured.append(extracted_id)

    await run_extraction(
        repo=repo,
        embeddings=None,
        agent_id=AGENT,
        episode_ids=[episode_id],
        ontology_config=TEST_CONFIG,
        extractor_config=TEST_CONFIG,
        librarian_config=TEST_CONFIG,
        precomputed={episode_id: _extraction()},
        on_extracted=capture,
    )

    assert captured == []


# ── CLI ──


def test_cli_defaults() -> None:
    args = probe.build_parser().parse_args([])

    assert args.episodes == ["E04", "E05"]
    assert args.model == "local:qwen3.8-flash-next"
    assert args.thinking == "low"
    assert args.episode_timeout == 900.0
    assert args.repo == "fresh"
    assert args.stage == "all"
    assert args.cache_dir == probe.CACHE_DIR
    assert args.output is None
    assert args.test_model is False
    assert args.profile is None
    assert args.classify is False


def test_thinking_off_maps_to_false() -> None:
    """``--thinking off`` reaches the agent config as ``thinking_effort=False``."""
    args = probe.build_parser().parse_args(["--thinking", "off"])

    assert probe.THINKING[args.thinking] is False
    assert probe.THINKING["low"] == "low"
    config = AgentInferenceConfig(use_test_model=True, thinking_effort=probe.THINKING[args.thinking])
    assert config.thinking_effort is False
    assert (config.model_settings or {}).get("thinking") is False


def test_local_endpoint_defaults_to_the_probe_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEOCORTEX_LOCAL_MODEL_BASE_URL", raising=False)
    monkeypatch.delenv("NEOCORTEX_LOCAL_MODEL_API_KEY_ENV", raising=False)

    endpoint = probe.resolve_local_endpoint(1500.0)

    assert endpoint.base_url == "http://127.0.0.1:24000/v1"
    assert endpoint.api_key_env == "LITELLM_API_KEY"
    assert endpoint.timeout_s == 1500.0


# ── End to end with TestModel ──


@pytest.mark.asyncio
async def test_test_model_run_over_two_episodes(tmp_path: Path) -> None:
    """A --test-model run needs no endpoint and writes a counts-only summary."""
    import sys

    from loguru import logger

    output = tmp_path / "summary.json"
    try:
        exit_code = await probe.main(
            [
                "--test-model",
                "--episodes",
                "E02",
                "E04",
                "--repo",
                "shared",
                "--cache-dir",
                str(tmp_path / "cache"),
                "--output",
                str(output),
            ]
        )
    finally:
        # ``probe.main`` installs its own loguru sinks; restore a plain one for
        # the rest of the session.
        logger.remove()
        logger.add(sys.stderr)

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["run"]["model"] == "test-model"
    assert payload["run"]["repo_mode"] == "shared"
    assert payload["run"]["embeddings"] == "none"
    assert [episode["episode"] for episode in payload["episodes"]] == ["E02", "E04"]
    assert all(episode["status"] == "ok" for episode in payload["episodes"])
    assert {row["stage"] for row in payload["stages"]} == {"ontology", "extractor", "librarian"}
    assert all(episode["words"] > 0 for episode in payload["episodes"])
