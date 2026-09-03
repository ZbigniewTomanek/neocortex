"""Probe NeoCortex's four PydanticAI agents against a local OpenAI-compatible model.

The script deliberately records failures instead of hiding them. It is usable offline
for harness validation, but live ontology/librarian tool behavior requires PostgreSQL
(``./scripts/manage.sh start``) and a configured local endpoint.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from corpus_loader import load_probe_corpus  # ty: ignore[unresolved-import]
from pydantic_ai.messages import RetryPromptPart, ToolCallPart, ToolReturnPart
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
        "tool_calls": data.get("tool_calls"),
        "prompt_tokens": data.get("input_tokens", data.get("request_tokens")),
        "completion_tokens": data.get("output_tokens", data.get("response_tokens")),
        "reasoning_tokens": details.get("reasoning_tokens"),
        "details": details,
    }


def _messages(result: Any) -> tuple[list[str], str, int, list[str]]:
    names: list[str] = []
    raw: list[str] = []
    retry_count = 0
    normalization_rejections: list[str] = []
    for message in result.all_messages():
        for part in getattr(message, "parts", []):
            if isinstance(part, ToolCallPart):
                names.append(part.tool_name)
            if isinstance(part, RetryPromptPart):
                retry_count += 1
            if hasattr(part, "content") and isinstance(part.content, str):
                raw.append(part.content)
            if isinstance(part, ToolReturnPart):
                content = part.content
                if isinstance(content, dict) and content.get("accepted") is False:
                    normalization_rejections.append(str(content.get("reason", "rejected")))
                elif isinstance(content, str) and re.search(r'"accepted"\s*:\s*false', content, re.IGNORECASE):
                    normalization_rejections.append(content)
    return names, "\n".join(raw), retry_count, normalization_rejections


def _output_dump(result: Any) -> Any:
    output = getattr(result, "output", None)
    if hasattr(output, "model_dump"):
        return output.model_dump(mode="json")
    return output


def _redact(text: str) -> str:
    """Remove bearer values from exception text before it enters evidence."""
    text = re.sub(r"(?i)(bearer\s+)[^\s,;}]+", r"\1<redacted>", text)
    for name in ("LITELLM_API_KEY", "VLLM_API_KEY"):
        value = os.environ.get(name)
        if value:
            text = text.replace(value, "<redacted>")
    return text


def _exception_output(exc: BaseException) -> str:
    for attr in ("raw_output", "body", "output"):
        value = getattr(exc, attr, None)
        if value:
            return _redact(str(value))
    return _redact(str(exc))


def _failure_class(exc: BaseException, raw_output: str) -> str:
    """Classify a failed call without collapsing transport and model failures."""
    text = raw_output.lower()
    if "system message must be at the beginning" in text:
        return "http_400_system_message_order"
    if re.search(r"(?:http|status|status_code)[^\n]{0,20}400", text) or "bad request" in text:
        return "http_400"
    if any(marker in text for marker in REFUSAL_MARKERS):
        return "model_refusal"
    if "empty" in text and ("content" in text or "output" in text):
        return "empty_content"
    if "validation" in text or "structured output" in text or "invalid json" in text:
        return "invalid_structured_output"
    if "argument" in text and ("tool" in text or "function" in text):
        return "malformed_tool_arguments"
    return type(exc).__name__


def _record_base(
    kind: str,
    episode_id: str,
    text: str,
    model: str,
    effort: ThinkingLevel | None,
    timeout_s: float,
    source_path: str,
) -> dict[str, Any]:
    return {
        "agent": kind,
        "episode": episode_id,
        "model": model,
        "effort": effort,
        "timeout_s": timeout_s,
        "input_source": source_path,
        "input_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "status": "failure",
        "outcome": "failure",
        "tool_calls": [],
        "retries": None,
        "normalization_rejections": [],
        "raw_output": "",
        "raw_validation_output": None,
        "usage": None,
    }


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
    source_path: str,
) -> dict[str, Any]:
    started = time.monotonic()
    record = _record_base(kind, episode_id, text, config.model_name, config.thinking_effort, timeout_s, source_path)
    try:
        result = await _run_with_timeout(_probe_extraction_agent(kind, text, config, InMemoryRepository()), timeout_s)
        tool_calls, raw_output, retries, rejections = _messages(result)
        record.update(
            status="success",
            outcome="success",
            tool_calls=tool_calls,
            retries=retries,
            normalization_rejections=rejections,
            raw_output=raw_output,
            raw_validation_output=_output_dump(result),
            usage=_usage(result),
        )
        record["refusal_mode"] = not tool_calls and any(marker in raw_output.lower() for marker in REFUSAL_MARKERS)
    except TimeoutError:
        record.update(
            status="timeout",
            outcome="timeout",
            exception_type="TimeoutError",
            failure_class="timeout",
            raw_output="timeout before a result was returned",
        )
    except Exception as exc:  # probe output must retain every failure
        raw_output = _exception_output(exc)
        record.update(
            status="failure",
            outcome="failure",
            exception_type=type(exc).__name__,
            failure_class=_failure_class(exc, raw_output),
            raw_output=raw_output,
        )
    record["elapsed_s"] = round(time.monotonic() - started, 3)
    return record


async def _probe_classifier(
    episode_id: str,
    text: str,
    model: str,
    effort: ThinkingLevel,
    endpoint: LocalEndpoint | None,
    timeout_s: float,
    source_path: str,
) -> dict[str, Any]:
    started = time.monotonic()
    classifier = AgentDomainClassifier(model_name=model, thinking_effort=effort, local_endpoint=endpoint)
    record = _record_base("domain_classifier", episode_id, text, model, effort, timeout_s, source_path)
    try:
        output = await _run_with_timeout(classifier.classify(text, SEED_DOMAINS), timeout_s)
        result = classifier._last_run_result
        usage = _usage(result) if result is not None else None
        tool_calls, raw_output, retries, rejections = _messages(result) if result is not None else ([], "", None, [])
        record.update(
            status="success",
            outcome="success",
            output=output.model_dump(mode="json"),
            raw_validation_output=_output_dump(result) if result is not None else None,
            usage=usage,
            tool_calls=tool_calls,
            retries=retries,
            normalization_rejections=rejections,
            raw_output=raw_output,
        )
    except TimeoutError:
        record.update(
            status="timeout",
            outcome="timeout",
            exception_type="TimeoutError",
            failure_class="timeout",
            raw_output="timeout before a result was returned",
        )
    except Exception as exc:
        raw_output = _exception_output(exc)
        record.update(
            status="failure",
            outcome="failure",
            exception_type=type(exc).__name__,
            failure_class=_failure_class(exc, raw_output),
            raw_output=raw_output,
        )
    record["elapsed_s"] = round(time.monotonic() - started, 3)
    return record


async def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.timeout < 300:
        raise ValueError("Stage 2 probes require a timeout of at least 300 seconds")
    settings = MCPSettings(_env_file=None)  # ty: ignore[unknown-argument]
    endpoint = LocalEndpoint.from_settings(settings)
    config = AgentInferenceConfig(model_name=args.model, thinking_effort=args.effort, local_endpoint=endpoint)
    corpus = load_probe_corpus(args.corpus)
    source_path = str(
        args.corpus or Path(__file__).parents[1] / "docs/plans/33-local-qwen-migration/resources/probe-corpus.md"
    )
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
                record = await _probe_classifier(
                    episode_id, text, args.model, args.effort, endpoint, args.timeout, source_path
                )
            else:
                record = await _probe_one(kind, episode_id, text, config, args.timeout, source_path)
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
