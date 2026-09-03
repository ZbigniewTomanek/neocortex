"""Domain router: classify → permissions → provision → extract.

Orchestrates automatic routing of episodes to shared domain-specific
knowledge graphs based on semantic classification.
"""

from __future__ import annotations

import re

import procrastinate
from loguru import logger

from neocortex.domains.classifier import AgentDomainClassifier, DomainClassifier
from neocortex.domains.models import (
    DomainClassification,
    ProposedDomain,
    RoutingResult,
    SemanticDomain,
)
from neocortex.domains.protocol import DomainService
from neocortex.domains.seed_generator import SeedGenerator
from neocortex.permissions.protocol import PermissionChecker
from neocortex.schema_manager import SchemaManager

_SLUG_PATTERN = re.compile(r"[^a-z0-9_]+")
_REPEATED_UNDERSCORES = re.compile(r"_+")


class DomainRouter:
    """Orchestrate domain classification, permission checks, schema
    provisioning, and extraction job enqueuing for shared domain graphs."""

    def __init__(
        self,
        domain_service: DomainService,
        classifier: DomainClassifier,
        schema_mgr: SchemaManager | None,
        permissions: PermissionChecker,
        job_app: procrastinate.App | None = None,
        classification_threshold: float = 0.3,
        seed_generator: SeedGenerator | None = None,
    ) -> None:
        self._domain_service = domain_service
        self._classifier = classifier
        self._schema_mgr = schema_mgr
        self._permissions = permissions
        self._job_app = job_app
        self._classification_threshold = classification_threshold
        self._seed_generator = seed_generator

    async def list_domains(self) -> list[SemanticDomain]:
        return await self._domain_service.list_domains()

    async def ensure_domains_seeded(self) -> None:
        """Ensure seed domains are available. Idempotent."""
        await self._domain_service.seed_defaults()

    async def route_and_extract(
        self,
        agent_id: str,
        episode_id: int,
        episode_text: str,
    ) -> list[RoutingResult]:
        """Classify episode text and route to matching shared domain schemas."""
        correlation_id = f"route:{agent_id}:{episode_id}"
        domains = await self._domain_service.list_domains()

        if not domains:
            logger.warning(
                "domain_routing_skipped",
                reason="no_domains_available",
                agent_id=agent_id,
                episode_id=episode_id,
            )
            return []

        try:
            if isinstance(self._classifier, AgentDomainClassifier):
                classification = await self._classifier.classify(
                    episode_text,
                    domains,
                    agent_id=agent_id,
                    episode_id=episode_id,
                    correlation_id=correlation_id,
                )
            else:
                # Keep the protocol compatible with deterministic test and
                # plugin classifiers that implement the original two-argument
                # method.
                classification = await self._classifier.classify(episode_text, domains)
        except Exception:
            logger.bind(action_log=True).warning(
                "domain_classification_failed",
                agent_id=agent_id,
                episode_id=episode_id,
                correlation_id=correlation_id,
            )
            return []

        logger.bind(action_log=True).info(
            "domain_classification_result",
            agent_id=agent_id,
            episode_id=episode_id,
            correlation_id=correlation_id,
            matched_count=len(classification.matched_domains),
            matched_slugs=[m.domain_slug for m in classification.matched_domains],
            method=(
                "llm"
                if classification.matched_domains and classification.matched_domains[0].reasoning != "keyword_fallback"
                else "keyword_fallback"
            ),
        )

        # Filter matches below threshold
        matches = [m for m in classification.matched_domains if m.confidence >= self._classification_threshold]

        # Handle proposed new domain
        if classification.proposed_domain is not None and self._schema_mgr is not None:
            new_domain = await self._provision_domain(classification.proposed_domain, agent_id)
            if new_domain is not None:
                # Warm the seed cache for the newly provisioned domain
                if self._seed_generator is not None:
                    try:
                        await self._seed_generator.resolve_seed(new_domain.slug)
                    except Exception:
                        logger.opt(exception=True).warning("seed_cache_warm_failed", slug=new_domain.slug)
                matches.append(
                    DomainClassification(
                        domain_slug=new_domain.slug,
                        confidence=0.6,
                        reasoning=f"Auto-provisioned domain: {classification.proposed_domain.reasoning}",
                    )
                )

        results: list[RoutingResult] = []
        for match in matches:
            domain = await self._domain_service.get_domain(match.domain_slug)
            if domain is None:
                continue

            schema_name = await self._ensure_schema(domain, agent_id)
            if schema_name is None:
                continue

            can_write = await self._permissions.can_write_schema(agent_id, schema_name)
            if not can_write:
                logger.warning(
                    "domain_routing_permission_denied",
                    agent_id=agent_id,
                    schema_name=schema_name,
                    domain_slug=match.domain_slug,
                )
                continue

            hint = f"{domain.name}: {domain.description}"
            job_id = await self._enqueue_extraction(
                agent_id,
                episode_id,
                schema_name,
                domain_hint=hint,
                domain_slug=match.domain_slug,
            )
            results.append(
                RoutingResult(
                    domain_slug=match.domain_slug,
                    schema_name=schema_name,
                    confidence=match.confidence,
                    extraction_job_id=job_id,
                )
            )

        if results:
            logger.bind(action_log=True).info(
                "domain_routing_completed",
                agent_id=agent_id,
                episode_id=episode_id,
                correlation_id=correlation_id,
                routed_to=[r.schema_name for r in results],
                domain_count=len(results),
            )
        else:
            logger.bind(action_log=True).warning(
                "domain_routing_unrouted",
                agent_id=agent_id,
                episode_id=episode_id,
                correlation_id=correlation_id,
                matched_count=len(classification.matched_domains),
                proposed=classification.proposed_domain is not None,
                reason="no_domains_matched_or_provisioned",
            )
        return results

    async def _provision_domain(self, proposed: ProposedDomain, agent_id: str) -> SemanticDomain | None:
        """Create a new domain, provision its shared schema, and grant permissions."""
        slug = _sanitize_slug(proposed.slug)

        # Resolve parent_slug to parent_id (D3: do not auto-create missing parents).
        # If the parent slug does not resolve, treat the proposal as root-level
        # rather than silently creating a synthetic parent domain.
        parent_id: int | None = None
        if proposed.parent_slug is not None:
            parent = await self._domain_service.get_domain(proposed.parent_slug)
            if parent is not None:
                parent_id = parent.id
            else:
                logger.bind(action_log=True).warning(
                    "domain_provision_parent_not_found",
                    proposed_slug=slug,
                    parent_slug=proposed.parent_slug,
                    action="treating_as_root",
                )

        try:
            domain = await self._domain_service.create_domain(
                slug=slug,
                name=proposed.name,
                description=proposed.description,
                created_by=agent_id,
                parent_id=parent_id,
            )
        except Exception:
            logger.warning("domain_provision_create_failed", slug=slug)
            return None

        # schema_mgr is guaranteed non-None by caller
        assert self._schema_mgr is not None
        schema_name = await self._schema_mgr.create_graph(agent_id="shared", purpose=slug, is_shared=True)

        await self._permissions.grant(
            agent_id=agent_id,
            schema_name=schema_name,
            can_read=True,
            can_write=True,
            granted_by="domain_router",
        )

        await self._domain_service.update_schema_name(slug, schema_name)

        logger.bind(action_log=True).info(
            "domain_provisioned",
            slug=slug,
            schema_name=schema_name,
            agent_id=agent_id,
        )
        return domain.model_copy(update={"schema_name": schema_name})

    async def _ensure_schema(self, domain: SemanticDomain, agent_id: str) -> str | None:
        """Get or create the shared schema for a domain. Returns None if unavailable."""
        if domain.schema_name is not None:
            # Verify schema actually exists (seed domains may have name but no schema)
            if self._schema_mgr is not None:
                existing = await self._schema_mgr.get_graph(agent_id="shared", purpose=domain.slug)
                if existing is not None:
                    # Grant permissions for this agent (idempotent)
                    await self._permissions.grant(
                        agent_id=agent_id,
                        schema_name=domain.schema_name,
                        can_read=True,
                        can_write=True,
                        granted_by="domain_router",
                    )
                    logger.info(
                        "domain_schema_permission_granted",
                        agent_id=agent_id,
                        schema_name=domain.schema_name,
                        domain_slug=domain.slug,
                    )
                    return domain.schema_name
                # Schema name set but schema doesn't exist — fall through to create
            else:
                return domain.schema_name

        if self._schema_mgr is None:
            return None

        schema_name = await self._schema_mgr.create_graph(agent_id="shared", purpose=domain.slug, is_shared=True)

        await self._permissions.grant(
            agent_id=agent_id,
            schema_name=schema_name,
            can_read=True,
            can_write=True,
            granted_by="domain_router",
        )

        await self._domain_service.update_schema_name(domain.slug, schema_name)
        return schema_name

    async def _enqueue_extraction(
        self,
        agent_id: str,
        episode_id: int,
        target_schema: str,
        domain_hint: str | None = None,
        domain_slug: str | None = None,
    ) -> int | None:
        """Defer an extract_episode task for the target schema.

        Episodes live in the agent's personal graph (source_schema=None),
        but extraction results go to the shared domain schema (target_schema).
        """
        if self._job_app is None:
            return None

        job_id = await self._job_app.configure_task("extract_episode").defer_async(
            agent_id=agent_id,
            episode_ids=[episode_id],
            target_schema=target_schema,
            source_schema="__personal__",  # sentinel: read from agent's personal graph
            domain_hint=domain_hint,
            domain_slug=domain_slug,
        )
        logger.debug(
            "domain_extraction_enqueued",
            agent_id=agent_id,
            episode_id=episode_id,
            target_schema=target_schema,
            job_id=job_id,
        )
        return job_id


def _sanitize_slug(value: str) -> str:
    """Sanitize a proposed domain slug to lowercase alphanumeric + underscores."""
    normalized = _SLUG_PATTERN.sub("_", value.strip().lower())
    normalized = _REPEATED_UNDERSCORES.sub("_", normalized).strip("_")
    if not normalized:
        raise ValueError("slug must contain at least one ASCII letter or digit")
    return normalized
