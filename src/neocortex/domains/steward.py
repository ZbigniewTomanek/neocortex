"""Taxonomy steward: report-only domain health review.

Collects routing metrics, shared-graph utilization, and domain hierarchy
metadata. Produces proposals (split, merge, description-drift,
underutilization) without applying any changes.

CLI entry point: ``python -m neocortex.domains.steward [--output FILE]``
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
from datetime import datetime

import asyncpg
from loguru import logger

from neocortex.config import PostgresConfig
from neocortex.db.scoped import schema_scoped_connection

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class DomainHealth:
    """Health metrics for a single domain."""

    slug: str
    name: str
    schema_name: str | None
    depth: int
    path: str
    seed: bool
    parent_slug: str | None

    # Routing metrics (from procrastinate_jobs)
    routed_episodes: int = 0

    # Shared-graph utilization
    active_nodes: int = 0
    edges: int = 0
    node_types_total: int = 0
    edge_types_total: int = 0
    node_types_used: int = 0
    edge_types_used: int = 0

    # Top active node type names (for drift / merge analysis)
    top_node_types: list[str] = field(default_factory=list)
    # Parallel counts for top_node_types (same order, for concentration analysis)
    top_node_type_counts: list[int] = field(default_factory=list)


@dataclass
class StewardProposal:
    """A report-only proposal for taxonomy improvement."""

    kind: str  # "split", "merge", "description_drift", "underutilized"
    targets: list[str]  # domain slugs
    reasoning: str


# ---------------------------------------------------------------------------
# Taxonomy steward
# ---------------------------------------------------------------------------

# Heuristic thresholds
_SPLIT_MIN_EPISODES = 10
_SPLIT_MIN_TYPES_USED = 6
_SPLIT_MAX_CONCENTRATION = 0.4  # no single type > 40% of nodes
_UNDERUTILIZED_MAX_EPISODES = 1


class TaxonomySteward:
    """Collect domain health metrics and generate report-only proposals."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    # ------------------------------------------------------------------
    # Data collection
    # ------------------------------------------------------------------

    async def collect_health(self) -> list[DomainHealth]:
        """Gather health metrics for every registered domain."""
        domains = await self._fetch_domains()
        if not domains:
            return []

        slug_by_id: dict[int, str] = {}
        for d in domains:
            if d["id"] is not None:
                slug_by_id[d["id"]] = d["slug"]

        routed_map = await self._fetch_routed_counts()

        results: list[DomainHealth] = []
        for d in domains:
            schema = d["schema_name"]
            health = DomainHealth(
                slug=d["slug"],
                name=d["name"],
                schema_name=schema,
                depth=d["depth"],
                path=d["path"],
                seed=d["seed"],
                parent_slug=slug_by_id.get(d["parent_id"]) if d["parent_id"] else None,
                routed_episodes=routed_map.get(schema, 0) if schema else 0,
            )

            if schema:
                try:
                    stats = await self._fetch_graph_stats(schema)
                    health.active_nodes = stats["active_nodes"]
                    health.edges = stats["edges"]
                    health.node_types_total = stats["node_types_total"]
                    health.edge_types_total = stats["edge_types_total"]
                    health.node_types_used = stats["node_types_used"]
                    health.edge_types_used = stats["edge_types_used"]
                    health.top_node_types = stats["top_node_types"]
                    health.top_node_type_counts = stats["top_node_type_counts"]
                except Exception:
                    logger.opt(exception=True).warning("steward_graph_stats_failed", schema=schema)

            results.append(health)

        return results

    async def _fetch_domains(self) -> list[dict]:
        """Read all domains from ontology_domains."""
        rows = await self._pool.fetch(
            "SELECT id, slug, name, schema_name, depth, path, seed, parent_id"
            " FROM ontology_domains ORDER BY path, id"
        )
        return [dict(r) for r in rows]

    async def _fetch_routed_counts(self) -> dict[str, int]:
        """Count distinct routed episodes per target_schema from procrastinate_jobs."""
        rows = await self._pool.fetch(
            "SELECT args->>'target_schema' AS schema_name,"
            " count(DISTINCT (args->'episode_ids'->>0)) AS routed_episodes"
            " FROM procrastinate_jobs"
            " WHERE task_name = 'extract_episode'"
            "   AND status = 'succeeded'"
            "   AND args->>'target_schema' IS NOT NULL"
            " GROUP BY args->>'target_schema'"
        )
        return {r["schema_name"]: r["routed_episodes"] for r in rows}

    async def _fetch_graph_stats(self, schema_name: str) -> dict:
        """Fetch node/edge/type stats from a shared graph schema."""
        async with schema_scoped_connection(self._pool, schema_name) as conn:
            active_nodes = await conn.fetchval("SELECT count(*) FROM node WHERE NOT forgotten")
            edges = await conn.fetchval("SELECT count(*) FROM edge")
            node_types_total = await conn.fetchval("SELECT count(*) FROM node_type")
            edge_types_total = await conn.fetchval("SELECT count(*) FROM edge_type")

            node_types_used = await conn.fetchval(
                "SELECT count(*) FROM node_type nt"
                " WHERE EXISTS ("
                "   SELECT 1 FROM node n WHERE n.type_id = nt.id AND NOT n.forgotten"
                " )"
            )
            edge_types_used = await conn.fetchval(
                "SELECT count(*) FROM edge_type et"
                " WHERE EXISTS ("
                "   SELECT 1 FROM edge e WHERE e.type_id = et.id"
                " )"
            )

            top_rows = await conn.fetch(
                "SELECT nt.name, count(n.id) AS cnt"
                " FROM node_type nt"
                " LEFT JOIN node n ON n.type_id = nt.id AND NOT n.forgotten"
                " GROUP BY nt.id, nt.name"
                " ORDER BY cnt DESC"
                " LIMIT 5"
            )
            top_node_types = [r["name"] for r in top_rows]
            top_node_type_counts = [r["cnt"] for r in top_rows]

        return {
            "active_nodes": active_nodes or 0,
            "edges": edges or 0,
            "node_types_total": node_types_total or 0,
            "edge_types_total": edge_types_total or 0,
            "node_types_used": node_types_used or 0,
            "edge_types_used": edge_types_used or 0,
            "top_node_types": top_node_types,
            "top_node_type_counts": top_node_type_counts,
        }

    # ------------------------------------------------------------------
    # Proposal heuristics
    # ------------------------------------------------------------------

    def generate_proposals(self, health: list[DomainHealth]) -> list[StewardProposal]:
        """Produce report-only proposals from collected health data."""
        proposals: list[StewardProposal] = []
        proposals.extend(self._check_splits(health))
        proposals.extend(self._check_merges(health))
        proposals.extend(self._check_drift(health))
        proposals.extend(self._check_underutilized(health))
        return proposals

    def _check_splits(self, health: list[DomainHealth]) -> list[StewardProposal]:
        """Domains with high volume + high type diversity may warrant a split."""
        proposals: list[StewardProposal] = []
        for h in health:
            if (
                h.routed_episodes >= _SPLIT_MIN_EPISODES
                and h.node_types_used >= _SPLIT_MIN_TYPES_USED
                and h.active_nodes > 0
            ):
                # Use actual max-type share when per-type counts are available
                if h.top_node_type_counts and h.active_nodes > 0:
                    concentration = max(h.top_node_type_counts) / h.active_nodes
                else:
                    concentration = 1.0 / h.node_types_used if h.node_types_used > 0 else 1.0
                if concentration < _SPLIT_MAX_CONCENTRATION:
                    proposals.append(
                        StewardProposal(
                            kind="split",
                            targets=[h.slug],
                            reasoning=(
                                f"{h.slug} has {h.routed_episodes} routed episodes and "
                                f"{h.node_types_used} active node types with low "
                                f"concentration ({concentration:.2f}). Consider splitting "
                                f"into child domains."
                            ),
                        )
                    )
        return proposals

    def _check_merges(self, health: list[DomainHealth]) -> list[StewardProposal]:
        """Sibling domains with similar active type sets may warrant merging."""
        proposals: list[StewardProposal] = []

        # Group by parent_slug
        by_parent: dict[str | None, list[DomainHealth]] = {}
        for h in health:
            by_parent.setdefault(h.parent_slug, []).append(h)

        for _parent, siblings in by_parent.items():
            if len(siblings) < 2:
                continue
            for i, a in enumerate(siblings):
                for b in siblings[i + 1 :]:
                    if not a.top_node_types or not b.top_node_types:
                        continue
                    overlap = set(a.top_node_types) & set(b.top_node_types)
                    union = set(a.top_node_types) | set(b.top_node_types)
                    if union and len(overlap) / len(union) > 0.5:
                        proposals.append(
                            StewardProposal(
                                kind="merge",
                                targets=[a.slug, b.slug],
                                reasoning=(
                                    f"Siblings {a.slug} and {b.slug} share "
                                    f"{len(overlap)}/{len(union)} top node types. "
                                    f"Consider merging."
                                ),
                            )
                        )
        return proposals

    def _check_drift(self, health: list[DomainHealth]) -> list[StewardProposal]:
        """Flag domains whose top active types seem inconsistent with their name."""
        proposals: list[StewardProposal] = []
        for h in health:
            if not h.top_node_types or h.active_nodes < 3:
                continue
            # Simple heuristic: if the domain slug tokens don't appear in any
            # of the top type names, it might be drifting.
            slug_tokens = set(h.slug.split("_"))
            type_tokens: set[str] = set()
            for t in h.top_node_types:
                type_tokens.update(t.lower().replace("_", " ").split())

            if not slug_tokens & type_tokens:
                proposals.append(
                    StewardProposal(
                        kind="description_drift",
                        targets=[h.slug],
                        reasoning=(
                            f"{h.slug} top types [{', '.join(h.top_node_types)}] "
                            f"share no tokens with the domain slug. "
                            f"Description may be drifting from actual content."
                        ),
                    )
                )
        return proposals

    def _check_underutilized(self, health: list[DomainHealth]) -> list[StewardProposal]:
        """Flag domains receiving very little traffic relative to peers."""
        proposals: list[StewardProposal] = []
        if not health:
            return proposals

        max_episodes = max(h.routed_episodes for h in health)
        if max_episodes == 0:
            return proposals

        for h in health:
            if h.routed_episodes <= _UNDERUTILIZED_MAX_EPISODES and not h.seed:
                proposals.append(
                    StewardProposal(
                        kind="underutilized",
                        targets=[h.slug],
                        reasoning=(
                            f"{h.slug} has only {h.routed_episodes} routed episode(s) "
                            f"while the busiest domain has {max_episodes}. "
                            f"May be too narrow or poorly described."
                        ),
                    )
                )
        return proposals

    # ------------------------------------------------------------------
    # Report formatting
    # ------------------------------------------------------------------

    def format_report(
        self,
        health: list[DomainHealth],
        proposals: list[StewardProposal],
    ) -> str:
        """Format a human-readable Markdown report."""
        lines: list[str] = []
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        lines.append(f"# Taxonomy Steward Report — {now}")
        lines.append("")

        # Domain tree
        lines.append("## Domain Tree")
        lines.append("")
        for h in sorted(health, key=lambda h: h.path):
            indent = "  " * h.depth
            seed_marker = " (seed)" if h.seed else ""
            lines.append(f"{indent}- **{h.slug}**{seed_marker}: {h.name}")
        lines.append("")

        # Metrics table
        lines.append("## Domain Metrics")
        lines.append("")
        lines.append(
            "| Domain | Routed Eps | Nodes | Edges | Node Types (used/total) " "| Edge Types (used/total) | Top Types |"
        )
        lines.append(
            "|--------|-----------|-------|-------|-------------------------|" "-------------------------|-----------|"
        )
        for h in sorted(health, key=lambda h: (-h.routed_episodes, h.slug)):
            top = ", ".join(h.top_node_types[:3]) if h.top_node_types else "—"
            lines.append(
                f"| {h.slug} | {h.routed_episodes} | {h.active_nodes} | {h.edges} "
                f"| {h.node_types_used}/{h.node_types_total} "
                f"| {h.edge_types_used}/{h.edge_types_total} "
                f"| {top} |"
            )
        lines.append("")

        # Proposals
        lines.append("## Proposals")
        lines.append("")
        if proposals:
            for i, p in enumerate(proposals, 1):
                lines.append(f"{i}. **{p.kind}** — {', '.join(p.targets)}")
                lines.append(f"   {p.reasoning}")
                lines.append("")
        else:
            lines.append("No proposals at this time.")
            lines.append("")

        # Summary
        total = len(health)
        seed_count = sum(1 for h in health if h.seed)
        non_seed = total - seed_count
        total_routed = sum(h.routed_episodes for h in health)
        lines.append("## Summary")
        lines.append("")
        lines.append(f"- **Total domains**: {total} ({seed_count} seed, {non_seed} created)")
        lines.append(f"- **Total routed episodes**: {total_routed}")
        lines.append(f"- **Proposals**: {len(proposals)}")
        lines.append("")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


async def _run(output: str | None) -> None:
    """Run the steward against a live PostgreSQL database."""
    pg_config = PostgresConfig()
    # statement_cache_size=0: scoped connections switch `search_path` per transaction on pooled
    # connections, so a plan cached under one graph schema would be invalid under another.
    pool = await asyncpg.create_pool(dsn=pg_config.dsn, min_size=1, max_size=3, statement_cache_size=0)
    assert pool is not None

    try:
        steward = TaxonomySteward(pool)
        health = await steward.collect_health()
        proposals = steward.generate_proposals(health)
        report = steward.format_report(health, proposals)

        if output:
            with open(output, "w") as f:
                f.write(report)
            print(f"Report written to {output}")
        else:
            print(report)
    finally:
        await pool.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Taxonomy steward: domain health report")
    parser.add_argument(
        "--output",
        "-o",
        help="Write report to file instead of stdout",
        default=None,
    )
    args = parser.parse_args()
    asyncio.run(_run(args.output))


if __name__ == "__main__":
    main()
