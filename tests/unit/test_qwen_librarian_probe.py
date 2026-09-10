from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic_ai.messages import RetryPromptPart, ToolCallPart
from pydantic_ai.usage import RunUsage

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


def test_bounded_probe_prompt_requires_end_to_end_micro_batches() -> None:
    prompt = probe._bounded_prompt(30, 33, idempotence=True)
    assert "entity indices in ascending micro-batches of at most 8" in prompt
    assert "immediately decide every index" in prompt
    assert "code-owned allowed_decisions" in prompt
    assert "relation indices in ascending micro-batches of at most 8" in prompt
    base = {
        "repeat": 1,
        "status": "completed",
        "max_read_streak": 0,
        "duplicate_calls": 0,
        "hard_budget_events": 0,
        "outcome_assertions_failed": 0,
        "validation_rejections": 0,
        "idempotence_duplicate_count": 0,
        "idempotence_status": "completed",
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
        "idempotence_status": "completed",
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


def test_failed_a2_is_ineligible_without_usage_crash() -> None:
    rows = _passing_rows()
    rows[-1].update({"status": "timeout", "provider_tool_calls": 0, "requests": 0})
    assert probe.evaluate_material_improvement(rows) == {
        "status": "NOT_MEASURED",
        "reason": "paired arm failed or lacks eligible numeric usage",
    }


def test_timed_out_a0_numeric_usage_is_a_conservative_lower_bound() -> None:
    rows = _passing_rows()
    rows[0]["status"] = "timeout"
    rows[1]["status"] = "timeout"
    gate = probe.evaluate_material_improvement(rows)
    assert gate == {
        "status": "PASS",
        "minimum": 18,
        "tool_ceiling": 71,
        "request_ceiling": 71,
        "a0_timeout_lower_bounds": 2,
    }

    rows[0]["provider_tool_calls"] = 50
    rows[1]["provider_tool_calls"] = 50
    assert probe.evaluate_material_improvement(rows)["status"] == "FAIL"


def test_failed_a0_and_nonnumeric_timeout_usage_remain_ineligible() -> None:
    rows = _passing_rows()
    rows[0]["status"] = "failed"
    assert probe.evaluate_material_improvement(rows)["status"] == "NOT_MEASURED"
    rows[0]["status"] = "timeout"
    rows[0]["requests"] = "NOT_MEASURED"
    assert probe.evaluate_material_improvement(rows)["status"] == "NOT_MEASURED"


def test_a1_status_does_not_affect_material_gate() -> None:
    rows = _passing_rows()
    rows.extend(
        [
            {"arm": "A1", "episode_key": "E04", "repeat": 1, "status": "timeout"},
            {"arm": "A1", "episode_key": "E05", "repeat": 1, "status": "failed"},
        ]
    )
    assert probe.evaluate_material_improvement(rows)["status"] == "PASS"


def test_unknown_tool_names_are_redacted_and_counted() -> None:
    counts = probe._safe_tool_counts(["resolve_entities", "copied private source text"])
    assert counts == {"resolve_entities": 1, "unknown": 1}
    assert "private" not in str(counts)


def test_framework_output_tool_is_separated_without_allowing_arbitrary_names() -> None:
    messages = [
        SimpleNamespace(
            parts=[
                ToolCallPart("resolve_entities", {}),
                ToolCallPart("private_arbitrary_name", {}),
                ToolCallPart("final_result", {}),
                RetryPromptPart("redacted test retry"),
            ]
        )
    ]
    counters = probe._message_counters(messages, "final_result")
    assert counters == {
        "tool_names": ["resolve_entities", "private_arbitrary_name"],
        "terminal_output_calls": 1,
        "validation_rejections": 1,
    }
    assert probe._safe_tool_counts(counters["tool_names"]) == {"resolve_entities": 1, "unknown": 1}


def test_partial_usage_snapshot_tracks_mutable_failure_counters() -> None:
    usage = RunUsage(requests=2, tool_calls=3, input_tokens=101, output_tokens=17, details={"reasoning_tokens": 5})
    usage.requests += 1
    usage.tool_calls += 2
    assert probe._usage_snapshot(usage) == {
        "requests": 3,
        "provider_tool_calls": 5,
        "input_tokens": 101,
        "output_tokens": 17,
        "reasoning_tokens": 5,
    }


def test_diagnostic_subset_cannot_satisfy_production_gate() -> None:
    arms = probe._selected_profiles({"A2"})
    episodes = probe.select_probe_episodes({"E04", "E05"})
    assert not probe._is_complete_matrix(arms, episodes)
    assert probe._apply_gate_eligibility({"status": "PASS"}, [], {}, False) == {
        "status": "NOT_MEASURED",
        "reason": "diagnostic subset cannot satisfy production gate",
    }


def test_default_selection_is_the_full_fixed_matrix() -> None:
    arms = probe._selected_profiles()
    episodes = probe.select_probe_episodes()
    assert probe._is_complete_matrix(arms, episodes)
    assert [arm for arm, _profile in arms] == ["A0", "A1", "A2"]
    assert [row["number"] for row in episodes] == [4, 5]


def test_fixture_representability_uses_only_frozen_extractor_fields() -> None:
    entity = SimpleNamespace(name="safe-subject", properties={"safe-count": 27}, supersedes=None, temporal_signal=None)
    extracted = SimpleNamespace(entities=[entity], relations=[])
    expected = {
        "episode_key": "E05",
        "kind": "quantitative_update",
        "subject": "safe-subject",
        "predicate": "safe-count",
        "object": "27",
    }
    wrong = {**expected, "object": "28"}
    hashes = probe._extractable_fact_hashes("E05", extracted)
    assert probe.hashlib.sha256(probe.canonical_expectation(expected)).hexdigest() in hashes
    assert probe.hashlib.sha256(probe.canonical_expectation(wrong)).hexdigest() not in hashes


def test_frozen_cache_round_trip_is_private_and_safe_summary_omits_content(tmp_path: Path) -> None:
    cache = tmp_path / "private" / "frozen.json"
    extracted = probe.ExtractionResult.model_validate(
        {
            "entities": [
                {
                    "name": "private entity",
                    "type_name": "Concept",
                    "description": "private description",
                    "properties": {"private_key": "private value"},
                }
            ]
        }
    )
    provenance = probe._cache_provenance(
        model="local:test", effort="low", temperature=0.6, top_p=0.95, episode_keys=["E04"]
    )
    frozen = {"E04": (extracted, [("Concept", None)], [])}
    probe._write_frozen_cache(cache, frozen, provenance)
    loaded, loaded_provenance = probe._read_frozen_cache(cache, provenance)
    safe = probe._safe_cache_summary(cache, loaded_provenance, loaded)
    assert cache.stat().st_mode & 0o777 == 0o600
    assert cache.parent.stat().st_mode & 0o777 == 0o700
    assert loaded["E04"][0] == extracted
    assert safe["cardinalities"]["E04"] == {
        "entities": 1,
        "relations": 0,
        "node_types": 1,
        "edge_types": 0,
    }
    assert "private entity" not in str(safe)
    assert "private value" not in str(safe)


def test_frozen_cache_rejects_mismatched_provenance(tmp_path: Path) -> None:
    cache = tmp_path / "private" / "frozen.json"
    provenance = probe._cache_provenance(
        model="local:test", effort="low", temperature=0.6, top_p=0.95, episode_keys=["E04"]
    )
    probe._write_frozen_cache(cache, {"E04": (probe.ExtractionResult(), [], [])}, provenance)
    with pytest.raises(ValueError, match="provenance"):
        probe._read_frozen_cache(cache, {**provenance, "temperature": 0.7})


def test_extraction_requests_have_explicit_timeout() -> None:
    source = SCRIPT.read_text()
    extract_body = source.split("async def _extract_once", 1)[1].split("def _cache_provenance", 1)[0]
    assert extract_body.count("await asyncio.wait_for(") == 2
    assert extract_body.count("timeout=timeout") == 2


def test_fixture_trace_reports_safe_mutation_property_omission() -> None:
    extracted = probe.ExtractionResult.model_validate(
        {"entities": [{"name": "safe-subject", "type_name": "Concept", "properties": {"count": 15}}]}
    )
    tracker = probe.LibrarianTrajectoryTracker(entities=extracted.entities)
    tracker.entity_states[0] = "created"
    tracker.bound_node_ids[0] = 7
    preimage = {
        "episode_key": "E04",
        "kind": "node_fact",
        "subject": "safe-subject",
        "predicate": "count",
        "object": "15",
    }
    expectation = {
        "preimage": preimage,
        "sha256": probe.hashlib.sha256(probe.canonical_expectation(preimage)).hexdigest(),
    }
    graph = {
        "nodes": [{"id": 7, "name": "safe-subject", "properties": {"_source_episode": 1}}],
        "edges": [],
        "node_types": [],
        "edge_types": [],
    }
    assert probe._fixture_trace_categories("E04", [expectation], extracted, tracker, graph) == {
        "mutation_property_omitted": 1
    }


def test_fixture_relation_is_preserved_through_bound_canonical_node_identity() -> None:
    extracted = probe.ExtractionResult.model_validate(
        {
            "entities": [
                {"name": "raw_source", "type_name": "Concept"},
                {"name": "Target", "type_name": "Concept"},
            ],
            "relations": [{"source_name": "raw_source", "target_name": "Target", "relation_type": "USES"}],
        }
    )
    tracker = probe.LibrarianTrajectoryTracker(entities=extracted.entities, relations=extracted.relations)
    tracker.entity_states.update({0: "created", 1: "created"})
    tracker.relation_states[0] = "created"
    tracker.bound_node_ids.update({0: 10, 1: 11})
    preimage = {
        "episode_key": "E04",
        "kind": "edge_signature",
        "subject": "raw_source",
        "predicate": "USES",
        "object": "Target",
    }
    expectation = {
        "preimage": preimage,
        "sha256": probe.hashlib.sha256(probe.canonical_expectation(preimage)).hexdigest(),
    }
    graph = {
        "nodes": [
            {"id": 10, "name": "Raw Source", "properties": {}},
            {"id": 11, "name": "Target", "properties": {}},
        ],
        "edges": [{"id": 20, "source_id": 10, "target_id": 11, "type_id": 30, "properties": {}}],
        "node_types": [],
        "edge_types": [{"id": 30, "name": "USES"}],
    }
    assert probe._lineage_preserved_fixture_hashes("E04", [expectation], extracted, tracker, graph) == {
        expectation["sha256"]
    }
    assert probe._fixture_trace_categories("E04", [expectation], extracted, tracker, graph) == {
        "preserved_via_bound_identity": 1
    }


@pytest.mark.parametrize(
    ("exc", "reason"),
    [
        (TimeoutError(), "timeout"),
        (ValueError("relation checks are out of phase"), "relation_phase_violation"),
        (
            ValueError("decision identity differs from the selected resolver candidate"),
            "entity_decision_identity_mismatch",
        ),
        (ValueError("unique index count exceeds the batch limit"), "unique_batch_limit"),
        (
            ValueError("unresolved requires a missing endpoint or ambiguity"),
            "invalid_unresolved_relation",
        ),
        (ValueError("private model-controlled message"), "value_error_unclassified"),
    ],
)
def test_failure_reasons_are_code_owned(exc: BaseException, reason: str) -> None:
    assert probe._failure_reason(exc) == reason
    assert "private" not in reason


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


def test_mutation_counts_do_not_evaluate_legacy_fields_for_bounded_tracker() -> None:
    legacy = probe.CurationActionTracker(
        entities_created=1,
        entities_updated=2,
        entities_archived=3,
        edges_created=4,
        edges_removed=5,
    )
    assert probe._mutation_counts(legacy) == (15, 15)

    bounded = probe.LibrarianTrajectoryTracker()
    bounded.mutations_attempted = 7
    bounded.mutations_succeeded = 6
    assert probe._mutation_counts(bounded) == (7, 6)


@pytest.mark.asyncio
async def test_probe_graph_is_shared_and_granted_before_use() -> None:
    events: list[tuple[object, ...]] = []

    class SchemaManager:
        async def create_graph(self, agent_id: str, purpose: str, *, is_shared: bool) -> str:
            events.append(("create", agent_id, purpose, is_shared))
            return "ncx_probe__fixed"

    class Permissions:
        async def grant(
            self,
            agent_id: str,
            schema_name: str,
            can_read: bool,
            can_write: bool,
            granted_by: str,
        ) -> None:
            events.append(("grant", agent_id, schema_name, can_read, can_write, granted_by))

    created: list[str] = []
    schema = await probe._create_probe_graph(SchemaManager(), Permissions(), "probeagent", "a0e04r1", "admin", created)
    assert schema == "ncx_probe__fixed"
    assert created == [schema]
    assert events == [
        ("create", "probeagent", "a0e04r1", True),
        ("grant", "probeagent", schema, True, True, "admin"),
    ]


def test_embedding_credential_uses_named_environment_without_returning_value(monkeypatch) -> None:
    monkeypatch.setenv("PROBE_EMBEDDING_KEY", "private-test-value")
    assert probe._configure_embedding_api_key("PROBE_EMBEDDING_KEY") == "PROBE_EMBEDDING_KEY"
    assert probe.os.environ["GOOGLE_API_KEY"] == "private-test-value"
    with pytest.raises(ValueError, match="environment name is invalid"):
        probe._configure_embedding_api_key("BAD-NAME")


def test_live_probe_has_no_hardcoded_repository_agent_identity() -> None:
    source = SCRIPT.read_text()
    assert '"probe"' not in source
    assert "repo: GraphServiceAdapter,\n    agent_id: str," in source


def test_graph_properties_normalize_string_jsonb_to_dictionary() -> None:
    row = {"id": 1, "properties": '{"count": 27, "active": true}'}
    normalized = probe._normalize_graph_properties(row)
    assert normalized is row
    assert normalized["properties"] == {"count": 27, "active": True}


@pytest.mark.parametrize("properties", [None, [], "[]", '"scalar"'])
def test_graph_properties_reject_non_object_shapes(properties: object) -> None:
    with pytest.raises(ValueError, match="graph properties must be a JSON object"):
        probe._normalize_graph_properties({"properties": properties})


def test_graph_properties_reject_invalid_json_without_echoing_content() -> None:
    private_value = "{private-invalid-json"
    with pytest.raises(ValueError, match="graph properties are not valid JSON") as exc_info:
        probe._normalize_graph_properties({"properties": private_value})
    assert private_value not in str(exc_info.value)
