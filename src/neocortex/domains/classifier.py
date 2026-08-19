"""Domain classification: PydanticAI agent and deterministic mock.

The DomainClassifier protocol classifies incoming knowledge text into one or
more semantic domains from the upper ontology.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from loguru import logger
from pydantic_ai import Agent
from pydantic_ai.settings import ThinkingLevel

from neocortex.domains.models import (
    ClassificationResult,
    DomainClassification,
    SemanticDomain,
)
from neocortex.model_factory import LocalEndpoint, build_model, build_model_settings


@runtime_checkable
class DomainClassifier(Protocol):
    async def classify(self, text: str, domains: list[SemanticDomain]) -> ClassificationResult: ...


def format_domain_tree(domains: list[SemanticDomain]) -> str:
    """Format domains as an indented tree using depth field.

    Each line: ``{"  " * depth}{slug}: {description}``
    """
    lines: list[str] = []
    for d in sorted(domains, key=lambda d: d.path or d.slug):
        indent = "  " * d.depth
        lines.append(f"{indent}{d.slug}: {d.description}")
    return "\n".join(lines)


class AgentDomainClassifier:
    """PydanticAI-based domain classifier."""

    def __init__(
        self,
        # Plan 33 introduces an opt-in local: model route; Stage 9 changes defaults after the gate.
        model_name: str = "openai-responses:gpt-5.4-mini",
        thinking_effort: ThinkingLevel = "medium",
        local_endpoint: LocalEndpoint | None = None,
    ) -> None:
        self._model_name = model_name
        self._thinking_effort = thinking_effort
        self._local_endpoint = local_endpoint

    async def classify(self, text: str, domains: list[SemanticDomain]) -> ClassificationResult:
        if not domains:
            logger.warning("classifier_received_empty_domains")
            return ClassificationResult(matched_domains=[], proposed_domain=None)

        domain_tree = format_domain_tree(domains)
        prompt = (
            "You are a knowledge classification agent for a memory system.\n"
            "Classify incoming knowledge into one or more semantic domains.\n\n"
            "DOMAIN TREE (indented children are sub-domains):\n"
            f"{domain_tree}\n\n"
            "GUIDELINES:\n"
            "- MULTI-LABEL: a single piece of knowledge may belong to multiple domains.\n"
            "- SPECIFIC: prefer the most specific matching domain. "
            "If a child domain fits, use it instead of the parent.\n"
            "- PROPOSE NEW DOMAINS: if the knowledge does not fit well into ANY existing domain, "
            "propose a new domain. Novel content deserves its own domain rather than being forced "
            "into a poor fit.\n"
            "- HIERARCHY: when proposing a new domain, set parent_slug to the slug of the most "
            "relevant existing parent domain if one exists. Example: proposing 'rust' under "
            "'technical_knowledge'. Leave parent_slug null for genuinely new top-level categories.\n"
            "- domain_knowledge is NOT a default catch-all. Only route content there if it is "
            "genuinely about general factual/industry/scientific knowledge.\n"
            "- Set confidence >= 0.3 for relevant domains, higher for strong matches.\n"
            "- If nothing fits, return empty matched_domains and propose a new domain.\n\n"
            "Classify the following knowledge text. Return matched domains with confidence scores, "
            "and optionally a proposed_domain if no existing domain is a good fit."
        )

        agent: Agent[None, ClassificationResult] = Agent(  # ty: ignore[invalid-assignment]
            build_model(self._model_name, self._local_endpoint),
            output_type=ClassificationResult,
            system_prompt=prompt,
        )

        result = await agent.run(
            text,
            model_settings=build_model_settings(self._thinking_effort, self._model_name, self._local_endpoint),
        )
        logger.debug(
            "classification_result",
            matched_count=len(result.output.matched_domains),
            proposed=result.output.proposed_domain is not None,
        )

        # Fallback: if LLM returned no matches and no proposal, try keyword matching
        if not result.output.matched_domains and result.output.proposed_domain is None:
            return self._keyword_fallback(text, domains)

        return result.output

    def _keyword_fallback(self, text: str, domains: list[SemanticDomain]) -> ClassificationResult:
        """Keyword-based classification fallback when LLM returns no matches.

        Only matches domains that actually exist in the provided list.
        Does NOT silently default to domain_knowledge.
        """
        text_lower = text.lower()
        domain_slugs = {d.slug for d in domains}
        matches: list[DomainClassification] = []

        for slug, keywords in _KEYWORD_MAP.items():
            if slug not in domain_slugs:
                continue
            if any(kw in text_lower for kw in keywords):
                matches.append(
                    DomainClassification(
                        domain_slug=slug,
                        confidence=0.6,
                        reasoning="keyword_fallback",
                    )
                )

        return ClassificationResult(matched_domains=matches, proposed_domain=None)


# ── Keyword maps for the mock classifier ──

_KEYWORD_MAP: dict[str, list[str]] = {
    "user_profile": [
        "prefer",
        "goal",
        "habit",
        "like",
        "dislike",
        "want",
        "value",
        "opinion",
    ],
    "technical_knowledge": [
        "python",
        "react",
        "api",
        "database",
        "framework",
        "library",
        "code",
        "architecture",
    ],
    "work_context": [
        "project",
        "task",
        "deadline",
        "meeting",
        "team",
        "milestone",
        "sprint",
    ],
    "domain_knowledge": [
        "concept",
        "theory",
        "fact",
        "research",
        "trend",
        "industry",
    ],
}


class MockDomainClassifier:
    """Deterministic keyword-based classifier for tests.

    Does NOT default unmatched text to domain_knowledge. Unmatched text
    returns an empty matched_domains list (no silent catch-all).
    """

    async def classify(self, text: str, domains: list[SemanticDomain]) -> ClassificationResult:
        text_lower = text.lower()
        domain_slugs = {d.slug for d in domains}
        matched: list[DomainClassification] = []

        for slug, keywords in _KEYWORD_MAP.items():
            if slug not in domain_slugs:
                continue
            if any(kw in text_lower for kw in keywords):
                matched.append(
                    DomainClassification(
                        domain_slug=slug,
                        confidence=0.8,
                        reasoning=f"Keyword match for domain '{slug}'",
                    )
                )

        return ClassificationResult(matched_domains=matched)
