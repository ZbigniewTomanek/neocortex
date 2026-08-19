"""Load the fixed markdown corpus used by the Plan 33 model probes."""

from __future__ import annotations

import re
from pathlib import Path


def load_probe_corpus(path: str | Path | None = None) -> list[tuple[str, str]]:
    """Return ``(id, text)`` pairs from ``##`` sections in the probe corpus."""
    corpus_path = (
        Path(path)
        if path
        else Path(__file__).parents[1] / "docs/plans/33-local-qwen-migration/resources/probe-corpus.md"
    )
    text = corpus_path.read_text(encoding="utf-8")
    sections = re.findall(r"^##\s+(E\d+)\s+—[^\n]*\n\n(.*?)(?=^##\s+|\Z)", text, re.MULTILINE | re.DOTALL)
    if len(sections) != 3:
        raise ValueError(f"Expected three probe episodes in {corpus_path}, found {len(sections)}")
    return [(episode_id, body.strip()) for episode_id, body in sections]


if __name__ == "__main__":
    for episode_id, body in load_probe_corpus():
        print(f"{episode_id}: {body}")
