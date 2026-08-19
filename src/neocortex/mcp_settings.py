from typing import Literal

from pydantic_ai.settings import ThinkingLevel
from pydantic_settings import BaseSettings


class MCPSettings(BaseSettings):
    """MCP server configuration. Loaded from env vars with NEOCORTEX_ prefix."""

    model_config = {
        "env_prefix": "NEOCORTEX_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    # Server
    server_name: str = "NeoCortex"
    server_host: str = "0.0.0.0"
    server_port: int = 8000
    transport: Literal["stdio", "http", "sse", "streamable-http"] = "http"

    # Authentication — "none" | "dev_token" | "google_oauth" | "auth0"
    #  - none: no auth, all requests are anonymous
    #  - dev_token: static bearer token for testing (no browser flow needed)
    #  - google_oauth: full Google OAuth via FastMCP OAuthProxy
    #  - auth0: Auth0 OAuth/JWT via FastMCP Auth0Provider
    auth_mode: Literal["none", "dev_token", "google_oauth", "auth0"] = "none"

    # Dev-token auth (used when auth_mode = "dev_token")
    dev_token: str = "dev-token-neocortex"  # Deprecated single-token fallback
    dev_user_id: str = "dev-user"  # Deprecated single-user fallback
    dev_tokens_file: str = ""  # Optional JSON mapping {token: agent_id}

    # Google OAuth (used when auth_mode = "google_oauth")
    google_client_id: str = ""
    google_client_secret: str = ""
    oauth_base_url: str = "http://localhost:8000"

    # Auth0 (used when auth_mode = "auth0")
    auth0_domain: str = ""  # e.g., "dev-xxx.us.auth0.com"
    auth0_client_id: str = ""  # Regular Web App client ID
    auth0_client_secret: str = ""  # Regular Web App client secret
    auth0_audience: str = ""  # API identifier (audience)
    auth0_m2m_client_id: str = ""  # M2M app client ID (for ingestion API)
    auth0_m2m_client_secret: str = ""  # M2M app client secret

    # Embedding model (experimental names may rotate)
    embedding_model: str = "gemini-embedding-001"

    # Hybrid recall weights (normalized at scoring time, so any ratio works)
    recall_weight_vector: float = 0.3
    recall_weight_text: float = 0.2
    # For episodes, a separate STM boost (episode_stm_boost_factor) is applied
    # multiplicatively on top when within episode_stm_window_hours.
    recall_weight_recency: float = 0.15
    recall_recency_half_life_hours: float = 168.0  # 7 days
    # Vector distance threshold: cosine distance below this counts as a match.
    # 0.5 distance = 0.5 similarity. Tune up for stricter matching, down for broader.
    recall_vector_distance_threshold: float = 0.5

    # Cognitive heuristic weights (wired in Stage 2+)
    recall_weight_activation: float = 0.20
    recall_weight_importance: float = 0.15

    # ACT-R activation parameters
    activation_decay_rate: float = 0.5
    # Sublinear dampening exponent for access_count in ACT-R formula.
    # 1.0 = original (unbounded log growth), 0.5 = square-root dampening.
    activation_access_exponent: float = 0.5

    # Max nodes/episodes whose access_count is incremented per recall query.
    # Prevents broad queries from boosting many items simultaneously.
    recall_access_increment_limit: int = 3

    # Bonus multiplier for unconsolidated episodes (not yet extracted into graph).
    # Compensates for lack of graph traversal bonus on fresh memories.
    recall_unconsolidated_episode_boost: float = 1.3

    # MMR diversity reranking
    # Lambda: 1.0 = pure relevance, 0.0 = pure diversity, default 0.7
    recall_mmr_lambda: float = 0.7
    # Enable/disable MMR postprocessing (disable to compare A/B)
    recall_mmr_enabled: bool = True

    # Short-term memory boost for recent episodes.
    # Episodes younger than stm_window_hours get a multiplicative boost (linear decay
    # from boost_factor at age=0 to 1.0 at the window boundary).
    # Independent of recency_weight — applied on top of the hybrid score.
    episode_stm_window_hours: float = 2.0  # episodes younger than this get STM boost
    episode_stm_boost_factor: float = 1.5  # peak multiplier for brand-new episodes

    # Temporal neighbor expansion (MemMachine nucleus+neighbors)
    recall_expand_neighbors: bool = True
    recall_neighbor_window: int = 3  # default: 1 before + 2 after
    recall_neighbor_score_factor: float = 0.6

    # Supersession scoring adjustments
    recall_superseded_penalty: float = 0.5  # Multiplier for outdated nodes
    recall_superseding_boost: float = 1.2  # Multiplier for correcting nodes

    # Spreading activation
    spreading_activation_decay: float = 0.6
    spreading_activation_max_depth: int = 2
    spreading_activation_bonus_weight: float = 0.1

    # Soft-forget thresholds
    forget_activation_threshold: float = 0.05
    forget_importance_floor: float = 0.3

    # Edge reinforcement
    edge_reinforcement_delta: float = 0.05
    edge_weight_floor: float = 0.1
    edge_weight_ceiling: float = 1.5
    edge_micro_decay_factor: float = 0.998

    # Graph traversal
    recall_traversal_depth: int = 2  # hops from matched node

    # Extraction pipeline
    extraction_enabled: bool = True
    librarian_use_tools: bool = True  # False falls back to _persist_payload
    # Per-agent inference config (env: NEOCORTEX_<AGENT>_MODEL / _THINKING_EFFORT)
    # Thinking effort: minimal|low|medium|high|xhigh (maps to token budgets)
    ontology_model: str = "openai-responses:gpt-5.4-mini"
    ontology_thinking_effort: ThinkingLevel = "medium"
    extractor_model: str = "openai-responses:gpt-5.4-mini"
    extractor_thinking_effort: ThinkingLevel = "low"
    librarian_model: str = "openai-responses:gpt-5.4-mini"
    librarian_thinking_effort: ThinkingLevel = "low"
    # Local OpenAI-compatible endpoint (LiteLLM / vLLM / SGLang / Ollama).
    # Any *_model value prefixed "local:" is routed here instead of to a hosted provider.
    local_model_base_url: str | None = None
    local_model_api_key_env: str = "VLLM_API_KEY"
    local_model_temperature: float = 0.6
    local_model_top_p: float = 0.95
    local_model_temperature_nothink: float = 0.3
    local_model_top_p_nothink: float = 0.9
    local_model_timeout_s: float = 600.0
    extraction_tool_calls_limit: int = 150
    ontology_tool_calls_limit: int = 30
    ontology_max_new_types: int = 3

    # Worker concurrency & polling
    worker_concurrency: int = 4  # Max parallel extraction jobs
    worker_polling_interval: float = 1.0  # Seconds between job fetch polls

    # Domain routing (upper ontology — automatic knowledge routing to shared graphs)
    # Note: requires extraction_enabled=True (domain routing uses the job queue)
    domain_routing_enabled: bool = True
    domain_classifier_model: str = "openai-responses:gpt-5.4-mini"
    domain_classifier_thinking_effort: ThinkingLevel = "medium"
    seed_generator_thinking_effort: ThinkingLevel = "medium"
    domain_classification_threshold: float = 0.3

    # Admin
    bootstrap_admin_id: str = "admin"  # Seeded into agent_registry as admin on startup
    admin_token: str = "admin-token"  # Bootstrap admin dev token

    # Media ingestion
    media_store_path: str = "./media_store"  # Root dir for compressed media files
    media_max_upload_bytes: int = 100 * 1024 * 1024  # 100 MB upload limit
    media_description_model: str = "gemini-3-flash-preview"  # Model for multimodal description
    media_description_max_tokens: int = 8192  # Max output tokens for description

    # Feature flags
    mock_db: bool = True  # Use in-memory mock until PG is wired
