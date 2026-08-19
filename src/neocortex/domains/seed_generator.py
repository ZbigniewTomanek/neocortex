"""Dynamic seed generation for newly created domains.

Resolution order:
1. Static seed in DOMAIN_SEEDS
2. Runtime cache
3. Parent inheritance
4. LLM generation
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger
from pydantic_ai import Agent
from pydantic_ai.settings import ThinkingLevel

from neocortex.domains.ontology_seeds import DOMAIN_SEEDS, DomainOntologySeed
from neocortex.model_factory import LocalEndpoint, build_model, build_model_settings

if TYPE_CHECKING:
    from neocortex.domains.protocol import DomainService


class SeedGenerator:
    """Resolve ontology seeds for domains, generating them when needed."""

    def __init__(
        self,
        domain_service: DomainService,
        # Plan 33 introduces an opt-in local: model route; Stage 9 changes defaults after the gate.
        model: str = "openai-responses:gpt-5.4-mini",
        thinking_effort: ThinkingLevel = "medium",
        local_endpoint: LocalEndpoint | None = None,
    ) -> None:
        self._domain_service = domain_service
        self._model = model
        self._thinking_effort = thinking_effort
        self._local_endpoint = local_endpoint
        self._cache: dict[str, DomainOntologySeed] = {}

    async def resolve_seed(self, slug: str) -> DomainOntologySeed:
        """Resolve a seed for the given domain slug.

        Resolution order:
        1. Static seed in DOMAIN_SEEDS
        2. Runtime cache hit
        3. Parent inheritance (if domain has a parent)
        4. LLM generation
        """
        # 1. Static seed
        if slug in DOMAIN_SEEDS:
            return DOMAIN_SEEDS[slug]

        # 2. Runtime cache
        if slug in self._cache:
            logger.debug("seed_cache_hit", slug=slug)
            return self._cache[slug]

        # 3. Parent inheritance
        parent_seed = await self._resolve_parent_seed(slug)

        # 4. LLM generation (with parent context if available)
        seed = await self._generate_seed(slug, parent_seed=parent_seed)
        self._cache[slug] = seed

        logger.bind(action_log=True).info(
            "seed_generated",
            slug=slug,
            node_types=len(seed.node_types),
            edge_types=len(seed.edge_types),
            has_parent_context=parent_seed is not None,
        )
        return seed

    async def _resolve_parent_seed(self, slug: str) -> DomainOntologySeed | None:
        """Look up the parent domain and return its seed, if any."""
        domain = await self._domain_service.get_domain(slug)
        if domain is None or domain.parent_id is None:
            return None

        # Build id -> domain map to resolve parent
        all_domains = await self._domain_service.list_domains()
        id_to_domain = {d.id: d for d in all_domains if d.id is not None}

        parent = id_to_domain.get(domain.parent_id)
        if parent is None:
            return None

        # Recursively resolve parent's seed (may be static, cached, or generated)
        return await self.resolve_seed(parent.slug)

    async def _generate_seed(
        self,
        slug: str,
        parent_seed: DomainOntologySeed | None = None,
    ) -> DomainOntologySeed:
        """Generate a seed via LLM structured output."""
        domain = await self._domain_service.get_domain(slug)
        domain_name = domain.name if domain else slug
        domain_desc = domain.description if domain else ""

        parent_context = ""
        if parent_seed is not None:
            parent_node_list = ", ".join(parent_seed.node_types.keys())
            parent_edge_list = ", ".join(parent_seed.edge_types.keys())
            parent_context = (
                f"\n\nThis domain is a child of a parent domain that uses these types:\n"
                f"Node types: {parent_node_list}\n"
                f"Edge types: {parent_edge_list}\n"
                f"Include relevant parent types and add domain-specific ones."
            )

        prompt = (
            "You are an ontology designer for a knowledge graph memory system.\n"
            f"Generate recommended node types and edge types for the domain: '{domain_name}'.\n"
            f"Domain description: {domain_desc}\n"
            f"{parent_context}\n\n"
            "Generate 8-15 node types and 8-15 edge types that would be useful for "
            "storing knowledge in this domain.\n"
            "Each type should have a short description (under 10 words).\n"
            "Return a DomainOntologySeed with node_types and edge_types as "
            "dictionaries mapping type names to descriptions."
        )

        agent: Agent[None, DomainOntologySeed] = Agent(  # ty: ignore[invalid-assignment]
            build_model(self._model, self._local_endpoint),
            output_type=DomainOntologySeed,
            system_prompt=prompt,
        )

        result = await agent.run(
            f"Generate ontology seed types for: {domain_name} - {domain_desc}",
            model_settings=build_model_settings(self._thinking_effort, self._model, self._local_endpoint),
        )
        return result.output
