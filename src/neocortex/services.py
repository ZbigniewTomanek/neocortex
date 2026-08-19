from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from neocortex.domains.router import DomainRouter
    from neocortex.domains.seed_generator import SeedGenerator

import procrastinate
import procrastinate.exceptions

from neocortex.config import PostgresConfig
from neocortex.db.adapter import GraphServiceAdapter
from neocortex.db.mock import InMemoryRepository
from neocortex.embedding_service import EmbeddingService
from neocortex.graph_router import GraphRouter
from neocortex.graph_service import GraphService
from neocortex.mcp_settings import MCPSettings
from neocortex.migrations import MigrationRunner
from neocortex.model_factory import LocalEndpoint
from neocortex.permissions import InMemoryPermissionService, PostgresPermissionService
from neocortex.permissions.protocol import PermissionChecker
from neocortex.postgres_service import PostgresService
from neocortex.schema_manager import SchemaManager


class ServiceContext(TypedDict):
    repo: GraphServiceAdapter | InMemoryRepository
    pg: PostgresService | None
    graph: GraphService | None
    schema_mgr: SchemaManager | None
    router: GraphRouter | None
    settings: MCPSettings
    embeddings: EmbeddingService | None
    job_app: procrastinate.App | None
    permissions: PermissionChecker
    domain_router: DomainRouter | None
    seed_generator: SeedGenerator | None
    local_endpoint: LocalEndpoint


async def create_services(settings: MCPSettings) -> ServiceContext:
    """Initialize the full NeoCortex service stack.

    When ``settings.mock_db`` is True, returns an in-memory repository
    with ``None`` for all PostgreSQL-backed services.
    """
    local_endpoint = LocalEndpoint.from_settings(settings)
    if settings.mock_db:
        mem_permissions = InMemoryPermissionService(settings.bootstrap_admin_id)
        await mem_permissions.ensure_admin(settings.bootstrap_admin_id)
        permissions: PermissionChecker = mem_permissions

        domain_router: DomainRouter | None = None
        mock_seed_gen: SeedGenerator | None = None
        if settings.domain_routing_enabled:
            from neocortex.domains import InMemoryDomainService
            from neocortex.domains.classifier import MockDomainClassifier
            from neocortex.domains.models import SEED_DOMAINS
            from neocortex.domains.router import DomainRouter
            from neocortex.domains.seed_generator import SeedGenerator

            domain_svc = InMemoryDomainService()
            await domain_svc.seed_defaults()

            # Register seed domain schemas as shared in the in-memory permission service
            for domain in SEED_DOMAINS:
                if domain.schema_name:
                    mem_permissions.register_shared_schema(domain.schema_name)

            mock_seed_gen = SeedGenerator(
                domain_service=domain_svc,
                model=settings.domain_classifier_model,
                thinking_effort=settings.seed_generator_thinking_effort,
                local_endpoint=local_endpoint,
            )

            domain_router = DomainRouter(
                domain_service=domain_svc,
                classifier=MockDomainClassifier(),
                schema_mgr=None,
                permissions=permissions,
                job_app=None,
                classification_threshold=settings.domain_classification_threshold,
                seed_generator=mock_seed_gen,
            )

        return ServiceContext(
            repo=InMemoryRepository(),
            pg=None,
            graph=None,
            schema_mgr=None,
            router=None,
            settings=settings,
            embeddings=None,
            job_app=None,
            permissions=permissions,
            domain_router=domain_router,
            seed_generator=mock_seed_gen,
            local_endpoint=local_endpoint,
        )

    pg_config = PostgresConfig()
    pg = PostgresService(pg_config)
    await pg.connect()

    migration_runner = MigrationRunner(pg)
    await migration_runner.run_public()

    graph = GraphService(pg)
    schema_mgr = SchemaManager(pg, migration_runner)
    await schema_mgr.create_graph("shared", "knowledge", is_shared=True)
    pg_permissions: PermissionChecker = PostgresPermissionService(pg, settings.bootstrap_admin_id)
    await pg_permissions.ensure_admin(settings.bootstrap_admin_id)
    router = GraphRouter(schema_mgr, pg.pool, permissions=pg_permissions)
    repo = GraphServiceAdapter(graph, router=router, pool=pg.pool, pg=pg, settings=settings)
    embeddings = EmbeddingService(model=settings.embedding_model)

    # Domain routing services (upper ontology)
    domain_svc = None
    domain_classifier = None
    if settings.domain_routing_enabled:
        from neocortex.domains import PostgresDomainService
        from neocortex.domains.classifier import AgentDomainClassifier
        from neocortex.domains.models import SEED_DOMAINS

        domain_svc = PostgresDomainService(pg)
        await domain_svc.seed_defaults()

        # Provision PG schemas for seed domains
        for domain in SEED_DOMAINS:
            if domain.schema_name:
                await schema_mgr.create_graph(agent_id="shared", purpose=domain.slug, is_shared=True)

        domain_classifier = AgentDomainClassifier(
            model_name=settings.domain_classifier_model,
            thinking_effort=settings.domain_classifier_thinking_effort,
            local_endpoint=local_endpoint,
        )

    await migration_runner.run_graph_schemas()

    # Procrastinate job queue (only when extraction is enabled with real DB)
    job_app: procrastinate.App | None = None
    if settings.extraction_enabled:
        from neocortex.jobs import create_job_app

        job_app = create_job_app(pg_config.dsn)
        await job_app.open_async()
        with contextlib.suppress(procrastinate.exceptions.ConnectorException):
            await job_app.schema_manager.apply_schema_async()

    # Create domain router after job_app (needs it for enqueuing)
    pg_domain_router: DomainRouter | None = None
    pg_seed_gen: SeedGenerator | None = None
    if settings.domain_routing_enabled and domain_svc is not None and domain_classifier is not None:
        from neocortex.domains.router import DomainRouter
        from neocortex.domains.seed_generator import SeedGenerator

        pg_seed_gen = SeedGenerator(
            domain_service=domain_svc,
            model=settings.domain_classifier_model,
            thinking_effort=settings.seed_generator_thinking_effort,
            local_endpoint=local_endpoint,
        )

        pg_domain_router = DomainRouter(
            domain_service=domain_svc,
            classifier=domain_classifier,
            schema_mgr=schema_mgr,
            permissions=pg_permissions,
            job_app=job_app,
            classification_threshold=settings.domain_classification_threshold,
            seed_generator=pg_seed_gen,
        )

    ctx = ServiceContext(
        repo=repo,
        pg=pg,
        graph=graph,
        schema_mgr=schema_mgr,
        router=router,
        settings=settings,
        embeddings=embeddings,
        job_app=job_app,
        permissions=pg_permissions,
        domain_router=pg_domain_router,
        seed_generator=pg_seed_gen,
        local_endpoint=local_endpoint,
    )

    # Make services available to Procrastinate task handlers
    if job_app is not None:
        from neocortex.jobs.context import set_services

        set_services(ctx)

    return ctx


async def shutdown_services(ctx: ServiceContext) -> None:
    """Shut down services, closing the PostgreSQL connection pool if open."""
    job_app = ctx.get("job_app")
    if job_app is not None:
        await job_app.close_async()

    pg = ctx.get("pg")
    if pg is not None:
        await pg.disconnect()
