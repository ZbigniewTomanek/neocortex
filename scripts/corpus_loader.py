#!/usr/bin/env python3
"""Load the Plan 18.5 golden corpus into the ingestion API."""

from __future__ import annotations

import argparse
import asyncio
import re
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "docs/plans/18.5-e2e-revalidation/resources/episodes.md"
_EPISODE = re.compile(
    r"### Episode (\d+) -- (.+?)\n\*\*Importance\*\*: ([0-9.]+)\n" r"\*\*Context\*\*: \"([^\"]+)\"\n\n```\n(.*?)\n```",
    re.DOTALL,
)


def load_corpus(path: Path = CORPUS) -> list[dict[str, object]]:
    text = path.read_text()
    episodes = [
        {"number": int(n), "title": title, "importance": float(importance), "context": context, "text": body.strip()}
        for n, title, importance, context, body in _EPISODE.findall(text)
    ]
    if len(episodes) != 28:
        raise ValueError(f"expected 28 episodes, parsed {len(episodes)}")
    return episodes


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--file", type=Path, default=CORPUS)
    args = parser.parse_args()
    episodes = load_corpus(args.file)
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
    if accepted < 28:
        raise RuntimeError(f"only {accepted} episodes accepted, expected 28")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
