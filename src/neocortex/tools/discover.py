from fastmcp import Context
from loguru import logger

from neocortex.auth.dependencies import ensure_provisioned, get_agent_id_from_context
from neocortex.schemas.memory import (
    BrowseNodesResult,
    DiscoverDetailsResult,
    DiscoverDomainsResult,
    DiscoverGraphsResult,
    DiscoverOntologyResult,
    DomainInfo,
    GraphSummary,
    InspectNodeResult,
    NeighborEdge,
    NodeSummary,
)


async def discover_domains(ctx: Context | None = None) -> DiscoverDomainsResult:
    """List semantic knowledge domains (upper ontology).
    Shows what broad categories of knowledge exist and which graphs store them.
    Call this first to understand the knowledge landscape.
    """
    if ctx is None:
        raise RuntimeError("FastMCP context is required for discover_domains().")

    agent_id = get_agent_id_from_context(ctx)
    domain_router = ctx.lifespan_context.get("domain_router")

    if domain_router is None:
        logger.bind(action_log=True).info("tool_call", tool="discover_domains", agent_id=agent_id, domains=0)
        return DiscoverDomainsResult(domains=[], message="Domain routing is not enabled")

    domains = await domain_router.list_domains()
    domain_infos = [
        DomainInfo(
            slug=d.slug,
            name=d.name,
            description=d.description,
            schema_name=d.schema_name,
        )
        for d in domains
    ]

    logger.bind(action_log=True).info(
        "tool_call",
        tool="discover_domains",
        agent_id=agent_id,
        domains=len(domain_infos),
    )
    return DiscoverDomainsResult(domains=domain_infos)


async def discover_graphs(ctx: Context | None = None) -> DiscoverGraphsResult:
    """List all knowledge graphs accessible to you, with per-graph statistics.
    Each graph has node/edge/episode counts.
    Use graph names with discover_ontology to drill into a specific graph.
    """
    if ctx is None:
        raise RuntimeError("FastMCP context is required for discover_graphs().")

    repo = ctx.lifespan_context["repo"]
    agent_id = get_agent_id_from_context(ctx)
    await ensure_provisioned(ctx, agent_id)

    schema_names = await repo.list_graphs(agent_id=agent_id)

    # Build a lookup of schema_name -> (purpose, is_shared) from schema_mgr if available
    schema_info: dict[str, tuple[str, bool]] = {}
    schema_mgr = ctx.lifespan_context.get("schema_mgr")
    if schema_mgr is not None:
        all_graphs = await schema_mgr.list_graphs()
        for g in all_graphs:
            schema_info[g.schema_name] = (g.purpose, g.is_shared)

    graphs: list[GraphSummary] = []
    for name in schema_names:
        stats = await repo.get_stats_for_schema(agent_id=agent_id, schema_name=name)
        if name in schema_info:
            purpose, is_shared = schema_info[name]
        else:
            # Parse purpose from schema name: strip ncx_{agent}__ prefix
            parts = name.split("__", 1)
            purpose = parts[1] if len(parts) > 1 else name
            is_shared = False
        graphs.append(
            GraphSummary(
                schema_name=name,
                is_shared=is_shared,
                purpose=purpose,
                stats=stats,
            )
        )

    logger.bind(action_log=True).info(
        "tool_call",
        tool="discover_graphs",
        agent_id=agent_id,
        graph_count=len(graphs),
    )
    return DiscoverGraphsResult(graphs=graphs)


async def discover_ontology(graph_name: str, ctx: Context | None = None) -> DiscoverOntologyResult:
    """Show the entity types and relationship types in a specific graph.
    Returns node types and edge types with counts. Use discover_details
    to drill into a specific type.
    """
    if ctx is None:
        raise RuntimeError("FastMCP context is required for discover_ontology().")

    repo = ctx.lifespan_context["repo"]
    agent_id = get_agent_id_from_context(ctx)

    node_types = await repo.get_node_types(agent_id=agent_id, target_schema=graph_name)
    edge_types = await repo.get_edge_types(agent_id=agent_id, target_schema=graph_name)
    stats = await repo.get_stats_for_schema(agent_id=agent_id, schema_name=graph_name)

    logger.bind(action_log=True).info(
        "tool_call",
        tool="discover_ontology",
        agent_id=agent_id,
        graph_name_present=bool(graph_name),
        node_types=len(node_types),
        edge_types=len(edge_types),
    )
    return DiscoverOntologyResult(
        graph_name=graph_name,
        node_types=node_types,
        edge_types=edge_types,
        stats=stats,
    )


async def discover_details(
    type_name: str,
    graph_name: str,
    kind: str = "node",
    ctx: Context | None = None,
) -> DiscoverDetailsResult:
    """Get detailed information about a specific type in a graph.
    Returns the type's description, connected types, and sample entity names.

    Args:
        type_name: The name of the type to inspect.
        graph_name: The schema name of the graph containing the type.
        kind: 'node' for entity types, 'edge' for relationship types.
    """
    if ctx is None:
        raise RuntimeError("FastMCP context is required for discover_details().")

    repo = ctx.lifespan_context["repo"]
    agent_id = get_agent_id_from_context(ctx)

    detail = await repo.get_type_detail(agent_id=agent_id, type_name=type_name, graph_name=graph_name, kind=kind)

    if detail is None:
        from neocortex.schemas.memory import TypeDetail

        detail = TypeDetail(id=0, name=type_name, description=f"Type '{type_name}' not found in {graph_name}")

    logger.bind(action_log=True).info(
        "tool_call",
        tool="discover_details",
        agent_id=agent_id,
        graph_name_present=bool(graph_name),
        type_name_present=bool(type_name),
        kind_is_node=kind == "node",
    )
    return DiscoverDetailsResult(graph_name=graph_name, type_detail=detail)


async def browse_nodes(
    graph_name: str,
    type_name: str | None = None,
    limit: int = 20,
    ctx: Context | None = None,
) -> BrowseNodesResult:
    """Browse actual node instances in a graph, optionally filtered by type.
    Returns node names, content snippets, importance scores, and access counts.

    Args:
        graph_name: The schema name of the graph to browse.
        type_name: Optional node type name to filter by.
        limit: Maximum number of nodes to return (default 20).
    """
    if ctx is None:
        raise RuntimeError("FastMCP context is required for browse_nodes().")

    repo = ctx.lifespan_context["repo"]
    agent_id = get_agent_id_from_context(ctx)

    # Resolve type_id if type_name is provided
    type_id: int | None = None
    node_types = await repo.get_node_types(agent_id=agent_id, target_schema=graph_name)
    type_map = {t.name: t for t in node_types}

    if type_name:
        ti = type_map.get(type_name)
        if ti is not None:
            type_id = ti.id

    nodes = await repo.list_nodes_page(
        agent_id=agent_id,
        target_schema=graph_name,
        type_id=type_id,
        limit=limit,
    )

    # Build type_id -> type_name lookup
    id_to_name = {t.id: t.name for t in node_types}

    summaries = [
        NodeSummary(
            id=n.id,
            name=n.name,
            type_name=id_to_name.get(n.type_id, "unknown"),
            content=(n.content[:200] if n.content else None),
            importance=n.importance,
            access_count=n.access_count,
        )
        for n in nodes
    ]

    logger.bind(action_log=True).info(
        "tool_call",
        tool="browse_nodes",
        agent_id=agent_id,
        graph_name_present=bool(graph_name),
        type_name_present=type_name is not None,
        count=len(summaries),
    )
    return BrowseNodesResult(
        graph_name=graph_name,
        type_name=type_name,
        nodes=summaries,
        total=len(summaries),
    )


async def inspect_node(
    node_name: str,
    graph_name: str,
    ctx: Context | None = None,
) -> InspectNodeResult:
    """Inspect a specific node and its immediate neighborhood (connected nodes and edges).
    Shows the node's content, importance, and all relationships with neighbor nodes.

    Args:
        node_name: The name of the node to inspect.
        graph_name: The schema name of the graph containing the node.
    """
    if ctx is None:
        raise RuntimeError("FastMCP context is required for inspect_node().")

    repo = ctx.lifespan_context["repo"]
    agent_id = get_agent_id_from_context(ctx)

    # Find the node
    found = await repo.find_nodes_by_name(agent_id=agent_id, name=node_name, target_schema=graph_name)
    if not found:
        logger.bind(action_log=True).info(
            "tool_call",
            tool="inspect_node",
            agent_id=agent_id,
            graph_name_present=bool(graph_name),
            node_name_present=bool(node_name),
            found=False,
        )
        return InspectNodeResult(
            graph_name=graph_name,
            node=NodeSummary(id=0, name=node_name, type_name="unknown"),
            edges=[],
            neighbor_nodes=[],
        )

    node = found[0]

    # Build type lookups
    node_types = await repo.get_node_types(agent_id=agent_id, target_schema=graph_name)
    edge_types = await repo.get_edge_types(agent_id=agent_id, target_schema=graph_name)
    nt_map = {t.id: t.name for t in node_types}
    et_map = {t.id: t.name for t in edge_types}

    node_summary = NodeSummary(
        id=node.id,
        name=node.name,
        type_name=nt_map.get(node.type_id, "unknown"),
        content=(node.content[:200] if node.content else None),
        importance=node.importance,
        access_count=node.access_count,
    )

    # Get neighborhood (depth=1 for immediate connections)
    neighborhood = await repo.get_node_neighborhood(agent_id=agent_id, node_id=node.id, depth=1)

    neighbor_edges: list[NeighborEdge] = []
    neighbor_summaries: list[NodeSummary] = []

    for entry in neighborhood[:20]:  # Cap at 20 neighbors
        neighbor_node = entry["node"]
        edges = entry.get("edges", [])

        neighbor_summaries.append(
            NodeSummary(
                id=neighbor_node.id,
                name=neighbor_node.name,
                type_name=nt_map.get(neighbor_node.type_id, "unknown"),
                content=(neighbor_node.content[:100] if neighbor_node.content else None),
                importance=neighbor_node.importance,
                access_count=neighbor_node.access_count,
            )
        )

        for edge in edges:
            # Determine direction
            if edge.source_id == node.id:
                src_name, src_type = node.name, nt_map.get(node.type_id, "unknown")
                tgt_name, tgt_type = neighbor_node.name, nt_map.get(neighbor_node.type_id, "unknown")
            else:
                src_name, src_type = neighbor_node.name, nt_map.get(neighbor_node.type_id, "unknown")
                tgt_name, tgt_type = node.name, nt_map.get(node.type_id, "unknown")

            neighbor_edges.append(
                NeighborEdge(
                    source_name=src_name,
                    source_type=src_type,
                    target_name=tgt_name,
                    target_type=tgt_type,
                    edge_type=et_map.get(edge.type_id, "unknown"),
                    weight=edge.weight,
                )
            )

    logger.bind(action_log=True).info(
        "tool_call",
        tool="inspect_node",
        agent_id=agent_id,
        graph_name_present=bool(graph_name),
        node_name_present=bool(node_name),
        edges=len(neighbor_edges),
        neighbors=len(neighbor_summaries),
    )
    return InspectNodeResult(
        graph_name=graph_name,
        node=node_summary,
        edges=neighbor_edges,
        neighbor_nodes=neighbor_summaries,
    )
