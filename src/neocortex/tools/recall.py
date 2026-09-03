import json
import random
from collections import defaultdict
from datetime import datetime

from fastmcp import Context
from loguru import logger

from neocortex.auth.dependencies import ensure_provisioned, get_agent_id_from_context
from neocortex.schemas.memory import GraphContext, RecallItem, RecallResult
from neocortex.scoring import compute_spreading_activation, neighborhood_to_adjacency, truncate_preserving_neighbors


def _format_recall_context(results: list[RecallItem]) -> str:
    """Return JSON blocks for recalled episodes, grouped by session."""
    episodes = [r for r in results if r.source_kind == "episode"]
    clustered: dict[tuple[str, str | None], list[RecallItem]] = defaultdict(list)
    isolated: list[RecallItem] = []

    for ep in episodes:
        if ep.session_id:
            clustered[(ep.session_id, ep.graph_name)].append(ep)
        else:
            isolated.append(ep)

    parts: list[str] = []
    for (session_id, graph_name), cluster in clustered.items():
        cluster.sort(
            key=lambda e: (
                e.session_sequence is None,
                e.session_sequence or 0,
                e.created_at or datetime.min,
                e.item_id,
            )
        )
        parts.append(
            json.dumps(
                {
                    "session_id": session_id,
                    "graph_name": graph_name,
                    "episodes": [
                        {
                            "id": ep.item_id,
                            "created_at": ep.created_at.isoformat() if ep.created_at else None,
                            "session_sequence": ep.session_sequence,
                            "content": ep.content,
                            "is_context_neighbor": ep.neighbor_of is not None,
                            "neighbor_of": ep.neighbor_of,
                            "score": round(ep.score, 4),
                        }
                        for ep in cluster
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )

    for ep in isolated:
        parts.append(
            json.dumps(
                {
                    "id": ep.item_id,
                    "graph_name": ep.graph_name,
                    "created_at": ep.created_at.isoformat() if ep.created_at else None,
                    "content": ep.content,
                    "score": round(ep.score, 4),
                },
                ensure_ascii=False,
                indent=2,
            )
        )

    return "\n---\n".join(parts) if parts else "(no episodes recalled)"


async def _maybe_decay_edges(repo, agent_id: str, settings, *, force: bool = False) -> None:
    """Probabilistically decay weights of stale edges (1 in 4 calls, or forced)."""
    if not force and random.random() >= 0.25:
        return
    await repo.decay_stale_edges(
        agent_id,
        older_than_hours=48.0,
        decay_factor=0.95,
        floor=settings.edge_weight_floor,
    )


async def _maybe_forget_sweep(repo, agent_id: str, settings, *, force: bool = False) -> None:
    """Probabilistically identify and soft-forget low-activation, low-importance nodes."""
    if not force and random.random() >= 0.05:
        return
    forgettable = await repo.identify_forgettable_nodes(
        agent_id, settings.forget_activation_threshold, settings.forget_importance_floor
    )
    if forgettable:
        count = await repo.mark_forgotten(agent_id, forgettable)
        if count:
            logger.bind(action_log=True).info("forget_sweep", agent_id=agent_id, forgotten_count=count)


async def recall(query: str, limit: int = 10, ctx: Context | None = None) -> RecallResult:
    """Recall memories related to a query. Uses hybrid search combining
    semantic similarity, full-text search, and graph traversal.

    Args:
        query: What you want to know, in natural language.
        limit: Maximum number of primary results to return (1-100).
               Session-context neighbors are included additionally,
               so the actual result count may exceed this value.
    """
    if ctx is None:
        raise RuntimeError("FastMCP context is required for recall().")

    limit = max(1, min(limit, 100))
    repo = ctx.lifespan_context["repo"]
    settings = ctx.lifespan_context["settings"]
    agent_id = get_agent_id_from_context(ctx)
    await ensure_provisioned(ctx, agent_id)

    embeddings = ctx.lifespan_context.get("embeddings")
    query_embedding = None
    episode_query_embedding = None
    if embeddings:
        query_embedding = await embeddings.embed(query)
        # Role-bias correction: prefix plain queries with "user:" for episode vector search
        if not query.lower().startswith(("user:", "assistant:")):
            episode_query_embedding = await embeddings.embed(f"user: {query}")

    # Episode + existing node recall
    results = await repo.recall(
        query=query,
        agent_id=agent_id,
        limit=limit,
        query_embedding=query_embedding,
        expand_neighbors=settings.recall_expand_neighbors,
        episode_query_embedding=episode_query_embedding,
    )

    # Node search with graph traversal
    matched_node_tuples = await repo.search_nodes(
        agent_id=agent_id, query=query, limit=5, query_embedding=query_embedding
    )

    traversal_depth = settings.recall_traversal_depth

    # Resolve type names (once, outside the loop)
    node_types = await repo.get_node_types(agent_id)
    edge_types = await repo.get_edge_types(agent_id)
    type_name_map = {t.id: t.name for t in node_types}
    edge_type_name_map = {t.id: t.name for t in edge_types}

    # Build node results with graph context + collect adjacency for spreading activation
    existing_node_ids = {r.item_id for r in results if r.source_kind == "node"}
    node_results: list[RecallItem] = []
    merged_adjacency: dict[int, list[tuple[int, float]]] = {}
    traversed_edge_ids: set[int] = set()

    # Collect all seeds: Phase 1 node results + Phase 2 search results
    seed_nodes: list[tuple[int, float]] = []
    for r in results:
        if r.source_kind == "node":
            seed_nodes.append((r.item_id, r.score))

    for node, relevance_score in matched_node_tuples:
        neighborhood = await repo.get_node_neighborhood(agent_id=agent_id, node_id=node.id, depth=traversal_depth)

        # Collect edge IDs for reinforcement
        for entry in neighborhood:
            for edge in entry["edges"]:
                traversed_edge_ids.add(edge.id)

        # Build adjacency map for spreading activation
        adjacency = neighborhood_to_adjacency(neighborhood, node.id)
        for nid, neighbors in adjacency.items():
            if nid not in merged_adjacency:
                merged_adjacency[nid] = []
            merged_adjacency[nid].extend(neighbors)

        node_type_name = type_name_map.get(node.type_id, "Unknown")

        graph_context = GraphContext(
            center_node={
                "id": node.id,
                "name": node.name,
                "type": node_type_name,
                "properties": node.properties,
            },
            edges=[
                {
                    "source": entry["edges"][0].source_id if entry["edges"] else None,
                    "target": entry["edges"][0].target_id if entry["edges"] else None,
                    "type": edge_type_name_map.get(entry["edges"][0].type_id, "Unknown") if entry["edges"] else None,
                    "weight": entry["edges"][0].weight if entry["edges"] else None,
                    "properties": entry["edges"][0].properties if entry["edges"] else {},
                }
                for entry in neighborhood
                if entry["edges"]
            ],
            neighbor_nodes=[
                {
                    "id": entry["node"].id,
                    "name": entry["node"].name,
                    "type": type_name_map.get(entry["node"].type_id, "Unknown"),
                }
                for entry in neighborhood
            ],
            depth=traversal_depth,
        )

        # If this node was already in recall results, enrich it with graph_context
        if node.id in existing_node_ids:
            for r in results:
                if r.source_kind == "node" and r.item_id == node.id:
                    r.graph_context = graph_context
                    break
        else:
            # Add Phase 2 seed with relevance score
            seed_nodes.append((node.id, relevance_score))
            node_results.append(
                RecallItem(
                    item_id=node.id,
                    name=node.name,
                    content=node.content or "",
                    item_type=node_type_name,
                    score=relevance_score,
                    source=node.source,
                    source_kind="node",
                    graph_name=None,
                    graph_context=graph_context,
                )
            )

    # Merge and apply spreading activation
    all_results = results + node_results

    if seed_nodes and merged_adjacency:
        bonus_map = compute_spreading_activation(
            seed_nodes=seed_nodes,
            neighborhood=merged_adjacency,
            decay=settings.spreading_activation_decay,
            max_depth=settings.spreading_activation_max_depth,
        )

        # Apply bonus to node results
        for r in all_results:
            if r.source_kind == "node" and r.item_id in bonus_map:
                bonus = bonus_map[r.item_id]
                r.spreading_bonus = bonus
                r.score += bonus * settings.spreading_activation_bonus_weight

    # Re-sort by updated score
    all_results.sort(key=lambda item: item.score, reverse=True)

    # Record access for returned results (ACT-R activation tracking)
    final_results = truncate_preserving_neighbors(all_results, limit)
    recalled_node_ids = [r.item_id for r in final_results if r.source_kind == "node"]
    recalled_episode_ids = [r.item_id for r in final_results if r.source_kind == "episode"]
    if recalled_node_ids:
        await repo.record_node_access(agent_id, recalled_node_ids)
    if recalled_episode_ids:
        await repo.record_episode_access(agent_id, recalled_episode_ids)

    # Edge reinforcement — strengthen traversed edges (Hebbian learning)
    if traversed_edge_ids:
        await repo.reinforce_edges(
            agent_id,
            list(traversed_edge_ids),
            delta=settings.edge_reinforcement_delta,
            ceiling=settings.edge_weight_ceiling,
        )

    # Micro-decay — probabilistic, bounded to recently-active edges only
    if traversed_edge_ids and random.random() < 0.25:
        await repo.micro_decay_edges(
            agent_id,
            exclude_ids=list(traversed_edge_ids),
            factor=settings.edge_micro_decay_factor,
            floor=settings.edge_weight_floor,
            recently_reinforced_hours=1.0,
        )

    # Lazy stale-edge decay — 1 in 4 recall calls, 48h window
    await _maybe_decay_edges(repo, agent_id, settings)

    # Lazy forget sweep — 1 in 20 recall calls
    await _maybe_forget_sweep(repo, agent_id, settings)

    formatted_context = _format_recall_context(final_results)

    logger.bind(action_log=True).info(
        "recall_with_graph_traversal",
        agent_id=agent_id,
        query_present=bool(query),
        total_results=len(all_results),
        node_results_with_context=sum(1 for r in all_results if r.graph_context is not None),
        results_with_session_id=sum(1 for r in final_results if r.session_id),
        neighbor_episodes_included=sum(1 for r in final_results if r.neighbor_of is not None),
        episode_role_bias_applied=episode_query_embedding is not None,
    )

    return RecallResult(
        results=final_results,
        total=len(final_results),
        query=query,
        formatted_context=formatted_context,
    )
