"""Deterministic tests for the offline fact-retention scorer.

Every graph here is built by hand: no pipeline run, no model, no database.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from scripts import fact_retention as fr  # ty: ignore[unresolved-import]
from scripts.corpus_loader import load_corpus  # ty: ignore[unresolved-import]

from neocortex.models import Edge, Node

FIXTURE_PATH = Path(__file__).resolve().parents[2] / "docs/plans/34-qwen-thinking-benchmark/resources/fact-fixture.json"
NOW = datetime(2026, 9, 11, tzinfo=UTC)


def _node(
    node_id: int, name: str, content: str = "", *, properties: dict | None = None, forgotten: bool = False
) -> Node:
    return Node(
        id=node_id,
        type_id=1,
        name=name,
        content=content,
        properties=properties or {},
        forgotten=forgotten,
        created_at=NOW,
        updated_at=NOW,
    )


def _edge(edge_id: int, source_id: int, target_id: int, type_id: int) -> Edge:
    return Edge(id=edge_id, source_id=source_id, target_id=target_id, type_id=type_id, created_at=NOW)


def _view(nodes: list[Node], edges: list[Edge] | None = None, edge_types: dict[int, str] | None = None) -> fr.GraphView:
    return fr.GraphView(
        nodes=nodes,
        edges=edges or [],
        node_type_names={1: "Concept"},
        edge_type_names=edge_types or {},
    )


def _compact_text(key: str) -> str:
    records = {f"E{int(str(record['number'])):02d}": str(record["text"]) for record in load_corpus(profile="compact")}
    return records[key]


def _committed_fixture() -> fr.Fixture:
    return fr.load_fixture(FIXTURE_PATH)


# ── Episode scoring ──


def test_full_graph_scores_every_fact() -> None:
    """A node holding the whole episode text keeps every fixture fact."""
    fixture = _committed_fixture()
    episode = fixture.episode("E04")
    assert episode is not None

    score = fr.score_episode(_view([_node(1, "Stage 1", _compact_text("E04"))]), episode)

    assert score.facts_total == len(episode.facts)
    assert score.facts_found == score.facts_total
    assert score.missing_keys == []


def test_removing_one_fact_lowers_facts_found_by_exactly_one() -> None:
    """The mutation case: a scorer that returns full marks regardless must fail here."""
    fixture = _committed_fixture()
    episode = fixture.episode("E04")
    assert episode is not None
    dropped = "Libpostal"
    index = list(episode.facts).index(dropped)
    text = _compact_text("E04")
    assert text.count(dropped) == 1
    mutated = text.replace(dropped, "")

    full = fr.score_episode(_view([_node(1, "Stage 1", text)]), episode)
    score = fr.score_episode(_view([_node(1, "Stage 1", mutated)]), episode)

    assert score.facts_found == full.facts_found - 1
    assert score.missing_keys == [index]


def test_facts_match_over_name_content_and_properties() -> None:
    """The haystack spans node name, content, and stringified property values."""
    episode = fr.EpisodeFixture(key="E04", facts=("Libpostal", "E.164", "252M entities"))
    nodes = [
        _node(1, "Libpostal"),
        _node(2, "phones", "normalized to E.164 format"),
        _node(3, "scale", properties={"volume": "252M entities"}),
    ]

    assert fr.score_episode(_view(nodes), episode).missing_keys == []


def test_forgotten_nodes_do_not_contribute_facts() -> None:
    """A forgotten node is not part of the graph the probe scores."""
    episode = fr.EpisodeFixture(key="E04", facts=("Libpostal",))

    score = fr.score_episode(_view([_node(1, "addresses", "Libpostal normalization", forgotten=True)]), episode)

    assert score == fr.FactScore(facts_total=1, facts_found=0, missing_keys=[0])


def test_a_fact_listed_twice_is_counted_once_per_index() -> None:
    """Deduplication is by fixture index, so a repeated fact cannot inflate the score."""
    episode = fr.EpisodeFixture(key="E04", facts=("Libpostal", "Libpostal"))

    score = fr.score_episode(_view([_node(1, "addresses", "Libpostal normalization")]), episode)

    assert score.facts_total == 2
    assert score.facts_found == 2
    assert score.missing_keys == []


# ── Supersession scoring ──


def _triplet() -> fr.SupersessionFixture:
    return fr.SupersessionFixture(
        id="S05",
        initial_text="initial",
        update_text="update",
        anchor_names=("zenith",),
        new_tokens=("may 1", "may"),
        old_tokens=("april 15", "april"),
    )


def test_stale_value_only_means_the_update_never_landed() -> None:
    graph = _view([_node(1, "Project Zenith", "The deadline is April 15, 2026.")])

    score = fr.score_supersession(graph, _triplet())

    assert score.new_present is False
    assert score.old_absent is False


def test_both_values_present_means_old_absent_is_false() -> None:
    graph = _view([_node(1, "Project Zenith", "Deadline moved from April 15 to May 1, 2026.")])

    score = fr.score_supersession(graph, _triplet())

    assert score.new_present is True
    assert score.old_absent is False


def test_new_value_only_is_a_clean_supersession() -> None:
    graph = _view([_node(1, "Project Zenith", "The deadline is May 1, 2026.")])

    score = fr.score_supersession(graph, _triplet())

    assert score.new_present is True
    assert score.old_absent is True


def test_missing_anchor_is_not_a_vacuous_pass() -> None:
    """No anchor node must never read as a pass on new_present."""
    graph = _view([_node(1, "Unrelated project", "The deadline is May 1, 2026.")])

    score = fr.score_supersession(graph, _triplet())

    assert score.new_present is False
    assert score.old_absent is True
    assert score.temporal_edge_present is False


def test_anchor_text_ignores_name_and_properties() -> None:
    """Only anchor ``content`` counts, matching what the E2E children assert on."""
    graph = _view([_node(1, "Project Zenith May 1", "", properties={"deadline": "May 1, 2026"})])

    assert fr.score_supersession(graph, _triplet()).new_present is False


def test_empty_old_tokens_make_old_absent_vacuously_true() -> None:
    triplet = fr.SupersessionFixture(
        id="S07",
        initial_text="initial",
        update_text="update",
        anchor_names=("dataforge",),
        new_tokens=("94.2",),
        old_tokens=(),
    )
    graph = _view([_node(1, "DataForge", "precision was previously 87%")])

    score = fr.score_supersession(graph, triplet)

    assert score.new_present is False
    assert score.old_absent is True


@pytest.mark.parametrize(
    ("type_name", "expected"),
    [("SUPERSEDES", True), ("CORRECTS", True), ("RELATES_TO", False)],
)
def test_temporal_edge_present_only_for_supersedes_or_corrects(type_name: str, expected: bool) -> None:
    nodes = [_node(1, "Project Zenith", "deadline May 1"), _node(2, "Deadline note", "old value")]
    graph = _view(nodes, [_edge(1, 2, 1, 7)], edge_types={7: type_name})

    assert fr.score_supersession(graph, _triplet()).temporal_edge_present is expected


def test_temporal_edge_must_touch_an_anchor() -> None:
    nodes = [_node(1, "Project Zenith", "deadline May 1"), _node(2, "Note A", ""), _node(3, "Note B", "")]
    graph = _view(nodes, [_edge(1, 2, 3, 7)], edge_types={7: "SUPERSEDES"})

    assert fr.score_supersession(graph, _triplet()).temporal_edge_present is False


def test_count_temporal_edges_counts_graph_wide() -> None:
    graph = _view(
        [_node(1, "A"), _node(2, "B")],
        [_edge(1, 1, 2, 7), _edge(2, 2, 1, 8), _edge(3, 1, 2, 7)],
        edge_types={7: "SUPERSEDES", 8: "RELATES_TO"},
    )

    assert fr.count_temporal_edges(graph) == 2


# ── Fixture loading ──


def test_load_fixture_accepts_the_committed_fixture() -> None:
    """The committed fixture's own regression test against the real compact corpus."""
    fixture = _committed_fixture()

    assert fixture.revision == 1
    assert [entry.key for entry in fixture.episodes] == ["E02", "E04", "E05", "E10", "E18", "E20", "E26", "E27"]
    assert [entry.id for entry in fixture.supersession] == ["S05", "S11", "S07"]
    assert fixture.chain is not None
    assert fixture.chain.episodes == ("E18", "E20", "E26")
    assert fixture.chain.min_temporal_edges == 1
    assert all(entry.facts for entry in fixture.episodes)


def test_load_fixture_rejects_a_fact_absent_from_its_episode(tmp_path: Path) -> None:
    """The message names the episode key and the index, never the fact text."""
    secret = "a fact the corpus never states"
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"revision": 1, "episodes": [{"key": "E04", "facts": [secret]}]}), encoding="utf-8")

    with pytest.raises(ValueError) as caught:
        fr.load_fixture(path)

    message = str(caught.value)
    assert "E04" in message
    assert "facts[0]" in message
    assert secret not in message


def test_load_fixture_rejects_an_unknown_episode_key(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"revision": 1, "episodes": [{"key": "E99", "facts": []}]}), encoding="utf-8")

    with pytest.raises(ValueError, match="E99"):
        fr.load_fixture(path)


def test_load_fixture_rejects_a_triplet_missing_a_field(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(
        json.dumps({"revision": 1, "episodes": [], "supersession": [{"id": "S05", "initial_text": "x"}]}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="supersession\\[0\\]"):
        fr.load_fixture(path)


# ── Privacy ──


def test_scores_serialize_to_counts_and_indices_only() -> None:
    """No graph text, episode text, or fact string may reach a probe row."""
    from dataclasses import asdict

    fixture = _committed_fixture()
    episode = fixture.episode("E04")
    triplet = fixture.triplet("S05")
    assert episode is not None and triplet is not None
    graph = _view([_node(1, "Project Zenith", _compact_text("E04") + " deadline May 1")])

    fact_payload = asdict(fr.score_episode(graph, episode))
    supersession_payload = asdict(fr.score_supersession(graph, triplet))

    assert set(fact_payload) == {"facts_total", "facts_found", "missing_keys"}
    assert isinstance(fact_payload["facts_total"], int)
    assert isinstance(fact_payload["facts_found"], int)
    assert all(isinstance(index, int) for index in fact_payload["missing_keys"])
    assert set(supersession_payload) == {"new_present", "old_absent", "temporal_edge_present"}
    assert all(isinstance(value, bool) for value in supersession_payload.values())
    # Serializable and free of text: json.dumps over both payloads holds no letters
    # from the graph beyond the field names themselves.
    dumped = json.dumps({"fact_score": fact_payload, "supersession": supersession_payload})
    assert "Zenith" not in dumped
    assert "Libpostal" not in dumped
