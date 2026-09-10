from datetime import UTC, datetime, timedelta
from typing import Literal, TypedDict

from loguru import logger

from neocortex.db.adapter import _types_are_merge_safe
from neocortex.models import Edge, EdgeType, Episode, Node, NodeType
from neocortex.normalization import canonicalize_name, names_are_similar, normalize_edge_type, normalize_node_type
from neocortex.schemas.memory import GraphStats, RecallItem, TypeDetail, TypeInfo
from neocortex.scoring import (
    HybridWeights,
    compute_base_activation,
    compute_hybrid_score,
    compute_recency_score,
)


class EpisodeRecord(TypedDict, total=False):
    id: int
    agent_id: str
    content: str
    context: str | None
    source_type: str
    metadata: dict
    embedding: list[float] | None
    created_at: datetime
    access_count: int
    last_accessed_at: datetime
    importance: float
    consolidated: bool
    content_hash: str | None
    session_id: str | None
    session_sequence: int | None


class InMemoryRepository:
    """Mock repository for testing and local MCP scaffolding."""

    def __init__(self) -> None:
        self._episodes: list[EpisodeRecord] = []
        self._schema_episodes: dict[str, list[EpisodeRecord]] = {}
        self._next_id = 1
        self._node_types: dict[str, NodeType] = {}  # keyed by name
        self._edge_types: dict[str, EdgeType] = {}  # keyed by name
        self._nodes: dict[int, Node] = {}  # keyed by id
        self._edges: dict[int, Edge] = {}  # keyed by id
        self._next_node_id = 1
        self._next_edge_id = 1
        self._next_type_id = 1
        self._aliases: dict[str, list[int]] = {}  # lower(alias) -> [node_id, ...]

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
        episode_id = self._next_id
        self._next_id += 1
        now = datetime.now(UTC)
        episode_metadata = metadata or {}
        if context:
            episode_metadata["context"] = context
        # Compute session_sequence
        session_sequence = None
        if session_id is not None:
            session_sequence = (
                sum(1 for ep in self._episodes if ep["agent_id"] == agent_id and ep.get("session_id") == session_id) + 1
            )
        self._episodes.append(
            {
                "id": episode_id,
                "agent_id": agent_id,
                "content": content,
                "context": context,
                "source_type": source_type,
                "metadata": episode_metadata,
                "created_at": now,
                "access_count": 0,
                "last_accessed_at": now,
                "importance": importance,
                "consolidated": False,
                "content_hash": content_hash,
                "session_id": session_id,
                "session_sequence": session_sequence,
            }
        )
        return episode_id

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
        episode_id = self._next_id
        self._next_id += 1
        now = datetime.now(UTC)
        episode_metadata = metadata or {}
        if context:
            episode_metadata["context"] = context
        # Compute session_sequence from schema bucket
        session_sequence = None
        schema_eps = self._schema_episodes.setdefault(target_schema, [])
        if session_id is not None:
            session_sequence = (
                sum(1 for ep in schema_eps if ep["agent_id"] == agent_id and ep.get("session_id") == session_id) + 1
            )
        record: EpisodeRecord = {
            "id": episode_id,
            "agent_id": agent_id,
            "content": content,
            "context": context,
            "source_type": source_type,
            "metadata": episode_metadata,
            "created_at": now,
            "access_count": 0,
            "last_accessed_at": now,
            "importance": importance,
            "consolidated": False,
            "content_hash": content_hash,
            "session_id": session_id,
            "session_sequence": session_sequence,
        }
        self._episodes.append(record)
        schema_eps.append(record)
        return episode_id

    async def check_episode_hashes(
        self,
        agent_id: str,
        hashes: list[str],
        target_schema: str | None = None,
    ) -> dict[str, int]:
        if not hashes:
            return {}
        hash_set = set(hashes)
        result: dict[str, int] = {}
        episodes = self._schema_episodes.get(target_schema, []) if target_schema is not None else self._episodes
        for ep in episodes:
            h = ep.get("content_hash")
            if h is not None and ep["agent_id"] == agent_id and h in hash_set:
                result[h] = ep["id"]
        return result

    async def recall(
        self,
        query: str,
        agent_id: str,
        limit: int = 10,
        query_embedding: list[float] | None = None,
        expand_neighbors: bool = True,
        episode_query_embedding: list[float] | None = None,
    ) -> list[RecallItem]:
        query_lower = query.lower()
        # Must stay in sync with MCPSettings defaults
        weights = HybridWeights(vector=0.3, text=0.2, recency=0.15, activation=0.20, importance=0.15)
        half_life = 168.0  # 7 days
        matches: list[RecallItem] = []

        # Match episodes
        for episode in self._episodes:
            if episode["agent_id"] != agent_id:
                continue
            content = str(episode["content"])
            if query_lower not in content.lower():
                continue

            created_at = episode.get("created_at", datetime.now(UTC))
            recency = compute_recency_score(created_at, half_life)

            access_count = episode.get("access_count", 0)
            last_accessed_at = episode.get("last_accessed_at", created_at)
            activation = compute_base_activation(access_count, last_accessed_at)

            importance_val = episode.get("importance", 0.5)
            score = compute_hybrid_score(
                vector_sim=None,
                text_rank=None,
                recency=recency,
                activation=activation,
                importance=importance_val,
                weights=weights,
            )

            # Consolidated episodes get half the score — graph nodes take priority
            if episode.get("consolidated", False):
                score *= 0.5
            else:
                # Unconsolidated episodes get a boost to compensate for lack of graph traversal bonus
                score *= 1.3  # matches MCPSettings.recall_unconsolidated_episode_boost default

            matches.append(
                RecallItem(
                    item_id=int(episode["id"]),
                    name=f"Episode #{episode['id']}",
                    content=content,
                    item_type="Episode",
                    score=score,
                    activation_score=activation,
                    importance=importance_val,
                    source=str(episode["source_type"]),
                    source_kind="episode",
                    graph_name=None,
                )
            )

        # Match nodes (exclude forgotten)
        for node in self._nodes.values():
            if node.forgotten:
                continue
            name_match = query_lower in node.name.lower()
            content_match = node.content and query_lower in node.content.lower()
            if not (name_match or content_match):
                continue

            recency_ts = max(node.created_at, node.updated_at) if node.updated_at else node.created_at
            recency = compute_recency_score(recency_ts, half_life)
            last_acc = node.last_accessed_at or node.created_at
            activation = compute_base_activation(node.access_count, last_acc)
            score = compute_hybrid_score(
                vector_sim=None,
                text_rank=None,
                recency=recency,
                activation=activation,
                importance=node.importance,
                weights=weights,
            )

            matches.append(
                RecallItem(
                    item_id=node.id,
                    name=node.name,
                    content=node.content or "",
                    item_type="Node",
                    score=score,
                    activation_score=activation,
                    importance=node.importance,
                    source=node.source,
                    source_kind="node",
                    graph_name=None,
                )
            )

        matches.sort(key=lambda item: item.score, reverse=True)
        return matches[:limit]

    async def get_node_types(self, agent_id: str | None = None, target_schema: str | None = None) -> list[TypeInfo]:
        del agent_id, target_schema
        return [
            TypeInfo(
                id=nt.id,
                name=nt.name,
                description=nt.description,
                count=sum(1 for n in self._nodes.values() if n.type_id == nt.id),
            )
            for nt in sorted(self._node_types.values(), key=lambda t: t.name)
        ]

    async def get_edge_types(self, agent_id: str | None = None, target_schema: str | None = None) -> list[TypeInfo]:
        del agent_id, target_schema
        return [
            TypeInfo(
                id=et.id,
                name=et.name,
                description=et.description,
                count=sum(1 for e in self._edges.values() if e.type_id == et.id),
            )
            for et in sorted(self._edge_types.values(), key=lambda t: t.name)
        ]

    async def get_stats(self, agent_id: str | None = None) -> GraphStats:
        count = sum(1 for e in self._episodes if agent_id is None or e["agent_id"] == agent_id)
        forgotten_nodes = sum(1 for n in self._nodes.values() if n.forgotten)
        consolidated_episodes = sum(
            1
            for e in self._episodes
            if (agent_id is None or e["agent_id"] == agent_id) and e.get("consolidated", False)
        )
        active_nodes = [n for n in self._nodes.values() if not n.forgotten]
        if active_nodes:
            avg_activation = sum(
                compute_base_activation(n.access_count, n.last_accessed_at or n.created_at) for n in active_nodes
            ) / len(active_nodes)
        else:
            avg_activation = 0.0
        return GraphStats(
            total_nodes=len(self._nodes),
            total_edges=len(self._edges),
            total_episodes=count,
            forgotten_nodes=forgotten_nodes,
            consolidated_episodes=consolidated_episodes,
            avg_activation=round(avg_activation, 4),
        )

    async def update_episode_embedding(
        self, episode_id: int, embedding: list[float], agent_id: str, target_schema: str | None = None
    ) -> None:
        # When target_schema is set, search the schema-bucketed episodes first
        if target_schema and target_schema in self._schema_episodes:
            for episode in self._schema_episodes[target_schema]:
                if episode["id"] == episode_id:
                    episode["embedding"] = embedding
                    return
        for episode in self._episodes:
            if episode["id"] == episode_id:
                episode["embedding"] = embedding
                return

    async def list_graphs(self, agent_id: str) -> list[str]:
        del agent_id
        return []

    async def get_stats_for_schema(self, agent_id: str, schema_name: str) -> GraphStats:
        del agent_id, schema_name
        return await self.get_stats()

    async def get_type_detail(self, agent_id: str, type_name: str, graph_name: str, kind: str) -> TypeDetail | None:
        del agent_id, graph_name
        if kind == "node":
            for nt in self._node_types.values():
                if nt.name == type_name:
                    count = sum(1 for n in self._nodes.values() if n.type_id == nt.id)
                    connected = set()
                    for e in self._edges.values():
                        src = self._nodes.get(e.source_id)
                        tgt = self._nodes.get(e.target_id)
                        if (src and src.type_id == nt.id) or (tgt and tgt.type_id == nt.id):
                            for et in self._edge_types.values():
                                if et.id == e.type_id:
                                    connected.add(et.name)
                    samples = sorted(
                        (n.name for n in self._nodes.values() if n.type_id == nt.id),
                    )[:5]
                    return TypeDetail(
                        id=nt.id,
                        name=nt.name,
                        description=nt.description,
                        count=count,
                        connected_edge_types=sorted(connected),
                        sample_names=samples,
                    )
        elif kind == "edge":
            for et in self._edge_types.values():
                if et.name == type_name:
                    count = sum(1 for e in self._edges.values() if e.type_id == et.id)
                    connected = set()
                    for e in self._edges.values():
                        if e.type_id == et.id:
                            src = self._nodes.get(e.source_id)
                            tgt = self._nodes.get(e.target_id)
                            if src:
                                for nt in self._node_types.values():
                                    if nt.id == src.type_id:
                                        connected.add(nt.name)
                            if tgt:
                                for nt in self._node_types.values():
                                    if nt.id == tgt.type_id:
                                        connected.add(nt.name)
                    samples = []
                    for e in self._edges.values():
                        if e.type_id == et.id:
                            src = self._nodes.get(e.source_id)
                            tgt = self._nodes.get(e.target_id)
                            if src and tgt:
                                samples.append(f"{src.name}→{tgt.name}")
                            if len(samples) >= 5:
                                break
                    return TypeDetail(
                        id=et.id,
                        name=et.name,
                        description=et.description,
                        count=count,
                        connected_edge_types=sorted(connected),
                        sample_names=samples,
                    )
        return None

    # ── Type Management ──

    async def get_or_create_node_type(
        self, agent_id: str, name: str, description: str | None = None, target_schema: str | None = None
    ) -> NodeType:
        del target_schema
        try:
            name = normalize_node_type(name)
        except ValueError:
            return None  # ty: ignore[invalid-return-type]  # protocol is NodeType | None
        if name in self._node_types:
            return self._node_types[name]
        now = datetime.now(UTC)
        nt = NodeType(id=self._next_type_id, name=name, description=description, created_at=now)
        self._next_type_id += 1
        self._node_types[name] = nt
        return nt

    async def get_or_create_edge_type(
        self, agent_id: str, name: str, description: str | None = None, target_schema: str | None = None
    ) -> EdgeType:
        del target_schema
        try:
            name = normalize_edge_type(name)
        except ValueError:
            return None  # ty: ignore[invalid-return-type]  # protocol is EdgeType | None
        if name in self._edge_types:
            return self._edge_types[name]
        now = datetime.now(UTC)
        et = EdgeType(id=self._next_type_id, name=name, description=description, created_at=now)
        self._next_type_id += 1
        self._edge_types[name] = et
        return et

    # ── Episode Read ──

    async def get_episode(self, agent_id: str, episode_id: int, target_schema: str | None = None) -> Episode | None:
        # When target_schema is set, search the schema-bucketed episodes first
        episodes = self._schema_episodes.get(target_schema, []) if target_schema else self._episodes
        for ep in episodes:
            if ep["id"] == episode_id and ep["agent_id"] == agent_id:
                return Episode(
                    id=ep["id"],
                    agent_id=ep["agent_id"],
                    content=ep["content"],
                    embedding=ep.get("embedding"),
                    source_type=ep.get("source_type"),
                    metadata=ep.get("metadata", {}),
                    access_count=ep.get("access_count", 0),
                    last_accessed_at=ep.get("last_accessed_at"),
                    importance=ep.get("importance", 0.5),
                    consolidated=ep.get("consolidated", False),
                    session_id=ep.get("session_id"),
                    session_sequence=ep.get("session_sequence"),
                    created_at=ep.get("created_at", datetime.now(UTC)),
                )
        return None

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
        del target_schema
        props = properties or {}

        # Canonicalize the name and extract aliases for registration after insert
        canonical, canon_aliases = canonicalize_name(name)
        if canonical:
            name = canonical

        # Phase 1: Look up by name only (name-primary dedup)
        # Include forgotten nodes so resurrection-on-upsert still works
        name_matches = [n for n in self._nodes.values() if n.name.lower() == name.lower()]

        # Phase 1.5: If no exact match, try alias resolution then fuzzy matching
        if not name_matches:
            # 1.5a: Check alias table
            alias_key = name.lower()
            alias_node_ids = self._aliases.get(alias_key, [])
            alias_nodes = [n for n in self._nodes.values() if n.id in alias_node_ids and not n.forgotten]
            if alias_nodes:
                name_matches = alias_nodes
                logger.bind(action_log=True).info(
                    "node_alias_resolved",
                    alias_value_present=bool(name),
                    candidate_node_ids=[n.id for n in alias_nodes],
                    agent_id=agent_id,
                )
            else:
                # 1.5b: Fuzzy matching using names_are_similar
                fuzzy_matches = [n for n in self._nodes.values() if not n.forgotten and names_are_similar(name, n.name)]
                if fuzzy_matches:
                    name_matches = [fuzzy_matches[0]]
                    logger.bind(action_log=True).info(
                        "node_fuzzy_matched",
                        input_value_present=bool(name),
                        matched_node_id=fuzzy_matches[0].id,
                        agent_id=agent_id,
                    )

        match: Node | None = None
        # Phase 2: Prefer exact (name, type_id) match
        for node in name_matches:
            if node.type_id == type_id:
                match = node
                break

        # Phase 3: If no exact match but exactly 1 node exists,
        # check whether the types are semantically compatible before merging.
        if match is None and len(name_matches) == 1:
            existing_node = name_matches[0]
            existing_type = next((nt.name for nt in self._node_types.values() if nt.id == existing_node.type_id), None)
            requested_type = next((nt.name for nt in self._node_types.values() if nt.id == type_id), None)
            if _types_are_merge_safe(existing_type, requested_type):
                match = existing_node
                logger.bind(action_log=True).info(
                    "node_type_drift_caught",
                    node_id=existing_node.id,
                    existing_type_id=existing_node.type_id,
                    requested_type_id=type_id,
                    action="merged",
                    agent_id=agent_id,
                )
            else:
                logger.bind(action_log=True).info(
                    "node_homonym_detected",
                    node_id=existing_node.id,
                    existing_type_id=existing_node.type_id,
                    requested_type_id=type_id,
                    action="created_separate",
                    agent_id=agent_id,
                )

        if match is not None:
            merged_props = {**match.properties, **props}
            now = datetime.now(UTC)
            # Resurrect forgotten nodes on re-upsert
            new_forgotten = match.forgotten if not match.forgotten else False
            new_forgotten_at = match.forgotten_at if not match.forgotten else None
            new_access_count = match.access_count + 1 if match.forgotten else match.access_count
            new_last_accessed = now if match.forgotten else match.last_accessed_at
            updated = Node(
                id=match.id,
                type_id=match.type_id,
                name=name,
                # Match COALESCE($1, content) semantics: only keep old when new is None
                content=content if content is not None else match.content,
                properties=merged_props,
                embedding=embedding or match.embedding,
                source=source or match.source,
                importance=max(match.importance, importance),
                access_count=new_access_count,
                last_accessed_at=new_last_accessed,
                forgotten=new_forgotten,
                forgotten_at=new_forgotten_at,
                created_at=match.created_at,
                updated_at=now,
            )
            self._nodes[match.id] = updated
            return updated
        now = datetime.now(UTC)
        node = Node(
            id=self._next_node_id,
            type_id=type_id,
            name=name,
            content=content,
            properties=props,
            embedding=embedding,
            source=source,
            importance=importance,
            created_at=now,
            updated_at=now,
        )
        self._next_node_id += 1
        self._nodes[node.id] = node
        # Auto-register canonicalization aliases for the new node
        for alias in canon_aliases:
            alias_key = alias.lower()
            self._aliases.setdefault(alias_key, [])
            if node.id not in self._aliases[alias_key]:
                self._aliases[alias_key].append(node.id)
        return node

    async def find_nodes_by_name(self, agent_id: str, name: str, target_schema: str | None = None) -> list[Node]:
        del target_schema
        return [n for n in self._nodes.values() if n.name.lower() == name.lower() and not n.forgotten]

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
        del target_schema, threshold
        expected_type_id = None
        if expected_type is not None:
            node_type = next(
                (item for item in self._node_types.values() if item.name.casefold() == expected_type.casefold()), None
            )
            if node_type is None:
                return []
            expected_type_id = node_type.id
        results: list[tuple[Node, float]] = []
        # Check alias table first
        alias_key = name.lower()
        alias_node_ids = self._aliases.get(alias_key, [])
        seen_ids: set[int] = set()
        for nid in alias_node_ids:
            node = self._nodes.get(nid)
            if (
                node
                and not node.forgotten
                and nid not in seen_ids
                and (expected_type_id is None or node.type_id == expected_type_id)
            ):
                results.append((node, 1.0))  # Alias match gets perfect score
                seen_ids.add(nid)
        # Then check fuzzy name similarity
        for node in self._nodes.values():
            if (
                node.forgotten
                or node.id in seen_ids
                or (expected_type_id is not None and node.type_id != expected_type_id)
            ):
                continue
            if names_are_similar(name, node.name):
                results.append((node, 0.5))
                seen_ids.add(node.id)
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:limit]

    async def register_alias(
        self,
        agent_id: str,
        node_id: int,
        alias: str,
        source: str = "extraction",
        target_schema: str | None = None,
    ) -> None:
        del agent_id, source, target_schema
        alias_key = alias.lower()
        self._aliases.setdefault(alias_key, [])
        if node_id not in self._aliases[alias_key]:
            self._aliases[alias_key].append(node_id)

    async def resolve_alias(
        self,
        agent_id: str,
        alias: str,
        target_schema: str | None = None,
    ) -> list[Node]:
        del agent_id, target_schema
        alias_key = alias.lower()
        node_ids = self._aliases.get(alias_key, [])
        return [n for n in self._nodes.values() if n.id in node_ids and not n.forgotten]

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
        del target_schema
        props = properties or {}

        # Source-target primary edge dedup
        st_edges = [e for e in self._edges.values() if e.source_id == source_id and e.target_id == target_id]

        if len(st_edges) == 1 and st_edges[0].type_id != type_id:
            # Single edge with different type → drift, update it
            old = st_edges[0]
            merged_props = {**old.properties, **props}
            logger.bind(action_log=True).info(
                "edge_type_drift_caught",
                source_id=source_id,
                target_id=target_id,
                old_type_id=old.type_id,
                new_type_id=type_id,
            )
            now = datetime.now(UTC)
            updated = Edge(
                id=old.id,
                source_id=source_id,
                target_id=target_id,
                type_id=type_id,
                weight=weight,
                properties=merged_props,
                created_at=old.created_at,
                last_reinforced_at=now,
            )
            self._edges[old.id] = updated
            return updated

        # Normal path: exact (source_id, target_id, type_id) match or insert
        for edge in st_edges:
            if edge.type_id == type_id:
                merged_props = {**edge.properties, **props}
                updated = Edge(
                    id=edge.id,
                    source_id=source_id,
                    target_id=target_id,
                    type_id=type_id,
                    weight=weight,
                    properties=merged_props,
                    created_at=edge.created_at,
                )
                self._edges[edge.id] = updated
                return updated
        now = datetime.now(UTC)
        edge = Edge(
            id=self._next_edge_id,
            source_id=source_id,
            target_id=target_id,
            type_id=type_id,
            weight=weight,
            properties=props,
            created_at=now,
        )
        self._next_edge_id += 1
        self._edges[edge.id] = edge
        return edge

    async def delete_edge(
        self,
        agent_id: str,
        edge_id: int,
        target_schema: str | None = None,
    ) -> bool:
        del agent_id, target_schema
        if edge_id in self._edges:
            del self._edges[edge_id]
            return True
        return False

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
        # The in-memory repository has one global graph and cannot enforce schema isolation.
        del agent_id, query_embedding, target_schema
        expected_type_id = None
        if expected_type is not None:
            node_type = next(
                (item for item in self._node_types.values() if item.name.casefold() == expected_type.casefold()), None
            )
            if node_type is None:
                return []
            expected_type_id = node_type.id
        query_lower = query.lower()
        matches: list[tuple[Node, float]] = []
        for node in self._nodes.values():
            if node.forgotten or (expected_type_id is not None and node.type_id != expected_type_id):
                continue
            name_match = query_lower in node.name.lower()
            content_match = node.content and query_lower in node.content.lower()
            if name_match or content_match:
                # Simple text overlap heuristic for relevance score
                name_score = 1.0 if name_match else 0.0
                content_score = 0.5 if content_match else 0.0
                relevance = max(name_score, content_score)
                matches.append((node, relevance))
        matches.sort(key=lambda x: x[1], reverse=True)
        return matches[:limit]

    # ── Graph Traversal ──

    async def get_node_neighborhood(
        self, agent_id: str, node_id: int, depth: int = 2, target_schema: str | None = None
    ) -> list[dict]:
        # Compatibility only: this repository does not model PostgreSQL schemas.
        del agent_id, target_schema
        visited: set[int] = {node_id}
        results: list[dict] = []
        current_frontier = [node_id]

        for dist in range(1, depth + 1):
            next_frontier: list[int] = []
            for nid in current_frontier:
                edges_by_neighbor: dict[int, list[Edge]] = {}
                for edge in self._edges.values():
                    neighbor_id: int | None = None
                    if edge.source_id == nid:
                        neighbor_id = edge.target_id
                    elif edge.target_id == nid:
                        neighbor_id = edge.source_id
                    if neighbor_id is not None:
                        edges_by_neighbor.setdefault(neighbor_id, []).append(edge)
                for neighbor_id, edges in edges_by_neighbor.items():
                    if neighbor_id in visited or neighbor_id not in self._nodes or self._nodes[neighbor_id].forgotten:
                        continue
                    visited.add(neighbor_id)
                    next_frontier.append(neighbor_id)
                    results.append({"node": self._nodes[neighbor_id], "edges": edges, "distance": dist})
            current_frontier = next_frontier
            if not current_frontier:
                break

        return results

    # ── Node Browsing ──

    async def list_nodes_page(
        self,
        agent_id: str,
        target_schema: str | None = None,
        type_id: int | None = None,
        limit: int = 20,
    ) -> list[Node]:
        del target_schema
        nodes = [n for n in self._nodes.values() if not n.forgotten]
        if type_id is not None:
            nodes = [n for n in nodes if n.type_id == type_id]
        nodes.sort(key=lambda n: (n.importance, n.access_count), reverse=True)
        return nodes[:limit]

    # ── Bulk Queries ──

    async def list_all_node_names(
        self, agent_id: str, target_schema: str | None = None, limit: int | None = None
    ) -> list[str]:
        del target_schema
        names = sorted(n.name for n in self._nodes.values() if not n.forgotten)
        if limit is not None:
            return names[:limit]
        return names

    # ── Soft-Forget ──

    async def mark_forgotten(self, agent_id: str, node_ids: list[int], target_schema: str | None = None) -> int:
        now = datetime.now(UTC)
        count = 0
        for nid in node_ids:
            node = self._nodes.get(nid)
            if node is not None and not node.forgotten:
                self._nodes[nid] = node.model_copy(update={"forgotten": True, "forgotten_at": now})
                count += 1
        return count

    async def resurrect_node(self, agent_id: str, node_id: int) -> None:
        now = datetime.now(UTC)
        node = self._nodes.get(node_id)
        if node is not None:
            self._nodes[node_id] = node.model_copy(
                update={
                    "forgotten": False,
                    "forgotten_at": None,
                    "access_count": node.access_count + 1,
                    "last_accessed_at": now,
                }
            )

    async def identify_forgettable_nodes(
        self, agent_id: str, activation_threshold: float, importance_floor: float
    ) -> list[int]:
        now = datetime.now(UTC)
        threshold = now - timedelta(days=7)
        forgettable = []
        for node in self._nodes.values():
            if node.forgotten:
                continue
            if node.importance >= importance_floor:
                continue
            if node.access_count > 0:
                continue
            last_acc = node.last_accessed_at or node.created_at
            if last_acc >= threshold:
                continue
            forgettable.append(node.id)
        return forgettable

    # ── Partial Curation Cleanup ──

    async def cleanup_partial_curation(
        self,
        agent_id: str,
        episode_id: int,
        target_schema: str | None = None,
    ) -> int:
        del agent_id, target_schema
        episode_str = str(episode_id)
        deleted = 0
        # Delete edges tagged with this episode
        edge_ids_to_delete = [
            eid for eid, edge in self._edges.items() if str(edge.properties.get("_source_episode", "")) == episode_str
        ]
        for eid in edge_ids_to_delete:
            del self._edges[eid]
            deleted += 1
        # Delete nodes tagged with this episode
        node_ids_to_delete = [
            nid for nid, node in self._nodes.items() if str(node.properties.get("_source_episode", "")) == episode_str
        ]
        for nid in node_ids_to_delete:
            del self._nodes[nid]
            deleted += 1
        return deleted

    # ── Episodic Consolidation ──

    async def mark_episode_consolidated(self, agent_id: str, episode_id: int, target_schema: str | None = None) -> None:
        for ep in self._episodes:
            if ep["id"] == episode_id and ep["agent_id"] == agent_id:
                ep["consolidated"] = True
                return

    async def link_personal_episode_to_session_predecessor(self, agent_id: str, episode_id: int) -> None:
        pass

    # ── Access Tracking ──

    async def record_node_access(self, agent_id: str, node_ids: list[int], limit: int | None = None) -> None:
        now = datetime.now(UTC)
        ids_to_update = node_ids[:limit] if limit is not None else node_ids
        for nid in ids_to_update:
            node = self._nodes.get(nid)
            if node is not None:
                self._nodes[nid] = node.model_copy(
                    update={"access_count": node.access_count + 1, "last_accessed_at": now}
                )

    async def record_episode_access(self, agent_id: str, episode_ids: list[int], limit: int | None = None) -> None:
        now = datetime.now(UTC)
        ids_to_update = set(episode_ids[:limit] if limit is not None else episode_ids)
        for ep in self._episodes:
            if ep["id"] in ids_to_update:
                ep["access_count"] = ep.get("access_count", 0) + 1
                ep["last_accessed_at"] = now

    # ── Edge Reinforcement ──

    async def reinforce_edges(
        self, agent_id: str, edge_ids: list[int], delta: float = 0.05, ceiling: float = 1.5
    ) -> None:
        now = datetime.now(UTC)
        for eid in edge_ids:
            edge = self._edges.get(eid)
            if edge is not None:
                # Logarithmic diminishing returns: increment shrinks as weight grows
                increment = delta / (1.0 + (edge.weight - 1.0) * 5.0)
                new_weight = min(edge.weight + increment, ceiling)
                self._edges[eid] = edge.model_copy(update={"weight": new_weight, "last_reinforced_at": now})

    async def micro_decay_edges(
        self,
        agent_id: str,
        exclude_ids: list[int],
        factor: float = 0.998,
        floor: float = 0.1,
        recently_reinforced_hours: float = 1.0,
    ) -> int:
        now = datetime.now(UTC)
        threshold = now - timedelta(hours=recently_reinforced_hours)
        count = 0
        for eid, edge in list(self._edges.items()):
            if eid in exclude_ids:
                continue
            reinforced_at = edge.last_reinforced_at or edge.created_at
            if reinforced_at > threshold and edge.weight > floor:
                new_weight = max(edge.weight * factor, floor)
                self._edges[eid] = edge.model_copy(update={"weight": new_weight})
                count += 1
        return count

    async def decay_stale_edges(
        self,
        agent_id: str,
        older_than_hours: float = 48.0,
        decay_factor: float = 0.95,
        floor: float = 0.1,
        force: bool = False,
    ) -> int:
        now = datetime.now(UTC)
        threshold = now - timedelta(hours=older_than_hours)
        count = 0
        for eid, edge in list(self._edges.items()):
            reinforced_at = edge.last_reinforced_at or edge.created_at
            if reinforced_at < threshold and edge.weight > floor:
                new_weight = max(edge.weight * decay_factor, floor)
                self._edges[eid] = edge.model_copy(update={"weight": new_weight})
                count += 1
        return count

    # ── Type Introspection ──

    async def get_type_examples(
        self,
        agent_id: str,
        target_schema: str | None = None,
        limit_per_type: int = 5,
        max_types: int = 20,
    ) -> dict[str, list[str]]:
        del agent_id, target_schema
        result: dict[str, list[str]] = {}
        for nt in sorted(self._node_types.values(), key=lambda t: t.name):
            nodes = sorted(
                (n for n in self._nodes.values() if n.type_id == nt.id and not n.forgotten),
                key=lambda n: n.importance,
                reverse=True,
            )
            if nodes:
                result[nt.name] = [n.name for n in nodes[:limit_per_type]]
            if len(result) >= max_types:
                break
        return result

    async def cleanup_empty_types(
        self,
        agent_id: str,
        max_age_minutes: int = 5,
        target_schema: str | None = None,
    ) -> None:
        del agent_id, target_schema
        now = datetime.now(UTC)
        cutoff = now - timedelta(minutes=max_age_minutes)
        to_delete = []
        for name, nt in self._node_types.items():
            has_nodes = any(n.type_id == nt.id for n in self._nodes.values())
            if not has_nodes and nt.created_at > cutoff:
                to_delete.append(name)
        for name in to_delete:
            del self._node_types[name]
            logger.info("cleaned_empty_types", count=1, names=[name])

    # ── Ontology Exploration ──

    async def find_similar_types(
        self,
        agent_id: str,
        query: str,
        kind: str = "node",
        limit: int = 5,
        target_schema: str | None = None,
    ) -> list[tuple[TypeInfo, int, list[str]]]:
        del agent_id, target_schema
        results: list[tuple[TypeInfo, int, list[str]]] = []
        if kind == "edge":
            for et in self._edge_types.values():
                if names_are_similar(query, et.name) or (et.description and query.lower() in et.description.lower()):
                    usage_count = sum(1 for e in self._edges.values() if e.type_id == et.id)
                    examples: list[str] = []
                    for e in self._edges.values():
                        if e.type_id == et.id:
                            src = self._nodes.get(e.source_id)
                            tgt = self._nodes.get(e.target_id)
                            if src and tgt:
                                examples.append(f"{src.name}→{tgt.name}")
                            if len(examples) >= 3:
                                break
                    results.append(
                        (
                            TypeInfo(id=et.id, name=et.name, description=et.description),
                            usage_count,
                            examples,
                        )
                    )
        else:
            for nt in self._node_types.values():
                if names_are_similar(query, nt.name) or (nt.description and query.lower() in nt.description.lower()):
                    usage_count = sum(1 for n in self._nodes.values() if n.type_id == nt.id and not n.forgotten)
                    examples = sorted(
                        (n.name for n in self._nodes.values() if n.type_id == nt.id and not n.forgotten),
                    )[:3]
                    results.append(
                        (
                            TypeInfo(id=nt.id, name=nt.name, description=nt.description),
                            usage_count,
                            examples,
                        )
                    )
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:limit]

    async def get_ontology_summary(
        self,
        agent_id: str,
        target_schema: str | None = None,
    ) -> dict:
        del agent_id, target_schema
        node_types_list = []
        for nt in sorted(self._node_types.values(), key=lambda t: t.name):
            usage = sum(1 for n in self._nodes.values() if n.type_id == nt.id and not n.forgotten)
            node_types_list.append({"name": nt.name, "description": nt.description or "", "usage_count": usage})
        node_types_list.sort(key=lambda x: x["usage_count"], reverse=True)

        edge_types_list = []
        for et in sorted(self._edge_types.values(), key=lambda t: t.name):
            usage = sum(1 for e in self._edges.values() if e.type_id == et.id)
            edge_types_list.append({"name": et.name, "description": et.description or "", "usage_count": usage})
        edge_types_list.sort(key=lambda x: x["usage_count"], reverse=True)

        total_nodes = sum(1 for n in self._nodes.values() if not n.forgotten)
        total_edges = len(self._edges)
        return {
            "node_types": node_types_list,
            "edge_types": edge_types_list,
            "total_nodes": total_nodes,
            "total_edges": total_edges,
        }

    async def list_all_edge_signatures(self, agent_id: str) -> list[str]:
        sigs = []
        for edge in self._edges.values():
            src = self._nodes.get(edge.source_id)
            tgt = self._nodes.get(edge.target_id)
            et = None
            for et_val in self._edge_types.values():
                if et_val.id == edge.type_id:
                    et = et_val
                    break
            if src and tgt and et:
                sigs.append(f"{src.name}→{et.name}→{tgt.name}")
        return sorted(sigs)

    # ── Type Consolidation ──

    async def reassign_node_type(
        self,
        agent_id: str,
        source_type_id: int,
        target_type_id: int,
        target_schema: str | None = None,
    ) -> int:
        del agent_id, target_schema
        count = 0
        for node in self._nodes.values():
            if node.type_id == source_type_id:
                # Create a new node with the updated type_id
                self._nodes[node.id] = Node(
                    id=node.id,
                    name=node.name,
                    type_id=target_type_id,
                    content=node.content,
                    properties=node.properties,
                    embedding=node.embedding,
                    importance=node.importance,
                    forgotten=node.forgotten,
                    created_at=node.created_at,
                    updated_at=node.updated_at,
                    access_count=node.access_count,
                    last_accessed_at=node.last_accessed_at,
                )
                count += 1
        return count

    async def delete_type(
        self,
        agent_id: str,
        type_id: int,
        kind: Literal["node", "edge"] = "node",
        target_schema: str | None = None,
    ) -> None:
        del agent_id, target_schema
        if kind == "edge":
            has_edges = any(e.type_id == type_id for e in self._edges.values())
            if has_edges:
                raise ValueError(f"Cannot delete edge type {type_id}: still has edges")
            to_del = [name for name, et in self._edge_types.items() if et.id == type_id]
            for name in to_del:
                del self._edge_types[name]
        else:
            has_nodes = any(n.type_id == type_id for n in self._nodes.values())
            if has_nodes:
                raise ValueError(f"Cannot delete node type {type_id}: still has nodes")
            to_del = [name for name, nt in self._node_types.items() if nt.id == type_id]
            for name in to_del:
                del self._node_types[name]

    async def get_unused_types(
        self,
        agent_id: str,
        kind: Literal["node", "edge"] = "node",
        min_age_hours: float = 24.0,
        target_schema: str | None = None,
    ) -> list[tuple[int, str, datetime]]:
        del agent_id, target_schema
        cutoff = datetime.now(UTC) - timedelta(hours=min_age_hours)
        results: list[tuple[int, str, datetime]] = []
        if kind == "edge":
            for et in self._edge_types.values():
                has_edges = any(e.type_id == et.id for e in self._edges.values())
                if not has_edges and et.created_at < cutoff:
                    results.append((et.id, et.name, et.created_at))
        else:
            for nt in self._node_types.values():
                has_nodes = any(n.type_id == nt.id for n in self._nodes.values())
                if not has_nodes and nt.created_at < cutoff:
                    results.append((nt.id, nt.name, nt.created_at))
        results.sort(key=lambda x: x[2])
        return results
