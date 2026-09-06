from fastmcp import Context
from loguru import logger

from neocortex.auth.dependencies import ensure_provisioned, get_agent_id_from_context
from neocortex.jobs.correlation import new_extraction_correlation_id
from neocortex.schemas.memory import RememberResult


async def remember(
    text: str,
    context: str | None = None,
    target_graph: str | None = None,
    importance: float | None = None,
    ctx: Context | None = None,
) -> RememberResult:
    """Store a memory. Describe what you want to remember in natural language.
    The system persists it as an episode and asynchronously extracts
    structured facts into the knowledge graph.

    Args:
        text: The content to remember, in natural language.
        context: Optional context about where/why this memory is being stored.
        target_graph: Optional shared graph to write to (requires write permission).
                      If omitted, stores to the agent's personal graph.
        importance: Optional importance hint (0.0-1.0). Higher values indicate more critical memories.
    """
    if ctx is None:
        raise RuntimeError("FastMCP context is required for remember().")

    repo = ctx.lifespan_context["repo"]
    agent_id = get_agent_id_from_context(ctx)
    await ensure_provisioned(ctx, agent_id)

    metadata: dict = {}
    episode_importance = 0.5
    if importance is not None:
        metadata["importance_hint"] = importance
        episode_importance = importance

    if target_graph is not None:
        router = ctx.lifespan_context["router"]
        await router.route_store_to(agent_id, target_graph)
        episode_id = await repo.store_episode_to(
            agent_id=agent_id,
            target_schema=target_graph,
            content=text,
            context=context,
            metadata=metadata,
            importance=episode_importance,
        )
    else:
        episode_id = await repo.store_episode(
            agent_id=agent_id,
            content=text,
            context=context,
            metadata=metadata,
            importance=episode_importance,
        )

    embeddings = ctx.lifespan_context.get("embeddings")
    if embeddings:
        vector = await embeddings.embed(text)
        if vector:
            await repo.update_episode_embedding(episode_id, vector, agent_id, target_schema=target_graph)

    # Enqueue extraction job if enabled
    extraction_job_id: int | None = None
    settings = ctx.lifespan_context["settings"]
    job_app = ctx.lifespan_context.get("job_app")
    if job_app and settings.extraction_enabled:
        correlation_id = new_extraction_correlation_id()
        extraction_job_id = await job_app.configure_task("extract_episode").defer_async(
            agent_id=agent_id,
            episode_ids=[episode_id],
            target_schema=target_graph,
            correlation_id=correlation_id,
        )
        logger.bind(action_log=True).info(
            "extraction_enqueued",
            job_id=extraction_job_id,
            episode_id=episode_id,
            agent_id=agent_id,
            correlation_id=correlation_id,
            target_graph_present=target_graph is not None,
        )

    # Enqueue domain routing if enabled (routes to shared domain graphs)
    # Requires: job_app (implies extraction_enabled), routing enabled, no explicit target
    if job_app and settings.domain_routing_enabled and target_graph is None:
        await job_app.configure_task("route_episode").defer_async(
            agent_id=agent_id,
            episode_id=episode_id,
            episode_text=text,
        )
        logger.bind(action_log=True).info(
            "domain_routing_enqueued",
            episode_id=episode_id,
            agent_id=agent_id,
        )

    return RememberResult(
        status="stored",
        episode_id=episode_id,
        message="Memory stored.",
        extraction_job_id=extraction_job_id,
    )
