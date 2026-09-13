"""Graph-sample export: deterministic selection, shortfalls, and temporal survival.

The whole selection and shaping path runs against a fake connection whose only
capability is ``await conn.fetch(query, *args)``.  No PostgreSQL is started;
Stage 7 is the first time this code meets a database.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from scripts import export_graph_sample as sampler  # ty: ignore[unresolved-import]

from neocortex.extraction.schemas import ProposedEdgeType, ProposedNodeType

ROOT = Path(__file__).parents[2]
SCHEMA_PATH = ROOT / "docs/plans/34-qwen-thinking-benchmark/resources/quality-sample-tuned.schema.json"
SCHEMA_NAME = "ncx_admin__personal"


class FakeConnection:
    """A connection stand-in used only as ``await conn.fetch(query, *args)``.

    ``survival`` models PostgreSQL evaluating ``SURVIVAL_QUERY`` over a set of
    directed, typed edges: a pair matches in either orientation.  The query text
    itself is asserted separately, so the both-direction rule is checked against
    the SQL and not only against this model.
    """

    def __init__(
        self,
        *,
        nodes: list[dict[str, Any]] | None = None,
        edges: list[dict[str, Any]] | None = None,
        schemas: list[str] | None = None,
        survival: set[tuple[int, int, str]] | None = None,
    ) -> None:
        self.nodes = nodes or []
        self.edges = edges or []
        self.schemas = schemas or []
        self.survival = survival or set()
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        self.calls.append((query, args))
        if query == sampler.NODE_QUERY:
            return list(self.nodes)
        if query == sampler.EDGE_QUERY:
            return list(self.edges)
        if query == sampler.SCHEMA_QUERY:
            return [{"schema_name": name} for name in self.schemas]
        if query == sampler.SURVIVAL_QUERY:
            source, target, types = args
            matches = sum(
                1
                for (stored_source, stored_target, edge_type) in self.survival
                if edge_type in types
                and {stored_source, stored_target} == {source, target}
                and stored_source != stored_target
            )
            return [{"matches": matches}]
        raise AssertionError(f"unexpected query: {query!r}")


def _node(index: int, *, type_name: str = "Concept", episode: int | None = 5) -> dict[str, Any]:
    return {
        "id": index,
        "type": type_name,
        "name_length": 10 + index,
        "content_length": 100 + index,
        "property_key_count": 2,
        "source_episode": None if episode is None else str(episode),
    }


def _edge(index: int, *, type_name: str = "RELATES_TO") -> dict[str, Any]:
    return {
        "id": 1000 + index,
        "type": type_name,
        "source_id": index,
        "target_id": index + 1,
        "weight": 1.0,
        "source_episode": "5",
        "endpoints_exist": True,
    }


def _validate_schema(document: dict[str, Any]) -> None:
    schema = json.loads(SCHEMA_PATH.read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(document)


async def _collect(conn: FakeConnection) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return await sampler.collect_schema_rows(conn, SCHEMA_NAME)


# ── Deterministic selection ──


async def test_twenty_five_nodes_and_thirty_edges_yield_a_stable_twenty_twenty() -> None:
    conn = FakeConnection(nodes=[_node(i) for i in range(1, 26)], edges=[_edge(i) for i in range(1, 31)])
    nodes, edges = await _collect(conn)
    first = sampler.build_document(
        run_id="r", arm="a", schemas=[SCHEMA_NAME], schema_source="metrics", sample_size=20, nodes=nodes, edges=edges
    )

    assert first["nodes"]["sampled"] == 20 and first["edges"]["sampled"] == 20
    assert first["nodes"]["count"] == 25 and first["edges"]["count"] == 30
    assert first["nodes"]["shortfall"] is False and first["edges"]["shortfall"] is False

    nodes_again, edges_again = await _collect(conn)
    second = sampler.build_document(
        run_id="r",
        arm="a",
        schemas=[SCHEMA_NAME],
        schema_source="metrics",
        sample_size=20,
        nodes=nodes_again,
        edges=edges_again,
    )
    assert [row["id"] for row in second["nodes"]["rows"]] == [row["id"] for row in first["nodes"]["rows"]]
    assert [row["id"] for row in second["edges"]["rows"]] == [row["id"] for row in first["edges"]["rows"]]
    _validate_schema(first)


def test_the_stride_spreads_the_sample_across_a_large_graph() -> None:
    rows = list(range(1, 101))
    chosen, counts = sampler.select_sample(rows, 20)
    # stride = 100 // 20 = 5, so the sample walks the whole id range.
    assert chosen == list(range(1, 100, 5))
    assert counts == {"count": 100, "sampled": 20, "shortfall": False}


async def test_seven_edges_are_reported_as_a_shortfall_and_never_padded() -> None:
    conn = FakeConnection(nodes=[_node(i) for i in range(1, 4)], edges=[_edge(i) for i in range(1, 8)])
    nodes, edges = await _collect(conn)
    document = sampler.build_document(
        run_id="r", arm="a", schemas=[SCHEMA_NAME], schema_source="metrics", sample_size=20, nodes=nodes, edges=edges
    )

    assert document["edges"]["count"] == 7
    assert document["edges"]["sampled"] == 7
    assert document["edges"]["shortfall"] is True
    assert len(document["edges"]["rows"]) == 7
    assert document["nodes"]["count"] == 3 and document["nodes"]["shortfall"] is True
    _validate_schema(document)


# ── Shaping and privacy ──


async def test_rows_carry_lengths_and_counts_but_no_text() -> None:
    conn = FakeConnection(nodes=[_node(1)], edges=[_edge(1)])
    nodes, edges = await _collect(conn)

    assert nodes[0] == {
        "schema": SCHEMA_NAME,
        "id": 1,
        "type": "Concept",
        "name_length": 11,
        "content_length": 101,
        "property_key_count": 2,
        "source_episode": 5,
        "type_valid": True,
    }
    assert edges[0] == {
        "id": 1001,
        "type": "RELATES_TO",
        "source_id": 1,
        "target_id": 2,
        "weight": 1.0,
        "source_episode": 5,
        "endpoints_exist": True,
        "type_valid": True,
    }
    # Nothing that could carry graph text is even selected by the queries.
    for query in (sampler.NODE_QUERY, sampler.EDGE_QUERY):
        assert "n.name," not in query and "n.content," not in query


async def test_a_non_integer_source_episode_is_dropped_rather_than_published() -> None:
    conn = FakeConnection(nodes=[{**_node(1), "source_episode": "episode about Jonas Weber"}])
    nodes, _edges = await _collect(conn)
    assert nodes[0]["source_episode"] is None


@pytest.mark.parametrize(
    ("node_type", "edge_type"),
    [("Drug Interaction", "Relates_To")],
)
def test_type_valid_uses_the_normalizer_regex_not_the_weaker_schema_check(node_type: str, edge_type: str) -> None:
    # The extraction schema accepts both names: they are short and start with
    # an uppercase letter.  The normalizer rejects both, so a sample built on
    # the weaker check would report a clean graph that the normalizer refuses.
    assert ProposedNodeType(name=node_type).name == node_type
    assert ProposedEdgeType(name=edge_type).name == edge_type

    node_row = sampler.shape_node_row(SCHEMA_NAME, _node(1, type_name=node_type))
    edge_row = sampler.shape_edge_row(_edge(1, type_name=edge_type))
    assert node_row["type_valid"] is False
    assert edge_row["type_valid"] is False
    assert sampler.shape_node_row(SCHEMA_NAME, _node(1))["type_valid"] is True
    assert sampler.shape_edge_row(_edge(1))["type_valid"] is True


# ── Schema resolution ──


def test_the_metrics_schemas_key_supplies_the_schema_list() -> None:
    flat = {"schemas": {"ncx_shared__knowledge": {}, "ncx_admin__personal": {}}}
    assert sampler.metrics_schema_names(flat) == ["ncx_admin__personal", "ncx_shared__knowledge"]
    merged = {"phases": {"corpus": {"schemas": {"ncx_admin__personal": {}}}}}
    assert sampler.metrics_schema_names(merged) == ["ncx_admin__personal"]
    assert sampler.metrics_schema_names({"run_metadata": {}}) == []


def test_an_unsafe_schema_name_never_reaches_sql() -> None:
    with pytest.raises(sampler.GraphSampleError, match="unsafe graph schema name"):
        sampler.validate_schema_names(['ncx_admin__personal"; DROP SCHEMA public CASCADE --'])


async def test_the_information_schema_fallback_reports_its_own_source() -> None:
    conn = FakeConnection(schemas=["ncx_admin__personal", "public"])
    with pytest.raises(sampler.GraphSampleError):
        # ``public`` is not a graph schema and must be refused, not silently
        # dropped: a silent drop would hide a misconfigured database.
        await sampler.resolve_schemas(conn, "arm-with-no-metrics-file")

    conn = FakeConnection(schemas=["ncx_admin__personal"])
    names, source = await sampler.resolve_schemas(conn, "arm-with-no-metrics-file")
    assert names == ["ncx_admin__personal"]
    assert source == "information_schema"
    assert conn.calls[-1] == (sampler.SCHEMA_QUERY, ("^ncx_[a-z0-9]+__[a-z0-9_]+$",))


async def test_metrics_for_another_run_are_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    resources = tmp_path / "resources"
    resources.mkdir()
    (resources / "metrics-arm.json").write_text(json.dumps({"run_metadata": {"run_id": "other"}, "schemas": {}}))
    monkeypatch.setattr(sampler, "PLAN33_RESOURCES", resources)
    with pytest.raises(sampler.GraphSampleError, match="different run"):
        await sampler.resolve_schemas(FakeConnection(), "arm", "wanted")


# ── Temporal survival ──


def test_the_survival_query_checks_both_orientations() -> None:
    query, args = sampler.survival_query_args(21, 22)
    assert args == (21, 22, ["SUPERSEDES", "CORRECTS"])
    assert "e.source_id = $1 AND e.target_id = $2" in query
    assert "e.source_id = $2 AND e.target_id = $1" in query


async def test_check_temporal_marks_survived_for_an_edge_in_the_reverse_direction() -> None:
    # The librarian writes temporal edges new -> old; the skipped pair was
    # logged old -> new, so only a both-direction check finds it.
    document = {
        "schema_version": 1,
        "kind": "neocortex-skip-events",
        "status": "MEASURED",
        "events": [
            {"reason_code": "temporal_pair", "source_id": 21, "target_id": 22, "survived": None},
            {"reason_code": "temporal_pair", "source_id": 31, "target_id": 32, "survived": None},
            {"reason_code": "missing_node", "source_id": 41, "target_id": None},
        ],
    }
    conn = FakeConnection(survival={(22, 21, "SUPERSEDES")})

    survived = {}
    for index, source_id, target_id in sampler.temporal_pairs(document):
        survived[index] = await sampler.pair_survived(conn, source_id, target_id)
    updated = sampler.apply_survival(document, survived)

    assert updated["events"][0]["survived"] is True
    assert updated["events"][1]["survived"] is False
    assert "survived" not in updated["events"][2]
    # The input document is not mutated in place.
    assert document["events"][0]["survived"] is None


async def test_an_unchecked_pair_stays_null_rather_than_false() -> None:
    document = {"events": [{"reason_code": "temporal_pair", "source_id": 1, "target_id": 2, "survived": None}]}
    assert sampler.apply_survival(document, {})["events"][0]["survived"] is None


def test_cross_schema_temporal_attribution_stays_unresolved() -> None:
    """An edge in another graph with colliding ids must never certify survival."""
    document = {"events": [{"reason_code": "temporal_pair", "source_id": 1, "target_id": 2, "survived": None}]}
    assert sampler.temporal_attribution_schema([SCHEMA_NAME, "ncx_shared__knowledge"]) is None
    assert sampler.temporal_attribution_schema([SCHEMA_NAME]) == SCHEMA_NAME
    # ``run`` deliberately leaves its survival map empty whenever attribution
    # is ambiguous.  The update represents that as null, never false or true.
    assert sampler.apply_survival(document, {})["events"][0]["survived"] is None


def test_documented_same_path_annotation_is_atomic_and_runnable(tmp_path: Path) -> None:
    path = tmp_path / "skip-events-arm-run.json"
    document = {
        "run_id": "run",
        "arm": "arm",
        "events": [{"reason_code": "temporal_pair", "source_id": 1, "target_id": 2, "survived": None}],
    }
    path.write_text(json.dumps(document))
    written = sampler.write_survival_annotation(path, document, {0: True})
    assert written["events"][0]["survived"] is True
    assert json.loads(path.read_text()) == written
