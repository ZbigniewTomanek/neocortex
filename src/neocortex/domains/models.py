from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class SemanticDomain(BaseModel):
    """A semantic domain in the upper ontology."""

    id: int | None = None
    slug: str
    name: str
    description: str
    schema_name: str | None = None
    seed: bool = False
    created_at: datetime | None = None
    created_by: str | None = None
    parent_id: int | None = None
    depth: int = 0
    path: str = ""
    children: list[SemanticDomain] = Field(default_factory=list)


class DomainClassification(BaseModel):
    """A single domain match from the classifier.

    ``confidence`` is clamped rather than rejected, and ``reasoning`` is
    informational: a local model that answers 1.2 or omits its rationale is
    still a usable classification, and rejecting it costs a whole retry.
    """

    domain_slug: str
    confidence: float = Field(ge=0, le=1)
    reasoning: str = ""

    @field_validator("confidence", mode="before")
    @classmethod
    def clamp_confidence(cls, value: object) -> object:
        if isinstance(value, int | float) and not isinstance(value, bool):
            return min(1.0, max(0.0, float(value)))
        return value


class ProposedDomain(BaseModel):
    """A new domain proposal from the classifier."""

    slug: str
    name: str
    description: str = ""
    reasoning: str = ""
    parent_slug: str | None = None


class ClassificationResult(BaseModel):
    """Full classification output from the domain classifier."""

    matched_domains: list[DomainClassification] = []
    proposed_domain: ProposedDomain | None = None


class RoutingResult(BaseModel):
    """Result of routing an episode to a shared schema."""

    domain_slug: str
    schema_name: str
    confidence: float
    extraction_job_id: int | None = None


SEED_DOMAINS = [
    SemanticDomain(
        slug="user_profile",
        name="User Profile & Preferences",
        description=(
            "Personal preferences, goals, habits, values, opinions, communication style, "
            "routines, and work style preferences. Knowledge about what the user likes, "
            "dislikes, wants to achieve, and how they prefer to work."
        ),
        schema_name="ncx_shared__user_profile",
        seed=True,
        parent_id=None,
        depth=0,
        path="user_profile",
    ),
    SemanticDomain(
        slug="technical_knowledge",
        name="Technical Knowledge",
        description=(
            "Programming languages, frameworks, libraries, tools, architecture patterns, "
            "APIs, technical concepts, best practices, and engineering approaches. Knowledge "
            "about technologies, how they work, and how to use them."
        ),
        schema_name="ncx_shared__technical_knowledge",
        seed=True,
        parent_id=None,
        depth=0,
        path="technical_knowledge",
    ),
    SemanticDomain(
        slug="work_context",
        name="Work & Projects",
        description=(
            "Ongoing projects, tasks, deadlines, team members, organizations, meetings, "
            "decisions, and professional activities. Knowledge about what is being worked "
            "on, by whom, and when."
        ),
        schema_name="ncx_shared__work_context",
        seed=True,
        parent_id=None,
        depth=0,
        path="work_context",
    ),
    SemanticDomain(
        slug="domain_knowledge",
        name="Domain Knowledge",
        description=(
            "General factual knowledge, industry concepts, scientific facts, business "
            "concepts, market trends, and domain-specific expertise. Broad knowledge "
            "that does not fit the other specific categories."
        ),
        schema_name="ncx_shared__domain_knowledge",
        seed=True,
        parent_id=None,
        depth=0,
        path="domain_knowledge",
    ),
]
