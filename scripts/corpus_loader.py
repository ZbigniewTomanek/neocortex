#!/usr/bin/env python3
"""Load the full golden corpus or the explicit Plan 33 compact corpus."""

from __future__ import annotations

import argparse
import asyncio
import os
import re
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "docs/plans/18.5-e2e-revalidation/resources/episodes.md"
COMPACT_CORPUS = ROOT / "docs/plans/33-local-qwen-migration/resources/compact-corpus.md"
CORPUS_EPISODE_IDS = {"full": tuple(range(1, 29)), "compact": (2, 4, 5, 10, 18, 20, 26, 27)}
PROBE_CORPUS = ROOT / "docs/plans/33-local-qwen-migration/resources/probe-corpus.md"
_EPISODE = re.compile(
    r"### Episode (\d+) -- (.+?)\n\*\*Importance\*\*: ([0-9.]+)\n" r"\*\*Context\*\*: \"([^\"]+)\"\n\n```\n(.*?)\n```",
    re.DOTALL,
)


def corpus_path(profile: str = "full") -> Path:
    if profile not in CORPUS_EPISODE_IDS:
        raise ValueError(f"unknown corpus profile: {profile}")
    return CORPUS if profile == "full" else COMPACT_CORPUS


def load_corpus(path: Path | None = None, *, profile: str = "full") -> list[dict[str, object]]:
    selected_path = path or corpus_path(profile)
    if profile not in CORPUS_EPISODE_IDS:
        raise ValueError(f"unknown corpus profile: {profile}")
    text = selected_path.read_text(encoding="utf-8")
    episodes = [
        {"number": int(n), "title": title, "importance": float(importance), "context": context, "text": body.strip()}
        for n, title, importance, context, body in _EPISODE.findall(text)
    ]
    expected = CORPUS_EPISODE_IDS[profile]
    actual = tuple(episode["number"] for episode in episodes)
    headings = tuple(int(n) for n in re.findall(r"^### Episode (\d+) -- ", text, re.MULTILINE))
    if actual != expected or headings != expected:
        raise ValueError(f"{profile} corpus expected episode IDs {expected}, parsed {actual}; headings {headings}")
    if any(not episode["text"] for episode in episodes):
        raise ValueError(f"{profile} corpus contains an empty episode")
    return episodes


def load_probe_corpus(path: Path | None = None) -> list[tuple[str, str]]:
    """Load the fixed Plan 33 probe corpus as ``(episode_id, source_text)`` pairs.

    ``load_corpus`` defaults to the 28-episode ingestion/bake-off contract. The capability
    probe intentionally uses the separate three-episode corpus, so keeping this
    adapter here prevents the probe from importing a stale symbol while preserving
    the existing ingestion loader's return shape.
    """
    corpus_path = path or PROBE_CORPUS
    text = corpus_path.read_text(encoding="utf-8")
    sections = re.findall(r"^##\s+(E\d+)\s+—[^\n]*\n\n(.*?)(?=^##\s+|\Z)", text, re.MULTILINE | re.DOTALL)
    if len(sections) != 3:
        raise ValueError(f"expected three probe episodes in {corpus_path}, found {len(sections)}")
    return [(episode_id, body.strip()) for episode_id, body in sections]


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--file", type=Path)
    parser.add_argument(
        "--corpus-profile",
        choices=tuple(CORPUS_EPISODE_IDS),
        default=os.environ.get("NEOCORTEX_BAKEOFF_CORPUS_PROFILE", "full"),
    )
    args = parser.parse_args()
    episodes = load_corpus(args.file, profile=args.corpus_profile)
    if args.dry_run:
        for episode in episodes:
            print(f"{episode['number']:02d}: {episode['title']} ({episode['importance']}, {episode['context']})")
        return 0

    base_url = __import__("os").environ.get("NEOCORTEX_INGESTION_BASE_URL", "http://127.0.0.1:8001")
    token = __import__("os").environ.get("NEOCORTEX_ADMIN_TOKEN", "admin-token-neocortex")
    async with httpx.AsyncClient(
        base_url=base_url, timeout=30.0, headers={"Authorization": f"Bearer {token}"}
    ) as client:
        accepted = 0
        for episode in episodes:
            response = await client.post(
                "/ingest/text",
                json={
                    "text": episode["text"],
                    "force": True,
                    "metadata": {
                        "importance_hint": episode["importance"],
                        "context": episode["context"],
                        "corpus_episode": episode["number"],
                    },
                },
            )
            response.raise_for_status()
            result = response.json()
            accepted += int(result.get("episodes_created", 0))
            print(f"episode {episode['number']}: {result.get('status')} ({result.get('message', '')})")
    if accepted < len(episodes):
        raise RuntimeError(f"only {accepted} episodes accepted, expected {len(episodes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
