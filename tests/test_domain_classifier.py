from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from loguru import logger
from pydantic_ai.models.test import TestModel

from neocortex.domains import InMemoryDomainService
from neocortex.domains.classifier import (
    AgentDomainClassifier,
    DomainClassifier,
    MockDomainClassifier,
    format_domain_tree,
)
from neocortex.domains.models import ClassificationResult, SemanticDomain


class TestFormatDomainTree:
    def test_flat_domains(self) -> None:
        domains = [
            SemanticDomain(slug="a", name="A", description="Domain A", depth=0, path="a"),
            SemanticDomain(slug="b", name="B", description="Domain B", depth=0, path="b"),
        ]
        result = format_domain_tree(domains)
        assert result == "a: Domain A\nb: Domain B"

    def test_nested_domains(self) -> None:
        domains = [
            SemanticDomain(slug="tech", name="Tech", description="Technical", depth=0, path="tech"),
            SemanticDomain(slug="python", name="Python", description="Python lang", depth=1, path="tech.python"),
            SemanticDomain(slug="asyncio", name="Asyncio", description="Async IO", depth=2, path="tech.python.asyncio"),
        ]
        result = format_domain_tree(domains)
        lines = result.split("\n")
        assert lines[0] == "tech: Technical"
        assert lines[1] == "  python: Python lang"
        assert lines[2] == "    asyncio: Async IO"

    def test_sorts_by_path(self) -> None:
        domains = [
            SemanticDomain(slug="z", name="Z", description="Last", depth=0, path="z"),
            SemanticDomain(slug="a", name="A", description="First", depth=0, path="a"),
        ]
        result = format_domain_tree(domains)
        assert result.startswith("a: First")

    def test_empty_domains(self) -> None:
        assert format_domain_tree([]) == ""


class TestMockDomainClassifier:
    @pytest.fixture
    async def domains(self) -> list:
        svc = InMemoryDomainService()
        await svc.seed_defaults()
        return await svc.list_domains()

    @pytest.fixture
    def classifier(self) -> MockDomainClassifier:
        return MockDomainClassifier()

    @pytest.mark.asyncio
    async def test_prefer_python_matches_user_profile_and_technical(
        self, classifier: MockDomainClassifier, domains: list
    ) -> None:
        result = await classifier.classify("I prefer Python for backend work", domains)
        slugs = {m.domain_slug for m in result.matched_domains}
        assert "user_profile" in slugs
        assert "technical_knowledge" in slugs

    @pytest.mark.asyncio
    async def test_project_deadline_matches_work_context(self, classifier: MockDomainClassifier, domains: list) -> None:
        result = await classifier.classify("We need to ship project X by Friday", domains)
        slugs = {m.domain_slug for m in result.matched_domains}
        assert "work_context" in slugs

    @pytest.mark.asyncio
    async def test_react_hooks_matches_technical(self, classifier: MockDomainClassifier, domains: list) -> None:
        result = await classifier.classify("React hooks simplify state management", domains)
        slugs = {m.domain_slug for m in result.matched_domains}
        assert "technical_knowledge" in slugs

    @pytest.mark.asyncio
    async def test_theory_matches_domain_knowledge(self, classifier: MockDomainClassifier, domains: list) -> None:
        result = await classifier.classify("The theory of relativity explains gravitational effects", domains)
        slugs = {m.domain_slug for m in result.matched_domains}
        assert "domain_knowledge" in slugs

    @pytest.mark.asyncio
    async def test_unmatched_text_returns_empty(self, classifier: MockDomainClassifier, domains: list) -> None:
        """Unmatched text returns empty matched_domains — no silent domain_knowledge fallback."""
        result = await classifier.classify("The weather is nice today", domains)
        assert len(result.matched_domains) == 0
        assert result.proposed_domain is None

    @pytest.mark.asyncio
    async def test_all_confidences_above_threshold(self, classifier: MockDomainClassifier, domains: list) -> None:
        texts = [
            "I prefer Python for backend work",
            "We need to ship project X by Friday",
            "React hooks simplify state management",
            "The theory of relativity explains gravitational effects",
        ]
        for text in texts:
            result = await classifier.classify(text, domains)
            for match in result.matched_domains:
                assert match.confidence >= 0.3, f"Confidence {match.confidence} below 0.3 for '{text}'"

    @pytest.mark.asyncio
    async def test_never_proposes_new_domains(self, classifier: MockDomainClassifier, domains: list) -> None:
        result = await classifier.classify("Something completely unrelated to anything", domains)
        assert result.proposed_domain is None

    @pytest.mark.asyncio
    async def test_implements_protocol(self, classifier: MockDomainClassifier) -> None:
        assert isinstance(classifier, DomainClassifier)


class TestAgentDomainClassifierEmptyDomains:
    @pytest.mark.asyncio
    async def test_classifier_empty_domains_returns_empty(self) -> None:
        """Classifier should return empty result when given no domains."""
        classifier = AgentDomainClassifier()
        result = await classifier.classify("some text about Python APIs", domains=[])
        assert len(result.matched_domains) == 0
        assert result.proposed_domain is None


class TestAgentDomainClassifierKeywordFallback:
    @pytest.fixture
    async def domains(self) -> list:
        svc = InMemoryDomainService()
        await svc.seed_defaults()
        return await svc.list_domains()

    @pytest.mark.asyncio
    async def test_keyword_fallback_fires_on_empty_llm_result(self, domains: list) -> None:
        """When LLM returns no matches and no proposal, keyword fallback should fire."""
        classifier = AgentDomainClassifier()

        # Mock the PydanticAI agent.run to return empty ClassificationResult
        mock_result = MagicMock()
        mock_result.output = ClassificationResult(matched_domains=[])

        with patch("neocortex.domains.classifier.Agent") as mock_agent_cls:
            mock_agent_instance = AsyncMock()
            mock_agent_instance.run = AsyncMock(return_value=mock_result)
            mock_agent_cls.return_value = mock_agent_instance

            result = await classifier.classify(
                "Working on the Python API database project",
                domains=domains,
            )

        assert len(result.matched_domains) > 0
        assert any(m.domain_slug == "technical_knowledge" for m in result.matched_domains)
        assert all(m.reasoning == "keyword_fallback" for m in result.matched_domains)

    @pytest.mark.asyncio
    async def test_no_default_to_domain_knowledge(self, domains: list) -> None:
        """When LLM and keywords both miss, returns empty — no domain_knowledge fallback."""
        classifier = AgentDomainClassifier()

        mock_result = MagicMock()
        mock_result.output = ClassificationResult(matched_domains=[])

        with patch("neocortex.domains.classifier.Agent") as mock_agent_cls:
            mock_agent_instance = AsyncMock()
            mock_agent_instance.run = AsyncMock(return_value=mock_result)
            mock_agent_cls.return_value = mock_agent_instance

            result = await classifier.classify(
                "The weather is lovely today",
                domains=domains,
            )

        assert len(result.matched_domains) == 0
        assert result.proposed_domain is None

    @pytest.mark.asyncio
    async def test_keyword_fallback_skipped_when_llm_proposes_domain(self, domains: list) -> None:
        """When LLM returns no matches but proposes a domain, keyword fallback should NOT fire."""
        from neocortex.domains.models import ProposedDomain

        classifier = AgentDomainClassifier()

        mock_result = MagicMock()
        mock_result.output = ClassificationResult(
            matched_domains=[],
            proposed_domain=ProposedDomain(
                slug="weather",
                name="Weather",
                description="Weather and climate",
                reasoning="Novel domain",
            ),
        )

        with patch("neocortex.domains.classifier.Agent") as mock_agent_cls:
            mock_agent_instance = AsyncMock()
            mock_agent_instance.run = AsyncMock(return_value=mock_result)
            mock_agent_cls.return_value = mock_agent_instance

            result = await classifier.classify(
                "The weather is lovely today",
                domains=domains,
            )

        assert len(result.matched_domains) == 0
        assert result.proposed_domain is not None
        assert result.proposed_domain.slug == "weather"

    @pytest.mark.asyncio
    async def test_keyword_fallback_not_used_when_llm_matches(self, domains: list) -> None:
        """When LLM returns matches, keyword fallback should NOT fire."""
        classifier = AgentDomainClassifier()

        from neocortex.domains.models import DomainClassification

        mock_result = MagicMock()
        mock_result.output = ClassificationResult(
            matched_domains=[DomainClassification(domain_slug="work_context", confidence=0.8, reasoning="LLM match")]
        )

        with patch("neocortex.domains.classifier.Agent") as mock_agent_cls:
            mock_agent_instance = AsyncMock()
            mock_agent_instance.run = AsyncMock(return_value=mock_result)
            mock_agent_cls.return_value = mock_agent_instance

            result = await classifier.classify(
                "We have a team meeting",
                domains=domains,
            )

        assert len(result.matched_domains) == 1
        assert result.matched_domains[0].domain_slug == "work_context"
        assert result.matched_domains[0].reasoning == "LLM match"


class TestAgentDomainClassifierAudit:
    @pytest.mark.asyncio
    async def test_generated_correlation_joins_hooks_and_usage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """One generated correlation id must identify hooks and the usage event."""
        domain = SemanticDomain(slug="technical", name="Technical", description="Technology", depth=0, path="technical")
        records: list[dict] = []
        sink_id = logger.add(lambda message: records.append(message.record), level="INFO")
        monkeypatch.setattr("neocortex.domains.classifier.build_model", lambda *args, **kwargs: TestModel())
        try:
            classifier = AgentDomainClassifier(thinking_effort="low")
            await classifier.classify("A private technical note", [domain], agent_id="agent-a", episode_id=7)
        finally:
            logger.remove(sink_id)

        audit = [record for record in records if record["extra"].get("action_log")]
        hook_ids = {
            record["extra"].get("correlation_id")
            for record in audit
            if record["message"] in {"model_request_started", "model_request_completed", "agent_run_completed"}
        }
        usage_ids = {record["extra"].get("correlation_id") for record in audit if record["message"] == "agent_usage"}
        assert len(hook_ids) == 1
        assert usage_ids == hook_ids
        assert None not in hook_ids
