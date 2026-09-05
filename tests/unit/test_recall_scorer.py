"""Authentication contracts for the bake-off recall scorer."""

from __future__ import annotations

import asyncio
import math
from pathlib import Path
from types import SimpleNamespace

import pytest
import scripts.recall_scorer as recall_scorer  # ty: ignore[unresolved-import]
from scripts.e2e_manifest import EvidenceError, validate_recall_evidence  # ty: ignore[unresolved-import]
from scripts.recall_scorer import _recall_token  # ty: ignore[unresolved-import]

ROOT = Path(__file__).parents[2]


def test_recall_scorer_prefers_explicit_recall_token(monkeypatch) -> None:
    monkeypatch.setenv("NEOCORTEX_RECALL_TOKEN", "recall-token")
    monkeypatch.setenv("NEOCORTEX_MCP_TOKEN", "mcp-token")
    monkeypatch.setenv("NEOCORTEX_ALICE_TOKEN", "alice-token")

    assert _recall_token() == "recall-token"


def test_recall_scorer_uses_mcp_token_for_bakeoff(monkeypatch) -> None:
    monkeypatch.delenv("NEOCORTEX_RECALL_TOKEN", raising=False)
    monkeypatch.setenv("NEOCORTEX_MCP_TOKEN", "mcp-token")
    monkeypatch.setenv("NEOCORTEX_ALICE_TOKEN", "alice-token")

    assert _recall_token() == "mcp-token"


def test_bakeoff_recall_requires_explicit_mcp_token(monkeypatch) -> None:
    monkeypatch.delenv("NEOCORTEX_MCP_TOKEN", raising=False)
    monkeypatch.setenv("NEOCORTEX_RECALL_TOKEN", "recall-token")
    monkeypatch.setenv("NEOCORTEX_ALICE_TOKEN", "alice-token")

    with pytest.raises(RuntimeError, match="NEOCORTEX_MCP_TOKEN"):
        _recall_token(require_bakeoff_mcp=True)


def test_recall_scorer_keeps_alice_fallback_for_standalone_runs(monkeypatch) -> None:
    monkeypatch.delenv("NEOCORTEX_RECALL_TOKEN", raising=False)
    monkeypatch.delenv("NEOCORTEX_MCP_TOKEN", raising=False)
    monkeypatch.setenv("NEOCORTEX_ALICE_TOKEN", "alice-token")

    assert _recall_token() == "alice-token"


def test_recall_scorer_passes_configured_mcp_token_to_client(monkeypatch, tmp_path: Path) -> None:
    captured_auth: list[str] = []

    class FakeClient:
        def __init__(self, _url: str, *, auth: str) -> None:
            captured_auth.append(auth)

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def call_tool(self, _tool_name: str, _arguments: dict[str, object]) -> SimpleNamespace:
            return SimpleNamespace(structured_content={"results": []})

    monkeypatch.setattr(recall_scorer, "Client", FakeClient)
    monkeypatch.delenv("NEOCORTEX_RECALL_TOKEN", raising=False)
    monkeypatch.setenv("NEOCORTEX_MCP_TOKEN", "mcp-token")
    monkeypatch.setenv("NEOCORTEX_ALICE_TOKEN", "alice-token")
    output = tmp_path / "recall-results.json"
    monkeypatch.setattr("sys.argv", ["recall_scorer.py", "--output", str(output)])

    assert asyncio.run(recall_scorer.main()) == 0
    assert captured_auth == ["mcp-token"]
    assert output.is_file()


def test_recall_evidence_is_aggregate_only_and_validated(tmp_path: Path) -> None:
    rows = [
        {
            "query": "Q1",
            "text": "SECRET QUERY TEXT",
            "keywords": ("blocking",),
            "results": [
                {
                    "item_id": "secret-item-id",
                    "name": "SECRET PERSON NAME",
                    "content": "SECRET EPISODE CONTENT",
                    "activation_score": 0.8,
                }
            ],
        }
    ] * 9
    evidence = recall_scorer._safe_recall_evidence(rows, run_id="run-123")
    output = tmp_path / "recall.json"
    recall_scorer.atomic_write_json(output, evidence)
    serialized = output.read_text()

    assert all(
        secret not in serialized for secret in ("SECRET QUERY TEXT", "SECRET PERSON NAME", "SECRET EPISODE CONTENT")
    )
    assert "top_item_hash" in serialized
    validate_recall_evidence(evidence, run_id="run-123")

    evidence["query_results"][0]["top_item_hash"] = "not-a-digest"
    with pytest.raises(EvidenceError):
        validate_recall_evidence(evidence, run_id="run-123")


def test_missing_top_ids_are_excluded_from_m2_with_availability_semantics() -> None:
    rows = [
        {"results": [{"name": "without an identifier"}], "keywords": ()},
        {"results": [{"content": "also without an identifier"}], "keywords": ()},
        {"results": [{"name": "third missing identifier"}], "keywords": ()},
        {"results": [{"item_id": "same-id"}], "keywords": ()},
        {"results": [{"id": "same-id"}], "keywords": ()},
        *[{"results": [{"item_id": f"normal-{index}"}], "keywords": ()} for index in range(4)],
    ]

    evidence = recall_scorer._safe_recall_evidence(rows, run_id="run-123")

    assert evidence["top1_id_availability"] == {"known": 6, "missing": 3}
    assert evidence["metrics"]["M2_max_top1_count"] == 2
    assert [row["top_item_hash"] for row in evidence["query_results"][:3]] == [None, None, None]
    validate_recall_evidence(evidence, run_id="run-123")


@pytest.mark.parametrize(("value", "expected"), [(1, 1), ("node-1", "node-1"), ("  node-1  ", "node-1")])
def test_recall_identifier_accepts_only_canonical_positive_values(value: object, expected: int | str) -> None:
    assert recall_scorer._item_identifier({"item_id": value}) == expected


@pytest.mark.parametrize(
    "value",
    [None, "", " ", "\t", True, False, 0, -1, 1.0, math.nan, math.inf, {}, [], ("id",)],
)
def test_recall_identifier_rejects_invalid_item_id_values(value: object) -> None:
    assert recall_scorer._item_identifier({"item_id": value}) is None


@pytest.mark.parametrize("invalid_item_id", [None, " ", False, 0, -1, 1.5, {}, []])
def test_recall_identifier_falls_back_to_valid_id(invalid_item_id: object) -> None:
    assert recall_scorer._item_identifier({"item_id": invalid_item_id, "id": 7}) == 7


@pytest.mark.parametrize(
    "script_name",
    [
        "e2e_extraction_pipeline_test.py",
        "e2e_plan15_scenarios_test.py",
        "e2e_plan17_validation.py",
        "e2e_episodic_memory_test.py",
        "e2e_cognitive_recall_test.py",
    ],
)
def test_e2e_scripts_do_not_print_credential_material(script_name: str) -> None:
    source = (ROOT / "scripts" / script_name).read_text()

    assert "TOKEN[:8]" not in source
    assert "ALICE_TOKEN[:8]" not in source
