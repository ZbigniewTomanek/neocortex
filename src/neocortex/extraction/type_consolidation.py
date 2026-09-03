"""Post-extraction type consolidation: merge near-duplicates, archive unused types.

Prevents ontology drift over time by:
1. Merging known-equivalent types (hardcoded merge map)
2. Archiving unused types older than a configurable threshold
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from loguru import logger

if TYPE_CHECKING:
    from neocortex.db.protocol import MemoryRepository

# Seed types from 003_seed_ontology.sql and 006_expanded_seed.sql — never archive these.
SEED_NODE_TYPES: frozenset[str] = frozenset(
    {
        # 003
        "Concept",
        "Person",
        "Document",
        "Event",
        "Tool",
        "Preference",
        # 006
        "Organization",
        "Location",
        "Project",
        "Activity",
        "Asset",
        "Substance",
        "Metric",
        "Symptom",
        "Goal",
        "Task",
        "Emotion",
        "Recipe",
        "Protocol",
        "Routine",
    }
)

SEED_EDGE_TYPES: frozenset[str] = frozenset(
    {
        # 003
        "RELATES_TO",
        "MENTIONS",
        "CAUSED_BY",
        "FOLLOWS",
        "AUTHORED",
        "USES",
        "CONTRADICTS",
        "SUPPORTS",
        "SUMMARIZES",
        "DERIVED_FROM",
        "SUPERSEDES",
        "CORRECTS",
        # 006
        "HAS_GOAL",
        "WORKS_ON",
        "WORKS_FOR",
        "LOCATED_AT",
        "PART_OF",
        "EXPERIENCED",
        "CONSUMES",
        "PERFORMS",
        "OWNS",
        "RECOMMENDS",
        "IMPROVES",
    }
)

# Known type equivalences. source -> target (target is the canonical name).
_MERGE_MAP: dict[str, str] = {
    "AnatomicalLocation": "BodyPart",
    "AnatomicalStructure": "BodyPart",
    "HealthActivity": "Activity",
    "SportActivity": "Activity",
    "ArchitectureConcept": "Concept",
    "TechnicalArchitecture": "ArchitecturePattern",
    "HealthState": "Symptom",
    "Condition": "Symptom",
}


@dataclass
class MergeAction:
    source_type_name: str
    source_type_id: int
    target_type_name: str
    target_type_id: int
    nodes_moved: int


@dataclass
class ArchiveAction:
    type_name: str
    type_id: int
    kind: str  # "node" or "edge"


@dataclass
class ConsolidationResult:
    merges: list[MergeAction]
    archives: list[ArchiveAction]


async def merge_similar_types(
    repo: MemoryRepository,
    agent_id: str,
    schema: str | None = None,
    dry_run: bool = True,
) -> list[MergeAction]:
    """Find and merge near-duplicate node types.

    Uses a hardcoded merge map for known equivalences. For each merge,
    reassigns all nodes from the source type to the target type, then
    deletes the source type.

    Returns list of merge actions taken (or that would be taken in dry_run mode).
    """
    actions: list[MergeAction] = []

    # Get current ontology
    summary = await repo.get_ontology_summary(agent_id, target_schema=schema)
    node_types_by_name: dict[str, dict] = {nt["name"]: nt for nt in summary["node_types"]}

    # Get type IDs — we need them for reassignment

    type_infos = await repo.get_node_types(agent_id, target_schema=schema)
    type_id_by_name: dict[str, int] = {t.name: t.id for t in type_infos}

    # Apply hardcoded merge map
    for source_name, target_name in _MERGE_MAP.items():
        if source_name not in type_id_by_name:
            continue
        if target_name not in type_id_by_name:
            continue

        source_id = type_id_by_name[source_name]
        target_id = type_id_by_name[target_name]
        source_usage = node_types_by_name.get(source_name, {}).get("usage_count", 0)

        if dry_run:
            actions.append(
                MergeAction(
                    source_type_name=source_name,
                    source_type_id=source_id,
                    target_type_name=target_name,
                    target_type_id=target_id,
                    nodes_moved=source_usage,
                )
            )
            logger.info(
                "merge_preview",
                source=source_name,
                target=target_name,
                nodes=source_usage,
            )
        else:
            moved = await repo.reassign_node_type(agent_id, source_id, target_id, target_schema=schema)
            await repo.delete_type(agent_id, source_id, kind="node", target_schema=schema)
            actions.append(
                MergeAction(
                    source_type_name=source_name,
                    source_type_id=source_id,
                    target_type_name=target_name,
                    target_type_id=target_id,
                    nodes_moved=moved,
                )
            )
            logger.bind(action_log=True).info(
                "type_merged",
                action="merged",
                kind="node",
                source_type_id=source_id,
                target_type_id=target_id,
                nodes_moved=moved,
            )

    return actions


async def archive_unused_types(
    repo: MemoryRepository,
    agent_id: str,
    schema: str | None = None,
    min_age_hours: float = 24.0,
    dry_run: bool = True,
) -> list[ArchiveAction]:
    """Remove types that have 0 usage and are older than min_age_hours.

    Seed types (from 003 and 006 migrations) are never archived.

    Returns list of archive actions taken (or that would be taken in dry_run mode).
    """
    actions: list[ArchiveAction] = []

    pairs: list[tuple[Literal["node", "edge"], frozenset[str]]] = [
        ("node", SEED_NODE_TYPES),
        ("edge", SEED_EDGE_TYPES),
    ]
    for kind, seed_names in pairs:
        unused = await repo.get_unused_types(agent_id, kind=kind, min_age_hours=min_age_hours, target_schema=schema)
        for type_id, type_name, _created_at in unused:
            if type_name in seed_names:
                continue

            if dry_run:
                actions.append(ArchiveAction(type_name=type_name, type_id=type_id, kind=kind))
                logger.info("archive_preview", kind=kind, name=type_name, type_id=type_id)
            else:
                try:
                    await repo.delete_type(agent_id, type_id, kind=kind, target_schema=schema)
                    actions.append(ArchiveAction(type_name=type_name, type_id=type_id, kind=kind))
                    logger.bind(action_log=True).info(
                        "type_archived",
                        action="archived",
                        kind=kind,
                        type_id=type_id,
                    )
                except ValueError:
                    # Race condition: type got used between query and delete
                    logger.debug("archive_skipped_in_use", kind=kind, name=type_name)

    return actions
