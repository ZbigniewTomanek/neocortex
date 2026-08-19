from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

import asyncpg
from loguru import logger

from neocortex.db.scoped import graph_scoped_connection, schema_scoped_connection
from neocortex.graph_service import GraphService
from neocortex.mcp_settings import MCPSettings
from neocortex.models import Edge, EdgeType, Episode, Node, NodeType
from neocortex.normalization import canonicalize_name, normalize_edge_type, normalize_node_type
from neocortex.postgres_service import PostgresService
from neocortex.schemas.memory import GraphStats, RecallItem, TypeDetail, TypeInfo
from neocortex.scoring import (
    HybridWeights,
    compute_base_activation,
    compute_hybrid_score,
    compute_recency_score,
    compute_stm_boost,
    compute_supersession_adjustment,
    mmr_rerank,
    truncate_preserving_neighbors,
)

if TYPE_CHECKING:
    from neocortex.graph_router import GraphRouter


def _escape_ilike(query: str) -> str:
    """Escape special ILIKE characters for use with ``ESCAPE '\\'``."""
    return query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# Type pairs that should NOT be auto-merged (known homonym categories)
_HOMONYM_TYPE_GROUPS: frozenset[frozenset[str]] = frozenset(
    {
        frozenset({"Drug", "Neurotransmitter"}),
        frozenset({"Person", "Organization"}),
        frozenset({"Language", "Country"}),
        frozenset({"Metric", "MetricUnit"}),  # a metric and its unit are different (prefix guard)
    }
)

# Types within the same group are considered merge-safe (likely type drift, not homonyms)
_MERGE_SAFE_TYPE_GROUPS: list[frozenset[str]] = [
    # Software entities — LLM often oscillates between these
    # NOTE: Service, Application, Platform excluded — they are semantically
    # distinct enough that same-name entities may legitimately differ.
    frozenset({"Tool", "Project", "Software", "SoftwareTool", "Framework", "Library", "Technology"}),
    # People — role vs person type drift
    frozenset({"Person", "PersonRole", "TeamMember", "Employee", "Researcher", "Engineer", "Scientist", "Developer"}),
    # Organizations
    frozenset({"Organization", "Company", "Team", "Group", "Department"}),
    # Concepts / Topics
    frozenset({"Concept", "Topic", "Subject", "Theme", "Idea", "Theory", "Principle"}),
    # Methodologies / Approaches — LLM commonly confuses these
    frozenset({"Methodology", "Method", "Approach", "Strategy", "Technique", "ProcessStage"}),
    # Protocols / Standards (specific, not general technology)
    frozenset({"Protocol", "Standard", "Specification"}),
    # Documents / Resources
    frozenset({"Document", "Resource", "Article", "Paper", "Report"}),
    # Events / Milestones
    # NOTE: Meeting, Sprint, Deadline excluded — a meeting ABOUT a sprint
    # is not the sprint. These have specific semantics worth preserving.
    frozenset({"Event", "Milestone"}),
    # Metrics / Measurements
    frozenset({"Metric", "Measurement", "Score", "KPI", "Statistic", "Indicator"}),
    # Data entities — LLM oscillates between Dataset/DataStore/DataSource
    frozenset({"Dataset", "Data", "DataSource", "DataStore"}),
]

# Pre-compute a lookup: type_name_lower -> group_index for O(1) group check
_TYPE_TO_GROUP: dict[str, int] = {}
for _i, _group in enumerate(_MERGE_SAFE_TYPE_GROUPS):
    for _t in _group:
        _TYPE_TO_GROUP[_t.lower()] = _i


def _types_are_merge_safe(existing: str | None, requested: str | None) -> bool:
    """Return True if two type names likely refer to the same entity
    (LLM type drift) rather than a legitimate homonym.

    Uses three checks in order:
    1. Exact match → True
    2. Known homonym pairs → False (never merge)
    3. Same merge-safe group → True
    4. Prefix heuristic (backward compat) → True
    5. Default → False (conservative)
    """
    if not existing or not requested:
        return False
    if existing == requested:
        return True

    # Known homonym pairs — never merge
    pair = frozenset({existing, requested})
    if pair in _HOMONYM_TYPE_GROUPS:
        return False

    # Same merge-safe group → merge
    e_lower, r_lower = existing.lower(), requested.lower()
    e_group = _TYPE_TO_GROUP.get(e_lower)
    r_group = _TYPE_TO_GROUP.get(r_lower)
    if e_group is not None and r_group is not None and e_group == r_group:
        return True

    # Backward compat: prefix heuristic for types not in any group
    return e_lower.startswith(r_lower) or r_lower.startswith(e_lower)


class GraphServiceAdapter:
    """Adapt GraphService to the MemoryRepository protocol."""

    def __init__(
        self,
        graph: GraphService,
        router: GraphRouter | None = None,
        pool: asyncpg.Pool | None = None,
        pg: PostgresService | None = None,
        settings: MCPSettings | None = None,
    ):
        self._graph = graph
        self._router = router
        self._pool = pool
        self._pg = pg
        self._settings = settings or MCPSettings()

    def _scoped_conn(self, schema_name: str, agent_id: str, target_schema: str | None):
        """Return the appropriate scoped connection context manager.

        When target_schema is set (shared schema write), use graph_scoped_connection
        which validates shared graph access. For personal schemas, use schema_scoped_connection.
        """
        assert self._pool is not None, "Connection pool required for scoped connections"
        if target_schema is not None:
            return graph_scoped_connection(self._pool, schema_name, agent_id=agent_id)
        return schema_scoped_connection(self._pool, schema_name)

    def _apply_stm_boost(self, score: float, created_at: datetime | None) -> float:
        """Apply short-term memory boost for recent episodes."""
        if created_at is None:
            return score
        hours_ago = (datetime.now(UTC) - created_at).total_seconds() / 3600.0
        return score * compute_stm_boost(
            hours_ago=hours_ago,
            stm_window_hours=self._settings.episode_stm_window_hours,
            boost_factor=self._settings.episode_stm_boost_factor,
        )

    async def _resolve_schema(self, agent_id: str, target_schema: str | None = None) -> str:
        """Resolve the target schema name for write operations."""
        if target_schema is not None:
            return target_schema
        assert self._router is not None, "Router required for schema resolution"
        return await self._router.route_store(agent_id)

    async def store_episode(
        self,
        agent_id: str,
        content: str,
        context: str | None = None,
        source_type: str = "mcp",
        metadata: dict | None = None,
        importance: float = 0.5,
        content_hash: str | None = None,
        session_id: str | None = None,
    ) -> int:
        episode_metadata = metadata or {}
        if context:
            episode_metadata["context"] = context
        if self._pool is None or self._router is None:
            episode = await self._graph.create_episode(
                agent_id=agent_id,
                content=content,
                source_type=source_type,
                metadata=episode_metadata,
                content_hash=content_hash,
                session_id=session_id,
            )
            return episode.id

        schema_name = await self._router.route_store(agent_id)
        async with schema_scoped_connection(self._pool, schema_name) as conn:
            # Assign session_sequence under advisory lock if session_id is set
            session_sequence = None
            if session_id is not None:
                # Advisory lock keyed on deterministic hash of (schema_name, agent_id, session_id)
                lock_material = f"{schema_name}:{agent_id}:{session_id}"
                lock_key = int(hashlib.sha256(lock_material.encode()).hexdigest()[:16], 16) % (2**63 - 1)
                await conn.execute("SELECT pg_advisory_xact_lock($1)", lock_key)
                seq_row = await conn.fetchrow(
                    "SELECT COALESCE(MAX(session_sequence), 0) + 1 AS next_seq "
                    "FROM episode WHERE agent_id = $1 AND session_id = $2",
                    agent_id,
                    session_id,
                )
                session_sequence = seq_row["next_seq"]
            row = await conn.fetchrow(
                """INSERT INTO episode
                   (agent_id, content, source_type, metadata,
                    importance, content_hash, session_id, session_sequence)
                   VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7, $8)
                   RETURNING id""",
                agent_id,
                content,
                source_type,
                json.dumps(episode_metadata),
                importance,
                content_hash,
                session_id,
                session_sequence,
            )
        if row is None:
            raise RuntimeError("Failed to store episode.")
        return int(row["id"])

    async def store_episode_to(
        self,
        agent_id: str,
        target_schema: str,
        content: str,
        context: str | None = None,
        source_type: str = "mcp",
        metadata: dict | None = None,
        importance: float = 0.5,
        content_hash: str | None = None,
        session_id: str | None = None,
    ) -> int:
        episode_metadata = metadata or {}
        if context:
            episode_metadata["context"] = context
        if self._pool is None:
            raise RuntimeError("Connection pool required for store_episode_to.")

        async with graph_scoped_connection(self._pool, target_schema, agent_id=agent_id) as conn:
            # Assign session_sequence under advisory lock if session_id is set
            session_sequence = None
            if session_id is not None:
                lock_material = f"{target_schema}:{agent_id}:{session_id}"
                lock_key = int(hashlib.sha256(lock_material.encode()).hexdigest()[:16], 16) % (2**63 - 1)
                await conn.execute("SELECT pg_advisory_xact_lock($1)", lock_key)
                seq_row = await conn.fetchrow(
                    "SELECT COALESCE(MAX(session_sequence), 0) + 1 AS next_seq "
                    "FROM episode WHERE agent_id = $1 AND session_id = $2",
                    agent_id,
                    session_id,
                )
                session_sequence = seq_row["next_seq"]
            row = await conn.fetchrow(
                """INSERT INTO episode
                   (agent_id, content, source_type, metadata,
                    importance, owner_role, content_hash,
                    session_id, session_sequence)
                   VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7, $8, $9)
                   RETURNING id""",
                agent_id,
                content,
                source_type,
                json.dumps(episode_metadata),
                importance,
                agent_id,
                content_hash,
                session_id,
                session_sequence,
            )
        if row is None:
            raise RuntimeError("Failed to store episode.")
        return int(row["id"])

    async def check_episode_hashes(
        self,
        agent_id: str,
        hashes: list[str],
        target_schema: str | None = None,
    ) -> dict[str, int]:
        if not hashes:
            return {}
        if self._pool is None or self._router is None:
            return {}

        if target_schema is not None:
            async with graph_scoped_connection(self._pool, target_schema, agent_id=agent_id) as conn:
                rows = await conn.fetch(
                    """SELECT content_hash, id FROM episode
                       WHERE agent_id = $1 AND content_hash = ANY($2)""",
                    agent_id,
                    hashes,
                )
        else:
            schema_name = await self._router.route_store(agent_id)
            async with schema_scoped_connection(self._pool, schema_name) as conn:
                rows = await conn.fetch(
                    """SELECT content_hash, id FROM episode
                       WHERE agent_id = $1 AND content_hash = ANY($2)""",
                    agent_id,
                    hashes,
                )
        return {row["content_hash"]: int(row["id"]) for row in rows}

    async def recall(
        self,
        query: str,
        agent_id: str,
        limit: int = 10,
        query_embedding: list[float] | None = None,
        expand_neighbors: bool = True,
        episode_query_embedding: list[float] | None = None,
    ) -> list[RecallItem]:
        if self._pool is None or self._router is None:
            return await self._recall_via_graph(
                query=query, agent_id=agent_id, limit=limit, query_embedding=query_embedding
            )

        schemas = await self._router.route_recall(agent_id)
        results_per_schema = await asyncio.gather(
            *(
                self._recall_in_schema(
                    schema_name,
                    query,
                    agent_id,
                    limit,
                    query_embedding=query_embedding,
                    expand_neighbors=expand_neighbors,
                    episode_query_embedding=episode_query_embedding if schema_name.endswith("__personal") else None,
                )
                for schema_name in schemas
            )
        )
        merged_results = [item for batch in results_per_schema for item in batch]
        merged_results.sort(key=lambda item: (item.score, item.source_kind == "node"), reverse=True)
        deduped = _deduplicate_recall_items(merged_results)
        top_results = truncate_preserving_neighbors(deduped, limit)
        return _sort_session_clusters_chronologically(top_results)

    async def update_episode_embedding(
        self, episode_id: int, embedding: list[float], agent_id: str, target_schema: str | None = None
    ) -> None:
        emb_str = str(embedding)
        if self._pool is None or self._router is None:
            if self._pg is None:
                raise RuntimeError("No database connection available for update_episode_embedding.")
            await self._pg.execute(
                "UPDATE episode SET embedding = $1::vector WHERE id = $2",
                emb_str,
                episode_id,
            )
            return
        schema_name = await self._resolve_schema(agent_id, target_schema)
        async with self._scoped_conn(schema_name, agent_id, target_schema) as conn:
            await conn.execute(
                "UPDATE episode SET embedding = $1::vector WHERE id = $2",
                emb_str,
                episode_id,
            )

    async def get_node_types(self, agent_id: str | None = None, target_schema: str | None = None) -> list[TypeInfo]:
        if target_schema is not None and self._pool is not None and agent_id is not None:
            rows = await self._fetch_types_in_schema(target_schema, "node_type", agent_id)
            counts = await self._fetch_type_counts_in_schema(target_schema, "node", agent_id)
            return [
                TypeInfo(
                    id=int(row["id"]),
                    name=str(row["name"]),
                    description=str(row["description"]) if row["description"] is not None else None,
                    count=counts.get(int(row["id"]), 0),
                )
                for row in rows
            ]
        return await self._get_types(table_name="node_type", count_table="node", agent_id=agent_id)

    async def get_edge_types(self, agent_id: str | None = None, target_schema: str | None = None) -> list[TypeInfo]:
        if target_schema is not None and self._pool is not None and agent_id is not None:
            rows = await self._fetch_types_in_schema(target_schema, "edge_type", agent_id)
            counts = await self._fetch_type_counts_in_schema(target_schema, "edge", agent_id)
            return [
                TypeInfo(
                    id=int(row["id"]),
                    name=str(row["name"]),
                    description=str(row["description"]) if row["description"] is not None else None,
                    count=counts.get(int(row["id"]), 0),
                )
                for row in rows
            ]
        return await self._get_types(table_name="edge_type", count_table="edge", agent_id=agent_id)

    async def get_stats(self, agent_id: str | None = None) -> GraphStats:
        if self._pool is None or self._router is None or agent_id is None:
            stats = await self._graph.get_ontology_stats()
            return GraphStats(
                total_nodes=int(stats["total_nodes"]),
                total_edges=int(stats["total_edges"]),
                total_episodes=int(stats["total_episodes"]),
            )

        schemas = await self._router.route_discover(agent_id)
        totals = GraphStats(total_nodes=0, total_edges=0, total_episodes=0)
        activation_sum = 0.0
        active_node_count = 0
        for schema_name in schemas:
            schema_stats = await self._get_stats_in_schema(schema_name, agent_id)
            totals.total_nodes += schema_stats.total_nodes
            totals.total_edges += schema_stats.total_edges
            totals.total_episodes += schema_stats.total_episodes
            totals.forgotten_nodes += schema_stats.forgotten_nodes
            totals.consolidated_episodes += schema_stats.consolidated_episodes
            active_in_schema = schema_stats.total_nodes - schema_stats.forgotten_nodes
            if active_in_schema > 0:
                activation_sum += schema_stats.avg_activation * active_in_schema
                active_node_count += active_in_schema
        if active_node_count > 0:
            totals.avg_activation = round(activation_sum / active_node_count, 4)
        return totals

    async def list_graphs(self, agent_id: str) -> list[str]:
        if self._router is None:
            return []
        return await self._router.route_discover(agent_id)

    async def get_stats_for_schema(self, agent_id: str, schema_name: str) -> GraphStats:
        if self._pool is None:
            raise RuntimeError("Connection pool is required for get_stats_for_schema.")
        return await self._get_stats_in_schema(schema_name, agent_id)

    async def get_type_detail(self, agent_id: str, type_name: str, graph_name: str, kind: str) -> TypeDetail | None:
        if self._pool is None:
            raise RuntimeError("Connection pool is required for get_type_detail.")

        if kind == "node":
            return await self._get_node_type_detail(agent_id, type_name, graph_name)
        elif kind == "edge":
            return await self._get_edge_type_detail(agent_id, type_name, graph_name)
        return None

    async def _get_node_type_detail(self, agent_id: str, type_name: str, schema_name: str) -> TypeDetail | None:
        assert self._pool is not None
        async with graph_scoped_connection(self._pool, schema_name, agent_id=agent_id) as conn:
            row = await conn.fetchrow(
                "SELECT id, name, description FROM node_type WHERE name = $1",
                type_name,
            )
            if row is None:
                return None

            type_id = int(row["id"])
            count_row = await conn.fetchrow(
                "SELECT count(*) AS cnt FROM node WHERE type_id = $1",
                type_id,
            )
            count = int(count_row["cnt"]) if count_row else 0

            # Connected edge types: edge types where nodes of this type participate
            edge_rows = await conn.fetch(
                """SELECT DISTINCT et.name FROM edge_type et
                   JOIN edge e ON e.type_id = et.id
                   JOIN node n ON (n.id = e.source_id OR n.id = e.target_id)
                   WHERE n.type_id = $1""",
                type_id,
            )
            connected = [str(r["name"]) for r in edge_rows]

            # Sample node names
            sample_rows = await conn.fetch(
                "SELECT name FROM node WHERE type_id = $1 ORDER BY created_at DESC LIMIT 5",
                type_id,
            )
            samples = [str(r["name"]) for r in sample_rows]

        return TypeDetail(
            id=type_id,
            name=str(row["name"]),
            description=str(row["description"]) if row["description"] is not None else None,
            count=count,
            connected_edge_types=connected,
            sample_names=samples,
        )

    async def _get_edge_type_detail(self, agent_id: str, type_name: str, schema_name: str) -> TypeDetail | None:
        assert self._pool is not None
        async with graph_scoped_connection(self._pool, schema_name, agent_id=agent_id) as conn:
            row = await conn.fetchrow(
                "SELECT id, name, description FROM edge_type WHERE name = $1",
                type_name,
            )
            if row is None:
                return None

            type_id = int(row["id"])
            count_row = await conn.fetchrow(
                "SELECT count(*) AS cnt FROM edge WHERE type_id = $1",
                type_id,
            )
            count = int(count_row["cnt"]) if count_row else 0

            # Connected node types: source and target node types for this edge type
            node_type_rows = await conn.fetch(
                """SELECT DISTINCT nt.name FROM node_type nt
                   JOIN node n ON n.type_id = nt.id
                   JOIN edge e ON (e.source_id = n.id OR e.target_id = n.id)
                   WHERE e.type_id = $1""",
                type_id,
            )
            connected = [str(r["name"]) for r in node_type_rows]

            # Sample edge signatures
            sample_rows = await conn.fetch(
                """SELECT src.name AS src_name, tgt.name AS tgt_name
                   FROM edge e
                   JOIN node src ON src.id = e.source_id
                   JOIN node tgt ON tgt.id = e.target_id
                   WHERE e.type_id = $1
                   ORDER BY e.created_at DESC LIMIT 5""",
                type_id,
            )
            samples = [f"{r['src_name']}→{r['tgt_name']}" for r in sample_rows]

        return TypeDetail(
            id=type_id,
            name=str(row["name"]),
            description=str(row["description"]) if row["description"] is not None else None,
            count=count,
            connected_edge_types=connected,
            sample_names=samples,
        )

    # ── Type Management ──

    async def get_or_create_node_type(
        self, agent_id: str, name: str, description: str | None = None, target_schema: str | None = None
    ) -> NodeType | None:
        try:
            name = normalize_node_type(name)
        except ValueError as e:
            logger.bind(action_log=True).warning("invalid_node_type_rejected", raw_name=name, error=str(e))
            return None
        if target_schema is None and (self._pool is None or self._router is None):
            existing = await self._graph.get_node_type_by_name(name)
            if existing is not None:
                return existing
            return await self._graph.create_node_type(name, description)

        schema_name = await self._resolve_schema(agent_id, target_schema)
        async with self._scoped_conn(schema_name, agent_id, target_schema) as conn:
            row = await conn.fetchrow(
                """INSERT INTO node_type (name, description) VALUES ($1, $2)
                   ON CONFLICT (name) DO NOTHING
                   RETURNING *""",
                name,
                description,
            )
            if row is not None:
                return NodeType(**dict(row))
            # Concurrent insert won — fetch the existing row
            row = await conn.fetchrow("SELECT * FROM node_type WHERE name = $1", name)
            if row is None:
                raise RuntimeError(f"Failed to create node type: {name}")
            return NodeType(**dict(row))

    async def get_or_create_edge_type(
        self, agent_id: str, name: str, description: str | None = None, target_schema: str | None = None
    ) -> EdgeType | None:
        try:
            name = normalize_edge_type(name)
        except ValueError as e:
            logger.bind(action_log=True).warning("invalid_edge_type_rejected", raw_name=name, error=str(e))
            return None
        if target_schema is None and (self._pool is None or self._router is None):
            existing = await self._graph.get_edge_type_by_name(name)
            if existing is not None:
                return existing
            return await self._graph.create_edge_type(name, description)

        schema_name = await self._resolve_schema(agent_id, target_schema)
        async with self._scoped_conn(schema_name, agent_id, target_schema) as conn:
            row = await conn.fetchrow(
                """INSERT INTO edge_type (name, description) VALUES ($1, $2)
                   ON CONFLICT (name) DO NOTHING
                   RETURNING *""",
                name,
                description,
            )
            if row is not None:
                return EdgeType(**dict(row))
            # Concurrent insert won — fetch the existing row
            row = await conn.fetchrow("SELECT * FROM edge_type WHERE name = $1", name)
            if row is not None:
                return EdgeType(**dict(row))

            # Fallback: check for very similar existing type (e.g., after normalization
            # both are SCREAMING_SNAKE but differ by a word like singular/plural)
            similar = await conn.fetchrow(
                "SELECT * FROM edge_type WHERE similarity(name, $1) >= 0.8 ORDER BY similarity(name, $1) DESC LIMIT 1",
                name,
            )
            if similar:
                logger.bind(action_log=True).info(
                    "edge_type_similar_reuse",
                    requested=name,
                    reused=similar["name"],
                    similarity=await conn.fetchval("SELECT similarity($1, $2)", name, similar["name"]),
                )
                return EdgeType(**dict(similar))

            raise RuntimeError(f"Failed to create edge type: {name}")

    # ── Episode Read ──

    async def get_episode(self, agent_id: str, episode_id: int, target_schema: str | None = None) -> Episode | None:
        if target_schema is None and (self._pool is None or self._router is None):
            return await self._graph.get_episode(episode_id)

        schema_name = await self._resolve_schema(agent_id, target_schema)
        async with self._scoped_conn(schema_name, agent_id, target_schema) as conn:
            row = await conn.fetchrow(
                "SELECT id, agent_id, content, source_type, metadata, "
                "access_count, last_accessed_at, importance, consolidated, "
                "session_id, session_sequence, created_at "
                "FROM episode WHERE id = $1",
                episode_id,
            )
        if row is None:
            return None
        d = dict(row)
        if isinstance(d.get("metadata"), str):
            d["metadata"] = json.loads(d["metadata"])
        return Episode(**d)

    # ── Node CRUD ──

    async def upsert_node(
        self,
        agent_id: str,
        name: str,
        type_id: int,
        content: str | None = None,
        properties: dict | None = None,
        embedding: list[float] | None = None,
        source: str | None = None,
        target_schema: str | None = None,
        importance: float = 0.5,
    ) -> Node:
        props = properties or {}
        if target_schema is None and (self._pool is None or self._router is None):
            # Fallback: use GraphService directly with name-primary dedup
            canonical, _fallback_aliases = canonicalize_name(name)
            if canonical:
                name = canonical
            all_nodes = await self._graph.list_nodes(limit=10000)
            name_matches = [n for n in all_nodes if n.name.lower() == name.lower()]

            match: Node | None = None
            # Phase 1: Prefer exact (name, type_id) match
            for node in name_matches:
                if node.type_id == type_id:
                    match = node
                    break
            # Phase 2: Single name match with compatible type → merge
            if match is None and len(name_matches) == 1:
                existing_node = name_matches[0]
                # Look up type names for merge-safety check
                all_types = {nt.id: nt.name for nt in await self._graph.list_node_types()}
                existing_type = all_types.get(existing_node.type_id)
                requested_type = all_types.get(type_id)
                if _types_are_merge_safe(existing_type, requested_type):
                    match = existing_node
                    logger.bind(action_log=True).info(
                        "node_type_drift_caught",
                        name=name,
                        existing_type=existing_type,
                        requested_type=requested_type,
                        action="merged",
                        agent_id=agent_id,
                    )
                else:
                    logger.bind(action_log=True).info(
                        "node_homonym_detected",
                        name=name,
                        existing_type=existing_type,
                        requested_type=requested_type,
                        action="created_separate",
                        agent_id=agent_id,
                    )

            if match is not None:
                # Note: on merge-safe type drift, the node retains its original
                # type_id — we don't update the type to avoid flip-flopping.
                merged_props = {**match.properties, **props}
                updated = await self._graph.update_node(
                    match.id,
                    name=name,
                    content=content if content is not None else match.content,
                    properties=merged_props,
                    embedding=embedding,
                )
                return updated if updated is not None else match
            return await self._graph.create_node(
                type_id=type_id,
                name=name,
                content=content,
                properties=props,
                embedding=embedding,
                source=source,
            )

        schema_name = await self._resolve_schema(agent_id, target_schema)
        # Canonicalize the name and extract aliases for registration after insert
        canonical, canon_aliases = canonicalize_name(name)
        if canonical:
            name = canonical
        props_json = json.dumps(props)
        emb_str = str(embedding) if embedding else None
        async with self._scoped_conn(schema_name, agent_id, target_schema) as conn:
            # Phase 1: Look up by name only (name-primary dedup)
            # Include forgotten nodes so resurrection-on-upsert still works
            rows = await conn.fetch(
                "SELECT id, type_id, name, content, properties, source, importance, "
                "forgotten, created_at, updated_at "
                "FROM node WHERE lower(name) = lower($1)",
                name,
            )

            # Phase 1.5: If no exact match, try alias resolution then trigram.
            # Only POPULATES `rows` — Phase 2/3 still run on whatever it finds.
            if not rows:
                # 1.5a: Check alias table
                alias_rows = await conn.fetch(
                    "SELECT n.id, n.type_id, n.name, n.content, n.properties, "
                    "n.source, n.importance, n.forgotten, n.created_at, n.updated_at "
                    "FROM node n "
                    "JOIN node_alias a ON a.node_id = n.id "
                    "WHERE lower(a.alias) = lower($1) AND n.forgotten = false",
                    name,
                )
                if alias_rows:
                    rows = list(alias_rows)
                    logger.bind(action_log=True).info(
                        "node_alias_resolved",
                        alias=name,
                        candidates=[r["name"] for r in rows],
                        agent_id=agent_id,
                    )
                else:
                    # 1.5b: Trigram similarity fallback
                    fuzzy_rows = await conn.fetch(
                        "SELECT id, type_id, name, content, properties, source, "
                        "importance, forgotten, created_at, updated_at, "
                        "similarity(name, $1) AS sim "
                        "FROM node WHERE forgotten = false "
                        "AND similarity(name, $1) >= $2 "
                        "ORDER BY sim DESC LIMIT 1",
                        name,
                        0.3,
                    )
                    if fuzzy_rows:
                        rows = [fuzzy_rows[0]]
                        logger.bind(action_log=True).info(
                            "node_fuzzy_matched",
                            input=name,
                            matched=fuzzy_rows[0]["name"],
                            similarity=float(fuzzy_rows[0]["sim"]),
                            agent_id=agent_id,
                        )

            row = None
            if rows:
                # Phase 2: Prefer exact (name, type_id) match
                for r in rows:
                    if r["type_id"] == type_id:
                        row = r
                        break

                # Phase 3: If no exact match but exactly 1 node exists,
                # check whether the types are semantically compatible before merging.
                if row is None and len(rows) == 1:
                    existing_type_id = rows[0]["type_id"]
                    existing_type = await conn.fetchval("SELECT name FROM node_type WHERE id = $1", existing_type_id)
                    requested_type = await conn.fetchval("SELECT name FROM node_type WHERE id = $1", type_id)
                    if _types_are_merge_safe(existing_type, requested_type):
                        row = rows[0]
                        logger.bind(action_log=True).info(
                            "node_type_drift_caught",
                            name=name,
                            existing_type=existing_type,
                            requested_type=requested_type,
                            action="merged",
                            agent_id=agent_id,
                        )
                    else:
                        # Legitimate homonym — create separate node, log for monitoring
                        logger.bind(action_log=True).info(
                            "node_homonym_detected",
                            name=name,
                            existing_type=existing_type,
                            requested_type=requested_type,
                            action="created_separate",
                            agent_id=agent_id,
                        )

            if row is not None:
                # Note: on merge-safe type drift, the node retains its original
                # type_id — we don't update the type to avoid flip-flopping.
                existing_props = row["properties"]
                if isinstance(existing_props, str):
                    existing_props = json.loads(existing_props)
                merged = {**(existing_props or {}), **props}
                merged_json = json.dumps(merged)
                updated_row = await conn.fetchrow(
                    """UPDATE node SET
                        -- Content: prefer new value, keep old only when new is NULL
                        content = COALESCE($1, content),
                        properties = $2::jsonb,
                        embedding = COALESCE($3::vector, embedding),
                        importance = GREATEST(importance, $5),
                        forgotten = false,
                        forgotten_at = NULL,
                        access_count = CASE WHEN forgotten THEN access_count + 1 ELSE access_count END,
                        last_accessed_at = CASE WHEN forgotten THEN now() ELSE last_accessed_at END,
                        updated_at = now()
                       WHERE id = $4
                       RETURNING id, type_id, name, content, properties, source, importance,
                                 access_count, last_accessed_at, forgotten, forgotten_at,
                                 created_at, updated_at""",
                    content,
                    merged_json,
                    emb_str,
                    row["id"],
                    importance,
                )
                if updated_row is None:
                    logger.bind(action_log=True).warning(
                        "upsert_node_update_missed",
                        node_id=row["id"],
                        name=name,
                        agent_id=agent_id,
                        target_schema=target_schema,
                        msg="UPDATE matched 0 rows (concurrent delete?), falling back to INSERT",
                    )
                    # Fall through to INSERT below
                else:
                    d = dict(updated_row)
                    if isinstance(d.get("properties"), str):
                        d["properties"] = json.loads(d["properties"])
                    return Node(**d)

            # INSERT path: reached when no existing node found OR update missed
            if target_schema is not None:
                new_row = await conn.fetchrow(
                    """INSERT INTO node
                       (type_id, name, content, properties, embedding, source, importance, owner_role)
                       VALUES ($1, $2, $3, $4::jsonb, $5::vector, $6, $7, $8)
                       RETURNING id, type_id, name, content, properties, source, importance,
                                 access_count, last_accessed_at, forgotten, forgotten_at,
                                 created_at, updated_at""",
                    type_id,
                    name,
                    content,
                    props_json,
                    emb_str,
                    source,
                    importance,
                    agent_id,
                )
            else:
                new_row = await conn.fetchrow(
                    """INSERT INTO node (type_id, name, content, properties, embedding, source, importance)
                       VALUES ($1, $2, $3, $4::jsonb, $5::vector, $6, $7)
                       RETURNING id, type_id, name, content, properties, source, importance,
                                 access_count, last_accessed_at, forgotten, forgotten_at,
                                 created_at, updated_at""",
                    type_id,
                    name,
                    content,
                    props_json,
                    emb_str,
                    source,
                    importance,
                )
            if new_row is None:
                raise RuntimeError("Failed to create node")
            d = dict(new_row)
            if isinstance(d.get("properties"), str):
                d["properties"] = json.loads(d["properties"])
            new_node = Node(**d)
            # Auto-register canonicalization aliases for the new node
            for alias in canon_aliases:
                await conn.execute(
                    "INSERT INTO node_alias (node_id, alias, source) "
                    "VALUES ($1, $2, 'canonicalization') "
                    "ON CONFLICT (alias, node_id) DO NOTHING",
                    new_node.id,
                    alias,
                )
            return new_node

    async def find_nodes_by_name(self, agent_id: str, name: str, target_schema: str | None = None) -> list[Node]:
        if target_schema is None and (self._pool is None or self._router is None):
            nodes = await self._graph.list_nodes(limit=10000)
            return [n for n in nodes if n.name.lower() == name.lower()]

        schema_name = await self._resolve_schema(agent_id, target_schema)
        async with self._scoped_conn(schema_name, agent_id, target_schema) as conn:
            rows = await conn.fetch(
                "SELECT id, type_id, name, content, properties, source, created_at, updated_at "
                "FROM node WHERE lower(name) = lower($1) AND forgotten = false",
                name,
            )
        results = []
        for row in rows:
            d = dict(row)
            if isinstance(d.get("properties"), str):
                d["properties"] = json.loads(d["properties"])
            results.append(Node(**d))
        return results

    # ── Fuzzy Name Matching & Aliases ──

    async def find_nodes_fuzzy(
        self,
        agent_id: str,
        name: str,
        threshold: float = 0.3,
        limit: int = 5,
        target_schema: str | None = None,
    ) -> list[tuple[Node, float]]:
        schema_name = await self._resolve_schema(agent_id, target_schema)
        async with self._scoped_conn(schema_name, agent_id, target_schema) as conn:
            rows = await conn.fetch(
                "SELECT n.id, n.type_id, n.name, n.content, n.properties, n.source, "
                "n.importance, n.created_at, n.updated_at, "
                "CASE WHEN n.id IN (SELECT node_id FROM node_alias WHERE lower(alias) = lower($1)) "
                "     THEN GREATEST(similarity(n.name, $1), 1.0) "
                "     ELSE similarity(n.name, $1) END AS sim "
                "FROM node n "
                "WHERE n.forgotten = false "
                "AND (similarity(n.name, $1) >= $2 "
                "     OR n.id IN (SELECT node_id FROM node_alias WHERE lower(alias) = lower($1))) "
                "ORDER BY sim DESC "
                "LIMIT $3",
                name,
                threshold,
                limit,
            )
        results: list[tuple[Node, float]] = []
        for row in rows:
            d = dict(row)
            sim = d.pop("sim", 0.0)
            if isinstance(d.get("properties"), str):
                d["properties"] = json.loads(d["properties"])
            results.append((Node(**d), float(sim)))
        return results

    async def register_alias(
        self,
        agent_id: str,
        node_id: int,
        alias: str,
        source: str = "extraction",
        target_schema: str | None = None,
    ) -> None:
        schema_name = await self._resolve_schema(agent_id, target_schema)
        async with self._scoped_conn(schema_name, agent_id, target_schema) as conn:
            await conn.execute(
                "INSERT INTO node_alias (node_id, alias, source) "
                "VALUES ($1, $2, $3) "
                "ON CONFLICT (alias, node_id) DO NOTHING",
                node_id,
                alias,
                source,
            )

    async def resolve_alias(
        self,
        agent_id: str,
        alias: str,
        target_schema: str | None = None,
    ) -> list[Node]:
        schema_name = await self._resolve_schema(agent_id, target_schema)
        async with self._scoped_conn(schema_name, agent_id, target_schema) as conn:
            rows = await conn.fetch(
                "SELECT n.id, n.type_id, n.name, n.content, n.properties, n.source, "
                "n.importance, n.forgotten, n.created_at, n.updated_at "
                "FROM node n "
                "JOIN node_alias a ON a.node_id = n.id "
                "WHERE lower(a.alias) = lower($1) "
                "AND n.forgotten = false",
                alias,
            )
        results: list[Node] = []
        for row in rows:
            d = dict(row)
            if isinstance(d.get("properties"), str):
                d["properties"] = json.loads(d["properties"])
            results.append(Node(**d))
        return results

    # ── Edge CRUD ──

    async def upsert_edge(
        self,
        agent_id: str,
        source_id: int,
        target_id: int,
        type_id: int,
        weight: float = 1.0,
        properties: dict | None = None,
        target_schema: str | None = None,
    ) -> Edge | None:
        props = properties or {}
        if target_schema is None and (self._pool is None or self._router is None):
            # Source-target primary edge dedup via GraphService
            all_edges = await self._graph.get_edges_from(source_id)
            st_edges = [e for e in all_edges if e.target_id == target_id]

            if len(st_edges) == 1 and st_edges[0].type_id != type_id:
                # Single edge with different type → drift, update it
                old = st_edges[0]
                merged = {**old.properties, **props}
                logger.bind(action_log=True).info(
                    "edge_type_drift_caught",
                    source_id=source_id,
                    target_id=target_id,
                    old_type_id=old.type_id,
                    new_type_id=type_id,
                )
                await self._graph.delete_edge(old.id)
                return await self._graph.create_edge(
                    source_id=source_id,
                    target_id=target_id,
                    type_id=type_id,
                    weight=weight,
                    properties=merged,
                )

            # Normal path: exact type match or 0/2+ existing
            for edge in st_edges:
                if edge.type_id == type_id:
                    merged = {**edge.properties, **props}
                    await self._graph.delete_edge(edge.id)
                    return await self._graph.create_edge(
                        source_id=source_id,
                        target_id=target_id,
                        type_id=type_id,
                        weight=weight,
                        properties=merged,
                    )
            return await self._graph.create_edge(
                source_id=source_id,
                target_id=target_id,
                type_id=type_id,
                weight=weight,
                properties=props,
            )

        schema_name = await self._resolve_schema(agent_id, target_schema)
        props_json = json.dumps(props)
        async with self._scoped_conn(schema_name, agent_id, target_schema) as conn:
            # Source-target primary edge dedup: check existing edges between this pair
            existing = await conn.fetch(
                "SELECT id, type_id, weight, properties FROM edge WHERE source_id = $1 AND target_id = $2",
                source_id,
                target_id,
            )

            if len(existing) == 1 and existing[0]["type_id"] != type_id:
                # Single edge with different type → drift, update the existing one
                old = existing[0]
                old_props = old["properties"]
                if isinstance(old_props, str):
                    old_props = json.loads(old_props)
                merged = {**(old_props or {}), **props}
                merged_json = json.dumps(merged)
                row = await conn.fetchrow(
                    "UPDATE edge SET type_id = $1, weight = $2, "
                    "properties = $3::jsonb, last_reinforced_at = now() "
                    "WHERE id = $4 RETURNING *",
                    type_id,
                    weight,
                    merged_json,
                    old["id"],
                )
                logger.bind(action_log=True).info(
                    "edge_type_drift_caught",
                    source_id=source_id,
                    target_id=target_id,
                    old_type_id=old["type_id"],
                    new_type_id=type_id,
                )
            else:
                # Normal path: INSERT...ON CONFLICT (exact match or 0/2+ existing)
                if target_schema is not None:
                    row = await conn.fetchrow(
                        """INSERT INTO edge (source_id, target_id, type_id, weight, properties, owner_role)
                           VALUES ($1, $2, $3, $4, $5::jsonb, $6)
                           ON CONFLICT (source_id, target_id, type_id)
                           DO UPDATE SET
                               weight = $4,
                               properties = edge.properties || $5::jsonb
                           RETURNING *""",
                        source_id,
                        target_id,
                        type_id,
                        weight,
                        props_json,
                        agent_id,
                    )
                else:
                    row = await conn.fetchrow(
                        """INSERT INTO edge (source_id, target_id, type_id, weight, properties)
                           VALUES ($1, $2, $3, $4, $5::jsonb)
                           ON CONFLICT (source_id, target_id, type_id)
                           DO UPDATE SET
                               weight = $4,
                               properties = edge.properties || $5::jsonb
                           RETURNING *""",
                        source_id,
                        target_id,
                        type_id,
                        weight,
                        props_json,
                    )
            if row is None:
                logger.bind(action_log=True).warning(
                    "upsert_edge_failed",
                    source_id=source_id,
                    target_id=target_id,
                    type_id=type_id,
                    agent_id=agent_id,
                    msg="INSERT ON CONFLICT returned no row — unexpected DB error",
                )
                return None
            d = dict(row)
            if isinstance(d.get("properties"), str):
                d["properties"] = json.loads(d["properties"])
            return Edge(**d)

    async def delete_edge(
        self,
        agent_id: str,
        edge_id: int,
        target_schema: str | None = None,
    ) -> bool:
        if target_schema is None and (self._pool is None or self._router is None):
            await self._graph.delete_edge(edge_id)
            return True

        schema_name = await self._resolve_schema(agent_id, target_schema)
        async with self._scoped_conn(schema_name, agent_id, target_schema) as conn:
            result = await conn.execute(
                "DELETE FROM edge WHERE id = $1",
                edge_id,
            )
        return result == "DELETE 1"

    # ── Node Search ──

    async def search_nodes(
        self,
        agent_id: str,
        query: str,
        limit: int = 5,
        query_embedding: list[float] | None = None,
    ) -> list[tuple[Node, float]]:
        if self._pool is None or self._router is None:
            # Fallback: simple text matching via GraphService
            nodes = await self._graph.list_nodes(limit=10000)
            query_lower = query.lower()
            matches: list[tuple[Node, float]] = []
            for n in nodes:
                name_match = query_lower in n.name.lower()
                content_match = n.content and query_lower in n.content.lower()
                if name_match or content_match:
                    relevance = 1.0 if name_match else 0.5
                    matches.append((n, relevance))
            matches.sort(key=lambda x: x[1], reverse=True)
            return matches[:limit]

        schemas = await self._router.route_recall(agent_id)
        all_results: list[tuple[Node, float]] = []
        for schema_name in schemas:
            results = await self._search_nodes_in_schema(schema_name, query, agent_id, limit, query_embedding)
            all_results.extend(results)
        # Deduplicate by (name, type_id) keeping highest-scoring occurrence
        seen: dict[tuple[str, int], int] = {}
        deduped: list[tuple[Node, float]] = []
        for node, score in all_results:
            key = (node.name.lower(), node.type_id)
            if key not in seen:
                seen[key] = len(deduped)
                deduped.append((node, score))
            elif score > deduped[seen[key]][1]:
                deduped[seen[key]] = (node, score)
        deduped.sort(key=lambda x: x[1], reverse=True)
        return deduped[:limit]

    async def _search_nodes_in_schema(
        self,
        schema_name: str,
        query: str,
        agent_id: str,
        limit: int,
        query_embedding: list[float] | None = None,
    ) -> list[tuple[Node, float]]:
        if self._pool is None:
            raise RuntimeError("Connection pool required")

        async with graph_scoped_connection(self._pool, schema_name, agent_id=agent_id) as conn:
            if query_embedding is not None:
                emb_str = str(query_embedding)
                rows = await conn.fetch(
                    """SELECT id, type_id, name, content, properties, source,
                              created_at, updated_at,
                              ts_rank(tsv, plainto_tsquery('english', $1)) AS text_rank,
                              CASE WHEN embedding IS NOT NULL
                                   THEN 1 - (embedding <=> $2::vector)
                                   ELSE 0
                              END AS vector_sim
                       FROM node
                       WHERE forgotten = false
                         AND (tsv @@ plainto_tsquery('english', $1)
                          OR (embedding IS NOT NULL AND (embedding <=> $2::vector) < $3)
                          OR lower(name) ILIKE '%' || $4 || '%' ESCAPE '\\')
                       ORDER BY GREATEST(
                           COALESCE(ts_rank(tsv, plainto_tsquery('english', $1)), 0),
                           CASE WHEN embedding IS NOT NULL
                                THEN 1 - (embedding <=> $2::vector)
                                ELSE 0
                           END
                       ) DESC
                       LIMIT $5""",
                    query,
                    emb_str,
                    self._settings.recall_vector_distance_threshold,
                    _escape_ilike(query).lower(),
                    limit,
                )
            else:
                rows = await conn.fetch(
                    """SELECT id, type_id, name, content, properties, source,
                              created_at, updated_at,
                              ts_rank(tsv, plainto_tsquery('english', $1)) AS text_rank
                       FROM node
                       WHERE forgotten = false
                         AND (tsv @@ plainto_tsquery('english', $1)
                          OR lower(name) ILIKE '%' || $2 || '%' ESCAPE '\\')
                       ORDER BY ts_rank(tsv, plainto_tsquery('english', $1)) DESC
                       LIMIT $3""",
                    query,
                    _escape_ilike(query).lower(),
                    limit,
                )

        results: list[tuple[Node, float]] = []
        for row in rows:
            d = dict(row)
            text_rank = d.pop("text_rank", 0.0) or 0.0
            vector_sim = d.pop("vector_sim", 0.0) or 0.0
            relevance = max(float(text_rank), float(vector_sim))
            if isinstance(d.get("properties"), str):
                d["properties"] = json.loads(d["properties"])
            results.append((Node(**d), relevance))
        return results

    # ── Node Browsing ──

    async def list_nodes_page(
        self,
        agent_id: str,
        target_schema: str | None = None,
        type_id: int | None = None,
        limit: int = 20,
    ) -> list[Node]:
        if target_schema is None and (self._pool is None or self._router is None):
            nodes = await self._graph.list_nodes(limit=10000)
            filtered = [n for n in nodes if not n.forgotten]
            if type_id is not None:
                filtered = [n for n in filtered if n.type_id == type_id]
            filtered.sort(key=lambda n: (n.importance, n.access_count), reverse=True)
            return filtered[:limit]

        schema_name = await self._resolve_schema(agent_id, target_schema)
        if type_id is not None:
            query = (
                "SELECT id, type_id, name, content, properties, source, importance, "
                "access_count, forgotten, created_at, updated_at "
                "FROM node WHERE forgotten = false AND type_id = $1 "
                "ORDER BY importance DESC, access_count DESC LIMIT $2"
            )
            params: tuple = (type_id, limit)
        else:
            query = (
                "SELECT id, type_id, name, content, properties, source, importance, "
                "access_count, forgotten, created_at, updated_at "
                "FROM node WHERE forgotten = false "
                "ORDER BY importance DESC, access_count DESC LIMIT $1"
            )
            params = (limit,)

        async with self._scoped_conn(schema_name, agent_id, target_schema) as conn:
            rows = await conn.fetch(query, *params)

        results = []
        for row in rows:
            d = dict(row)
            if isinstance(d.get("properties"), str):
                d["properties"] = json.loads(d["properties"])
            results.append(Node(**d))
        return results

    # ── Graph Traversal ──

    async def get_node_neighborhood(self, agent_id: str, node_id: int, depth: int = 2) -> list[dict]:
        if self._pool is None or self._router is None:
            return await self._bfs_via_graph_service(node_id, depth)

        schema_name = await self._router.route_store(agent_id)
        return await self._bfs_in_schema(schema_name, node_id, depth)

    async def _bfs_via_graph_service(self, node_id: int, depth: int) -> list[dict]:
        visited: set[int] = {node_id}
        results: list[dict] = []
        current_frontier = [node_id]

        for dist in range(1, depth + 1):
            next_frontier: list[int] = []
            for nid in current_frontier:
                neighbors = await self._graph.get_neighbors(nid)
                for neighbor in neighbors:
                    neighbor_id = int(neighbor["id"])
                    if neighbor_id not in visited:
                        visited.add(neighbor_id)
                        next_frontier.append(neighbor_id)
                        neighbor_node = await self._graph.get_node(neighbor_id)
                        if neighbor_node is not None and not getattr(neighbor_node, "forgotten", False):
                            edge_id = int(neighbor["edge_id"])
                            edge = await self._graph.get_edge(edge_id)
                            results.append(
                                {
                                    "node": neighbor_node,
                                    "edges": [edge] if edge else [],
                                    "distance": dist,
                                }
                            )
            current_frontier = next_frontier
            if not current_frontier:
                break

        return results

    async def _bfs_in_schema(self, schema_name: str, node_id: int, depth: int) -> list[dict]:
        if self._pool is None:
            raise RuntimeError("Connection pool required")

        visited: set[int] = {node_id}
        results: list[dict] = []
        current_frontier = [node_id]

        for dist in range(1, depth + 1):
            if not current_frontier:
                break
            next_frontier: list[int] = []
            async with schema_scoped_connection(self._pool, schema_name) as conn:
                for nid in current_frontier:
                    # Get all edges connected to this node
                    edge_rows = await conn.fetch(
                        """SELECT e.*, 'outgoing' AS direction
                           FROM edge e WHERE e.source_id = $1
                           UNION ALL
                           SELECT e.*, 'incoming' AS direction
                           FROM edge e WHERE e.target_id = $1""",
                        nid,
                    )
                    for erow in edge_rows:
                        ed = dict(erow)
                        direction = ed.pop("direction")
                        neighbor_id = int(ed["target_id"]) if direction == "outgoing" else int(ed["source_id"])
                        if neighbor_id in visited:
                            continue
                        visited.add(neighbor_id)
                        next_frontier.append(neighbor_id)

                        if isinstance(ed.get("properties"), str):
                            ed["properties"] = json.loads(ed["properties"])
                        edge_obj = Edge(**ed)

                        node_row = await conn.fetchrow(
                            "SELECT id, type_id, name, content, properties, source, "
                            "created_at, updated_at FROM node WHERE id = $1 AND forgotten = false",
                            neighbor_id,
                        )
                        if node_row is not None:
                            nd = dict(node_row)
                            if isinstance(nd.get("properties"), str):
                                nd["properties"] = json.loads(nd["properties"])
                            node_obj = Node(**nd)
                            results.append(
                                {
                                    "node": node_obj,
                                    "edges": [edge_obj],
                                    "distance": dist,
                                }
                            )
            current_frontier = next_frontier

        return results

    # ── Bulk Queries ──

    async def list_all_node_names(
        self, agent_id: str, target_schema: str | None = None, limit: int | None = None
    ) -> list[str]:
        if target_schema is None and (self._pool is None or self._router is None):
            nodes = await self._graph.list_nodes(limit=limit or 100000)
            return [n.name for n in nodes]

        schema_name = await self._resolve_schema(agent_id, target_schema)
        limit_clause = f" LIMIT {int(limit)}" if limit is not None else ""
        async with self._scoped_conn(schema_name, agent_id, target_schema) as conn:
            rows = await conn.fetch(f"SELECT name FROM node WHERE forgotten = false ORDER BY name{limit_clause}")
        return [str(row["name"]) for row in rows]

    # ── Access Tracking ──

    async def record_node_access(self, agent_id: str, node_ids: list[int], limit: int | None = None) -> None:
        if not node_ids:
            return
        if self._pool is None or self._router is None:
            return

        if limit is None:
            limit = self._settings.recall_access_increment_limit
        ids_to_update = node_ids[:limit]

        schema_name = await self._router.route_store(agent_id)
        async with schema_scoped_connection(self._pool, schema_name) as conn:
            await conn.execute(
                "UPDATE node SET access_count = access_count + 1, last_accessed_at = now() WHERE id = ANY($1::int[])",
                ids_to_update,
            )

    async def record_episode_access(self, agent_id: str, episode_ids: list[int], limit: int | None = None) -> None:
        if not episode_ids:
            return
        if self._pool is None or self._router is None:
            return

        if limit is None:
            limit = self._settings.recall_access_increment_limit
        ids_to_update = episode_ids[:limit]

        schema_name = await self._router.route_store(agent_id)
        async with schema_scoped_connection(self._pool, schema_name) as conn:
            await conn.execute(
                "UPDATE episode SET access_count = access_count + 1, last_accessed_at = now() "
                "WHERE id = ANY($1::int[])",
                ids_to_update,
            )

    # ── Soft-Forget ──

    async def mark_forgotten(self, agent_id: str, node_ids: list[int], target_schema: str | None = None) -> int:
        if not node_ids:
            return 0
        if self._pool is None or self._router is None:
            return 0

        schema_name = await self._resolve_schema(agent_id, target_schema)
        async with self._scoped_conn(schema_name, agent_id, target_schema) as conn:
            result = await conn.execute(
                "UPDATE node SET forgotten = true, forgotten_at = now() "
                "WHERE id = ANY($1::int[]) AND forgotten = false",
                node_ids,
            )
        count = int(result.split()[-1]) if result else 0
        return count

    async def resurrect_node(self, agent_id: str, node_id: int) -> None:
        if self._pool is None or self._router is None:
            return

        schema_name = await self._router.route_store(agent_id)
        async with schema_scoped_connection(self._pool, schema_name) as conn:
            await conn.execute(
                "UPDATE node SET forgotten = false, forgotten_at = NULL, "
                "access_count = access_count + 1, last_accessed_at = now() "
                "WHERE id = $1",
                node_id,
            )

    async def identify_forgettable_nodes(
        self, agent_id: str, activation_threshold: float, importance_floor: float
    ) -> list[int]:
        if self._pool is None or self._router is None:
            return []

        schema_name = await self._router.route_store(agent_id)
        async with schema_scoped_connection(self._pool, schema_name) as conn:
            rows = await conn.fetch(
                "SELECT id FROM node "
                "WHERE forgotten = false "
                "AND importance < $1 "
                "AND access_count = 0 "
                "AND last_accessed_at < now() - interval '7 days'",
                importance_floor,
            )
        return [int(row["id"]) for row in rows]

    # ── Type Introspection ──

    async def get_type_examples(
        self,
        agent_id: str,
        target_schema: str | None = None,
        limit_per_type: int = 5,
        max_types: int = 20,
    ) -> dict[str, list[str]]:
        """Fetch sample node names grouped by type for context injection."""
        if self._pool is None or self._router is None:
            return {}
        schema = target_schema or await self._resolve_schema(agent_id, None)
        async with schema_scoped_connection(self._pool, schema) as conn:
            rows = await conn.fetch(
                "SELECT nt.name as type_name, "
                "  (SELECT array_agg(sub.name ORDER BY sub.importance DESC) "
                "   FROM (SELECT name, importance FROM node "
                "         WHERE type_id = nt.id AND NOT forgotten "
                "         ORDER BY importance DESC LIMIT $1) sub"
                "  ) as examples "
                "FROM node_type nt "
                "WHERE EXISTS (SELECT 1 FROM node WHERE type_id = nt.id AND NOT forgotten) "
                "LIMIT $2",
                limit_per_type,
                max_types,
            )
            return {r["type_name"]: r["examples"] for r in rows if r["examples"]}

    async def cleanup_empty_types(
        self,
        agent_id: str,
        max_age_minutes: int = 5,
        target_schema: str | None = None,
    ) -> None:
        """Delete node types with zero nodes that were created recently."""
        if self._pool is None or self._router is None:
            return
        schema = target_schema or await self._resolve_schema(agent_id, None)
        async with schema_scoped_connection(self._pool, schema) as conn:
            deleted = await conn.fetch(
                "DELETE FROM node_type WHERE id NOT IN "
                "(SELECT DISTINCT type_id FROM node WHERE type_id IS NOT NULL) "
                "AND created_at < now() - make_interval(mins => $1) RETURNING name",
                max_age_minutes,
            )
            if deleted:
                logger.info(
                    "cleaned_empty_types",
                    count=len(deleted),
                    names=[r["name"] for r in deleted],
                )

    # ── Ontology Exploration ──

    async def find_similar_types(
        self,
        agent_id: str,
        query: str,
        kind: Literal["node", "edge"] = "node",
        limit: int = 5,
        target_schema: str | None = None,
    ) -> list[tuple[TypeInfo, int, list[str]]]:
        if self._pool is None or self._router is None:
            return []
        schema_name = await self._resolve_schema(agent_id, target_schema)
        async with self._scoped_conn(schema_name, agent_id, target_schema) as conn:
            if kind == "edge":
                rows = await conn.fetch(
                    "SELECT t.id, t.name, t.description, "
                    "similarity(t.name, $1) AS sim, "
                    "COUNT(e.id) AS usage_count "
                    "FROM edge_type t "
                    "LEFT JOIN edge e ON e.type_id = t.id "
                    "WHERE similarity(t.name, $1) > 0.2 "
                    "   OR t.name ILIKE '%' || $1 || '%' "
                    "   OR t.description ILIKE '%' || $1 || '%' "
                    "GROUP BY t.id "
                    "ORDER BY sim DESC "
                    "LIMIT $2",
                    query,
                    limit,
                )
                # Fetch example edge signatures per matched type
                results: list[tuple[TypeInfo, int, list[str]]] = []
                for row in rows:
                    example_rows = await conn.fetch(
                        "SELECT src.name || '→' || tgt.name AS sig "
                        "FROM edge e "
                        "JOIN node src ON src.id = e.source_id "
                        "JOIN node tgt ON tgt.id = e.target_id "
                        "WHERE e.type_id = $1 "
                        "ORDER BY e.created_at DESC LIMIT 3",
                        row["id"],
                    )
                    examples = [r["sig"] for r in example_rows]
                    results.append(
                        (
                            TypeInfo(
                                id=row["id"],
                                name=row["name"],
                                description=row["description"],
                            ),
                            int(row["usage_count"]),
                            examples,
                        )
                    )
                return results
            else:
                rows = await conn.fetch(
                    "SELECT t.id, t.name, t.description, "
                    "similarity(t.name, $1) AS sim, "
                    "COUNT(n.id) AS usage_count "
                    "FROM node_type t "
                    "LEFT JOIN node n ON n.type_id = t.id AND NOT n.forgotten "
                    "WHERE similarity(t.name, $1) > 0.2 "
                    "   OR t.name ILIKE '%' || $1 || '%' "
                    "   OR t.description ILIKE '%' || $1 || '%' "
                    "GROUP BY t.id "
                    "ORDER BY sim DESC "
                    "LIMIT $2",
                    query,
                    limit,
                )
                results = []
                for row in rows:
                    example_rows = await conn.fetch(
                        "SELECT n.name FROM node n "
                        "WHERE n.type_id = $1 AND NOT n.forgotten "
                        "ORDER BY n.importance DESC LIMIT 3",
                        row["id"],
                    )
                    examples = [r["name"] for r in example_rows]
                    results.append(
                        (
                            TypeInfo(
                                id=row["id"],
                                name=row["name"],
                                description=row["description"],
                            ),
                            int(row["usage_count"]),
                            examples,
                        )
                    )
                return results

    async def get_ontology_summary(
        self,
        agent_id: str,
        target_schema: str | None = None,
    ) -> dict:
        if self._pool is None or self._router is None:
            return {"node_types": [], "edge_types": [], "total_nodes": 0, "total_edges": 0}
        schema_name = await self._resolve_schema(agent_id, target_schema)
        async with self._scoped_conn(schema_name, agent_id, target_schema) as conn:
            node_type_rows = await conn.fetch(
                "SELECT t.name, t.description, COUNT(n.id) AS usage_count "
                "FROM node_type t "
                "LEFT JOIN node n ON n.type_id = t.id AND NOT n.forgotten "
                "GROUP BY t.id ORDER BY usage_count DESC"
            )
            edge_type_rows = await conn.fetch(
                "SELECT t.name, t.description, COUNT(e.id) AS usage_count "
                "FROM edge_type t "
                "LEFT JOIN edge e ON e.type_id = t.id "
                "GROUP BY t.id ORDER BY usage_count DESC"
            )
            total_nodes = await conn.fetchval("SELECT COUNT(*) FROM node WHERE NOT forgotten")
            total_edges = await conn.fetchval("SELECT COUNT(*) FROM edge")
        return {
            "node_types": [
                {"name": r["name"], "description": r["description"] or "", "usage_count": int(r["usage_count"])}
                for r in node_type_rows
            ],
            "edge_types": [
                {"name": r["name"], "description": r["description"] or "", "usage_count": int(r["usage_count"])}
                for r in edge_type_rows
            ],
            "total_nodes": int(total_nodes or 0),
            "total_edges": int(total_edges or 0),
        }

    # ── Type Consolidation ──

    async def reassign_node_type(
        self,
        agent_id: str,
        source_type_id: int,
        target_type_id: int,
        target_schema: str | None = None,
    ) -> int:
        if self._pool is None or self._router is None:
            return 0
        schema_name = await self._resolve_schema(agent_id, target_schema)
        async with self._scoped_conn(schema_name, agent_id, target_schema) as conn:
            result = await conn.execute(
                "UPDATE node SET type_id = $2 WHERE type_id = $1",
                source_type_id,
                target_type_id,
            )
            return int(result.split()[-1]) if result else 0

    async def delete_type(
        self,
        agent_id: str,
        type_id: int,
        kind: Literal["node", "edge"] = "node",
        target_schema: str | None = None,
    ) -> None:
        if self._pool is None or self._router is None:
            return
        schema_name = await self._resolve_schema(agent_id, target_schema)
        async with self._scoped_conn(schema_name, agent_id, target_schema) as conn:
            if kind == "edge":
                count = await conn.fetchval("SELECT COUNT(*) FROM edge WHERE type_id = $1", type_id)
                if count and count > 0:
                    raise ValueError(f"Cannot delete edge type {type_id}: still has {count} edges")
                await conn.execute("DELETE FROM edge_type WHERE id = $1", type_id)
            else:
                count = await conn.fetchval("SELECT COUNT(*) FROM node WHERE type_id = $1", type_id)
                if count and count > 0:
                    raise ValueError(f"Cannot delete node type {type_id}: still has {count} nodes")
                await conn.execute("DELETE FROM node_type WHERE id = $1", type_id)

    async def get_unused_types(
        self,
        agent_id: str,
        kind: Literal["node", "edge"] = "node",
        min_age_hours: float = 24.0,
        target_schema: str | None = None,
    ) -> list[tuple[int, str, datetime]]:
        if self._pool is None or self._router is None:
            return []
        schema_name = await self._resolve_schema(agent_id, target_schema)
        async with self._scoped_conn(schema_name, agent_id, target_schema) as conn:
            if kind == "edge":
                rows = await conn.fetch(
                    "SELECT t.id, t.name, t.created_at "
                    "FROM edge_type t "
                    "LEFT JOIN edge e ON e.type_id = t.id "
                    "WHERE e.id IS NULL "
                    "AND t.created_at < now() - make_interval(hours => $1) "
                    "ORDER BY t.created_at",
                    min_age_hours,
                )
            else:
                rows = await conn.fetch(
                    "SELECT t.id, t.name, t.created_at "
                    "FROM node_type t "
                    "LEFT JOIN node n ON n.type_id = t.id "
                    "WHERE n.id IS NULL "
                    "AND t.created_at < now() - make_interval(hours => $1) "
                    "ORDER BY t.created_at",
                    min_age_hours,
                )
            return [(r["id"], r["name"], r["created_at"]) for r in rows]

    # ── Partial Curation Cleanup ──

    async def cleanup_partial_curation(
        self,
        agent_id: str,
        episode_id: int,
        target_schema: str | None = None,
    ) -> int:
        if self._pool is None or self._router is None:
            return 0

        schema_name = await self._resolve_schema(agent_id, target_schema)
        episode_str = str(episode_id)
        async with self._scoped_conn(schema_name, agent_id, target_schema) as conn, conn.transaction():
            r1 = await conn.execute(
                "DELETE FROM edge WHERE properties->>'_source_episode' = $1",
                episode_str,
            )
            r2 = await conn.execute(
                "DELETE FROM node WHERE properties->>'_source_episode' = $1",
                episode_str,
            )
        edges_deleted = int(r1.split()[-1]) if r1 else 0
        nodes_deleted = int(r2.split()[-1]) if r2 else 0
        return edges_deleted + nodes_deleted

    # ── Episodic Consolidation ──

    async def mark_episode_consolidated(self, agent_id: str, episode_id: int, target_schema: str | None = None) -> None:
        if self._pool is None or self._router is None:
            return

        if target_schema is not None:
            async with graph_scoped_connection(self._pool, target_schema, agent_id=agent_id) as conn:
                await conn.execute(
                    "UPDATE episode SET consolidated = true WHERE id = $1",
                    episode_id,
                )
        else:
            schema_name = await self._router.route_store(agent_id)
            async with schema_scoped_connection(self._pool, schema_name) as conn:
                await conn.execute(
                    "UPDATE episode SET consolidated = true WHERE id = $1",
                    episode_id,
                )

    async def link_personal_episode_to_session_predecessor(self, agent_id: str, episode_id: int) -> None:
        if self._pool is None or self._router is None:
            return

        schema_name = await self._router.route_store(agent_id)
        async with schema_scoped_connection(self._pool, schema_name) as conn:
            current = await conn.fetchrow(
                """
                SELECT id, session_id, session_sequence, created_at
                FROM episode
                WHERE id = $1 AND agent_id = $2
                """,
                episode_id,
                agent_id,
            )
            if current is None or current["session_id"] is None:
                return

            session_id = str(current["session_id"])
            lock_material = f"{schema_name}:{agent_id}:{session_id}"
            lock_key = int(hashlib.sha256(lock_material.encode()).hexdigest()[:16], 16) % (2**63 - 1)

            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock($1)", lock_key)

                previous = await conn.fetchrow(
                    """
                    SELECT id
                    FROM episode
                    WHERE agent_id = $1
                      AND session_id = $2
                      AND id <> $3
                      AND (
                        (session_sequence IS NOT NULL AND $4::int IS NOT NULL AND session_sequence < $4)
                        OR ($4::int IS NULL AND (created_at, id) < ($5, $3))
                      )
                    ORDER BY session_sequence DESC NULLS LAST, created_at DESC, id DESC
                    LIMIT 1
                    """,
                    agent_id,
                    session_id,
                    episode_id,
                    current["session_sequence"],
                    current["created_at"],
                )
                if previous is None:
                    return

                prev_id = int(previous["id"])
                prev_node_id = await conn.fetchval(
                    """
                    SELECT id FROM node
                    WHERE properties->>'_source_episode' = $1
                    ORDER BY created_at ASC, id ASC
                    LIMIT 1
                    """,
                    str(prev_id),
                )
                curr_node_id = await conn.fetchval(
                    """
                    SELECT id FROM node
                    WHERE properties->>'_source_episode' = $1
                    ORDER BY created_at ASC, id ASC
                    LIMIT 1
                    """,
                    str(episode_id),
                )
                if prev_node_id is None or curr_node_id is None:
                    return

                follows_type_id = await conn.fetchval("SELECT id FROM edge_type WHERE name = 'FOLLOWS'")
                if follows_type_id is None:
                    return

                await conn.execute(
                    """
                    INSERT INTO edge (source_id, target_id, type_id, weight, properties)
                    VALUES ($1, $2, $3, $4, $5::jsonb)
                    ON CONFLICT (source_id, target_id, type_id) DO NOTHING
                    """,
                    curr_node_id,
                    prev_node_id,
                    follows_type_id,
                    0.9,
                    json.dumps({"episode_follows": episode_id, "episode_precedes": prev_id}),
                )

    # ── Edge Reinforcement ──

    async def reinforce_edges(
        self, agent_id: str, edge_ids: list[int], delta: float = 0.05, ceiling: float = 1.5
    ) -> None:
        if not edge_ids:
            return
        if self._pool is None or self._router is None:
            return

        schema_name = await self._router.route_store(agent_id)
        async with schema_scoped_connection(self._pool, schema_name) as conn:
            # Logarithmic diminishing returns: increment shrinks as weight grows
            # At weight 1.0: +delta/1.0, at 1.2: +delta/2.0, at 1.4: +delta/3.0
            await conn.execute(
                "UPDATE edge SET "
                "weight = LEAST(weight + $2 / (1.0 + (weight - 1.0) * 5.0), $3), "
                "last_reinforced_at = now() "
                "WHERE id = ANY($1::int[])",
                edge_ids,
                delta,
                ceiling,
            )

    async def micro_decay_edges(
        self,
        agent_id: str,
        exclude_ids: list[int],
        factor: float = 0.998,
        floor: float = 0.1,
        recently_reinforced_hours: float = 1.0,
    ) -> int:
        if self._pool is None or self._router is None:
            return 0

        schema_name = await self._router.route_store(agent_id)
        async with schema_scoped_connection(self._pool, schema_name) as conn:
            result = await conn.execute(
                "UPDATE edge SET weight = GREATEST(weight * $1, $2) "
                "WHERE id != ALL($3::int[]) "
                "AND weight > $2 "
                "AND last_reinforced_at > now() - make_interval(hours => $4)",
                factor,
                floor,
                exclude_ids or [],
                recently_reinforced_hours,
            )
        count = int(result.split()[-1]) if result else 0
        return count

    async def decay_stale_edges(
        self,
        agent_id: str,
        older_than_hours: float = 48.0,
        decay_factor: float = 0.95,
        floor: float = 0.1,
        force: bool = False,
    ) -> int:
        if self._pool is None or self._router is None:
            return 0

        schema_name = await self._router.route_store(agent_id)
        async with schema_scoped_connection(self._pool, schema_name) as conn:
            result = await conn.execute(
                "UPDATE edge SET weight = GREATEST(weight * $1, $2) "
                "WHERE last_reinforced_at < now() - make_interval(hours => $3) "
                "AND weight > $2",
                decay_factor,
                floor,
                older_than_hours,
            )
        # asyncpg returns "UPDATE N" string
        count = int(result.split()[-1]) if result else 0
        return count

    async def list_all_edge_signatures(self, agent_id: str) -> list[str]:
        if self._pool is None or self._router is None:
            return []

        schema_name = await self._router.route_store(agent_id)
        async with schema_scoped_connection(self._pool, schema_name) as conn:
            rows = await conn.fetch("""SELECT src.name AS source, et.name AS rel, tgt.name AS target
                   FROM edge e
                   JOIN node src ON src.id = e.source_id
                   JOIN node tgt ON tgt.id = e.target_id
                   JOIN edge_type et ON et.id = e.type_id
                   ORDER BY src.name, et.name, tgt.name""")
        return [f"{row['source']}→{row['rel']}→{row['target']}" for row in rows]

    async def _recall_via_graph(
        self, query: str, agent_id: str, limit: int, query_embedding: list[float] | None = None
    ) -> list[RecallItem]:
        weights = HybridWeights(
            vector=self._settings.recall_weight_vector,
            text=self._settings.recall_weight_text,
            recency=self._settings.recall_weight_recency,
            activation=self._settings.recall_weight_activation,
            importance=self._settings.recall_weight_importance,
        )
        half_life = self._settings.recall_recency_half_life_hours

        # 1. Text search (existing) — returns nodes with ts_rank
        text_hits = await self._graph.search_by_text(query, limit=limit)

        # 2. Vector search (new) — returns nodes with cosine similarity
        vector_hits: list[dict] = []
        if query_embedding is not None:
            vector_hits = await self._graph.search_by_vector(query_embedding, limit=limit)

        # 3. Episode search — text (ILIKE, existing) + vector (new)
        episodes = await self._graph.list_episodes(agent_id=agent_id, limit=max(limit * 5, 20))
        vector_episodes: list[dict] = []
        if query_embedding is not None:
            vector_episodes = await self._graph.search_episodes_by_vector(
                query_embedding, agent_id=agent_id, limit=limit
            )

        # 4. Merge nodes into a single dict keyed by id (type resolved via JOIN)
        merged_nodes: dict[int, dict] = {}
        for hit in text_hits:
            nid = int(hit["id"])
            merged_nodes[nid] = {
                "hit": hit,
                "text_rank": float(hit.get("rank") or 0.0),
                "vector_sim": None,
            }
        for hit in vector_hits:
            nid = int(hit["id"])
            if nid in merged_nodes:
                merged_nodes[nid]["vector_sim"] = float(hit.get("similarity") or 0.0)
            else:
                merged_nodes[nid] = {
                    "hit": hit,
                    "text_rank": None,
                    "vector_sim": float(hit.get("similarity") or 0.0),
                }

        # 5. Score nodes
        node_results: list[RecallItem] = []
        for nid, info in merged_nodes.items():
            hit = info["hit"]
            created_at = hit.get("created_at")
            updated_at = hit.get("updated_at")
            recency_ts = max(created_at, updated_at) if (created_at and updated_at) else created_at
            recency = compute_recency_score(recency_ts, half_life) if recency_ts else 0.5

            # Compute activation from access_count and last_accessed_at if available
            access_count = int(hit.get("access_count") or 0)
            last_accessed = hit.get("last_accessed_at") or created_at
            activation = (
                compute_base_activation(
                    access_count,
                    last_accessed,
                    decay_rate=self._settings.activation_decay_rate,
                    access_exponent=self._settings.activation_access_exponent,
                )
                if last_accessed
                else None
            )
            node_importance = float(hit.get("importance") or 0.5)

            score = compute_hybrid_score(
                info["vector_sim"],
                info["text_rank"],
                recency,
                activation,
                node_importance,
                weights,
            )
            node_results.append(
                RecallItem(
                    item_id=nid,
                    name=str(hit["name"]),
                    content=str(hit.get("content") or ""),
                    item_type=str(hit.get("resolved_type_name", "Untyped")),
                    score=score,
                    activation_score=activation,
                    importance=node_importance,
                    source=str(hit["source"]) if hit.get("source") is not None else None,
                    source_kind="node",
                    graph_name=None,
                )
            )

        # 6. Merge episodes — text matches + vector matches
        query_lower = query.lower()
        merged_episodes: dict[int, dict] = {}
        for episode in episodes:
            if query_lower in episode.content.lower():
                merged_episodes[episode.id] = {
                    "episode": episode,
                    "text_rank": None,  # episodes don't have tsvector
                    "vector_sim": None,
                }
        for hit in vector_episodes:
            eid = int(hit["id"])
            if eid in merged_episodes:
                merged_episodes[eid]["vector_sim"] = float(hit.get("similarity") or 0.0)
            else:
                # Build a minimal episode-like object for scoring
                merged_episodes[eid] = {
                    "episode": hit,
                    "text_rank": None,
                    "vector_sim": float(hit.get("similarity") or 0.0),
                }

        # 7. Score episodes
        episode_results: list[RecallItem] = []
        for eid, info in merged_episodes.items():
            ep = info["episode"]
            created_at = ep.created_at if hasattr(ep, "created_at") else ep.get("created_at")
            recency = compute_recency_score(created_at, half_life) if created_at else 0.5

            # Episode activation
            ep_access = int(ep.access_count if hasattr(ep, "access_count") else ep.get("access_count", 0))
            ep_last_acc = (
                ep.last_accessed_at if hasattr(ep, "last_accessed_at") else ep.get("last_accessed_at")
            ) or created_at
            activation = (
                compute_base_activation(
                    ep_access,
                    ep_last_acc,
                    decay_rate=self._settings.activation_decay_rate,
                    access_exponent=self._settings.activation_access_exponent,
                )
                if ep_last_acc
                else None
            )
            ep_importance = float(ep.importance if hasattr(ep, "importance") else ep.get("importance", 0.5))

            score = compute_hybrid_score(
                info["vector_sim"],
                info["text_rank"],
                recency,
                activation,
                ep_importance,
                weights,
            )
            consolidated = ep.consolidated if hasattr(ep, "consolidated") else ep.get("consolidated", True)
            if consolidated:
                score *= 0.5
            else:
                score *= self._settings.recall_unconsolidated_episode_boost
            score = self._apply_stm_boost(score, created_at)
            content = ep.content if hasattr(ep, "content") else str(ep.get("content", ""))
            source_type = ep.source_type if hasattr(ep, "source_type") else str(ep.get("source_type", ""))
            episode_results.append(
                RecallItem(
                    item_id=eid,
                    name=f"Episode #{eid}",
                    content=content,
                    item_type="Episode",
                    score=score,
                    activation_score=activation,
                    importance=ep_importance,
                    source=source_type,
                    source_kind="episode",
                    graph_name=None,
                )
            )

        all_results = node_results + episode_results
        all_results.sort(key=lambda item: item.score, reverse=True)
        return all_results[:limit]

    async def _recall_in_schema(
        self,
        schema_name: str,
        query: str,
        agent_id: str,
        limit: int,
        query_embedding: list[float] | None = None,
        expand_neighbors: bool = True,
        episode_query_embedding: list[float] | None = None,
    ) -> list[RecallItem]:
        if self._pool is None:
            raise RuntimeError("Connection pool is required for schema-scoped recall.")

        weights = HybridWeights(
            vector=self._settings.recall_weight_vector,
            text=self._settings.recall_weight_text,
            recency=self._settings.recall_weight_recency,
            activation=self._settings.recall_weight_activation,
            importance=self._settings.recall_weight_importance,
        )
        half_life = self._settings.recall_recency_half_life_hours

        # Over-fetch episode candidates when neighbor expansion is on,
        # so the SQL returns episodes from multiple sessions rather than
        # only the most recent (which may all be from the same session).
        episode_sql_limit = max(limit * 3, limit + 10) if expand_neighbors else limit

        async with graph_scoped_connection(self._pool, schema_name, agent_id=agent_id) as conn:
            if query_embedding is not None:
                emb_str = str(query_embedding)
                ep_emb_str = str(episode_query_embedding) if episode_query_embedding is not None else emb_str
                node_rows = await conn.fetch(
                    """SELECT n.id, n.name, n.content, n.source, n.type_id,
                              COALESCE(nt.name, 'Untyped') AS resolved_type_name,
                              ts_rank(n.tsv, plainto_tsquery('english', $1)) AS text_rank,
                              CASE WHEN n.embedding IS NOT NULL
                                   THEN 1 - (n.embedding <=> $2::vector)
                                   ELSE NULL
                              END AS vector_sim,
                              n.access_count, n.last_accessed_at, n.importance,
                              n.created_at, n.updated_at,
                              NULL::float[] AS embedding_vec
                       FROM node n
                       LEFT JOIN node_type nt ON nt.id = n.type_id
                       WHERE n.forgotten = false
                         AND (n.tsv @@ plainto_tsquery('english', $1)
                          OR (n.embedding IS NOT NULL AND (n.embedding <=> $2::vector) < $3))
                       ORDER BY text_rank DESC NULLS LAST
                       LIMIT $4""",
                    query,
                    emb_str,
                    self._settings.recall_vector_distance_threshold,
                    limit,
                )
                escaped_query = _escape_ilike(query)
                episode_rows = await conn.fetch(
                    """SELECT id, content, source_type,
                              access_count, last_accessed_at, importance,
                              consolidated,
                              created_at, session_id, session_sequence,
                              CASE WHEN embedding IS NOT NULL
                                   THEN 1 - (embedding <=> $2::vector)
                                   ELSE NULL
                              END AS vector_sim,
                              NULL::float[] AS embedding_vec
                       FROM episode
                       WHERE content ILIKE '%' || $1 || '%' ESCAPE '\\'
                          OR (embedding IS NOT NULL AND (embedding <=> $2::vector) < $3)
                       ORDER BY created_at DESC
                       LIMIT $4""",
                    escaped_query,
                    ep_emb_str,
                    self._settings.recall_vector_distance_threshold,
                    episode_sql_limit,
                )
            else:
                # Text-only path — no regression from existing behavior
                node_rows = await conn.fetch(
                    """SELECT n.id, n.name, n.content, n.source, n.type_id,
                              COALESCE(nt.name, 'Untyped') AS resolved_type_name,
                              ts_rank(n.tsv, plainto_tsquery('english', $1)) AS text_rank,
                              NULL::double precision AS vector_sim,
                              n.access_count, n.last_accessed_at, n.importance,
                              n.created_at, n.updated_at
                       FROM node n
                       LEFT JOIN node_type nt ON nt.id = n.type_id
                       WHERE n.forgotten = false
                         AND n.tsv @@ plainto_tsquery('english', $1)
                       ORDER BY text_rank DESC
                       LIMIT $2""",
                    query,
                    limit,
                )
                escaped_query = _escape_ilike(query)
                episode_rows = await conn.fetch(
                    """SELECT id, content, source_type,
                              access_count, last_accessed_at, importance,
                              consolidated,
                              created_at, session_id, session_sequence,
                              NULL::double precision AS vector_sim
                       FROM episode
                       WHERE content ILIKE '%' || $1 || '%' ESCAPE '\\'
                       ORDER BY created_at DESC
                       LIMIT $2""",
                    escaped_query,
                    episode_sql_limit,
                )

            # Fetch supersession relationships for candidate nodes
            candidate_node_ids = [int(r["id"]) for r in node_rows]
            supersession_type_ids = await conn.fetch(
                "SELECT id FROM edge_type WHERE name IN ('SUPERSEDES', 'CORRECTS')"
            )
            s_type_ids = [r["id"] for r in supersession_type_ids]

            supersession_edges: dict[str, dict[int, list]] = {"superseded_by": {}, "supersedes": {}}

            if s_type_ids and candidate_node_ids:
                superseded_rows = await conn.fetch(
                    "SELECT target_id, source_id FROM edge "
                    "WHERE type_id = ANY($1::int[]) AND target_id = ANY($2::int[])",
                    s_type_ids,
                    candidate_node_ids,
                )
                superseding_rows = await conn.fetch(
                    "SELECT source_id, target_id FROM edge "
                    "WHERE type_id = ANY($1::int[]) AND source_id = ANY($2::int[])",
                    s_type_ids,
                    candidate_node_ids,
                )
                for r in superseded_rows:
                    supersession_edges["superseded_by"].setdefault(r["target_id"], []).append(r)
                for r in superseding_rows:
                    supersession_edges["supersedes"].setdefault(r["source_id"], []).append(r)

            # Prefetch temporal neighbors for personal episode expansion
            episode_row_dicts = [dict(r) for r in episode_rows]
            neighbors_by_nucleus: dict[int, list[dict]] = {}

            if expand_neighbors and self._settings.recall_expand_neighbors and schema_name.endswith("__personal"):
                # Only the top-`limit` episodes (by vector similarity) are nucleus
                # candidates.  Over-fetched episodes beyond `limit` can still be
                # discovered as session neighbors — this is the whole point of
                # over-fetching.  Replace episode_row_dicts with the nucleus set
                # so only they get scored as primary results later.
                episode_row_dicts = sorted(
                    episode_row_dicts,
                    key=lambda r: r.get("vector_sim") or 0.0,
                    reverse=True,
                )[:limit]
                seen_episode_ids = {int(r["id"]) for r in episode_row_dicts}
                for ep in episode_row_dicts:
                    if ep.get("session_id") is None:
                        continue
                    neighbors = await self._fetch_episode_neighbors(
                        conn=conn,
                        episode_id=int(ep["id"]),
                        session_id=str(ep["session_id"]),
                        created_at=ep["created_at"],
                        session_sequence=ep.get("session_sequence"),
                        window=self._settings.recall_neighbor_window,
                    )
                    unique_neighbors: list[dict] = []
                    for nb in neighbors:
                        nb_id = int(nb["id"])
                        if nb_id in seen_episode_ids:
                            continue
                        seen_episode_ids.add(nb_id)
                        nb["neighbor_of"] = int(ep["id"])
                        unique_neighbors.append(nb)
                    if unique_neighbors:
                        neighbors_by_nucleus[int(ep["id"])] = unique_neighbors

        # Build intermediate dicts (includes embedding for MMR, stripped before return)
        result_dicts: list[dict] = []
        for row in node_rows:
            text_rank = float(row["text_rank"]) if row["text_rank"] is not None else None
            vector_sim = float(row["vector_sim"]) if row["vector_sim"] is not None else None
            created_at = row["created_at"]
            updated_at = row.get("updated_at")
            recency_ts = max(created_at, updated_at) if updated_at else created_at
            recency = compute_recency_score(recency_ts, half_life) if created_at else 0.5

            access_count = int(row["access_count"] or 0)
            last_accessed = row["last_accessed_at"] or created_at
            activation = (
                compute_base_activation(
                    access_count,
                    last_accessed,
                    decay_rate=self._settings.activation_decay_rate,
                    access_exponent=self._settings.activation_access_exponent,
                )
                if last_accessed
                else None
            )
            node_importance = float(row["importance"]) if row["importance"] is not None else 0.5

            score = compute_hybrid_score(
                vector_sim,
                text_rank,
                recency,
                activation,
                node_importance,
                weights,
            )

            # Apply supersession adjustment (penalize outdated, boost correcting)
            node_id = int(row["id"])
            adjustment = compute_supersession_adjustment(
                node_id,
                supersession_edges,
                superseded_penalty=self._settings.recall_superseded_penalty,
                superseding_boost=self._settings.recall_superseding_boost,
            )
            score *= adjustment

            embedding_vec = row.get("embedding_vec")
            result_dicts.append(
                {
                    "score": score,
                    "embedding": list(embedding_vec) if embedding_vec is not None else None,
                    "item_id": int(row["id"]),
                    "name": str(row["name"]),
                    "content": str(row["content"] or ""),
                    "item_type": str(row["resolved_type_name"]),
                    "activation_score": activation,
                    "importance": node_importance,
                    "source": str(row["source"]) if row["source"] is not None else None,
                    "source_kind": "node",
                    "graph_name": schema_name,
                }
            )

        def _episode_result_dict(
            row: dict, score: float, activation: float | None, importance: float, neighbor_of: int | None = None
        ) -> dict:
            embedding_vec = row.get("embedding_vec")
            return {
                "score": score,
                "embedding": list(embedding_vec) if embedding_vec is not None else None,
                "item_id": int(row["id"]),
                "name": f"Episode #{int(row['id'])}",
                "content": str(row["content"]),
                "item_type": "Episode",
                "activation_score": activation,
                "importance": importance,
                "source": str(row["source_type"]) if row.get("source_type") is not None else None,
                "source_kind": "episode",
                "graph_name": schema_name,
                "created_at": row.get("created_at"),
                "session_id": str(row["session_id"]) if row.get("session_id") is not None else None,
                "session_sequence": int(row["session_sequence"]) if row.get("session_sequence") is not None else None,
                "neighbor_of": neighbor_of,
            }

        for row in episode_row_dicts:
            vector_sim = float(row["vector_sim"]) if row["vector_sim"] is not None else None
            created_at = row["created_at"]
            recency = compute_recency_score(created_at, half_life) if created_at else 0.5

            ep_access = int(row["access_count"] or 0)
            ep_last_acc = row["last_accessed_at"] or created_at
            activation = (
                compute_base_activation(
                    ep_access,
                    ep_last_acc,
                    decay_rate=self._settings.activation_decay_rate,
                    access_exponent=self._settings.activation_access_exponent,
                )
                if ep_last_acc
                else None
            )
            ep_importance = float(row["importance"]) if row["importance"] is not None else 0.5

            score = compute_hybrid_score(
                vector_sim,
                None,
                recency,
                activation,
                ep_importance,
                weights,
            )

            # Consolidated episodes get half the score — graph nodes take priority
            if row.get("consolidated"):
                score *= 0.5
            else:
                # Unconsolidated episodes get a boost to compensate for lack of graph traversal bonus
                score *= self._settings.recall_unconsolidated_episode_boost

            score = self._apply_stm_boost(score, created_at)

            primary_id = int(row["id"])
            result_dicts.append(_episode_result_dict(row, score, activation, ep_importance))

            # Append neighbor episodes with discounted score
            for nb in neighbors_by_nucleus.get(primary_id, []):
                nb_created = nb.get("created_at")
                nb_access = int(nb.get("access_count") or 0)
                nb_last_acc = nb.get("last_accessed_at") or nb_created
                nb_activation = (
                    compute_base_activation(
                        nb_access,
                        nb_last_acc,
                        decay_rate=self._settings.activation_decay_rate,
                        access_exponent=self._settings.activation_access_exponent,
                    )
                    if nb_last_acc
                    else None
                )
                nb_importance = float(nb["importance"]) if nb.get("importance") is not None else 0.5
                nb_score = score * self._settings.recall_neighbor_score_factor
                result_dicts.append(
                    _episode_result_dict(nb, nb_score, nb_activation, nb_importance, neighbor_of=primary_id)
                )

        # Apply MMR diversity reranking if enabled
        if self._settings.recall_mmr_enabled:
            result_dicts = mmr_rerank(
                result_dicts,
                lambda_param=self._settings.recall_mmr_lambda,
            )
        else:
            result_dicts.sort(key=lambda d: d["score"], reverse=True)

        # Convert to RecallItem objects (strip embeddings)
        results: list[RecallItem] = []
        for d in result_dicts:
            results.append(
                RecallItem(
                    item_id=d["item_id"],
                    name=d["name"],
                    content=d["content"],
                    item_type=d["item_type"],
                    score=d["score"],
                    activation_score=d["activation_score"],
                    importance=d["importance"],
                    source=d["source"],
                    source_kind=d["source_kind"],
                    graph_name=d["graph_name"],
                    created_at=d.get("created_at"),
                    session_id=d.get("session_id"),
                    session_sequence=d.get("session_sequence"),
                    neighbor_of=d.get("neighbor_of"),
                )
            )
        return results

    async def _fetch_episode_neighbors(
        self,
        conn,
        episode_id: int,
        session_id: str,
        created_at,
        session_sequence: int | None,
        window: int = 3,
    ) -> list[dict]:
        """Fetch temporal neighbor episodes within the same session."""
        if window <= 0:
            return []
        before_limit = max(1, window // 3)
        after_limit = max(1, window - before_limit)

        before = await conn.fetch(
            f"""
            SELECT id, content, source_type,
                   access_count, last_accessed_at, importance, consolidated,
                   created_at, session_id, session_sequence,
                   NULL::double precision AS vector_sim,
                   NULL::float[] AS embedding_vec
            FROM episode
            WHERE session_id = $1
              AND id <> $2
              AND (
                (session_sequence IS NOT NULL AND $4::int IS NOT NULL AND session_sequence < $4)
                OR ($4::int IS NULL AND (created_at, id) < ($3, $2))
              )
            ORDER BY session_sequence DESC NULLS LAST, created_at DESC, id DESC
            LIMIT {before_limit}
            """,
            session_id,
            episode_id,
            created_at,
            session_sequence,
        )
        after = await conn.fetch(
            f"""
            SELECT id, content, source_type,
                   access_count, last_accessed_at, importance, consolidated,
                   created_at, session_id, session_sequence,
                   NULL::double precision AS vector_sim,
                   NULL::float[] AS embedding_vec
            FROM episode
            WHERE session_id = $1
              AND id <> $2
              AND (
                (session_sequence IS NOT NULL AND $4::int IS NOT NULL AND session_sequence > $4)
                OR ($4::int IS NULL AND (created_at, id) > ($3, $2))
              )
            ORDER BY session_sequence ASC NULLS LAST, created_at ASC, id ASC
            LIMIT {after_limit}
            """,
            session_id,
            episode_id,
            created_at,
            session_sequence,
        )
        rows: list[dict] = []
        rows.extend(dict(r) | {"neighbor_position": "before"} for r in before)
        rows.extend(dict(r) | {"neighbor_position": "after"} for r in after)
        return rows

    async def _get_types(self, table_name: str, count_table: str, agent_id: str | None = None) -> list[TypeInfo]:
        if self._pool is None or self._router is None or agent_id is None:
            return await self._get_types_from_public(table_name=table_name, count_table=count_table)

        schemas = await self._router.route_discover(agent_id)
        aggregated: dict[str, TypeInfo] = {}

        for schema_name in schemas:
            rows = await self._fetch_types_in_schema(schema_name, table_name, agent_id)
            counts = await self._fetch_type_counts_in_schema(schema_name, count_table, agent_id)
            for row in rows:
                type_name = str(row["name"])
                current = aggregated.get(type_name)
                description = str(row["description"]) if row["description"] is not None else None
                count = counts.get(int(row["id"]), 0)
                if current is None:
                    aggregated[type_name] = TypeInfo(
                        id=0,
                        name=type_name,
                        description=description,
                        count=count,
                    )
                    continue

                current.count += count
                if current.description is None and description is not None:
                    current.description = description

        return [
            TypeInfo(
                id=index,
                name=item.name,
                description=item.description,
                count=item.count,
            )
            for index, item in enumerate(sorted(aggregated.values(), key=lambda item: item.name), start=1)
        ]

    async def _get_types_from_public(self, table_name: str, count_table: str) -> list[TypeInfo]:
        if self._pg is None:
            stats = await self._graph.get_ontology_stats()
            key = "node_types" if table_name == "node_type" else "edge_types"
            return [
                TypeInfo(
                    id=index,
                    name=str(item["type_name"]),
                    count=int(item["count"]),
                )
                for index, item in enumerate(stats[key], start=1)
            ]

        rows = await self._pg.fetch(f"SELECT id, name, description FROM {table_name} ORDER BY name")
        counts = await self._pg.fetch(f"SELECT type_id AS id, count(*) AS count FROM {count_table} GROUP BY type_id")
        count_map = {int(row["id"]): int(row["count"]) for row in counts}

        return [
            TypeInfo(
                id=int(row["id"]),
                name=str(row["name"]),
                description=str(row["description"]) if row["description"] is not None else None,
                count=count_map.get(int(row["id"]), 0),
            )
            for row in rows
        ]

    async def _fetch_types_in_schema(self, schema_name: str, table_name: str, agent_id: str) -> list[asyncpg.Record]:
        if self._pool is None:
            raise RuntimeError("Connection pool is required for schema-scoped type lookups.")

        async with graph_scoped_connection(self._pool, schema_name, agent_id=agent_id) as conn:
            return await conn.fetch(f"SELECT id, name, description FROM {table_name} ORDER BY name")

    async def _fetch_type_counts_in_schema(self, schema_name: str, count_table: str, agent_id: str) -> dict[int, int]:
        if self._pool is None:
            raise RuntimeError("Connection pool is required for schema-scoped type counts.")

        async with graph_scoped_connection(self._pool, schema_name, agent_id=agent_id) as conn:
            rows = await conn.fetch(f"SELECT type_id AS id, count(*) AS count FROM {count_table} GROUP BY type_id")
        return {int(row["id"]): int(row["count"]) for row in rows}

    async def _get_stats_in_schema(self, schema_name: str, agent_id: str) -> GraphStats:
        if self._pool is None:
            raise RuntimeError("Connection pool is required for schema-scoped stats.")

        async with graph_scoped_connection(self._pool, schema_name, agent_id=agent_id) as conn:
            row = await conn.fetchrow("""SELECT
                       (SELECT count(*) FROM node) AS total_nodes,
                       (SELECT count(*) FROM edge) AS total_edges,
                       (SELECT count(*) FROM episode) AS total_episodes,
                       (SELECT count(*) FROM node WHERE forgotten = true) AS forgotten_nodes,
                       (SELECT count(*) FROM episode WHERE consolidated = true) AS consolidated_episodes,
                       (SELECT coalesce(avg(access_count), 0) FROM node WHERE forgotten = false) AS avg_access_count""")
        # NOTE: avg_access_count is a rough proxy for avg_activation.
        # Computing real ACT-R activation in SQL is impractical; the mock
        # implementation uses compute_base_activation() for accuracy.
        if row is None:
            raise RuntimeError(f"Failed to fetch graph stats for schema '{schema_name}'.")

        return GraphStats(
            total_nodes=int(row["total_nodes"]),
            total_edges=int(row["total_edges"]),
            total_episodes=int(row["total_episodes"]),
            forgotten_nodes=int(row["forgotten_nodes"]),
            consolidated_episodes=int(row["consolidated_episodes"]),
            avg_activation=round(float(row["avg_access_count"]), 4),
        )


def _deduplicate_recall_items(items: Iterable[RecallItem]) -> list[RecallItem]:
    deduplicated: list[RecallItem] = []
    seen: set[tuple[str, int, str | None]] = set()

    for item in items:
        key = (item.source_kind, item.item_id, item.graph_name)
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(item)

    return deduplicated


def _sort_session_clusters_chronologically(items: list[RecallItem]) -> list[RecallItem]:
    """Reorder results so episodes from the same session appear in chronological order."""
    result: list[RecallItem] = []
    consumed: set[tuple[str, int, str | None]] = set()

    def key_for(item: RecallItem) -> tuple[str, int, str | None]:
        return (item.source_kind, item.item_id, item.graph_name)

    for item in items:
        key = key_for(item)
        if key in consumed:
            continue
        if item.source_kind != "episode" or not item.session_id:
            consumed.add(key)
            result.append(item)
            continue

        cluster = [
            x
            for x in items
            if x.source_kind == "episode"
            and x.graph_name == item.graph_name
            and x.session_id == item.session_id
            and key_for(x) not in consumed
        ]
        cluster.sort(
            key=lambda x: (x.session_sequence is None, x.session_sequence or 0, x.created_at or datetime.min, x.item_id)
        )
        for c in cluster:
            consumed.add(key_for(c))
            result.append(c)

    return result
