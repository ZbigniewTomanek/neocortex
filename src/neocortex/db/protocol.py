from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

from neocortex.models import Edge, EdgeType, Episode, Node, NodeType
from neocortex.schemas.memory import GraphStats, RecallItem, TypeDetail, TypeInfo


class MemoryRepository(Protocol):
    """Abstract interface for NeoCortex storage backends."""

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
        """Store a raw episode and return the episode ID."""

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
        """Store an episode in an explicit target schema (for shared graph writes)."""

    async def check_episode_hashes(
        self,
        agent_id: str,
        hashes: list[str],
        target_schema: str | None = None,
    ) -> dict[str, int]:
        """Check which content hashes already exist for this agent.

        Returns a dict of {hash: episode_id} for hashes that exist.
        """
        ...

    async def recall(
        self,
        query: str,
        agent_id: str,
        limit: int = 10,
        query_embedding: list[float] | None = None,
        expand_neighbors: bool = True,
        episode_query_embedding: list[float] | None = None,
    ) -> list[RecallItem]:
        """Return ranked recall results for an agent."""

    async def get_node_types(self, agent_id: str | None = None, target_schema: str | None = None) -> list[TypeInfo]:
        """Return available node types."""

    async def get_edge_types(self, agent_id: str | None = None, target_schema: str | None = None) -> list[TypeInfo]:
        """Return available edge types."""

    async def get_stats(self, agent_id: str | None = None) -> GraphStats:
        """Return graph summary statistics."""

    async def get_stats_for_schema(self, agent_id: str, schema_name: str) -> GraphStats:
        """Return stats for a single schema."""

    async def get_type_detail(self, agent_id: str, type_name: str, graph_name: str, kind: str) -> TypeDetail | None:
        """Return detailed info for a single type: description, connected types, sample names."""

    async def update_episode_embedding(
        self, episode_id: int, embedding: list[float], agent_id: str, target_schema: str | None = None
    ) -> None:
        """Attach a vector embedding to an existing episode."""

    async def list_graphs(self, agent_id: str) -> list[str]:
        """Return graph schemas accessible to the agent."""

    # ── Type Management ──

    async def get_or_create_node_type(
        self, agent_id: str, name: str, description: str | None = None, target_schema: str | None = None
    ) -> NodeType | None:
        """Return existing node type by name or create a new one. Returns None if name is invalid."""

    async def get_or_create_edge_type(
        self, agent_id: str, name: str, description: str | None = None, target_schema: str | None = None
    ) -> EdgeType | None:
        """Return existing edge type by name or create a new one. Returns None if name is invalid."""

    # ── Episode Read ──

    async def get_episode(self, agent_id: str, episode_id: int, target_schema: str | None = None) -> Episode | None:
        """Fetch a single episode by ID within the agent's schema or a target schema."""

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
        """Upsert by (name, type_id) within the agent's schema.

        If a node with the same name AND type_id exists, merge properties and update.
        Importance uses max semantics — it only goes up.
        Name alone is NOT the uniqueness key — the same name under different types
        creates separate nodes (e.g. 'Serotonin' as Neurotransmitter vs Drug).
        """

    async def find_nodes_by_name(self, agent_id: str, name: str, target_schema: str | None = None) -> list[Node]:
        """Return all nodes matching ``name`` (case-insensitive) across all types."""

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
        """Upsert by (source_id, target_id, type_id) within the agent's schema.

        If an edge with the same triple exists, merge properties and update weight.
        """

    async def delete_edge(
        self,
        agent_id: str,
        edge_id: int,
        target_schema: str | None = None,
    ) -> bool:
        """Hard-delete an edge by ID. Returns True if deleted."""

    # ── Fuzzy Name Matching & Aliases ──

    async def find_nodes_fuzzy(
        self,
        agent_id: str,
        name: str,
        threshold: float = 0.3,
        limit: int = 5,
        target_schema: str | None = None,
        expected_type: str | None = None,
    ) -> list[tuple[Node, float]]:
        """Find nodes by trigram similarity to name.
        Returns (node, similarity_score) pairs sorted by score descending.
        Also checks the node_alias table for alias matches.
        """
        ...

    async def register_alias(
        self,
        agent_id: str,
        node_id: int,
        alias: str,
        source: str = "extraction",
        target_schema: str | None = None,
    ) -> None:
        """Register an alias for an existing node.
        Silently ignores if alias already exists for same node.
        """
        ...

    async def resolve_alias(
        self,
        agent_id: str,
        alias: str,
        target_schema: str | None = None,
    ) -> list[Node]:
        """Resolve an alias to its canonical node(s).
        Returns all nodes associated with this alias (usually 1).
        Caller should apply type filtering if multiple matches exist.
        """
        ...

    # ── Node Search ──

    async def search_nodes(
        self,
        agent_id: str,
        query: str,
        limit: int = 5,
        query_embedding: list[float] | None = None,
        target_schema: str | None = None,
        expected_type: str | None = None,
    ) -> list[tuple[Node, float]]:
        """Search nodes by text and/or vector similarity.

        Combines text search on node names/content with vector similarity
        on node embeddings. Returns top-N matching (node, relevance_score) tuples.
        """

    # ── Graph Traversal ──

    async def get_node_neighborhood(
        self, agent_id: str, node_id: int, depth: int = 2, target_schema: str | None = None
    ) -> list[dict]:
        """BFS traversal up to ``depth`` hops.

        Returns list of ``{node: Node, edges: list[Edge], distance: int}``.
        """

    # ── Node Browsing ──

    async def list_nodes_page(
        self,
        agent_id: str,
        target_schema: str | None = None,
        type_id: int | None = None,
        limit: int = 20,
    ) -> list[Node]:
        """Return a page of nodes, optionally filtered by type."""

    # ── Bulk Queries (for extraction pipeline) ──

    async def list_all_node_names(
        self, agent_id: str, target_schema: str | None = None, limit: int | None = None
    ) -> list[str]:
        """Return node names in the agent's graph, optionally limited."""

    async def list_all_edge_signatures(self, agent_id: str) -> list[str]:
        """Return all edge signatures (source→type→target) in the agent's graph."""

    # ── Access Tracking ──

    async def record_node_access(self, agent_id: str, node_ids: list[int], limit: int | None = None) -> None:
        """Increment access_count and update last_accessed_at for recalled nodes."""

    async def record_episode_access(self, agent_id: str, episode_ids: list[int], limit: int | None = None) -> None:
        """Increment access_count and update last_accessed_at for recalled episodes."""

    # ── Soft-Forget ──

    async def mark_forgotten(self, agent_id: str, node_ids: list[int], target_schema: str | None = None) -> int:
        """Soft-delete nodes by setting forgotten=true. Returns count."""

    async def resurrect_node(self, agent_id: str, node_id: int) -> None:
        """Clear forgotten flag and bump access_count for a re-referenced node."""

    async def identify_forgettable_nodes(
        self, agent_id: str, activation_threshold: float, importance_floor: float
    ) -> list[int]:
        """Return IDs of nodes eligible for soft-forget.

        Uses a practical proxy (access_count == 0 AND stale > 7 days) rather
        than computing ACT-R activation in SQL. ``activation_threshold`` is
        accepted for future use but currently unused by both implementations.
        ``importance_floor`` is applied: nodes with importance >= floor are
        never forgettable.
        """

    # ── Partial Curation Cleanup ──

    async def cleanup_partial_curation(
        self,
        agent_id: str,
        episode_id: int,
        target_schema: str | None = None,
    ) -> int:
        """Delete nodes and edges tagged with _source_episode = episode_id.

        Called before retrying a failed curation to ensure idempotency.
        Returns total items deleted.
        """

    # ── Episodic Consolidation ──

    async def mark_episode_consolidated(
        self,
        agent_id: str,
        episode_id: int,
        target_schema: str | None = None,
    ) -> None:
        """Mark an episode as consolidated in the schema where the episode row lives."""

    async def link_personal_episode_to_session_predecessor(
        self,
        agent_id: str,
        episode_id: int,
    ) -> None:
        """Create a personal-graph FOLLOWS edge from this episode to its predecessor.

        Always operates on the agent's personal schema. No-op when the episode has
        no session_id, no predecessor exists, no extracted nodes exist for either
        episode, or the FOLLOWS type is missing.
        """
        ...

    # ── Edge Reinforcement ──

    async def reinforce_edges(
        self, agent_id: str, edge_ids: list[int], delta: float = 0.05, ceiling: float = 1.5
    ) -> None:
        """Increment edge weights for traversed edges using diminishing returns, capped at ceiling."""

    async def micro_decay_edges(
        self,
        agent_id: str,
        exclude_ids: list[int],
        factor: float = 0.998,
        floor: float = 0.1,
        recently_reinforced_hours: float = 1.0,
    ) -> int:
        """Apply small multiplicative decay to recently-active edges (excluding given IDs).

        Targets edges reinforced within ``recently_reinforced_hours`` that are NOT in
        ``exclude_ids``. This prevents weight stagnation without touching the entire table.
        Called probabilistically (~25% of recalls). Returns count of decayed edges.
        """

    async def decay_stale_edges(
        self,
        agent_id: str,
        older_than_hours: float = 48.0,
        decay_factor: float = 0.95,
        floor: float = 0.1,
        force: bool = False,
    ) -> int:
        """Decay weights of edges not recently reinforced. Returns count of decayed edges.

        Uses last_reinforced_at (not created_at) to target edges that haven't
        been traversed recently. The force parameter bypasses probabilistic
        gating for deterministic testing.
        """

    # ── Type Introspection ──

    async def get_type_examples(
        self,
        agent_id: str,
        target_schema: str | None = None,
        limit_per_type: int = 5,
        max_types: int = 20,
    ) -> dict[str, list[str]]:
        """Fetch sample node names grouped by type for context injection.

        Returns {type_name: [node_name, ...]} for types that have active nodes.
        """

    async def cleanup_empty_types(
        self,
        agent_id: str,
        max_age_minutes: int = 5,
        target_schema: str | None = None,
    ) -> None:
        """Delete node types with zero nodes that were created recently.

        Only deletes types created within ``max_age_minutes`` to avoid
        removing types created by concurrent extractions.
        """

    # ── Ontology Exploration ──

    async def find_similar_types(
        self,
        agent_id: str,
        query: str,
        kind: Literal["node", "edge"] = "node",
        limit: int = 5,
        target_schema: str | None = None,
    ) -> list[tuple[TypeInfo, int, list[str]]]:
        """Find types with names similar to a query string.

        Returns list of (TypeInfo, usage_count, example_entity_names) tuples,
        sorted by similarity score descending.
        - usage_count: number of nodes/edges using this type
        - example_entity_names: up to 3 entity names of this type
        """
        ...

    async def get_ontology_summary(
        self,
        agent_id: str,
        target_schema: str | None = None,
    ) -> dict:
        """Return full ontology snapshot with usage counts.

        Returns:
            {
                "node_types": [{"name": str, "description": str, "usage_count": int}],
                "edge_types": [{"name": str, "description": str, "usage_count": int}],
                "total_nodes": int,
                "total_edges": int,
            }
        Sorted by usage_count descending within each list.
        """
        ...

    # ── Type Consolidation ──

    async def reassign_node_type(
        self,
        agent_id: str,
        source_type_id: int,
        target_type_id: int,
        target_schema: str | None = None,
    ) -> int:
        """Reassign all nodes from source type to target type. Returns count of nodes moved."""
        ...

    async def delete_type(
        self,
        agent_id: str,
        type_id: int,
        kind: Literal["node", "edge"],
        target_schema: str | None = None,
    ) -> None:
        """Delete a node or edge type by ID. Fails if type still has nodes/edges."""
        ...

    async def get_unused_types(
        self,
        agent_id: str,
        kind: Literal["node", "edge"],
        min_age_hours: float = 24.0,
        target_schema: str | None = None,
    ) -> list[tuple[int, str, datetime]]:
        """Return types with 0 usage that were created more than min_age_hours ago.

        Returns list of (type_id, type_name, created_at) tuples.
        """
        ...
