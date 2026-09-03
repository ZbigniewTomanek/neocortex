"""Regression tests for the Plan 33 probe corpus loader contract."""

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
