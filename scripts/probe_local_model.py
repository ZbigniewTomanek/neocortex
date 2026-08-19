"""Probe NeoCortex's four PydanticAI agents against a local OpenAI-compatible model.

The script deliberately records failures instead of hiding them. It is usable offline
for harness validation, but live ontology/librarian tool behavior requires PostgreSQL
(``./scripts/manage.sh start``) and a configured local endpoint.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

from corpus_loader import load_probe_corpus  # ty: ignore[unresolved-import]
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.settings import ThinkingLevel

from neocortex.db.mock import InMemoryRepository
from neocortex.domains.classifier import AgentDomainClassifier
from neocortex.domains.models import SEED_DOMAINS
from neocortex.extraction.agents import (
    AgentInferenceConfig,
    ExtractorAgentDeps,
    LibrarianAgentDeps,
    OntologyAgentDeps,
    build_extractor_agent,
    build_librarian_agent,
    build_ontology_agent,
)
from neocortex.extraction.schemas import ExtractedEntity, ExtractedRelation
from neocortex.mcp_settings import MCPSettings
from neocortex.model_factory import LocalEndpoint

AGENT_NAMES = ("ontology", "extractor", "librarian", "domain_classifier")
REFUSAL_MARKERS = ("i can't verify", "i have no record", "i don't have access")


def _usage(result: Any) -> dict[str, Any]:
    usage = result.usage()
    data = usage.model_dump() if hasattr(usage, "model_dump") else vars(usage)
    details = data.get("details") or {}
    return {
        "requests": data.get("requests"),
        "prompt_tokens": data.get("request_tokens"),
        "completion_tokens": data.get("response_tokens"),
        "reasoning_tokens": details.get("reasoning_tokens"),
        "details": details,
    }


def _messages(result: Any) -> tuple[list[str], str]:
    names: list[str] = []
    raw: list[str] = []
    for message in result.all_messages():
        for part in getattr(message, "parts", []):
            if isinstance(part, ToolCallPart):
                names.append(part.tool_name)
            if hasattr(part, "content") and isinstance(part.content, str):
                raw.append(part.content)
    return names, "\n".join(raw)


def _exception_output(exc: BaseException) -> str:
    for attr in ("raw_output", "body", "output"):
        value = getattr(exc, attr, None)
        if value:
            return str(value)
    return str(exc)


async def _run_with_timeout(awaitable: Any, timeout_s: float) -> Any:
    return await asyncio.wait_for(awaitable, timeout=timeout_s)


async def _probe_extraction_agent(kind: str, text: str, config: AgentInferenceConfig, repo: InMemoryRepository) -> Any:
    if kind == "ontology":
        agent = build_ontology_agent(config)
        return await agent.run(
            f"Analyze this text and propose ontology extensions:\n\n{text}",
            deps=OntologyAgentDeps(
                episode_text=text,
                existing_node_types=["Database", "SoftwareComponent", "Date", "Location"],
                existing_edge_types=["USES", "LOCATED_IN", "CORRECTS", "SUPERSEDES"],
                repo=repo,
                agent_id="probe",
            ),
            model_settings=config.model_settings,
        )
    if kind == "extractor":
        agent = build_extractor_agent(config)
        return await agent.run(
            f"Extract entities and relations from:\n\n{text}",
            deps=ExtractorAgentDeps(
                episode_text=text,
                node_types=["Database", "SoftwareComponent", "Date", "Location", "Vehicle", "Presentation"],
                edge_types=["USES", "LOCATED_IN", "CORRECTS", "SUPERSEDES"],
            ),
            model_settings=config.model_settings,
        )
    agent = build_librarian_agent(config, use_tools=True)
    node_type = await repo.get_or_create_node_type("probe", "SoftwareComponent", "A software component")
    edge_type = await repo.get_or_create_edge_type("probe", "USES", "Uses relationship")
    assert node_type is not None and edge_type is not None
    return await agent.run(
        "Curate the extracted knowledge into the graph.",
        deps=LibrarianAgentDeps(
            episode_text=text,
            node_types=["SoftwareComponent"],
            edge_types=["USES"],
            extracted_entities=[
                ExtractedEntity(name="PostgreSQL", type_name="SoftwareComponent", description=text),
                ExtractedEntity(name="NeoCortex", type_name="SoftwareComponent", description="Memory system"),
            ],
            extracted_relations=[
                ExtractedRelation(source_name="NeoCortex", target_name="PostgreSQL", relation_type="USES")
            ],
            repo=repo,
            embeddings=None,
            agent_id="probe",
        ),
        model_settings=config.model_settings,
    )


async def _probe_one(
    kind: str,
    episode_id: str,
    text: str,
    config: AgentInferenceConfig,
    timeout_s: float,
) -> dict[str, Any]:
    started = time.monotonic()
    record: dict[str, Any] = {
        "agent": kind,
        "episode": episode_id,
        "status": "failure",
        "tool_calls": [],
        "raw_output": "",
    }
    try:
        result = await _run_with_timeout(_probe_extraction_agent(kind, text, config, InMemoryRepository()), timeout_s)
        tool_calls, raw_output = _messages(result)
        record.update(status="success", tool_calls=tool_calls, raw_output=raw_output, usage=_usage(result))
        record["refusal_mode"] = not tool_calls and any(marker in raw_output.lower() for marker in REFUSAL_MARKERS)
    except TimeoutError:
        record.update(
            status="timeout", exception_type="TimeoutError", raw_output="timeout before a result was returned"
        )
    except Exception as exc:  # probe output must retain every failure
        record.update(status="failure", exception_type=type(exc).__name__, raw_output=_exception_output(exc))
    record["elapsed_s"] = round(time.monotonic() - started, 3)
    return record


async def _probe_classifier(
    episode_id: str, text: str, model: str, effort: ThinkingLevel, endpoint: LocalEndpoint | None, timeout_s: float
) -> dict[str, Any]:
    started = time.monotonic()
    classifier = AgentDomainClassifier(model_name=model, thinking_effort=effort, local_endpoint=endpoint)
    record: dict[str, Any] = {"agent": "domain_classifier", "episode": episode_id, "tool_calls": [], "raw_output": ""}
    try:
        output = await _run_with_timeout(classifier.classify(text, SEED_DOMAINS), timeout_s)
        result = classifier._last_run_result
        usage = _usage(result) if result is not None else None
        tool_calls, raw_output = _messages(result) if result is not None else ([], "")
        record.update(
            status="success", output=output.model_dump(), usage=usage, tool_calls=tool_calls, raw_output=raw_output
        )
    except TimeoutError:
        record.update(
            status="timeout", exception_type="TimeoutError", raw_output="timeout before a result was returned"
        )
    except Exception as exc:
        record.update(status="failure", exception_type=type(exc).__name__, raw_output=_exception_output(exc))
    record["elapsed_s"] = round(time.monotonic() - started, 3)
    return record


async def run(args: argparse.Namespace) -> dict[str, Any]:
    settings = MCPSettings()
    endpoint = LocalEndpoint.from_settings(settings)
    config = AgentInferenceConfig(model_name=args.model, thinking_effort=args.effort, local_endpoint=endpoint)
    corpus = load_probe_corpus(args.corpus)
    jobs = [
        (attempt, episode_id, text, kind)
        for attempt in range(1, args.repeats + 1)
        for episode_id, text in corpus
        for kind in (*("ontology", "extractor", "librarian"), "domain_classifier")
    ]
    semaphore = asyncio.Semaphore(args.concurrency)

    async def run_job(job: tuple[int, str, str, str]) -> dict[str, Any]:
        attempt, episode_id, text, kind = job
        async with semaphore:
            if kind == "domain_classifier":
                record = await _probe_classifier(episode_id, text, args.model, args.effort, endpoint, args.timeout)
            else:
                record = await _probe_one(kind, episode_id, text, config, args.timeout)
        record["attempt"] = attempt
        return record

    records = await asyncio.gather(*(run_job(job) for job in jobs))
    return {
        "model": args.model,
        "effort": args.effort,
        "repeats": args.repeats,
        "concurrency": args.concurrency,
        "records": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--effort", choices=["low", "medium", "high", "xhigh"], default="medium")
    parser.add_argument("--model", default="local:qwen3.8-27b")
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = (
        args.output
        or Path(__file__).parents[1] / f"docs/plans/33-local-qwen-migration/resources/probe-results-{args.effort}.json"
    )
    result = asyncio.run(run(args))
    output.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(f"Wrote {output} ({len(result['records'])} attempts)")


if __name__ == "__main__":
    main()
