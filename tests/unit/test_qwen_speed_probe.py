"""Deterministic tests for the Qwen speed probe and its pipeline hooks."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from scripts import qwen_speed_probe as probe  # ty: ignore[unresolved-import]

from neocortex.db.mock import InMemoryRepository
from neocortex.extraction.agents import AgentInferenceConfig
from neocortex.extraction.pipeline import run_extraction
from neocortex.extraction.schemas import ExtractedEntity, ExtractedRelation, ExtractionResult

AGENT = "qwen_speed_probe"
TEST_CONFIG = AgentInferenceConfig(use_test_model=True)
FIXTURE_PATH = Path(__file__).resolve().parents[2] / "docs/plans/34-qwen-thinking-benchmark/resources/fact-fixture.json"


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


def test_critical_defects_are_scoped_and_use_only_code_owned_reasons() -> None:
    """Graph leaks, malformed types, terminal validation, and unknown tools are observable."""
    before = probe.GraphView(nodes=[], edges=[], node_type_names={}, edge_type_names={})
    after = probe.GraphView(
        nodes=[
            SimpleNamespace(
                id=1,
                type_id=1,
                name="safe node",
                content="<think>private reasoning</think>",
                properties={},
            )
        ],
        edges=[SimpleNamespace(id=1, source_id=1, target_id=1, type_id=2, weight=1.0, properties={})],
        node_type_names={1: "bad node type"},
        edge_type_names={2: "bad-edge-type"},
    )
    records = [
        _record("tool_call_failed", tool="unknown"),
        _record("tool_validation_rejected", retry=2, max_retries=2),
        _record("agent_run_failed"),
    ]

    defects = probe.detect_critical_defects(before, after, records, "error:UnexpectedModelBehavior")

    assert defects == [
        "agent_run_failure",
        "invalid_edge_type",
        "invalid_node_type",
        "reasoning_marker",
        "tool_call_failure",
        "unknown_tool",
        "validation_failure",
    ]
    assert "private reasoning" not in json.dumps(defects)


def test_critical_defects_ignore_unchanged_graph_content_and_recovered_retries() -> None:
    """A prior unit's leak and a retry that later succeeded do not taint this unit."""
    existing = SimpleNamespace(
        id=1,
        type_id=1,
        name="Existing",
        content="<think>older unit</think>",
        properties={},
    )
    before = probe.GraphView(nodes=[existing], edges=[], node_type_names={1: "Person"}, edge_type_names={})
    after = probe.GraphView(nodes=[existing], edges=[], node_type_names={1: "Person"}, edge_type_names={})

    assert probe.detect_critical_defects(before, after, [_record("output_validation_retry", retry=1)], "ok") == []


@pytest.mark.parametrize(
    ("name", "normalizer", "expected"),
    [
        ("Person", probe.normalize_node_type, True),
        ("DishGreg", probe.normalize_node_type, False),
        ("Functiondefault", probe.normalize_node_type, False),
        ("WORKS_ON", probe.normalize_edge_type, True),
        ("FUNCTIONDEFAULT", probe.normalize_edge_type, False),
    ],
)
def test_type_validation_uses_the_repository_normalizers(name: str, normalizer: Any, expected: bool) -> None:
    """Instance-level and tool-artifact names cannot pass a copied subset of the rules."""
    assert probe._valid_type_name(name, normalizer) is expected


async def _run_text_with_model(
    monkeypatch: pytest.MonkeyPatch,
    model_type: type,
    *,
    episode_timeout: float,
) -> tuple[str, list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    from loguru import logger

    from neocortex.extraction import agents as extraction_agents

    monkeypatch.setattr(extraction_agents, "TestModel", model_type)
    args = probe.build_parser().parse_args(["--test-model", "--episode-timeout", str(episode_timeout)])
    levels = probe.resolve_thinking_levels(args)
    configs = probe.build_configs(args, levels, probe.resolve_local_endpoint(args.per_call_timeout))
    collector = probe.ActionLogCollector()
    sink_id = logger.add(collector, level="DEBUG", filter=lambda record: bool(record["extra"].get("action_log")))
    try:
        _seconds, outcome, rows, defects = await probe.run_text(
            "E04",
            "Alpha works on Beta.",
            0.5,
            InMemoryRepository(),
            args,
            collector,
            configs,
            levels,
            None,
            "corpus-hash",
            None,
        )
    finally:
        logger.remove(sink_id)
    return outcome, rows, defects, collector.records


@pytest.mark.asyncio
async def test_episode_timeout_is_not_a_critical_agent_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Outer wait_for cancellation remains an allowed timeout observation."""
    import asyncio

    from pydantic_ai.models.test import TestModel

    class SlowTestModel(TestModel):
        async def request(self, messages: Any, model_settings: Any, model_request_parameters: Any) -> Any:
            await asyncio.sleep(0.2)
            return await super().request(messages, model_settings, model_request_parameters)

    outcome, rows, defects, records = await _run_text_with_model(monkeypatch, SlowTestModel, episode_timeout=0.01)

    assert outcome == "timeout"
    assert [(row["stage"], row["status"]) for row in rows] == [("ontology", "timeout")]
    assert defects == []
    assert any(
        record["event"] == "agent_run_failed" and record["fields"]["error_type"] == "CancelledError"
        for record in records
    )


@pytest.mark.asyncio
async def test_provider_timeout_is_normalized_and_not_a_critical_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """The OpenAI client timeout class counts as timeout, not model corruption."""
    import httpx
    from openai import APITimeoutError
    from pydantic_ai.models.test import TestModel

    class ProviderTimeoutModel(TestModel):
        async def request(self, messages: Any, model_settings: Any, model_request_parameters: Any) -> Any:
            raise APITimeoutError(request=httpx.Request("POST", "http://test.invalid/v1/chat/completions"))

    outcome, rows, defects, records = await _run_text_with_model(monkeypatch, ProviderTimeoutModel, episode_timeout=1)

    assert outcome == "timeout"
    assert [(row["stage"], row["status"]) for row in rows] == [("ontology", "timeout")]
    assert defects == []
    assert {
        (record["event"], record["fields"].get("error_type"))
        for record in records
        if record["event"].endswith("failed")
    } == {("model_request_failed", "APITimeoutError"), ("agent_run_failed", "APITimeoutError")}


@pytest.mark.asyncio
async def test_classifier_provider_timeout_is_normalized(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The probe-local classifier TestModel applies the same timeout status."""
    import httpx
    import pydantic_ai.models.test
    from openai import APITimeoutError
    from pydantic_ai.models.test import TestModel

    class ProviderTimeoutModel(TestModel):
        async def request(self, messages: Any, model_settings: Any, model_request_parameters: Any) -> Any:
            raise APITimeoutError(request=httpx.Request("POST", "http://test.invalid/v1/chat/completions"))

    monkeypatch.setattr(pydantic_ai.models.test, "TestModel", ProviderTimeoutModel)
    args = probe.build_parser().parse_args(["--test-model", "--classify"])
    levels = probe.resolve_thinking_levels(args)
    config = probe.build_configs(args, levels, probe.resolve_local_endpoint(args.per_call_timeout))["classifier"]

    _seconds, status, matched, proposed = await probe._classify(
        "Alpha works on Beta.", "E04", 1, config, probe.THINKING[levels["classifier"]], 1, tmp_path
    )

    assert (status, matched, proposed) == ("timeout", 0, 0)


def test_timeout_does_not_hide_an_independent_stored_marker() -> None:
    """Suppressing cancellation events must not suppress graph integrity defects."""
    before = probe.GraphView(nodes=[], edges=[], node_type_names={}, edge_type_names={})
    after = probe.GraphView(
        nodes=[SimpleNamespace(id=1, type_id=1, name="Safe", content="<think>leak</think>", properties={})],
        edges=[],
        node_type_names={1: "Person"},
        edge_type_names={},
    )
    records = [_record("agent_run_failed", error_type="CancelledError")]

    assert probe.detect_critical_defects(before, after, records, "timeout") == ["reasoning_marker"]


# ── Cache ──


def test_cache_key_is_setup_specific() -> None:
    """The key separates episodes, models, thinking levels, and test-model runs."""
    base = probe.cache_key("E04", "local:qwen3.8-flash-next", "low", "abc", "episode text", test_model=False)
    assert base.startswith("E04-")
    assert len(base) == len("E04-") + 12
    assert base != probe.cache_key("E05", "local:qwen3.8-flash-next", "low", "abc", "episode text", test_model=False)
    assert base != probe.cache_key("E04", "local:other", "low", "abc", "episode text", test_model=False)
    assert base != probe.cache_key("E04", "local:qwen3.8-flash-next", False, "abc", "episode text", test_model=False)
    assert base != probe.cache_key("E04", "local:qwen3.8-flash-next", "low", "def", "episode text", test_model=False)
    assert base != probe.cache_key("E04", "local:qwen3.8-flash-next", "low", "abc", "episode text", test_model=True)
    # A cache entry holds the ontology and extractor agents' output, so both of
    # their levels separate keys; omitting either would let a rerun reuse an
    # extraction produced at a different level.
    assert base == probe.cache_key(
        "E04", "local:qwen3.8-flash-next", "low", "abc", "episode text", test_model=False, ontology_thinking="low"
    )
    assert base != probe.cache_key(
        "E04", "local:qwen3.8-flash-next", "low", "abc", "episode text", test_model=False, ontology_thinking="high"
    )
    assert base != probe.cache_key(
        "E04", "local:qwen3.8-flash-next", "low", "abc", "episode text", test_model=False, extractor_thinking="high"
    )


def test_triplet_cache_key_includes_fixture_text_and_revision() -> None:
    """Changed S05 fixture content or revision cannot reuse an earlier extraction."""
    kwargs = {"test_model": False, "fixture_revision": 1}
    base = probe.cache_key("S05-1", "local:qwen3.8-flash-next", "off", "corpus", "April 15", **kwargs)

    assert base != probe.cache_key("S05-1", "local:qwen3.8-flash-next", "off", "corpus", "May 1", **kwargs)
    assert base != probe.cache_key(
        "S05-1",
        "local:qwen3.8-flash-next",
        "off",
        "corpus",
        "April 15",
        test_model=False,
        fixture_revision=2,
    )


def test_cache_key_ignores_the_librarian_and_classifier_levels() -> None:
    """Stage 6's librarian sweep reuses one extraction across librarian levels.

    The librarian never influences the cached artifacts (an ``ExtractionResult``
    plus the ontology snapshot it was produced against), and a single-valued
    ``--cache-thinking`` cannot express a per-agent key — so folding the
    librarian level in would miss the cache at every cell and re-run extraction.
    The requirement that a librarian-only rerun cannot silently reuse a foreign
    extraction is met by the *extractor* level being in the key.
    """
    import inspect

    parameters = inspect.signature(probe.cache_key).parameters
    assert "librarian_thinking" not in parameters
    assert "classifier_thinking" not in parameters

    def key_for(argv: list[str]) -> str:
        args = probe.build_parser().parse_args(argv)
        levels = probe.resolve_thinking_levels(args)
        return probe.cache_key(
            "E04",
            args.model,
            probe.THINKING[args.cache_thinking or args.thinking],
            "abc",
            "episode text",
            test_model=args.test_model,
            ontology_thinking=probe.THINKING[levels["ontology"]],
            extractor_thinking=probe.THINKING[levels["extractor"]],
        )

    base = key_for(["--thinking", "low"])
    assert key_for(["--thinking", "low", "--thinking-librarian", "high"]) == base
    assert key_for(["--thinking", "low", "--thinking-classifier", "high"]) == base
    assert key_for(["--thinking", "low", "--thinking-extractor", "high"]) != base
    assert key_for(["--thinking", "low", "--thinking-ontology", "high"]) != base


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
    assert args.corpus == "episodes"
    assert args.fixture is None
    assert args.per_call_timeout == 300.0
    assert args.max_wall_seconds is None
    assert args.thinking_ontology is None
    assert args.thinking_extractor is None
    assert args.thinking_librarian is None
    assert args.thinking_classifier is None


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


def test_thinking_high_is_available() -> None:
    """``high`` is a level the sweep must be able to ask for; ``xhigh`` is not."""
    args = probe.build_parser().parse_args(["--thinking", "high"])

    assert args.thinking == "high"
    assert probe.THINKING["high"] == "high"
    assert "xhigh" not in probe.THINKING


def test_per_agent_thinking_flags_parse_and_fall_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each per-agent flag defaults to None and resolves to --thinking."""
    del monkeypatch
    default = probe.build_parser().parse_args(["--thinking", "medium"])

    assert probe.resolve_thinking_levels(default) == {
        "ontology": "medium",
        "extractor": "medium",
        "librarian": "medium",
        "classifier": "medium",
    }

    overridden = probe.build_parser().parse_args(
        ["--thinking", "off", "--thinking-extractor", "high", "--thinking-classifier", "low"]
    )

    assert probe.resolve_thinking_levels(overridden) == {
        "ontology": "off",
        "extractor": "high",
        "librarian": "off",
        "classifier": "low",
    }


def test_per_agent_levels_reach_three_separate_agent_configs() -> None:
    """The resolved levels build one AgentInferenceConfig per agent."""
    args = probe.build_parser().parse_args(["--test-model", "--thinking", "off", "--thinking-extractor", "high"])
    configs = probe.build_configs(args, probe.resolve_thinking_levels(args), None)

    assert configs["ontology"].thinking_effort is False
    assert configs["extractor"].thinking_effort == "high"
    assert configs["librarian"].thinking_effort is False
    assert configs["classifier"].thinking_effort is False
    assert all(config.model_name == args.model for config in configs.values())


def test_per_call_timeout_bounds_one_model_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """``--per-call-timeout`` reaches LocalEndpoint; ``--episode-timeout`` keeps its own default."""
    monkeypatch.delenv("NEOCORTEX_LOCAL_MODEL_BASE_URL", raising=False)
    monkeypatch.delenv("NEOCORTEX_LOCAL_MODEL_API_KEY_ENV", raising=False)
    args = probe.build_parser().parse_args([])

    assert args.per_call_timeout == 300.0
    assert args.episode_timeout == 900.0
    assert probe.resolve_local_endpoint(args.per_call_timeout).timeout_s == 300.0

    explicit = probe.build_parser().parse_args(["--per-call-timeout", "45"])
    assert probe.resolve_local_endpoint(explicit.per_call_timeout).timeout_s == 45.0
    assert explicit.episode_timeout == 900.0


# ── Unit selection ──


def _corpus() -> dict[int, dict[str, object]]:
    from scripts.corpus_loader import load_corpus  # ty: ignore[unresolved-import]

    return {int(str(record["number"])): record for record in load_corpus(profile="compact")}


def test_corpus_modes_select_the_right_units() -> None:
    from scripts.fact_retention import load_fixture  # ty: ignore[unresolved-import]

    fixture = load_fixture(FIXTURE_PATH)
    corpus = _corpus()

    def keys(argv: list[str]) -> list[str]:
        args = probe.build_parser().parse_args(argv)
        return [unit.key for unit in probe.select_units(args, corpus, fixture)]

    assert keys([]) == ["E04", "E05"]
    assert keys(["--corpus", "compact"]) == ["E02", "E04", "E05", "E10", "E18", "E20", "E26", "E27"]
    assert keys(["--corpus", "supersession"]) == ["S05", "S11", "S07"]
    both = keys(["--corpus", "both"])
    assert len(both) == 11
    assert both[-3:] == ["S05", "S11", "S07"]


def test_a_triplet_unit_carries_both_texts_at_the_triplet_importance() -> None:
    from scripts.fact_retention import load_fixture  # ty: ignore[unresolved-import]

    args = probe.build_parser().parse_args(["--corpus", "supersession"])
    units = probe.select_units(args, _corpus(), load_fixture(FIXTURE_PATH))

    assert [label for label, _ in units[0].texts] == ["S05-1", "S05-2"]
    assert units[0].kind == "triplet"
    assert units[0].importance == 0.5


@pytest.mark.parametrize("corpus_mode", ["supersession", "both"])
@pytest.mark.asyncio
async def test_triplet_corpora_require_a_fixture(corpus_mode: str, capsys: pytest.CaptureFixture[str]) -> None:
    """Without --fixture there are no triplets to run, so the run must not start."""
    with pytest.raises(SystemExit) as caught:
        await probe.main(["--test-model", "--corpus", corpus_mode])

    assert caught.value.code == 2
    assert "--fixture" in capsys.readouterr().err


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


@pytest.mark.asyncio
async def test_test_model_run_over_the_full_corpus_and_triplets(tmp_path: Path) -> None:
    """``--corpus both`` writes eleven rows, each with a fact_score key.

    TestModel returns stub entities, so a low or zero ``facts_found`` is the
    correct result here: this proves the plumbing, not the model's quality.
    """
    import sys

    from loguru import logger

    output = tmp_path / "both.json"
    try:
        exit_code = await probe.main(
            [
                "--test-model",
                "--corpus",
                "both",
                "--fixture",
                str(FIXTURE_PATH),
                "--cache-dir",
                str(tmp_path / "cache"),
                "--output",
                str(output),
            ]
        )
    finally:
        logger.remove()
        logger.add(sys.stderr)

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    keys = [episode["episode"] for episode in payload["episodes"]]
    assert keys == ["E02", "E04", "E05", "E10", "E18", "E20", "E26", "E27", "S05", "S11", "S07"]
    assert all("fact_score" in episode for episode in payload["episodes"])
    assert all(episode["critical_defects"] == [] for episode in payload["episodes"])
    compact = payload["episodes"][:8]
    triplets = payload["episodes"][8:]
    assert all(isinstance(episode["fact_score"], dict) for episode in compact)
    assert all(set(episode["fact_score"]) == {"facts_total", "facts_found", "missing_keys"} for episode in compact)
    assert all(episode["supersession"] is None for episode in compact)
    # A triplet has no facts[] in the fixture, so a zero-valued score there would
    # read as a measured full-marks result; it must stay null.
    assert all(episode["fact_score"] is None for episode in triplets)
    assert all(
        set(episode["supersession"]) == {"new_present", "old_absent", "temporal_edge_present"} for episode in triplets
    )
    assert payload["run"]["corpus"] == "both"
    assert payload["run"]["chain"] == {"status": "NOT MEASURED", "reason": "repo_mode=fresh"}
    assert payload["run"]["wall_budget_exhausted"] is False


@pytest.mark.asyncio
async def test_librarian_cache_misses_are_recorded_and_remaining_units_continue(tmp_path: Path) -> None:
    """A missing cache entry is an error row, not a traceback that prevents output."""
    import sys

    from loguru import logger

    output = tmp_path / "cache-misses.json"
    try:
        exit_code = await probe.main(
            [
                "--test-model",
                "--stage",
                "librarian",
                "--episodes",
                "E04",
                "E05",
                "--cache-dir",
                str(tmp_path / "empty-cache"),
                "--output",
                str(output),
            ]
        )
    finally:
        logger.remove()
        logger.add(sys.stderr)

    assert exit_code == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert [row["episode"] for row in payload["episodes"]] == ["E04", "E05"]
    assert [row["status"] for row in payload["episodes"]] == [
        "error:FileNotFoundError",
        "error:FileNotFoundError",
    ]
    assert [row["critical_defects"] for row in payload["episodes"]] == [["unit_error"], ["unit_error"]]
    assert [(row["episode"], row["stage"], row["status"]) for row in payload["stages"]] == [
        ("E04", "librarian", "error:FileNotFoundError"),
        ("E05", "librarian", "error:FileNotFoundError"),
    ]


@pytest.mark.asyncio
async def test_classifier_test_model_runs_eight_rows_without_a_provider_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mock CLI exercises AgentDomainClassifier while denying live I/O."""
    import sys

    import httpx
    from loguru import logger

    from neocortex.domains import classifier as classifier_module

    def deny_provider_factory(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("live provider factory called")

    async def deny_http_request(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("live HTTP request called")

    monkeypatch.setattr(classifier_module, "build_model", deny_provider_factory)
    monkeypatch.setattr(httpx.AsyncClient, "send", deny_http_request)
    output = tmp_path / "classifier.json"
    try:
        exit_code = await probe.main(
            [
                "--test-model",
                "--classify",
                "--corpus",
                "compact",
                "--fixture",
                str(FIXTURE_PATH),
                "--cache-dir",
                str(tmp_path / "cache"),
                "--output",
                str(output),
            ]
        )
    finally:
        logger.remove()
        logger.add(sys.stderr)

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    classifier_rows = [row for row in payload["stages"] if row["stage"] == "classifier"]
    assert [row["episode"] for row in classifier_rows] == [
        "E02",
        "E04",
        "E05",
        "E10",
        "E18",
        "E20",
        "E26",
        "E27",
    ]
    assert all(row["status"] == "ok" and row["valid_result"] is True for row in classifier_rows)
    assert all(row["critical_defects"] == [] for row in payload["episodes"])


@pytest.mark.asyncio
async def test_classifier_failure_remains_the_unit_outcome(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A successful extraction cannot turn a failed classifier row into an ok unit."""
    import sys

    from loguru import logger

    async def fail_classifier(*args: Any, **kwargs: Any) -> tuple[float, str, int, int]:
        return 0.01, "error:UnexpectedModelBehavior", 0, 0

    monkeypatch.setattr(probe, "_classify", fail_classifier)
    output = tmp_path / "classifier-failure.json"
    try:
        exit_code = await probe.main(
            [
                "--test-model",
                "--classify",
                "--episodes",
                "E04",
                "--cache-dir",
                str(tmp_path / "cache"),
                "--output",
                str(output),
            ]
        )
    finally:
        logger.remove()
        logger.add(sys.stderr)

    assert exit_code == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["episodes"][0]["status"] == "error:UnexpectedModelBehavior"
    assert payload["episodes"][0]["critical_defects"] == ["unit_error"]
    classifier_row = next(row for row in payload["stages"] if row["stage"] == "classifier")
    assert classifier_row["status"] == "error:UnexpectedModelBehavior"
    assert classifier_row["valid_result"] is False


@pytest.mark.asyncio
async def test_chain_is_measured_on_a_shared_repository(tmp_path: Path) -> None:
    """``--corpus compact --repo shared`` records the chain expectation, measured."""
    import sys

    from loguru import logger

    output = tmp_path / "chain.json"
    try:
        await probe.main(
            [
                "--test-model",
                "--corpus",
                "compact",
                "--repo",
                "shared",
                "--fixture",
                str(FIXTURE_PATH),
                "--cache-dir",
                str(tmp_path / "cache"),
                "--output",
                str(output),
            ]
        )
    finally:
        logger.remove()
        logger.add(sys.stderr)

    chain = json.loads(output.read_text(encoding="utf-8"))["run"]["chain"]
    assert chain["episodes"] == ["E18", "E20", "E26"]
    assert chain["min_temporal_edges"] == 1
    assert isinstance(chain["temporal_edges"], int)
    assert chain["satisfied"] == (chain["temporal_edges"] >= 1)


@pytest.mark.asyncio
async def test_max_wall_seconds_zero_launches_nothing_and_still_writes(tmp_path: Path) -> None:
    """An exhausted budget records every unit as NOT MEASURED, never as a zero row."""
    import sys

    from loguru import logger

    output = tmp_path / "budget.json"
    try:
        exit_code = await probe.main(
            [
                "--test-model",
                "--max-wall-seconds",
                "0",
                "--cache-dir",
                str(tmp_path / "cache"),
                "--output",
                str(output),
            ]
        )
    finally:
        logger.remove()
        logger.add(sys.stderr)

    assert exit_code == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert [episode["episode"] for episode in payload["episodes"]] == ["E04", "E05"]
    assert all(episode["status"] == "NOT MEASURED" for episode in payload["episodes"])
    assert all(episode["reason"] == "wall_budget" for episode in payload["episodes"])
    assert all(episode["seconds_total"] is None for episode in payload["episodes"])
    assert all(episode["words"] is None for episode in payload["episodes"])
    assert all(episode["critical_defects"] is None for episode in payload["episodes"])
    assert payload["stages"] == []
    assert payload["run"]["wall_budget_exhausted"] is True
    assert payload["run"]["chain"] == {"status": "NOT MEASURED", "reason": "wall_budget"}


@pytest.mark.asyncio
async def test_the_output_file_is_written_after_every_unit(tmp_path: Path) -> None:
    """A killed run must leave valid JSON holding every unit that finished."""
    import sys

    from loguru import logger

    output = tmp_path / "incremental.json"
    seen: list[int] = []
    original = probe.write_output

    def spy(path: Path, run_meta: Any, summaries: list[dict[str, Any]], rows: list[dict[str, Any]]) -> None:
        original(path, run_meta, summaries, rows)
        seen.append(len(json.loads(path.read_text(encoding="utf-8"))["episodes"]))

    probe.write_output = spy
    try:
        await probe.main(["--test-model", "--cache-dir", str(tmp_path / "cache"), "--output", str(output)])
    finally:
        probe.write_output = original
        logger.remove()
        logger.add(sys.stderr)

    # One write after each of the two episodes, plus the final write.
    assert seen == [1, 2, 2]
