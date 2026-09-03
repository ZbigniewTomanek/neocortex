"""Tests for post-extraction type consolidation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from loguru import logger

import neocortex.extraction.type_consolidation as type_consolidation
from neocortex.db.mock import InMemoryRepository
from neocortex.extraction.type_consolidation import (
    archive_unused_types,
    merge_similar_types,
)
from neocortex.models import NodeType

AGENT_ID = "test-agent"


@pytest.fixture
def repo() -> InMemoryRepository:
    return InMemoryRepository()


async def _create_node_type(repo: InMemoryRepository, name: str, age_hours: float = 0) -> NodeType:
    """Helper to create a node type with controllable created_at."""
    nt = await repo.get_or_create_node_type(AGENT_ID, name, description=f"Test type {name}")
    assert nt is not None
    # Backdate the created_at if needed
    if age_hours > 0:
        nt_obj = repo._node_types[name]
        backdated = datetime.now(UTC) - timedelta(hours=age_hours)
        repo._node_types[name] = NodeType(
            id=nt_obj.id,
            name=nt_obj.name,
            description=nt_obj.description,
            created_at=backdated,
        )
    return nt


async def _create_edge_type(repo: InMemoryRepository, name: str, age_hours: float = 0):
    """Helper to create an edge type with controllable created_at."""
    from neocortex.models import EdgeType

    et = await repo.get_or_create_edge_type(AGENT_ID, name, description=f"Test edge {name}")
    assert et is not None
    if age_hours > 0:
        et_obj = repo._edge_types[name]
        backdated = datetime.now(UTC) - timedelta(hours=age_hours)
        repo._edge_types[name] = EdgeType(
            id=et_obj.id,
            name=et_obj.name,
            description=et_obj.description,
            created_at=backdated,
        )
    return et


# ---------------------------------------------------------------------------
# merge_similar_types
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_dry_run_reports_without_mutating(repo: InMemoryRepository):
    """Dry run should identify merges but not modify data."""
    # Create source and target types from the merge map
    await _create_node_type(repo, "AnatomicalLocation")
    await _create_node_type(repo, "BodyPart")

    # Add a node to the source type
    source_type = repo._node_types["AnatomicalLocation"]
    await repo.upsert_node(AGENT_ID, "Spine", type_id=source_type.id)

    actions = await merge_similar_types(repo, AGENT_ID, dry_run=True)

    assert len(actions) == 1
    assert actions[0].source_type_name == "AnatomicalLocation"
    assert actions[0].target_type_name == "BodyPart"
    assert actions[0].nodes_moved == 1

    # Data should NOT be modified
    assert "AnatomicalLocation" in repo._node_types
    spine_node = next(n for n in repo._nodes.values() if n.name == "Spine")
    assert spine_node.type_id == source_type.id


@pytest.mark.asyncio
async def test_merge_apply_reassigns_and_deletes(repo: InMemoryRepository):
    """Apply mode should reassign nodes and delete source type."""
    await _create_node_type(repo, "HealthActivity")
    target = await _create_node_type(repo, "Activity")

    source_type = repo._node_types["HealthActivity"]
    await repo.upsert_node(AGENT_ID, "Running", type_id=source_type.id)
    await repo.upsert_node(AGENT_ID, "Swimming", type_id=source_type.id)

    actions = await merge_similar_types(repo, AGENT_ID, dry_run=False)

    assert len(actions) == 1
    assert actions[0].nodes_moved == 2

    # Source type should be deleted
    assert "HealthActivity" not in repo._node_types

    # Nodes should be reassigned to target type
    for node in repo._nodes.values():
        if node.name in ("Running", "Swimming"):
            assert node.type_id == target.id


@pytest.mark.asyncio
async def test_merge_skips_missing_types(repo: InMemoryRepository):
    """Merge should skip entries where source or target type doesn't exist."""
    # Only create the source, not the target
    await _create_node_type(repo, "AnatomicalLocation")

    actions = await merge_similar_types(repo, AGENT_ID, dry_run=False)
    assert len(actions) == 0


@pytest.mark.asyncio
async def test_merge_handles_multiple_map_entries(repo: InMemoryRepository):
    """Multiple merge map entries pointing to the same target should all work."""
    await _create_node_type(repo, "AnatomicalLocation")
    await _create_node_type(repo, "AnatomicalStructure")
    target = await _create_node_type(repo, "BodyPart")

    source1 = repo._node_types["AnatomicalLocation"]
    source2 = repo._node_types["AnatomicalStructure"]
    await repo.upsert_node(AGENT_ID, "Spine", type_id=source1.id)
    await repo.upsert_node(AGENT_ID, "Femur", type_id=source2.id)

    actions = await merge_similar_types(repo, AGENT_ID, dry_run=False)

    assert len(actions) == 2
    assert "AnatomicalLocation" not in repo._node_types
    assert "AnatomicalStructure" not in repo._node_types
    assert "BodyPart" in repo._node_types

    for node in repo._nodes.values():
        assert node.type_id == target.id


# ---------------------------------------------------------------------------
# archive_unused_types
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_archive_dry_run_reports_without_deleting(repo: InMemoryRepository):
    """Dry run should identify unused types but not delete them."""
    await _create_node_type(repo, "ObsoleteType", age_hours=48)

    actions = await archive_unused_types(repo, AGENT_ID, min_age_hours=24.0, dry_run=True)

    assert len(actions) == 1
    assert actions[0].type_name == "ObsoleteType"
    assert actions[0].kind == "node"

    # Type should still exist
    assert "ObsoleteType" in repo._node_types


@pytest.mark.asyncio
async def test_archive_apply_deletes_old_unused(repo: InMemoryRepository):
    """Apply should delete old unused types."""
    await _create_node_type(repo, "ObsoleteType", age_hours=48)

    actions = await archive_unused_types(repo, AGENT_ID, min_age_hours=24.0, dry_run=False)

    assert len(actions) == 1
    assert "ObsoleteType" not in repo._node_types


@pytest.mark.asyncio
async def test_archive_skips_recent_types(repo: InMemoryRepository):
    """Types younger than min_age_hours should not be archived."""
    await _create_node_type(repo, "NewType", age_hours=1)

    actions = await archive_unused_types(repo, AGENT_ID, min_age_hours=24.0, dry_run=False)

    assert len(actions) == 0
    assert "NewType" in repo._node_types


@pytest.mark.asyncio
async def test_archive_skips_used_types(repo: InMemoryRepository):
    """Types with nodes should never be archived."""
    nt = await _create_node_type(repo, "UsedType", age_hours=48)
    await repo.upsert_node(AGENT_ID, "SomeEntity", type_id=nt.id)

    actions = await archive_unused_types(repo, AGENT_ID, min_age_hours=24.0, dry_run=False)

    assert len(actions) == 0
    assert "UsedType" in repo._node_types


@pytest.mark.asyncio
async def test_archive_never_deletes_seed_node_types(repo: InMemoryRepository):
    """Seed node types should never be archived, even if unused and old."""
    for seed_name in ["Concept", "Person", "Activity", "Location"]:
        await _create_node_type(repo, seed_name, age_hours=720)

    actions = await archive_unused_types(repo, AGENT_ID, min_age_hours=24.0, dry_run=False)

    # No seed types should be archived
    assert len(actions) == 0
    for seed_name in ["Concept", "Person", "Activity", "Location"]:
        assert seed_name in repo._node_types


@pytest.mark.asyncio
async def test_archive_never_deletes_seed_edge_types(repo: InMemoryRepository):
    """Seed edge types should never be archived, even if unused and old."""
    for seed_name in ["RELATES_TO", "MENTIONS", "USES"]:
        await _create_edge_type(repo, seed_name, age_hours=720)

    actions = await archive_unused_types(repo, AGENT_ID, min_age_hours=24.0, dry_run=False)

    assert len(actions) == 0


@pytest.mark.asyncio
async def test_archive_handles_both_node_and_edge_types(repo: InMemoryRepository):
    """Archive should process both node and edge types."""
    await _create_node_type(repo, "ObsoleteNode", age_hours=48)
    await _create_edge_type(repo, "OBSOLETE_EDGE", age_hours=48)

    actions = await archive_unused_types(repo, AGENT_ID, min_age_hours=24.0, dry_run=False)

    assert len(actions) == 2
    kinds = {a.kind for a in actions}
    assert kinds == {"node", "edge"}
    assert "ObsoleteNode" not in repo._node_types
    assert "OBSOLETE_EDGE" not in repo._edge_types


# ---------------------------------------------------------------------------
# Protocol methods: reassign_node_type and delete_type
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reassign_node_type(repo: InMemoryRepository):
    """reassign_node_type should move all nodes from source to target type."""
    source = await _create_node_type(repo, "SourceType")
    target = await _create_node_type(repo, "TargetType")

    await repo.upsert_node(AGENT_ID, "Node1", type_id=source.id)
    await repo.upsert_node(AGENT_ID, "Node2", type_id=source.id)
    await repo.upsert_node(AGENT_ID, "Node3", type_id=target.id)

    moved = await repo.reassign_node_type(AGENT_ID, source.id, target.id)

    assert moved == 2
    for node in repo._nodes.values():
        if node.name in ("Node1", "Node2", "Node3"):
            assert node.type_id == target.id


@pytest.mark.asyncio
async def test_delete_type_node_empty(repo: InMemoryRepository):
    """delete_type should succeed for node types with no nodes."""
    nt = await _create_node_type(repo, "EmptyType")

    await repo.delete_type(AGENT_ID, nt.id, kind="node")

    assert "EmptyType" not in repo._node_types


@pytest.mark.asyncio
async def test_delete_type_node_with_nodes_raises(repo: InMemoryRepository):
    """delete_type should fail if the node type still has nodes."""
    nt = await _create_node_type(repo, "UsedType")
    await repo.upsert_node(AGENT_ID, "Entity", type_id=nt.id)

    with pytest.raises(ValueError, match="still has nodes"):
        await repo.delete_type(AGENT_ID, nt.id, kind="node")


@pytest.mark.asyncio
async def test_delete_type_edge_empty(repo: InMemoryRepository):
    """delete_type should succeed for edge types with no edges."""
    et = await _create_edge_type(repo, "EMPTY_EDGE")

    await repo.delete_type(AGENT_ID, et.id, kind="edge")

    assert "EMPTY_EDGE" not in repo._edge_types


@pytest.mark.asyncio
async def test_delete_type_edge_with_edges_raises(repo: InMemoryRepository):
    """delete_type should fail if the edge type still has edges."""
    et = await _create_edge_type(repo, "USED_EDGE")
    nt = await _create_node_type(repo, "SomeType")
    n1 = await repo.upsert_node(AGENT_ID, "A", type_id=nt.id)
    n2 = await repo.upsert_node(AGENT_ID, "B", type_id=nt.id)
    await repo.upsert_edge(AGENT_ID, n1.id, n2.id, type_id=et.id)

    with pytest.raises(ValueError, match="still has edges"):
        await repo.delete_type(AGENT_ID, et.id, kind="edge")


@pytest.mark.asyncio
async def test_get_unused_types_filters_by_age(repo: InMemoryRepository):
    """get_unused_types should only return types older than the threshold."""
    await _create_node_type(repo, "OldUnused", age_hours=48)
    await _create_node_type(repo, "NewUnused", age_hours=1)

    unused = await repo.get_unused_types(AGENT_ID, kind="node", min_age_hours=24.0)

    names = [name for _, name, _ in unused]
    assert "OldUnused" in names
    assert "NewUnused" not in names


@pytest.mark.asyncio
async def test_get_unused_types_excludes_used(repo: InMemoryRepository):
    """get_unused_types should exclude types that have nodes."""
    nt = await _create_node_type(repo, "UsedType", age_hours=48)
    await repo.upsert_node(AGENT_ID, "Entity", type_id=nt.id)
    await _create_node_type(repo, "UnusedType", age_hours=48)

    unused = await repo.get_unused_types(AGENT_ID, kind="node", min_age_hours=24.0)

    names = [name for _, name, _ in unused]
    assert "UnusedType" in names
    assert "UsedType" not in names


@pytest.mark.asyncio
async def test_type_consolidation_action_audit_is_opaque(
    repo: InMemoryRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Type action audit records contain IDs, not model/source-derived names."""
    source_name = "PrivateSourceTypeSentinel"
    target_name = "PrivateTargetTypeSentinel"
    unused_name = "PrivateUnusedTypeSentinel"
    monkeypatch.setattr(type_consolidation, "_MERGE_MAP", {source_name: target_name})
    await _create_node_type(repo, source_name)
    await _create_node_type(repo, target_name)
    await _create_node_type(repo, unused_name, age_hours=48)

    records: list[dict] = []
    sink_id = logger.add(lambda message: records.append(message.record), level="INFO")
    try:
        await merge_similar_types(repo, AGENT_ID, dry_run=False)
        await archive_unused_types(repo, AGENT_ID, min_age_hours=24.0, dry_run=False)
    finally:
        logger.remove(sink_id)

    action_records = [record for record in records if record["extra"].get("action_log")]
    assert {record["message"] for record in action_records} >= {"type_merged", "type_archived"}
    for record in action_records:
        assert all(sentinel not in str(record["extra"]) for sentinel in (source_name, target_name, unused_name))
    merged = next(record for record in action_records if record["message"] == "type_merged")
    assert isinstance(merged["extra"]["source_type_id"], int)
    assert isinstance(merged["extra"]["target_type_id"], int)
    archived = next(record for record in action_records if record["message"] == "type_archived")
    assert isinstance(archived["extra"]["type_id"], int)
