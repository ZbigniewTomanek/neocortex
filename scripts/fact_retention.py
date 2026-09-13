#!/usr/bin/env python3
"""Offline fact-retention scoring for the Qwen speed probe.

Scores a graph the probe just built against a committed fixture: did the graph
keep the scalar facts the source text stated, and did a later correction reach
node ``content``?  Nothing here contacts a model or a database; the input is an
already-built in-memory graph.

The plan's spec sketches ``score_episode(nodes, edges, fixture)``.  This module
takes a :class:`GraphView` instead, because :class:`neocortex.models.Edge`
carries ``type_id`` and not a type name, so recognising a ``SUPERSEDES`` or
``CORRECTS`` edge needs the type tables alongside the rows.  A ``GraphView`` is
the same information plus those two tables.

**Privacy.**  No function in this module returns, logs, or prints graph text,
episode text, or fact strings.  Results carry counts, booleans, and fixture
indices only, so a probe summary written from them stays free of model output.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from neocortex.models import Edge, Node

try:  # Direct ``python scripts/fact_retention.py`` invocation.
    from corpus_loader import load_corpus  # ty: ignore[unresolved-import]
except ModuleNotFoundError:  # Imported as ``scripts.fact_retention``.
    from scripts.corpus_loader import load_corpus  # ty: ignore[unresolved-import]

# Edge type names that count as a correction/supersession link, upper-cased.
TEMPORAL_EDGE_TYPES = frozenset({"SUPERSEDES", "CORRECTS"})
_TRIPLET_FIELDS = ("id", "initial_text", "update_text", "anchor_names", "new_tokens", "old_tokens")
_WHITESPACE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Lower-case, collapse whitespace runs to one space, strip.

    Applied identically to every needle and every haystack, so a fact only has
    to survive the graph's re-wrapping, not its spacing.
    """
    return _WHITESPACE.sub(" ", text).strip().lower()


@dataclass(frozen=True)
class GraphView:
    """A graph snapshot plus the type-id tables the edge rule needs."""

    nodes: list[Node]
    edges: list[Edge]
    node_type_names: dict[int, str]  # type_id -> name
    edge_type_names: dict[int, str]


@dataclass(frozen=True)
class EpisodeFixture:
    """The facts one compact episode's text stated."""

    key: str
    facts: tuple[str, ...]


@dataclass(frozen=True)
class SupersessionFixture:
    """One initial/update pair and the tokens that decide whether it landed."""

    id: str
    initial_text: str
    update_text: str
    anchor_names: tuple[str, ...]
    new_tokens: tuple[str, ...]
    old_tokens: tuple[str, ...]


@dataclass(frozen=True)
class ChainFixture:
    """How many temporal edges the ordered episode chain must produce."""

    episodes: tuple[str, ...]
    min_temporal_edges: int


@dataclass(frozen=True)
class Fixture:
    """The whole committed fixture file."""

    revision: int
    episodes: tuple[EpisodeFixture, ...]
    chain: ChainFixture | None
    supersession: tuple[SupersessionFixture, ...]

    def episode(self, key: str) -> EpisodeFixture | None:
        return next((entry for entry in self.episodes if entry.key == key), None)

    def triplet(self, triplet_id: str) -> SupersessionFixture | None:
        return next((entry for entry in self.supersession if entry.id == triplet_id), None)


@dataclass(frozen=True)
class FactScore:
    """How many of an episode's fixture facts survived into the graph."""

    facts_total: int
    facts_found: int
    missing_keys: list[int]  # fixture indices only, never fact text


@dataclass(frozen=True)
class SupersessionScore:
    """Whether a correction reached the anchor nodes' content."""

    new_present: bool
    old_absent: bool
    temporal_edge_present: bool


class _GraphSnapshotSource(Protocol):
    """Anything exposing ``InMemoryRepository.graph_snapshot``."""

    def graph_snapshot(self) -> tuple[list[Node], list[Edge], dict[int, str], dict[int, str]]: ...


def snapshot_graph(repo: _GraphSnapshotSource) -> GraphView:
    """Read an in-memory repository into a :class:`GraphView`."""
    nodes, edges, node_type_names, edge_type_names = repo.graph_snapshot()
    return GraphView(nodes=nodes, edges=edges, node_type_names=node_type_names, edge_type_names=edge_type_names)


def load_fixture(path: Path, *, corpus: list[dict[str, object]] | None = None) -> Fixture:
    """Load and validate the fact fixture against the compact corpus.

    Every ``facts[]`` entry must be a case-insensitive substring of its episode
    text after normalization.  A fact that is not is a fixture error, not a
    measurement: it would score zero forever and read as a model failure.

    Raises:
        ValueError: on an unknown episode key, a fact absent from its episode
            text, or a triplet missing a required field.  The message names the
            episode key and the fixture index, never the fact text.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = corpus if corpus is not None else load_corpus(profile="compact")
    texts = {f"E{int(str(record['number'])):02d}": normalize(str(record["text"])) for record in records}

    episodes: list[EpisodeFixture] = []
    for entry in payload.get("episodes", []):
        key = str(entry["key"])
        if key not in texts:
            raise ValueError(f"fact fixture: unknown episode key {key!r}")
        haystack = texts[key]
        facts = [str(fact) for fact in entry.get("facts", [])]
        for index, fact in enumerate(facts):
            if normalize(fact) not in haystack:
                raise ValueError(f"fact fixture: {key} facts[{index}] does not occur in the episode text")
        episodes.append(EpisodeFixture(key=key, facts=tuple(facts)))

    triplets: list[SupersessionFixture] = []
    for position, entry in enumerate(payload.get("supersession", [])):
        missing = [field for field in _TRIPLET_FIELDS if field not in entry]
        if missing:
            raise ValueError(f"fact fixture: supersession[{position}] is missing {sorted(missing)}")
        triplets.append(
            SupersessionFixture(
                id=str(entry["id"]),
                initial_text=str(entry["initial_text"]),
                update_text=str(entry["update_text"]),
                anchor_names=tuple(str(name) for name in entry["anchor_names"]),
                new_tokens=tuple(str(token) for token in entry["new_tokens"]),
                old_tokens=tuple(str(token) for token in entry["old_tokens"]),
            )
        )

    chain_payload = payload.get("chain")
    chain = (
        ChainFixture(
            episodes=tuple(str(key) for key in chain_payload["episodes"]),
            min_temporal_edges=int(chain_payload["min_temporal_edges"]),
        )
        if chain_payload
        else None
    )
    return Fixture(
        revision=int(payload.get("revision", 0)),
        episodes=tuple(episodes),
        chain=chain,
        supersession=tuple(triplets),
    )


def _node_haystacks(graph: GraphView) -> tuple[str, ...]:
    """Return each active node field as its own normalized search boundary."""
    parts: list[str] = []
    for node in graph.nodes:
        if node.forgotten:
            continue
        parts.append(node.name)
        parts.append(node.content or "")
        parts.extend(str(value) for value in (node.properties or {}).values())
    return tuple(normalize(part) for part in parts if part)


def score_episode(graph: GraphView, episode: EpisodeFixture) -> FactScore:
    """Count the fixture facts that survived anywhere in the graph.

    Facts are deduplicated by fixture index, so one fact listed twice cannot be
    counted twice.
    """
    haystacks = _node_haystacks(graph)
    missing = [
        index
        for index, fact in enumerate(episode.facts)
        if not any(normalize(fact) in haystack for haystack in haystacks)
    ]
    return FactScore(
        facts_total=len(episode.facts),
        facts_found=len(episode.facts) - len(missing),
        missing_keys=missing,
    )


def _anchor_nodes(graph: GraphView, anchor_names: tuple[str, ...]) -> list[Node]:
    anchors = [normalize(name) for name in anchor_names]
    return [
        node for node in graph.nodes if not node.forgotten and any(anchor in normalize(node.name) for anchor in anchors)
    ]


def count_temporal_edges(graph: GraphView) -> int:
    """Count ``SUPERSEDES``/``CORRECTS`` edges anywhere in the graph."""
    return sum(1 for edge in graph.edges if graph.edge_type_names.get(edge.type_id, "").upper() in TEMPORAL_EDGE_TYPES)


def score_supersession(graph: GraphView, triplet: SupersessionFixture) -> SupersessionScore:
    """Score the E2E supersession conditions on an offline graph.

    The anchor text is the anchor nodes' ``content`` only — not ``name``, not
    ``properties``.  This exactly mirrors the S05 and S07 content checks.  It is
    only an approximation for S11: the real E2E check ranks recalled content
    using embeddings, while this offline probe has embeddings disabled.

    With no anchor node at all the result is
    ``new_present=False, old_absent=True, temporal_edge_present=False``: a
    missing anchor must never read as a pass on ``new_present``.
    """
    anchors = _anchor_nodes(graph, triplet.anchor_names)
    anchor_text = normalize(" ".join(node.content or "" for node in anchors))
    anchor_ids = {node.id for node in anchors}
    temporal = any(
        graph.edge_type_names.get(edge.type_id, "").upper() in TEMPORAL_EDGE_TYPES
        and (edge.source_id in anchor_ids or edge.target_id in anchor_ids)
        for edge in graph.edges
    )
    return SupersessionScore(
        new_present=any(normalize(token) in anchor_text for token in triplet.new_tokens),
        old_absent=not any(normalize(token) in anchor_text for token in triplet.old_tokens),
        temporal_edge_present=temporal,
    )


def _main(argv: list[str] | None = None) -> int:
    """Validate a fixture file against the compact corpus and print counts only."""
    import argparse

    parser = argparse.ArgumentParser(description="Validate a fact fixture against the compact corpus.")
    parser.add_argument("fixture", type=Path)
    args = parser.parse_args(argv)
    fixture = load_fixture(args.fixture)
    counts: dict[str, Any] = {
        "revision": fixture.revision,
        "episodes": {entry.key: len(entry.facts) for entry in fixture.episodes},
        "supersession": [entry.id for entry in fixture.supersession],
    }
    print(json.dumps(counts, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
