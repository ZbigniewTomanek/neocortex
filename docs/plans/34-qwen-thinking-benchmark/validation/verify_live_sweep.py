#!/usr/bin/env python3
"""Read-only verification of the finalized Plan34 live sweep."""

import importlib.util
import json
import sys
from pathlib import Path

PLAN = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("sweep_verification_runner", PLAN / "validation/effort_sweep_runner.py")
assert spec is not None and spec.loader is not None
runner = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runner
spec.loader.exec_module(runner)

result = json.loads((PLAN / "resources/effort-sweep.json").read_text())
identity = json.loads((PLAN / "resources/effort-levels.json").read_text())
assert result["run"]["complete"] is True
assert result["run"]["test_model"] is False
assert result["run"]["budget_exhausted"] is False
assert 0 < result["run"]["runner_wall_seconds"] <= 14400
assert len(result["cells"]) == 16
assert len({(cell["agent"], cell["level"]) for cell in result["cells"]}) == 16
selected = {}
observed = []
for agent in runner.AGENTS:
    for cell in [item for item in result["cells"] if item["agent"] == agent]:
        raw_path = PLAN / cell["raw_path"]
        raw = json.loads(raw_path.read_text())
        cell_spec = runner.make_spec(agent, cell["level"], selected)
        recomputed = runner.analyse_raw(
            cell_spec,
            raw_path,
            test_model=False,
            expected_model=identity["run"]["configured_model"],
            expected_corpus_sha256=identity["run"]["compact_corpus_sha256"],
        )
        for key, value in recomputed.items():
            if key != "selected":
                assert cell[key] == value, (agent, cell["level"], key, cell[key], value)
        assert len(raw["episodes"]) == len(cell_spec.expected_units)
        assert raw["run"]["embeddings"] == "none"
        assert raw["run"]["per_call_timeout_s"] <= 300
        if cell["selected"]:
            assert cell["status"] == "PASS"
            assert cell["critical_defects"] == []
            assert cell["timeouts"] <= 1
            assert all(row["critical_defects"] == [] for row in raw["episodes"])
        observed.append(
            {
                key: cell[key]
                for key in (
                    "agent",
                    "level",
                    "status",
                    "reason",
                    "raw_path",
                    "episodes",
                    "facts_found",
                    "facts_total",
                    "triplet_passes",
                    "timeouts",
                    "critical_defects",
                    "median_reasoning_tokens",
                    "valid_results",
                )
            }
        )
    selection = runner.select_agent(agent, result["cells"])
    assert selection == result["selections"][agent]
    assert selection["status"] == "SELECTED"
    selected[agent] = selection["level"]
assert runner.classifier_agreement(result["cells"]) == result["classifier_domain_agreement"]
actual_child_wall = round(sum(cell.get("child_wall_seconds", 0) for cell in result["cells"]), 3)
assert actual_child_wall == result["run"]["total_cell_wall_seconds"]
print(
    json.dumps(
        {
            "raw_cells_reopened": len(observed),
            "all_fields_recomputed_equal": True,
            "run": result["run"],
            "selections": result["selections"],
            "classifier_domain_agreement": result["classifier_domain_agreement"],
            "cells": observed,
        },
        indent=2,
    )
)
