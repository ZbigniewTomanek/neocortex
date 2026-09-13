#!/usr/bin/env python3
"""Export a deterministic, privacy-safe graph sample and temporal-survival flags.

Plan 33's graph "sample" was a raw ``pg_dump``, which no evidence tool may read.
This exporter publishes shape only: identifiers, types, lengths, counts and
booleans.  No node name, no content, no property value ever leaves the database.

Every query goes through an injected connection used only as
``await conn.fetch(query, *args)``, so the whole selection and shaping path is
exercised in unit tests against a fake connection.  Stage 7 is the first time
this script touches a real database.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol, cast

from neocortex.config import PostgresConfig
from neocortex.db.scoped import _VALID_SCHEMA_NAME, schema_scoped_connection
from neocortex.normalization import _VALID_EDGE_TYPE, _VALID_NODE_TYPE

try:  # Package import (tests, ``python -m``).
    from scripts.compute_metrics import _atomic_write_json  # ty: ignore[unresolved-import]
except ModuleNotFoundError:  # Direct script execution.
    from compute_metrics import _atomic_write_json  # ty: ignore[unresolved-import]

ROOT = Path(__file__).resolve().parents[1]
PLAN33_RESOURCES = ROOT / "docs/plans/33-local-qwen-migration/resources"
SCHEMA_VERSION = 1
KIND = "neocortex-graph-sample"
DEFAULT_SAMPLE = 20

# A temporal pair survives only as one of these two edge types.
TEMPORAL_EDGE_TYPES = ("SUPERSEDES", "CORRECTS")

# search_path is set to the target schema by ``schema_scoped_connection``, so
# the tables are addressed unqualified and no schema name is interpolated into
# any statement.  Values always travel as $1, $2, ... parameters.
NODE_QUERY = """
    SELECT n.id AS id,
           nt.name AS type,
           char_length(n.name) AS name_length,
           char_length(n.content) AS content_length,
           CASE
               WHEN jsonb_typeof(coalesce(n.properties, '{}'::jsonb)) = 'object'
               THEN (SELECT count(*) FROM jsonb_object_keys(coalesce(n.properties, '{}'::jsonb)))
               ELSE 0
           END AS property_key_count,
           n.properties ->> '_source_episode' AS source_episode
    FROM node n
    JOIN node_type nt ON nt.id = n.type_id
    ORDER BY n.id ASC
"""

EDGE_QUERY = """
    SELECT e.id AS id,
           et.name AS type,
           e.source_id AS source_id,
           e.target_id AS target_id,
           e.weight AS weight,
           e.properties ->> '_source_episode' AS source_episode,
           (src.id IS NOT NULL AND tgt.id IS NOT NULL) AS endpoints_exist
    FROM edge e
    JOIN edge_type et ON et.id = e.type_id
    LEFT JOIN node src ON src.id = e.source_id
    LEFT JOIN node tgt ON tgt.id = e.target_id
    ORDER BY e.id ASC
"""

# Production writes a temporal edge new -> old (``oneshot_librarian._apply``
# passes ``source_id=bound[outcome.index]``, ``target_id=outcome.predecessor.id``
# and does not reverse it).  A *skipped* pair's logged orientation is whatever
# the relation carried, which is not guaranteed to match, so survival is checked
# in both directions.
SURVIVAL_QUERY = """
    SELECT count(*)::int AS matches
    FROM edge e
    JOIN edge_type et ON et.id = e.type_id
    WHERE et.name = ANY($3::text[])
      AND ((e.source_id = $1 AND e.target_id = $2)
        OR (e.source_id = $2 AND e.target_id = $1))
"""

SCHEMA_QUERY = """
    SELECT schema_name
    FROM information_schema.schemata
    WHERE schema_name ~ $1
    ORDER BY schema_name ASC
"""


class GraphSampleError(ValueError):
    """Raised when a sample cannot be taken safely or truthfully."""


class Fetcher(Protocol):
    """The only database capability this module uses."""

    async def fetch(self, query: str, *args: Any) -> Sequence[Mapping[str, Any]]: ...


# ── Pure selection and shaping ──


def select_sample(rows: Sequence[Any], sample_size: int) -> tuple[list[Any], dict[str, Any]]:
    """Pick ``sample_size`` rows deterministically from an id-ordered sequence.

    ``count <= sample_size`` takes every row and records a shortfall with the
    real count.  Otherwise the stride is ``count // sample_size`` and the sample
    is ``rows[0::stride][:sample_size]``.  Rows are never padded or repeated:
    a shortfall is the honest answer.
    """
    if sample_size < 1:
        raise GraphSampleError("sample size must be at least one row")
    count = len(rows)
    if count <= sample_size:
        return list(rows), {"count": count, "sampled": count, "shortfall": count < sample_size}
    stride = count // sample_size
    chosen = list(rows)[0::stride][:sample_size]
    return chosen, {"count": count, "sampled": len(chosen), "shortfall": False}


def _source_episode(value: Any) -> int | None:
    """Return the ``_source_episode`` property as an integer id, or null.

    The property is written as an episode row id.  Anything that is not an
    integer is not an episode id and could be arbitrary text, so it is dropped
    rather than published.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _type_name(value: Any) -> str:
    if not isinstance(value, str):
        raise GraphSampleError("type name is not a string")
    return value


def shape_node_row(schema: str, row: Mapping[str, Any]) -> dict[str, Any]:
    """Project one node onto publishable shape: lengths and counts only.

    ``type_valid`` uses ``normalization._VALID_NODE_TYPE`` — the regex the
    normalizer actually enforces — not the weaker length/uppercase check in
    ``extraction/schemas.py``, which accepts names the normalizer rejects.
    """
    type_name = _type_name(row["type"])
    return {
        "schema": schema,
        "id": row["id"],
        "type": type_name,
        "name_length": row["name_length"],
        "content_length": row["content_length"],
        "property_key_count": row["property_key_count"],
        "source_episode": _source_episode(row["source_episode"]),
        "type_valid": _VALID_NODE_TYPE.fullmatch(type_name) is not None,
    }


def shape_edge_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Project one edge onto publishable shape."""
    type_name = _type_name(row["type"])
    return {
        "id": row["id"],
        "type": type_name,
        "source_id": row["source_id"],
        "target_id": row["target_id"],
        "weight": row["weight"],
        "source_episode": _source_episode(row["source_episode"]),
        "endpoints_exist": bool(row["endpoints_exist"]),
        "type_valid": _VALID_EDGE_TYPE.fullmatch(type_name) is not None,
    }


def survival_query_args(source_id: int, target_id: int) -> tuple[str, tuple[Any, ...]]:
    """Return the parameterized survival query and its arguments for one pair."""
    return SURVIVAL_QUERY, (source_id, target_id, list(TEMPORAL_EDGE_TYPES))


def validate_schema_names(names: Sequence[str]) -> list[str]:
    """Return the schema names safe to address, refusing anything else."""
    safe: list[str] = []
    for name in names:
        if not isinstance(name, str) or not _VALID_SCHEMA_NAME.fullmatch(name):
            raise GraphSampleError(f"unsafe graph schema name: {name!r}")
        safe.append(name)
    return sorted(set(safe))


def metrics_schema_names(metrics: Mapping[str, Any]) -> list[str]:
    """Return the graph schemas a metrics document lists, or an empty list.

    ``compute_metrics.collect`` writes them as the keys of the ``schemas``
    object.  ``--merge`` nests the same payload under ``phases.<phase>``, so
    both layouts are read.
    """
    found: set[str] = set()
    payloads: list[Any] = [metrics]
    phases = metrics.get("phases")
    if isinstance(phases, dict):
        payloads.extend(phases.values())
    for payload in payloads:
        schemas = payload.get("schemas") if isinstance(payload, dict) else None
        if isinstance(schemas, dict):
            found.update(str(name) for name in schemas)
    return sorted(found)


# ── Database-facing collection (one injected connection per schema) ──


async def collect_schema_rows(conn: Fetcher, schema: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return every shaped node and edge row of one schema, ordered by id."""
    nodes = [shape_node_row(schema, row) for row in await conn.fetch(NODE_QUERY)]
    edges = [shape_edge_row(row) for row in await conn.fetch(EDGE_QUERY)]
    return nodes, edges


async def pair_survived(conn: Fetcher, source_id: int, target_id: int) -> bool:
    """Return whether a SUPERSEDES/CORRECTS edge joins the pair either way."""
    query, args = survival_query_args(source_id, target_id)
    rows = await conn.fetch(query, *args)
    return bool(rows) and int(rows[0]["matches"]) > 0


def apply_survival(document: Mapping[str, Any], survived: Mapping[int, bool]) -> dict[str, Any]:
    """Return a copy of a skip-events document with ``survived`` filled in.

    ``survived`` is keyed by the event's index in the document, so two events
    over the same pair keep their own answer.
    """
    events = document.get("events")
    if not isinstance(events, list) or not all(isinstance(event, Mapping) for event in events):
        return dict(document)
    event_rows = cast(list[Mapping[str, Any]], events)
    updated = []
    for index, event in enumerate(event_rows):
        row = dict(event)
        if row.get("reason_code") == "temporal_pair" and index in survived:
            row["survived"] = survived[index]
        updated.append(row)
    return {**document, "events": updated}


def temporal_pairs(document: Mapping[str, Any]) -> list[tuple[int, int, int]]:
    """Return ``(event_index, source_id, target_id)`` for checkable pairs."""
    events = document.get("events")
    if not isinstance(events, list) or not all(isinstance(event, Mapping) for event in events):
        return []
    event_rows = cast(list[Mapping[str, Any]], events)
    pairs = []
    for index, event in enumerate(event_rows):
        if event.get("reason_code") != "temporal_pair":
            continue
        source_id, target_id = event.get("source_id"), event.get("target_id")
        if isinstance(source_id, int) and isinstance(target_id, int):
            pairs.append((index, source_id, target_id))
    return pairs


def temporal_attribution_schema(schemas: Sequence[str]) -> str | None:
    """Return the sole graph a schema-less skip event can be attributed to."""
    return schemas[0] if len(schemas) == 1 else None


def write_survival_annotation(path: Path, document: Mapping[str, Any], survived: Mapping[int, bool]) -> dict[str, Any]:
    """Atomically annotate a skip-events artifact and return the written copy."""
    annotated = apply_survival(document, survived)
    _atomic_write_json(path, annotated)
    return annotated


def build_document(
    *,
    run_id: str,
    arm: str,
    schemas: Sequence[str],
    schema_source: str,
    sample_size: int,
    nodes: Sequence[dict[str, Any]],
    edges: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Assemble the graph-sample document from already-shaped rows."""
    node_sample, node_counts = select_sample(list(nodes), sample_size)
    edge_sample, edge_counts = select_sample(list(edges), sample_size)
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "run_id": run_id,
        "arm": arm,
        "status": "MEASURED",
        "schema_source": schema_source,
        "schemas": list(schemas),
        "requested": sample_size,
        "nodes": {**node_counts, "rows": node_sample},
        "edges": {**edge_counts, "rows": edge_sample},
    }


async def resolve_schemas(conn: Fetcher, arm: str, run_id: str | None = None) -> tuple[list[str], str]:
    """Return the schemas to sample and which source named them."""
    metrics_path = PLAN33_RESOURCES / f"metrics-{arm}.json"
    if metrics_path.is_file():
        try:
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GraphSampleError(f"metrics document cannot be read: {metrics_path.name}") from exc
        if isinstance(metrics, dict):
            metadata = metrics.get("run_metadata")
            metrics_run_id = metadata.get("run_id") if isinstance(metadata, dict) else None
            if run_id is not None and metrics_run_id != run_id:
                raise GraphSampleError("metrics document belongs to a different run")
            names = metrics_schema_names(metrics)
            if names:
                return validate_schema_names(names), "metrics"
    rows = await conn.fetch(SCHEMA_QUERY, _VALID_SCHEMA_NAME.pattern)
    return validate_schema_names([str(row["schema_name"]) for row in rows]), "information_schema"


async def run(
    *,
    run_id: str,
    arm: str,
    output: Path,
    sample_size: int,
    check_temporal: Path | None,
) -> dict[str, Any]:
    """Sample the live graph and, when asked, resolve temporal survival."""
    import asyncpg  # Imported here so the pure functions import without a driver.

    skip_document: dict[str, Any] | None = None
    if check_temporal is not None:
        skip_document = json.loads(check_temporal.read_text(encoding="utf-8"))
        if skip_document.get("run_id") != run_id or skip_document.get("arm") != arm:
            raise GraphSampleError("skip-events document belongs to a different run or arm")

    config = PostgresConfig()
    pool = await asyncpg.create_pool(config.dsn, min_size=1, max_size=2)
    if pool is None:  # pragma: no cover - asyncpg returns a pool or raises
        raise GraphSampleError("could not open a PostgreSQL connection pool")
    try:
        async with pool.acquire() as conn:
            schemas, schema_source = await resolve_schemas(conn, arm, run_id)
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        survived: dict[int, bool] = {}
        pairs = temporal_pairs(skip_document) if skip_document else []
        for schema in schemas:
            async with schema_scoped_connection(pool, schema) as conn:
                schema_nodes, schema_edges = await collect_schema_rows(conn, schema)
                nodes.extend(schema_nodes)
                edges.extend(schema_edges)
                # Skip events currently carry integer endpoints but no target
                # schema.  Those ids are only unambiguous when exactly one graph
                # was in scope; OR-ing matches across schemas can certify an
                # unrelated edge that happens to reuse the same numeric ids.
                # Multi-schema attribution therefore stays null until the audit
                # contract itself carries safe schema provenance.
                if temporal_attribution_schema(schemas) == schema:
                    for index, source_id, target_id in pairs:
                        survived[index] = await pair_survived(conn, source_id, target_id)
    finally:
        await pool.close()

    document = build_document(
        run_id=run_id,
        arm=arm,
        schemas=schemas,
        schema_source=schema_source,
        sample_size=sample_size,
        nodes=nodes,
        edges=edges,
    )
    _atomic_write_json(output, document)
    if skip_document is not None and check_temporal is not None:
        # The documented Stage 7 workflow annotates the same run artifact in
        # place.  The atomic writer replaces it only after the full updated JSON
        # exists, so an interrupted write cannot leave a partial evidence file.
        write_survival_annotation(check_temporal, skip_document, survived)
    return document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--arm", required=True)
    parser.add_argument("--check-temporal", type=Path)
    parser.add_argument("--sample", type=int, default=DEFAULT_SAMPLE)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        document = asyncio.run(
            run(
                run_id=args.run_id,
                arm=args.arm,
                output=args.output,
                sample_size=args.sample,
                check_temporal=args.check_temporal,
            )
        )
    except GraphSampleError as exc:
        print(f"graph sample refused: {exc}", file=sys.stderr)
        return 2
    print(f"{args.output} nodes={document['nodes']['sampled']} edges={document['edges']['sampled']}")
    return 0


__all__ = [
    "EDGE_QUERY",
    "NODE_QUERY",
    "SURVIVAL_QUERY",
    "TEMPORAL_EDGE_TYPES",
    "GraphSampleError",
    "apply_survival",
    "build_document",
    "collect_schema_rows",
    "metrics_schema_names",
    "pair_survived",
    "select_sample",
    "shape_edge_row",
    "shape_node_row",
    "survival_query_args",
    "temporal_attribution_schema",
    "temporal_pairs",
    "validate_schema_names",
    "write_survival_annotation",
]

if __name__ == "__main__":
    raise SystemExit(main())
