"""Tests for Procrastinate job integration (Stage 2, Plan 07).

Uses InMemoryConnector — no Docker or PostgreSQL needed.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import procrastinate
import pytest
from loguru import logger
from procrastinate.testing import InMemoryConnector

from neocortex.jobs import create_job_app
from neocortex.jobs.context import get_services, set_services

# ── Job app factory ──


def test_create_job_app_returns_app():
    """create_job_app returns a properly configured Procrastinate App."""
    app = create_job_app("postgresql://user:pass@localhost:5432/testdb")
    assert isinstance(app, procrastinate.App)


# ── Context holder ──


def test_get_services_raises_before_set():
    """get_services raises RuntimeError if set_services was never called."""
    # Reset module state
    import neocortex.jobs.context as ctx_mod

    ctx_mod._services = None
    with pytest.raises(RuntimeError, match="not initialized"):
        get_services()


def test_set_and_get_services():
    """set_services / get_services round-trip works."""
    import neocortex.jobs.context as ctx_mod

    ctx_mod._services = None

    sentinel = {"repo": "fake", "settings": "fake"}
    set_services(sentinel)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
    assert get_services() is sentinel

    # Cleanup
    ctx_mod._services = None


# ── Task registration & deferral ──


@pytest.mark.asyncio
async def test_extract_episode_task_registered():
    """The extract_episode task is registered on the placeholder app."""
    from neocortex.jobs.tasks import app as placeholder_app

    task_names = [t.name for t in placeholder_app.tasks.values()]
    assert "extract_episode" in task_names


@pytest.mark.asyncio
async def test_extract_episode_task_has_retry():
    """extract_episode task has retry strategy with max_attempts=3."""
    from neocortex.jobs.tasks import app as placeholder_app

    task = placeholder_app.tasks["extract_episode"]
    assert task.retry_strategy is not None
    assert task.retry_strategy.max_attempts == 3  # ty: ignore[unresolved-attribute]


@pytest.mark.asyncio
async def test_extract_episode_task_queue():
    """extract_episode task is assigned to the 'extraction' queue."""
    from neocortex.jobs.tasks import app as placeholder_app

    task = placeholder_app.tasks["extract_episode"]
    assert task.queue == "extraction"


@pytest.mark.asyncio
async def test_defer_extract_episode():
    """Deferring extract_episode returns a valid job ID."""
    connector = InMemoryConnector()
    app = procrastinate.App(
        connector=connector,
        import_paths=["neocortex.jobs.tasks"],
    )

    await app.open_async()
    try:
        from neocortex.jobs.tasks import extract_episode

        job_id = await extract_episode.configure(app=app).defer_async(
            agent_id="test-agent",
            episode_ids=[1, 2, 3],
        )
        assert job_id is not None
        assert isinstance(job_id, int)
        assert job_id > 0

        # Deferring a second job yields a different ID
        job_id_2 = await extract_episode.configure(app=app).defer_async(
            agent_id="test-agent",
            episode_ids=[4, 5],
        )
        assert job_id_2 > job_id
    finally:
        await app.close_async()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provided_correlation_id", "expected_correlation_id"),
    [
        ("job:test-agent:10", None),
        ("extract-0123456789abcdef0123456789abcdef", "extract-0123456789abcdef0123456789abcdef"),
    ],
)
async def test_extract_episode_calls_run_extraction(provided_correlation_id: str, expected_correlation_id: str | None):
    """When the task executes, it calls run_extraction with correct args."""
    import sys
    import types

    import neocortex.jobs.context as ctx_mod

    mock_repo = AsyncMock()
    mock_embeddings = AsyncMock()
    mock_settings = AsyncMock()
    mock_settings.ontology_model = "test-model"
    mock_settings.ontology_thinking_effort = "low"
    mock_settings.extractor_model = "test-model"
    mock_settings.extractor_thinking_effort = "low"
    mock_settings.librarian_model = "test-model"
    mock_settings.librarian_thinking_effort = "low"
    mock_settings.librarian_use_tools = True
    mock_settings.extraction_tool_calls_limit = 150
    mock_settings.librarian_entity_read_limit = 2
    mock_settings.librarian_relation_read_limit = 1
    mock_settings.librarian_soft_read_streak = 6
    mock_settings.librarian_hard_read_streak = 10
    mock_settings.librarian_soft_no_progress_calls = 8
    mock_settings.librarian_hard_no_progress_calls = 14
    mock_settings.librarian_max_duplicate_calls = 2
    mock_settings.ontology_tool_calls_limit = 30
    mock_settings.ontology_max_new_types = 3

    mock_seed_generator = AsyncMock()

    fake_ctx = {
        "repo": mock_repo,
        "embeddings": mock_embeddings,
        "settings": mock_settings,
        "seed_generator": mock_seed_generator,
    }
    ctx_mod._services = fake_ctx  # ty: ignore[invalid-assignment]

    # Create temporary mock modules so the lazy imports in the task succeed.
    mock_run = AsyncMock()
    fake_pipeline = types.ModuleType("neocortex.extraction.pipeline")
    fake_pipeline.run_extraction = mock_run  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]

    fake_extraction = types.ModuleType("neocortex.extraction")

    # AgentInferenceConfig must be importable from the agents module
    from neocortex.extraction.agents import AgentInferenceConfig, LibrarianBudgetConfig

    fake_agents = types.ModuleType("neocortex.extraction.agents")
    fake_agents.AgentInferenceConfig = (  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
        AgentInferenceConfig
    )
    fake_agents.LibrarianBudgetConfig = (  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
        LibrarianBudgetConfig
    )

    original_modules = {
        name: sys.modules.get(name)
        for name in ("neocortex.extraction", "neocortex.extraction.pipeline", "neocortex.extraction.agents")
    }
    sys.modules["neocortex.extraction"] = fake_extraction
    sys.modules["neocortex.extraction.pipeline"] = fake_pipeline
    sys.modules["neocortex.extraction.agents"] = fake_agents  # type: ignore[assignment]
    audit_records: list[dict] = []
    sink_id = logger.add(lambda message: audit_records.append(message.record), level="INFO")

    try:
        from neocortex.jobs.tasks import extract_episode

        # Call the task function directly (bypassing Procrastinate machinery)
        await extract_episode(
            agent_id="test-agent",
            episode_ids=[10, 20],
            domain_hint="PRIVATE_DOMAIN_HINT",
            correlation_id=provided_correlation_id,
        )

        mock_run.assert_called_once_with(
            repo=mock_repo,
            embeddings=mock_embeddings,
            agent_id="test-agent",
            episode_ids=[10, 20],
            target_schema=None,
            ontology_config=AgentInferenceConfig(
                model_name="test-model",
                thinking_effort="low",
            ),
            extractor_config=AgentInferenceConfig(
                model_name="test-model",
                thinking_effort="low",
            ),
            librarian_config=AgentInferenceConfig(
                model_name="test-model",
                thinking_effort="low",
            ),
            librarian_use_tools=True,
            tool_calls_limit=150,
            librarian_budget=LibrarianBudgetConfig(),
            ontology_tool_calls_limit=30,
            ontology_max_new_types=3,
            domain_hint="PRIVATE_DOMAIN_HINT",
            domain_slug=None,
            seed_generator=mock_seed_generator,
            correlation_id=mock_run.call_args.kwargs["correlation_id"],
        )
        action_records = [record for record in audit_records if record["extra"].get("action_log")]
        assert action_records
        correlation_id = mock_run.call_args.kwargs["correlation_id"]
        assert correlation_id.startswith("extract-")
        assert len(correlation_id) == len("extract-") + 32
        if expected_correlation_id is not None:
            assert correlation_id == expected_correlation_id
        else:
            assert correlation_id != provided_correlation_id
        assert all("domain_hint" not in record["extra"] for record in action_records)
        assert all("PRIVATE_DOMAIN_HINT" not in str(record["extra"]) for record in action_records)
    finally:
        logger.remove(sink_id)
        ctx_mod._services = None
        for name, original in original_modules.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


# ── Worker lifecycle ──


@pytest.mark.asyncio
async def test_worker_starts_and_stops():
    """Worker can be started as an asyncio task and cancelled cleanly."""
    connector = InMemoryConnector()
    app = procrastinate.App(
        connector=connector,
        import_paths=["neocortex.jobs.tasks"],
    )

    await app.open_async()
    try:
        worker_task = asyncio.create_task(app.run_worker_async(queues=["extraction"], install_signal_handlers=False))

        # Give the worker a moment to start
        await asyncio.sleep(0.05)
        assert not worker_task.done()

        # Cancel and verify clean shutdown
        worker_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker_task
    finally:
        await app.close_async()


# ── Settings ──


def test_extraction_settings_defaults():
    """MCPSettings has per-agent extraction settings with correct defaults."""
    from neocortex.mcp_settings import MCPSettings

    s = MCPSettings(_env_file=None)  # ty: ignore[unknown-argument]
    assert s.extraction_enabled is True
    for prefix in ("ontology", "extractor", "librarian"):
        assert getattr(s, f"{prefix}_model") == "openai-responses:gpt-5.4-mini"
    # Ontology agent uses medium thinking for better tool-use sequencing
    assert s.ontology_thinking_effort == "medium"
    assert s.extractor_thinking_effort == "low"
    assert s.librarian_thinking_effort == "low"
    assert s.librarian_entity_read_limit == 2
    assert s.librarian_relation_read_limit == 1
    assert s.librarian_soft_read_streak == 6
    assert s.librarian_hard_read_streak == 10
    assert s.librarian_soft_no_progress_calls == 8
    assert s.librarian_hard_no_progress_calls == 14
    assert s.librarian_max_duplicate_calls == 2
    assert s.domain_classifier_model == "openai-responses:gpt-5.4-mini"


def test_qwen_family_detection_is_exact() -> None:
    from neocortex.model_factory import is_qwen_model

    assert is_qwen_model("local:qwen3.8-flash-next")
    assert is_qwen_model("openai:qwen3.5")
    assert is_qwen_model("openai:org/qwen3.5")
    assert not is_qwen_model("local:llama-3")
    assert not is_qwen_model("openai-responses:gpt-5.4-mini")


# ── ServiceContext includes job_app ──


def test_service_context_type_has_job_app():
    """ServiceContext TypedDict includes job_app field."""
    from neocortex.services import ServiceContext

    # TypedDict annotations should include job_app
    annotations = ServiceContext.__annotations__
    assert "job_app" in annotations
