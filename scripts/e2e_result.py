"""Small atomic writer shared by scenario E2E scripts."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

try:
    from scripts.e2e_manifest import atomic_write_json  # ty: ignore[unresolved-import]
except ModuleNotFoundError:  # Direct ``python scripts/e2e_*.py`` execution.
    from e2e_manifest import atomic_write_json  # ty: ignore[unresolved-import]


def write_configured_result(payload: dict[str, Any]) -> None:
    """Write a machine result only when the bake-off supplied a result path."""
    configured = os.environ.get("NEOCORTEX_E2E_RESULT_PATH")
    if configured:
        atomic_write_json(Path(configured), payload)
