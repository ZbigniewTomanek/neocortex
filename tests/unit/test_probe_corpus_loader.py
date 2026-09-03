"""Regression tests for the Plan 33 probe corpus loader and evidence contract."""

import json
from pathlib import Path

from scripts.corpus_loader import load_probe_corpus  # ty: ignore[unresolved-import]


def test_load_probe_corpus_returns_fixed_plan33_episodes() -> None:
    episodes = load_probe_corpus()

    assert [episode_id for episode_id, _text in episodes] == ["E1", "E2", "E3"]
    assert all(text for _episode_id, text in episodes)
    assert "Correction: it actually landed" in episodes[1][1]


def test_load_probe_corpus_accepts_pathlike(tmp_path: Path) -> None:
    source = tmp_path / "probe-corpus.md"
    source.write_text(
        "## E1 — test\n\nOne\n\n## E2 — test\n\nTwo\n\n## E3 — test\n\nThree\n",
        encoding="utf-8",
    )

    assert load_probe_corpus(source) == [("E1", "One"), ("E2", "Two"), ("E3", "Three")]


def test_probe_artifacts_have_run_provenance_and_measured_availability() -> None:
    root = Path(__file__).parents[2]
    artifact_paths = sorted((root / "docs/plans/33-local-qwen-migration/resources").glob("probe-results-*.json"))
    assert {path.stem for path in artifact_paths} >= {
        "probe-results-low",
        "probe-results-medium",
        "probe-results-high",
        "probe-results-xhigh",
    }

    required_metadata = {
        "run_id",
        "started_at_utc",
        "source_revision",
        "working_tree_clean",
        "source_worktree_clean",
        "source_diff_sha256",
        "probe_script_sha256",
        "corpus_id",
        "corpus_path",
        "corpus_sha256",
        "episode_set",
        "endpoint_url",
        "model_id",
        "direct_call_mode",
        "job_ids",
        "concurrency",
        "timeout_s",
        "repeats",
        "expected_records",
    }
    required_record = {
        "agent",
        "episode",
        "model",
        "effort",
        "input_source",
        "status",
        "outcome",
        "elapsed_s",
        "tool_calls",
        "tool_calls_available",
        "retries",
        "retries_available",
        "normalization_rejections",
        "normalization_rejections_available",
        "raw_validation_output",
        "raw_validation_output_available",
        "usage",
        "usage_available",
    }
    for artifact_path in artifact_paths:
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        metadata = artifact["run_metadata"]
        assert artifact["schema_version"] == 2
        assert required_metadata <= metadata.keys()
        assert metadata["corpus_path"] == "docs/plans/33-local-qwen-migration/resources/probe-corpus.md"
        assert metadata["episode_set"] == ["E1", "E2", "E3"]
        assert metadata["job_ids"] == []
        assert metadata["direct_call_mode"] == "pydanticai_agent_direct"
        assert metadata["expected_records"] == len(artifact["records"]) == 60

        for record in artifact["records"]:
            assert required_record <= record.keys()
            assert record["model"] == metadata["model"]
            assert record["effort"] == metadata["effort"]
            assert record["input_source"] == metadata["corpus_path"]
            if record["usage_available"]:
                assert record["usage"]["availability"] == "MEASURED"
            else:
                assert record["usage"]["availability"] == "NOT_MEASURED"
            if record["raw_validation_output_available"]:
                assert record["raw_validation_output"] != "NOT_MEASURED"
            else:
                assert record["raw_validation_output"] == "NOT_MEASURED"
            if record["retries_available"]:
                assert isinstance(record["retries"], int)
            else:
                assert record["retries"] == "NOT_MEASURED"
