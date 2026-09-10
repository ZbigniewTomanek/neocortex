from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/probe_librarian_trajectory.py"
SPEC = importlib.util.spec_from_file_location("probe_librarian_trajectory", SCRIPT)
assert SPEC and SPEC.loader
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def test_fixed_fixture_and_episode_selection() -> None:
    fixture = probe.validate_fixture()
    assert [row["episode_key"] for row in fixture["episodes"]] == ["E04", "E05"]
    assert [row["number"] for row in probe.select_probe_episodes()] == [4, 5]


def test_provider_call_minimum_and_material_ceiling() -> None:
    assert probe.provider_call_minimum(42, 0, 41) == 18
    assert probe.provider_call_minimum(42, 42, 41) == 24
    base = {
        "repeat": 1,
        "status": "completed",
        "max_read_streak": 0,
        "duplicate_calls": 0,
        "hard_budget_events": 0,
        "outcome_assertions_failed": 0,
        "validation_rejections": 0,
        "idempotence_duplicate_count": 0,
    }
    rows = [
        {**base, "arm": "A0", "episode_key": "E04", "provider_tool_calls": 51, "requests": 51},
        {**base, "arm": "A0", "episode_key": "E05", "provider_tool_calls": 51, "requests": 51},
        {
            **base,
            "arm": "A2",
            "episode_key": "E04",
            "provider_tool_calls": 35,
            "requests": 35,
            "provider_call_minimum": 9,
        },
        {
            **base,
            "arm": "A2",
            "episode_key": "E05",
            "provider_tool_calls": 36,
            "requests": 36,
            "provider_call_minimum": 9,
        },
    ]
    assert probe.evaluate_material_improvement(rows)["status"] == "PASS"
    rows[-1]["provider_tool_calls"] = 37
    assert probe.evaluate_material_improvement(rows)["status"] == "FAIL"


def _passing_rows() -> list[dict[str, object]]:
    base = {
        "repeat": 1,
        "status": "completed",
        "max_read_streak": 0,
        "duplicate_calls": 0,
        "hard_budget_events": 0,
        "outcome_assertions_failed": 0,
        "validation_rejections": 0,
        "idempotence_duplicate_count": 0,
    }
    return [
        {**base, "arm": "A0", "episode_key": "E04", "provider_tool_calls": 51, "requests": 51},
        {**base, "arm": "A0", "episode_key": "E05", "provider_tool_calls": 51, "requests": 51},
        {
            **base,
            "arm": "A2",
            "episode_key": "E04",
            "provider_tool_calls": 35,
            "requests": 35,
            "provider_call_minimum": 9,
        },
        {
            **base,
            "arm": "A2",
            "episode_key": "E05",
            "provider_tool_calls": 36,
            "requests": 36,
            "provider_call_minimum": 9,
        },
    ]


def test_validation_rejections_cannot_increase() -> None:
    rows = _passing_rows()
    rows[-1]["validation_rejections"] = 1
    assert probe.evaluate_material_improvement(rows)["status"] == "FAIL"


def test_failed_or_timed_out_arm_is_ineligible_without_usage_crash() -> None:
    rows = _passing_rows()
    rows[-1].update({"status": "timeout", "provider_tool_calls": 0, "requests": 0})
    assert probe.evaluate_material_improvement(rows) == {
        "status": "NOT_MEASURED",
        "reason": "paired arm failed, timed out, or lacks numeric usage",
    }


def test_unknown_tool_names_are_redacted_and_counted() -> None:
    counts = probe._safe_tool_counts(["resolve_entities", "copied private source text"])
    assert counts == {"resolve_entities": 1, "unknown": 1}
    assert "private" not in str(counts)


def test_safe_tool_allow_list_is_exactly_the_three_librarian_profiles() -> None:
    assert {
        "archive_node",
        "create_or_update_edge",
        "create_or_update_node",
        "find_node_by_name",
        "find_similar_nodes",
        "get_edges_between",
        "inspect_node_neighborhood",
        "remove_edge",
        "search_existing_nodes",
        "apply_entity_decisions",
        "apply_relation_decisions",
        "check_relations",
        "read_entity_details",
        "resolve_entities",
    } == probe.SAFE_TOOL_NAMES


def test_observed_fact_hashes_require_exact_subject_predicate_and_object() -> None:
    graph = {
        "nodes": [{"id": 1, "name": "organization atomic features", "properties": {"count": 27}}],
        "edges": [],
        "node_types": [],
        "edge_types": [],
    }
    exact = {
        "episode_key": "E05",
        "kind": "quantitative_update",
        "subject": "organization atomic features",
        "predicate": "count",
        "object": "27",
    }
    wrong = {**exact, "predicate": "unrelated"}
    hashes = probe._observed_fact_hashes("E05", graph)
    assert probe.hashlib.sha256(probe.canonical_expectation(exact)).hexdigest() in hashes
    assert probe.hashlib.sha256(probe.canonical_expectation(wrong)).hexdigest() not in hashes


def test_source_manifest_hashes_tracked_and_untracked() -> None:
    _revision, digest, files = probe._source_identity()
    by_name = {row["path"]: row["sha256"] for row in files}
    assert "scripts/probe_librarian_trajectory.py" in by_name
    assert by_name["scripts/probe_librarian_trajectory.py"] == probe.sha256_file(SCRIPT)
    assert len(digest) == 64


def test_probe_uses_postgresql_target_schemas_and_measured_embedding_service() -> None:
    source = SCRIPT.read_text()
    assert "InMemoryRepository" not in source
    assert "create_services(settings)" in source
    assert "target_schema=target_schema" in source
    assert 'await embeddings.embed("neocortex fixed librarian trajectory probe")' in source
    assert '"vector_dimension": 768' not in source
