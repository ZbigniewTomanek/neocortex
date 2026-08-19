"""Procrastinate task definitions for NeoCortex."""

from __future__ import annotations

import procrastinate
from loguru import logger
from procrastinate.testing import InMemoryConnector

# Placeholder app for task registration — replaced at runtime with real conninfo.
app = procrastinate.App(
    connector=InMemoryConnector(),
    import_paths=["neocortex.jobs.tasks"],
)


@app.task(
    name="extract_episode",
    retry=procrastinate.RetryStrategy(max_attempts=3, wait=5),
    queue="extraction",
)
async def extract_episode(
    agent_id: str,
    episode_ids: list[int],
    target_schema: str | None = None,
    source_schema: str | None = None,
    domain_hint: str | None = None,
    domain_slug: str | None = None,
) -> None:
    """Run extraction pipeline for a batch of episodes.

    Args:
        agent_id: Agent whose graph is being populated.
        episode_ids: Episodes to process.
        target_schema: Schema to write extracted nodes/edges to.
        source_schema: Schema to read episodes from (defaults to target_schema).
                       Used by domain routing where episodes live in the personal
                       graph but results go to a shared domain schema.
        domain_hint: Optional domain context passed to extraction agents to guide
                     semantically appropriate type proposals.
        domain_slug: Optional domain slug used to look up domain-specific seed
                     ontology recommendations.
    """
    logger.info(
        "extract_episode_started",
        agent_id=agent_id,
        episode_ids=episode_ids,
        target_schema=target_schema,
        source_schema=source_schema,
        domain_hint=domain_hint,
        domain_slug=domain_slug,
    )
    from neocortex.extraction.agents import AgentInferenceConfig
    from neocortex.extraction.pipeline import run_extraction
    from neocortex.jobs.context import get_services

    services = get_services()
    settings = services["settings"]

    # The pipeline uses a sentinel (_UNSET) to distinguish "not provided →
    # read from target_schema" from "None → read from personal graph".
    # Since procrastinate serialises args as JSON, we use "__personal__" as a
    # string sentinel for "read from agent's personal graph" (i.e. None).
    extra: dict = {}
    if source_schema == "__personal__":
        extra["source_schema"] = None  # personal graph
    elif source_schema is not None:
        extra["source_schema"] = source_schema

    await run_extraction(
        repo=services["repo"],
        embeddings=services["embeddings"],
        agent_id=agent_id,
        episode_ids=episode_ids,
        target_schema=target_schema,
        **extra,
        ontology_config=AgentInferenceConfig(
            model_name=settings.ontology_model,
            thinking_effort=settings.ontology_thinking_effort,
            local_endpoint=services.get("local_endpoint"),
        ),
        extractor_config=AgentInferenceConfig(
            model_name=settings.extractor_model,
            thinking_effort=settings.extractor_thinking_effort,
            local_endpoint=services.get("local_endpoint"),
        ),
        librarian_config=AgentInferenceConfig(
            model_name=settings.librarian_model,
            thinking_effort=settings.librarian_thinking_effort,
            local_endpoint=services.get("local_endpoint"),
        ),
        librarian_use_tools=settings.librarian_use_tools,
        tool_calls_limit=settings.extraction_tool_calls_limit,
        ontology_tool_calls_limit=settings.ontology_tool_calls_limit,
        ontology_max_new_types=settings.ontology_max_new_types,
        domain_hint=domain_hint,
        domain_slug=domain_slug,
        seed_generator=services.get("seed_generator"),
    )
    logger.info(
        "extract_episode_completed",
        agent_id=agent_id,
        episode_ids=episode_ids,
        target_schema=target_schema,
    )


@app.task(
    name="route_episode",
    retry=procrastinate.RetryStrategy(max_attempts=3, wait=5),
    queue="extraction",
)
async def route_episode(
    agent_id: str,
    episode_id: int,
    episode_text: str,
) -> None:
    """Route an episode to shared graphs via domain classification."""
    logger.info("route_episode_started", agent_id=agent_id, episode_id=episode_id)
    from neocortex.jobs.context import get_services

    services = get_services()
    domain_router = services.get("domain_router")
    if domain_router is None:
        logger.debug("route_episode_skipped_no_router")
        return

    # Ensure seed domains are available in the job worker context.
    # seed_defaults() is idempotent (ON CONFLICT DO NOTHING).
    await domain_router.ensure_domains_seeded()

    results = await domain_router.route_and_extract(
        agent_id=agent_id,
        episode_id=episode_id,
        episode_text=episode_text,
    )
    logger.bind(action_log=True).info(
        "route_episode_completed",
        agent_id=agent_id,
        episode_id=episode_id,
        routed_to=[r.schema_name for r in results],
        domain_count=len(results),
    )
